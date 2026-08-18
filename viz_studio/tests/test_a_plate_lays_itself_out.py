"""An HCS plate opens as one picture, laid out from its own plate description.

OME-Zarr 0.5 has two big shapes on microscopes: a folder of images placed by
stage translations -- what every transfer in this repository is -- and the
high-content-screening PLATE, one store holding rows of wells, each well
holding its numbered fields. A plate carries no stage translations at all:
where a field belongs follows from the plate's own row and column indices.

So the mosaic reader learns the second shape: a plate's wells are laid out on
the grid the plate itself declares, the fields of each well side by side in a
little sub-grid within it, with a small gap between wells so the plate reads
as a plate. Everything after that -- building, baking, serving, the load
window -- sees ordinary tiles and needs no new ideas.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import zarr
from numcodecs import Zstd

VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIZ / "building"))

import served  # noqa: E402
from declare import declare_a_built_picture  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402

FIELD = (2, 32, 32)  # planes, height, width of one field
VOXEL_UM = (1.0, 0.5, 0.5)


def _write_a_field(group: Path, value: int) -> None:
    """One field of a well: an ordinary small image, no translation."""
    picture = np.full(FIELD, value, "uint16")
    array = zarr.create_array(
        store=str(group / "0"), shape=FIELD, chunks=FIELD, dtype="uint16",
        zarr_format=3, dimension_names=["z", "y", "x"], overwrite=True)
    array[:] = picture
    (group / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "name": group.name, "type": "nearest",
            "axes": [{"name": one, "type": "space", "unit": "micrometer"}
                     for one in ("z", "y", "x")],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": list(VOXEL_UM)}]}],
        }]}},
        "zarr_format": 3, "node_type": "group"}), encoding="utf-8")


def a_small_plate(folder: Path, *, fields_per_well: int = 2) -> Path:
    """Three wells of a two-by-two plate, two fields each, values by place.

    A1 is present, A2 is present, B1 is present, B2 is deliberately absent:
    real screens skip wells, and a layout that cannot cope with a hole would
    fail on the first real plate it met.
    """
    plate = folder / "plate.ome.zarr"
    wells = [("A/1", 0, 0), ("A/2", 0, 1), ("B/1", 1, 0)]
    for number, (path, _, _) in enumerate(wells):
        well = plate / path
        well.mkdir(parents=True)
        for field in range(fields_per_well):
            group = well / str(field)
            group.mkdir()
            _write_a_field(group, 1000 * (number + 1) + 100 * field)
        (well / "zarr.json").write_text(json.dumps({
            "attributes": {"ome": {"version": "0.5", "well": {
                "images": [{"path": str(field)}
                           for field in range(fields_per_well)]}}},
            "zarr_format": 3, "node_type": "group"}), encoding="utf-8")
    (plate / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {"version": "0.5", "plate": {
            "name": "a small screen",
            "rows": [{"name": "A"}, {"name": "B"}],
            "columns": [{"name": "1"}, {"name": "2"}],
            "wells": [{"path": path, "rowIndex": row, "columnIndex": column}
                      for path, row, column in wells],
        }}},
        "zarr_format": 3, "node_type": "group"}), encoding="utf-8")
    return folder


def test_a_plate_lays_its_wells_on_the_plate_grid(tmp_path):
    """Six fields, three wells, every corner where the plate says it belongs."""
    mosaic = read_the_transfer(a_small_plate(tmp_path))
    assert len(mosaic.tiles) == 6
    corners = {tile.name: tile.copies[0].corner_um[1:] for tile in mosaic.tiles}

    field_h = FIELD[1] * VOXEL_UM[1]
    field_w = FIELD[2] * VOXEL_UM[2]
    # Two fields per well sit side by side in a two-across sub-grid.
    assert corners["A1-0"] == (0.0, 0.0)
    assert corners["A1-1"] == (0.0, field_w)
    # Wells step by the well's own extent plus a visible gap, on the plate's
    # row and column indices -- B2 is absent and nothing minds.
    (a2_y, a2_x), (b1_y, b1_x) = corners["A2-0"], corners["B1-0"]
    assert a2_y == 0.0 and b1_x == 0.0
    assert a2_x > 2 * field_w, "well A2 must clear the whole of well A1"
    assert b1_y > field_h, "well B1 must clear the whole of well A1"


def test_a_plate_builds_and_each_field_serves_its_own_pixels(tmp_path):
    """The built plate is an ordinary picture; wells answer as themselves."""
    folder = a_small_plate(tmp_path)
    store = declare_a_built_picture(tmp_path / "views", folder, name="plate",
                                    piece=32)
    try:
        mosaic = read_the_transfer(folder)
        corners = {tile.name: tile.copies[0].corner_um[1:]
                   for tile in mosaic.tiles}
        piece = 32  # one field is exactly one piece at this size
        decode = Zstd().decode
        for name, expected in (("A1-0", 1000), ("A2-1", 2100), ("B1-0", 3000)):
            row = int(corners[name][0] / VOXEL_UM[1]) // piece
            column = int(corners[name][1] / VOXEL_UM[2]) // piece
            body = served.the_bytes_behind(store, f"0/c/0/{row}/{column}")
            assert body is not None, f"{name} served nothing"
            values = np.frombuffer(decode(body), "uint16")
            assert values.max() == expected, (
                f"{name} at piece ({row}, {column}) served {values.max()}, "
                f"not its own {expected}"
            )
    finally:
        served.forget(store)


def test_two_plates_in_one_folder_are_refused_plainly(tmp_path):
    a_small_plate(tmp_path)
    second = tmp_path / "second"
    second.mkdir()
    a_small_plate(second)
    (second / "plate.ome.zarr").rename(tmp_path / "plate2.ome.zarr")
    with pytest.raises(ValueError, match="plate"):
        read_the_transfer(tmp_path)
