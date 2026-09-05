"""How this microscope is set up: the Leica's side of the ZMART setup seam.

Where :mod:`zmart_adapter` is what a *session* drives this microscope through,
this is what the *setup workflow* configures it through, and the two are
registered with different registries on purpose: nothing holding a controller
session can reach anything here. See :mod:`zmart_setup` for why that
separation is a safety property.

What this supplies is the small vocabulary that package asks of every driver,
mapped onto the functions the three set-up notebooks already use:

- ``open`` is :func:`navigator_expert.connect_microscope` with the calibration
  left unloaded, exactly as the notebooks open, so that a microscope nobody has
  configured yet can still be reached. The limits handshake still runs: with
  no published envelope the bundled default governs, and the hardcoded
  physical backstop bounds every move regardless.
- ``where`` / ``move`` are the stage readers and the gated, verified movers
  the calibration notebooks use (:func:`move_xy_and_verify`,
  :func:`move_zwide_and_verify`).
- ``acquire`` is the driver's own acquire-and-save, saving **raw** pixels
  (an explicit identity orientation), because measuring the orientation needs
  the picture as the camera recorded it.
- ``objective`` observes which lens is in; it never commands one.
- ``markers`` reads the four Point markers the operator placed in the active
  LAS X template, through :func:`capture_adaptive_xy_limits`, which is the
  one genuinely vendor-shaped read in the whole procedure.
- ``read`` / ``publish`` resolve and write the four dated snapshots under
  ProgramData through :class:`MachineProfile`, with each subsystem's own
  validation in front of the write.

Everything measured from the pictures -- which way the camera is turned, how
the lenses line up -- happens in ``zmart_analysis``, not here.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import navigator_expert as drv
from navigator_expert.acquisition.naming import Naming, run_hash
from navigator_expert.config import machine as _machine
from navigator_expert.limits import config as _limits_config
from navigator_expert.limits import checks as _limits_checks
from navigator_expert.orientation import Orientation
from navigator_expert.readers import parsing as _parsing

from . import zmart_adapter as _adapter

log = logging.getLogger(__name__)

#: The same identity the operating adapter registers under, so the instrument
#: an operator connected to on the page is the one whose setup is offered.
CONNECTION = {
    key: _adapter.CONNECTION[key] for key in ("vendor", "microscope", "api", "client", "api_delay_ms")
}

#: The limits document as the step shows it: this driver's axes, the objective
#: slots, and the twenty settings it can fence. The keys are the file's own.
LIMITS_DOCUMENT = {
    "axes": [
        {"key": "x_um", "label": "X", "unit": "µm"},
        {"key": "y_um", "label": "Y", "unit": "µm"},
        {"key": "z_galvo_um", "label": "Z galvo", "unit": "µm"},
        {"key": "z_wide_um", "label": "Z wide", "unit": "µm",
         "note": "Starts at zero: the wide stage cannot travel to a negative position."},
    ],
    "measured": ["x_um", "y_um"],
    # Every stage range is required: limits.json refuses an axis without one.
    "required": ["x_um", "y_um", "z_galvo_um", "z_wide_um"],
    "slots": {"key": "objective_slot", "label": "Objective slots",
              "note": "Empty means every slot the turret reports. Slots count from zero."},
    "settings": list(_limits_checks.SETTER_LIMIT_KEYS),
}


@dataclass
class SetupHandle:
    """The CAM client opened for configuration, plus what this side remembers."""

    client: Any
    connection: dict = field(default_factory=dict)
    hash6: str = ""
    closed: bool = False
    #: The last adaptive XY capture, kept so the template trio it archived can
    #: travel with the limits when they are published.
    last_markers: dict | None = None


def _require_open(handle: SetupHandle) -> None:
    if handle.closed:
        raise RuntimeError("setup is closed")


def _job(handle: SetupHandle) -> str:
    selected = drv.get_selected_job(handle.client) or {}
    name = str(selected.get("Name") or "").strip()
    if not name:
        raise RuntimeError("No Navigator Expert job is selected in LAS X.")
    return name


# ---------------------------------------------------------------------------
# open / close / describe
# ---------------------------------------------------------------------------


def open_setup(connection: dict) -> SetupHandle:
    """Open the CAM client the way the notebooks do: limits loaded (default or
    published), calibration left unloaded, so a fresh machine can be reached."""
    client = drv.connect_microscope(
        client_name=connection.get("client", "PythonClient"),
        api_delay_ms=connection.get("api_delay_ms"),
        load_limits=True,
        load_calibration=False,
        configuration=connection.get("configuration"),
    )
    return SetupHandle(client=client, connection=dict(connection), hash6=run_hash())


def close_setup(handle: SetupHandle) -> None:
    handle.closed = True


def describe(handle: SetupHandle) -> dict:
    _require_open(handle)
    machine = _machine.MACHINE
    checks = {
        "api": "answering" if _adapter._try(lambda: drv.ping(handle.client)) else "failed — no answer",
        "limits": _say_limits_source(machine),
        "configuration": machine.snapshot_root().name,
    }
    return {
        "label": "Leica Stellaris 5 · Navigator Expert",
        "checks": checks,
        "subsystems": {
            "limits": {"supported": True, "document": LIMITS_DOCUMENT},
            "orientation": {"supported": True},
            "calibration": {"supported": True},
            "origin": {"supported": True},
        },
    }


def _say_limits_source(machine) -> str:
    latest = machine.latest_snapshot("limits")
    return "published" if latest is not None else "default (fallback) — publish limits first"


# ---------------------------------------------------------------------------
# where / move / acquire / objective / markers
# ---------------------------------------------------------------------------


def where(handle: SetupHandle) -> dict:
    """Absolute stage XY and the wide Z drive, in micrometres, plus every
    drive's own reading -- motoric X and Y, Z-wide, Z-galvo -- and the
    objective, which is what an origin record is made of."""
    _require_open(handle)
    xy = drv.get_xy(handle.client) or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    job = _job(handle)
    z_wide = float(drv.read_zwide_um(handle.client, job))
    settings = drv.get_job_settings(handle.client, job) or {}
    z_galvo = _adapter._try(lambda: float(
        _adapter._z_um_from_settings(settings, "z-galvo", client=handle.client, job_name=job)))
    lens = settings.get("objective") or {}
    actuators = {
        "x motoric": {"value": float(xy["x_um"]), "unit": "um"},
        "y motoric": {"value": float(xy["y_um"]), "unit": "um"},
        "z-wide": {"value": z_wide, "unit": "um"},
    }
    if z_galvo is not None:
        actuators["z-galvo"] = {"value": z_galvo, "unit": "um"}
    return {
        "x_um": float(xy["x_um"]), "y_um": float(xy["y_um"]), "z_um": z_wide,
        "actuators": actuators,
        "objective": {"slot": lens.get("slotIndex"), "name": lens.get("name")} if lens else None,
    }


def move(handle: SetupHandle, x_um: float, y_um: float, z_um: float) -> dict:
    """Move XY and the wide Z drive through the gated, verified movers, and
    answer with where the stage was read back to be."""
    _require_open(handle)
    from navigator_expert.calibration.core.common import move_xy_and_verify, move_zwide_and_verify

    here = where(handle)
    if abs(here["z_um"] - z_um) > 1e-6:
        move_zwide_and_verify(handle.client, _job(handle), float(z_um))
    if abs(here["x_um"] - x_um) > 1e-6 or abs(here["y_um"] - y_um) > 1e-6:
        move_xy_and_verify(handle.client, float(x_um), float(y_um))
    return where(handle)


def acquire(handle: SetupHandle, *, into: str, name: str, z_um: list[float] | None = None) -> dict:
    """One raw frame under the selected job, or a stack of them at ``z_um``,
    saved under ``into`` with the driver's own naming. Raw: the picture as the
    camera recorded it, before any orientation correction."""
    _require_open(handle)
    from navigator_expert.calibration.core.common import move_zwide_and_verify

    job = _job(handle)
    folder = Path(into)
    folder.mkdir(parents=True, exist_ok=True)
    heights = [None] if not z_um else [float(z) for z in z_um]
    paths: list[str] = []
    pixel_um = None
    frame_px = None
    for index, height in enumerate(heights):
        if height is not None:
            move_zwide_and_verify(handle.client, job, height)
        naming = Naming(acquisition_type="setup", hash6=handle.hash6, position_label=f"{name}_{index:05d}")
        acq = drv.acquire(handle.client, job)
        saved = drv.save(handle.client, acq, folder / name, naming, orientation=Orientation())
        for _index, path in sorted(saved.image_paths.items()):
            paths.append(str(path))
        if pixel_um is None:
            settings = drv.get_job_settings(handle.client, job) or {}
            geometry = _parsing.parse_tile_geometry(settings) or {}
            pixel_um = geometry.get("pixel_w_um")
            frame_px = [geometry.get("pixels_x"), geometry.get("pixels_y")]
    return {
        "images": paths,
        "z_um": [h for h in heights if h is not None] or [where(handle)["z_um"]],
        "pixel_um": float(pixel_um) if pixel_um is not None else None,
        "frame_px": frame_px,
        "job": job,
        "position": where(handle),
    }


def objective(handle: SetupHandle) -> dict:
    """Which lens is in, observed from the selected job -- never commanded."""
    _require_open(handle)
    job = _job(handle)
    settings = drv.get_job_settings(handle.client, job) or {}
    lens = settings.get("objective") or {}
    slot = lens.get("slotIndex")
    if slot is None:
        raise RuntimeError(f"could not read the active objective slot from job {job!r}")
    geometry = _parsing.parse_tile_geometry(settings) or {}
    return {
        "slot": int(slot),
        "name": str(lens.get("name") or "").strip() or f"slot {slot}",
        "pixel_um": geometry.get("pixel_w_um"),
    }


def objectives(handle: SetupHandle) -> list:
    """Every lens the turret holds, from the instrument's hardware report."""
    _require_open(handle)
    from navigator_expert.commands import objectives as _objectives

    hw = drv.get_hardware_info(handle.client) or {}
    found = []
    for slot, entry in sorted(_objectives.objective_by_slot(hw).items()):
        name = entry.get("name") if isinstance(entry, dict) else str(entry)
        found.append({"slot": int(slot), "name": str(name or f"slot {slot}").strip()})
    return found


def markers(handle: SetupHandle) -> dict:
    """The four Point markers the operator placed at the safe corners in the
    active LAS X template, read without changing that template. The saved
    template trio is kept so it can be archived with the limits."""
    _require_open(handle)
    from navigator_expert.limits.adaptive import capture_adaptive_xy_limits

    captured = capture_adaptive_xy_limits(handle.client)
    handle.last_markers = captured
    x = captured["limits"]["x_um"]["range"]
    y = captured["limits"]["y_um"]["range"]
    return {
        "points": [
            {"x_um": x[0], "y_um": y[0]}, {"x_um": x[1], "y_um": y[0]},
            {"x_um": x[1], "y_um": y[1]}, {"x_um": x[0], "y_um": y[1]},
        ],
        "template_paths": list(captured.get("template_paths") or []),
    }


# ---------------------------------------------------------------------------
# the four documents
# ---------------------------------------------------------------------------


def read(handle: SetupHandle, subsystem: str, *, fresh: bool = False) -> dict:
    """The document that stands: the newest snapshot, else the bundled default
    -- or the bundled default regardless, for a setup that starts over."""
    _require_open(handle)
    machine = _machine.MACHINE
    if fresh:
        if subsystem == "origin":
            return {"document": {}, "source": "none", "path": None}
        filename = {"limits": _machine.LIMITS_FILENAME, "orientation": _machine.ORIENTATION_FILENAME,
                    "calibration": _machine.CALIBRATION_FILENAME}.get(subsystem)
        if filename is None:
            raise ValueError(f"unknown subsystem {subsystem!r}")
        path = machine.bundled_default_path(filename)
        return {"document": json.loads(Path(path).read_text(encoding="utf-8")), "source": "default", "path": str(path)}
    if subsystem == "origin":
        payload = machine.read_origin()
        if payload is None:
            return {"document": {}, "source": "none", "path": None}
        return {"document": payload, "source": "published", "path": str(machine.origin_path())}
    # Resolving seeds a first snapshot from the bundled default where the
    # driver allows it (orientation, calibration), so the path alone does not
    # say whether anyone measured anything. The document does: an orientation
    # says whether it was measured, and a calibration with no objectives was
    # never adopted. Limits are the exception: the driver refuses to seed them,
    # because their mere presence under ProgramData means operator-published.
    evidence: list = []
    if subsystem == "limits":
        try:
            path, _ = machine.resolve(_machine.LIMITS_FILENAME)
            source = "published"
        except FileNotFoundError:
            path, source = machine.bundled_default_path(_machine.LIMITS_FILENAME), "default"
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    elif subsystem == "orientation":
        path, _ = machine.resolve(_machine.ORIENTATION_FILENAME)
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        evidence = _evidence(Path(path).parent, _machine.ORIENTATION_FILENAME)
        source = "published" if document.get("measured") else "default"
    elif subsystem == "calibration":
        path, _ = machine.resolve_calibration()
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        source = "published" if document.get("objectives") else "default"
    else:
        raise ValueError(f"unknown subsystem {subsystem!r}")
    if subsystem == "calibration":
        evidence = _evidence(Path(path).parent, _machine.CALIBRATION_FILENAME)
    return {"document": document, "source": source, "path": str(path),
            "evidence": evidence if source == "published" else []}


def publish(handle: SetupHandle, subsystem: str, document: dict, evidence=()) -> dict:
    """Validate the way each subsystem validates, then append a dated snapshot.

    ``evidence`` -- the figures and numbers behind the document -- is archived
    into the orientation and calibration snapshots, which the machine profile
    already archives files into; limits and origin have their own archiving
    (the LAS X template) or none, and keep no evidence.
    """
    _require_open(handle)
    machine = _machine.MACHINE
    moment = datetime.now(timezone.utc)
    archive = [str(p) for p in (evidence or ()) if Path(p).is_file()]
    if subsystem == "limits":
        template_paths = (handle.last_markers or {}).get("template_paths") or ()
        published = _limits_config.adopt_limits(
            document, machine=machine, moment=moment, template_paths=template_paths,
        )
        snapshot = Path(published["snapshot"])
        return {"path": str(published["limits_path"]), "snapshot": str(snapshot)}
    if subsystem == "orientation":
        # The document names the turn and the mirror; the driver derives the
        # rest (the sign convention) from those, so the two cannot disagree.
        from navigator_expert.orientation import orientation_config

        orientation = Orientation(
            rotate_deg=int(document["rotation_deg"]), mirrored=bool(document["reflection"]),
        )
        snapshot = machine.publish_snapshot(
            moment, orientation=orientation_config(orientation, measured=True), archive_paths=archive,
        )
        return {"path": str(snapshot / _machine.ORIENTATION_FILENAME), "snapshot": str(snapshot),
                "evidence": _evidence(snapshot, _machine.ORIENTATION_FILENAME)}
    if subsystem == "calibration":
        from navigator_expert.calibration.core import model as _model

        config = _model.prepared_calibration(document)
        name = document.get("calibration_name")
        snapshot = machine.publish_snapshot(
            moment, calibration=config, calibration_name=name, archive_paths=archive,
        )
        relpath = machine.calibration_relpath(name) if name else Path("calibration.json")
        return {"path": str(snapshot / relpath), "snapshot": str(snapshot), "calibration_name": name,
                "evidence": _evidence(snapshot, _machine.CALIBRATION_FILENAME)}
    if subsystem == "origin":
        payload = _origin_payload(handle, document)
        path = machine.write_origin(payload, moment=moment)
        return {"path": str(path), "snapshot": str(path.parent)}
    raise ValueError(f"unknown subsystem {subsystem!r}")


def _evidence(snapshot: Path, document_name: str) -> list[str]:
    """The figures and numbers archived beside a snapshot's document: its
    top-level PNG and JSON files, the document itself aside."""
    if not snapshot.is_dir():
        return []
    return sorted(
        str(p) for p in snapshot.iterdir()
        if p.is_file() and p.suffix in (".png", ".json") and p.name != document_name
    )


def _origin_payload(handle: SetupHandle, document: dict) -> dict:
    """The record :func:`zmart_adapter.connect` reads back. Given only where
    the stage stands (``x_um``, ``y_um``, ``z_um``), the rest -- both z
    drives, their focus sum, the objective -- is read off the instrument so
    the record is complete in the shape the frame maths needs."""
    if all(key in document for key in ("x_um", "y_um", "z_wide_um", "z_galvo_um", "z_focus_um")):
        origin = {key: float(document[key]) for key in ("x_um", "y_um", "z_wide_um", "z_galvo_um", "z_focus_um")}
        origin["objective"] = document.get("objective")
        return {"origin": origin, "job": document.get("job"), "session_hash6": handle.hash6,
                "captured_at": time.time()}
    job = _job(handle)
    settings = drv.get_job_settings(handle.client, job) or {}
    z_wide = _adapter._z_um_from_settings(settings, "z-wide", client=handle.client, job_name=job)
    z_galvo = _adapter._z_um_from_settings(settings, "z-galvo", client=handle.client, job_name=job)
    here = where(handle)
    return {
        "origin": {
            "x_um": float(document.get("x_um", here["x_um"])),
            "y_um": float(document.get("y_um", here["y_um"])),
            "z_wide_um": float(z_wide),
            "z_galvo_um": float(z_galvo),
            "z_focus_um": float(z_wide) + float(z_galvo),
            "objective": settings.get("objective"),
        },
        "job": job,
        "session_hash6": handle.hash6,
        "captured_at": time.time(),
    }


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def configurations(connection: dict | None = None) -> list:
    """Every configuration this microscope has, newest first, as a listing
    shows them. Needs no connection: they are folders under ProgramData."""
    machine = _machine.MACHINE
    return [machine.describe_configuration(path) for path in reversed(machine.configurations())]


def new_configuration(handle) -> dict:
    """Start a configuration as a full copy of what stands now, and stand on it."""
    _require_open(handle)
    machine = _machine.MACHINE
    path = machine.new_configuration()
    _machine.use_configuration(path.name)
    return machine.describe_configuration(path)


def use_configuration(handle, configuration: str) -> dict:
    """Stand on one of this microscope's configurations, by id."""
    _require_open(handle)
    _machine.use_configuration(str(configuration))
    return _machine.MACHINE.describe_configuration(_machine.MACHINE.snapshot_root())


def configuration(handle) -> dict | None:
    """The configuration this setup stands on, if one has been chosen."""
    _require_open(handle)
    chosen = _machine.chosen_configuration()
    return None if chosen is None else _machine.MACHINE.describe_configuration(_machine.MACHINE.api_root() / chosen)


def register() -> None:
    """Register this microscope's setup with ``zmart_setup`` -- and only there."""
    from zmart_setup.registry import register as _register

    _register(
        CONNECTION,
        ops={
            "open": open_setup,
            "close": close_setup,
            "describe": describe,
            "where": where,
            "move": move,
            "acquire": acquire,
            "objective": objective,
            "objectives": objectives,
            "markers": markers,
            "configurations": configurations,
            "new_configuration": new_configuration,
            "use_configuration": use_configuration,
            "configuration": configuration,
            "read": read,
            "publish": publish,
        },
    )


register()
