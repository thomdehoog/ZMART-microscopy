"""Log-backed polling helpers for selected state transitions.

The low-level log reader stays a single-snapshot parser. Helpers in this
module poll those snapshots for a caller-owned expected condition. They are
used narrowly by selected production confirmations and hardware validators.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from . import log_reader


@dataclass(frozen=True)
class LogPollResult:
    """Outcome of one log-backed polling wait."""

    success: bool
    value: object | None
    matched_at: float | None
    elapsed_s: float
    attempts: int
    reason: str
    diagnostics: dict


def _profile():
    from ..config import profiles

    return profiles.STATE_READERS


def wait_for_selected_job_log(
    job_name: str,
    command_started_at: float,
    *,
    timeout_s: float | None = None,
    poll_interval_s: float | None = None,
    max_age_s: float | None = None,
    parse_fn: Callable[[], log_reader.Snapshot] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    monotonic_fn: Callable[[], float] | None = None,
) -> LogPollResult:
    """Poll LAS X logs until *job_name* is selected after *command_started_at*.

    This is a log-only experiment helper. It succeeds only when the log can
    map the selected element to the target job name and the selected-element
    log timestamp is newer than the command start time.
    """

    profile = _profile()
    timeout_s = profile.selected_job_log_poll_timeout_s if timeout_s is None else timeout_s
    poll_interval_s = (
        profile.selected_job_log_poll_interval_s if poll_interval_s is None else poll_interval_s
    )
    max_age_s = profile.selected_job_log_cluster_max_age_s if max_age_s is None else max_age_s
    parse_fn = log_reader.parse_log if parse_fn is None else parse_fn
    sleep_fn = time.sleep if sleep_fn is None else sleep_fn
    monotonic_fn = time.monotonic if monotonic_fn is None else monotonic_fn

    started = monotonic_fn()
    deadline = started + timeout_s
    attempts = 0
    last_reason = "not_polled"
    base_diag = {
        "target_job": job_name,
        "command_started_at": command_started_at,
        "timeout_s": timeout_s,
        "poll_interval_s": poll_interval_s,
        "max_age_s": max_age_s,
    }
    last_diag = dict(base_diag)

    while True:
        attempts += 1
        try:
            snapshot = parse_fn()
            jobs = log_reader.get_jobs(snapshot, max_age_s=max_age_s)
            selected = log_reader.get_selected_job(snapshot, max_age_s=max_age_s)
            last_reason, selected_diag = _selected_job_reason(
                snapshot=snapshot,
                jobs=jobs,
                selected=selected,
                target_job=job_name,
                command_started_at=command_started_at,
                max_age_s=max_age_s,
            )
            last_diag = {**base_diag, **selected_diag}
        except Exception as exc:  # pragma: no cover - defensive, parser is tolerant
            last_reason = "reader_error"
            last_diag = {
                **base_diag,
                "last_reason": last_reason,
                "error": f"{type(exc).__name__}: {exc}",
            }

        if last_reason == "matched":
            return LogPollResult(
                success=True,
                value=last_diag.get("selected_job_name"),
                matched_at=last_diag.get("matched_ts"),
                elapsed_s=monotonic_fn() - started,
                attempts=attempts,
                reason="matched",
                diagnostics={**last_diag, "last_reason": "matched"},
            )

        now = monotonic_fn()
        if now >= deadline:
            return LogPollResult(
                success=False,
                value=last_diag.get("selected_job_name"),
                matched_at=None,
                elapsed_s=now - started,
                attempts=attempts,
                reason="timeout",
                diagnostics={**last_diag, "last_reason": last_reason},
            )

        sleep_s = min(poll_interval_s, max(0.0, deadline - now))
        if sleep_s > 0:
            sleep_fn(sleep_s)


def _selected_job_reason(
    *,
    snapshot: log_reader.Snapshot,
    jobs,
    selected,
    target_job: str,
    command_started_at: float,
    max_age_s: float | None,
) -> tuple[str, dict]:
    selected_name = selected.get("Name") if selected else None
    selected_ts = snapshot.selected_ts
    selected_after = selected_ts is not None and selected_ts > command_started_at
    current_block_name = snapshot.current_block_name
    current_block_ts = snapshot.current_block_ts
    current_block_after = current_block_ts is not None and current_block_ts > command_started_at
    current_block_fresh = not log_reader._too_old(
        current_block_ts, snapshot.now, max_age_s=max_age_s
    )
    cluster = _cluster_diagnostics(snapshot, max_age_s=max_age_s)
    diagnostics = {
        "target_job": target_job,
        "command_started_at": command_started_at,
        "selected_element": snapshot.selected_element,
        "selected_ts": selected_ts,
        "selected_after_command": selected_after,
        "selected_job_name": selected_name,
        "current_block_name": current_block_name,
        "current_block_id": snapshot.current_block_id,
        "current_block_ts": current_block_ts,
        "current_block_after_command": current_block_after,
        "current_block_fresh": current_block_fresh,
        "matched_ts": selected_ts,
        "jobs_count": 0 if jobs is None else len(jobs),
        "job_names": [] if jobs is None else [j.get("Name") for j in jobs],
        **cluster,
    }

    if (
        current_block_name is not None
        and current_block_ts is not None
        and current_block_after
        and current_block_fresh
    ):
        diagnostics["selected_job_name"] = current_block_name
        diagnostics["matched_ts"] = current_block_ts
        if current_block_name == target_job:
            return "matched", diagnostics
        return "selected_other_job", diagnostics

    if snapshot.selected_element is None:
        return "no_selected_element", diagnostics
    if selected_ts is None:
        return "selected_timestamp_missing", diagnostics
    if not selected_after:
        return "selected_before_command", diagnostics
    if not jobs:
        return "no_jobs", diagnostics
    if not cluster["cluster_complete"]:
        return "partial_job_cluster", diagnostics
    if cluster["ambiguous_job_names"]:
        return "ambiguous_job_cluster", diagnostics
    if not cluster["block_ids_numeric"]:
        return "selected_unmapped", diagnostics
    if selected_name is None:
        return "selected_unmapped", diagnostics
    if selected_name != target_job:
        return "selected_other_job", diagnostics
    return "matched", diagnostics


def _cluster_diagnostics(snapshot: log_reader.Snapshot, *, max_age_s):
    latest, ambiguous = log_reader._current_blocks(  # same-package diagnostic
        snapshot,
        max_age_s=max_age_s,
    )
    latest_names = set(latest.keys())
    all_names = {
        j.get("jobName") for (j, _ts) in snapshot.atl_by_block.values() if j.get("jobName")
    }
    block_ids_numeric = all(
        log_reader._block_id_int(block_id) is not None for block_id, _job, _ts in latest.values()
    )
    return {
        "current_job_names": sorted(latest_names),
        "all_job_names": sorted(all_names),
        "cluster_complete": bool(latest_names) and latest_names == all_names,
        "ambiguous_job_names": sorted(ambiguous),
        "block_ids_numeric": block_ids_numeric,
    }
