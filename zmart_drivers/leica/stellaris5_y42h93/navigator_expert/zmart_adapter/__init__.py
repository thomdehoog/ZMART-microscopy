"""ZMART Controller adapter for the Navigator Expert driver.

The ops table that plugs this driver into ``zmart_controller``: one
function per controller op, each taking the opaque handle as its first
argument. The controller stays vendor-free — this module (not the
controller) knows both contracts, and importing it registers the
instrument::

    import zmart_controller
    import zmart_drivers.leica.stellaris5_y42h93.navigator_expert.zmart_adapter  # registers

    instrument = next(
        i for i in zmart_controller.get_instruments() if i["vendor"] == "leica"
    )
    instrument["output_root"] = r"D:\\smart_output"   # where acquire() saves
    zmart_controller.set_instrument(instrument)

Frame math lives here: the driver speaks absolute stage micrometres, the
controller speaks micrometres relative to the origin set by
``set_origin``. The driver package itself is untouched.

Scope of v1 (grow as needed):
    - ``get_state``/``set_state`` round-trip the selected job (the job
      is LAS X's unit of configuration, so reapplying the selection
      restores the whole setup).
    - ``get_procedures`` offers backlash takeup only.
    - ``acquire`` maps ``acquisition_type`` -> the driver's Naming slot
      convention and ``options["job"]`` -> the LAS X job to run.

Dependency direction:
    - Imports: driver internals, ``zmart_controller.registry``,
      ``shared.output_layout``.
    - Imported by: nothing in the driver — workflows opt in explicitly.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.output_layout import Naming
from shared.output_layout.naming import run_hash
from zmart_controller import registry as _registry

from .. import readers as _readers
from ..acquisition import capture as _capture
from ..acquisition import save as _save
from ..commands import commands as _commands
from ..commands import settings as _cmd_settings
from ..connection import session as _session
from ..motion import movement as _motion

log = logging.getLogger(__name__)

CONNECTION = {
    "vendor": "leica",
    "microscope": "stellaris5-y42h93",
    "api": "navigator-expert",
    # driver-specific connect params — edit before set_instrument():
    "client": "PythonClient",
    "api_delay_ms": None,
    "output_root": None,  # required by acquire(): where products are saved
}

_ACTUATORS = {"x": ("motoric",), "y": ("motoric",), "z": ("z-wide", "z-galvo")}

# controller actuator name -> driver move_z z_mode
_Z_MODES = {"z-wide": "zwide", "z-galvo": "galvo"}


@dataclass
class ZmartHandle:
    """Opaque controller handle: client + frame origin + adapter state."""

    client: Any
    connection: dict
    hash6: str
    origin: dict = field(
        default_factory=lambda: {
            "x_um": 0.0,
            "y_um": 0.0,
            "z_wide_um": 0.0,
            "z_galvo_um": 0.0,
            "z_focus_um": 0.0,
            "objective": None,
        }
    )
    actuators: dict[str, str] = field(
        default_factory=lambda: {"x": "motoric", "y": "motoric", "z": "z-wide"}
    )
    position_counter: int = 0
    closed: bool = False


def _require_open(handle: ZmartHandle) -> None:
    if handle.closed:
        raise RuntimeError("session is disconnected")


# =============================================================================
# Lifecycle
# =============================================================================


def connect(connection: dict) -> ZmartHandle:
    """Open the CAM client and return the controller handle."""
    client = _session.connect_python_client(
        client_name=connection.get("client", "PythonClient"),
        api_delay_ms=connection.get("api_delay_ms"),
    )
    return ZmartHandle(client=client, connection=dict(connection), hash6=run_hash())


def disconnect(handle: ZmartHandle) -> None:
    """Mark the handle closed; the CAM client itself has no teardown."""
    handle.closed = True


# =============================================================================
# Frame and movement
# =============================================================================


def _z_um_from_settings(settings: dict, key: str) -> float:
    """One z drive's live position (um) from raw job settings."""
    ch = _cmd_settings.make_changeable_copy(settings)
    if not ch or "zPosition" not in ch:
        raise RuntimeError("zPosition not in job settings - LAS X version mismatch?")
    val = ch["zPosition"].get(key)
    if isinstance(val, dict):
        val = val.get("position")
    if val is None:
        raise RuntimeError(f"{key} readback missing; got {ch['zPosition']!r}")
    return float(val)


def _hardware_snapshot(handle: ZmartHandle) -> dict:
    """One consistent read of everything the frame math needs.

    Stage XY, both z drives, and the current objective come from the
    authoritative API route; raises when any of them is unreadable.
    """
    xy = _readers.get_xy(handle.client, mode="api")
    if not xy:
        raise RuntimeError("could not read stage XY position")
    job = _selected_job_name(handle)
    settings = _readers.get_job_settings(handle.client, job, mode="api")
    if not settings:
        raise RuntimeError(f"could not read job settings for '{job}'")
    return {
        "job": job,
        "x_um": float(xy["x_um"]),
        "y_um": float(xy["y_um"]),
        "z_wide_um": _z_um_from_settings(settings, "z-wide"),
        "z_galvo_um": _z_um_from_settings(settings, "z-galvo"),
        "objective": settings.get("objective"),
    }


def _warn_on_objective_change(handle: ZmartHandle, snapshot: dict) -> None:
    origin_obj = (handle.origin.get("objective") or {}).get("name")
    current_obj = (snapshot.get("objective") or {}).get("name")
    if origin_obj and current_obj and origin_obj != current_obj:
        log.warning(
            "objective changed since set_origin ('%s' -> '%s'); frame positions "
            "do not account for parfocality/parcentricity offsets",
            origin_obj,
            current_obj,
        )


def _selected_job_name(handle: ZmartHandle) -> str:
    selected = _readers.get_selected_job(handle.client, mode="api")
    name = selected.get("Name") if selected else None
    if not name:
        raise RuntimeError("could not determine the selected LAS X job")
    return name


def set_origin(handle: ZmartHandle) -> dict:
    """The current position becomes (0, 0, 0) of the controller frame.

    Captures stage XY, both z drives, their focus sum, and the current
    objective as the zero point, and persists that reference to
    ``origin.json`` under ``connection['output_root']`` (memory-only,
    with a warning, when no output root is configured).
    """
    _require_open(handle)
    snap = _hardware_snapshot(handle)
    handle.origin = {
        "x_um": snap["x_um"],
        "y_um": snap["y_um"],
        "z_wide_um": snap["z_wide_um"],
        "z_galvo_um": snap["z_galvo_um"],
        "z_focus_um": snap["z_wide_um"] + snap["z_galvo_um"],
        "objective": snap["objective"],
    }
    origin_file = None
    output_root = handle.connection.get("output_root")
    if output_root:
        path = Path(output_root) / "origin.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "origin": handle.origin,
                    "job": snap["job"],
                    "session_hash6": handle.hash6,
                    "captured_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        origin_file = str(path)
    else:
        log.warning("set_origin: no output_root configured; origin kept in memory only")
    return {
        "origin": {"x": 0.0, "y": 0.0, "z": 0.0},
        "reference": dict(handle.origin),
        "origin_file": origin_file,
    }


def get_actuators(handle: ZmartHandle) -> dict:
    _require_open(handle)
    return {axis: list(opts) for axis, opts in _ACTUATORS.items()}


def _resolve_actuators(handle: ZmartHandle, with_actuators: dict | None) -> dict[str, str]:
    chosen = dict(handle.actuators)
    for axis, actuator in (with_actuators or {}).items():
        if actuator not in _ACTUATORS.get(axis, ()):
            raise ValueError(f"unknown actuator {actuator!r} for axis {axis!r}")
        chosen[axis] = actuator
    return chosen


def get_xyz(handle: ZmartHandle, *, with_actuators: dict | None = None) -> dict:
    """Position per axis in the frame (um from the origin), plus raw hardware.

    The frame ``z`` is the *focus* displacement: (z-wide + z-galvo) minus
    the origin's focus sum, so it reads the same regardless of which drive
    realized the move. The untranslated stage values (XY, both z drives,
    objective) ride along under ``"hardware"``.
    """
    _require_open(handle)
    chosen = _resolve_actuators(handle, with_actuators)
    snap = _hardware_snapshot(handle)
    _warn_on_objective_change(handle, snap)
    z_focus = snap["z_wide_um"] + snap["z_galvo_um"]
    frame = {
        "x": snap["x_um"] - handle.origin["x_um"],
        "y": snap["y_um"] - handle.origin["y_um"],
        "z": z_focus - handle.origin["z_focus_um"],
    }
    result = {
        axis: {"value": frame[axis], "unit": "um", "actuator": chosen[axis]}
        for axis in ("x", "y", "z")
    }
    result["hardware"] = {
        "x_um": snap["x_um"],
        "y_um": snap["y_um"],
        "z_wide_um": snap["z_wide_um"],
        "z_galvo_um": snap["z_galvo_um"],
        "objective": snap["objective"],
        "job": snap["job"],
    }
    return result


def set_xyz(
    handle: ZmartHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to (x, y, z) in the frame; confirmed or this raises.

    Stage behind the controller: XY targets are origin + frame value on
    the motoric stage. Frame ``z`` is a *focus* target — the two drives
    sum, so the chosen actuator moves to::

        target_drive = origin_focus + z - other_drive_current

    i.e. z-wide absorbs the target while whatever z-galvo offset is
    parked stays accounted for, and vice versa. (Additive combination —
    validate the sign convention live before trusting large z moves.)
    """
    _require_open(handle)
    chosen = _resolve_actuators(handle, with_actuators)
    handle.actuators = chosen
    snap = _hardware_snapshot(handle)
    _warn_on_objective_change(handle, snap)
    abs_x = handle.origin["x_um"] + x
    abs_y = handle.origin["y_um"] + y
    target_focus = handle.origin["z_focus_um"] + z
    if chosen["z"] == "z-wide":
        z_target = target_focus - snap["z_galvo_um"]
    else:
        z_target = target_focus - snap["z_wide_um"]

    # Backlash-compensated transit raises unless the readback confirms.
    _motion.move_xy_with_backlash(handle.client, abs_x, abs_y)

    z_mode = _Z_MODES[chosen["z"]]
    z_result = _commands.move_z(handle.client, snap["job"], z_target, unit="um", z_mode=z_mode)
    if not z_result.get("success") or not z_result.get("confirmed"):
        raise RuntimeError(f"move_z ({chosen['z']}) failed or was unconfirmed: {z_result}")

    return {
        "position": {"x": x, "y": y, "z": z},
        "actuators": dict(chosen),
        "hardware_targets": {
            "x_um": abs_x,
            "y_um": abs_y,
            f"{chosen['z'].replace('-', '_')}_um": z_target,
        },
    }


# =============================================================================
# Acquisition (captures and saves)
# =============================================================================


def get_acquisition_options(handle: ZmartHandle) -> dict:
    _require_open(handle)
    jobs = _readers.get_jobs(handle.client, mode="api") or []
    names = [j["Name"] for j in jobs if j.get("Name")]
    selected = next((j["Name"] for j in jobs if j.get("IsSelected")), None)
    return {
        "job": {"options": names, "active": selected},
        "backlash_correction": {"options": [True, False], "active": True},
        "format": {"options": ["ome-tiff"], "active": "ome-tiff"},
        "exporter": {
            "options": ["navigator_expert", "lasx_native_autosave"],
            "active": _save.active_save_exporter(),
        },
        "cleanup_source": {"options": [True, False], "active": False},
    }


def _with_defaults(handle: ZmartHandle, options: dict | None) -> dict:
    """Validate options against the live menu, filling omissions from actives."""
    menu = get_acquisition_options(handle)
    resolved = {name: spec["active"] for name, spec in menu.items()}
    for name, value in (options or {}).items():
        if name not in menu:
            raise ValueError(f"unknown acquisition option {name!r}")
        if value not in menu[name]["options"]:
            raise ValueError(f"invalid value {value!r} for acquisition option {name!r}")
        resolved[name] = value
    return resolved


def acquire(
    handle: ZmartHandle,
    *,
    acquisition_type: str,
    position_label: str,
    options: dict | None = None,
) -> dict:
    """Run the job, wait for the export, and persist the OME-TIFF product."""
    _require_open(handle)
    output_root = handle.connection.get("output_root")
    if not output_root:
        raise RuntimeError(
            "acquire needs connection['output_root'] — set it on the "
            "instrument dict before set_instrument()"
        )
    resolved = _with_defaults(handle, options)
    job = resolved["job"]
    if not job:
        raise RuntimeError("no LAS X job selected and none passed via options['job']")

    if job != _selected_job_name(handle):
        select = _commands.select_job(handle.client, job)
        if not select.get("success"):
            raise RuntimeError(f"select_job('{job}') failed: {select}")

    if resolved["backlash_correction"]:
        _motion.correct_backlash(handle.client)

    acq = _capture.acquire(handle.client, job)

    # Propagation: acquisition_type becomes the Naming slot that names the
    # output folder/files; position_label maps onto the p slot when numeric
    # (a per-session counter otherwise) and always travels verbatim in the
    # lineage record that save() writes into summary.json.
    handle.position_counter += 1
    p = int(position_label) if str(position_label).isdigit() else handle.position_counter
    naming = Naming(acquisition_type=acquisition_type, hash6=handle.hash6, p=p)
    saved = _save.save(
        handle.client,
        acq,
        Path(output_root),
        naming,
        lineage={
            "acquisition_type": acquisition_type,
            "position_label": str(position_label),
            "job": job,
            "session_hash6": handle.hash6,
        },
        exporter=resolved["exporter"],
        cleanup_source=resolved["cleanup_source"],
    )

    return {
        "acquisition_type": acquisition_type,
        "position_label": position_label,
        "job": job,
        "format": resolved["format"],
        "settle": "backlash-corrected" if resolved["backlash_correction"] else "direct",
        "images": sorted(str(path) for path in saved.image_paths.values()),
        "xml": sorted(str(path) for path in saved.xml_paths.values()),
    }


# =============================================================================
# State and procedures
# =============================================================================


def get_state(handle: ZmartHandle) -> dict:
    """Immutable fingerprint + the mutable settings v1 can round-trip.

    Mutable is deliberately just the selected job: the job *is* the unit
    of configuration in LAS X (each job carries its own optics/scan
    settings), so capture-and-reapply of the selection round-trips the
    whole setup without this adapter re-implementing per-setting state.
    """
    _require_open(handle)
    hw = _readers.get_hardware_info(handle.client, mode="api") or {}
    return {
        "immutable": {"microscope": (hw.get("Microscope") or {}).get("name")},
        "mutable": {"job": _selected_job_name(handle)},
    }


def set_state(handle: ZmartHandle, state: dict) -> dict:
    """Reapply the mutable part; report what stuck."""
    _require_open(handle)
    immutable = state.get("immutable", {})
    current = get_state(handle)["immutable"]
    if immutable and immutable.get("microscope", current["microscope"]) != current["microscope"]:
        raise ValueError("state captured on a different instrument")

    applied: dict[str, Any] = {}
    job = state.get("mutable", {}).get("job")
    if job and job != _selected_job_name(handle):
        result = _commands.select_job(handle.client, job)
        if not result.get("success"):
            raise RuntimeError(f"select_job('{job}') failed: {result}")
        applied["job"] = job
    return {"applied": applied}


def get_procedures(handle: ZmartHandle) -> dict:
    _require_open(handle)
    return {
        "backlash_takeup": {
            "description": "pin the XY leadscrew slack at the current position (+X +Y approach)"
        },
    }


def set_procedure(handle: ZmartHandle, procedure: dict) -> dict:
    _require_open(handle)
    name = procedure.get("name")
    if name == "backlash_takeup":
        _motion.correct_backlash(handle.client)
        return {"ran": dict(procedure)}
    raise ValueError(f"unknown procedure {name!r}")


# =============================================================================
# Context and registration
# =============================================================================


def get_context(handle: ZmartHandle) -> dict:
    _require_open(handle)
    return {
        "selected_job": _selected_job_name(handle),
        "client": handle.connection.get("client"),
        "output_root": handle.connection.get("output_root"),
        "session_hash6": handle.hash6,
    }


def register() -> None:
    """Register this instrument's ops table with the controller registry."""
    _registry.register(
        CONNECTION,
        ops={
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
        },
    )


register()
