"""_job_state.py -- verified job transitions.

Every job switch in the workflow goes through ensure_job_state().
No other module calls drv.select_job directly.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import navigator_expert.driver as drv

if TYPE_CHECKING:
    from .context import Context


def ensure_job_state(ctx: Context, job: str) -> None:
    """Select job, verify objective slot, settle on actual change.

    If ctx.current_job == job, this is a no-op (already verified
    on the transition that set it). On a real transition: select,
    verify slot, settle, update ctx.current_job.
    """
    if ctx.current_job == job:
        return

    cfg = ctx.cfg
    expected_slot = _expected_slot(ctx, job)

    # Invalidate cache before touching LAS X — if anything below fails,
    # we must not skip re-verification on the next call.
    ctx.current_job = ""

    r = drv.select_job(ctx.client, job)
    if not r or not r.get("success"):
        raise RuntimeError(f"select_job({job!r}) failed: {r!r}")

    actual_slot = _read_objective_slot(ctx.client, job)
    if actual_slot != expected_slot:
        raise RuntimeError(
            f"Job {job!r} reports objective slot {actual_slot}, "
            f"expected {expected_slot}. Check LAS X job configuration.")

    time.sleep(cfg.settle_after_job_switch_s)
    ctx.current_job = job
    print(f"[job] {job!r} selected (slot {actual_slot})")


def _expected_slot(ctx: Context, job: str) -> int:
    """Map job name to expected objective slot. Hard error on unknown job."""
    cfg = ctx.cfg
    if job == cfg.acquisition_job or job == cfg.af_job:
        return ctx.source_slot
    if job == cfg.target_job:
        return ctx.target_slot
    raise ValueError(
        f"Job {job!r} is not acquisition_job, target_job, or af_job. "
        f"Cannot determine expected objective slot.")


def _read_objective_slot(client, job: str) -> int:
    """Read objective slot from job settings with defensive parsing."""
    settings = drv.get_job_settings(client, job)
    if not settings:
        raise RuntimeError(
            f"get_job_settings({job!r}) returned nothing.")
    objective = settings.get("objective")
    if not objective or not isinstance(objective, dict):
        raise RuntimeError(
            f"Job {job!r} has no 'objective' in settings: "
            f"{settings!r}")
    slot = objective.get("slotIndex")
    if slot is None:
        raise RuntimeError(
            f"Job {job!r} has no 'slotIndex' in objective settings: "
            f"{objective!r}")
    try:
        return int(slot)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"Job {job!r} has non-integer slotIndex {slot!r}: {exc}"
        ) from exc
