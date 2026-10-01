"""The mock microscope's ZMART controller plugin: the 11 functions.

This is part 8 of the driver anatomy. It presents the driver to the ZMART
Controller in the shape every microscope shares, and it does nothing else:
no coordinate arithmetic and no safety checks of its own. Those happened
further down. Each function here only maps a controller command onto the
driver's get commands, set commands, procedures and data handling.

The mock is a complete driver, built from the same parts a real one has::

    vendor_interface/   talks to MockScope Control, the pretend vendor software
    error_handling/     sorts every problem into a kind, and says what to do
    get_commands/       asks the microscope things, through the get dispatcher
    set_commands/       changes the microscope, through the set dispatcher
    procedures/         recipes: autofocus, backlash takeup, parking the piezo
    data_handling/      turns the vendor's files into OME-TIFF or OME-Zarr
    configuration/      origin, registration, limits, calibration
    zmart_controller/   this plugin
    testing/            the mock API and everything else for testing

Plug it in like any driver::

    zmart_controller.register_driver("zmart_driver_mock")

The connection dictionary may hold ``output_root`` (where images are
saved), ``token`` (the vendor login, default ``"mock-token"``) and
``mock_timing``: ``"realistic"`` (the default) lets moves and acquisitions
take time, ``"instant"`` makes them finish at once.

Every function except ``connect`` and ``disconnect`` takes the handle first
and returns ``{"success": bool, "report": ...}``.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import inspect
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zmart_driver_mock import get_commands as get
from zmart_driver_mock import set_commands as setter
from zmart_driver_mock.configuration import Configuration, load_configuration, user_range
from zmart_driver_mock.data_handling import FORMATS, CommandLog, save_acquisition
from zmart_driver_mock.data_handling.save import safe_name
from zmart_driver_mock.error_handling import classify
from zmart_driver_mock.get_commands import GetDispatcher
from zmart_driver_mock.procedures import PROCEDURES
from zmart_driver_mock.set_commands import Gate, SetDispatcher
from zmart_driver_mock.vendor_interface import MockScopeConnection

logger = logging.getLogger("zmart_driver_mock")

# Where images go when the connection does not say: a folder in the
# computer's temporary space, so trying the mock never litters a project.
DEFAULT_OUTPUT_ROOT = Path(tempfile.gettempdir()) / "zmart-mock-output"

# The order in which set_state applies settings: the objective first, since
# changing it can change what the other settings mean.
_STATE_ORDER = ("objective", "laser_power", "gain", "exposure_ms")


@dataclass
class MockHandle:
    """Everything a connected mock driver holds.

    ``vendor`` is the connection to MockScope Control (``vendor.scope`` is
    the pretend software itself, for tests). ``get`` and ``set`` are the two
    dispatchers, ``config`` the configuration loaded at connect, ``log`` the
    command log, and ``output_root`` the folder where images are saved.
    """

    vendor: MockScopeConnection
    config: Configuration
    get: GetDispatcher
    set: SetDispatcher
    log: CommandLog
    output_root: Path
    identity: tuple[str, str, str]
    client: Any = None
    closed: bool = False
    software: dict[str, str] = field(default_factory=dict)

    @property
    def scope(self):
        """The pretend vendor software, for tests that make it misbehave."""
        return self.vendor.scope


def _answer(report: Any, *, success: bool = True) -> dict:
    """Wrap a report in the shape every command returns."""
    return {"success": success, "report": report}


def _require_open(handle: MockHandle) -> None:
    if handle.closed:
        raise RuntimeError("session is disconnected")


# --- connecting ---------------------------------------------------------------


def connect(connection: dict) -> MockHandle:
    """Start the pretend vendor software, check it, and load this microscope's configuration.

    The steps, in order: start the software and log in; load the
    configuration (machine description, registration and origin, then the
    limits, which switch on the limits gate, then the calibration); check
    the software's version and serial number against the machine
    description. If any step fails, the software is closed again and the
    error is raised.
    """
    identity = (connection["vendor"], connection["microscope"], connection["api"])
    output_root = Path(connection.get("output_root") or DEFAULT_OUTPUT_ROOT)
    output_root.mkdir(parents=True, exist_ok=True)
    timing = connection.get("mock_timing", "realistic")
    if timing not in ("realistic", "instant"):
        raise ValueError(f"mock_timing must be 'realistic' or 'instant', not {timing!r}")
    vendor = MockScopeConnection.start(
        output_folder=output_root / "_vendor_raw",
        token=connection.get("token", "mock-token"),
        instant=timing == "instant",
    )
    try:
        log = CommandLog()
        config = load_configuration(identity)
        handle = MockHandle(
            vendor=vendor,
            config=config,
            get=GetDispatcher(classify=classify, record=log.record),
            set=SetDispatcher(gate=Gate(config.limits), classify=classify, record=log.record),
            log=log,
            output_root=output_root,
            identity=identity,
            client=connection.get("client"),
        )
        handle.software = get.version(handle).value_or_raise("the software version")
        _check_machine(handle)
    except BaseException:
        vendor.close()
        raise
    return handle


def _check_machine(handle: MockHandle) -> None:
    """Refuse a configuration that belongs to another microscope; warn about an untested version."""
    machine = handle.config.machine_description
    serial = get.hardware(handle).value_or_raise("the hardware description")["serial"]
    if serial != machine["serial"]:
        raise RuntimeError(
            f"this microscope reports serial {serial}, but the configuration in "
            f"{handle.config.sources['machine_description']} belongs to {machine['serial']}"
        )
    version = handle.software["version"]
    if version not in machine["tested_versions"]:
        message = (
            f"{handle.software['software']} {version} has not been tested with this driver "
            f"(tested: {machine['tested_versions']}); watch the first commands closely"
        )
        logger.warning(message)
        handle.log.record("warning", message)


def disconnect(handle: MockHandle) -> None:
    """Close the session. Every later call raises; a second disconnect is harmless."""
    if handle.closed:
        return
    handle.closed = True
    handle.vendor.close()


# --- describing the setup -----------------------------------------------------


def get_info(handle: MockHandle) -> dict:
    """Where images go, plus which configuration files are in use."""
    _require_open(handle)
    return _answer(
        {
            "output_root": str(handle.output_root),
            "client": handle.client,
            "serial": handle.config.machine_description["serial"],
            "software": dict(handle.software),
            "configuration": dict(handle.config.sources),
        }
    )


def get_actuators(handle: MockHandle) -> dict:
    """The motors that can move each axis."""
    _require_open(handle)
    return _answer({axis: list(names) for axis, names in get.ACTUATORS.items()})


def _actuators(with_actuators: dict | None) -> dict[str, str]:
    """The motor per axis: the one named, or the first in the list. Never sticky."""
    chosen = {axis: names[0] for axis, names in get.ACTUATORS.items()}
    for axis, name in (with_actuators or {}).items():
        if axis not in get.ACTUATORS or name not in get.ACTUATORS[axis]:
            raise ValueError(f"unknown actuator {name!r} for axis {axis!r}")
        chosen[axis] = name
    return chosen


# --- moving -------------------------------------------------------------------


def get_xyz(handle: MockHandle, *, with_actuators: dict | None = None) -> dict:
    """The position in micrometers from the origin, and how far each axis may travel."""
    _require_open(handle)
    chosen = _actuators(with_actuators)
    raw = get.raw_position(handle).value_or_raise("the position")
    user = get.user_position(handle).value_or_raise("the position")
    ranges = user_range(handle.config, raw["objective"])
    return _answer(
        {
            axis: {
                "value": user[axis],
                "actuator": chosen[axis],
                "unit": "um",
                "range": ranges[axis],
            }
            for axis in ("x", "y", "z")
        }
    )


def set_xyz(
    handle: MockHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to a position in micrometers from the origin, and confirm it.

    Raises ``ValueError`` for a position outside the limits or an unknown
    motor, and ``RuntimeError`` when the move cannot be confirmed: carrying
    on at an unknown position is never safe.
    """
    _require_open(handle)
    chosen = _actuators(with_actuators)
    outcome, _raw = setter.move_to_user(handle, x=x, y=y, z=z, z_actuator=chosen["z"])
    if not outcome.confirmed:
        raise RuntimeError(f"the move to ({x}, {y}, {z}) could not be confirmed: {outcome.reason}")
    reached = get.user_position(handle).value_or_raise("the position")
    return _answer({"position": {"x": x, "y": y, "z": z}, "readback": reached, "actuators": chosen})


# --- state --------------------------------------------------------------------


def get_state(handle: MockHandle) -> dict:
    """The settings that can be changed, and a read-only description of the instrument."""
    _require_open(handle)
    changeable = get.state(handle).value_or_raise("the settings")
    slot = str(changeable["objective"])
    hardware = get.hardware(handle).value_or_raise("the hardware description")
    pixel = float(handle.config.image_stage_registration["pixel_size_um"].get(slot, 0.0))
    camera = hardware["camera"]
    return _answer(
        {
            "changeable": changeable,
            "observed": {
                "serial": hardware["serial"],
                "objective": hardware["objectives"][int(slot)]["name"],
                "pixel_size": {"x": pixel, "y": pixel, "unit": "um"},
                "frame_size": {
                    "x": camera["width"] * pixel,
                    "y": camera["height"] * pixel,
                    "unit": "um",
                },
                "software": dict(handle.software),
            },
        }
    )


def set_state(handle: MockHandle, state: dict) -> dict:
    """Apply the ``changeable`` settings, confirm each one, and report what happened.

    ``observed`` is never read. Settings this microscope does not know are
    listed under ``ignored``. ``success`` is False when nothing was applied,
    or when a setting was sent but could not be confirmed; both are safe to
    carry on from, so they are reported, not raised.
    """
    _require_open(handle)
    changeable = dict(state.get("changeable", {}))
    applied: dict[str, Any] = {}
    unconfirmed: dict[str, str] = {}
    for name in _STATE_ORDER:
        if name not in changeable:
            continue
        value = changeable[name]
        if name == "objective":
            outcome = setter.set_objective(handle, value)
        else:
            outcome = setter.set_setting(handle, name, value)
        if outcome.confirmed:
            applied[name] = value
        else:
            unconfirmed[name] = outcome.reason
    ignored = sorted(set(changeable) - set(_STATE_ORDER))
    success = bool(applied) and not unconfirmed
    report = {"applied": applied, "unconfirmed": unconfirmed, "ignored": ignored}
    return _answer(report, success=success)


# --- acquiring ----------------------------------------------------------------


def _menu() -> dict:
    return {
        "backlash_correction": {"options": [True, False], "active": True},
        "format": {"options": list(FORMATS), "active": "ome-tiff"},
        "z_planes": {"options": "whole number from 1 up to the limit", "active": 1},
        "z_step_um": {"options": "number > 0", "active": 1.0},
    }


def get_acquisition_options(handle: MockHandle) -> dict:
    """The choices for capturing and saving, with allowed values and the active one."""
    _require_open(handle)
    return _answer(_menu())


def _with_defaults(options: dict | None) -> dict:
    """Check the options against the menu and fill in the ones left out."""
    menu = _menu()
    resolved = {name: spec["active"] for name, spec in menu.items()}
    for name, value in (options or {}).items():
        if name not in menu:
            raise ValueError(f"unknown acquisition option {name!r}")
        allowed = menu[name]["options"]
        if isinstance(allowed, list) and value not in allowed:
            raise ValueError(f"invalid value {value!r} for acquisition option {name!r}")
        resolved[name] = value
    planes = resolved["z_planes"]
    if isinstance(planes, bool) or not isinstance(planes, int) or planes < 1:
        raise ValueError(f"invalid value {planes!r} for acquisition option 'z_planes'")
    step = resolved["z_step_um"]
    if isinstance(step, bool) or not isinstance(step, (int, float)) or not step > 0:
        raise ValueError(f"invalid value {step!r} for acquisition option 'z_step_um'")
    return resolved


def acquire(
    handle: MockHandle, *, acquisition_type: str, position_label: str, options: dict | None = None
) -> dict:
    """Capture an image (or a z-stack) here and save it, in one step.

    Options left out keep their active value. The report lists the saved
    ``files`` and the ``command_log`` that records how they were made. When
    the acquisition cannot be confirmed, ``success`` is False and no files
    are listed.
    """
    _require_open(handle)
    options = _with_defaults(options)
    mark = handle.log.mark()
    if options["backlash_correction"]:
        PROCEDURES["backlash_takeup"]["run"](handle)
    position = get.user_position(handle).value_or_raise("the position")
    vendor_name = safe_name(f"{acquisition_type}_{position_label}")
    outcome = setter.acquire(
        handle, name=vendor_name, z_planes=options["z_planes"], z_step_um=options["z_step_um"]
    )
    report: dict[str, Any] = {
        "acquisition_type": acquisition_type,
        "position_label": position_label,
        "format": options["format"],
        "settle": "backlash-corrected" if options["backlash_correction"] else "direct",
        "position": position,
        "confirmed": outcome.confirmed,
    }
    if not outcome.confirmed:
        return _answer({**report, "files": [], "reason": outcome.reason}, success=False)
    saved = save_acquisition(
        handle,
        vendor_file=outcome.result,
        acquisition_type=acquisition_type,
        position_label=position_label,
        image_format=options["format"],
        position_um=position,
        log_mark=mark,
    )
    return _answer({**report, **saved, "vendor_file": outcome.result})


# --- procedures ---------------------------------------------------------------


def get_procedures(handle: MockHandle) -> dict:
    """The routines this microscope offers, each with a plain description."""
    _require_open(handle)
    return _answer(
        {name: {"description": spec["description"]} for name, spec in PROCEDURES.items()}
    )


def run_procedure(handle: MockHandle, procedure: dict) -> dict:
    """Run one routine by name; any other entries are passed to it. An unknown name is refused."""
    _require_open(handle)
    entries = dict(procedure)
    name = entries.pop("name", None)
    if name not in PROCEDURES:
        raise ValueError(f"unknown procedure {name!r}")
    run = PROCEDURES[name]["run"]
    try:
        inspect.signature(run).bind(handle, **entries)
    except TypeError as exc:
        raise ValueError(f"procedure {name!r} does not take these entries: {exc}") from None
    return _answer({"ran": name, **run(handle, **entries)})
