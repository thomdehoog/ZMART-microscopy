"""
Command wrappers.
=================
Public ``move_xy``, ``move_z``, ``set_objective``, ``load_experiment``,
``run_snap``, ``run_experiment``, ``start_experiment``, ``start_live``, ``stop``
and the focus procedures. Each follows the three-phase pattern:

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

from ..config.profiles import (
    FOCUS_MOVE,
    FOCUS_PROCEDURE,
    OBJECTIVE,
    RUN_EXPERIMENT,
    SNAP,
    STAGE_MOVE,
)
from ..config.units import m_to_um, to_um, um_to_m
from ..limits.checks import _check_xy_limits, _check_z_limits
from ..readers.api_reader import _attr
from .confirmations import confirm_acquire, confirm_move_xy, confirm_move_z, confirm_objective
from .dispatch import confirm_and_fire
from .envelope import _make_log_entry, _make_timing
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
            "success": False,
            "confirmed": None,
            "message": str(e),
            "position": None,
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }
    x_m, y_m = um_to_m(x_um), um_to_m(y_um)

    # Phase B: backbone.
    fire_fn = _rpc_fire(
        client,
        "MoveXY",
        lambda: client.stage.move_to(client.messages.stage_move(x_m, y_m)),
        call_timeout=STAGE_MOVE.call_timeout,
    )
    confirm_fn = partial(
        confirm_move_xy,
        client,
        target_x_um=x_um,
        target_y_um=y_um,
        tolerance=_profile_value(STAGE_MOVE, "confirm_tolerance", tolerance),
        poll_window=STAGE_MOVE.confirm_poll_s,
    )
    r = _dispatch(
        client,
        f"MoveXY -> ({x_um:.2f}, {y_um:.2f}) um",
        STAGE_MOVE,
        fire_fn=fire_fn,
        confirm_fn=confirm_fn,
        max_retries=max_retries,
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
            "success": False,
            "confirmed": None,
            "message": str(e),
            "z_um": None,
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }
    z_m = um_to_m(z_um)

    fire_fn = _rpc_fire(
        client,
        "MoveZ",
        lambda: client.focus.move_to(client.messages.focus_move(z_m)),
        call_timeout=FOCUS_MOVE.call_timeout,
    )
    confirm_fn = partial(
        confirm_move_z,
        client,
        target_um=z_um,
        tolerance=_profile_value(FOCUS_MOVE, "confirm_tolerance", tolerance),
        poll_window=FOCUS_MOVE.confirm_poll_s,
    )
    r = _dispatch(
        client,
        f"MoveZ -> {z_um:.2f} um",
        FOCUS_MOVE,
        fire_fn=fire_fn,
        confirm_fn=confirm_fn,
        max_retries=max_retries,
    )
    r["z_um"] = z_um
    return r


def set_objective(client, *, index=None, name=None, magnification=None, max_retries=None):
    """Switch the objective by turret index, name, or magnification."""
    target = resolve_objective_index(client, index=index, name=name, magnification=magnification)

    fire_fn = _rpc_fire(
        client,
        "SetObjective",
        lambda: client.objective.move_to(client.messages.objective_move(target)),
        call_timeout=OBJECTIVE.call_timeout,
    )
    confirm_fn = partial(
        confirm_objective, client, target_index=target, poll_window=OBJECTIVE.confirm_poll_s
    )
    r = _dispatch(
        client,
        f"SetObjective -> index {target}",
        OBJECTIVE,
        fire_fn=fire_fn,
        confirm_fn=confirm_fn,
        max_retries=max_retries,
    )
    r["index"] = target
    return r


# =============================================================================
# Acquisition
# =============================================================================


def load_experiment(client, name) -> Experiment:
    """Load one of ZEN's saved experiments by name and return its handle.

    ``name`` is the experiment as it appears in ZEN (the ``.czexp`` file name
    without the extension; ``get_available_experiments`` lists them). ZEN
    answers with an id that every later call uses to refer to this loaded
    copy. Raises the gRPC error when ZEN does not know the name.
    """
    resp = client.submit(client.experiment.load(client.messages.experiment_load(name)))
    experiment_id = _attr(resp, "experiment_id", "id")
    return Experiment(experiment_id=experiment_id, name=str(name))


def _run_acquisition(client, experiment, *, verb, profile, output_name):
    """Shared body of ``run_snap`` and ``run_experiment``.

    ZEN's run calls block until the acquisition is over, so the RPC itself is
    the completion signal; ``confirm_acquire`` then reads the final status.
    The result carries ``output_name`` (the CZI name ZEN chose or accepted)
    and ``status`` (the final status dict, or None if the readback failed).
    """
    experiment_id = _exp_id(experiment)
    requested = output_name or ""
    builder = getattr(client.messages, verb)
    rpc = getattr(client.experiment, verb)
    fire_fn = _rpc_fire(
        client,
        verb,
        lambda: rpc(builder(experiment_id, requested)),
        call_timeout=profile.call_timeout,
    )
    sink: dict = {}
    confirm_fn = partial(
        confirm_acquire,
        client,
        experiment_id=experiment_id,
        poll_window=profile.confirm_poll_s,
        sink=sink,
    )
    label = f"{verb} '{requested}'" if requested else verb
    r = _dispatch(client, label, profile, fire_fn=fire_fn, confirm_fn=confirm_fn)
    value = r.get("value")
    # betterproto gives "" for an unset string, so an empty echo from ZEN
    # means "use the name we asked for", and None when ZEN chose and did not say.
    echoed = _attr(value, "output_name") if value is not None else None
    r["output_name"] = echoed or requested or None
    r["status"] = sink.get("last_status")
    return r


def run_snap(client, experiment, *, output_name=None, poll_timeout=None, start_timeout=None):
    """Take one snap with the loaded experiment; returns when ZEN has finished.

    A snap is a single image with the experiment's active channels. ZEN writes
    it as ``<output_name>.czi`` in its image output folder (``get_image_output_path``),
    choosing a name itself when none is given. ``poll_timeout`` and
    ``start_timeout`` are accepted for compatibility and unused.
    """
    return _run_acquisition(
        client, experiment, verb="run_snap", profile=SNAP, output_name=output_name
    )


def run_experiment(
    client,
    experiment,
    *,
    output_name=None,
    poll_timeout=None,
    start_timeout=None,
    heartbeat_interval=None,
):
    """Run the whole loaded experiment (tiles, Z-stack, time series...) to completion.

    Blocks until ZEN reports the experiment finished, failed or was stopped.
    The image lands as ``<output_name>.czi`` in ZEN's image output folder; the
    result's ``output_name`` says which name ZEN used. The extra keyword
    arguments are accepted for compatibility and unused.
    """
    return _run_acquisition(
        client, experiment, verb="run_experiment", profile=RUN_EXPERIMENT, output_name=output_name
    )


def start_experiment(client, experiment, *, output_name=None) -> dict:
    """Start the loaded experiment and return as soon as it is running.

    Use this instead of ``run_experiment`` when you want to follow progress
    with ``monitor`` (ZEN only lets you subscribe to the status stream while
    the experiment is active). Returns ``{"output_name": ...}``.
    """
    experiment_id = _exp_id(experiment)
    resp = client.submit(
        client.experiment.start_experiment(
            client.messages.start_experiment(experiment_id, output_name or "")
        ),
        timeout=RUN_EXPERIMENT.call_timeout,
    )
    return {"output_name": _attr(resp, "output_name", default=output_name)}


def start_live(client, experiment) -> dict:
    """Start ZEN's live view with the loaded experiment (runs until ``stop``)."""
    experiment_id = _exp_id(experiment)
    client.submit(client.experiment.start_live(client.messages.start_live(experiment_id)))
    return {"experiment_id": experiment_id}


def stop(client, experiment=None) -> dict:
    """Stop the given experiment, or whatever acquisition is active when none is given.

    Covers experiments, snaps, live and continuous mode. Returns
    ``{"experiment_id": ...}`` naming what ZEN stopped.
    """
    experiment_id = _exp_id(experiment) if experiment is not None else ""
    resp = client.submit(client.experiment.stop(client.messages.stop(experiment_id)))
    return {"experiment_id": _attr(resp, "experiment_id", default=experiment_id)}


# =============================================================================
# Focus procedures
# =============================================================================


def _focus_result(r, *, key):
    """Attach the focus position (m on the wire -> µm) from the RPC value."""
    value = r.get("value")
    raw = _attr(value, key) if value is not None else None
    r["z_um"] = m_to_um(raw) if raw is not None else None
    return r


def find_autofocus(client, experiment, *, timeout_s=None):
    """Run ZEN's software autofocus as set up in the loaded experiment.

    ZEN scans through focus using the experiment's autofocus settings
    (search range, reference channel, contrast measure) and leaves the focus
    drive at the sharpest position, which comes back as ``z_um``. Blocks
    until the search is over; ``timeout_s`` caps the search on the ZEN side.
    """
    experiment_id = _exp_id(experiment)
    fire_fn = _rpc_fire(
        client,
        "FindAutoFocus",
        lambda: client.sw_autofocus.find_auto_focus(
            client.messages.find_autofocus(experiment_id, timeout_s)
        ),
        call_timeout=FOCUS_PROCEDURE.call_timeout,
    )
    r = _dispatch(client, "FindAutoFocus", FOCUS_PROCEDURE, fire_fn=fire_fn)
    return _focus_result(r, key="focus_position")


def find_surface(client):
    """Ask Definite Focus to find the coverslip surface; the focus drive moves there.

    Only available on microscopes with ZEISS Definite Focus hardware. The
    surface position comes back as ``z_um``.
    """
    fire_fn = _rpc_fire(
        client,
        "FindSurface",
        lambda: client.definite_focus.find_surface(client.messages.find_surface()),
        call_timeout=FOCUS_PROCEDURE.call_timeout,
    )
    r = _dispatch(client, "FindSurface", FOCUS_PROCEDURE, fire_fn=fire_fn)
    return _focus_result(r, key="zposition")


def store_focus(client):
    """Remember the current focus in Definite Focus (see ``recall_focus``)."""
    fire_fn = _rpc_fire(
        client,
        "StoreFocus",
        lambda: client.definite_focus.store_focus(client.messages.store_focus()),
        call_timeout=FOCUS_PROCEDURE.call_timeout,
    )
    return _dispatch(client, "StoreFocus", FOCUS_PROCEDURE, fire_fn=fire_fn)


def recall_focus(client):
    """Return the focus drive to the position stored with ``store_focus``; gives ``z_um``."""
    fire_fn = _rpc_fire(
        client,
        "RecallFocus",
        lambda: client.definite_focus.recall_focus(client.messages.recall_focus()),
        call_timeout=FOCUS_PROCEDURE.call_timeout,
    )
    r = _dispatch(client, "RecallFocus", FOCUS_PROCEDURE, fire_fn=fire_fn)
    return _focus_result(r, key="zposition")
