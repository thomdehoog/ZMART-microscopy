"""Alternating API/log change-wait reader.

``wait_for_change`` answers one question after a command was fired: *did the
state visibly change?* It alternates the CAM API and the LAS X log until one
source observes a value that differs from that same source's pre-command
baseline, or a profile-configured timeout expires (``unconfirmed``).

This detects *effect*, not *arrival*: for continuous state (XY) the first
changed reading means the move started, not that it reached the target. The
optional ``target``/``tolerance`` are therefore reported on the result
(``matches_target`` / ``within_tolerance`` / ``target_delta``) and never gate
acceptance. Callers that must gate on a target keep using the confirmation
layer (``core/confirmations.py``).

Safety rules carried over from the routed readers (see
``docs/WHY_HYBRID_READERS_20260605.md``):

- The CAM API read is blocking and non-cancellable, so the API leg runs in a
  capped worker thread (``router._claim_api_read``). A hung API read degrades
  the wait to log-only; it never freezes the loop.
- Change is judged per source against that source's own baseline. Cross-source
  comparison only feeds the ``sources_agree`` report - representation and lag
  differences between API and log must not fabricate a change by themselves.
  The API has no independent event timestamp, so callers that rely on the API
  leg must capture the baseline after any previous command's API readback has
  converged.
- A log observation counts only when its log timestamp is newer than the
  baseline; a differing value on a pre-baseline line is leaked state.
- ``None`` / NaN / empty / ``"Unknown"`` values are never a change.
- On timeout the result is ``unconfirmed`` - never a stale or guessed value.

All default tunables live in ``profiles.STATE_READERS`` (``change_wait_*``).
"""

from __future__ import annotations

import math
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import api_reader, log_reader, router


@dataclass(frozen=True)
class ChangeBaseline:
    """Per-source pre-command readings a change is judged against."""

    datum: str
    taken_at: float
    api: router.Reading | None
    log: router.Reading | None
    diagnostics: dict


@dataclass(frozen=True)
class ChangeWaitResult:
    """Outcome of one change-wait, with full debugging surface."""

    success: bool
    outcome: str                       # "changed" | "unconfirmed"
    value: object | None
    source: str | None                 # "api" | "log"
    observed_at: float | None
    elapsed_s: float
    api_attempts: int
    log_attempts: int
    matches_target: bool | None
    within_tolerance: bool | None
    target_delta: float | None
    sources_agree: bool | None
    reason: str
    diagnostics: dict


@dataclass(frozen=True)
class _DatumSpec:
    """How one datum is read and compared across both sources."""

    api_fn: Callable                   # (client) -> raw value
    log_fn: Callable                   # (snapshot) -> (raw value, observed_at)
    key_fn: Callable                   # (raw value) -> comparable key or None
    numeric: bool = False


def _profile():
    from ..core import profiles
    return profiles.STATE_READERS


def _selected_job_key(value):
    if not isinstance(value, dict):
        return None
    name = value.get("Name")
    if not isinstance(name, str) or not name.strip() or name == "Unknown":
        return None
    return name


def _xy_key(value):
    if not isinstance(value, dict):
        return None
    try:
        key = (float(value["x_um"]), float(value["y_um"]))
    except (KeyError, TypeError, ValueError):
        return None
    if any(math.isnan(c) or math.isinf(c) for c in key):
        return None
    return key


def _log_selected_job(snapshot):
    # CurrentBlock is the measured fast-and-correct selection signal
    # (~0.2 s after a switch). SetCurrentSelectedElementID is an intent echo,
    # not applied state, so it is deliberately not used for change detection.
    if snapshot.current_block_name:
        return {"Name": snapshot.current_block_name}, snapshot.current_block_ts
    return None, None


def _log_xy(snapshot):
    value = log_reader.get_xy(snapshot, max_age_s=None)
    observed_at = None if value is None else snapshot.xy_ts
    return value, observed_at


_DATUMS = {
    "selected_job": _DatumSpec(
        api_fn=lambda client: api_reader.get_selected_job(client),
        log_fn=_log_selected_job,
        key_fn=_selected_job_key,
    ),
    "xy": _DatumSpec(
        api_fn=lambda client: api_reader.get_xy(client),
        log_fn=_log_xy,
        key_fn=_xy_key,
        numeric=True,
    ),
}


def _spec(datum):
    spec = _DATUMS.get(datum)
    if spec is None:
        raise ValueError(
            f"unknown change-wait datum {datum!r}; known: {sorted(_DATUMS)}")
    return spec


def _key_delta(key, other):
    """Distance between two keys: max component delta for numeric tuples,
    ``None`` for equal discrete keys, ``inf`` for differing discrete keys."""
    if isinstance(key, tuple) and isinstance(other, tuple) \
            and len(key) == len(other):
        return max(abs(a - b) for a, b in zip(key, other, strict=True))
    return None if key == other else math.inf


def _change_delta(spec, profile, override):
    if override is not None:
        return override
    if spec.numeric:
        return profile.change_wait_xy_min_delta_um
    return 0.0


def _target_key(datum, target):
    if target is None:
        return None
    if datum == "xy":
        if not isinstance(target, (tuple, list)) or len(target) != 2:
            raise ValueError("xy change-wait target must be a 2-item sequence")
        try:
            key = tuple(float(c) for c in target)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "xy change-wait target must contain finite numbers") from exc
        if any(math.isnan(c) or math.isinf(c) for c in key):
            raise ValueError(
                "xy change-wait target must contain finite numbers")
        return key
    if datum == "selected_job":
        if not isinstance(target, str) or not target.strip() or target == "Unknown":
            raise ValueError(
                "selected_job change-wait target must be a non-empty name")
        return target
    raise ValueError(f"unknown change-wait datum {datum!r}")


def _log_reading(spec, parse_fn):
    try:
        snapshot = parse_fn()
        value, observed_at = spec.log_fn(snapshot)
        age_s = (
            None if observed_at is None
            else max(0.0, snapshot.now - observed_at)
        )
        return router.Reading(
            value=value, source="log",
            observed_at=observed_at, age_s=age_s, error=None)
    except Exception as exc:
        return router.Reading(
            value=None, source="log",
            observed_at=None, age_s=None, error=exc)


def _fire_api_read(fn, api_key):
    """Start one capped API read; return its result queue, or ``None`` when
    another read is already in flight on this client.

    The worker thread holds the in-flight claim until the CAM call actually
    returns, even if the caller stops waiting - a hung read must keep
    blocking further API attempts on this client, not pile up threads.
    """
    if not router._claim_api_read(api_key):
        return None
    results = queue.Queue()

    def run():
        try:
            results.put(router._api_read(fn))
        finally:
            router._release_api_read(api_key)

    threading.Thread(
        target=run, name="lasx-change-wait-api", daemon=True).start()
    return results


def _validated(reading, key_fn):
    """Collapse a reading to ``(reading, "ok")`` or ``(None, reason)``."""
    if reading is None:
        return None, "api_timeout"
    if reading.error is not None:
        return None, f"{reading.source}_error"
    if key_fn(reading.value) is None:
        return None, "invalid_value"
    return reading, "ok"


def read_change_baseline(client, datum, *, parse_fn=None, api_timeout_s=None):
    """Capture one pre-command reading per source for *datum*.

    Call this BEFORE firing the command whose effect ``wait_for_change``
    should detect. A source whose baseline is missing or invalid cannot
    signal a change later (fail closed); the reason is recorded in
    ``diagnostics``.
    """
    spec = _spec(datum)
    profile = _profile()
    api_timeout_s = (
        profile.change_wait_baseline_api_timeout_s
        if api_timeout_s is None else api_timeout_s
    )
    parse_fn = log_reader.parse_log if parse_fn is None else parse_fn
    taken_at = time.time()

    api_queue = _fire_api_read(
        lambda: spec.api_fn(client), router._client_api_key(client))
    if api_queue is None:
        api_reading, api_reason = None, "api_in_flight"
    else:
        try:
            api_reading = api_queue.get(timeout=api_timeout_s)
        except queue.Empty:
            api_reading = None
        api_reading, api_reason = _validated(api_reading, spec.key_fn)

    log_reading, log_reason = _validated(
        _log_reading(spec, parse_fn), spec.key_fn)

    return ChangeBaseline(
        datum=datum,
        taken_at=taken_at,
        api=api_reading,
        log=log_reading,
        diagnostics={
            "datum": datum,
            "api_timeout_s": api_timeout_s,
            "api_reason": api_reason,
            "log_reason": log_reason,
        },
    )


def wait_for_change(
    client,
    datum,
    baseline=None,
    *,
    target=None,
    tolerance=None,
    command_started_at=None,
    timeout_s=None,
    loop_interval_s=None,
    api_retry_interval_s=None,
    min_delta=None,
    parse_fn=None,
    sleep_fn=None,
):
    """Alternate API and log reads until *datum* differs from *baseline*.

    Without an explicit *baseline* one is captured at entry; that only
    detects changes that happen AFTER this call, so callers should normally
    pass a ``read_change_baseline`` result taken before their command fired.
    When provided, ``command_started_at`` is the wall-clock timestamp captured
    immediately before firing the command. The log leg rejects observations at
    or before the later of baseline capture and command start, so a bad caller
    timestamp cannot weaken the stale-log guard.
    """
    spec = _spec(datum)
    profile = _profile()
    target_key = _target_key(datum, target)
    timeout_s = (
        profile.change_wait_timeout_s if timeout_s is None else timeout_s)
    loop_interval_s = (
        profile.change_wait_loop_interval_s
        if loop_interval_s is None else loop_interval_s
    )
    api_retry_interval_s = (
        profile.change_wait_api_retry_interval_s
        if api_retry_interval_s is None else api_retry_interval_s
    )
    min_delta = _change_delta(spec, profile, min_delta)
    parse_fn = log_reader.parse_log if parse_fn is None else parse_fn
    sleep_fn = time.sleep if sleep_fn is None else sleep_fn

    if baseline is None:
        baseline = read_change_baseline(client, datum, parse_fn=parse_fn)
    if baseline.datum != datum:
        raise ValueError(
            f"baseline datum {baseline.datum!r} does not match {datum!r}")
    log_boundary = baseline.taken_at
    if command_started_at is not None:
        log_boundary = max(log_boundary, command_started_at)

    api_key = router._client_api_key(client)
    baseline_keys = {
        "api": None if baseline.api is None else spec.key_fn(baseline.api.value),
        "log": None if baseline.log is None else spec.key_fn(baseline.log.value),
    }

    started = time.monotonic()
    deadline = started + timeout_s
    api_queue = None
    api_due_at = started
    api_attempts = 0
    log_attempts = 0
    api_skips = 0
    trace = []
    last_valid = {}
    last_current = {}
    last_reasons = {"api": "not_attempted", "log": "not_attempted"}

    def evaluate(source, reading):
        entry = {
            "t_s": round(time.monotonic() - started, 4),
            "source": source,
            "valid": False,
            "changed": False,
        }
        trace.append(entry)
        if reading.error is not None:
            entry["error"] = f"{type(reading.error).__name__}: {reading.error}"
            last_reasons[source] = "error"
            return False
        key = spec.key_fn(reading.value)
        if key is None:
            last_reasons[source] = "invalid_value"
            return False
        entry["valid"] = True
        entry["key"] = key
        entry["observed_at"] = reading.observed_at
        last_valid[source] = {
            "key": key,
            "value": reading.value,
            "observed_at": reading.observed_at,
        }
        if baseline_keys[source] is None:
            last_reasons[source] = "no_baseline"
            return False
        if source == "log":
            if reading.observed_at is None:
                last_reasons[source] = "no_timestamp"
                return False
            if reading.observed_at <= log_boundary:
                last_reasons[source] = "observed_before_log_boundary"
                return False
        last_current[source] = {
            "key": key,
            "value": reading.value,
            "observed_at": reading.observed_at,
        }
        delta = _key_delta(key, baseline_keys[source])
        if delta is None or delta <= min_delta:
            last_reasons[source] = "unchanged"
            return False
        entry["changed"] = True
        last_reasons[source] = "changed"
        return True

    winner = None
    while True:
        now = time.monotonic()
        if api_queue is None and now >= api_due_at:
            api_queue = _fire_api_read(lambda: spec.api_fn(client), api_key)
            if api_queue is not None:
                api_attempts += 1
            else:
                api_skips += 1
                api_due_at = now + api_retry_interval_s
        if api_queue is not None:
            try:
                reading = api_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                api_queue = None
                api_due_at = time.monotonic() + api_retry_interval_s
                if evaluate("api", reading):
                    winner = ("api", reading)
                    break
        log_attempts += 1
        reading = _log_reading(spec, parse_fn)
        if evaluate("log", reading):
            winner = ("log", reading)
            break
        now = time.monotonic()
        if now >= deadline:
            break
        sleep_fn(min(loop_interval_s, deadline - now))

    elapsed_s = time.monotonic() - started
    diagnostics = {
        "datum": datum,
        "params": {
            "timeout_s": timeout_s,
            "loop_interval_s": loop_interval_s,
            "api_retry_interval_s": api_retry_interval_s,
            "min_delta": min_delta,
        },
        "baseline": {
            "taken_at": baseline.taken_at,
            "command_started_at": command_started_at,
            "log_boundary": log_boundary,
            "api_key": baseline_keys["api"],
            "log_key": baseline_keys["log"],
            **baseline.diagnostics,
        },
        "last_valid": last_valid,
        "last_current": last_current,
        "last_reasons": dict(last_reasons),
        "api_skips": api_skips,
        "api_pending_at_exit": api_queue is not None,
        "trace": trace,
    }

    if winner is None:
        return ChangeWaitResult(
            success=False,
            outcome="unconfirmed",
            value=None,
            source=None,
            observed_at=None,
            elapsed_s=elapsed_s,
            api_attempts=api_attempts,
            log_attempts=log_attempts,
            matches_target=None,
            within_tolerance=None,
            target_delta=None,
            sources_agree=None,
            reason="timeout",
            diagnostics=diagnostics,
        )

    source, reading = winner
    key = spec.key_fn(reading.value)
    other = "log" if source == "api" else "api"
    other_key = last_current.get(other, {}).get("key")
    if other_key is None:
        sources_agree = None
    else:
        agreement_delta = tolerance if spec.numeric and tolerance is not None else min_delta
        delta = _key_delta(key, other_key)
        sources_agree = delta is None or delta <= agreement_delta

    matches_target = None
    within_tolerance = None
    target_delta = None
    if target_key is not None:
        target_delta = _key_delta(key, target_key)
        if spec.numeric:
            if tolerance is not None:
                within_tolerance = (
                    target_delta is not None and target_delta <= tolerance)
                matches_target = within_tolerance
        else:
            matches_target = target_delta is None

    return ChangeWaitResult(
        success=True,
        outcome="changed",
        value=reading.value,
        source=source,
        observed_at=reading.observed_at,
        elapsed_s=elapsed_s,
        api_attempts=api_attempts,
        log_attempts=log_attempts,
        matches_target=matches_target,
        within_tolerance=within_tolerance,
        target_delta=target_delta,
        sources_agree=sources_agree,
        reason="changed",
        diagnostics=diagnostics,
    )
