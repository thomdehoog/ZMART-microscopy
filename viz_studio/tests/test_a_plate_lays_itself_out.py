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
# The backend goes in FRONT of the building folder: both hold a server.py,
# and the one with make_server -- the one the door gates below drive -- is
# the backend's.
sys.path.insert(0, str(VIZ / "backend"))
sys.path.insert(0, str(VIZ.parent))

import served  # noqa: E402
from declare import declare_a_built_picture, the_scene_folder_name  # noqa: E402
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


def test_a_folder_that_is_itself_a_plate_lays_out_its_wells(tmp_path):
    """Pointed at the plate store itself, the layout still follows.

    A real plate lives beside other data -- other plates, a survey, loose
    images -- so the answer to "is this a plate?" can never come from the
    parent folder or from the folder's name. The plate's own description
    says what it is, and that is the whole of what is read. Found on the
    workstation 2026-08-19 with a real 336-well plate named
    ``HA-1a_Plate_4561.zarr``: opened through the window it was refused,
    because the layout went looking in the mixed folder above it for
    stores named ``*.ome.zarr``.
    """
    plate = a_small_plate(tmp_path) / "plate.ome.zarr"
    mosaic = read_the_transfer(plate)
    assert len(mosaic.tiles) == 6
    corners = {tile.name: tile.copies[0].corner_um[1:] for tile in mosaic.tiles}
    assert corners["A1-0"] == (0.0, 0.0)
    assert corners["A2-0"][1] > 2 * FIELD[2] * VOXEL_UM[2]


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


def test_no_two_plate_tiles_claim_the_same_ground(tmp_path):
    """The layout arithmetic, falsified rather than trusted.

    A wrong pitch or a swapped row and column would stack fields on one
    another, and a mean-based gate could still pass by luck. Every pair of
    footprints must be disjoint, full stop.
    """
    mosaic = read_the_transfer(a_small_plate(tmp_path, fields_per_well=3))
    boxes = []
    for tile in mosaic.tiles:
        _, y, x = tile.copies[0].corner_um
        boxes.append((tile.name, y, y + FIELD[1] * VOXEL_UM[1],
                      x, x + FIELD[2] * VOXEL_UM[2]))
    for i, (name_a, top_a, bottom_a, left_a, right_a) in enumerate(boxes):
        for name_b, top_b, bottom_b, left_b, right_b in boxes[i + 1:]:
            apart = (bottom_a <= top_b or bottom_b <= top_a
                     or right_a <= left_b or right_b <= left_a)
            assert apart, f"{name_a} and {name_b} overlap"


def a_plate_of_placed_fields(folder: Path) -> Path:
    """A plate whose fields carry their own places inside each well.

    Some screening microscopes record where each field sits within its
    well, as an ordinary translation. Here every well holds three fields
    stacked VERTICALLY, one above the other, at a small shared offset --
    deliberately nothing like the squarest grid, so a layout that invents
    a grid instead of reading the places would both draw the fields
    somewhere the microscope never put them and space the wells too
    tightly to hold them.
    """
    plate = folder / "plate.ome.zarr"
    field_h = FIELD[1] * VOXEL_UM[1]
    wells = [("A/1", 0, 0), ("A/2", 0, 1), ("B/1", 1, 0)]
    for number, (path, _, _) in enumerate(wells):
        well = plate / path
        well.mkdir(parents=True)
        for field in range(3):
            group = well / str(field)
            group.mkdir()
            _write_a_field(group, 1000 * (number + 1) + 100 * field)
            described = json.loads((group / "zarr.json").read_text())
            described["attributes"]["ome"]["multiscales"][0]["datasets"][0][
                "coordinateTransformations"].append({
                    "type": "translation",
                    "translation": [0.0, 5.0 + field * field_h, 3.0]})
            (group / "zarr.json").write_text(json.dumps(described),
                                             encoding="utf-8")
        (well / "zarr.json").write_text(json.dumps({
            "attributes": {"ome": {"version": "0.5", "well": {
                "images": [{"path": str(field)} for field in range(3)]}}},
            "zarr_format": 3, "node_type": "group"}), encoding="utf-8")
    (plate / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {"version": "0.5", "plate": {
            "name": "a placed screen",
            "rows": [{"name": "A"}, {"name": "B"}],
            "columns": [{"name": "1"}, {"name": "2"}],
            "wells": [{"path": path, "rowIndex": row, "columnIndex": column}
                      for path, row, column in wells],
        }}},
        "zarr_format": 3, "node_type": "group"}), encoding="utf-8")
    return folder


def test_fields_keep_the_places_their_writer_recorded(tmp_path):
    """Fields with their own translations are drawn there, not on a grid.

    The squarest sub-grid is only the fallback for wells whose writer said
    nothing. When the places ARE recorded, inventing a grid would draw the
    fields somewhere the microscope never put them. The shared offset is
    normalised away -- the well's content starts at its own cell either
    way -- and the wells are spaced by their actual extent (three fields
    tall here), not by the fallback grid's assumption.
    """
    mosaic = read_the_transfer(a_plate_of_placed_fields(tmp_path))
    assert len(mosaic.tiles) == 9
    corners = {tile.name: tile.copies[0].corner_um[1:] for tile in mosaic.tiles}
    field_h = FIELD[1] * VOXEL_UM[1]
    field_w = FIELD[2] * VOXEL_UM[2]
    assert corners["A1-0"] == (0.0, 0.0)
    assert corners["A1-1"] == (field_h, 0.0), (
        "the writer stacked the fields vertically; the layout must not "
        "move them onto a side-by-side grid"
    )
    assert corners["A1-2"] == (2 * field_h, 0.0)
    (a2_y, a2_x), (b1_y, b1_x) = corners["A2-0"], corners["B1-0"]
    assert a2_y == 0.0 and b1_x == 0.0
    assert field_w < a2_x < 2 * field_w, (
        "the wells are one field wide, so their columns must step by about "
        "one field plus the gap -- not by the fallback grid's square"
    )
    assert b1_y > 3 * field_h, (
        "well B1 must clear the whole of well A1, which is three fields tall"
    )
    # And no two fields may overlap, exactly as on a grid-laid plate.
    boxes = []
    for tile in mosaic.tiles:
        _, y, x = tile.copies[0].corner_um
        boxes.append((tile.name, y, y + field_h, x, x + field_w))
    for i, (name_a, top_a, bottom_a, left_a, right_a) in enumerate(boxes):
        for name_b, top_b, bottom_b, left_b, right_b in boxes[i + 1:]:
            apart = (bottom_a <= top_b or bottom_b <= top_a
                     or right_a <= left_b or right_b <= left_a)
            assert apart, f"{name_a} and {name_b} overlap"


def test_global_and_local_field_places_lay_out_the_same(tmp_path):
    """Nobody can tell us whether a field's translation counts from the
    well or from the stage, so the layout must not need to know.

    Two copies of the same plate: one writes each field's place counting
    from inside its well, the other counts from the stage corner (every
    well's fields carry the well's own big offset too). Only the RELATIVE
    arrangement within a well is trusted -- the shared part is stripped
    and the well is anchored by its plate indices -- so both must come
    out at exactly the same corners.
    """
    local = read_the_transfer(a_plate_of_placed_fields(tmp_path / "local"))

    folder = a_plate_of_placed_fields(tmp_path / "global")
    plate = folder / "plate.ome.zarr"
    for well in ("A/1", "A/2", "B/1"):
        row, column = ord(well[0]) - ord("A"), int(well[-1]) - 1
        for field in range(3):
            described = json.loads(
                (plate / well / str(field) / "zarr.json").read_text())
            placing = described["attributes"]["ome"]["multiscales"][0][
                "datasets"][0]["coordinateTransformations"][1]
            placing["translation"][1] += row * 3000.0
            placing["translation"][2] += column * 2000.0
            (plate / well / str(field) / "zarr.json").write_text(
                json.dumps(described), encoding="utf-8")
    stage = read_the_transfer(folder)

    told = {tile.name: tile.copies[0].corner_um for tile in local.tiles}
    placed = {tile.name: tile.copies[0].corner_um for tile in stage.tiles}
    assert placed.keys() == told.keys()
    for name, corner in told.items():
        # To within floating-point dust: subtracting a stage-sized offset
        # costs the last few bits, and a nanometre is far below anything
        # a pixel could show.
        assert placed[name] == pytest.approx(corner, abs=1e-6), name


def test_a_placed_field_serves_its_own_pixels(tmp_path):
    """The built plate answers a placed field with that field's own values."""
    folder = a_plate_of_placed_fields(tmp_path)
    store = declare_a_built_picture(tmp_path / "views", folder, name="plate",
                                    piece=32)
    try:
        mosaic = read_the_transfer(folder)
        corners = {tile.name: tile.copies[0].corner_um[1:]
                   for tile in mosaic.tiles}
        decode = Zstd().decode
        for name, expected in (("A1-2", 1200), ("B1-1", 3100)):
            row = int(corners[name][0] / VOXEL_UM[1]) // 32
            column = int(corners[name][1] / VOXEL_UM[2]) // 32
            body = served.the_bytes_behind(store, f"0/c/0/{row}/{column}")
            held = np.frombuffer(decode(body), "<u2")
            assert held.max() == expected, (
                f"{name} should answer {expected}, not {held.max()}"
            )
    finally:
        served.forget(store)


def test_wells_without_indices_take_their_place_from_their_names(tmp_path):
    """Some writers name the well's path and omit rowIndex and columnIndex.

    The plate's own rows and columns lists still say where "B/1" belongs,
    so the layout is derived from them rather than refused.
    """
    folder = a_small_plate(tmp_path)
    plate = folder / "plate.ome.zarr"
    described = json.loads((plate / "zarr.json").read_text())
    for well in described["attributes"]["ome"]["plate"]["wells"]:
        del well["rowIndex"]
        del well["columnIndex"]
    (plate / "zarr.json").write_text(json.dumps(described), encoding="utf-8")

    mosaic = read_the_transfer(folder)
    corners = {tile.name: tile.copies[0].corner_um[1:] for tile in mosaic.tiles}
    assert corners["A1-0"] == (0.0, 0.0)
    assert corners["B1-0"][0] > 0.0 and corners["B1-0"][1] == 0.0
    assert corners["A2-0"][1] > 0.0 and corners["A2-0"][0] == 0.0


def test_a_04_plate_reads_the_same_as_a_05_one(tmp_path):
    """The older metadata generation, which real converters still write.

    bioformats2raw has produced 0.4 plates for years: flat ``.zattrs``
    beside zarr v2 arrays. The same wells must land in the same places.
    """
    plate = tmp_path / "plate.ome.zarr"
    wells = [("A/1", 0, 0), ("B/2", 1, 1)]
    for number, (path, _, _) in enumerate(wells):
        well = plate / path
        well.mkdir(parents=True)
        field = well / "0"
        field.mkdir()
        group = zarr.open_group(str(field), mode="w", zarr_format=2)
        data = np.full(FIELD, 1000 * (number + 1), "uint16")
        group.create_array("0", shape=FIELD, chunks=FIELD,
                           dtype="uint16")[:] = data
        (field / ".zattrs").write_text(json.dumps({"multiscales": [{
            "version": "0.4",
            "axes": [{"name": one, "type": "space", "unit": "micrometer"}
                     for one in ("z", "y", "x")],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": list(VOXEL_UM)}]}],
        }]}), encoding="utf-8")
        (well / ".zattrs").write_text(json.dumps({
            "well": {"images": [{"path": "0"}]}}), encoding="utf-8")
    (plate / ".zattrs").write_text(json.dumps({"plate": {
        "rows": [{"name": "A"}, {"name": "B"}],
        "columns": [{"name": "1"}, {"name": "2"}],
        "wells": [{"path": path, "rowIndex": row, "columnIndex": column}
                  for path, row, column in wells],
    }}), encoding="utf-8")

    mosaic = read_the_transfer(tmp_path)
    corners = {tile.name: tile.copies[0].corner_um[1:] for tile in mosaic.tiles}
    assert corners["A1-0"] == (0.0, 0.0)
    assert corners["B2-0"][0] > 0.0 and corners["B2-0"][1] > 0.0


# ---------------------------------------------------------------------------
# The plain door: a plate opened directly still lays itself out
# ---------------------------------------------------------------------------


@pytest.fixture
def door(built_dist, tmp_path):
    """A served viewer beside a folder holding one plate, for the door gates."""
    import threading

    from server import make_server
    from test_open_and_close import _store

    first = tmp_path / "overview"
    first.mkdir()
    _store(first / "overview_pos001.ome.zarr", channels=1)
    screen = tmp_path / "screenday"
    a_small_plate(screen)
    server = make_server(port=0, data_dir=first, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", screen
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_a_plate_store_opened_directly_lays_itself_out(door):
    """The plain open door routes a plate through the plate layout.

    Pointed straight at the plate STORE -- the view or other tab, not the
    scene builder -- the door used to hand it to the library as an
    ordinary image, which drew every well at the origin, stacked. Now the
    door notices the plate, builds (or reuses) the scene beside it exactly
    as the build tab would, and serves THAT: what reaches the screen is
    the laid-out plate, whichever tab opened it.
    """
    from test_a_dataset_is_relived_as_a_live_run import _post

    address, screen = door
    status, answer = _post(address, "/api/stores/open",
                           {"path": str(screen / "plate.ome.zarr")})
    assert status == 200, answer
    # The scene's folder name follows the one naming rule every built view
    # follows, so the test can never disagree with the builder about it.
    scene = screen / "scenes" / the_scene_folder_name("plate")
    described = json.loads((scene / "zarr.json").read_text(encoding="utf-8"))
    assert described["attributes"]["zmart"]["built_from"] == (
        (screen / "plate.ome.zarr").as_posix()), (
        "the scene must say which plate it was built from")
    # The heading keeps the view's full name: the suffix is what tells a
    # view from the raw data beside it (the operator asked, 2026-08-23).
    composed = [one for one in answer.get("layers", [])
                if one.get("kind") == "image"
                and one.get("group") == scene.name]
    assert len(composed) == 1, (
        "the laid-out scene is ONE composed picture; several rows means the "
        "raw plate's fields were served directly -- the "
        "wells-stacked-at-the-origin picture"
    )


def test_a_real_plate_lives_beside_other_data(door, tmp_path):
    """A plate is opened for what it is, wherever it stands.

    The real folder a plate arrives in also holds the rest of the day's
    work -- another plate, a survey, loose images -- and real plates are
    named ``something.zarr``, not ``something.ome.zarr``. Neither fact may
    cost the operator the plate: the door reads the plate's own
    description and builds the scene beside it, from it alone.
    """
    from test_a_dataset_is_relived_as_a_live_run import _post
    from test_open_and_close import _store

    address, _ = door
    bench = tmp_path / "benchday"
    a_small_plate(bench)
    (bench / "plate.ome.zarr").rename(bench / "HA_plate.zarr")
    _store(bench / "loose_pos001.ome.zarr", channels=1)
    status, answer = _post(address, "/api/stores/open",
                           {"path": str(bench / "HA_plate.zarr")})
    assert status == 200, answer
    scene = bench / "scenes" / the_scene_folder_name("HA_plate")
    described = json.loads((scene / "zarr.json").read_text(encoding="utf-8"))
    assert described["attributes"]["zmart"]["built_from"] == (
        (bench / "HA_plate.zarr").as_posix()), (
        "the scene must say it was built from the plate itself"
    )
    composed = [one for one in answer.get("layers", [])
                if one.get("kind") == "image"
                and one.get("group") == scene.name]
    assert len(composed) == 1, (
        "the served rows must draw the one composed scene, never the raw "
        "plate's fields"
    )


def test_an_unbaked_scene_opens_at_a_measured_window(door):
    """A scene with no baked ground still opens seeable.

    The open door declares a plate's scene without the hard copy, so its
    level folders hold no pixels to measure -- and the answer used to be
    the camera's full range: a real 336-well plate opened as a near-black
    grid with an empty histogram and a dead Auto (workstation,
    2026-08-19). A built picture's pixels are one ask away -- its own
    composer makes any piece in milliseconds -- so the measurement follows
    the composer, exactly as a live picture's follows its members.
    """
    from test_a_dataset_is_relived_as_a_live_run import _post

    address, screen = door
    status, answer = _post(address, "/api/stores/open",
                           {"path": str(screen / "plate.ome.zarr")})
    assert status == 200, answer
    layer = next(one for one in answer["layers"]
                 if one.get("kind") == "image"
                 and one.get("group") == the_scene_folder_name("plate"))
    window = layer["window"]
    assert (window["low"], window["high"]) != (0.0, 65535.0), (
        "the unbaked scene opened at the camera's full range -- nothing "
        "was measured, and the operator sees a black plate"
    )
    counts = (layer.get("histogram") or {}).get("counts") or []
    assert sum(counts) > 0, "the histogram must be measured, not empty"


def test_a_scene_already_built_for_the_plate_is_reused(door):
    """A plate whose scene exists -- baked ground and all -- keeps it.

    Re-declaring on every open would remove the baked coarse ground the
    operator paid for on the build tab (declaring without the bake
    deliberately removes yesterday's files). A scene that says it was
    built from this plate's folder is opened as it stands.
    """
    from test_a_dataset_is_relived_as_a_live_run import _post

    address, screen = door
    scene = declare_a_built_picture(screen / "scenes",
                                    screen / "plate.ome.zarr",
                                    name="plate", piece=32, bake=True)
    baked = sorted(str(one.relative_to(scene))
                   for one in scene.rglob("*") if one.is_file())
    status, answer = _post(address, "/api/stores/open",
                           {"path": str(screen / "plate.ome.zarr")})
    assert status == 200, answer
    assert sorted(str(one.relative_to(scene))
                  for one in scene.rglob("*") if one.is_file()) == baked, (
        "opening the plate must not rebuild or strip the scene that "
        "already stands -- the baked ground was paid for once"
    )
