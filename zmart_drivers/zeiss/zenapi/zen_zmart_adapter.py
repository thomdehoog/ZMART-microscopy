"""
ZMART controller adapter for ZEISS ZEN.
=======================================
The seam that plugs this driver into the vendor-agnostic **ZMART controller**
(``zmart_controller``). The controller drives every microscope through one
small ops table -- ``connect`` plus one callable per operation -- registered
under a ``connection`` identity dict. This module implements that table for
ZEN (through the ZEN API gateway, see ``connection/``) and registers it.

As in the other drivers, the driver owns the frame **origin**: the controller
works in micrometres from an origin the driver subtracts, so the controller
never does coordinate maths. Every move is checked against the stage limits
of this microscope before ZEN is asked to move, and ``acquire`` runs the
loaded ZEN experiment and brings the CZI into the output folder.

What the neutral surface covers for ZEN today:

* **x/y/z** -- the XY stage and the focus drive (one "motoric" actuator each).
* **changeable state** -- the objective (position on the changer) and the
  loaded ZEN experiment (the imaging settings: channels, exposure, Z-stack).
* **procedures** -- ``software_autofocus`` (ZEN's focus search as set up in
  the loaded experiment), ``find_surface`` / ``store_focus`` / ``recall_focus``
  (Definite Focus), ``live`` and ``stop``.
* **acquire** -- a snap, or the whole experiment (tiles, Z-stack, time
  series) when asked, written by ZEN as one CZI and copied into
  ``<output_root>/data/``.

Register at import: importing this module (which ``import zenapi`` does) calls
:func:`register` at the bottom of the file, so
``zmart_controller.get_instruments()`` lists the ZEISS entry with no explicit
call. It is a safe no-op when ``zmart_controller`` is not installed.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .acquisition.save import _wait_stable, zen_image_path
from .calibration import machine as _machine
from .commands import commands as _cmd
from .connection.session import close as _close
from .connection.session import connect as _connect
from .limits import checks as _limits
from .limits import stage_config as _stage_config
from .readers import api_reader as _readers

log = logging.getLogger(__name__)

# Every axis is driven by one motor under ZEN: the XY stage and the focus drive.
_ACTUATORS: dict[str, list[str]] = {"x": ["motoric"], "y": ["motoric"], "z": ["motoric"]}

# The connection identity the ZMART controller keys on. ``microscope`` names a
# specific instrument; edit it (and ``config`` / ``output_root``) per
# deployment. ``config`` is the ZEN API ``config.ini`` (host, port, gateway
# certificate, control token); ``host`` / ``port`` / ``cert_file`` /
# ``control_token`` may be given directly instead.
CONNECTION = {
    "vendor": "zeiss",
    "microscope": "zen-lm",
    "api": "zen-api",
    "config": "config.ini",
}


@dataclass
class ZenHandle:
    """Live session handle the controller passes back into every op."""

    client: Any
    connection: dict
    output_root: Path
    machine: Any
    limits: dict = field(default_factory=dict)
    limits_are_defaults: bool = False
    origin: dict = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0})
    immutable: dict = field(default_factory=dict)
    initial_position: dict = field(default_factory=dict)
    experiment: Any = None  # the loaded zenapi.Experiment, or None
    closed: bool = False


# =============================================================================
# lifecycle
# =============================================================================


def _open_client(connection: dict):
    """Connect to the gateway from the connection dict (kept separate so tests can swap it)."""
    return _connect(
        connection.get("config"),
        host=connection.get("host"),
        port=connection.get("port"),
        cert_file=connection.get("cert_file"),
        control_token=connection.get("control_token"),
        connect_timeout=connection.get("connect_timeout"),
    )


def connect(connection: dict) -> ZenHandle:
    """Open a session with ZEN through its API gateway and read what it offers.

    Honours ``config`` (path to the ZEN API ``config.ini``) or the explicit
    ``host`` / ``port`` / ``cert_file`` / ``control_token`` keys,
    ``output_root`` (where ``acquire`` copies images; a temp folder when
    omitted), ``machine_root`` (override for the ProgramData root) and
    ``experiment`` (a ZEN experiment to load right away). The stage limits
    come from this microscope's ``stage_limits.json`` (generic defaults are
    copied there on the first connect, with a warning) and govern every move
    of the session; the frame origin a previous session persisted is restored.
    """
    client = _open_client(connection)
    try:
        output_root = Path(connection.get("output_root") or tempfile.mkdtemp(prefix="zeiss_run_"))
        output_root.mkdir(parents=True, exist_ok=True)
        machine = _machine.MachineProfile(
            microscope_id=connection.get("microscope") or CONNECTION["microscope"],
            programdata_root=connection.get("machine_root"),
        )
        limits_path, copied = machine.ensure_limits_file()
        stage_cfg = _stage_config.load(limits_path)
        _limits.apply_stage_limits_from_config(stage_cfg)
        if copied:
            log.warning(
                "no stage limits were set for this microscope; generic defaults were "
                "copied to %s. Replace them with the real travel range of the stage.",
                limits_path,
            )
        limits = {
            axis: {"min": float(lo), "max": float(hi)}
            for axis, (lo, hi) in stage_cfg["stage_um"].items()
        }
        objectives = _readers.get_objectives(client)
        handle = ZenHandle(
            client=client,
            connection=dict(connection),
            output_root=output_root,
            machine=machine,
            limits=limits,
            limits_are_defaults=copied,
            immutable={
                "app": "ZEN",
                "api": "ZEN API (gRPC)",
                "microscope": connection.get("microscope"),
                "runtime": dict(getattr(client, "runtime", {})),
                "objectives": objectives,
                "image_output_path": _safe(_readers.get_image_output_path, client, default=""),
            },
            initial_position=_raw_xyz(client),
        )
        _restore_persisted_origin(handle)
        if connection.get("experiment"):
            handle.experiment = _cmd.load_experiment(client, str(connection["experiment"]))
    except Exception:
        _close(client)
        raise
    log.info("ZEN controller session ready (output_root=%s)", output_root)
    return handle


def _safe(fn, *args, default=None):
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - optional information must not block connect
        log.debug("%s unavailable: %s", getattr(fn, "__name__", fn), exc)
        return default


def _restore_persisted_origin(handle: ZenHandle) -> None:
    try:
        payload = handle.machine.read_origin()
    except Exception as exc:  # noqa: BLE001 - a corrupt file must not block connect
        log.warning("could not read persisted origin (%s); frame is raw stage coordinates", exc)
        return
    if not payload:
        return
    origin = payload.get("origin") or {}
    try:
        handle.origin = {axis: float(origin[axis]) for axis in ("x", "y", "z")}
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("persisted origin is malformed (%s); frame is raw stage coordinates", exc)
        return
    log.info(
        "restored frame origin from %s", handle.machine.machine_dir() / _machine.ORIGIN_FILENAME
    )


def disconnect(handle: ZenHandle) -> None:
    """Close the connection to the gateway (ZEN itself keeps running)."""
    handle.closed = True
    _close(handle.client)


def _require_open(handle: ZenHandle) -> None:
    if handle.closed:
        raise RuntimeError("session is disconnected")


# =============================================================================
# frame origin
# =============================================================================


def _raw_xyz(client) -> dict[str, float]:
    """The position ZEN reports, in micrometres, before the origin is subtracted."""
    xy = _readers.get_xy(client)
    return {"x": float(xy["x_um"]), "y": float(xy["y_um"]), "z": float(_readers.get_z(client))}


def set_origin(handle: ZenHandle) -> dict:
    """Mark the current position as the origin -- it now reads (0, 0, 0).

    Persisted in the machine folder and restored by :func:`connect`, so the zero
    point survives reconnects until it is set again.
    """
    _require_open(handle)
    handle.origin = _raw_xyz(handle.client)
    try:
        path = handle.machine.write_origin(
            {
                "origin": dict(handle.origin),
                "microscope": handle.immutable.get("microscope"),
                "captured_at": time.time(),
            }
        )
    except OSError as exc:
        raise RuntimeError(f"could not persist origin reference: {exc}") from exc
    return {"origin": dict(handle.origin), "origin_file": str(path)}


def _user_xyz(handle: ZenHandle, raw: dict) -> dict[str, float]:
    return {axis: float(raw[axis]) - handle.origin[axis] for axis in ("x", "y", "z")}


# =============================================================================
# movement
# =============================================================================


def get_actuators(handle: ZenHandle) -> dict:
    """The actuator options each axis offers: one motor per axis under ZEN."""
    _require_open(handle)
    return {axis: list(opts) for axis, opts in _ACTUATORS.items()}


def _resolve_actuators(with_actuators: dict | None) -> dict[str, str]:
    """Per-axis actuator choice for one call, validated; ZEN has one option per axis."""
    chosen = {axis: opts[0] for axis, opts in _ACTUATORS.items()}
    if not with_actuators:
        return chosen
    for axis, actuator in with_actuators.items():
        if axis not in _ACTUATORS:
            raise ValueError(f"unknown axis {axis!r}")
        name = actuator[0] if isinstance(actuator, (list, tuple)) else actuator
        if name not in _ACTUATORS[axis]:
            raise ValueError(f"unknown actuator {actuator!r} for axis {axis!r}")
        chosen[axis] = name
    return chosen


def get_xyz(handle: ZenHandle, *, with_actuators: dict | None = None) -> dict:
    """Report the position per axis (um, relative to the origin) with its actuator."""
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    user = _user_xyz(handle, _raw_xyz(handle.client))
    return {
        axis: {"value": user[axis], "actuator": chosen[axis], "unit": "um"}
        for axis in ("x", "y", "z")
    }


def _raise_if_failed(result: dict, what: str) -> None:
    """Turn a failed command result into the controller's error contract."""
    if not result.get("success"):
        raise RuntimeError(f"{what} refused: {result.get('message')}")


def set_xyz(
    handle: ZenHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to an absolute target (um, relative to the origin); return a move record.

    The target is mapped to ZEN's stage coordinates through the origin and
    checked against the stage limits before ZEN is asked to move; XY moves
    first, then the focus drive. The record carries the position ZEN reported
    after the move.
    """
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    targets = {
        axis: handle.origin[axis] + float(value) for axis, value in (("x", x), ("y", y), ("z", z))
    }
    # All three axes are checked before anything moves, so a bad Z target
    # never leaves the stage half-way to its XY target.
    try:
        _limits._check_xy_limits(targets["x"], targets["y"])
        _limits._check_z_limits(targets["z"])
    except RuntimeError as exc:
        raise RuntimeError(f"set_xyz refused: {exc}") from exc
    _raise_if_failed(_cmd.move_xy(handle.client, targets["x"], targets["y"]), "set_xyz")
    _raise_if_failed(_cmd.move_z(handle.client, targets["z"]), "set_xyz")
    return {
        "position": {"x": float(x), "y": float(y), "z": float(z)},
        "confirmed": _user_xyz(handle, _raw_xyz(handle.client)),
        "actuators": chosen,
    }


# =============================================================================
# state
# =============================================================================


def get_state(handle: ZenHandle) -> dict:
    """Changeable settings first, then the observed report.

    Changeable: ``objective_position`` (position index on the objective
    changer) and ``experiment`` (the loaded ZEN experiment, which carries the
    imaging settings: channels, exposure, Z-stack). Observed: identity, the
    objectives, the experiments ZEN can load, where ZEN writes images, the
    stage limits.
    """
    _require_open(handle)
    current = _readers.get_objective(handle.client)
    observed = dict(handle.immutable)
    observed["objective"] = current
    observed["available_experiments"] = _safe(
        _readers.get_available_experiments, handle.client, default=[]
    )
    observed["limits"] = dict(handle.limits)
    observed["limits_are_defaults"] = handle.limits_are_defaults
    observed["busy"] = _readers.get_status(handle.client)["is_experiment_running"]
    return {
        "changeable": {
            "objective_position": current["index"],
            "experiment": handle.experiment.name if handle.experiment else None,
        },
        "observed": observed,
    }


def set_state(handle: ZenHandle, state: dict) -> dict:
    """Apply the changeable settings; report what stuck.

    Accepts ``objective_position`` (a position index from the observed
    objectives) and ``experiment`` (a name from ``available_experiments``).
    ``observed`` is a report, never an instruction, and is not read here.
    """
    _require_open(handle)
    changeable = state.get("changeable") or {}
    applied: dict[str, Any] = {}
    if "objective_position" in changeable:
        result = _cmd.set_objective(handle.client, index=int(changeable["objective_position"]))
        _raise_if_failed(result, "set_state(objective_position)")
        applied["objective_position"] = result["index"]
    if changeable.get("experiment"):
        handle.experiment = _cmd.load_experiment(handle.client, str(changeable["experiment"]))
        applied["experiment"] = handle.experiment.name
    return {"applied": applied}


# =============================================================================
# procedures
# =============================================================================


def get_procedures(handle: ZenHandle) -> dict:
    """The named procedures this driver offers."""
    _require_open(handle)
    return {
        "software_autofocus": {
            "description": "ZEN's software autofocus with the settings of the loaded "
            "experiment; leaves the focus drive at the sharpest plane",
            "args": ["timeout_s"],
        },
        "find_surface": {
            "description": "Definite Focus: find the coverslip surface and move the "
            "focus drive there (needs Definite Focus hardware)"
        },
        "store_focus": {"description": "Definite Focus: remember the current focus"},
        "recall_focus": {"description": "Definite Focus: return to the stored focus"},
        "live": {"description": "start ZEN's live view with the loaded experiment"},
        "stop": {"description": "stop whatever ZEN is acquiring (live, snap or experiment)"},
    }


def _focus_record(handle: ZenHandle, name: str, result: dict) -> dict:
    _raise_if_failed(result, name)
    raw_z = result.get("z_um")
    if raw_z is None:
        raw_z = float(_readers.get_z(handle.client))
    return {
        "ran": name,
        "focus_um": raw_z,
        "frame_z_um": raw_z - handle.origin["z"],
        "duration_s": result.get("timing", {}).get("total_s"),
    }


def run_procedure(handle: ZenHandle, procedure: dict) -> dict:
    """Run a procedure. ``procedure`` is ``{"name": ..., ...args}``.

    The focus procedures report the focus as ``frame_z_um`` (relative to the
    origin) and ``focus_um`` (ZEN's raw position), like the other drivers.
    """
    _require_open(handle)
    name = procedure.get("name")
    if name == "software_autofocus":
        _require_experiment(handle, "software_autofocus")
        timeout = procedure.get("timeout_s")
        result = _cmd.find_autofocus(
            handle.client, handle.experiment, timeout_s=float(timeout) if timeout else None
        )
        return _focus_record(handle, name, result)
    if name == "find_surface":
        return _focus_record(handle, name, _cmd.find_surface(handle.client))
    if name == "store_focus":
        _raise_if_failed(_cmd.store_focus(handle.client), name)
        return {"ran": name}
    if name == "recall_focus":
        return _focus_record(handle, name, _cmd.recall_focus(handle.client))
    if name == "live":
        _require_experiment(handle, "live")
        _cmd.start_live(handle.client, handle.experiment)
        return {"ran": name, "experiment": handle.experiment.name}
    if name == "stop":
        stopped = _cmd.stop(handle.client)
        return {"ran": name, **stopped}
    raise ValueError(f"unknown procedure {name!r}; known: {sorted(get_procedures(handle))}")


def _require_experiment(handle: ZenHandle, what: str) -> None:
    if handle.experiment is None:
        raise ValueError(
            f"{what} needs a loaded ZEN experiment: set_state({{'changeable': "
            f"{{'experiment': <name>}}}}) first, or pass 'experiment' in the connection"
        )


# =============================================================================
# acquire (captures and saves)
# =============================================================================

# What ``acquisition_type`` means here: anything containing one of these runs
# the whole experiment (tiles, Z-stack, time series); everything else is a snap.
EXPERIMENT_TYPES = ("experiment", "stack", "z_stack", "zstack", "z-stack", "tiles", "timelapse")


def get_acquisition_options(handle: ZenHandle) -> dict:
    """The acquisition + saving options this instrument offers (options + active).

    ``experiment`` chooses the ZEN experiment (the imaging settings), ``mode``
    a single snap or the whole experiment, ``copy_to_output_root`` whether the
    CZI is copied from ZEN's image folder into ``<output_root>/data/``.
    """
    _require_open(handle)
    return {
        "experiment": {
            "options": _safe(_readers.get_available_experiments, handle.client, default=[]),
            "active": handle.experiment.name if handle.experiment else None,
        },
        "mode": {"options": ["snap", "experiment"], "active": "snap"},
        "format": {"options": ["czi"], "active": "czi"},
        "copy_to_output_root": {"options": [True, False], "active": True},
        "timeout_s": {"options": "float > 0 (wait for the CZI to be complete)", "active": 60.0},
    }


def canonical_stem(acquisition_type: str, position_label: str) -> str:
    """A file-name stem safe on Windows: ``<type>_<label>`` with odd characters replaced."""
    raw = f"{acquisition_type}_{position_label}"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_") or "acquisition"


def acquire(
    handle: ZenHandle, *, acquisition_type: str, position_label: str, options: dict | None = None
) -> dict:
    """Acquire with the loaded ZEN experiment and bring the CZI into the output folder.

    A snap by default; the whole experiment when ``mode`` is "experiment" or
    the acquisition type mentions a stack, tiles or a time lapse. ZEN writes
    ``<type>_<label>.czi`` into its image folder; that file is then copied to
    ``<output_root>/data/`` (when the ZEN folder is reachable from here). The
    record names both locations.
    """
    _require_open(handle)
    options = dict(options or {})
    if options.get("experiment"):
        handle.experiment = _cmd.load_experiment(handle.client, str(options["experiment"]))
    _require_experiment(handle, "acquire")
    fmt = str(options.get("format", "czi"))
    if fmt != "czi":
        raise ValueError(f"unknown format {fmt!r}; ZEN writes 'czi'")
    mode = options.get("mode")
    if mode is None:
        lowered = str(acquisition_type).lower()
        mode = "experiment" if any(t in lowered for t in EXPERIMENT_TYPES) else "snap"
    if mode not in ("snap", "experiment"):
        raise ValueError(f"unknown mode {mode!r}; choose 'snap' or 'experiment'")
    timeout = float(options.get("timeout_s", 60.0))

    started = time.perf_counter()
    output_name = canonical_stem(acquisition_type, position_label)
    run = _cmd.run_snap if mode == "snap" else _cmd.run_experiment
    result = run(handle.client, handle.experiment, output_name=output_name)
    _raise_if_failed(result, "acquire")
    status = result.get("status") or {}

    zen_path = zen_image_path(handle.client, result["output_name"])
    copied = False
    image_files = [str(zen_path)]
    if options.get("copy_to_output_root", True):
        data_dir = handle.output_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        dst = data_dir / f"{result['output_name']}.czi"
        try:
            _wait_stable(zen_path, timeout_s=timeout, poll_s=0.2)
            shutil.copy2(zen_path, dst)
            copied = True
            image_files = [str(dst)]
        except (TimeoutError, OSError) as exc:
            log.warning("CZI left on the ZEN computer (%s): %s", zen_path, exc)

    planes = status.get("images_count")
    return {
        "acquisition_type": acquisition_type,
        "position_label": position_label,
        "format": "czi",
        "mode": mode,
        "experiment": handle.experiment.name,
        "output_name": result["output_name"],
        "planes": planes if planes and planes > 0 else None,
        "image_files": image_files,
        "zen_image_path": str(zen_path),
        "copied": copied,
        "metadata_file": None,
        "status": status,
        "position": _user_xyz(handle, _raw_xyz(handle.client)),
        "duration_s": round(time.perf_counter() - started, 3),
    }


# =============================================================================
# info + registration
# =============================================================================


def get_info(handle: ZenHandle) -> dict:
    """Read-only extras: where the session started, the limits, the objectives, the output root."""
    _require_open(handle)
    return {
        "initial_position": dict(handle.initial_position),
        "limits": dict(handle.limits),
        "limits_file": str(handle.machine.limits_path()),
        "limits_are_defaults": handle.limits_are_defaults,
        "objectives": list(handle.immutable.get("objectives", [])),
        "output_root": str(handle.output_root),
        "image_output_path": handle.immutable.get("image_output_path"),
        "experiment": handle.experiment.name if handle.experiment else None,
        "server": dict(handle.immutable.get("runtime", {})),
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
    "run_procedure": run_procedure,
    "get_info": get_info,
}


def register(connection: dict | None = None) -> None:
    """Register the ZEISS driver with the ZMART controller registry (idempotent)."""
    try:
        from zmart_controller.registry import register as _register
    except Exception:  # noqa: BLE001 - controller optional at import time
        log.debug("zmart_controller not importable; skipping registration", exc_info=True)
        return
    _register(connection or dict(CONNECTION), ops=dict(OPS))


register()
