"""Mock microscope integration: a reference driver with no hardware.

It exercises the full controller contract so the package can be tested offline,
and it shows the shape a real driver implements: it receives the connection dict,
owns the frame origin (user coordinates are micrometers from it), and does the
work the controller does not -- settling before capture, saving, and
owning the changeable/observed state boundary.

Driver contract used by the registry: ``connect(connection) -> handle`` opens a
session and returns an opaque handle; every other operation takes that handle as
its first argument.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Per-axis actuator options this instrument exposes (driver-defined).
_ACTUATORS: dict[str, list[str]] = {
    "x": ["motoric"],
    "y": ["motoric"],
    "z": ["motoric", "galvo", "piezo"],
}

# Fixed defaults for axes omitted from ``with_actuators`` (the reference
# actuator per axis) — never sticky: a previous call's choice is not state.
_DEFAULT_ACTUATORS: dict[str, str] = {"x": "motoric", "y": "motoric", "z": "motoric"}


@dataclass
class MockHandle:
    """In-memory instrument state standing in for a live connection.

    Stores the raw motoric position (um) and the origin; user coordinates are raw
    minus origin. The driver owns that arithmetic.
    """

    # raw motoric position, micrometers
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    # frame origin (the raw position that reads as zero)
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0

    # mutable instrument settings
    laser_power: float = 5.0
    gain: float = 1.0

    # immutable identity, plus connection info filled at connect
    serial: str = "MOCK-0001"
    client: str | None = None
    connection: dict = field(default_factory=dict)
    tile_positions: list[dict] = field(default_factory=list)

    # set by disconnect(); every other op refuses a closed handle
    closed: bool = False


def connect(connection: dict):
    """Open a session with a small vendor-authored tile setup.

    Receives the whole variable connection dict; a real driver would validate the
    api and authenticate with e.g. ``connection["client"]`` / credentials. The
    origin defaults to the current position (zero), so ``set_xyz`` works at once.
    """
    handle = MockHandle()
    handle.client = connection.get("client")
    handle.connection = dict(connection)
    handle.tile_positions = [
        {"x": 0.0, "y": 0.0, "z": 0.0, "tile_size": {"x": 100.0, "y": 100.0}},
        {"x": 120.0, "y": 0.0, "z": 0.0, "tile_size": {"x": 100.0, "y": 100.0}},
        {"x": 0.0, "y": 120.0, "z": 0.0, "tile_size": {"x": 100.0, "y": 100.0}},
    ]
    return handle


def disconnect(handle: MockHandle) -> None:
    """Close the session; every subsequent op on the handle raises.

    A real driver would release its client connection here.
    """
    handle.closed = True


def _require_open(handle: MockHandle) -> None:
    """Refuse to drive a disconnected handle -- a real connection would be dead."""
    if handle.closed:
        raise RuntimeError("session is disconnected")


def set_origin(handle: MockHandle) -> dict:
    """Mark the current position as the origin -- it now reads (0, 0, 0)."""
    _require_open(handle)
    handle.origin_x = handle.x
    handle.origin_y = handle.y
    handle.origin_z = handle.z
    return {"origin": {"x": handle.origin_x, "y": handle.origin_y, "z": handle.origin_z}}


def get_actuators(handle: MockHandle) -> dict:
    """The actuator options each axis offers (driver-defined)."""
    _require_open(handle)
    return {axis: list(opts) for axis, opts in _ACTUATORS.items()}


def get_acquisition_options(handle: MockHandle) -> dict:
    """The acquisition + saving options this instrument offers (options + active).

    Driver-owned and answered on demand; the controller caches nothing.
    """
    _require_open(handle)
    return {
        "backlash_correction": {"options": [True, False], "active": True},
        "format": {"options": ["ome-tiff", "ome-zarr"], "active": "ome-tiff"},
        "procedure": {"options": ["direct", "tiled"], "active": "direct"},
    }


def _with_defaults(handle: MockHandle, options: dict | None) -> dict:
    """Validate options against the menu, filling omissions from the active defaults."""
    menu = get_acquisition_options(handle)
    resolved = {name: spec["active"] for name, spec in menu.items()}
    if options:
        for name, value in options.items():
            if name not in menu:
                raise ValueError(f"unknown acquisition option {name!r}")
            if value not in menu[name]["options"]:
                raise ValueError(f"invalid value {value!r} for acquisition option {name!r}")
        resolved.update(options)
    return resolved


def _resolve_actuators(with_actuators: dict | None) -> dict[str, str]:
    """Per-axis actuator choice, validated, over the fixed reference defaults.

    Never sticky: a previous call's selection is not state — omitted axes
    always resolve to the reference actuator.
    """
    chosen = dict(_DEFAULT_ACTUATORS)
    if with_actuators:
        for axis, actuator in with_actuators.items():
            if axis not in _ACTUATORS or actuator not in _ACTUATORS[axis]:
                raise ValueError(f"unknown actuator {actuator!r} for axis {axis!r}")
        chosen.update(with_actuators)
    return chosen


def _user_position(handle: MockHandle) -> dict[str, float]:
    """Raw position minus origin -- the coordinates the workflow sees."""
    return {
        "x": handle.x - handle.origin_x,
        "y": handle.y - handle.origin_y,
        "z": handle.z - handle.origin_z,
    }


def get_xyz(handle: MockHandle, *, with_actuators: dict | None = None) -> dict:
    """Report the position per axis (um, relative to origin) with its actuator."""
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    user = _user_position(handle)
    return {
        axis: {"value": user[axis], "actuator": chosen[axis], "unit": "um"}
        for axis in ("x", "y", "z")
    }


def set_xyz(
    handle: MockHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to an absolute target (um, relative to origin); return a move record.

    The chosen actuators realize this move only — the selection is never
    remembered (omitted axes always default to the reference actuator).
    Mapping user coordinates to the raw position via the origin is the driver's
    arithmetic, not the controller's.
    """
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    handle.x = handle.origin_x + x
    handle.y = handle.origin_y + y
    handle.z = handle.origin_z + z
    return {"position": {"x": x, "y": y, "z": z}, "actuators": chosen}


def acquire(
    handle: MockHandle, *, acquisition_type: str, position_label: str, options: dict | None = None
) -> dict:
    """Capture a frame and save it, returning the record.

    ``acquisition_type`` is the scan kind; ``position_label`` names the output.
    The driver fills omitted options (acquisition + saving) from its active
    defaults. Captures and saves in one step -- there is no separate export.
    """
    _require_open(handle)
    options = _with_defaults(handle, options)
    settle = "backlash-corrected" if options["backlash_correction"] else "direct"
    record = {
        "acquisition_type": acquisition_type,
        "position_label": position_label,
        "filename": f"{position_label}.{options['format'].split('-')[-1]}",
        "format": options["format"],
        "procedure": options["procedure"],
        "settle": settle,
        "position": _user_position(handle),
    }
    return record


def get_state(handle: MockHandle) -> dict:
    """Return the opaque state: the changeable settings first, then the
    observed report (identity and condition, read-only)."""
    _require_open(handle)
    return {
        "changeable": {"laser_power": handle.laser_power, "gain": handle.gain},
        "observed": {
            "serial": handle.serial,
            "pixel_size": {"x": 1.0, "y": 1.0, "unit": "um"},
        },
    }


def set_state(handle: MockHandle, state: dict) -> dict:
    """Apply the changeable settings; report what stuck.

    ``observed`` is a report, never an instruction — it is not read here
    (operator decision: the identity gate returns only if the changeable
    part ever grows beyond low-risk settings).
    """
    _require_open(handle)
    changeable = state.get("changeable", {})
    applied = {}
    if "laser_power" in changeable:
        handle.laser_power = changeable["laser_power"]
        applied["laser_power"] = handle.laser_power
    if "gain" in changeable:
        handle.gain = changeable["gain"]
        applied["gain"] = handle.gain
    return {"applied": applied}


def get_procedures(handle: MockHandle) -> dict:
    """Return the named procedures this instrument offers."""
    _require_open(handle)
    return {
        "autofocus": {"description": "hardware autofocus"},
        "find_sample": {"description": "locate the sample"},
    }


def run_procedure(handle: MockHandle, procedure: dict) -> dict:
    """Run a procedure and report what ran."""
    _require_open(handle)
    name = procedure.get("name")
    if name == "autofocus":
        # Mirror the real drivers' contract: report the sharp z in frame
        # terms (``frame_z_um``). The mock's "sharp" z is simply wherever
        # the stage currently sits, which is deterministic and lets the
        # workflow's focus step run end-to-end offline.
        frame_z = handle.z - handle.origin_z
        return {"ran": dict(procedure), "focus_um": handle.z, "frame_z_um": frame_z}
    return {"ran": dict(procedure)}


def get_info(handle: MockHandle) -> dict:
    """Return the live vendor-authored setup and resolved output root."""
    _require_open(handle)
    root = Path(handle.connection.get("output_root") or "mock-output")
    return {
        "tile_positions": [dict(pos) for pos in handle.tile_positions],
        "focus_positions": [
            {"x": pos["x"], "y": pos["y"], "z": pos["z"]}
            for pos in handle.tile_positions
        ],
        "client": handle.client,
        "output_root": str(root),
    }


def register_mock() -> None:
    """Register this mock driver into the controller's registry.

    Shared by the test suite (conftest) and the runnable example so the wiring
    lives in one place.
    """
    from zmart_controller.registry import register

    register(
        {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api", "client": "mock-client"},
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
            "run_procedure": run_procedure,
            "get_info": get_info,
        },
    )
