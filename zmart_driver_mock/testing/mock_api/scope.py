"""MockScope Control: pretend vendor software for a pretend microscope.

A ZMART driver is built on top of the software that comes with a microscope:
LAS X for Leica, NIS-Elements for Nikon, ZEN for ZEISS. This module plays
that role for the mock microscope. It is the *mock API* from the driver
anatomy: the stand-in at the very bottom of a driver, below the vendor
interface, so that every part above it can be built and tested on a laptop.

To be a useful stand-in it behaves like vendor software, not like ZMART:

- **It speaks its own language.** Commands have their own names
  (``MoveStage``, ``SetSetting``, ``StartAcquisition``), positions are raw
  stage micrometers with no origin, and focus is split over two drives, a
  coarse ``focus`` drive and a fine ``piezo``. The driver's vendor interface
  has to translate.
- **It answers with status codes.** Every command returns a reply,
  ``{"ok": True, "result": {...}}`` or ``{"ok": False, "code": 201,
  "message": "..."}``, and the driver's error handling has to sort the codes
  and messages into kinds.
- **Things take time.** A move is accepted at once but finishes later, so
  reading the position straight away shows the stage still travelling. A
  driver has to confirm that a command really took effect.
- **It refuses while busy.** During an acquisition, moves and setting
  changes are refused with error 100.
- **It writes its own file format.** Acquisitions are saved as ``.mraw``
  files (see :mod:`.mraw`), written in two steps, so a driver has to wait
  until a file is complete.
- **It can fail on purpose.** :attr:`MockScope.faults` makes the next command
  fail in a chosen way (see :mod:`.faults`).

Time
----
The pretend microscope does not run in the background. Instead, every
command first catches up with the time that has passed since the last one:
moves that should be finished are finished, and acquisitions that should be
done are written. With the normal clock this follows real time. For exact,
fast tests, pass a :class:`FakeClock` and move time forward yourself with
``clock.advance(seconds)``.

A short example::

    from zmart_driver_mock.testing.mock_api import FakeClock, MockScope

    clock = FakeClock()
    scope = MockScope(output_folder="images", clock=clock)
    scope.send("Login", token="mock-token")
    scope.send("MoveStage", x=51_000.0)        # accepted; the stage starts moving
    scope.send("GetStatus")["result"]["state"] # "moving"
    clock.advance(1.0)
    scope.send("GetStagePosition")["result"]   # {"x": 51000.0, "y": 37500.0}

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import copy
import math
import random
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import mraw
from .faults import Faults
from .sample import Tilt, render

SOFTWARE = "MockScope Control"
VERSION = "2.4.1"
SERIAL = "MOCK-0001"

# How far each drive can travel, in raw micrometers. The vendor software
# refuses anything outside these with error 201. These are the hardware's
# own end stops, wider than the limits an operator sets in ZMART.
STAGE_TRAVEL: dict[str, tuple[float, float]] = {"x": (0.0, 100_000.0), "y": (0.0, 75_000.0)}
FOCUS_TRAVEL: dict[str, tuple[float, float]] = {"focus": (0.0, 10_000.0), "piezo": (-100.0, 100.0)}

# Where the drives are when the software starts: the middle of the slide.
START_POSITION: dict[str, float] = {"x": 50_000.0, "y": 37_500.0, "focus": 5_000.0, "piezo": 0.0}

# The settings SetSetting can change, with their allowed range and start value.
SETTINGS: dict[str, dict[str, float]] = {
    "laser_power_percent": {"min": 0.0, "max": 100.0, "start": 10.0},
    "detector_gain": {"min": 0.0, "max": 1000.0, "start": 100.0},
    "exposure_ms": {"min": 0.1, "max": 10_000.0, "start": 10.0},
}

# The objectives in the turret. The vendor software reports these facts.
OBJECTIVES: dict[int, dict[str, Any]] = {
    1: {"name": "10x/0.30 Air", "magnification": 10, "pixel_size_um": 1.0},
    2: {"name": "20x/0.75 Air", "magnification": 20, "pixel_size_um": 0.5},
    3: {"name": "40x/0.95 Air", "magnification": 40, "pixel_size_um": 0.25},
}

# What the vendor software does NOT report: how far each objective's view is
# shifted from objective 1, in micrometers. Optical calibration has to
# measure these.
OBJECTIVE_OFFSETS_UM: dict[int, dict[str, float]] = {
    1: {"x": 0.0, "y": 0.0, "z": 0.0},
    2: {"x": 3.0, "y": -2.0, "z": 1.5},
    3: {"x": -4.0, "y": 5.5, "z": -2.5},
}

# How the camera sits on the stage, as a small table ((a, b), (c, d)). A step
# of u micrometers to the right in the picture and v micrometers down is a
# stage step of (a*u + b*v) in x and (c*u + d*v) in y. The default is a
# mirror image: right in the picture is +y on the stage, and down is +x.
# Image-to-stage registration has to find this.
DEFAULT_ORIENTATION: tuple[tuple[int, int], tuple[int, int]] = ((0, 1), (1, 0))

# How quickly things happen. All in seconds or micrometers per second.
DEFAULT_TIMING: dict[str, float] = {
    "stage_speed_um_s": 50_000.0,
    "focus_speed_um_s": 2_000.0,
    "piezo_speed_um_s": 1_000.0,
    "settle_s": 0.02,
    "setting_delay_s": 0.0,
    "objective_change_s": 0.3,
    "plane_s": 0.02,
}

# Every error code the software can answer with.
ERRORS: dict[int, str] = {
    100: "System busy, try again later",
    200: "Unknown command",
    201: "Value out of range",
    202: "Unknown setting",
    203: "Missing argument",
    204: "Unknown argument",
    205: "Invalid value",
    206: "Folder does not exist",
    300: "Hardware fault: controller not responding",
    401: "Access denied",
    402: "Not logged in",
    999: "Internal error 0x7F3A",
}

# For every command: the arguments it needs, and those it may take.
COMMANDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "GetVersion": (frozenset(), frozenset()),
    "Login": (frozenset({"token"}), frozenset()),
    "Logout": (frozenset(), frozenset()),
    "GetHardware": (frozenset(), frozenset()),
    "GetStagePosition": (frozenset(), frozenset()),
    "GetFocus": (frozenset(), frozenset()),
    "GetSettings": (frozenset(), frozenset()),
    "GetStatus": (frozenset(), frozenset()),
    "GetOutputFolder": (frozenset(), frozenset()),
    "MoveStage": (frozenset(), frozenset({"x", "y"})),
    "MoveFocus": (frozenset(), frozenset({"focus", "piezo"})),
    "SetSetting": (frozenset({"name", "value"}), frozenset()),
    "SetObjective": (frozenset({"slot"}), frozenset()),
    "SetOutputFolder": (frozenset({"folder"}), frozenset()),
    "StartAcquisition": (frozenset({"name"}), frozenset({"z_planes", "z_step_um"})),
    "Abort": (frozenset(), frozenset()),
}

# Commands that work without logging in first.
_OPEN_COMMANDS = frozenset({"GetVersion", "Login"})

# Argument values that must never appear in the command history.
_SECRET_ARGUMENTS = frozenset({"token"})

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class FakeClock:
    """A clock that only moves when you tell it to.

    Hand it to :class:`MockScope` to make tests exact and fast: nothing
    happens between two commands unless the test calls :meth:`advance`.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        """Let ``seconds`` pass."""
        if seconds < 0:
            raise ValueError("time only moves forward")
        self.now += seconds


class _Refusal(Exception):
    """Raised inside a command to answer with an error code."""

    def __init__(self, code: int, detail: str = "") -> None:
        super().__init__(code, detail)
        self.code = code
        self.detail = detail


class _Drives:
    """A group of drives that move together, such as the stage's x and y.

    A move starts at the current position and ends at the target after a
    set time. In between, the position is read part of the way there, as a
    real stage would be.
    """

    def __init__(self, positions: dict[str, float]) -> None:
        self.start = dict(positions)
        self.target = dict(positions)
        self.t0 = 0.0
        self.t1 = 0.0

    def position(self, now: float) -> dict[str, float]:
        if now >= self.t1:
            return dict(self.target)
        part = (now - self.t0) / (self.t1 - self.t0)
        return {
            axis: self.start[axis] + part * (self.target[axis] - self.start[axis])
            for axis in self.target
        }

    def moving(self, now: float) -> bool:
        return now < self.t1

    def move(self, now: float, target: dict[str, float], duration: float) -> None:
        self.start = self.position(now)
        self.target = {**self.start, **target}
        self.t0 = now
        self.t1 = now + duration

    def stop(self, now: float) -> None:
        here = self.position(now)
        self.start = here
        self.target = dict(here)
        self.t1 = now


def _check_orientation(orientation) -> tuple[tuple[int, int], tuple[int, int]]:
    """Accept only a 90° turn or a mirror image, the ways a camera can sit."""
    (a, b), (c, d) = orientation
    entries = (a, b, c, d)
    if any(value not in (-1, 0, 1) for value in entries) or abs(a * d - b * c) != 1:
        raise ValueError(
            "orientation must be a 90° turn or a mirror, such as ((1, 0), (0, 1)) or ((0, 1), (1, 0))"
        )
    if (a != 0 and b != 0) or (c != 0 and d != 0):
        raise ValueError("orientation must line the camera up with the stage axes")
    return ((int(a), int(b)), (int(c), int(d)))


class MockScope:
    """The pretend vendor software, with the pretend microscope behind it.

    ``output_folder`` is where acquisitions are written; it must exist.
    ``token`` is the password that ``Login`` expects. ``clock`` is a function
    returning the time in seconds; pass a :class:`FakeClock` for exact
    tests. ``image_size`` is the camera's ``(width, height)`` in pixels.
    ``orientation``, ``objective_offsets`` and ``tilt`` set the hidden facts
    that setup notebooks measure (see :meth:`truth`). ``seed`` chooses the
    pattern of spots on the slide. ``noise=False`` gives clean pictures.
    ``timing`` overrides any of :data:`DEFAULT_TIMING`.

    Send commands with :meth:`send`. Make it misbehave with :attr:`faults`.
    Every command sent is recorded in :attr:`history`.
    """

    def __init__(
        self,
        *,
        output_folder: str | Path,
        token: str = "mock-token",
        clock: Callable[[], float] | None = None,
        image_size: tuple[int, int] = (64, 64),
        orientation: tuple[tuple[int, int], tuple[int, int]] = DEFAULT_ORIENTATION,
        objective_offsets: dict[int, dict[str, float]] | None = None,
        tilt: Tilt | None = None,
        seed: int = 0,
        noise: bool = True,
        timing: dict[str, float] | None = None,
    ) -> None:
        folder = Path(output_folder)
        if not folder.is_dir():
            raise ValueError(f"output folder {folder} does not exist")
        unknown = set(timing or {}) - set(DEFAULT_TIMING)
        if unknown:
            raise ValueError(
                f"unknown timing keys {sorted(unknown)}; known: {sorted(DEFAULT_TIMING)}"
            )
        self._token = token
        self._clock = clock or time.monotonic
        self._width, self._height = (int(image_size[0]), int(image_size[1]))
        self._orientation = _check_orientation(orientation)
        self._offsets = copy.deepcopy(objective_offsets or OBJECTIVE_OFFSETS_UM)
        if set(self._offsets) != set(OBJECTIVES):
            raise ValueError(f"objective_offsets must give every slot {sorted(OBJECTIVES)}")
        self._tilt = tilt or Tilt()
        self._seed = int(seed)
        self._noise = bool(noise)
        self._timing = {**DEFAULT_TIMING, **(timing or {})}

        self.faults = Faults()
        self.history: list[dict[str, Any]] = []

        self._running = True
        self._logged_in = False
        self._output_folder = folder
        self._stage = _Drives({"x": START_POSITION["x"], "y": START_POSITION["y"]})
        self._focus = _Drives({"focus": START_POSITION["focus"], "piezo": START_POSITION["piezo"]})
        self._settings = {name: spec["start"] for name, spec in SETTINGS.items()}
        self._pending_settings: list[tuple[float, str, float]] = []
        self._objective = 1
        self._objective_change: tuple[float, int] | None = None
        self._acquisition: dict[str, Any] | None = None
        self._acquisition_count = 0
        self._last_replies: dict[str, dict] = {}

    @classmethod
    def instant(cls, **kwargs) -> MockScope:
        """A MockScope where everything happens at once: no travel time, no waiting.

        Handy when a test is about something other than timing.
        """
        timing = {key: 0.0 for key in DEFAULT_TIMING if not key.endswith("speed_um_s")}
        timing.update({key: math.inf for key in DEFAULT_TIMING if key.endswith("speed_um_s")})
        timing.update(kwargs.pop("timing", None) or {})
        return cls(timing=timing, **kwargs)

    # --- the one way in -----------------------------------------------------

    def send(self, command: str, **arguments: Any) -> dict[str, Any]:
        """Send one command and return the software's reply.

        The reply is ``{"ok": True, "result": {...}}`` when the command was
        accepted, or ``{"ok": False, "code": ..., "message": ...}`` when it
        was refused. "Accepted" means the software took it on, not that it
        has finished: read back to find out.

        Raises ``ConnectionError`` when the software is not running, and
        ``TimeoutError`` when the reply is lost (only through a fault).
        """
        if not self._running:
            raise ConnectionError(f"{SOFTWARE} is not running")
        now = self._clock()
        self._catch_up(now)
        fault = None
        try:
            self._check_arguments(command, arguments)
            if command not in _OPEN_COMMANDS and not self._logged_in:
                raise _Refusal(402)
            fault = self.faults.take(command)
            if fault == "disconnect":
                self._running = False
                self._logged_in = False
                self._record(now, command, arguments, None, fault)
                raise ConnectionError(f"{SOFTWARE} closed unexpectedly")
            reply = self._run(command, arguments, fault, now)
        except _Refusal as refusal:
            message = ERRORS[refusal.code]
            if refusal.detail:
                message = f"{message}: {refusal.detail}"
            reply = {"ok": False, "code": refusal.code, "message": message}
        self._record(now, command, arguments, reply, fault)
        if fault == "timeout":
            raise TimeoutError(f"no reply from {SOFTWARE} to {command}")
        return reply

    def _run(self, command: str, arguments: dict, fault: str | None, now: float) -> dict:
        refusals = {"busy": 100, "out_of_range": 201, "hardware_fault": 300, "unknown_error": 999}
        if fault in refusals:
            raise _Refusal(refusals[fault])
        is_get = command.startswith("Get")
        if fault == "stale" and is_get and command in self._last_replies:
            return copy.deepcopy(self._last_replies[command])
        if fault == "ignore" and not is_get:
            return {"ok": True, "result": {"accepted": command}}
        result = getattr(self, f"_cmd_{command}")(now, **arguments)
        reply = {"ok": True, "result": result}
        if is_get:
            self._last_replies[command] = copy.deepcopy(reply)
        return reply

    def _check_arguments(self, command: str, arguments: dict) -> None:
        if command not in COMMANDS:
            raise _Refusal(200, repr(command))
        required, optional = COMMANDS[command]
        missing = required - set(arguments)
        if missing:
            raise _Refusal(203, ", ".join(sorted(missing)))
        unknown = set(arguments) - required - optional
        if unknown:
            raise _Refusal(204, ", ".join(sorted(unknown)))

    def _record(self, now, command, arguments, reply, fault) -> None:
        # Keep the names of secret arguments, never their values.
        shown = {
            key: ("<hidden>" if key in _SECRET_ARGUMENTS else value)
            for key, value in arguments.items()
        }
        self.history.append(
            {
                "time": now,
                "command": command,
                "arguments": shown,
                "ok": None if reply is None else reply["ok"],
                "code": None if reply is None else reply.get("code"),
                "fault": fault,
            }
        )

    # --- the passing of time -----------------------------------------------

    def _catch_up(self, now: float) -> None:
        """Finish whatever should have finished by now."""
        still_waiting = []
        for due, name, value in self._pending_settings:
            if now >= due:
                self._settings[name] = value
            else:
                still_waiting.append((due, name, value))
        self._pending_settings = still_waiting
        if self._objective_change is not None and now >= self._objective_change[0]:
            self._objective = self._objective_change[1]
            self._objective_change = None
        acquisition = self._acquisition
        if (
            acquisition is not None
            and acquisition["state"] == "running"
            and now >= acquisition["ends"]
        ):
            self._finish_acquisition(acquisition)

    def _state(self, now: float) -> str:
        if self._acquisition is not None and self._acquisition["state"] == "running":
            return "acquiring"
        if self._objective_change is not None:
            return "changing_objective"
        if self._stage.moving(now) or self._focus.moving(now):
            return "moving"
        return "idle"

    def _refuse_if_acquiring(self, now: float) -> None:
        if self._state(now) == "acquiring":
            raise _Refusal(100, "an acquisition is running")

    # --- connection ---------------------------------------------------------

    def _cmd_GetVersion(self, now):
        return {"software": SOFTWARE, "version": VERSION}

    def _cmd_Login(self, now, token):
        if token != self._token:
            raise _Refusal(401)
        self._logged_in = True
        return {"session": "open"}

    def _cmd_Logout(self, now):
        self._logged_in = False
        return {"session": "closed"}

    def shutdown(self) -> None:
        """Pretend the vendor software was closed. Every later command raises ``ConnectionError``."""
        self._running = False
        self._logged_in = False

    def restart(self) -> None:
        """Start the vendor software again after :meth:`shutdown` or a ``disconnect`` fault.

        The microscope keeps its position and settings, but the session is
        new: log in again. An acquisition that was running is lost.
        """
        self._running = True
        self._logged_in = False
        if self._acquisition is not None and self._acquisition["state"] == "running":
            self._acquisition["state"] = "aborted"

    # --- reading ------------------------------------------------------------

    def _cmd_GetHardware(self, now):
        return {
            "serial": SERIAL,
            "stage_travel_um": {axis: list(span) for axis, span in STAGE_TRAVEL.items()},
            "focus_travel_um": {axis: list(span) for axis, span in FOCUS_TRAVEL.items()},
            "objectives": {slot: dict(spec) for slot, spec in OBJECTIVES.items()},
            "camera": {"width": self._width, "height": self._height, "bit_depth": 16},
            "settings": {
                name: {"min": spec["min"], "max": spec["max"]} for name, spec in SETTINGS.items()
            },
        }

    def _cmd_GetStagePosition(self, now):
        return self._stage.position(now)

    def _cmd_GetFocus(self, now):
        return self._focus.position(now)

    def _cmd_GetSettings(self, now):
        return {**self._settings, "objective_slot": self._objective}

    def _cmd_GetStatus(self, now):
        last = None
        if self._acquisition is not None:
            acquisition = self._acquisition
            last = {
                "name": acquisition["name"],
                "file": str(acquisition["path"]),
                "planes": acquisition["planes"],
                "state": acquisition["state"],
            }
        return {
            "state": self._state(now),
            "stage_moving": self._stage.moving(now),
            "focus_moving": self._focus.moving(now),
            "last_acquisition": last,
        }

    def _cmd_GetOutputFolder(self, now):
        return {"folder": str(self._output_folder)}

    # --- changing -----------------------------------------------------------

    def _cmd_MoveStage(self, now, **target):
        self._refuse_if_acquiring(now)
        if not target:
            raise _Refusal(203, "x or y")
        target = {axis: _number(axis, value) for axis, value in target.items()}
        _check_travel(target, STAGE_TRAVEL)
        here = self._stage.position(now)
        speed = self._timing["stage_speed_um_s"]
        travel = max(abs(target[axis] - here[axis]) for axis in target)
        self._stage.move(now, target, travel / speed + self._timing["settle_s"])
        return {"accepted": "MoveStage"}

    def _cmd_MoveFocus(self, now, **target):
        self._refuse_if_acquiring(now)
        if self._objective_change is not None:
            raise _Refusal(100, "the objective is changing")
        if not target:
            raise _Refusal(203, "focus or piezo")
        target = {axis: _number(axis, value) for axis, value in target.items()}
        _check_travel(target, FOCUS_TRAVEL)
        here = self._focus.position(now)
        duration = max(
            abs(target[axis] - here[axis]) / self._timing[f"{axis}_speed_um_s"] for axis in target
        )
        self._focus.move(now, target, duration + self._timing["settle_s"])
        return {"accepted": "MoveFocus"}

    def _cmd_SetSetting(self, now, name, value):
        self._refuse_if_acquiring(now)
        if name not in SETTINGS:
            raise _Refusal(202, repr(name))
        value = _number(name, value)
        spec = SETTINGS[name]
        if not spec["min"] <= value <= spec["max"]:
            raise _Refusal(201, f"{name} must be between {spec['min']} and {spec['max']}")
        self._pending_settings.append((now + self._timing["setting_delay_s"], name, value))
        self._catch_up(now)
        return {"accepted": "SetSetting"}

    def _cmd_SetObjective(self, now, slot):
        self._refuse_if_acquiring(now)
        if self._objective_change is not None or self._focus.moving(now):
            raise _Refusal(100, "the focus drive is busy")
        if isinstance(slot, bool) or not isinstance(slot, int):
            raise _Refusal(205, "slot must be a whole number")
        if slot not in OBJECTIVES:
            raise _Refusal(201, f"slot must be one of {sorted(OBJECTIVES)}")
        if slot != self._objective:
            self._objective_change = (now + self._timing["objective_change_s"], slot)
            self._catch_up(now)
        return {"accepted": "SetObjective"}

    def _cmd_SetOutputFolder(self, now, folder):
        self._refuse_if_acquiring(now)
        path = Path(str(folder))
        if not path.is_dir():
            raise _Refusal(206, str(path))
        self._output_folder = path
        return {"accepted": "SetOutputFolder"}

    def _cmd_Abort(self, now):
        """Stop every movement and any acquisition, where they are now."""
        self._stage.stop(now)
        self._focus.stop(now)
        if self._acquisition is not None and self._acquisition["state"] == "running":
            # The file keeps its description line but never gets its pixels.
            self._acquisition["state"] = "aborted"
        return {"accepted": "Abort"}

    # --- acquiring ----------------------------------------------------------

    def _cmd_StartAcquisition(self, now, name, z_planes=1, z_step_um=1.0):
        state = self._state(now)
        if state != "idle":
            raise _Refusal(100, f"the microscope is {state.replace('_', ' ')}")
        if not isinstance(name, str) or not _NAME_PATTERN.match(name):
            raise _Refusal(205, "name may use letters, digits, '_', '-' and '.'")
        if isinstance(z_planes, bool) or not isinstance(z_planes, int):
            raise _Refusal(205, "z_planes must be a whole number")
        if not 1 <= z_planes <= 200:
            raise _Refusal(201, "z_planes must be between 1 and 200")
        z_step_um = _number("z_step_um", z_step_um)
        if z_planes > 1 and z_step_um <= 0:
            raise _Refusal(201, "z_step_um must be above 0")
        path = self._free_file_name(name)
        stage = self._stage.position(now)
        focus = self._focus.position(now)
        objective = OBJECTIVES[self._objective]
        header = {
            "name": name,
            "width": self._width,
            "height": self._height,
            "planes": z_planes,
            "dtype": "uint16",
            "pixel_size_um": objective["pixel_size_um"],
            "z_step_um": z_step_um,
            "stage_um": {**stage, **focus},
            "objective": {"slot": self._objective, "name": objective["name"]},
            "settings": dict(self._settings),
            "started_at": now,
        }
        mraw.write_header(path, header)
        self._acquisition_count += 1
        self._acquisition = {
            "name": name,
            "path": path,
            "planes": z_planes,
            "z_step_um": z_step_um,
            "stage": stage,
            "focus": focus,
            "objective": self._objective,
            "settings": dict(self._settings),
            "number": self._acquisition_count,
            "ends": now + z_planes * self._timing["plane_s"],
            "state": "running",
        }
        self._catch_up(now)
        return {"accepted": "StartAcquisition", "file": str(path)}

    def _free_file_name(self, name: str) -> Path:
        """Never overwrite: add _001, _002, ... the way much vendor software does."""
        path = self._output_folder / f"{name}.mraw"
        number = 0
        while path.exists():
            number += 1
            path = self._output_folder / f"{name}_{number:03d}.mraw"
        return path

    def _finish_acquisition(self, acquisition: dict) -> None:
        settings = acquisition["settings"]
        signal = (
            20_000.0
            * settings["laser_power_percent"]
            / 100.0
            * settings["detector_gain"]
            / 100.0
            * settings["exposure_ms"]
            / 10.0
        )
        offset = self._offsets[acquisition["objective"]]
        centre_x = acquisition["stage"]["x"] + offset["x"]
        centre_y = acquisition["stage"]["y"] + offset["y"]
        sharp_at = self._tilt.focus_at(centre_x, centre_y)
        noise = (
            random.Random(self._seed * 1_000_003 + acquisition["number"]) if self._noise else None
        )
        planes = []
        for index in range(acquisition["planes"]):
            height = (
                acquisition["focus"]["focus"]
                + acquisition["focus"]["piezo"]
                + offset["z"]
                + index * acquisition["z_step_um"]
            )
            planes.append(
                render(
                    seed=self._seed,
                    width=self._width,
                    height=self._height,
                    pixel_size_um=OBJECTIVES[acquisition["objective"]]["pixel_size_um"],
                    centre_x=centre_x,
                    centre_y=centre_y,
                    defocus_um=height - sharp_at,
                    orientation=self._orientation,
                    signal=signal,
                    noise=noise,
                )
            )
        mraw.append_planes(acquisition["path"], planes)
        acquisition["state"] = "done"

    # --- the hidden answers -------------------------------------------------

    def truth(self) -> dict[str, Any]:
        """The facts a real microscope never reports, for checking setup work.

        Returns the camera ``orientation``, the ``objective_offsets_um``
        (relative to objective 1), the slide ``tilt``, and the ``seed`` of the
        spot pattern. A test can compare what a setup notebook measured with
        these answers.
        """
        return {
            "orientation": self._orientation,
            "objective_offsets_um": copy.deepcopy(self._offsets),
            "tilt": {
                "x0": self._tilt.x0,
                "y0": self._tilt.y0,
                "z0": self._tilt.z0,
                "slope_x": self._tilt.slope_x,
                "slope_y": self._tilt.slope_y,
            },
            "seed": self._seed,
        }


def _number(name: str, value: Any) -> float:
    """Accept a plain, finite number; refuse anything else with error 205."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _Refusal(205, f"{name} must be a number")
    return float(value)


def _check_travel(target: dict[str, float], travel: dict[str, tuple[float, float]]) -> None:
    for axis, value in target.items():
        low, high = travel[axis]
        if not low <= value <= high:
            raise _Refusal(201, f"{axis} must be between {low} and {high}")
