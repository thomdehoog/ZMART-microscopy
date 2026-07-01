"""
Command wrappers.
=================
Public ``move_xy``, ``move_z``, ``set_objective``, ``load_experiment``,
``run_snap``, ``run_experiment``. Each follows the three-phase pattern:

    Phase A - pre-checks: input validation, unit conversion, limit checks.
    Phase B - backbone: build a synchronous ``fire_fn`` (which awaits one RPC via
        ``client.submit`` and classifies any gRPC error) plus a target-bound
        ``confirm_fn``, then call ``confirm_and_fire``.
    Phase C - post-processing: attach extra data (position / index / output_name).

Unit rule: the public API is micrometers; conversion to meters happens HERE, in
the request builder, and nowhere else on the write path.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial

from ..config.profiles import FOCUS_MOVE, OBJECTIVE, RUN_EXPERIMENT, SNAP, STAGE_MOVE
from ..motion.limits import _check_xy_limits, _check_z_limits
from ..readers.api_reader import _attr
from ..utils import _make_log_entry, _make_timing, to_um, um_to_m
from .confirmations import confirm_acquire, confirm_move_xy, confirm_move_z, confirm_objective
from .dispatch import confirm_and_fire
from .errors import classify_grpc_error
from .objectives import resolve_objective_index

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Experiment:
    """A loaded ZEN experiment handle (the ``experiment_id`` + its name)."""

    experiment_id: str
    name: str


def _profile_value(profile, name, override=None):
    """Return an explicit override or the command profile value."""
    return override if override is not None else getattr(profile, name)


def _exp_id(experiment):
    """Accept an Experiment, a raw id string, or anything with .experiment_id."""
    return getattr(experiment, "experiment_id", experiment)


def _rpc_fire(client, label, coro_factory, *, call_timeout):
    """Build a synchronous ``fire_fn`` that awaits one RPC and classifies errors.

    ``coro_factory`` must return a FRESH coroutine each call (a coroutine cannot
    be awaited twice), so retries re-build the request.
    """

    def fire_fn():
        try:
            value = client.submit(coro_factory(), timeout=call_timeout)
        except Exception as exc:  # noqa: BLE001 - classified, not swallowed
            cls = classify_grpc_error(exc)
            level = "warning" if cls["transient"] else "error"
            return {
                "success": False,
                "error": cls["error"],
                "transient": cls["transient"],
                "value": None,
                "logs": [_make_log_entry(level, f"{label}: {cls['error']}")],
            }
        return {"success": True, "error": None, "transient": None, "value": value, "logs": []}

    return fire_fn


def _dispatch(client, description, profile, *, fire_fn, confirm_fn=None, max_retries=None):
    """Uniform backbone call: apply profile tuning to ``confirm_and_fire``."""
    return confirm_and_fire(
        client,
        description,
        fire_fn=fire_fn,
        confirm_fn=confirm_fn,
        max_retries=_profile_value(profile, "max_retries", max_retries),
        max_confirm_attempts=profile.max_confirm_attempts,
        refire_on_unconfirmed=profile.refire_on_unconfirmed,
        retry_backoff=profile.retry_backoff,
        retry_escalate=profile.retry_escalate,
        success_on_unconfirmed=profile.success_on_unconfirmed,
    )


# =============================================================================
# Stage / focus
# =============================================================================


def move_xy(client, x, y, unit="um", *, max_retries=None, tolerance=None):
    """Move the XY stage to an absolute position.

    Args:
        x, y: target coordinates in ``unit`` ('um' | 'mm' | 'm').
        tolerance: confirmation tolerance in micrometers (profile default if None).

    Returns:
        Result dict with a ``position`` key ({x_m,y_m,x_um,y_um}).
    """
    # Phase A: convert to µm and enforce limits (µm), before any meters/RPC.
    x_um, y_um = to_um(x, unit), to_um(y, unit)
    try:
        _check_xy_limits(x_um, y_um)
    except RuntimeError as e:
        return {
            "success": False, "confirmed": None, "message": str(e), "position": None,
            "timing": _make_timing(total_s=0.0, attempts=0), "logs": [],
        }
    x_m, y_m = um_to_m(x_um), um_to_m(y_um)

    # Phase B: backbone.
    fire_fn = _rpc_fire(
        client, "MoveXY",
        lambda: client.stage.move_to(client.messages.stage_move(x_m, y_m)),
        call_timeout=STAGE_MOVE.call_timeout,
    )
    confirm_fn = partial(
        confirm_move_xy, client,
        target_x_um=x_um, target_y_um=y_um,
        tolerance=_profile_value(STAGE_MOVE, "confirm_tolerance", tolerance),
        poll_window=STAGE_MOVE.confirm_poll_s,
    )
    r = _dispatch(
        client, f"MoveXY -> ({x_um:.2f}, {y_um:.2f}) um", STAGE_MOVE,
        fire_fn=fire_fn, confirm_fn=confirm_fn, max_retries=max_retries,
    )

    # Phase C: target position (check r["confirmed"] for verification status).
    r["position"] = {"x_m": x_m, "y_m": y_m, "x_um": x_um, "y_um": y_um}
    return r


def move_z(client, z, unit="um", *, max_retries=None, tolerance=None):
    """Move focus (Z) to an absolute position. Returns a result dict with ``z_um``."""
    z_um = to_um(z, unit)
    try:
        _check_z_limits(z_um)
    except RuntimeError as e:
        return {
            "success": False, "confirmed": None, "message": str(e), "z_um": None,
            "timing": _make_timing(total_s=0.0, attempts=0), "logs": [],
        }
    z_m = um_to_m(z_um)

    fire_fn = _rpc_fire(
        client, "MoveZ",
        lambda: client.focus.move_to(client.messages.focus_move(z_m)),
        call_timeout=FOCUS_MOVE.call_timeout,
    )
    confirm_fn = partial(
        confirm_move_z, client,
        target_um=z_um,
        tolerance=_profile_value(FOCUS_MOVE, "confirm_tolerance", tolerance),
        poll_window=FOCUS_MOVE.confirm_poll_s,
    )
    r = _dispatch(
        client, f"MoveZ -> {z_um:.2f} um", FOCUS_MOVE,
        fire_fn=fire_fn, confirm_fn=confirm_fn, max_retries=max_retries,
    )
    r["z_um"] = z_um
    return r


def set_objective(client, *, index=None, name=None, magnification=None, max_retries=None):
    """Switch the objective by turret index, name, or magnification."""
    target = resolve_objective_index(client, index=index, name=name, magnification=magnification)

    fire_fn = _rpc_fire(
        client, "SetObjective",
        lambda: client.objective.move_to(client.messages.objective_move(target)),
        call_timeout=OBJECTIVE.call_timeout,
    )
    confirm_fn = partial(
        confirm_objective, client, target_index=target, poll_window=OBJECTIVE.confirm_poll_s
    )
    r = _dispatch(
        client, f"SetObjective -> index {target}", OBJECTIVE,
        fire_fn=fire_fn, confirm_fn=confirm_fn, max_retries=max_retries,
    )
    r["index"] = target
    return r


# =============================================================================
# Acquisition
# =============================================================================


def load_experiment(client, name_or_path) -> Experiment:
    """Load a ZEN experiment by name/path and return its handle."""
    resp = client.submit(client.experiment.load(client.messages.experiment_load(name_or_path)))
    experiment_id = _attr(resp, "experiment_id", "id")
    return Experiment(experiment_id=experiment_id, name=str(name_or_path))


def run_snap(client, experiment, *, poll_timeout=None, start_timeout=None):
    """Acquire a single snap for a loaded experiment; block until complete."""
    experiment_id = _exp_id(experiment)
    fire_fn = _rpc_fire(
        client, "RunSnap",
        lambda: client.experiment.run_snap(client.messages.run_snap(experiment_id)),
        call_timeout=SNAP.call_timeout,
    )
    confirm_fn = partial(
        confirm_acquire, client, experiment_id=experiment_id,
        start_timeout=_profile_value(SNAP, "start_timeout", start_timeout),
        heartbeat_interval=SNAP.heartbeat_interval,
        timeout=_profile_value(SNAP, "poll_timeout", poll_timeout),
        poll_interval=SNAP.poll_interval,
    )
    return _dispatch(client, "RunSnap", SNAP, fire_fn=fire_fn, confirm_fn=confirm_fn)


def run_experiment(
    client, experiment, *, output_name=None, poll_timeout=None, start_timeout=None, heartbeat_interval=None
):
    """Run a loaded experiment to completion; block via the status stream.

    Returns the result dict with an ``output_name`` key (the CZI name ZEN wrote,
    from the RPC response when present, else the requested name).
    """
    experiment_id = _exp_id(experiment)
    requested = output_name or getattr(experiment, "name", "experiment")
    fire_fn = _rpc_fire(
        client, "RunExperiment",
        lambda: client.experiment.run_experiment(
            client.messages.run_experiment(experiment_id, requested)
        ),
        call_timeout=RUN_EXPERIMENT.call_timeout,
    )
    confirm_fn = partial(
        confirm_acquire, client, experiment_id=experiment_id,
        start_timeout=_profile_value(RUN_EXPERIMENT, "start_timeout", start_timeout),
        heartbeat_interval=_profile_value(RUN_EXPERIMENT, "heartbeat_interval", heartbeat_interval),
        timeout=_profile_value(RUN_EXPERIMENT, "poll_timeout", poll_timeout),
        poll_interval=RUN_EXPERIMENT.poll_interval,
    )
    r = _dispatch(client, f"RunExperiment '{requested}'", RUN_EXPERIMENT, fire_fn=fire_fn, confirm_fn=confirm_fn)
    value = r.get("value")
    r["output_name"] = _attr(value, "output_name", default=requested) if value is not None else requested
    return r
