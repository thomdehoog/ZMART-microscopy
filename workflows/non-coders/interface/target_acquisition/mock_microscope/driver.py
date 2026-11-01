"""The mock microscope: a pretend instrument the interface can be tried and tested on.

It behaves like a real microscope as far as the operator page can tell. It
has a stage that moves within its travel, jobs to choose between (an
overview, a focussing stack, a close look at a target, ...), and it writes
real image files: one plane of a mouse kidney section (scikit-image's
``kidney`` sample), laid across the whole stage, slightly tilted so the
sharp height changes from place to place, blurred by how far the focus is
from it, and here and there a speck of dust that is sharp at the wrong
height -- the failure a focus routine has to survive.

The functions here return their answers as they are. The plug-in in
``zmart_controller_plugin/`` hands them to the ZMART Controller, which writes
the answer every client reads, ``{"success": ..., "output": ...}``.

What this mock does not have: a setup of its own. A real driver loads its
origin, travel limits and calibration from the setup the operator made once
for that microscope; the mock simply counts from the stage's own zero and is
fenced by its travel.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import subprocess
import sys
import time
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


#: How much sample one pixel covers. Reported in the state and written into
#: every frame, so the two cannot come to disagree: a driver whose state and
#: whose files disagreed about how much sample it had seen would place every
#: picture wrongly, and only on the second one would anybody notice. The frames
#: are small so that a test can take a hundred of them, and the pixel is
#: correspondingly large -- 256 of them across 1024 um, which is what
#: its state reports, and at which the sample's nuclei come out a few
#: tens of micrometres wide, the size a detector is told to look for.
_PIXEL_UM = 4.0

#: The jobs this pretend instrument has stored, in the order it lists them.
JOBS: tuple[str, ...] = (
    "Overview", "Overview stack", "Focussing", "Target", "Target stack", "Target focussing",
)

#: What a capture takes is the selected job's, as on a real instrument, where
#: it comes with the settings the operator imported for that kind of scan.
#: A job without a stack takes the single plane an imaging scan takes, in every
#: channel the sample has.
_ONE_PLANE = {"z_planes": 1, "z_step_um": 0.0, "channels": 3}
#: The stack the Focussing job takes: 61 planes over +/-34 um, fine enough that
#: a speck a micrometre or two wide lands on a plane at all. A stack that
#: stepped past its dust could not show the failure focusing exists to survive.
#: It takes one channel, as a focus job does.
_FOCUS_STACK = {"z_planes": 61, "z_step_um": 68.0 / 60.0, "channels": 1}
#: The fine focussing before a target: the target's own frame, a short
#: stack in fine steps about the map's height -- what a focussing job at
#: the targets' magnification is on a real instrument.
_TARGET_FOCUS_STACK = {"z_planes": 41, "z_step_um": 0.5, "channels": 1}
JOB_STACKS = {
    "Focussing": _FOCUS_STACK,
    "Target focussing": _TARGET_FOCUS_STACK,
    "Overview stack": {"z_planes": 7, "z_step_um": 2.0, "channels": 3},
    "Target stack": {"z_planes": 11, "z_step_um": 1.0, "channels": 3},
}

# The pretend sample: a real micrograph lying at a slight tilt across the
# stage, sharp where the focal plane meets it and blurring with distance from
# it. A driver that returned the same picture at every height would let a
# broken focus routine pass, so this one does not.
_SAMPLE_Z_UM = 8.0  # the sample sits a few um above where a fresh stage stands, so an
# operator who has not yet focused still sweeps through it. Far from zero, every
# plane of a first stack is equally blurred and the map begins from nothing.
_SAMPLE_TILT = (0.0002, -0.0001)  # um of height per um across x and y: about
# 30 um corner to corner, a real plate's tilt, and inside a first sweep everywhere
_BLUR_PER_UM = 0.25  # blur radius in pixels per um out of focus


#: How often a field has a speck of dust in it, and how far apart two fields
#: must be to have different dust. A speck is the failure worth pretending: it
#: is a hard edge in one plane, so it out-scores tissue over a far narrower
#: range, which is how an autofocus ends up focused on dust. A focus routine
#: that cannot be shown this cannot be shown to survive it.
_DEBRIS_CHANCE = 0.45
_DEBRIS_CELL_UM = 50.0


def sharp_height_um(x_um: float, y_um: float) -> float:
    """The frame height the pretend sample is in focus at, above this (x, y).

    Exported because a test that acquires a stack has to know what the right
    answer was; nothing in the driver's own contract exposes it, exactly as no
    instrument tells you where the tissue is.
    """
    return _SAMPLE_Z_UM + _SAMPLE_TILT[0] * x_um + _SAMPLE_TILT[1] * y_um


def debris_at(x_um: float, y_um: float) -> dict | None:
    """The speck of dust in the field above this (x, y), if there is one.

    Deterministic from where it is, not from when it was asked: the same field
    has the same dust every run, so a stack that goes wrong goes wrong the same
    way twice and can be tested. ``offset_um`` is where it sits relative to the
    tissue, ``width_um`` how narrow its peak is, and ``contrast`` how hard its
    edges are against the tissue's.

    Exported for the same reason as :func:`sharp_height_um`: a test has to know
    which fields are the awkward ones.
    """
    cell_x = int(x_um // _DEBRIS_CELL_UM)
    cell_y = int(y_um // _DEBRIS_CELL_UM)
    rng = random.Random(770 + cell_x * 613 + cell_y * 1009)
    if rng.random() > _DEBRIS_CHANCE:
        return None
    return {
        "offset_um": (-1 if rng.random() < 0.5 else 1) * (9.0 + 13.0 * rng.random()),
        # Narrower than tissue and wider than one plane: a speck has to be
        # tellable from the sample and still be caught by the drive.
        "width_um": 1.2 + 1.6 * rng.random(),
        "contrast": 1.12 + 0.34 * rng.random(),
    }


#: How far the stage travels, in micrometres from its zero: every move is
#: checked against this, and a move outside it is refused with ``ValueError``
#: before anything moves.
TRAVEL_UM = {"x": (-5_000.0, 125_000.0), "y": (-5_000.0, 85_000.0), "z": (-1_000.0, 11_000.0)}


@dataclass
class MockHandle:
    """In-memory instrument state standing in for a live connection.

    The stage position is in micrometres from the stage's own zero.
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    # How far each of the three z motors has moved from its own zero. Their
    # sum is ``z``. A move with ``with_actuators={"z": "piezo"}`` is carried
    # by the piezo alone, so these readings show how the motors share the
    # height, as a real instrument's would.
    z_motors: dict = field(default_factory=lambda: {"motoric": 0.0, "galvo": 0.0, "piezo": 0.0})

    # mutable instrument settings
    laser_power: float = 5.0
    gain: float = 1.0
    # The acquisition setting an operator actually reaches for: which stored
    # recipe the next capture is taken with. Every instrument has one under
    # some name; naming it here is what lets a client exercise choosing one
    # without hardware.
    job: str = "Overview"

    # the optics, as an instrument reports them: what the light goes through,
    # how much of it the lens collects, and what the scanner does on top
    magnification: float = 20.0
    numerical_aperture: float = 0.75
    immersion: str = "dry"
    zoom: float = 1.0

    # immutable identity, plus connection info filled at connect
    serial: str = "MOCK-0001"
    client: str | None = None
    connection: dict = field(default_factory=dict)
    tile_positions: list[dict] = field(default_factory=list)
    # where the changeable settings live; see ``where_the_instrument_stands``
    state_file: Path | None = None
    # when the session opened (time.monotonic); the connection checks answer
    # one after another from here, so a client polling get_info sees them
    # arrive the way it will on an instrument that takes time to answer
    connected_at: float = 0.0

    # set by disconnect(); every other op refuses a closed handle
    closed: bool = False


#: The settings an operator changes on the instrument's own software, and
#: where the mock keeps them. LAS X is a program of its own holding the
#: Leica's job; the mock has no such program, so its settings live in one
#: small file that anything may write -- the mock instrument window, or
#: ``set_state`` through the controller -- and that the driver reads back on
#: every readout and every capture. The file is the one place the state
#: lives, so whoever wrote it last is what the instrument stands on, and
#: it outlives a session the way a real instrument's setup does.
CHANGEABLE: tuple[str, ...] = ("job", "laser_power", "gain")
STATE_FILE_ENV = "ZMART_MOCK_STATE"


def where_the_instrument_stands(connection: dict | None = None) -> Path:
    """The state file: named in the connection, else by the environment,
    else under the user's home."""
    named = (connection or {}).get("state_file") or os.environ.get(STATE_FILE_ENV)
    if named:
        return Path(named)
    return Path.home() / ".zmart-mock" / "instrument.json"


# -- the instrument's own window -------------------------------------------
#
# The mock has no software of its own; its window (``window.py``) is
# it. The window claims a lock beside the state file while it is open, so a
# session that connects to the mock can open the window when it is not
# there yet and leave it alone when it is -- the way LAS X is simply there
# on the Leica.


def where_the_window_stands(path: Path | None = None) -> Path:
    """The lock the window holds while open, beside the state file."""
    where = path or where_the_instrument_stands()
    return where.with_name("instrument.window")


def claim_the_window(pid: int, path: Path | None = None) -> Path:
    lock = where_the_window_stands(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(int(pid)), encoding="utf-8")
    return lock


def release_the_window(path: Path | None = None) -> None:
    try:
        where_the_window_stands(path).unlink()
    except FileNotFoundError:
        pass


def the_window_is_open(path: Path | None = None) -> bool:
    """Whether a window holds the lock and is still running: a lock left by
    a window that died is not a window."""
    try:
        pid = int(where_the_window_stands(path).read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return False
    return _is_running(pid)


def _is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_instrument_settings(path: Path | None = None) -> dict:
    """The settings in the file, or nothing when there is no file yet."""
    where = path or where_the_instrument_stands()
    try:
        held = json.loads(where.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return {key: held[key] for key in CHANGEABLE if key in held}


def write_instrument_settings(settings: dict, path: Path | None = None) -> Path:
    """Write the settings whole; a job the mock does not have is refused."""
    if "job" in settings and settings["job"] not in JOBS:
        raise ValueError(f"unknown job {settings['job']!r}; have {list(JOBS)}")
    where = path or where_the_instrument_stands()
    where.parent.mkdir(parents=True, exist_ok=True)
    kept = {**read_instrument_settings(where), **{k: v for k, v in settings.items() if k in CHANGEABLE}}
    where.write_text(json.dumps(kept, indent=2), encoding="utf-8")
    return where


def _read_the_settings(handle: MockHandle) -> None:
    """The file wins: what it holds is what the instrument stands on."""
    for key, value in read_instrument_settings(handle.state_file).items():
        setattr(handle, key, value)


def _write_the_settings(handle: MockHandle) -> None:
    write_instrument_settings({key: getattr(handle, key) for key in CHANGEABLE}, handle.state_file)


def open_the_window(connection: dict) -> None:
    """Open the mock's own window beside a session, unless one is open already.

    On a real microscope the vendor's software is simply there; the mock has
    only its window, and an operator connecting to the mock wants it in front
    of them without remembering to start it. Its own process, so closing it
    never touches the session. A window that cannot be opened is a warning,
    never a failed connect.
    """
    state_file = where_the_instrument_stands(connection)
    if the_window_is_open(state_file):
        return
    # The window is started as a module of this workflow, by the workflow's own
    # name. The folder of workflows it sits in goes on the new Python's search
    # path, wherever that folder is, as the bridge puts it on its own.
    workflows = str(Path(__file__).resolve().parents[len(__package__.split("."))])
    search_path = os.pathsep.join(filter(None, [workflows, os.environ.get("PYTHONPATH")]))
    try:
        subprocess.Popen(
            [sys.executable, "-m", f"{__package__}.window"],
            env={**os.environ, STATE_FILE_ENV: str(state_file), "PYTHONPATH": search_path},
        )
    except OSError as why:
        logging.getLogger(__name__).warning("the mock instrument window could not be opened: %s", why)


def connect(connection: dict):
    """Open a session with a small vendor-authored tile setup.

    Receives the whole variable connection dict; a real driver would validate the
    api and authenticate with e.g. ``connection["client"]`` / credentials. The
    stage counts from its own zero, so ``set_xyz`` works at once.

    ``connection["open_window"]`` true opens the mock's own window beside the
    session (:func:`open_the_window`), as the interface asks when it offers the
    mock: an operator expects the instrument's software to be there. A script
    that plugs the mock in leaves it out and gets no window.
    """
    if connection.get("open_window"):
        open_the_window(connection)
    handle = MockHandle()
    handle.client = connection.get("client")
    handle.connection = dict(connection)
    handle.connected_at = time.monotonic()
    handle.state_file = where_the_instrument_stands(connection)
    _read_the_settings(handle)
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


def _within_the_travel(position: dict[str, float]) -> None:
    """Refuse a target outside the stage's travel, before anything moves."""
    for axis, value in position.items():
        low, high = TRAVEL_UM[axis]
        if not (low <= value <= high):
            raise ValueError(
                f"{axis} = {value:g} um is outside the stage's travel [{low:g}, {high:g}] um"
            )


def get_actuators(handle: MockHandle) -> dict:
    """The motors each axis offers, and the one used when a command chooses none."""
    _require_open(handle)
    return {
        axis: {"options": list(opts), "default": _DEFAULT_ACTUATORS[axis]}
        for axis, opts in _ACTUATORS.items()
    }


def get_acquisition_settings(handle: MockHandle) -> dict:
    """How a capture is triggered: ``full``, the whole of the selected job, the only way here.

    The job itself, the mock's stored acquisition, is part of the state; how
    and where the files are saved is the connection's. This menu holds the
    trigger and nothing else, as the controller's contract asks.
    """
    _require_open(handle)
    return {"trigger": {"options": ["full"], "default": "full", "active": "full"}}


def _with_defaults(handle: MockHandle, settings: dict | None) -> dict:
    """Validate settings against the menu, filling omissions from the active values."""
    menu = get_acquisition_settings(handle)
    resolved = {name: spec["active"] for name, spec in menu.items()}
    for name, value in (settings or {}).items():
        if name not in menu:
            raise ValueError(f"unknown acquisition setting {name!r}")
        if value not in menu[name]["options"]:
            raise ValueError(f"invalid value {value!r} for acquisition setting {name!r}")
        resolved[name] = value
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
    """Where the stage stands, in micrometres from its zero."""
    return {"x": handle.x, "y": handle.y, "z": handle.z}


def get_xyz(handle: MockHandle, *, with_actuators: dict | None = None) -> dict:
    """Where the stage is, per axis: ``position``, ``unit``, ``used_actuator``, ``actuator_readings``, ``canvas``.

    ``position`` is in micrometres from the origin. ``used_actuator`` is the
    motor this call used: the one ``with_actuators`` named, or the default.
    ``actuator_readings`` gives every motor of the axis with its own raw reading: for
    z, how far the coarse drive, the galvo and the piezo each stand from their
    own zero. ``canvas`` is everywhere a picture can show along that axis (see
    :data:`CANVAS_UM`): the travel, widened by half a field and half a stack.
    The travel itself stays inside the driver, where every move is checked
    against it.
    """
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    user = _user_position(handle)
    readings = {
        "x": {"motoric": handle.x},
        "y": {"motoric": handle.y},
        "z": dict(handle.z_motors),
    }
    return {
        axis: {
            "position": user[axis],
            "unit": "micrometer",
            "used_actuator": chosen[axis],
            "actuator_readings": readings[axis],
            "canvas": list(CANVAS_UM[axis]),
        }
        for axis in ("x", "y", "z")
    }


def set_xyz(
    handle: MockHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to an absolute target (um), then answer exactly like ``get_xyz``.

    The chosen actuators realize this move only — the selection is never
    remembered (omitted axes always default to the reference actuator). A
    target outside the travel is refused with ``ValueError``, and the stage
    stays where it was. The answer is read back after the move, so it shows
    where the stage now stands.
    """
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    target = {"x": float(x), "y": float(y), "z": float(z)}
    _within_the_travel(target)
    handle.z_motors[chosen["z"]] += target["z"] - handle.z
    handle.x, handle.y, handle.z = target["x"], target["y"], target["z"]
    return get_xyz(handle, with_actuators=with_actuators)


def acquire(
    handle: MockHandle,
    *,
    position_label: str,
    acquisition_settings: dict | None,
    acquisition_type: str,
    output_folder: str | None,
) -> dict:
    """Capture the selected job here and save it, returning the record.

    Every file name is ``acquisition_type``, then ``position_label``, as the
    workflow gave them; the mock adds the time point, channel and plane. The
    files go into ``data`` in ``output_folder``, or in the connection's
    ``output_root`` when it is None, as the Leica lays out the folder it is
    given, and a name already used there gets ``_001``, ``_002``, ... so an
    earlier capture is never overwritten. Captures and saves in one step --
    there is no separate export.
    """
    _require_open(handle)
    _read_the_settings(handle)
    settings = _with_defaults(handle, acquisition_settings)
    root = (Path(output_folder) if output_folder is not None else _the_output_root(handle)) / "data"
    stem = _a_free_stem(root, f"{acquisition_type}_{position_label}")
    # The stage is standing at the centre of the range; the job says how far
    # either side to go and in what steps. One 2-D plane per file, flat, which
    # is what every ZMART driver writes -- a stack is a list of planes, never
    # one stacked file.
    heights = stack_heights(handle)
    taken = [
        (channel, z_index, height)
        for z_index, height in enumerate(heights)
        for channel in range(channels_of(handle))
    ]
    paths = [
        _write_a_frame(handle, root, stem, channel, z_index, height)
        for channel, z_index, height in taken
    ]
    printed = _print_the_state(handle, root, stem)
    # The two keys a client follows, in the shapes the real driver answers
    # with: ``files`` every file saved, the name the ZMART Controller's
    # contract fixes, and ``planes`` the manifest that tells a channel from a
    # z. Each plane says where on the sample it was taken,
    # because the driver is the only thing that knows: a saved file says how
    # large a pixel is and nothing about where it came from, and the stage
    # stands at the middle of a stack while its planes are spread either side.
    #
    # ``path`` is where the pixels are and ``t``/``c``/``z`` where inside them.
    # A flat OME-TIFF holds exactly the one plane they name; were this a store,
    # the same three would index into it and only the path would change.
    where = _user_position(handle)
    planes = [
        {
            "t": 0,
            "z": z_index,
            "c": channel,
            "path": str(path),
            "x_um": where["x"],
            "y_um": where["y"],
            "z_um": height,
        }
        for (channel, z_index, height), path in zip(taken, paths, strict=True)
    ]
    return {
        "position_label": position_label,
        "acquisition_type": acquisition_type,
        "trigger": settings["trigger"],
        "job": handle.job,
        "position": _user_position(handle),
        "files": [*(plane["path"] for plane in planes), str(printed)],
        "planes": planes,
    }


def _the_output_root(handle: MockHandle) -> Path:
    """Where this mock saves when acquire names no folder: the connection's
    ``output_root``, or ``mock-output`` here."""
    return Path(handle.connection.get("output_root") or "mock-output")


def _a_free_stem(root: Path, name: str) -> str:
    """``name``, or ``name_001``, ``name_002``, ...: the first no earlier capture in *root* used."""
    stem, number = name, 0
    while (root / f"{stem}_T000000_C00_Z00000.ome.tiff").exists():
        number += 1
        stem = f"{name}_{number:03d}"
    return stem


def stack_heights(handle: MockHandle) -> list[float]:
    """The frame heights the selected job visits, around where the stage stands.

    A single-plane capture visits exactly where the stage is. A stack is
    centred there, which is why a caller drives to the middle of the range it
    wants searched rather than to the bottom of it.
    """
    stack = JOB_STACKS.get(handle.job, _ONE_PLANE)
    centre = handle.z
    middle = (stack["z_planes"] - 1) / 2
    return [centre + (index - middle) * stack["z_step_um"] for index in range(stack["z_planes"])]


def channels_of(handle: MockHandle) -> int:
    """How many channels the selected job takes, one file per channel."""
    return JOB_STACKS.get(handle.job, _ONE_PLANE)["channels"]


def _write_a_frame(
    handle: MockHandle,
    root: Path,
    stem: str,
    channel: int,
    z_index: int,
    height_um: float,
) -> Path:
    """Write one plane of the sample as it looks from *height_um*, and return it.

    It writes rather than merely naming a file, because the real driver does:
    a record naming files that are not there is one a client can follow on the
    microscope and not on the bench. And it writes the sample rather than a
    placeholder, because a focus routine scored against a picture that never
    changes cannot be told from one that works.

    ``numpy`` and ``tifffile`` are imported here, not at the top, so that
    plugging in this driver stays free of them — the operator page's bridge
    imports it at start-up and is standard library plus the controller, which
    is what lets it run on a microscope PC with nothing installed.
    """
    import numpy as np  # noqa: PLC0415 — see above
    import tifffile  # noqa: PLC0415

    # The canonical name, flat, one file per plane: the acquisition type and
    # the label, then which plane of the capture it is. Nothing has to be
    # opened to know what it holds.
    path = root / f"{stem}_T000000_C{channel:02d}_Z{z_index:05d}.ome.tiff"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_px, px = frame_of(handle.job)
    where = _user_position(handle)
    frame = _the_sample_from(np, where["x"], where["y"], height_um, channel, frame_px, px)
    size = frame.shape[0]
    tifffile.imwrite(
        path,
        frame,
        description=(
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            '<Image><Pixels DimensionOrder="XYCZT" Type="uint16" '
            f'SizeX="{size}" SizeY="{size}" SizeC="1" SizeZ="1" SizeT="1" '
            f'PhysicalSizeX="{px}" PhysicalSizeY="{px}"/></Image></OME>'
        ),
    )
    return path


#: How wide a captured frame is, in pixels: a quarter of the micrograph.
_FRAME_PX = 256
#: What each job images: how many pixels across and how much sample one
#: pixel covers. The job owns the geometry, as on a real instrument, where
#: the objective and the format come with the job the operator selected.
#: ``Target`` is the close look for targets: far fewer micrometres across
#: than an overview field and finer pixels over them -- the same micrograph
#: sampled finer than it was recorded, what a mock can offer for
#: magnification.
_JOB_FRAMES: dict[str, tuple[int, float]] = {
    "Overview": (_FRAME_PX, _PIXEL_UM),
    "Overview stack": (_FRAME_PX, _PIXEL_UM),
    "Focussing": (256, 1.0),
    "Target": (128, 1.0),
    "Target stack": (128, 1.0),
    "Target focussing": (128, 1.0),
}


def frame_of(job: str) -> tuple[int, float]:
    """How wide a capture under this job is in pixels, and how much sample
    one pixel covers, in micrometres. The job owns the geometry, as on a real
    instrument."""
    return _JOB_FRAMES.get(job, (_FRAME_PX, _PIXEL_UM))

#: The speck's size in pixels, and how much of the full range its edges span.
#: Its squares are two pixels wide: a sharpness metric reads the difference two
#: pixels apart, and squares one pixel wide cancel in it, leaving a speck that
#: real tissue out-scores at every height.
_SPECK_PX = 32
_SPECK_LEVEL = 4095.0

#: The micrograph the sample is made of, loaded on the first capture: one
#: plane of a mouse kidney section, its three channels first, shipped with
#: the package (see ``kidney.py``). Real tissue rather than noise, because a
#: detector run over the overview has to find real cells, and nothing made of
#: random numbers has any.
_sample = None


def _the_micrograph(np):
    """The kidney's middle plane as (channel, row, column), read once."""
    global _sample
    if _sample is None:
        from .kidney import the_kidney_plane  # noqa: PLC0415 -- see _write_a_frame

        _sample = the_kidney_plane().astype("float64")
    return _sample


def _softened(np, plane):
    """One separable box pass: what being a little further out of focus does."""
    plane = (np.roll(plane, 1, 0) + plane + np.roll(plane, -1, 0)) / 3.0
    return (np.roll(plane, 1, 1) + plane + np.roll(plane, -1, 1)) / 3.0


def _blurred(np, plane, radius: float):
    """*plane* softened by a fractional number of passes.

    Fractional because in whole passes several planes come out identically
    sharp, and the peak is then whichever of them happened to be scored first
    -- an artefact of the pretending rather than of the focus.
    """
    for _ in range(int(radius)):
        plane = _softened(np, plane)
    part = radius - int(radius)
    return (1.0 - part) * plane + part * _softened(np, plane)


def _mirrored(np, index, length: int):
    """*index* folded back into ``0 .. length-1``, reflecting at both ends."""
    period = 2 * length - 2
    index = index % period
    return np.where(index >= length, period - index, index)


def _the_sample_from(
    np, x_um: float, y_um: float, height_um: float, channel: int,
    frame_px: int = _FRAME_PX, pixel_um: float = _PIXEL_UM,
):
    """The sample as it looks from *height_um*: the tissue, and any dust with it.

    The tissue is the micrograph, one pixel of it per pixel of the frame, laid
    across the whole stage mirrored edge to edge so that every position has
    tissue under it and no seam where a picture ends -- a seam is an edge, and
    a detector run over the overview would find it. The frame is the piece
    centred on (x, y). It is softened by how far the
    drive is from where the sheet lies here -- detail is what a sharpness
    metric measures and blur is what removes it. Where it comes into focus
    changes with position, because the sheet is tilted.

    A speck of dust, where there is one, is added on top: a hard-edged patch
    whose contrast collapses within a micrometre or two of its own height. That
    is the whole failure this driver can show -- a peak sharper than the tissue
    and far narrower, at a height the tissue is not at.
    """
    micrograph = _the_micrograph(np)[channel]
    # The frame's pixels laid over the micrograph's: a finer pixel than the
    # micrograph's reads the same recorded pixel more than once, the nearest.
    step = pixel_um / _PIXEL_UM
    across = (np.arange(frame_px) - frame_px // 2) * step
    rows = _mirrored(np, np.rint(y_um / _PIXEL_UM + across).astype(int), micrograph.shape[0])
    cols = _mirrored(np, np.rint(x_um / _PIXEL_UM + across).astype(int), micrograph.shape[1])
    tissue = micrograph[np.ix_(rows, cols)]
    focus_um = sharp_height_um(x_um, y_um)
    frame = _blurred(np, tissue, _BLUR_PER_UM * abs(height_um - focus_um))

    speck = debris_at(x_um, y_um)
    if speck is not None:
        away = height_um - (focus_um + speck["offset_um"])
        # Gaussian in height: sharp within its own width and gone outside it,
        # which is what makes its peak narrow enough to be told from tissue.
        showing = math.exp(-(away * away) / (2.0 * speck["width_um"] ** 2))
        if showing > 1e-3:
            edges = (np.indices((_SPECK_PX, _SPECK_PX)).sum(axis=0) // 2) % 2
            patch = edges * (_SPECK_LEVEL * speck["contrast"] * showing)
            at = frame_px // 2 - _SPECK_PX // 2
            frame = frame.copy()
            frame[at: at + _SPECK_PX, at: at + _SPECK_PX] += patch

    return np.clip(frame, 0.0, 65535.0).astype("uint16")


def _print_the_state(handle: MockHandle, root: Path, stem: str) -> Path:
    """Print the state this capture was made under beside the images.

    The state is embedded in the image too, where reading it costs opening a
    picture. In ``metadata/ZMART_state`` beside the images -- where the
    Leica prints it, beside the vendor's own account, one folder per
    party -- it can simply be read. One file per
    acquisition: the name of the images without the channel and the z-slice,
    which one state spans.
    """
    metadata = root / "metadata" / "ZMART_state"
    metadata.mkdir(parents=True, exist_ok=True)
    printed = metadata / f"{stem}_T000000_ZMART_state.json"
    printed.write_text(json.dumps(get_state(handle), indent=2), encoding="utf-8")
    return printed


def get_state(handle: MockHandle) -> dict:
    """Return the opaque state: the changeable settings first, then the
    observed report (identity and condition, read-only)."""
    _require_open(handle)
    _read_the_settings(handle)
    return {
        "changeable": {
            "job": handle.job,
            "laser_power": handle.laser_power,
            "gain": handle.gain,
        },
        "observed": {
            "serial": handle.serial,
            "objective": {
                "magnification": handle.magnification,
                "numerical_aperture": handle.numerical_aperture,
                "immersion": handle.immersion,
            },
            "zoom": handle.zoom,
            # The controller's own keys: the image size and pixel size of the
            # current settings, which the job owns here, as on a real instrument.
            "image_size_px": [frame_of(handle.job)[0]] * 2,
            "pixel_size_um": [frame_of(handle.job)[1]] * 2,
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
    if "job" in changeable:
        # Refused rather than accepted quietly: a job the instrument does not
        # have is a capture that would not run, and a client is better told now
        # than at the press.
        if changeable["job"] not in JOBS:
            raise ValueError(f"unknown job {changeable['job']!r}; have {list(JOBS)}")
        handle.job = changeable["job"]
        applied["job"] = handle.job
    if "laser_power" in changeable:
        handle.laser_power = changeable["laser_power"]
        applied["laser_power"] = handle.laser_power
    if "gain" in changeable:
        handle.gain = changeable["gain"]
        applied["gain"] = handle.gain
    if applied:
        _write_the_settings(handle)
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
        # terms (``frame_z_um``). It reports where the sample actually is
        # above this (x, y), not the height it was driven to -- an autofocus
        # that hands back its own input measures nothing, and a focus map
        # built from one would come out flat however wrong it was.
        where = _user_position(handle)
        frame_z = sharp_height_um(where["x"], where["y"])
        return {
            "ran": dict(procedure),
            "focus_um": frame_z,
            "frame_z_um": frame_z,
        }
    return {"ran": dict(procedure)}


def _the_canvas() -> dict[str, list[float]]:
    """Everywhere a capture can show: the stage's whole travel, and half a field beyond it.

    A field is centred where the stage stands, so one taken at the edge of the
    travel shows half its width further, and a stack half its depth above and
    below. The interface lays out the viewer's area from this, and the viewer
    refuses, whole, a capture that shows outside that area; the
    stage stands at its zero, at the edge of where it travels, until the
    operator first moves it. So the canvas is the widest field's half and the
    deepest stack's half beyond the travel on every side.
    """
    half_field = max(px * um for px, um in (frame_of(job) for job in JOBS)) / 2
    stacks = [_ONE_PLANE, *JOB_STACKS.values()]
    half_stack = max((one["z_planes"] - 1) * one["z_step_um"] for one in stacks) / 2
    beyond = {"x": half_field, "y": half_field, "z": half_stack}
    return {axis: [low - beyond[axis], high + beyond[axis]] for axis, (low, high) in TRAVEL_UM.items()}


#: Everywhere a picture can show per axis, in micrometres: what ``get_xyz``
#: reports as ``canvas``, and so the area the page draws and the viewer places
#: pictures on.
CANVAS_UM = _the_canvas()

# The connection checks, in the order they answer, each with the delay after
# connect (seconds) at which its answer becomes available. Until then a client
# polling get_info reads "pending" for it. A real driver answers these from
# the instrument; the mock answers from its own state, staggered so the
# pending state is real and not just a word.
_CONNECTION_CHECKS: list[tuple[str, float]] = [
    ("driver", 0.0),
    ("client", 0.25),
    ("serial", 0.5),
    ("stage", 0.75),
    ("limits", 0.9),
    ("saving", 1.0),
]

PENDING = "pending"


def _connection_status(handle: MockHandle) -> dict[str, str]:
    elapsed = time.monotonic() - handle.connected_at
    user = _user_position(handle)
    answers = {
        "driver": "mock_microscope, the interface's pretend microscope",
        "client": str(handle.client),
        "serial": handle.serial,
        "stage": f"x {user['x']:.1f} · y {user['y']:.1f} · z {user['z']:.1f} um",
        # What the stage is fenced by, and whether an operator published it or
        # the mock is standing on its own physical travel -- the same
        # "(fallback)" the Leica driver reports until limits are published.
        "limits": "the stage's own travel (a mock has no setup)",
        "saving": f"OME-TIFF in the folder each capture names, else under {_the_output_root(handle)}",
    }
    return {
        key: (answers[key] if elapsed >= after else PENDING) for key, after in _CONNECTION_CHECKS
    }


def get_info(handle: MockHandle) -> dict:
    """Describe the microscope, what is set up on it, and the connection's health.

    ``description`` is the microscope in plain words and ``setup`` what is set
    up once on it, as every ZMART driver gives them: here only saving, where
    the connection's ``output_root`` puts the files when acquire names no
    folder. ``chooses_its_own_folder`` is False: the mock saves in the folder
    acquire is given.
    ``connection_status`` is what a client shows under Connect: one row per
    key, its value the answer or ``"pending"`` until the check has answered
    (a value beginning ``failed`` is a failed check). The area a client
    draws to scale is not here: it is ``get_xyz``'s ``canvas``, per axis.
    """
    _require_open(handle)
    saving = (
        f"OME-TIFF files in the output folder acquire is given, else under {_the_output_root(handle)}, "
        "as the connection's output_root says"
    )
    return {
        "description": DESCRIPTION,
        "setup": {"saving": {"done": True, "says": saving}},
        "chooses_its_own_folder": False,
        "connection_status": _connection_status(handle),
        "tile_positions": [dict(pos) for pos in handle.tile_positions],
        "focus_positions": [
            {"x": pos["x"], "y": pos["y"], "z": pos["z"]} for pos in handle.tile_positions
        ],
        "client": handle.client,
    }


#: The microscope in plain words, for whoever drives it: a person, a notebook,
#: or an assistant that builds its picture of the instrument from this.
DESCRIPTION = """A pretend widefield microscope that runs entirely in software, for trying the ZMART interface without hardware. It images one plane of a mouse kidney section (three channels) laid across the whole stage. The section is slightly tilted, so the sharp height changes a little from place to place, and here and there a speck of dust is sharp at a different height from the tissue.

Stage: x and y move the slide, z moves the focus, all in micrometres from the stage's own zero. x travels from -5000 to 125000, y from -5000 to 85000, z from -1000 to 11000. A move outside that is refused and nothing moves.

Stage motors: x and y have one motor each; z has three, "motoric", the default, "galvo" and "piezo".

Settings (the changeable part of the state): job is the stored acquisition the next capture is taken with, one of Overview (256 x 256 pixels of 4 um, three channels), Overview stack (the same, 7 planes 2 um apart), Focussing (a 61-plane stack of 1 um pixels, one channel), Target (128 x 128 pixels of 1 um, three channels), Target stack (the same, 11 planes 1 um apart) and Target focussing (41 planes 0.5 um apart, one channel). laser_power and gain are kept but change nothing in the pictures. The job is also chosen in the mock instrument's own window, the way an operator chooses one in the vendor's software.

Acquiring has one trigger, full: the whole of the selected job. It saves one OME-TIFF per plane and channel straight into the output folder it is given, each file named by the acquisition type and the position label, then the time point, the channel and the plane."""
