"""A capture from a microscope that is not the interface's own mock.

The interface promises to work with any microscope the ZMART Controller
drives. What it may rely on is what the controller's contract fixes: an
acquisition lists every file it saved under ``files``, and under ``planes``
says for each picture which file it is in, its channel, depth and moment
(``c``, ``z``, ``t``) and the stage position it was taken at (``x_um``,
``y_um``, ``z_um``). Nothing else -- not the way a driver names its files.

``Elsewhere`` below is such a microscope: a plugin of its own, written to the
contract and nothing more, that names its files its own way ("A1.ome.tif",
"A1_z000.ome.tif"). These tests take a capture from it and send it down the
interface's own paths: moved into the run, kept as an OME-Zarr position,
drawn as the scan's small picture, and cut into a focus stack's slice copies.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("zmart_controller")
np = pytest.importorskip("numpy")
tifffile = pytest.importorskip("tifffile")
pytest.importorskip("zarr")

from zmart_controller import ZmartController, check_acquire_answer  # noqa: E402

from .jpeg_tiles import (  # noqa: E402
    make_slice_copies,
    make_what_is_missing,
)
from .output import (  # noqa: E402
    move_record_images,
    prepare_acquisition,
    prepare_experiment,
)
from .zarr_positions import position_store_from_record  # noqa: E402


class Elsewhere:
    """A microscope of another make: the contract, and its own way of naming files.

    A snap is one plane, ``<label>.ome.tif``; with ``z_planes`` and
    ``z_step_um`` set as state, ``full`` takes that many planes upwards from
    where the stage stands, ``<label>_z000.ome.tif`` and on.
    """

    PIXEL_UM = 0.5

    def __init__(self, connection):
        self.root = Path(connection["output_root"])
        self.at = (0.0, 0.0, 0.0)
        self.stack = {"z_planes": 1, "z_step_um": 0.0}

    def disconnect(self):
        pass

    def get_info(self):
        return True, ("A microscope of another make, in memory. +z points up.", {}, False, {})

    def get_actuators(self):
        motor = {"options": ["motor"], "default": "motor"}
        return True, (motor, motor, motor)

    def get_xyz(self, with_actuators):
        x, y, z = self.at
        readings = {"x": {"motor": x}, "y": {"motor": y}, "z": {"motor": z}}
        return True, (x, y, z, readings, (-1e4, 1e4, -1e4, 1e4, -1e3, 1e3))

    def set_xyz(self, x, y, z, with_actuators):
        self.at = (x, y, z)
        return self.get_xyz(with_actuators)

    def get_state(self):
        return True, (dict(self.stack), {})

    def set_state(self, changeable):
        self.stack.update(changeable)
        return True, changeable

    def get_acquisition_settings(self):
        return True, {"trigger": {"options": ["snap", "full"], "default": "snap", "active": "snap"}}

    def acquire(self, position_label, acquisition_type, output_folder, acquisition_settings):
        folder = Path(output_folder) if output_folder else self.root
        folder.mkdir(parents=True, exist_ok=True)
        full = (acquisition_settings or {}).get("trigger") == "full"
        depths = self.stack["z_planes"] if full else 1
        x, y, z = self.at
        planes = []
        for k in range(depths):
            name = f"{position_label}_z{k:03d}.ome.tif" if full else f"{position_label}.ome.tif"
            path = folder / name
            tifffile.imwrite(
                path,
                np.full((32, 32), 100 * k, dtype=np.uint16),
                ome=True,
                metadata={
                    "axes": "YX",
                    "PhysicalSizeX": self.PIXEL_UM,
                    "PhysicalSizeXUnit": "µm",
                    "PhysicalSizeY": self.PIXEL_UM,
                    "PhysicalSizeYUnit": "µm",
                },
            )
            planes.append({
                "path": str(path), "t": 0, "c": 0, "z": k,
                "x_um": x, "y_um": y, "z_um": z + k * self.stack["z_step_um"],
            })
        return True, ([plane["path"] for plane in planes], planes)

    def get_procedures(self):
        return True, {}

    def run_procedure(self, procedure):
        return True, procedure


@pytest.fixture
def capture(tmp_path):
    """Take one capture on the other microscope, the way the bridge asks for one."""
    connection = {"output_root": str(tmp_path / "staging")}

    def take(label: str, **stack) -> dict:
        """One snap, or with ``stack`` (``z_planes``, ``z_step_um``) set as state, the full stack."""
        session = ZmartController(Elsewhere, connection)
        try:
            session.set_xyz(100.0, 50.0, 3.0)
            if stack:
                session.set_state({"changeable": stack})
            answer = session.acquire(
                position_label=label, acquisition_settings={"trigger": "full" if stack else "snap"}
            )
        finally:
            session.disconnect()
        assert check_acquire_answer(answer) == []
        return answer["output"]

    return take


@pytest.fixture
def run(tmp_path):
    return prepare_experiment(tmp_path / "runs", "any-microscope")


def test_a_capture_from_another_microscope_is_kept_as_a_position(capture, run):
    record = move_record_images(capture("A1"), prepare_acquisition(run, "overview"))
    store = position_store_from_record(record, run / "positions" / "overview")

    attributes = json.loads((store / "zarr.json").read_text())["attributes"]
    multiscale = attributes["ome"]["multiscales"][0]
    assert [axis["name"] for axis in multiscale["axes"]][-2:] == ["y", "x"]
    assert all(Path(plane["path"]).parent == run / "overview" for plane in record["planes"])


def test_a_stack_from_another_microscope_keeps_its_depths(capture, run):
    record = capture("B1", z_planes=3, z_step_um=2.0)
    record = move_record_images(record, prepare_acquisition(run, "overview"))
    store = position_store_from_record(record, run / "positions" / "overview")

    import zarr

    opened = zarr.open(str(store), mode="r")
    assert opened["0"].shape[-3] == 3, "three depths, one per plane the record named"


def test_its_small_picture_is_drawn_where_the_record_says(capture, tmp_path):
    record = capture("C1")
    planes, x_um, y_um = record["planes"], record["planes"][0]["x_um"], record["planes"][0]["y_um"]
    note = make_what_is_missing(tmp_path / "view", {"C1": (planes, (x_um, y_um))})

    tiles = json.loads(note.read_text())["tiles"]
    assert [tile["label"] for tile in tiles] == ["C1"]
    assert tiles[0]["x0"] + tiles[0]["w"] / 2 == pytest.approx(100.0)
    assert tiles[0]["y0"] + tiles[0]["h"] / 2 == pytest.approx(50.0)


def test_its_focus_stack_is_cut_into_slices_at_the_reported_heights(capture, tmp_path):
    record = capture("D1", z_planes=3, z_step_um=2.0)
    slices = make_slice_copies(tmp_path / "focus", record["planes"])

    assert [entry["z_um"] for entry in slices] == [pytest.approx(3.0 + 2.0 * k) for k in range(3)]
    assert all((tmp_path / "focus" / entry["name"]).is_file() for entry in slices)
