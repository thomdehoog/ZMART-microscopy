"""The mock microscope: a pretend instrument that lives in memory.

Use it to try every command without hardware, and read it as a complete
example of a driver::

    from zmart_controller import mock
    mock.register()

It does everything a real driver does and the controller does not: it loads
its origin at connect, refuses a closed connection, checks options, and keeps
the changeable and observed parts of the state apart.

Every function except ``connect`` and ``disconnect`` takes the handle first
and returns ``{"success": bool, "report": ...}``.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# The motors that can move each axis.
_ACTUATORS: dict[str, list[str]] = {
    "x": ["motoric"],
    "y": ["motoric"],
    "z": ["motoric", "galvo", "piezo"],
}

# The motor used when a call does not name one. A choice never carries over
# to the next call.
_DEFAULT_ACTUATORS: dict[str, str] = {"x": "motoric", "y": "motoric", "z": "motoric"}


@dataclass
class MockHandle:
    """The pretend instrument's state, standing in for a live connection.

    Positions the user sees are the raw stage position minus the origin.
    """

    # raw stage position, in micrometers
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    # the raw position that reads as (0, 0, 0)
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0

    # settings that set_state can change
    laser_power: float = 5.0
    gain: float = 1.0

    # identity and what connect was given
    serial: str = "MOCK-0001"
    client: str | None = None
    connection: dict = field(default_factory=dict)
    tile_positions: list[dict] = field(default_factory=list)

    # set by disconnect; every other function then refuses
    closed: bool = False


def connect(connection: dict):
    """Open a session.

    A real driver would log in here with what the connection dict holds, and
    load its saved origin. The mock takes an optional ``"origin"`` entry in
    the dict instead, ``{"x": ..., "y": ..., "z": ...}`` in raw micrometers.
    Without one the origin is zero.
    """
    handle = MockHandle()
    origin = connection.get("origin") or {}
    handle.origin_x = float(origin.get("x", 0.0))
    handle.origin_y = float(origin.get("y", 0.0))
    handle.origin_z = float(origin.get("z", 0.0))
    handle.client = connection.get("client")
    handle.connection = dict(connection)
    handle.tile_positions = [
        {"x": 0.0, "y": 0.0, "z": 0.0, "tile_size": {"x": 100.0, "y": 100.0}},
        {"x": 120.0, "y": 0.0, "z": 0.0, "tile_size": {"x": 100.0, "y": 100.0}},
        {"x": 0.0, "y": 120.0, "z": 0.0, "tile_size": {"x": 100.0, "y": 100.0}},
    ]
    return handle


def disconnect(handle: MockHandle) -> None:
    """Close the session. Every later call on this handle raises."""
    handle.closed = True


def _answer(report, *, success: bool = True) -> dict:
    """Wrap a report in the shape every command returns.

    Only outcomes that are safe to carry on from use ``success=False``.
    Anything unsafe is raised instead.
    """
    return {"success": success, "report": report}


def _require_open(handle: MockHandle) -> None:
    """Refuse a closed handle."""
    if handle.closed:
        raise RuntimeError("session is disconnected")


def get_actuators(handle: MockHandle) -> dict:
    """The motors that can move each axis."""
    _require_open(handle)
    return _answer({axis: list(opts) for axis, opts in _ACTUATORS.items()})


def get_acquisition_options(handle: MockHandle) -> dict:
    """The choices for capturing and saving, with allowed values and the active one."""
    _require_open(handle)
    return _answer(_menu())


def _menu() -> dict:
    return {
        "backlash_correction": {"options": [True, False], "active": True},
        "format": {"options": ["ome-tiff", "ome-zarr"], "active": "ome-tiff"},
        "procedure": {"options": ["direct", "tiled"], "active": "direct"},
    }


def _with_defaults(handle: MockHandle, options: dict | None) -> dict:
    """Check the options against the menu and fill in the ones left out."""
    menu = _menu()
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
    """The motor to use per axis: the one named, or the default."""
    chosen = dict(_DEFAULT_ACTUATORS)
    if with_actuators:
        for axis, actuator in with_actuators.items():
            if axis not in _ACTUATORS or actuator not in _ACTUATORS[axis]:
                raise ValueError(f"unknown actuator {actuator!r} for axis {axis!r}")
        chosen.update(with_actuators)
    return chosen


def _user_position(handle: MockHandle) -> dict[str, float]:
    """The position as the user sees it: raw minus origin."""
    return {
        "x": handle.x - handle.origin_x,
        "y": handle.y - handle.origin_y,
        "z": handle.z - handle.origin_z,
    }


def get_xyz(handle: MockHandle, *, with_actuators: dict | None = None) -> dict:
    """The position of each axis, in micrometers from the origin."""
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    user = _user_position(handle)
    return _answer(
        {
            axis: {"value": user[axis], "actuator": chosen[axis], "unit": "um"}
            for axis in ("x", "y", "z")
        }
    )


def set_xyz(
    handle: MockHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to a position, in micrometers from the origin.

    Adding the origin back is the driver's arithmetic, never the controller's.
    """
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    handle.x = handle.origin_x + x
    handle.y = handle.origin_y + y
    handle.z = handle.origin_z + z
    return _answer({"position": {"x": x, "y": y, "z": z}, "actuators": chosen})


def acquire(
    handle: MockHandle, *, acquisition_type: str, position_label: str, options: dict | None = None
) -> dict:
    """Capture one image and save it, in one step.

    Options left out keep their active value.
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
    return _answer(record)


def get_state(handle: MockHandle) -> dict:
    """The settings that can be changed, and a read-only description of the instrument."""
    _require_open(handle)
    return _answer(
        {
            "changeable": {"laser_power": handle.laser_power, "gain": handle.gain},
            "observed": {
                "serial": handle.serial,
                "pixel_size": {"x": 1.0, "y": 1.0, "unit": "um"},
                "frame_size": {"x": 1024.0, "y": 1024.0, "unit": "um"},
            },
        }
    )


def set_state(handle: MockHandle, state: dict) -> dict:
    """Apply the ``changeable`` settings and report which ones were applied.

    ``observed`` is never read. If no setting is one this microscope knows,
    nothing changes and ``success`` is False. That is safe to carry on from,
    so it is reported, not raised.
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
    return _answer({"applied": applied}, success=bool(applied))


def get_procedures(handle: MockHandle) -> dict:
    """The routines this microscope offers."""
    _require_open(handle)
    return _answer(
        {
            "autofocus": {"description": "hardware autofocus"},
            "find_sample": {"description": "locate the sample"},
        }
    )


def run_procedure(handle: MockHandle, procedure: dict) -> dict:
    """Run one routine by name. An unknown name is refused."""
    _require_open(handle)
    name = procedure.get("name")
    if name not in ("autofocus", "find_sample"):
        raise ValueError(f"unknown procedure {name!r}")
    if name == "autofocus":
        # Report the sharp z in the user's frame, as real drivers do. For the
        # mock, "sharp" is wherever the stage is now.
        frame_z = handle.z - handle.origin_z
        return _answer({"ran": name, "focus_um": handle.z, "frame_z_um": frame_z})
    return _answer({"ran": name})


def get_info(handle: MockHandle) -> dict:
    """Describe the setup: where images go, plus this mock's extras."""
    _require_open(handle)
    root = Path(handle.connection.get("output_root") or "mock-output")
    return _answer(
        {
            "tile_positions": [dict(pos) for pos in handle.tile_positions],
            "focus_positions": [
                {"x": pos["x"], "y": pos["y"], "z": pos["z"]} for pos in handle.tile_positions
            ],
            "client": handle.client,
            "output_root": str(root),
        }
    )


def register() -> None:
    """Plug the mock in, so :func:`zmart_controller.get_instruments` lists it.

    A real driver does the same, usually when its module is imported.
    """
    from zmart_controller.registry import register

    register(
        {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api", "client": "mock-client"},
        ops={
            "connect": connect,
            "disconnect": disconnect,
            "get_acquisition_options": get_acquisition_options,
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
