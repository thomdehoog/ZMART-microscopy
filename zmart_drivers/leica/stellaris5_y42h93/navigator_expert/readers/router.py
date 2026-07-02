"""Routed LAS X state readers.

Public functions keep the old reader return shapes by default. The backend is
a profile-controlled implementation detail: ``api``, ``log``, or ``hybrid``.
Which legs a datum offers is declared once in :mod:`capabilities`; asking a
family for a leg the datum does not have fails closed with an
``UnsupportedSource`` diagnostic. When callers need source/timestamp
diagnostics, pass ``diagnostics=True`` to receive a :class:`Reading`.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

from . import api_reader, capabilities, derived, log_reader

log = logging.getLogger(__name__)

_API_IN_FLIGHT = set()
_API_IN_FLIGHT_LOCK = threading.Lock()


@dataclass(frozen=True)
class Reading:
    """A source-tagged state reading used by routed callers."""

    value: object
    source: str
    observed_at: float | None
    age_s: float | None
    error: Exception | None = None

    def _replace_value_none(self):
        """This reading with the value stripped (kept: source/timing/error)."""
        if self.value is None:
            return self
        return Reading(
            value=None,
            source=self.source,
            observed_at=self.observed_at,
            age_s=self.age_s,
            error=self.error,
        )


def _profile():
    from ..config import profiles

    return profiles.STATE_READERS


def _plain_or_diagnostic(reading, diagnostics):
    if diagnostics:
        return reading
    return None if reading is None else reading.value


def _api_read(fn) -> Reading:
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


def _fire_api_read(fn, api_key):
    """Start one capped API read; return its result queue, or ``None`` when
    another read is already in flight on this client.

    This is the only way a concurrent API read starts. The worker thread
    holds the in-flight claim until the CAM call actually returns, even if
    the caller stops waiting - a hung read must keep blocking further API
    attempts on this client, not pile up threads behind it.
    """
    if not _claim_api_read(api_key):
        return None
    results = queue.Queue()

    def run():
        try:
            results.put(_api_read(fn))
        finally:
            _release_api_read(api_key)

    threading.Thread(target=run, name="lasx-api-read", daemon=True).start()
    return results


def _capped_api_read(api_fn, api_key, timeout_s):
    """One CAM read through the capped worker, bounded by *timeout_s*.

    Waits for the in-flight slot if another read holds it, then for the
    result. Returns the Reading, or ``None`` when the slot or the result
    did not arrive in time — a hung CAM call (modal dialog) parks in the
    daemon worker instead of blocking the caller forever.
    """
    deadline = time.monotonic() + timeout_s
    results = _fire_api_read(api_fn, api_key)
    while results is None:
        if time.monotonic() >= deadline:
            log.warning("api read not started: another read in flight past %.1fs", timeout_s)
            return None
        time.sleep(0.005)
        results = _fire_api_read(api_fn, api_key)
    try:
        return results.get(timeout=max(0.0, deadline - time.monotonic()))
    except queue.Empty:
        log.warning("api read timed out after %.1fs", timeout_s)
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


def _snapshot_read(spec, *, max_age_s, job_name=None) -> Reading:
    try:
        snapshot = log_reader.parse_log()
        if job_name is None:
            value = spec.log_fn(snapshot, max_age_s=max_age_s)
        else:
            value = spec.log_fn(snapshot, max_age_s=max_age_s, job_name=job_name)
        age_s = capabilities.age_for_snapshot(snapshot, age_key=spec.age_key, job_name=job_name)
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


def _unsupported(mode, datum) -> Reading:
    return Reading(
        value=None,
        source=mode,
        observed_at=None,
        age_s=None,
        error=capabilities.UnsupportedSource(f"datum {datum!r} has no {mode} leg"),
    )


def _routed(datum, client, *, mode, diagnostics, api_kwargs=None, job_name=None):
    spec = capabilities.spec(datum)
    profile = _profile()
    mode = mode if mode is not None else getattr(profile, spec.mode_attr)
    api_fn = None
    if spec.api_fn is not None:
        kwargs = api_kwargs or {}
        api_fn = lambda: spec.api_fn(client, **kwargs)  # noqa: E731
    log_fn = None
    if spec.log_fn is not None:
        max_age_s = (
            None if spec.log_max_age_attr is None else getattr(profile, spec.log_max_age_attr)
        )
        log_fn = lambda: _snapshot_read(  # noqa: E731
            spec, max_age_s=max_age_s, job_name=job_name
        )
    reading = _route_read(
        mode,
        datum=datum,
        api_fn=api_fn,
        log_fn=log_fn,
        trust=spec.trust,
        timeout_s=getattr(profile, spec.timeout_attr),
        api_key=_client_api_key(client),
    )
    return _plain_or_diagnostic(reading, diagnostics)


def _route_read(mode, *, datum, api_fn, log_fn, trust, timeout_s, api_key):
    # Failed reads return the error-carrying Reading (value=None) rather than
    # bare None, so diagnostics=True callers can see *why* — plain callers
    # still receive None via _plain_or_diagnostic. Untrusted (stale) log
    # readings stay None: their value must never leak to a plain caller.
    if mode == "api":
        if api_fn is None:
            return _unsupported("api", datum)
        reading = _capped_api_read(api_fn, api_key, timeout_s)
        if reading is None:
            return None
        return reading if reading.error is None else reading._replace_value_none()
    if mode == "log":
        if log_fn is None:
            return _unsupported("log", datum)
        reading = log_fn()
        if trust(reading):
            return reading
        return reading._replace_value_none() if reading.error is not None else None
    if mode == "hybrid":
        if api_fn is None and log_fn is None:
            return _unsupported("hybrid", datum)
        if log_fn is None:
            log.debug("hybrid: datum %r has no log leg; api only", datum)
            reading = _capped_api_read(api_fn, api_key, timeout_s)
            if reading is None:
                return None
            return reading if reading.error is None else reading._replace_value_none()
        if api_fn is None:
            log.debug("hybrid: datum %r has no api leg; log only", datum)
            reading = log_fn()
            if trust(reading):
                return reading
            return reading._replace_value_none() if reading.error is not None else None
        return _log_rescue_concurrent(
            api_fn=api_fn,
            log_fn=log_fn,
            trust_api=trust,
            trust_log=trust,
            timeout_s=timeout_s,
            log_grace_s=_profile().hybrid_log_grace_s,
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
    """Race both passive legs, log-preferred within a grace window.

    A trustworthy fresh log wins (immediately if it arrives first, or within
    ``log_grace_s`` of a trusted API reading); otherwise the API reading is
    the fallback. Fail-closed ``None`` when neither leg can vouch for a
    value within ``timeout_s``.
    """
    log_results = queue.Queue()

    def run_log():
        log_results.put(log_fn())

    threading.Thread(target=run_log, name="lasx-log-reader", daemon=True).start()
    api_results = _fire_api_read(api_fn, api_key)

    deadline = time.monotonic() + timeout_s
    api_candidate = None
    grace_deadline = None
    log_pending = True
    api_pending = api_results is not None
    while log_pending or api_pending:
        active_deadline = deadline if grace_deadline is None else min(deadline, grace_deadline)
        if time.monotonic() >= active_deadline:
            break
        if log_pending:
            try:
                reading = log_results.get_nowait()
            except queue.Empty:
                pass
            else:
                log_pending = False
                if trust_log(reading):
                    return reading
                if api_candidate is not None:
                    return api_candidate
        if api_pending:
            try:
                reading = api_results.get_nowait()
            except queue.Empty:
                pass
            else:
                api_pending = False
                if trust_api(reading):
                    if not log_pending:
                        return reading
                    api_candidate = reading
                    grace_deadline = time.monotonic() + log_grace_s
        if log_pending or api_pending:
            time.sleep(0.005)
    # Deadline hit: a result that landed during the final sleep is already
    # in its queue — drain once instead of dropping it.
    if log_pending:
        try:
            reading = log_results.get_nowait()
        except queue.Empty:
            pass
        else:
            if trust_log(reading):
                return reading
    if api_pending and api_results is not None:
        try:
            reading = api_results.get_nowait()
        except queue.Empty:
            pass
        else:
            if trust_api(reading) and api_candidate is None:
                api_candidate = reading
    return api_candidate


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
    return _routed("scan_status", client, mode=mode, diagnostics=diagnostics)


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
    return _routed(
        "job_settings",
        client,
        mode=mode,
        diagnostics=diagnostics,
        api_kwargs=dict(
            job_name=job_name,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
        ),
        job_name=job_name,
    )


def get_hardware_info(
    client,
    timeout=1.0,
    poll_interval=0.01,
    max_retries=3,
    *,
    mode=None,
    diagnostics=False,
):
    return _routed(
        "hardware_info",
        client,
        mode=mode,
        diagnostics=diagnostics,
        api_kwargs=dict(
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
        ),
    )


def get_xy(
    client,
    timeout=1.0,
    poll_interval=0.01,
    max_retries=3,
    *,
    mode=None,
    diagnostics=False,
):
    return _routed(
        "xy",
        client,
        mode=mode,
        diagnostics=diagnostics,
        api_kwargs=dict(
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
        ),
    )


def read_zwide_um(client, job_name, *, mode=None):
    """Z-wide position (um) from the job settings, or None when unreadable.

    Like every routed reader this fails closed with None instead of raising.
    """
    settings = get_job_settings(client, job_name, mode=mode)
    if not settings:
        log.warning("read_zwide_um: could not read job settings for '%s'", job_name)
        return None
    return derived.zwide_um_from_settings(settings)


def get_jobs(
    client,
    timeout=1.0,
    poll_interval=0.01,
    max_retries=3,
    *,
    mode=None,
    diagnostics=False,
):
    return _routed(
        "jobs",
        client,
        mode=mode,
        diagnostics=diagnostics,
        api_kwargs=dict(
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
        ),
    )


def get_job_by_name(client, job_name, *, mode=None, diagnostics=False, **kwargs):
    jobs_reading = get_jobs(
        client,
        mode=mode,
        diagnostics=True,
        **kwargs,
    )
    value = None if jobs_reading is None else derived.job_by_name(jobs_reading.value, job_name)
    reading = _derive(jobs_reading, value)
    return _plain_or_diagnostic(reading, diagnostics)


def get_selected_job(client, *, mode=None, diagnostics=False, **kwargs):
    return _routed(
        "selected_job",
        client,
        mode=mode,
        diagnostics=diagnostics,
        api_kwargs=kwargs,
    )


def get_fov(client, job_name, *, mode=None, diagnostics=False, **kwargs):
    settings_reading = get_job_settings(
        client,
        job_name,
        mode=mode,
        diagnostics=True,
        **kwargs,
    )
    value = None if settings_reading is None else derived.fov_from_settings(settings_reading.value)
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
    value = (
        None if settings_reading is None else derived.base_fov_from_settings(settings_reading.value)
    )
    reading = _derive(settings_reading, value)
    return _plain_or_diagnostic(reading, diagnostics)


def get_lasx_settings(settings_path=None):
    return api_reader.get_lasx_settings(settings_path=settings_path)


def get_pending_dialog(*, diagnostics=False):
    snapshot = log_reader.parse_msgbox_log()
    value = log_reader.get_pending_dialog(snapshot)
    age_s = capabilities.age_for_snapshot(snapshot, age_key="dialog")
    observed_at = None if age_s is None else snapshot.now - age_s
    reading = Reading(
        value=value,
        source="log",
        observed_at=observed_at,
        age_s=age_s,
        error=None,
    )
    return _plain_or_diagnostic(reading, diagnostics)
