"""Mock microscope integration: a reference driver with no hardware.

It exercises the full controller contract so the package can be tested offline,
and it shows the shape a real driver implements: it receives the connection dict,
owns the frame origin (user coordinates are micrometers from it), and does the
work the controller does not -- settling before capture, saving, and
owning the mutable/immutable state boundary.

Driver contract used by the registry: ``connect(connection) -> handle`` opens a
session and returns an opaque handle; every other operation takes that handle as
its first argument.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Per-axis actuator options this instrument exposes (driver-defined).
_ACTUATORS: dict[str, list[str]] = {
    "x": ["motoric"],
    "y": ["motoric"],
    "z": ["motoric", "galvo", "piezo"],
}


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

    # active actuator per axis
    actuators: dict = field(
        default_factory=lambda: {"x": "motoric", "y": "motoric", "z": "motoric"}
    )

    # mutable instrument settings
    laser_power: float = 5.0
    gain: float = 1.0

    # immutable identity, plus connection info filled at connect
    serial: str = "MOCK-0001"
    client: str | None = None
    initial: list[dict] = field(default_factory=list)


def connect(connection: dict):
    """Open a session and capture the initial positions.

    Receives the whole variable connection dict; a real driver would validate the
    api and authenticate with e.g. ``connection["client"]`` / credentials. The
    origin defaults to the current position (zero), so ``set_xyz`` works at once.
    """
    handle = MockHandle()
    handle.client = connection.get("client")
    handle.initial = [
        {"x": 0.0, "y": 0.0, "z": 0.0},
        {"x": 120.0, "y": 0.0, "z": 0.0},
        {"x": 0.0, "y": 120.0, "z": 0.0},
    ]
    return handle


def set_origin(handle: MockHandle) -> dict:
    """Mark the current position as the origin -- it now reads (0, 0, 0)."""
    handle.origin_x = handle.x
    handle.origin_y = handle.y
    handle.origin_z = handle.z
    return {"origin": {"x": handle.origin_x, "y": handle.origin_y, "z": handle.origin_z}}


def get_actuators(handle: MockHandle) -> dict:
    """The actuator options each axis offers (driver-defined)."""
    return {axis: list(opts) for axis, opts in _ACTUATORS.items()}


def acquisition_options(handle: MockHandle) -> dict:
    """The acquisition + saving options this instrument offers (options + active).

    Driver-owned and answered on demand; the controller caches nothing.
    """
    return {
        "backlash_correction": {"options": [True, False], "active": True},
        "format": {"options": ["ome-tiff", "ome-zarr"], "active": "ome-tiff"},
        "procedure": {"options": ["direct", "tiled"], "active": "direct"},
    }


def _with_defaults(handle: MockHandle, options: dict | None) -> dict:
    """Fill omitted options from the active defaults (driver-side)."""
    resolved = {name: spec["active"] for name, spec in acquisition_options(handle).items()}
    if options:
        resolved.update(options)
    return resolved


def _resolve_actuators(handle: MockHandle, with_actuators: dict | None) -> dict[str, str]:
    """Per-axis actuator choice, validated and defaulting to the active one."""
    chosen = dict(handle.actuators)
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
    chosen = _resolve_actuators(handle, with_actuators)
    user = _user_position(handle)
    return {
        axis: {"value": user[axis], "actuator": chosen[axis], "unit": "um"}
        for axis in ("x", "y", "z")
    }


def set_xyz(
    handle: MockHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to an absolute target (um, relative to origin); return a move record.

    The chosen actuators realize the move. Mapping user coordinates to the raw
    position via the origin is the driver's arithmetic, not the controller's.
    """
    chosen = _resolve_actuators(handle, with_actuators)
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
    """Return the opaque state: immutable identity + mutable settings."""
    return {
        "immutable": {"serial": handle.serial},
        "mutable": {"laser_power": handle.laser_power, "gain": handle.gain},
    }


def set_state(handle: MockHandle, state: dict) -> dict:
    """Validate the immutable fingerprint, apply mutable settings, report what stuck."""
    immutable = state.get("immutable", {})
    if immutable.get("serial", handle.serial) != handle.serial:
        raise ValueError("state captured on a different instrument")
    mutable = state.get("mutable", {})
    applied = {}
    if "laser_power" in mutable:
        handle.laser_power = mutable["laser_power"]
        applied["laser_power"] = handle.laser_power
    if "gain" in mutable:
        handle.gain = mutable["gain"]
        applied["gain"] = handle.gain
    return {"applied": applied}


def get_procedures(handle: MockHandle) -> dict:
    """Return the named procedures this instrument offers."""
    return {
        "autofocus": {"description": "hardware autofocus"},
        "find_sample": {"description": "locate the sample"},
    }


def set_procedure(handle: MockHandle, procedure: dict) -> dict:
    """Run a procedure and report what ran."""
    return {"ran": dict(procedure)}


def get_context(handle: MockHandle) -> dict:
    """Whatever extra context the driver chooses to expose."""
    return {
        "initial_positions": [dict(pos) for pos in handle.initial],
        "client": handle.client,
    }


def register_mock() -> None:
    """Register this mock driver into the controller's registry.

    Shared by the test suite (conftest) and the runnable example so the wiring
    lives in one place.
    """
    from controller.registry import register

    register(
        {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api", "client": "mock-client"},
        ops={
            "connect": connect,
            "acquisition_options": acquisition_options,
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
