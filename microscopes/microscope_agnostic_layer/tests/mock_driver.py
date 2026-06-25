"""Mock microscope integration -- a reference driver with no hardware.

It exercises the full agnostic contract so the orchestrator can be tested
offline, and it shows the shape a real driver implements: it receives context
(objective, stage frame, actuator) and does the work the layer does not --
applying the objective offset, settling before capture, owning the
mutable/immutable state boundary.

Driver contract used by the registry:

* ``connect(**ctx) -> handle`` opens a session and returns an opaque handle.
* every other operation takes that handle as its first argument.
* ``capabilities(handle) -> dict`` reports options + active selection.

Each function below is what an entry in the registry's ops table points at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Objective parcentricity offsets in motoric-frame micrometres, relative to the
# 10x baseline. A real driver reads these from calibration.
_OBJECTIVE_OFFSETS: dict[str, tuple[float, float]] = {
    "10x": (0.0, 0.0),
    "20x": (1.5, -0.8),
    "40x": (2.1, 0.4),
}


@dataclass
class MockHandle:
    """In-memory instrument state standing in for a live connection.

    Holds the canonical position, the captured-at-connect initial positions, the
    mutable settings (reactivatable) and the immutable identity (fingerprint).
    """

    objective: str
    stage_type: str
    x: float = 0.0  # canonical position in the motoric frame
    y: float = 0.0
    z: float = 0.0
    connected: bool = True
    acquired: list[dict] = field(default_factory=list)
    # mutable instrument settings (captured and reactivated)
    laser_power: float = 5.0
    gain: float = 1.0
    # immutable identity
    serial: str = "MOCK-0001"
    procedure: dict = field(default_factory=lambda: {"name": "default", "steps": []})
    initial: dict = field(default_factory=dict)


def connect(
    *,
    microscope: str,
    api: str,
    client: str | None,
    password: str | None,
    objective: str,
    stage_type: str,
) -> MockHandle:
    """Open a session and capture initial positions.

    Validates the requested objective (a real driver would also validate the api
    and authenticate with ``client``/``password``).
    """
    if objective not in _OBJECTIVE_OFFSETS:
        raise ValueError(f"unknown objective {objective!r}")
    handle = MockHandle(objective=objective, stage_type=stage_type)
    # Capture initial positions at connect, available for later reactivation.
    handle.initial = {"x": handle.x, "y": handle.y, "z": handle.z}
    return handle


def disconnect(handle: MockHandle) -> None:
    """Mark the handle disconnected (no real resource to release)."""
    handle.connected = False


def capabilities(handle: MockHandle) -> dict:
    """Report the selectable options and the active selection, discovered here.

    Each axis is ``{"options": [...], "active": ...}``. The orchestrator reuses
    these identifiers as the legal vocabulary for ``stages`` / ``format`` /
    ``procedure`` arguments.
    """
    return {
        "objective": {"options": list(_OBJECTIVE_OFFSETS), "active": handle.objective},
        "stages": {
            "x": {"options": ["motoric", "galvo"], "active": handle.stage_type},
            "y": {"options": ["motoric", "galvo"], "active": handle.stage_type},
            "z": {"options": ["motoric", "piezo"], "active": handle.stage_type},
        },
        "save_format": {"options": ["ome-tiff", "ome-zarr"], "active": "ome-tiff"},
        "save_procedure": {"options": ["direct", "tiled"], "active": "direct"},
    }


def _resolve_stages(handle: MockHandle, stages: dict | None) -> dict[str, str]:
    """Per-axis actuator choice, defaulting unspecified axes to the active frame."""
    chosen = {"x": handle.stage_type, "y": handle.stage_type, "z": handle.stage_type}
    if stages:
        chosen.update(stages)
    return chosen


def get_xyz(handle: MockHandle, *, stages: dict | None = None) -> dict:
    """Report the canonical position per axis with its actuator and unit."""
    chosen = _resolve_stages(handle, stages)
    return {
        axis: {"value": getattr(handle, axis), "stage": chosen[axis], "unit": "um"}
        for axis in ("x", "y", "z")
    }


def set_xyz(
    handle: MockHandle, x: float, y: float, z: float, *, stages: dict | None = None
) -> None:
    """Realize an absolute motoric-frame target, applying the objective offset.

    The target is in the motoric frame; the chosen actuator (``stages``) realizes
    it. Applying the objective offset is the driver's responsibility, not the
    layer's. The mock folds the offset straight into the stored position to make
    that ownership visible in tests; a real driver would instead apply it when
    commanding the actuator and keep the canonical value unchanged.
    """
    _resolve_stages(handle, stages)  # actuator selection (no-op in the mock)
    off_x, off_y = _OBJECTIVE_OFFSETS[handle.objective]
    handle.x, handle.y, handle.z = x + off_x, y + off_y, z


def acquire(handle: MockHandle, *, backlash_correction: bool = True) -> dict:
    """Capture a frame, settling per ``backlash_correction`` before the capture.

    Records the settle mode in the returned frame so tests can confirm the
    acquisition-time intent reached the driver.
    """
    settle = "backlash-corrected" if backlash_correction else "direct"
    frame = {
        "pixels": [[0, 1], [1, 0]],
        "position": {"x": handle.x, "y": handle.y, "z": handle.z},
        "objective": handle.objective,
        "settle": settle,
    }
    handle.acquired.append(frame)
    return frame


def save(
    handle: MockHandle,
    *,
    format: str,
    procedure: str,
    name: str | None,
    position: Any,
) -> dict:
    """Return a save record for the acquired frames.

    Raises if nothing has been acquired yet. ``format``/``procedure`` arrive
    already resolved to concrete values by the orchestrator.
    """
    if not handle.acquired:
        raise RuntimeError("nothing acquired to save")
    return {
        "format": format,
        "procedure": procedure,
        "name": name or "untitled",
        "position": position,
        "frames": len(handle.acquired),
    }


def get_state(handle: MockHandle) -> dict:
    """Return the opaque state: immutable identity + mutable settings."""
    return {
        "immutable": {"serial": handle.serial, "objective": handle.objective},
        "mutable": {"laser_power": handle.laser_power, "gain": handle.gain},
    }


def set_state(handle: MockHandle, state: dict) -> None:
    """Validate the immutable fingerprint, then apply only the mutable settings.

    Demonstrates that the driver -- not the layer -- owns the mutable/immutable
    boundary: a state captured on a different instrument (serial mismatch) is
    rejected, and immutable fields are never written.
    """
    immutable = state.get("immutable", {})
    if immutable.get("serial", handle.serial) != handle.serial:
        raise ValueError("state captured on a different instrument")
    mutable = state.get("mutable", {})
    if "laser_power" in mutable:
        handle.laser_power = mutable["laser_power"]
    if "gain" in mutable:
        handle.gain = mutable["gain"]


def get_procedure(handle: MockHandle) -> dict:
    """Return a copy of the current procedure dict."""
    return dict(handle.procedure)


def set_procedure(handle: MockHandle, procedure: dict) -> None:
    """Replace the current procedure with a copy of the given dict."""
    handle.procedure = dict(procedure)


def get_initial_positions(handle: MockHandle) -> dict:
    """Return a copy of the positions captured at connect."""
    return dict(handle.initial)
