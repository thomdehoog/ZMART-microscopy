"""Mock microscope integration: a reference driver with no hardware.

It exercises the full controller contract so the package can be tested offline,
and it shows the shape a real driver implements: it receives the connection dict,
owns the frame origin (user coordinates are micrometers from it), and does the
work the controller does not -- settling before capture, saving, and
owning the changeable/observed state boundary.

It sits beside the other drivers, and that is deliberate. It was filed under
``zmart_controller/tests/`` for a while, which made everything that needed a
pretend instrument -- the controller's own tests, the operator page's bridge,
the workflow's -- import a production dependency from a test package, and made
the one place pretend behaviour belongs look like a place it did not.

Driver contract used by the registry: ``connect(connection) -> handle`` opens a
session and returns an opaque handle; every other operation takes that handle as
its first argument.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import math
import random
import time
import uuid
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
#: ``frame_size`` reports, and at which the sample's nuclei come out a few
#: tens of micrometres wide, the size a detector is told to look for.
_PIXEL_UM = 4.0

#: The jobs this pretend instrument has stored, in the order it lists them.
_JOBS: tuple[str, ...] = ("Overview", "HiRes", "Survey")

#: What each kind of acquisition captures. On a real instrument this comes from
#: the settings the operator imported for that kind of scan; here it is how the
#: driver knows what is being asked of it, since nothing else about a mock says.
#: A ``focussing`` capture is a stack -- 61 planes over +/-34 um, fine enough
#: that a speck a micrometre or two wide lands on a plane at all. A stack that
#: stepped past its dust could not show the failure focusing exists to survive.
#: It takes one channel, as a focus job does. Everything else is the single
#: plane an imaging scan takes, in every channel the sample has.
_ONE_PLANE = {"z_planes": 1, "z_step_um": 0.0, "channels": 3}
_STACKS: dict[str, dict] = {
    "focussing": {"z_planes": 61, "z_step_um": 68.0 / 60.0, "channels": 1}
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
    # when the session opened (time.monotonic); the connection checks answer
    # one after another from here, so a client polling get_info sees them
    # arrive the way it will on an instrument that takes time to answer
    connected_at: float = 0.0

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
    handle.connected_at = time.monotonic()
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
        "job": {"options": list(_JOBS), "active": handle.job},
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
    acquisition_hash = uuid.uuid4().hex[:6]
    # The stage is standing at the centre of the range; the job says how far
    # either side to go and in what steps. One 2-D plane per file, flat, which
    # is what every ZMART driver writes -- a stack is a list of planes, never
    # one stacked file.
    heights = stack_heights(handle, acquisition_type)
    taken = [
        (channel, z_index, height)
        for z_index, height in enumerate(heights)
        for channel in range(channels_of(acquisition_type))
    ]
    paths = [
        _write_a_frame(
            handle, acquisition_type, acquisition_hash, position_label, channel, z_index, height
        )
        for channel, z_index, height in taken
    ]
    printed = _print_the_state(
        handle, paths[0].parent, acquisition_type, acquisition_hash, position_label
    )
    # The two keys a client follows, in the shapes the real driver answers
    # with: ``images`` the simple list, ``planes`` the manifest that tells a
    # channel from a z. Each plane says where on the sample it was taken,
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
        for (channel, z_index, height), path in zip(taken, paths)
    ]
    return {
        "acquisition_type": acquisition_type,
        "acquisition_hash": acquisition_hash,
        "position_label": position_label,
        "format": options["format"],
        "procedure": options["procedure"],
        "settle": settle,
        "job": options["job"],
        "position": _user_position(handle),
        "images": [plane["path"] for plane in planes],
        "planes": planes,
        # What the driver printed about this capture, beside the images.
        "metadata": [str(printed)],
    }


def stack_heights(handle: MockHandle, acquisition_type: str) -> list[float]:
    """The frame heights this kind of capture visits, around where it stands.

    A single-plane capture visits exactly where the stage is. A stack is
    centred there, which is why a caller drives to the middle of the range it
    wants searched rather than to the bottom of it.
    """
    stack = _STACKS.get(acquisition_type, _ONE_PLANE)
    centre = handle.z - handle.origin_z
    middle = (stack["z_planes"] - 1) / 2
    return [centre + (index - middle) * stack["z_step_um"] for index in range(stack["z_planes"])]


def channels_of(acquisition_type: str) -> int:
    """How many channels this kind of capture takes, one file per channel."""
    return _STACKS.get(acquisition_type, _ONE_PLANE)["channels"]


def _write_a_frame(
    handle: MockHandle,
    acquisition_type: str,
    acquisition_hash: str,
    position_label: str,
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
    registering this driver stays free of them — the operator page's bridge
    imports it at start-up and is standard library plus the controller, which
    is what lets it run on a microscope PC with nothing installed.
    """
    import numpy as np  # noqa: PLC0415 — see above
    import tifffile  # noqa: PLC0415

    root = Path(handle.connection.get("output_root") or "mock-output")
    # ``<type>/data``: the pixels in a folder of their own, so what is made
    # from them afterwards -- a stitched view, an analysis, the vendor's copy --
    # becomes a folder beside it rather than a file to be told apart by name.
    # The canonical name, flat, one file per plane: what the capture was, which
    # capture it was, where on the sample, and which plane of it. Nothing has to
    # be opened to know what it holds.
    path = root / acquisition_type / "data" / (
        f"{acquisition_type}_{acquisition_hash}_{position_label}_"
        f"T000000_C{channel:02d}_Z{z_index:05d}.ome.tiff"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    px = _PIXEL_UM
    where = _user_position(handle)
    frame = _the_sample_from(np, where["x"], where["y"], height_um, channel)
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

#: The speck's size in pixels, and how much of the full range its edges span.
#: Its squares are two pixels wide: a sharpness metric reads the difference two
#: pixels apart, and squares one pixel wide cancel in it, leaving a speck that
#: real tissue out-scores at every height.
_SPECK_PX = 32
_SPECK_LEVEL = 4095.0

#: The micrograph the sample is made of, loaded on the first capture: one
#: plane of scikit-image's mouse kidney, its three channels first. Real
#: tissue rather than noise, because a detector run over the overview has to
#: find real cells, and nothing made of random numbers has any.
_sample = None


def _the_micrograph(np):
    """The kidney's middle plane as (channel, row, column), read once."""
    global _sample
    if _sample is None:
        from skimage.data import kidney  # noqa: PLC0415 -- see _write_a_frame

        _sample = np.moveaxis(kidney()[8], -1, 0).astype("float64")
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


def _the_sample_from(np, x_um: float, y_um: float, height_um: float, channel: int):
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
    half = _FRAME_PX // 2
    rows = _mirrored(np, int(round(y_um / _PIXEL_UM)) - half + np.arange(_FRAME_PX), micrograph.shape[0])
    cols = _mirrored(np, int(round(x_um / _PIXEL_UM)) - half + np.arange(_FRAME_PX), micrograph.shape[1])
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
            at = _FRAME_PX // 2 - _SPECK_PX // 2
            frame = frame.copy()
            frame[at: at + _SPECK_PX, at: at + _SPECK_PX] += patch

    return np.clip(frame, 0.0, 65535.0).astype("uint16")


def _print_the_state(
    handle: MockHandle,
    data: Path,
    acquisition_type: str,
    acquisition_hash: str,
    position_label: str,
) -> Path:
    """Print the state this capture was made under beside the images.

    The state is embedded in the image too, where reading it costs opening a
    picture. In ``data/metadata/ZMART_state`` -- beside the vendor's own
    account, one folder per party -- it can simply be read. One file per
    acquisition: the name of the images without the channel and the z-slice,
    which one state spans.
    """
    metadata = data / "metadata" / "ZMART_state"
    metadata.mkdir(parents=True, exist_ok=True)
    printed = (
        metadata
        / f"{acquisition_type}_{acquisition_hash}_{position_label}_T000000_ZMART_state.json"
    )
    printed.write_text(json.dumps(get_state(handle), indent=2), encoding="utf-8")
    return printed


def get_state(handle: MockHandle) -> dict:
    """Return the opaque state: the changeable settings first, then the
    observed report (identity and condition, read-only)."""
    _require_open(handle)
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
            "pixel_size": {"x": _PIXEL_UM, "y": _PIXEL_UM, "unit": "um"},
            "frame_size": {
                "x": _FRAME_PX * _PIXEL_UM,
                "y": _FRAME_PX * _PIXEL_UM,
                "unit": "um",
            },
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
        if changeable["job"] not in _JOBS:
            raise ValueError(f"unknown job {changeable['job']!r}; have {list(_JOBS)}")
        handle.job = changeable["job"]
        applied["job"] = handle.job
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
        # terms (``frame_z_um``). It reports where the sample actually is
        # above this (x, y), not the height it was driven to -- an autofocus
        # that hands back its own input measures nothing, and a focus map
        # built from one would come out flat however wrong it was.
        where = _user_position(handle)
        frame_z = sharp_height_um(where["x"], where["y"])
        return {
            "ran": dict(procedure),
            "focus_um": frame_z + handle.origin_z,
            "frame_z_um": frame_z,
        }
    return {"ran": dict(procedure)}


# How far the mock's stage travels, in micrometres from the raw zero. The
# canvas a client draws is this area to scale; the stage's position is
# get_xyz's business, not this constant's.
CANVAS_UM = {"x_um": [0.0, 120_000.0], "y_um": [0.0, 80_000.0], "z_um": [0.0, 10_000.0]}

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
    ("output root", 1.0),
]

PENDING = "pending"


def _connection_status(handle: MockHandle) -> dict[str, str]:
    elapsed = time.monotonic() - handle.connected_at
    user = _user_position(handle)
    answers = {
        "driver": "mock · mock-scope · mock-api",
        "client": str(handle.client),
        "serial": handle.serial,
        "stage": f"x {user['x']:.1f} · y {user['y']:.1f} · z {user['z']:.1f} um",
        "output root": str(Path(handle.connection.get("output_root") or "mock-output")),
    }
    return {
        key: (answers[key] if elapsed >= after else PENDING) for key, after in _CONNECTION_CHECKS
    }


def get_info(handle: MockHandle) -> dict:
    """Return the live vendor-authored setup, the connection's health, and the canvas.

    ``connection_status`` is what a client shows under Connect: one row per
    key, its value the answer or ``"pending"`` until the check has answered
    (a value beginning ``failed`` is a failed check). ``canvas`` is the stage
    travel a client draws to scale; where the stage is comes from ``get_xyz``.
    """
    _require_open(handle)
    root = Path(handle.connection.get("output_root") or "mock-output")
    return {
        "connection_status": _connection_status(handle),
        "canvas": dict(CANVAS_UM),
        "tile_positions": [dict(pos) for pos in handle.tile_positions],
        "focus_positions": [
            {"x": pos["x"], "y": pos["y"], "z": pos["z"]} for pos in handle.tile_positions
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
