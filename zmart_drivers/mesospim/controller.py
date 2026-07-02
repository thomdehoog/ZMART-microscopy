"""
ZMART controller adapter.
=========================
The seam that plugs this driver into the vendor-agnostic **ZMART controller**
(``zmart_controller``). The controller drives every microscope through one small
ops table -- ``connect`` plus one callable per operation -- registered under a
``connection`` identity dict. This module implements that table for mesoSPIM and
registers it.

Like the reference ``mock_driver``, the driver owns the frame **origin**: the
controller works in micrometers from an origin the driver subtracts, so the
controller never does coordinate math. It also owns the mutable/immutable state
boundary and the capture+save step.

The controller surface is deliberately x/y/z centric. mesoSPIM's extra axes
(focus, rotation) and light-path settings are exposed too: focus/rotation as
**procedures**, and laser/filter/zoom/intensity/shutter/ETL as the **mutable
state**. The full driver API (``import mesospim``) remains available for anything
the neutral surface does not cover.

Register at import: ``from mesospim import controller`` runs :func:`register`
via the package ``__init__``, so ``zmart_controller.get_instruments()`` lists the
mesoSPIM entry.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import acquisition as _acq
from . import commands as _cmd
from .config import limits as _limits
from .config.profiles import ACQUISITION, HARDWARE
from .connection.session import close as _close
from .connection.session import connect as _connect
from .readers import readers as _readers

log = logging.getLogger(__name__)

# Per-axis actuator options this instrument exposes to the controller. mesoSPIM
# linear axes are single-motoric; focus/rotation are separate axes reached via
# procedures, not actuators of x/y/z.
_ACTUATORS: dict[str, list[str]] = {
    "x": ["motoric"],
    "y": ["motoric"],
    "z": ["motoric"],
}

# State keys the driver treats as mutable (capturable + reapplyable).
_MUTABLE_KEYS = (
    "laser",
    "intensity",
    "filter",
    "zoom",
    "shutterconfig",
    "etl_l_amplitude",
    "etl_l_offset",
    "etl_r_amplitude",
    "etl_r_offset",
)


@dataclass
class MesospimHandle:
    """Live session handle the controller passes back into every op."""

    client: Any
    connection: dict
    output_root: Path
    origin: dict = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0})
    initial_positions: list = field(default_factory=list)
    immutable: dict = field(default_factory=dict)
    # Monotonic counter to give each acquisition a unique image-writer staging
    # dir (so repeated/same-label captures never collide).
    _acq_seq: int = 0


# =============================================================================
# lifecycle
# =============================================================================


def connect(connection: dict) -> MesospimHandle:
    """Open a mesoSPIM session and capture the initial positions.

    Honours ``connection`` keys ``host`` / ``port`` / ``timeout`` (forwarded to
    the driver ``connect``), ``output_root`` (where ``acquire`` saves), and
    ``stage_limits`` (a path to a stage-limits config; defaults to the bundled
    envelope). If no ``output_root`` is given, a per-session temp directory is
    created.

    Stage safety limits are loaded here so the controller path is never left
    fail-open: ``check_axis`` rejects an unconfigured axis, so a move can only
    run once limits exist.
    """
    client = _connect(connection)
    output_root = Path(connection.get("output_root") or tempfile.mkdtemp(prefix="mesospim_run_"))
    output_root.mkdir(parents=True, exist_ok=True)

    # Configure hard stage limits before any move is possible. Without this the
    # fail-closed ``check_axis`` would reject every move; with it the bundled
    # (or caller-supplied) envelope is active for the whole session. Cleared
    # first so a reconnect fully replaces the limits rather than merging into a
    # prior session's. NOTE: limits are process-global, so this driver assumes a
    # single instrument per process; connecting a second instrument in the same
    # process would share (and overwrite) these limits.
    _limits.clear_stage_limits()
    _limits.apply_stage_limits_from_config(
        _limits.load_stage_config(connection.get("stage_limits"))
    )

    positions = _readers.get_positions(client)
    info = dict(client.server_info)
    handle = MesospimHandle(
        client=client,
        connection=dict(connection),
        output_root=output_root,
        immutable={
            "app": info.get("app", "mesoSPIM-control"),
            "microscope": connection.get("microscope"),
            "version": info.get("version"),
            "host": client.host,
            "port": client.port,
        },
        initial_positions=[{k: positions.get(k) for k in ("x", "y", "z", "f", "theta")}],
    )
    log.info("mesoSPIM controller session ready (output_root=%s)", output_root)
    return handle


def disconnect(handle: MesospimHandle) -> None:
    """Close the underlying client session."""
    _close(handle.client)


# =============================================================================
# frame origin
# =============================================================================


def set_origin(handle: MesospimHandle) -> dict:
    """Mark the current position as the origin -- it now reads (0, 0, 0)."""
    pos = _readers.get_positions(handle.client)
    handle.origin = {axis: float(pos.get(axis) or 0.0) for axis in ("x", "y", "z")}
    return {"origin": dict(handle.origin)}


def _user_xyz(handle: MesospimHandle, pos: dict) -> dict[str, float]:
    return {axis: float(pos.get(axis) or 0.0) - handle.origin[axis] for axis in ("x", "y", "z")}


# =============================================================================
# movement
# =============================================================================


def get_actuators(handle: MesospimHandle) -> dict:
    """The actuator options each axis offers (driver-defined)."""
    return {axis: list(opts) for axis, opts in _ACTUATORS.items()}


def _validate_actuators(with_actuators: dict | None) -> None:
    if not with_actuators:
        return
    for axis, actuator in with_actuators.items():
        if axis not in _ACTUATORS:
            raise ValueError(f"unknown axis {axis!r}")
        # A single value or a one-element list both name the actuator.
        name = actuator[0] if isinstance(actuator, (list, tuple)) else actuator
        if name not in _ACTUATORS[axis]:
            raise ValueError(f"unknown actuator {actuator!r} for axis {axis!r}")


def get_xyz(handle: MesospimHandle, *, with_actuators: dict | None = None) -> dict:
    """Report the linear position per axis (um, relative to origin)."""
    _validate_actuators(with_actuators)
    pos = _readers.get_positions(handle.client)
    user = _user_xyz(handle, pos)
    return {
        axis: {"value": user[axis], "actuator": _ACTUATORS[axis][0], "unit": "um"}
        for axis in ("x", "y", "z")
    }


def set_xyz(
    handle: MesospimHandle,
    x: float,
    y: float,
    z: float,
    *,
    with_actuators: dict | None = None,
) -> dict:
    """Move to an absolute target (um, relative to origin); return a move record.

    The driver maps user coordinates to raw stage coordinates via the origin and
    issues one absolute move, then reports the confirmed position.
    """
    _validate_actuators(with_actuators)
    targets = {
        "x": handle.origin["x"] + float(x),
        "y": handle.origin["y"] + float(y),
        "z": handle.origin["z"] + float(z),
    }
    result = _cmd.move_absolute(handle.client, targets)
    if not result.get("success"):
        raise RuntimeError(f"set_xyz failed: {result.get('message')}")
    return {
        "position": {"x": float(x), "y": float(y), "z": float(z)},
        "confirmed": result.get("confirmed"),
        "actuators": {axis: _ACTUATORS[axis][0] for axis in ("x", "y", "z")},
    }


# =============================================================================
# state
# =============================================================================


def get_state(handle: MesospimHandle) -> dict:
    """Capture instrument state: immutable fingerprint + mutable settings."""
    state = _readers.get_state(handle.client)
    mutable = {key: state.get(key) for key in _MUTABLE_KEYS if state.get(key) is not None}
    return {"immutable": dict(handle.immutable), "mutable": mutable}


def set_state(handle: MesospimHandle, state: dict) -> dict:
    """Validate the immutable fingerprint, then reapply the mutable settings.

    Rejects state that carries no fingerprint at all (an empty ``immutable`` must
    not silently pass), and compares the instrument identity -- including the
    configured ``microscope`` name, not just the socket endpoint, so state from a
    different instrument reachable at the same ``host``/``port`` is still caught.
    """
    immutable = state.get("immutable") or {}
    if not immutable:
        raise ValueError("state has no immutable fingerprint; refusing to reapply")
    for key in ("app", "microscope", "host", "port"):
        want = immutable.get(key, handle.immutable.get(key))
        if want != handle.immutable.get(key):
            raise ValueError(
                f"state captured on a different instrument ({key}={want!r} != "
                f"{handle.immutable.get(key)!r})"
            )
    mutable = {k: v for k, v in (state.get("mutable") or {}).items() if k in _MUTABLE_KEYS}
    if not mutable:
        return {"applied": {}}
    result = _cmd.set_state(handle.client, mutable)
    if not result.get("success"):
        raise RuntimeError(f"set_state failed: {result.get('message')}")
    return {"applied": mutable, "confirmed": result.get("confirmed")}


# =============================================================================
# procedures
# =============================================================================


def get_procedures(handle: MesospimHandle) -> dict:
    """The named procedures the driver offers."""
    procs = {name: {"description": desc} for name, desc in ACQUISITION.procedures}
    procs["move_focus"] = {"description": "move the focus (detection) axis (um)", "args": ["value"]}
    procs["move_rotation"] = {"description": "rotate the sample (degrees)", "args": ["value"]}
    return procs


def set_procedure(handle: MesospimHandle, procedure: dict) -> dict:
    """Run a procedure. ``procedure`` is ``{"name": ..., ...args}``."""
    name = procedure.get("name")
    if name == "move_focus":
        result = _cmd.move_focus(handle.client, float(procedure["value"]))
    elif name == "move_rotation":
        result = _cmd.move_rotation(handle.client, float(procedure["value"]))
    elif name == "zero_stage":
        result = _cmd.zero_axes(handle.client, ["x", "y", "z"])
    elif name in ("autofocus", "find_sample"):
        # Server-side named procedures: forwarded verbatim to the command server.
        reply = handle.client.request("procedure", name=name, args=procedure.get("args", {}))
        return {"ran": name, "data": dict(reply.data)}
    else:
        raise ValueError(f"unknown procedure {name!r}")
    if not result.get("success"):
        raise RuntimeError(f"procedure {name!r} failed: {result.get('message')}")
    return {"ran": name, "confirmed": result.get("confirmed")}


# =============================================================================
# acquire (captures and saves)
# =============================================================================


def get_acquisition_options(handle: MesospimHandle) -> dict:
    """The acquisition + saving options this instrument offers (options + active)."""
    zooms = [name for name, _px in HARDWARE.zoom_pixel_size_um]
    return {
        "format": {"options": list(ACQUISITION.formats), "active": ACQUISITION.save_format},
        "backlash_correction": {"options": [True, False], "active": True},
        "shutterconfig": {
            "options": list(HARDWARE.shutter_configs),
            "active": ACQUISITION.default_shutterconfig,
        },
        "zoom": {"options": zooms, "active": ACQUISITION.default_zoom},
        "planes": {"options": "int >= 1", "active": 1},
        "z_step": {"options": "float um", "active": 1.0},
    }


_ACQUIRE_STATE_KEYS = ("laser", "intensity", "filter", "zoom", "shutterconfig")
_ACQUIRE_CAPTURE_KEYS = ("planes", "z_step", "z_start", "z_end")


def acquire(
    handle: MesospimHandle,
    *,
    acquisition_type: str,
    position_label: str,
    options: dict | None = None,
) -> dict:
    """Capture one dataset and save it, returning the record.

    Applies any light-path options as state first, optionally settles the stage
    (backlash correction), captures via the mesoSPIM image writer, then relocates
    the frames into ``<output_root>/data/``.
    """
    options = dict(options or {})
    fmt = options.get("format", ACQUISITION.save_format)

    # 1) apply light-path settings that were passed as options.
    state_updates = {k: options[k] for k in _ACQUIRE_STATE_KEYS if k in options}
    if state_updates:
        res = _cmd.set_state(handle.client, state_updates)
        if not res.get("success"):
            raise RuntimeError(f"acquire: applying settings failed: {res.get('message')}")

    # 2) optional backlash settle on the linear stage before capture.
    if options.get("backlash_correction", True):
        _settle(handle)

    # 3) capture (snap or stack, per the capture options).
    capture_options = {k: options[k] for k in _ACQUIRE_CAPTURE_KEYS if k in options}
    # Stack Z bounds arrive in the controller's user frame (like set_xyz); map
    # them to raw stage coordinates via the origin so a non-zero origin does not
    # shift the stack. z_step is a delta, so it is left untouched.
    for zc in ("z_start", "z_end"):
        if zc in capture_options:
            capture_options[zc] = handle.origin["z"] + float(capture_options[zc])
    # Limit-check the swept Z range before firing: the capture path sweeps the
    # stage but does not go through move_absolute, so enforce the same hard
    # limits here (fail closed) rather than trusting the acquisition to be safe.
    try:
        for zc in ("z_start", "z_end"):
            if zc in capture_options:
                _limits.check_axis("z", float(capture_options[zc]))
    except _limits.LimitError as exc:
        raise RuntimeError(f"acquire: stack Z range outside stage limits: {exc}") from exc

    # Give the image writer an explicit, per-acquisition output location so the
    # resident server can resolve the frame paths and repeated/same-label
    # captures never collide. Cleaned up after the frames are relocated.
    handle._acq_seq += 1
    stem = _acq.canonical_stem(acquisition_type, position_label)
    staging = handle.output_root / "_staging" / f"{stem}_{handle._acq_seq:04d}"
    staging.mkdir(parents=True, exist_ok=True)
    capture_options.setdefault("folder", str(staging))
    capture_options.setdefault("filename", f"{stem}.tiff")
    result = _acq.acquire(handle.client, acquisition_type, options=capture_options)

    # 4) save into the canonical layout, then drop the staging copies (save()
    #    copies rather than moves, so remove the writer's originals to avoid
    #    doubling every dataset on disk).
    try:
        saved = _acq.save(
            result,
            handle.output_root,
            position_label=position_label,
            format=fmt,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {
        "acquisition_type": acquisition_type,
        "position_label": position_label,
        "format": fmt,
        "planes": result.planes,
        "image_files": [str(p) for p in saved.image_paths],
        "metadata_file": str(saved.metadata_path) if saved.metadata_path else None,
        "position": _user_xyz(handle, _readers.get_positions(handle.client)),
        "duration_s": result.duration_s,
    }


def _settle(handle: MesospimHandle, overshoot_um: float = 5.0) -> None:
    """Pin the linear stage backlash: nudge -overshoot on x/y/z, then return.

    Backlash correction is an optimisation, not a requirement: if the overshoot
    would violate a stage limit (or otherwise fails), it is skipped with a
    warning rather than driving into a hard stop. But once the overshoot has
    moved the stage, a failed return move leaves the stage displaced, so that is
    surfaced as an error rather than proceeding to capture at the wrong place.
    """
    pos = _readers.get_positions(handle.client)
    linear = {axis: float(pos.get(axis) or 0.0) for axis in ("x", "y", "z")}
    nudge = _cmd.move_absolute(handle.client, {a: v - overshoot_um for a, v in linear.items()})
    if not nudge.get("success"):
        log.warning("acquire: backlash settle skipped (%s)", nudge.get("message"))
        return
    back = _cmd.move_absolute(handle.client, linear)
    if not back.get("success"):
        raise RuntimeError(f"acquire: backlash settle left stage displaced: {back.get('message')}")


# =============================================================================
# registration
# =============================================================================

# The connection identity the ZMART controller keys on. ``microscope`` is a
# placeholder for a specific instrument; edit it (and host/port/output_root) per
# deployment before connecting.
CONNECTION = {
    "vendor": "mesospim",
    "microscope": "mesospim-01",
    "api": "command-server",
    "host": "127.0.0.1",
    "port": 42000,
}


def get_context(handle: MesospimHandle) -> dict:
    """Read-only extras the driver exposes: initial positions, focus/rotation."""
    pos = _readers.get_positions(handle.client)
    return {
        "initial_positions": [dict(p) for p in handle.initial_positions],
        "focus_um": pos.get("f"),
        "rotation_deg": pos.get("theta"),
        "output_root": str(handle.output_root),
        "server": dict(handle.immutable),
    }


OPS = {
    "connect": connect,
    "disconnect": disconnect,
    "get_acquisition_options": get_acquisition_options,
    "set_origin": set_origin,
    "get_actuators": get_actuators,
    "get_xyz": get_xyz,
    "set_xyz": set_xyz,
    "acquire": acquire,
    "get_state": get_state,
    "set_state": set_state,
    "get_procedures": get_procedures,
    "set_procedure": set_procedure,
    "get_context": get_context,
}


def register(connection: dict | None = None) -> None:
    """Register the mesoSPIM driver with the ZMART controller registry.

    Safe to call more than once (idempotent per identity). ``connection`` may
    override the default identity/params (e.g. a specific ``microscope`` name,
    ``host``/``port``, ``output_root``).
    """
    try:
        from zmart_controller.registry import register as _register
    except Exception:  # noqa: BLE001 - controller optional at import time
        log.debug("zmart_controller not importable; skipping registration", exc_info=True)
        return
    _register(connection or dict(CONNECTION), ops=dict(OPS))
