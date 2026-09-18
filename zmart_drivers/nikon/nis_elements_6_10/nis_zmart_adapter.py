"""
ZMART controller adapter for Nikon NIS-Elements.
================================================
The seam that plugs this driver into the vendor-agnostic **ZMART controller**
(``zmart_controller``). The controller drives every microscope through one
small ops table -- ``connect`` plus one callable per operation -- registered
under a ``connection`` identity dict. This module implements that table for
NIS-Elements (through the bridge, see ``bridge/nis_bridge.py``) and registers it.

As in the reference ``mock_driver``, the driver owns the frame **origin**: the
controller works in micrometres from an origin the driver subtracts, so the
controller never does coordinate maths. The driver also refuses any move
outside the stage limits NIS-Elements reports, and it does the capture+save in
one step.

What the neutral surface covers for Nikon today:

* **x/y/z** -- the XY stage and the main focus drive (single "motoric" actuator each).
* **z actuators** -- ``"motoric"`` (focus drive) and ``"piezo"`` when NIS
  reports a piezo insert.
* **changeable state** -- objective (nosepiece slot), optical configuration,
  camera exposure, PFS on/off.
* **procedures** -- ``autofocus`` (NIS image-based), ``live`` / ``freeze``,
  ``pfs_on`` / ``pfs_off``.
* **acquire** -- one snapshot, or a Z-stack when the acquisition type contains
  "stack", saved as TIFF / ND2 / OME-TIFF into ``<output_root>/data/``.

Register at import: importing this module (which ``import nis_elements_6_10`` does)
calls :func:`register` at the bottom of the file, so
``zmart_controller.get_instruments()`` lists the Nikon entry with no explicit
call. It is a safe no-op when ``zmart_controller`` is not installed.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .calibration import machine as _machine
from .commands import commands as _cmd
from .connection.session import close as _close
from .connection.session import connect as _connect
from .readers import readers as _readers

log = logging.getLogger(__name__)

# Reference actuator options per axis. When NIS reports a piezo Z insert,
# connect() adds "piezo" to z on the handle (see NisHandle.actuators).
_ACTUATORS: dict[str, list[str]] = {"x": ["motoric"], "y": ["motoric"], "z": ["motoric"]}

# The connection identity the ZMART controller keys on. ``microscope`` names a
# specific instrument; edit it (and host/port/output_root) per deployment.
CONNECTION = {
    "vendor": "nikon",
    "microscope": "ti2-simulator",
    "api": "nis-elements-bridge",
    "host": "127.0.0.1",
    "port": 54468,
}


@dataclass
class NisHandle:
    """Live session handle the controller passes back into every op."""

    client: Any
    connection: dict
    output_root: Path
    machine: Any
    limits: dict = field(default_factory=dict)
    origin: dict = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0})
    immutable: dict = field(default_factory=dict)
    initial_position: dict = field(default_factory=dict)
    # Per-axis actuator options, read at connect ("piezo" for z only when NIS reports one).
    actuators: dict = field(default_factory=lambda: {a: list(o) for a, o in _ACTUATORS.items()})
    # Raw piezo Z (um) that reads as zero when z is driven by the piezo; set by set_origin.
    piezo_origin: float = 0.0
    closed: bool = False


# =============================================================================
# lifecycle
# =============================================================================


def connect(connection: dict) -> NisHandle:
    """Open a session with the bridge and read what the microscope offers.

    Honours ``host`` / ``port`` / ``timeout`` (where the bridge listens),
    ``output_root`` (where ``acquire`` saves; a temp folder when omitted) and
    ``machine_root`` (override for the ProgramData root). The stage limits are
    read from NIS-Elements here and govern every move of the session; the
    frame origin a previous session persisted is restored.
    """
    client = _connect(connection)
    output_root = Path(connection.get("output_root") or tempfile.mkdtemp(prefix="nikon_run_"))
    output_root.mkdir(parents=True, exist_ok=True)
    machine = _machine.MachineProfile(
        microscope_id=connection.get("microscope") or CONNECTION["microscope"],
        programdata_root=connection.get("machine_root"),
    )
    info = _readers.get_bridge_info(client)
    devices = _readers.get_devices(client)
    limits = _readers.get_limits(client)
    z_drives = _readers.get_z_drives(client)
    pfs = _readers.get_pfs(client)
    devices["pfs"] = bool(pfs.get("present"))
    devices["piezo_z"] = z_drives.get("piezo_index", -1) >= 0
    handle = NisHandle(
        client=client,
        connection=dict(connection),
        output_root=output_root,
        machine=machine,
        limits=limits,
        immutable={
            "app": "NIS-Elements",
            "version": info.get("nis"),
            "bridge": info.get("bridge"),
            "microscope": connection.get("microscope"),
            "devices": devices,
            "host": client.host,
            "port": client.port,
        },
        initial_position=_readers.get_position(client),
    )
    if devices["piezo_z"]:
        handle.actuators["z"] = ["motoric", "piezo"]
    _restore_persisted_origin(handle)
    log.info("NIS-Elements controller session ready (output_root=%s)", output_root)
    return handle


def _restore_persisted_origin(handle: NisHandle) -> None:
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
        handle.piezo_origin = float(payload.get("piezo_origin", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("persisted origin is malformed (%s); frame is raw stage coordinates", exc)
        return
    log.info(
        "restored frame origin from %s", handle.machine.machine_dir() / _machine.ORIGIN_FILENAME
    )


def disconnect(handle: NisHandle) -> None:
    """Close the connection to the bridge (the bridge itself keeps running in NIS)."""
    handle.closed = True
    _close(handle.client)


def _require_open(handle: NisHandle) -> None:
    if handle.closed:
        raise RuntimeError("session is disconnected")


# =============================================================================
# frame origin
# =============================================================================


def set_origin(handle: NisHandle) -> dict:
    """Mark the current position as the origin -- it now reads (0, 0, 0).

    Persisted in the machine folder and restored by :func:`connect`, so the zero
    point survives reconnects until it is set again.
    """
    _require_open(handle)
    pos = _readers.get_position(handle.client)
    handle.origin = {axis: float(pos[axis]) for axis in ("x", "y", "z")}
    if "piezo" in handle.actuators["z"]:
        handle.piezo_origin = _piezo_z(handle)
    try:
        path = handle.machine.write_origin(
            {
                "origin": dict(handle.origin),
                "piezo_origin": handle.piezo_origin,
                "microscope": handle.immutable.get("microscope"),
                "captured_at": time.time(),
            }
        )
    except OSError as exc:
        raise RuntimeError(f"could not persist origin reference: {exc}") from exc
    return {"origin": dict(handle.origin), "origin_file": str(path)}


def _user_xyz(handle: NisHandle, pos: dict) -> dict[str, float]:
    return {axis: float(pos[axis]) - handle.origin[axis] for axis in ("x", "y", "z")}


# =============================================================================
# movement
# =============================================================================


def get_actuators(handle: NisHandle) -> dict:
    """The actuator options each axis offers.

    X and Y are always the motorised stage. Z offers ``"motoric"`` (the
    microscope's focus drive) and, when NIS reports a piezo insert,
    ``"piezo"`` as well. The list is read at connect and kept on the handle.
    """
    _require_open(handle)
    return {axis: list(opts) for axis, opts in handle.actuators.items()}


def _resolve_actuators(handle: NisHandle, with_actuators: dict | None) -> dict[str, str]:
    """Per-axis actuator choice for one call, validated; omitted axes use the reference one.

    Never sticky: a previous call's choice is not remembered.
    """
    chosen = {axis: opts[0] for axis, opts in handle.actuators.items()}
    if not with_actuators:
        return chosen
    for axis, actuator in with_actuators.items():
        if axis not in handle.actuators:
            raise ValueError(f"unknown axis {axis!r}")
        name = actuator[0] if isinstance(actuator, (list, tuple)) else actuator
        if name not in handle.actuators[axis]:
            raise ValueError(f"unknown actuator {actuator!r} for axis {axis!r}")
        chosen[axis] = name
    return chosen


def _piezo_z(handle: NisHandle) -> float:
    """Raw piezo Z (um), read from the drive NIS marks as the piezo."""
    drives = _readers.get_z_drives(handle.client)
    for drive in drives["drives"]:
        if drive["kind"] == "piezo":
            return float(drive["z"])
    raise RuntimeError("no piezo Z drive is connected")


def get_xyz(handle: NisHandle, *, with_actuators: dict | None = None) -> dict:
    """Report the position per axis (um, relative to the origin) with its actuator.

    With ``with_actuators={"z": "piezo"}`` the z value is the piezo insert's
    position (relative to the piezo origin), not the focus drive's.
    """
    _require_open(handle)
    chosen = _resolve_actuators(handle, with_actuators)
    user = _user_xyz(handle, _readers.get_position(handle.client))
    if chosen["z"] == "piezo":
        user["z"] = _piezo_z(handle) - handle.piezo_origin
    return {
        axis: {"value": user[axis], "actuator": chosen[axis], "unit": "um"}
        for axis in ("x", "y", "z")
    }


def set_xyz(
    handle: NisHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to an absolute target (um, relative to the origin); return a move record.

    The target is mapped to raw stage coordinates through the origin and checked
    against the stage limits before NIS-Elements is asked to move. With
    ``with_actuators={"z": "piezo"}`` the XY stage moves and the piezo insert
    takes the z target (relative to the piezo origin) while the focus drive stays
    put. The record carries the position NIS reported after the move.
    """
    _require_open(handle)
    chosen = _resolve_actuators(handle, with_actuators)
    targets = {
        axis: handle.origin[axis] + float(value) for axis, value in (("x", x), ("y", y), ("z", z))
    }
    try:
        if chosen["z"] == "piezo":
            _cmd.move_xy(handle.client, targets["x"], targets["y"], limits=handle.limits)
            piezo_z = _cmd.move_piezo_z(handle.client, handle.piezo_origin + float(z))
            confirmed = _user_xyz(handle, _readers.get_position(handle.client))
            confirmed["z"] = piezo_z - handle.piezo_origin
        else:
            raw = _cmd.move_xyz(
                handle.client, targets["x"], targets["y"], targets["z"], limits=handle.limits
            )
            confirmed = _user_xyz(handle, raw)
    except _cmd.LimitError as exc:
        raise RuntimeError(f"set_xyz refused: {exc}") from exc
    return {
        "position": {"x": float(x), "y": float(y), "z": float(z)},
        "confirmed": confirmed,
        "actuators": chosen,
    }


# =============================================================================
# state
# =============================================================================


def get_state(handle: NisHandle) -> dict:
    """Changeable settings first, then the observed report.

    Changeable: ``objective_position`` (nosepiece slot), ``exposure_ms`` (camera
    exposure) and ``pfs`` (Perfect Focus on/off, only when a PFS is present).
    Observed: identity, objectives, optical configurations, Z drives, PFS
    status, limits.
    """
    _require_open(handle)
    objectives = _readers.get_objectives(handle.client)
    configurations = _readers.get_optical_configurations(handle.client)
    pfs = _readers.get_pfs(handle.client)
    changeable: dict[str, Any] = {
        "objective_position": objectives.get("current"),
        "exposure_ms": _readers.get_exposure_ms(handle.client),
    }
    if pfs.get("present"):
        changeable["pfs"] = bool(pfs.get("on"))
    observed = dict(handle.immutable)
    observed["objectives"] = objectives.get("objectives", [])
    observed["optical_configurations"] = configurations
    observed["z_drives"] = _readers.get_z_drives(handle.client)
    observed["pfs"] = pfs
    observed["limits"] = dict(handle.limits)
    return {"changeable": changeable, "observed": observed}


def set_state(handle: NisHandle, state: dict) -> dict:
    """Apply the changeable settings; report what stuck.

    Accepts ``objective_position`` (1-based nosepiece position),
    ``optical_configuration`` (a name from the observed list), ``exposure_ms``
    and ``pfs`` (true/false). Applied in that order, so an exposure set here
    wins over the one an optical configuration brings along. ``observed`` is a
    report, never an instruction, and is not read here.
    """
    _require_open(handle)
    changeable = state.get("changeable") or {}
    applied: dict[str, Any] = {}
    if "optical_configuration" in changeable:
        applied["optical_configuration"] = _cmd.select_optical_configuration(
            handle.client, str(changeable["optical_configuration"])
        )
    if "objective_position" in changeable:
        applied["objective_position"] = _cmd.set_objective(
            handle.client, int(changeable["objective_position"])
        )
    if "exposure_ms" in changeable:
        applied["exposure_ms"] = _cmd.set_exposure_ms(
            handle.client, float(changeable["exposure_ms"])
        )
    if "pfs" in changeable:
        applied["pfs"] = bool(_cmd.set_pfs(handle.client, bool(changeable["pfs"]))["on"])
    return {"applied": applied}


# =============================================================================
# procedures
# =============================================================================


def get_procedures(handle: NisHandle) -> dict:
    """The named procedures this driver offers."""
    _require_open(handle)
    procedures = {
        "autofocus": {
            "description": "NIS image-based autofocus: sweep range_um around the current Z, "
            "stop on the sharpest plane",
            "args": ["range_um", "speed"],
        },
        "live": {"description": "start the live camera view in NIS-Elements"},
        "freeze": {"description": "stop the live view; the last frame stays as the current image"},
    }
    if handle.immutable.get("devices", {}).get("pfs"):
        procedures["pfs_on"] = {
            "description": "switch the Perfect Focus System on and wait for it to lock"
        }
        procedures["pfs_off"] = {"description": "switch the Perfect Focus System off"}
    return procedures


def run_procedure(handle: NisHandle, procedure: dict) -> dict:
    """Run a procedure. ``procedure`` is ``{"name": ..., ...args}``.

    ``autofocus`` reports the sharp z as ``frame_z_um`` (relative to the origin)
    and ``focus_um`` (raw), like the other drivers.
    """
    _require_open(handle)
    name = procedure.get("name")
    if name == "autofocus":
        result = _cmd.autofocus(
            handle.client,
            range_um=float(procedure.get("range_um", 50.0)),
            speed=int(procedure.get("speed", 30)),
            timeout=float(procedure.get("timeout", 300.0)),
        )
        raw_z = float(result["position"]["z"])
        return {
            "ran": name,
            "focus_um": raw_z,
            "frame_z_um": raw_z - handle.origin["z"],
            "duration_s": result.get("duration_s"),
        }
    if name == "live":
        _cmd.live(handle.client)
        return {"ran": name}
    if name == "freeze":
        _cmd.freeze(handle.client)
        return {"ran": name}
    if name in ("pfs_on", "pfs_off"):
        pfs = _cmd.set_pfs(
            handle.client, name == "pfs_on", timeout_s=float(procedure.get("timeout_s", 8.0))
        )
        return {"ran": name, "pfs": pfs}
    raise ValueError(f"unknown procedure {name!r}; known: {sorted(get_procedures(handle))}")


# =============================================================================
# acquire (captures and saves)
# =============================================================================


# What ``acquisition_type`` means here: anything containing "stack" acquires a
# Z-series; everything else takes one image.
STACK_TYPES = ("stack", "z_stack", "zstack", "z-stack")


def get_acquisition_options(handle: NisHandle) -> dict:
    """The acquisition + saving options this instrument offers (options + active).

    ``z_start`` / ``z_end`` / ``z_step`` are only read for a stack
    (``acquisition_type`` containing "stack"); they are in the same frame as
    ``set_xyz`` (um from the origin) and must lie inside the stage limits.
    """
    _require_open(handle)
    return {
        "format": {"options": list(_cmd.SAVE_FORMATS), "active": "tif"},
        "optical_configuration": {
            "options": _readers.get_optical_configurations(handle.client),
            "active": None,
        },
        "exposure_ms": {"options": "float > 0", "active": _readers.get_exposure_ms(handle.client)},
        "close_after_save": {"options": [True, False], "active": True},
        "z_start": {"options": "float um (stack only)", "active": None},
        "z_end": {"options": "float um (stack only)", "active": None},
        "z_step": {"options": "float um (stack only)", "active": 1.0},
    }


def canonical_stem(acquisition_type: str, position_label: str) -> str:
    """A file-name stem safe on Windows: ``<type>_<label>`` with odd characters replaced."""
    raw = f"{acquisition_type}_{position_label}"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_") or "acquisition"


def acquire(
    handle: NisHandle, *, acquisition_type: str, position_label: str, options: dict | None = None
) -> dict:
    """Take one image (or a Z-stack) and save it; return the record.

    Optionally switches the optical configuration and sets the exposure first.
    A stack needs ``z_start`` and ``z_end`` (um from the origin) and uses
    ``z_step``; it is best saved as ``nd2`` so every plane and all metadata
    survive. The file goes to ``<output_root>/data/<type>_<label>.<format>``
    and the NIS window is closed afterwards by default, so windows do not pile
    up during a scan.
    """
    _require_open(handle)
    options = dict(options or {})
    fmt = str(options.get("format", "tif"))
    if fmt not in _cmd.SAVE_FORMATS:
        raise ValueError(f"unknown format {fmt!r}; choose one of {_cmd.SAVE_FORMATS}")
    if options.get("optical_configuration"):
        _cmd.select_optical_configuration(handle.client, str(options["optical_configuration"]))
    if options.get("exposure_ms") is not None:
        _cmd.set_exposure_ms(handle.client, float(options["exposure_ms"]))
    timeout = float(options.get("timeout", 300.0))

    started = time.perf_counter()
    is_stack = any(token in str(acquisition_type).lower() for token in STACK_TYPES)
    if is_stack:
        if options.get("z_start") is None or options.get("z_end") is None:
            raise ValueError("a stack needs 'z_start' and 'z_end' (um from the origin) in options")
        z_top = handle.origin["z"] + float(options["z_end"])
        z_bottom = handle.origin["z"] + float(options["z_start"])
        try:
            image = _cmd.capture_z_stack(
                handle.client,
                z_top=z_top,
                z_bottom=z_bottom,
                z_step=float(options.get("z_step", 1.0)),
                limits=handle.limits,
                timeout=timeout,
            )
        except _cmd.LimitError as exc:
            raise RuntimeError(
                f"acquire refused: stack range outside the stage limits: {exc}"
            ) from exc
    else:
        image = _cmd.capture(handle.client, timeout=timeout)

    data_dir = handle.output_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{canonical_stem(acquisition_type, position_label)}.{fmt}"
    saved = _cmd.save_image(
        handle.client, str(path), format=fmt, close=bool(options.get("close_after_save", True))
    )
    return {
        "acquisition_type": acquisition_type,
        "position_label": position_label,
        "format": fmt,
        "planes": image.get("z_planes", image.get("planes")),
        "image_files": [saved["path"]],
        "metadata_file": None,
        "image": image,
        "position": _user_xyz(handle, _readers.get_position(handle.client)),
        "duration_s": round(time.perf_counter() - started, 3),
    }


# =============================================================================
# info + registration
# =============================================================================


def get_info(handle: NisHandle) -> dict:
    """Read-only extras: where the session started, the limits, the objectives, the output root."""
    _require_open(handle)
    return {
        "initial_position": dict(handle.initial_position),
        "limits": dict(handle.limits),
        "objectives": _readers.get_objectives(handle.client),
        "calibration": _readers.get_calibration(handle.client),
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
    "run_procedure": run_procedure,
    "get_info": get_info,
}


def register(connection: dict | None = None) -> None:
    """Register the Nikon driver with the ZMART controller registry (idempotent)."""
    try:
        from zmart_controller.registry import register as _register
    except Exception:  # noqa: BLE001 - controller optional at import time
        log.debug("zmart_controller not importable; skipping registration", exc_info=True)
        return
    _register(connection or dict(CONNECTION), ops=dict(OPS))


register()
