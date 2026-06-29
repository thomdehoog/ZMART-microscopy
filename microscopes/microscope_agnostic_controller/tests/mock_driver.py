"""Mock microscope integration: a reference driver with no hardware.

It exercises the full controller contract so the package can be tested offline,
and it shows the shape a real driver implements: it receives context (objective,
stage, actuator) and does the work the controller does not -- applying the
objective offset, settling before capture, saving, and owning the
mutable/immutable state boundary.

Driver contract used by the registry: ``connect(**ctx) -> handle`` opens a
session and returns an opaque handle; every other operation takes that handle as
its first argument.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Objective parcentricity offsets in micrometres, in the motoric coordinate
# system, relative to the 10x baseline. A real driver reads these from calibration.
_OBJECTIVE_OFFSETS: dict[str, tuple[float, float]] = {
    "10x": (0.0, 0.0),
    "20x": (1.5, -0.8),
    "40x": (2.1, 0.4),
}

# Stage types this instrument exposes (declared at registration so they are
# discoverable before connecting).
_STAGE_OPTIONS: list[str] = ["motoric", "galvo", "piezo"]


@dataclass
class MockHandle:
    """In-memory instrument state standing in for a live connection."""

    objective: str = "10x"
    stage_type: str = "motoric"

    # canonical position in the motoric coordinate system
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    connected: bool = True
    acquired: list[dict] = field(default_factory=list)

    # mutable instrument settings (captured and reapplied)
    laser_power: float = 5.0
    gain: float = 1.0

    # immutable identity
    serial: str = "MOCK-0001"
    initial: list[dict] = field(default_factory=list)
    last_procedure: dict = field(default_factory=dict)


def connect(*, microscope: str, api: str, client: str | None = None, password: str | None = None):
    """Open a session and capture initial positions.

    A real driver would also validate the api and authenticate with
    ``client`` / ``password``.
    """
    handle = MockHandle()
    handle.initial = [
        {"x": 0.0, "y": 0.0, "z": 0.0},
        {"x": 120.0, "y": 0.0, "z": 0.0},
        {"x": 0.0, "y": 120.0, "z": 0.0},
    ]
    return handle


def set_coordinate_system(
    handle: MockHandle, *, objective: str | None = None, stage_type: str | None = None
) -> None:
    """Fix the reference objective and/or stage, validating the choices.

    A real driver would also move to the objective and pick up its calibration.
    """
    if objective is not None:
        if objective not in _OBJECTIVE_OFFSETS:
            raise ValueError(f"unknown objective {objective!r}")
        handle.objective = objective

    if stage_type is not None:
        if stage_type not in _STAGE_OPTIONS:
            raise ValueError(f"unknown stage {stage_type!r}")
        handle.stage_type = stage_type


def disconnect(handle: MockHandle) -> None:
    """Mark the handle disconnected (no real resource to release)."""
    handle.connected = False


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


def _resolve_stage_types(handle: MockHandle, with_stage_types: dict | None) -> dict[str, str]:
    """Per-axis actuator choice, defaulting unspecified axes to the active one."""
    chosen = {"x": handle.stage_type, "y": handle.stage_type, "z": handle.stage_type}
    if with_stage_types:
        chosen.update(with_stage_types)
    return chosen


def get_xyz(handle: MockHandle, *, with_stage_types: dict | None = None) -> dict:
    """Report the canonical position per axis with its actuator and unit."""
    chosen = _resolve_stage_types(handle, with_stage_types)
    return {
        axis: {"value": getattr(handle, axis), "stage": chosen[axis], "unit": "um"}
        for axis in ("x", "y", "z")
    }


def set_xyz(
    handle: MockHandle, x: float, y: float, z: float, *, with_stage_types: dict | None = None
) -> None:
    """Realize an absolute target in the motoric coordinate system, applying the offset.

    The chosen actuator (``with_stage_types``) realizes the move. The mock folds
    the objective offset into the stored position to make that ownership visible
    in tests; a real driver would apply it when commanding the actuator.
    """
    _resolve_stage_types(handle, with_stage_types)  # actuator selection (no-op in the mock)
    off_x, off_y = _OBJECTIVE_OFFSETS[handle.objective]
    handle.x, handle.y, handle.z = x + off_x, y + off_y, z


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
        "position": {"x": handle.x, "y": handle.y, "z": handle.z},
        "objective": handle.objective,
    }
    handle.acquired.append(record)
    return record


def get_state(handle: MockHandle) -> dict:
    """Return the opaque state: immutable identity + mutable settings."""
    return {
        "immutable": {"serial": handle.serial, "objective": handle.objective},
        "mutable": {"laser_power": handle.laser_power, "gain": handle.gain},
    }


def set_state(handle: MockHandle, state: dict) -> dict:
    """Validate the immutable fingerprint, apply the mutable settings, report what was applied."""
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
    """Run a procedure and report it ran (the mock records the last one run)."""
    handle.last_procedure = dict(procedure)
    return {"ran": handle.last_procedure}


def get_context(handle: MockHandle) -> dict:
    """Whatever extra context the driver chooses to expose."""
    return {
        "initial_positions": [dict(pos) for pos in handle.initial],
        "serial": handle.serial,
        "objective": handle.objective,
        "stage_type": handle.stage_type,
    }


def register_mock() -> None:
    """Register this mock driver into the controller's registry.

    Shared by the test suite (conftest) and the runnable example so the wiring
    lives in one place.
    """
    from microscope_agnostic_controller.registry import register

    register(
        "mock",
        "mock-scope",
        "mock-api",
        ops={
            "connect": connect,
            "acquisition_options": acquisition_options,
            "set_coordinate_system": set_coordinate_system,
            "get_xyz": get_xyz,
            "set_xyz": set_xyz,
            "acquire": acquire,
            "get_state": get_state,
            "set_state": set_state,
            "get_procedures": get_procedures,
            "set_procedure": set_procedure,
            "get_context": get_context,
            "disconnect": disconnect,
        },
        objective_options=list(_OBJECTIVE_OFFSETS),
        stage_options=_STAGE_OPTIONS,
    )
