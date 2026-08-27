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


#: How much sample one pixel covers, in micrometres. Reported in the state and
#: written into every frame, so the two cannot come to disagree.
_PIXEL_UM = 1.0

#: The jobs this pretend instrument has stored, in the order it lists them.
_JOBS: tuple[str, ...] = ("Overview", "HiRes", "Survey")


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
    path = _write_a_frame(handle, acquisition_type, acquisition_hash, position_label)
    printed = _print_the_state(
        handle, path.parent, acquisition_type, acquisition_hash, position_label
    )
    # The two keys a client follows, in the shapes the real driver answers
    # with: ``images`` the simple list, ``planes`` the manifest that tells a
    # channel from a z. One plane, because this instrument captures one.
    planes = [{"t": 0, "z": 0, "c": 0, "path": str(path)}]
    return {
        "acquisition_type": acquisition_type,
        "acquisition_hash": acquisition_hash,
        "position_label": position_label,
        "format": options["format"],
        "procedure": options["procedure"],
        "settle": settle,
        "position": _user_position(handle),
        "images": [plane["path"] for plane in planes],
        "planes": planes,
        # What the driver printed about this capture, beside the images.
        "metadata": [str(printed)],
    }


def _write_a_frame(
    handle: MockHandle, acquisition_type: str, acquisition_hash: str, position_label: str
) -> Path:
    """Write one OME-TIFF where a real driver would, and return the path.

    It writes rather than merely naming a file, because the real driver does:
    a record naming files that are not there is one a client can follow on the
    microscope and not on the bench.

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
        "T000000_C00_Z00000.ome.tiff"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    px = _PIXEL_UM
    size = 64  # read to check a file arrived, never to look at
    tifffile.imwrite(
        path,
        np.tile(np.linspace(0, 4095, size, dtype="uint16"), (size, 1)),
        description=(
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            '<Image><Pixels DimensionOrder="XYCZT" Type="uint16" '
            f'SizeX="{size}" SizeY="{size}" SizeC="1" SizeZ="1" SizeT="1" '
            f'PhysicalSizeX="{px}" PhysicalSizeY="{px}"/></Image></OME>'
        ),
    )
    return path


def _print_the_state(
    handle: MockHandle,
    data: Path,
    acquisition_type: str,
    acquisition_hash: str,
    position_label: str,
) -> Path:
    """Print the state this capture was made under beside the images.

    The state is embedded in the image too, where reading it costs opening a
    picture. In ``data/metadata`` it can simply be read. One file per
    acquisition: the name of the images without the channel and the z-slice,
    which one state spans.
    """
    metadata = data / "metadata"
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
            "frame_size": {"x": 1024.0, "y": 1024.0, "unit": "um"},
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
        # terms (``frame_z_um``). The mock's "sharp" z is simply wherever
        # the stage currently sits, which is deterministic and lets the
        # workflow's focus step run end-to-end offline.
        frame_z = handle.z - handle.origin_z
        return {"ran": dict(procedure), "focus_um": handle.z, "frame_z_um": frame_z}
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
