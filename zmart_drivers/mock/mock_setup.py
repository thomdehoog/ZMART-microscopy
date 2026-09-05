"""The mock microscope's configuration: a pretend rig, set up the way a real one is.

Where :mod:`mock_driver` stands in for a microscope being *driven*, this
stands in for one being *set up*. It registers with :mod:`zmart_drivers.setup`, not
with the controller, and supplies the small vocabulary that package asks of a
driver: where the stage is, move it, take a picture, say which lens is in,
read the operator's markers, and read and publish the four configuration
documents. Everything measured from the pictures happens in
:mod:`zmart_analysis`; nothing here knows how to work out an orientation.

## The rig

A real microscope has properties nobody chose in software: how far its stage
can physically travel, which way its camera is mounted, what each objective
sees. The mock keeps those in one small file, ``rig.json``, under the same
machine root its published snapshots go to. The mock instrument window edits
it -- turning the camera, changing the lens, dropping a marker where the
stage stands -- the way an operator does those things in LAS X, and this
module reads it back on every call. A picture taken here is the sample as
:mod:`mock_driver` draws it, then *recorded the way a camera turned that way
would record it*, so the orientation step has something real to find. Until
an orientation is measured and published, target acquisition's pictures come
out turned too, as they would on a rig nobody has measured.

## The machine root

Published documents go to ``<machine root>/configuration_<datetime>/<subsystem>/<datetime>/<file>``,
the same shape the Leica driver uses under ProgramData, so a reader of one
tree can read the other. The root is ``connection["machine_root"]``, else the
``ZMART_MOCK_MACHINE`` environment variable, else ``~/.zmart-mock/machine``.
The newest snapshot in each subsystem is the one that stands.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MACHINE_ROOT_ENV = "ZMART_MOCK_MACHINE"
RIG_FILENAME = "rig.json"

SUBSYSTEM_FILES = {
    "limits": "limits.json",
    "orientation": "orientation.json",
    "calibration": "calibration.json",
    "origin": "origin.json",
}

#: The stage's physical travel, in micrometres from its raw zero. The backstop
#: no published envelope can widen: the mock refuses to publish limits beyond
#: it, and refuses to move outside it whatever any file says. It reaches a
#: little past the area the canvas draws (``mock_driver.CANVAS_UM``), as a
#: real stage has some travel beyond its nominal working area -- and so that
#: a run standing on an origin near the canvas's edge can still look around it.
PHYSICAL_UM = {"x_um": [-5_000.0, 125_000.0], "y_um": [-5_000.0, 85_000.0], "z_um": [-1_000.0, 11_000.0]}

#: The settings this pretend instrument lets the driver change, each of which
#: a limits document may fence. Mirrors the mock driver's changeable settings.
SETTINGS = ("set_laser_power", "set_gain")

#: What the rig is on a fresh machine: a camera mounted a quarter-turn round,
#: which is the whole reason the orientation step exists; a turret of four
#: lenses, each of the higher-power ones looking a little off the 10x and
#: focusing a little higher or lower, which is what the optics step measures
#: (a perfectly parcentric and parfocal microscope would have every offset at
#: zero); no markers placed yet; the stage at home.
DEFAULT_RIG = {
    "camera": {"rotation_deg": 90, "reflection": False},
    "objectives": [
        {"slot": 0, "name": "10x dry", "pixel_um": 4.0, "offset_um": {"x": 0.0, "y": 0.0, "z": 0.0}},
        {"slot": 1, "name": "20x dry", "pixel_um": 2.0, "offset_um": {"x": 6.0, "y": -4.0, "z": 1.2}},
        {"slot": 2, "name": "40x dry", "pixel_um": 1.0, "offset_um": {"x": -18.0, "y": 11.0, "z": 3.5}},
        {"slot": 3, "name": "63x oil", "pixel_um": 0.6, "offset_um": {"x": -9.0, "y": 7.0, "z": -2.0}},
    ],
    "objective_slot": 0,
    "frame_px": 256,
    "markers": [],
    # The stage starts in the middle of its travel, and at the height the
    # sample is sharp there (see ``mock_driver.sharp_height_um``), so that a
    # focus stack taken around it finds a peak rather than a slope.
    "stage": {"x_um": 60_000.0, "y_um": 40_000.0, "z_um": 16.0},
}

_SNAPSHOT_FORMAT = "%Y-%m-%dT%H-%M-%S-%fZ"
_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{6}Z$")


# ---------------------------------------------------------------------------
# where things are
# ---------------------------------------------------------------------------


def where_the_machine_is(connection: dict | None = None) -> Path:
    """The machine root: named in the connection, else by the environment,
    else under the user's home."""
    named = (connection or {}).get("machine_root") or os.environ.get(MACHINE_ROOT_ENV)
    return Path(named) if named else Path.home() / ".zmart-mock" / "machine"


def read_rig(root: Path) -> dict:
    """The rig as it stands, with the defaults filled in for anything unsaid."""
    try:
        held = json.loads((root / RIG_FILENAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        held = {}
    rig = json.loads(json.dumps(DEFAULT_RIG))
    for key, value in held.items():
        if key in rig:
            rig[key] = value
    return rig


def write_rig(root: Path, rig: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / RIG_FILENAME
    path.write_text(json.dumps(rig, indent=2), encoding="utf-8")
    return path


def _snapshot_name(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_SNAPSHOT_FORMAT)


#: A configuration folder is ``configuration_<datetime>``, the same shape the
#: Leica keeps under ProgramData: one folder per pass through the workflow,
#: each holding the four subsystem trees in full.
CONFIGURATION_PREFIX = "configuration_"
_CONFIGURATION_RE = re.compile(r"^configuration_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{6}Z$")


def configurations(root: Path) -> list[Path]:
    """Every configuration under the machine root, oldest first."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and _CONFIGURATION_RE.match(p.name))


def configuration_root(root: Path, chosen: str | None = None) -> Path:
    """The configuration folder to stand on: ``chosen`` by name, else the
    newest, else one seeded now so the machine has somewhere to stand."""
    if chosen:
        path = root / chosen
        if not (_CONFIGURATION_RE.match(chosen) and path.is_dir()):
            raise FileNotFoundError(f"no configuration {chosen} under {root}")
        return path
    found = configurations(root)
    if found:
        return found[-1]
    seeded = root / (CONFIGURATION_PREFIX + _snapshot_name(datetime.now(timezone.utc)))
    for subsystem in SUBSYSTEM_FILES:
        (seeded / subsystem).mkdir(parents=True, exist_ok=True)
    return seeded


def new_configuration(root: Path) -> Path:
    """Start a configuration as a full copy of what stands now: the newest
    snapshot of each subsystem of the newest configuration."""
    found = configurations(root)
    name = CONFIGURATION_PREFIX + _snapshot_name(datetime.now(timezone.utc))
    while found and name <= found[-1].name:
        time.sleep(0.001)
        name = CONFIGURATION_PREFIX + _snapshot_name(datetime.now(timezone.utc))
    target = root / name
    for subsystem in SUBSYSTEM_FILES:
        (target / subsystem).mkdir(parents=True)
        if found:
            latest = snapshots(found[-1], subsystem)
            if latest:
                shutil.copytree(latest[-1], target / subsystem / latest[-1].name)
    return target


def configured(connection: dict | None = None) -> str:
    """The id of a configuration the controller will accept: the newest,
    given the rig's default limits if it has none yet. What a test, or an
    example, calls before connecting through the controller -- an operator
    does the same in step 2 of the workflow."""
    root = where_the_machine_is(connection)
    root.mkdir(parents=True, exist_ok=True)
    tree = configuration_root(root)
    if not snapshots(tree, "limits"):
        _publish(tree, "limits", {**_default("limits"), "published_at": datetime.now(timezone.utc).isoformat()})
    return tree.name


def describe_configuration(path: Path) -> dict:
    """One configuration as a listing shows it: id, when it was started, and
    which subsystems hold a published document."""
    stamp = path.name[len(CONFIGURATION_PREFIX):]
    moment = datetime.strptime(stamp, _SNAPSHOT_FORMAT).replace(tzinfo=timezone.utc)
    return {
        "id": path.name,
        "created_at": moment.isoformat(),
        "has": {subsystem: bool(snapshots(path, subsystem)) for subsystem in SUBSYSTEM_FILES},
    }


def snapshots(root: Path, subsystem: str) -> list[Path]:
    """Every published snapshot of one subsystem under one configuration, oldest first."""
    tree = root / subsystem
    if not tree.is_dir():
        return []
    return sorted(p for p in tree.iterdir() if p.is_dir() and _SNAPSHOT_RE.match(p.name))


def newest(root: Path, subsystem: str) -> dict | None:
    """The document that stands for one subsystem, or None when never published."""
    found = snapshots(root, subsystem)
    if not found:
        return None
    path = found[-1] / SUBSYSTEM_FILES[subsystem]
    return json.loads(path.read_text(encoding="utf-8"))


def _publish(root: Path, subsystem: str, document: dict) -> Path:
    """Append one dated snapshot, strictly later than the last."""
    moment = datetime.now(timezone.utc)
    latest = snapshots(root, subsystem)
    name = _snapshot_name(moment)
    while latest and name <= latest[-1].name:
        time.sleep(0.001)
        name = _snapshot_name(datetime.now(timezone.utc))
    target = root / subsystem / name
    target.mkdir(parents=True, exist_ok=False)
    path = target / SUBSYSTEM_FILES[subsystem]
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# the handle and the vocabulary
# ---------------------------------------------------------------------------


@dataclass
class SetupHandle:
    root: Path
    connection: dict = field(default_factory=dict)
    opened_at: float = 0.0
    closed: bool = False
    #: The configuration this setup stands on, by folder name, once chosen.
    configuration: str | None = None
    #: The envelope loaded at open from the configuration's published limits,
    #: the way a real driver loads its limits at connect: None until limits
    #: are published, and unchanged until the setup is opened again.
    envelope: dict | None = None

    @property
    def tree(self) -> Path:
        """The configuration folder read from and published into."""
        return configuration_root(self.root, self.configuration)


def _require_open(handle: SetupHandle) -> None:
    if handle.closed:
        raise RuntimeError("setup is closed")


def open_setup(connection: dict) -> SetupHandle:
    """Open the rig for configuration. Needs no published envelope: the
    physical travel fences every move until one exists."""
    root = where_the_machine_is(connection)
    root.mkdir(parents=True, exist_ok=True)
    if not (root / RIG_FILENAME).exists():
        write_rig(root, read_rig(root))
    # A first configuration is seeded so the machine has one to stand on --
    # the same thing the Leica does at connect -- and its published limits,
    # if any, are loaded now, as a real driver loads them at connect.
    tree = configuration_root(root, connection.get("configuration") or None)
    limits = newest(tree, "limits")
    envelope = None
    if limits:
        envelope = {axis: [float(v) for v in limits[axis]["range"]]
                    for axis in PHYSICAL_UM if isinstance(limits.get(axis), dict) and "range" in limits[axis]}
    return SetupHandle(root=root, connection=dict(connection), opened_at=time.monotonic(), envelope=envelope)


def close_setup(handle: SetupHandle) -> None:
    handle.closed = True


def describe(handle: SetupHandle) -> dict:
    _require_open(handle)
    rig = read_rig(handle.root)
    lens = _current_objective(rig)
    return {
        "label": "Mock microscope · mock API",
        "checks": {
            "driver": "mock · mock-scope · mock-api",
            "stage": _say_position(rig["stage"]),
            "objective": f"slot {lens['slot']} · {lens['name']}",
            "machine root": str(handle.root),
            "configuration": handle.tree.name,
        },
        "subsystems": {
            "limits": {
                "supported": True,
                "document": {
                    "axes": [
                        {"key": "x_um", "label": "X", "unit": "µm"},
                        {"key": "y_um", "label": "Y", "unit": "µm"},
                        {"key": "z_um", "label": "Z", "unit": "µm"},
                    ],
                    "measured": ["x_um", "y_um"],
                    # The stage ranges cannot be left open: a move is checked
                    # against them, and an unfenced axis would be no fence.
                    "required": ["x_um", "y_um", "z_um"],
                    "slots": {"key": "objective_slot", "label": "Objective slots"},
                    "settings": list(SETTINGS),
                },
                "physical": PHYSICAL_UM,
            },
            "orientation": {"supported": True},
            "calibration": {"supported": True,
                            "objectives": [dict(o, offset_um=None) for o in rig["objectives"]]},
            "origin": {"supported": True},
        },
    }


def _say_position(stage: dict) -> str:
    return f"x {stage['x_um']:.0f} · y {stage['y_um']:.0f} · z {stage['z_um']:.1f} um"


def _current_objective(rig: dict) -> dict:
    slot = rig.get("objective_slot", 0)
    for lens in rig["objectives"]:
        if lens["slot"] == slot:
            return lens
    raise RuntimeError(f"the rig names objective slot {slot}, which it does not have")


def where(handle: SetupHandle) -> dict:
    """Where the stage stands, and every drive's reading. The mock has one
    motoric drive per axis and a galvo and a piezo on Z that rest at zero."""
    _require_open(handle)
    stage = read_rig(handle.root)["stage"]
    return {
        **stage,
        "actuators": {
            "x motoric": {"value": stage["x_um"], "unit": "um"},
            "y motoric": {"value": stage["y_um"], "unit": "um"},
            "z motoric": {"value": stage["z_um"], "unit": "um"},
            "z galvo": {"value": 0.0, "unit": "um"},
            "z piezo": {"value": 0.0, "unit": "um"},
        },
    }


def move(handle: SetupHandle, x_um: float, y_um: float, z_um: float) -> dict:
    """Move within the limits loaded at open, and within the physical
    travel whatever is published; answer with the readback."""
    _require_open(handle)
    asked = {"x_um": float(x_um), "y_um": float(y_um), "z_um": float(z_um)}
    for axis, value in asked.items():
        low, high = PHYSICAL_UM[axis]
        if not (low <= value <= high):
            raise RuntimeError(
                f"{axis} = {value:g} is outside the stage's physical travel "
                f"[{low:g}, {high:g}] — refused regardless of any published envelope"
            )
        fence = (handle.envelope or {}).get(axis)
        if fence and not (fence[0] <= value <= fence[1]):
            raise RuntimeError(
                f"{axis} = {value:g} is outside the limits [{fence[0]:g}, {fence[1]:g}] "
                "this setup was opened with"
            )
    rig = read_rig(handle.root)
    rig["stage"] = asked
    write_rig(handle.root, rig)
    return where(handle)


def objective(handle: SetupHandle) -> dict:
    _require_open(handle)
    lens = _current_objective(read_rig(handle.root))
    return {"slot": lens["slot"], "name": lens["name"], "pixel_um": lens["pixel_um"]}


def objectives(handle: SetupHandle) -> list:
    """Every lens the pretend turret holds."""
    _require_open(handle)
    return [{"slot": o["slot"], "name": o["name"], "pixel_um": o["pixel_um"]}
            for o in read_rig(handle.root)["objectives"]]


def list_configurations(connection: dict | None = None) -> list:
    """Every configuration this rig has, newest first. Needs no open handle."""
    root = where_the_machine_is(connection)
    return [describe_configuration(p) for p in reversed(configurations(root))]


def start_configuration(handle: SetupHandle) -> dict:
    """Start a configuration as a full copy of what stands now, and stand on it."""
    _require_open(handle)
    path = new_configuration(handle.root)
    handle.configuration = path.name
    return describe_configuration(path)


def use_configuration(handle: SetupHandle, configuration: str) -> dict:
    """Stand on one of the rig's configurations, by id."""
    _require_open(handle)
    path = configuration_root(handle.root, str(configuration))
    handle.configuration = path.name
    return describe_configuration(path)


def current_configuration(handle: SetupHandle) -> dict | None:
    """The configuration this setup stands on, or None before one is chosen."""
    _require_open(handle)
    return None if handle.configuration is None else describe_configuration(handle.tree)


def markers(handle: SetupHandle) -> dict:
    """The corner markers the operator dropped in the mock instrument window."""
    _require_open(handle)
    points = read_rig(handle.root).get("markers") or []
    if len(points) != 4:
        raise RuntimeError(
            f"place exactly four markers at the safe corners in the mock instrument "
            f"window first; found {len(points)}"
        )
    return {"points": [dict(p) for p in points]}


def acquire(handle: SetupHandle, *, into: str, name: str, z_um: list[float] | None = None) -> dict:
    """One raw picture, or a stack, of the sample under the current lens.

    Raw means as the mock's camera records it: the sample as the driver draws
    it, laid down the way a camera turned like this rig's would lay it down.
    """
    _require_open(handle)
    import numpy as np  # noqa: PLC0415 — kept off the import path, as the driver does
    import tifffile  # noqa: PLC0415

    from . import mock_driver  # noqa: PLC0415

    rig = read_rig(handle.root)
    lens = _current_objective(rig)
    stage = rig["stage"]
    heights = [float(stage["z_um"])] if not z_um else [float(z) for z in z_um]
    folder = Path(into)
    folder.mkdir(parents=True, exist_ok=True)
    frame_px = int(rig.get("frame_px", 256))
    paths = []
    for index, height in enumerate(heights):
        # What this lens sees: the sample where the lens is looking, at the
        # height the lens is focusing, with this lens's pixel size.
        aligned = mock_driver._the_sample_from(
            np,
            stage["x_um"] + lens["offset_um"]["x"],
            stage["y_um"] + lens["offset_um"]["y"],
            height - lens["offset_um"]["z"],
            0,
            frame_px,
            float(lens["pixel_um"]),
        )
        raw = as_the_camera_records(np, aligned, rig["camera"])
        path = folder / f"{name}_Z{index:05d}.ome.tiff"
        tifffile.imwrite(
            path, raw,
            description=(
                '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
                '<Image><Pixels DimensionOrder="XYCZT" Type="uint16" '
                f'SizeX="{raw.shape[1]}" SizeY="{raw.shape[0]}" SizeC="1" SizeZ="1" SizeT="1" '
                f'PhysicalSizeX="{lens["pixel_um"]}" PhysicalSizeY="{lens["pixel_um"]}"/></Image></OME>'
            ),
        )
        paths.append(str(path))
    return {
        "images": paths,
        "z_um": heights,
        "pixel_um": float(lens["pixel_um"]),
        "frame_px": [frame_px, frame_px],
        "job": lens["name"],
        "position": dict(stage),
    }


def as_the_camera_records(np, aligned, camera: dict):
    """A stage-aligned picture, laid down the way this camera would record it.

    The inverse of the correction the orientation document describes: undo
    the clockwise turn, then undo the mirror.
    """
    k = int(camera.get("rotation_deg", 0)) // 90
    out = aligned
    if k:
        out = np.rot90(out, k=k)
    if camera.get("reflection"):
        out = np.fliplr(out)
    return np.ascontiguousarray(out)


def as_the_stage_sees(np, raw, orientation: dict):
    """Apply a published orientation: mirror first, then the clockwise turn."""
    out = raw
    if orientation.get("reflection"):
        out = np.fliplr(out)
    k = int(orientation.get("rotation_deg", 0)) // 90
    if k:
        out = np.rot90(out, k=-k)
    return np.ascontiguousarray(out)


# ---------------------------------------------------------------------------
# the four documents
# ---------------------------------------------------------------------------


def _default(subsystem: str) -> dict:
    if subsystem == "limits":
        return {
            "x_um": {"range": list(PHYSICAL_UM["x_um"])},
            "y_um": {"range": list(PHYSICAL_UM["y_um"])},
            "z_um": {"range": list(PHYSICAL_UM["z_um"])},
            "objective_slot": [],
            **{name: [] for name in SETTINGS},
        }
    if subsystem == "orientation":
        return {
            "schema_version": 3, "measured": False, "rotation_deg": 0, "reflection": False,
            "sign_convention": {"stage_x_from_image": "+X", "stage_y_from_image": "+Y"},
        }
    if subsystem == "calibration":
        return {"schema_version": 1, "objectives": {}}
    return {}


def read(handle: SetupHandle, subsystem: str, *, fresh: bool = False) -> dict:
    """The document as it stands: the newest snapshot, else the bundled
    default -- or the default regardless, for a setup that starts over."""
    _require_open(handle)
    if subsystem not in SUBSYSTEM_FILES:
        raise ValueError(f"unknown subsystem {subsystem!r}")
    found = [] if fresh else snapshots(handle.tree, subsystem)
    if found:
        document = json.loads((found[-1] / SUBSYSTEM_FILES[subsystem]).read_text(encoding="utf-8"))
        return {"document": document, "source": "published", "path": str(found[-1]),
                "evidence": _evidence(found[-1])}
    return {"document": _default(subsystem), "source": "default", "path": None, "evidence": []}


def validate(subsystem: str, document: dict) -> dict:
    """Refuse what a real driver would refuse, in a sentence an operator can act on."""
    if subsystem == "limits":
        for axis, (low, high) in PHYSICAL_UM.items():
            entry = document.get(axis)
            if not isinstance(entry, dict) or "range" not in entry:
                raise ValueError(f"limits document needs {axis} as {{'range': [low, high]}}")
            lo, hi = entry["range"]
            if not (lo < hi):
                raise ValueError(f"{axis} range must run low to high, got {entry['range']}")
            if lo < low or hi > high:
                raise RuntimeError(
                    f"{axis} range {entry['range']} reaches outside the physical travel "
                    f"[{low:g}, {high:g}]; a published envelope can only be narrower"
                )
        for name in ("objective_slot", *SETTINGS):
            if name not in document:
                raise ValueError(f"limits document needs an entry for {name} ([] means unrestricted)")
        return dict(document)
    if subsystem == "orientation":
        if int(document.get("rotation_deg", -1)) not in (0, 90, 180, 270):
            raise ValueError("rotation_deg must be 0, 90, 180 or 270")
        if not isinstance(document.get("reflection"), bool):
            raise ValueError("reflection must be true or false")
        return {"schema_version": 3, "measured": True, **document}
    if subsystem == "calibration":
        if not isinstance(document.get("objectives"), dict):
            raise ValueError("calibration document needs an 'objectives' map")
        # The schema is the driver's to say, whatever a publisher sent.
        return {**document, "schema_version": 1}
    if subsystem == "origin":
        for axis in ("x_um", "y_um", "z_um"):
            if not isinstance(document.get(axis), (int, float)):
                raise ValueError(f"origin document needs {axis} as a number")
        return dict(document)
    raise ValueError(f"unknown subsystem {subsystem!r}")


def publish(handle: SetupHandle, subsystem: str, document: dict, evidence=()) -> dict:
    _require_open(handle)
    checked = validate(subsystem, document)
    checked = {**checked, "published_at": datetime.now(timezone.utc).isoformat()}
    path = _publish(handle.tree, subsystem, checked)
    # The figures and numbers behind the document, kept beside it so a
    # reopened configuration can show what was measured.
    data = path.parent / "data"
    for source in evidence or ():
        source = Path(source)
        if source.is_dir():
            shutil.copytree(source, data / source.name, dirs_exist_ok=True)
        elif source.is_file():
            data.mkdir(exist_ok=True)
            shutil.copy2(source, data / source.name)
    return {"path": str(path), "snapshot": str(path.parent), "document": checked,
            "evidence": _evidence(path.parent)}


def _evidence(snapshot: Path) -> list[dict]:
    """Every file kept beside the document, named relative to ``data/``."""
    data = snapshot / "data"
    if not data.is_dir():
        return []
    return [{"name": p.relative_to(data).as_posix(), "path": str(p)}
            for p in sorted(data.rglob("*")) if p.is_file()]


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

CONNECTION = {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api", "client": "mock-client"}


def register_mock_setup() -> None:
    """Register this mock with the setup registry — and only with that one."""
    from zmart_drivers.setup.registry import register

    register(
        CONNECTION,
        ops={
            "open": open_setup,
            "close": close_setup,
            "describe": describe,
            "where": where,
            "move": move,
            "acquire": acquire,
            "objective": objective,
            "objectives": objectives,
            "markers": markers,
            "configurations": list_configurations,
            "new_configuration": start_configuration,
            "use_configuration": use_configuration,
            "configuration": current_configuration,
            "read": read,
            "publish": publish,
        },
    )
