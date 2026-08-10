"""A transfer from another microscope, shown as one picture without copying it.

``viz_studio/building`` serves a folder of separately-written tiles as a single
OME-Zarr that holds no pixels: every piece of it is built out of whichever tiles
cover that ground, when the browser asks. These are the tests that hold it to
that, and they are written against a synthetic transfer so they run anywhere --
the real one they were developed on is 36 GB on a particular disk.

The tiles here are placed at **fractional** voxel offsets, which is the whole
point of building rather than pointing: a transfer arranged by nobody does not
land on a grid of whole files, and :mod:`zmart_storage.linked` correctly refuses
such a run. Nothing here would work if the offsets were tidy.

Three of these tests exist because something got through that should not have:

- pieces are asked for **all at once** as well as one at a time, because the
  browser only ever asks in parallel and a shared encoder once handed requests
  each other's specimen -- more than half of them, differently every round, with
  every check of the day passing;
- the coarser copies are checked against **full resolution** rather than against
  the code that places them, because a placement worked out wrongly would be
  worked out wrongly on both sides of a comparison that used it;
- tiles that disagree are checked at the door, because a tile of the wrong number
  type is converted into the picture by numpy rather than refused, and that is a
  black square or a field of noise with nothing anywhere to report it.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
import zarr

VIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VIZ / "building"))

from composer import Composer  # noqa: E402
from declare import declare_a_built_picture  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402
import served  # noqa: E402

# One tile: shallow, small, and square, so a whole transfer of them is quick to
# write and every test can afford to compare every voxel.
TILE = (2, 64, 64)
VOXEL_UM = (1.0, 0.5, 0.5)
LEVELS = 3

# How far the stage moves between tiles, in micrometres. 27.3 um at half a
# micrometre a voxel is 54.6 voxels -- deliberately not a whole number, and
# deliberately less than a tile so neighbours overlap.
STEP_UM = 27.3

# Small enough that the picture is several pieces across, so seams fall inside
# pieces rather than conveniently between them.
PIECE = 32


def _write_a_tile(store: Path, number: int, at_um: tuple[float, float],
                  dtype: str = "uint16",
                  voxel_um: tuple[float, float, float] = VOXEL_UM,
                  axes: tuple[str, str, str] = ("z", "y", "x")) -> None:
    """One tile of a transfer, with its own brightness so mixups are visible."""
    # Kept inside whatever the tile's own type can hold: one of these tests writes
    # a uint8 tile on purpose, to check that a transfer of two number types is
    # refused, and a fixture that overflowed would fail for its own reasons.
    brightest = int(np.iinfo(np.dtype(dtype)).max)
    picture = np.full(TILE, min(500 + number * 900, brightest // 2), dtype)
    picture[:, :3, :] = brightest
    picture[:, :, :3] = brightest

    datasets = []
    for level in range(LEVELS):
        shrink = 2 ** level
        array = zarr.create_array(
            store=str(store / str(level)),
            shape=(TILE[0], TILE[1] // shrink, TILE[2] // shrink),
            chunks=(TILE[0], TILE[1] // shrink, TILE[2] // shrink),
            dtype=dtype, zarr_format=3, dimension_names=list(axes),
            overwrite=True,
        )
        array[:] = picture[:, ::shrink, ::shrink]
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale", "scale": [voxel_um[0], voxel_um[1] * shrink,
                                            voxel_um[2] * shrink]},
                {"type": "translation",
                 "translation": [0.0, at_um[0], at_um[1]]},
            ],
        })
    (store / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {
            "version": "0.5",
            "multiscales": [{
                "name": store.name, "type": "nearest",
                "axes": [{"name": one, "type": "space", "unit": "micrometer"}
                         for one in axes],
                "datasets": datasets,
            }],
        }},
        "zarr_format": 3, "node_type": "group",
    }), encoding="utf-8")


@pytest.fixture
def a_transfer(tmp_path: Path) -> Path:
    """Four tiles in two rows of two, overlapping, at fractional offsets."""
    folder = tmp_path / "transfer"
    folder.mkdir()
    for number, (row, column) in enumerate([(0, 0), (0, 1), (1, 0), (1, 1)]):
        _write_a_tile(folder / f"Tile{number}.ome.zarr", number,
                      (row * STEP_UM, column * STEP_UM))
    return folder


def _laid_out_by_hand(mosaic, level: int, plane: int, top: int, left: int,
                      piece: int) -> np.ndarray:
    """The same ground, straight from the tiles, without using the composer.

    Written the long way on purpose: a helper shared with the code under test
    would repeat its mistakes rather than catch them.
    """
    _, height, width = mosaic.shape(level)
    ground = np.zeros((piece, piece), mosaic.dtype)
    for tile in mosaic.tiles:
        at = mosaic.lands_at(tile, level)
        held = tile.copies[level]
        if not at[0] <= plane < at[0] + held.shape[0]:
            continue
        from_y, to_y = max(top, at[1]), min(min(top + piece, height),
                                            at[1] + held.shape[1])
        from_x, to_x = max(left, at[2]), min(min(left + piece, width),
                                             at[2] + held.shape[2])
        if from_y >= to_y or from_x >= to_x:
            continue
        ground[from_y - top:to_y - top, from_x - left:to_x - left] = np.asarray(
            held.array[plane - at[0], from_y - at[1]:to_y - at[1],
                       from_x - at[2]:to_x - at[2]])
    return ground


def test_the_tiles_land_where_their_own_descriptions_say(a_transfer: Path):
    """And at fractional offsets, which is the case pointing cannot serve."""
    mosaic = read_the_transfer(a_transfer)
    assert len(mosaic.tiles) == 4
    assert mosaic.levels == LEVELS

    apart = STEP_UM / VOXEL_UM[1]
    assert apart != int(apart), "the fixture must not sit on whole voxels"

    lands = {tile.name: mosaic.lands_at(tile, 0) for tile in mosaic.tiles}
    assert lands["Tile0.ome.zarr"] == (0, 0, 0)
    assert lands["Tile1.ome.zarr"] == (0, 0, round(apart))
    assert lands["Tile3.ome.zarr"] == (0, round(apart), round(apart))


def test_every_piece_is_the_ground_it_covers(a_transfer: Path):
    """At every resolution, and compared against the tiles rather than the code."""
    mosaic = read_the_transfer(a_transfer)
    composer = Composer(mosaic, piece=PIECE)

    for level in range(mosaic.levels):
        deep, down, across = composer.grid(level)
        for plane in range(deep):
            for row in range(down):
                for column in range(across):
                    built = composer._slab_for(level, plane, row, column)
                    depth = composer.slab_depth(level)
                    got = built[plane - (plane // depth) * depth]
                    want = _laid_out_by_hand(mosaic, level, plane,
                                             row * PIECE, column * PIECE, PIECE)
                    assert np.array_equal(got, want), (
                        f"L{level} plane {plane} piece {row},{column}")


def test_a_served_piece_decodes_to_what_went_into_it(a_transfer: Path):
    """The bytes on the wire, read back the way the browser's engine reads them.

    A description promising one encoding over bytes in another raises nothing
    anywhere; it draws a window of noise. So the encoding is checked through
    zarr's own machinery rather than trusted.
    """
    mosaic = read_the_transfer(a_transfer)
    composer = Composer(mosaic, piece=PIECE)
    body = composer.bytes_for(0, 0, 0, 0)

    store = zarr.storage.MemoryStore()
    array = zarr.create_array(
        store=store, shape=(1, PIECE, PIECE), chunks=(1, PIECE, PIECE),
        dtype=mosaic.dtype, zarr_format=3,
        dimension_names=list(mosaic.axes), overwrite=True,
    )
    from zarr.core.buffer import cpu

    store._store_dict["c/0/0/0"] = cpu.Buffer.from_bytes(body)
    assert np.array_equal(
        np.asarray(array[0]),
        _laid_out_by_hand(mosaic, 0, 0, 0, 0, PIECE),
    )


def test_pieces_asked_for_all_at_once_are_not_muddled(a_transfer: Path):
    """The browser never asks politely, and this is where that showed.

    One encoder was shared between threads, so a request could be handed another
    request's specimen -- 13 to 22 of 25 pieces, differently every round. Every
    other test here built one piece at a time and every one of them passed.
    """
    mosaic = read_the_transfer(a_transfer)
    deep, down, across = Composer(mosaic, piece=PIECE).grid(0)
    places = [(row, column) for row in range(down) for column in range(across)]

    alone = {one: Composer(mosaic, piece=PIECE).bytes_for(0, 0, *one)
             for one in places}

    racing = Composer(mosaic, piece=PIECE)
    together: dict = {}
    keeping = threading.Lock()

    def fetch(place):
        body = racing.bytes_for(0, 0, *place)
        with keeping:
            together[place] = body

    for _ in range(3):
        together.clear()
        threads = [threading.Thread(target=fetch, args=(one,)) for one in places]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        muddled = [one for one in places if together[one] != alone[one]]
        assert not muddled, f"pieces handed to the wrong request: {muddled}"


def test_every_copy_places_its_tiles_where_the_micrometres_say(a_transfer: Path):
    """The check that was missing, and the one a reported fault needed.

    Every other comparison here lays its own truth out with ``Mosaic.lands_at`` --
    the same function the composer places with -- so a tile put in the wrong place
    is put in the same wrong place on both sides and the comparison passes. It did
    pass, on a picture where 31.8% of one copy and 31.6% of the next were a whole
    voxel out and the fault was plain on screen.

    So this places the tiles itself, from the micrometres they record, touching
    none of the code under test.
    """
    mosaic = read_the_transfer(a_transfer)
    composer = Composer(mosaic, piece=PIECE)

    for level in range(mosaic.levels):
        voxel = mosaic.voxel_um(level)
        deep, height, width = mosaic.shape(level)
        plane = deep // 2
        want = np.zeros((height, width), mosaic.dtype)
        for tile in mosaic.tiles:
            held = tile.copies[level]
            if not 0 <= plane < held.shape[0]:
                continue
            top = int(np.floor(
                (held.corner_um[1] - mosaic.corner_um[1]) / voxel[1] + 0.5))
            left = int(np.floor(
                (held.corner_um[2] - mosaic.corner_um[2]) / voxel[2] + 0.5))
            to_y, to_x = min(height, top + held.shape[1]), min(width,
                                                               left + held.shape[2])
            want[top:to_y, left:to_x] = np.asarray(
                held.array[plane, :to_y - top, :to_x - left])

        _, down, across = composer.grid(level)
        built = np.zeros((down * PIECE, across * PIECE), mosaic.dtype)
        depth = composer.slab_depth(level)
        for row in range(down):
            for column in range(across):
                slab = composer._slab_for(level, plane, row, column)
                built[row * PIECE:(row + 1) * PIECE,
                      column * PIECE:(column + 1) * PIECE] = slab[
                          plane - (plane // depth) * depth]

        differing = int((built[:height, :width] != want).sum())
        assert differing == 0, (
            f"L{level} places {differing} voxels somewhere other than where the "
            "tiles' own micrometres put them"
        )


def test_a_coarse_copy_sits_where_full_resolution_says(a_transfer: Path):
    """Checked against full resolution, not against the placement code.

    Each copy used to round its tiles separately, from micrometres, so the copies
    could disagree with one another and the disagreement could compound down the
    pyramid. Coarse placements are worked out from full resolution instead, which
    bounds it at half a voxel of the copy being drawn.
    """
    mosaic = read_the_transfer(a_transfer)
    finest = mosaic.voxel_um(0)
    for tile in mosaic.tiles:
        at_full = mosaic.lands_at(tile, 0)
        for level in range(1, mosaic.levels):
            voxel = mosaic.voxel_um(level)
            here = mosaic.lands_at(tile, level)
            for axis in range(3):
                shrink = voxel[axis] / finest[axis]
                assert abs(here[axis] - at_full[axis] / shrink) <= 0.5 + 1e-9, (
                    f"{tile.name} L{level} axis {axis} is further than half a "
                    "voxel from where full resolution puts it"
                )


def test_ground_no_tile_covers_is_answered_with_nothing(a_transfer: Path,
                                                        tmp_path: Path):
    """A sparse run is mostly ground nobody imaged, and that is not a fault."""
    store = declare_a_built_picture(tmp_path / "views", a_transfer, name="built",
                                    piece=PIECE)
    served.forget(store)
    assert served.the_bytes_behind(store, "0/c/0/0/0") is not None
    assert served.the_bytes_behind(store, "0/c/0/9999/9999") is None
    assert served.the_bytes_behind(store, "not/a/piece") is None
    served.forget(store)


def test_a_declared_picture_holds_no_pixels(a_transfer: Path, tmp_path: Path):
    """The folder is a description and nothing else; the tiles keep the picture."""
    store = declare_a_built_picture(tmp_path / "views", a_transfer, name="built",
                                    piece=PIECE)
    written = sorted(one.name for one in store.rglob("*") if one.is_file())
    assert written == ["zarr.json"] * (LEVELS + 1)

    described = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    assert described["attributes"]["zmart"]["tiles"] == 4
    assert (Path(described["attributes"]["zmart"]["built_from"]).resolve()
            == a_transfer.resolve())
    served.forget(store)


@pytest.mark.parametrize("what,changed", [
    ("a different kind of number", {"dtype": "uint8"}),
    ("a different magnification", {"voxel_um": (1.0, 0.25, 0.25)}),
    ("axes that mean something else", {"axes": ("x", "y", "z")}),
])
def test_tiles_that_disagree_are_refused(tmp_path: Path, what: str, changed: dict):
    """Each of these is converted or misread silently rather than reported.

    A tile of another number type is cast into the picture by numpy; one at
    another magnification puts the whole run in the wrong place, since every
    position is worked out by dividing micrometres by that number; one whose axes
    mean something else holds the same bytes for a different picture.
    """
    folder = tmp_path / "mixed"
    folder.mkdir()
    _write_a_tile(folder / "Tile0.ome.zarr", 0, (0.0, 0.0))
    _write_a_tile(folder / "Tile1.ome.zarr", 1, (0.0, STEP_UM), **changed)

    with pytest.raises(ValueError):
        read_the_transfer(folder)


def test_a_transfer_of_five_axes_is_turned_away(tmp_path: Path):
    """Ours are shown by pointing instead, and the message should say so."""
    folder = tmp_path / "five"
    folder.mkdir()
    store = folder / "Tile0.ome.zarr"
    zarr.create_array(store=str(store / "0"), shape=(1, 1, 2, 8, 8),
                      chunks=(1, 1, 2, 8, 8), dtype="uint16", zarr_format=3,
                      dimension_names=["t", "c", "z", "y", "x"], overwrite=True)
    (store / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "name": "five", "axes": [{"name": one} for one in "tczyx"],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0, 1.0, 0.5, 0.5]},
                {"type": "translation", "translation": [0.0] * 5}]}],
        }]}},
        "zarr_format": 3, "node_type": "group",
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="three axes"):
        read_the_transfer(folder)


def test_an_empty_folder_says_so(tmp_path: Path):
    """The commonest mistake is opening the folder above the transfer."""
    (tmp_path / "nothing").mkdir()
    with pytest.raises(ValueError, match="no OME-Zarr images"):
        read_the_transfer(tmp_path / "nothing")
