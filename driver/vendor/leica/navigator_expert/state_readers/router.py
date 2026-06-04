"""Routed LAS X state readers.

Public functions keep the old reader return shapes by default. The backend is a
profile-controlled implementation detail: API, log, or concurrent API+log. When
callers need source/timestamp diagnostics, pass ``diagnostics=True`` to receive
a :class:`Reading`.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import api_reader, derived, log_reader

log = logging.getLogger(__name__)

_API_IN_FLIGHT = set()
_API_IN_FLIGHT_LOCK = threading.Lock()


@dataclass(frozen=True)
class Reading:
    """A source-tagged state reading used by routed callers."""

    value: object
    source: str
    observed_at: Optional[float]
    age_s: Optional[float]
    error: Exception | None = None


def _profile():
    from ..core import profiles
    return profiles.STATE_READERS


def _mode(explicit, profile_attr):
    return explicit if explicit is not None else getattr(_profile(), profile_attr)


def _plain_or_diagnostic(reading, diagnostics):
    if diagnostics:
        return reading
    return None if reading is None else reading.value


def _api_read(fn: Callable[[], object]) -> Reading:
    try:
        value = fn()
        # API has no independent freshness timestamp. observed_at/age_s mark
        # call completion, not proof that LAS X returned newly-produced state.
        observed_at = time.time()
        return Reading(
            value=value,
            source="api",
            observed_at=observed_at,
            age_s=0.0,
            error=None,
        )
    except Exception as exc:
        log.debug("api reader failed", exc_info=True)
        return Reading(
            value=None,
            source="api",
            observed_at=time.time(),
            age_s=None,
            error=exc,
        )


def _snapshot_read(fn, *, age_key=None, job_name=None) -> Reading:
    try:
        snapshot = log_reader.parse_log()
        value = fn(snapshot)
        age_s = _age_for_snapshot(snapshot, age_key=age_key, job_name=job_name)
        observed_at = None if age_s is None else snapshot.now - age_s
        return Reading(
            value=value,
            source="log",
            observed_at=observed_at,
            age_s=age_s,
            error=None,
        )
    except Exception as exc:
        log.debug("log reader failed", exc_info=True)
        return Reading(
            value=None,
            source="log",
            observed_at=time.time(),
            age_s=None,
            error=exc,
        )


def _age_for_snapshot(snapshot, *, age_key=None, job_name=None):
    ages = log_reader.ages(snapshot)
    if job_name is not None:
        return ages.get("jobs", {}).get(job_name)
    if age_key == "jobs":
        values = [
            age for age in (ages.get("jobs") or {}).values()
            if age is not None
        ]
        selected_age = ages.get("selected")
        if selected_age is not None:
            values.append(selected_age)
        return max(values) if values else None
    return ages.get(age_key)


def _trust_present(reading: Reading) -> bool:
    return reading.error is None and reading.value is not None


def _trust_status(reading: Reading) -> bool:
    return _trust_present(reading) and reading.value != "Unknown"


def _route_read(
    mode,
    *,
    api_fn,
    log_fn,
    trust_api=_trust_present,
    trust_log=_trust_present,
    timeout_s=2.0,
    api_key=None,
):
    if mode == "api":
        reading = _api_read(api_fn)
        return reading if reading.error is None else None
    if mode == "log":
        reading = log_fn()
        return reading if trust_log(reading) else None
    if mode == "both":
        return _log_rescue_concurrent(
            api_fn=api_fn,
            log_fn=log_fn,
            trust_api=trust_api,
            trust_log=trust_log,
            timeout_s=timeout_s,
            log_grace_s=_profile().both_log_grace_s,
            api_key=api_key,
        )
    raise ValueError(f"unknown state-reader mode {mode!r}")


def _log_rescue_concurrent(
    *,
    api_fn,
    log_fn,
    trust_api,
    trust_log,
    timeout_s,
    log_grace_s,
    api_key,
):
    results = queue.Queue()
    start_api = _claim_api_read(api_key)

    def run_api():
        try:
            results.put(("api", _api_read(api_fn)))
        finally:
            _release_api_read(api_key)

    def run_log():
        results.put(("log", log_fn()))

    threads = [
        threading.Thread(target=run_log, name="lasx-log-reader", daemon=True),
    ]
    if start_api:
        threads.insert(
            0,
            threading.Thread(target=run_api, name="lasx-api-reader", daemon=True),
        )
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + timeout_s
    api_candidate = None
    api_grace_deadline = None
    remaining = len(threads)
    while remaining:
        active_deadline = deadline
        if api_candidate is not None and api_grace_deadline is not None:
            active_deadline = min(active_deadline, api_grace_deadline)
        wait_s = max(0.0, active_deadline - time.monotonic())
        if wait_s <= 0:
            break
        try:
            source, reading = results.get(timeout=wait_s)
        except queue.Empty:
            break
        remaining -= 1
        if source == "log" and trust_log(reading):
            return reading
        if source == "log" and api_candidate is not None:
            return api_candidate
        if source == "api" and trust_api(reading):
            api_candidate = reading
            api_grace_deadline = time.monotonic() + log_grace_s
            if remaining == 0:
                return api_candidate
            continue
    if api_candidate is not None:
        return api_candidate
    return None


def _claim_api_read(api_key):
    if api_key is None:
        return True
    with _API_IN_FLIGHT_LOCK:
        if api_key in _API_IN_FLIGHT:
            return False
        _API_IN_FLIGHT.add(api_key)
        return True


def _release_api_read(api_key):
    if api_key is None:
        return
    with _API_IN_FLIGHT_LOCK:
        _API_IN_FLIGHT.discard(api_key)


def _client_api_key(client):
    return id(client)


def _derive(reading, value):
    if reading is None:
        return None
    return Reading(
        value=value,
        source=reading.source,
        observed_at=reading.observed_at,
        age_s=reading.age_s,
        error=reading.error,
    )


def get_scan_status(client, *, mode=None, diagnostics=False):
    profile = _profile()
    reading = _route_read(
        _mode(mode, "scan_status_mode"),
        api_fn=lambda: api_reader.get_scan_status(client),
        log_fn=lambda: _snapshot_read(
            lambda snapshot: log_reader.get_scan_status(
                snapshot,
                max_age_s=profile.scan_status_log_max_age_s,
            ),
            age_key="scan_status",
        ),
        trust_api=_trust_status,
        trust_log=_trust_status,
        timeout_s=profile.scan_status_timeout_s,
        api_key=_client_api_key(client),
    )
    return _plain_or_diagnostic(reading, diagnostics)


def ping(client):
    return api_reader.ping(client)


def get_job_settings(
    client,
    job_name,
    timeout=1.0,
    poll_interval=0.01,
    max_retries=3,
    *,
    mode=None,
    diagnostics=False,
):
    profile = _profile()
    reading = _route_read(
        _mode(mode, "job_settings_mode"),
        api_fn=lambda: api_reader.get_job_settings(
            client,
            job_name,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
        ),
        log_fn=lambda: _snapshot_read(
            lambda snapshot: log_reader.get_job_settings(
                job_name,
                snapshot,
                max_age_s=profile.job_settings_log_max_age_s,
            ),
            job_name=job_name,
        ),
        timeout_s=profile.job_settings_timeout_s,
        api_key=_client_api_key(client),
    )
    return _plain_or_diagnostic(reading, diagnostics)


def get_hardware_info(
    client,
    timeout=1.0,
    poll_interval=0.01,
    max_retries=3,
    *,
    mode=None,
    diagnostics=False,
):
    profile = _profile()
    reading = _route_read(
        _mode(mode, "hardware_info_mode"),
        api_fn=lambda: api_reader.get_hardware_info(
            client,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
        ),
        log_fn=lambda: _snapshot_read(
            lambda snapshot: log_reader.get_hardware_info(
                snapshot,
                max_age_s=profile.hardware_info_log_max_age_s,
            ),
            age_key="hardware_info",
        ),
        timeout_s=profile.hardware_info_timeout_s,
        api_key=_client_api_key(client),
    )
    return _plain_or_diagnostic(reading, diagnostics)


def get_xy(
    client,
    timeout=1.0,
    poll_interval=0.01,
    max_retries=3,
    *,
    mode=None,
    diagnostics=False,
):
    profile = _profile()
    reading = _route_read(
        _mode(mode, "xy_mode"),
        api_fn=lambda: api_reader.get_xy(
            client,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
        ),
        log_fn=lambda: _snapshot_read(
            lambda snapshot: log_reader.get_xy(
                snapshot,
                max_age_s=profile.xy_log_max_age_s,
            ),
            age_key="xy",
        ),
        timeout_s=profile.xy_timeout_s,
        api_key=_client_api_key(client),
    )
    return _plain_or_diagnostic(reading, diagnostics)


def read_zwide_um(client, job_name, *, mode=None):
    settings = get_job_settings(client, job_name, mode=mode)
    if not settings:
        raise RuntimeError(f"could not read job settings for '{job_name}'")
    from ..core.settings import make_changeable_copy
    ch = make_changeable_copy(settings)
    if not ch or "zPosition" not in ch:
        raise RuntimeError(
            "zPosition not in job settings - LAS X version mismatch?"
        )
    val = ch["zPosition"].get("z-wide")
    if isinstance(val, dict):
        val = val.get("position")
    if val is None:
        raise RuntimeError(f"z-wide readback missing; got {ch['zPosition']!r}")
    return float(val)


def get_jobs(
    client,
    timeout=1.0,
    poll_interval=0.01,
    max_retries=3,
    *,
    mode=None,
    diagnostics=False,
):
    profile = _profile()
    reading = _route_read(
        _mode(mode, "jobs_mode"),
        api_fn=lambda: api_reader.get_jobs(
            client,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
        ),
        log_fn=lambda: _snapshot_read(
            lambda snapshot: log_reader.get_jobs(
                snapshot,
                max_age_s=profile.jobs_log_max_age_s,
            ),
            age_key="jobs",
        ),
        timeout_s=profile.jobs_timeout_s,
        api_key=_client_api_key(client),
    )
    return _plain_or_diagnostic(reading, diagnostics)


def get_job_by_name(client, job_name, *, mode=None, diagnostics=False, **kwargs):
    jobs_reading = get_jobs(
        client,
        mode=mode,
        diagnostics=True,
        **kwargs,
    )
    value = None if jobs_reading is None else derived.job_by_name(
        jobs_reading.value, job_name)
    reading = _derive(jobs_reading, value)
    return _plain_or_diagnostic(reading, diagnostics)


def get_selected_job(client, *, mode=None, diagnostics=False, **kwargs):
    jobs_reading = get_jobs(
        client,
        mode=mode,
        diagnostics=True,
        **kwargs,
    )
    value = None if jobs_reading is None else derived.selected_job(
        jobs_reading.value)
    reading = _derive(jobs_reading, value)
    return _plain_or_diagnostic(reading, diagnostics)


def get_fov(client, job_name, *, mode=None, diagnostics=False, **kwargs):
    settings_reading = get_job_settings(
        client,
        job_name,
        mode=mode,
        diagnostics=True,
        **kwargs,
    )
    value = None if settings_reading is None else derived.fov_from_settings(
        settings_reading.value)
    reading = _derive(settings_reading, value)
    return _plain_or_diagnostic(reading, diagnostics)


def get_base_fov(client, job_name, *, mode=None, diagnostics=False, **kwargs):
    settings_reading = get_job_settings(
        client,
        job_name,
        mode=mode,
        diagnostics=True,
        **kwargs,
    )
    value = None if settings_reading is None else derived.base_fov_from_settings(
        settings_reading.value)
    reading = _derive(settings_reading, value)
    return _plain_or_diagnostic(reading, diagnostics)


def get_lasx_settings(settings_path=None):
    return api_reader.get_lasx_settings(settings_path=settings_path)


def get_pending_dialog(*, diagnostics=False):
    snapshot = log_reader.parse_msgbox_log()
    value = log_reader.get_pending_dialog(snapshot)
    age_s = _age_for_snapshot(snapshot, age_key="dialog")
    observed_at = None if age_s is None else snapshot.now - age_s
    reading = Reading(
        value=value,
        source="log",
        observed_at=observed_at,
        age_s=age_s,
        error=None,
    )
    return _plain_or_diagnostic(reading, diagnostics)
