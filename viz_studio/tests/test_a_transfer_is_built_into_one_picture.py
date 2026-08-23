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

import served  # noqa: E402
from composer import Composer  # noqa: E402
from declare import declare_a_built_picture, the_scene_folder_name  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402

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


def test_a_scene_wears_its_suffix_once(a_transfer: Path, tmp_path: Path):
    """A run already named ``something.ome.zarr`` builds a scene named once.

    Every built view is named ``<name>.zmartview.zarr`` -- the operator's
    convention of 2026-08-23, so a view can be told from raw data by its
    name alone -- and real exported runs usually wear a format suffix of
    their own already. Appended blindly, a real survey's scene once landed
    as ``Thy1_Mag25x_Ch561.ome.zarr.ome.zarr`` (workstation, 2026-08-19)
    -- a name no biologist should have to read back -- so the raw name's
    dress comes off before the view's goes on.
    """
    for asked, worn in (("survey.ome.zarr", "survey.zmartview.zarr"),
                        ("plate_4561.zarr", "plate_4561.zmartview.zarr"),
                        ("built", "built.zmartview.zarr")):
        store = declare_a_built_picture(tmp_path / "views", a_transfer,
                                        name=asked, piece=PIECE)
        assert store.name == worn, (asked, store.name)
        # And the builder agrees with the one naming rule everything else
        # looks a scene up by, so built and looked-for can never diverge.
        assert store.name == the_scene_folder_name(asked)


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


def test_a_piece_between_scattered_tiles_is_answered_with_nothing(tmp_path: Path):
    """Empty ground *inside* the picture, which a scattered run is mostly made of.

    The picture's grid spans the bounding box of every tile, so tiles scattered
    apart leave whole pieces that no tile reaches. Those are answered with
    ``None`` — served as 404, read by the engine as the declared fill value —
    exactly as never-written ground of a live run is. The first scattered
    transfer opened for real crashed here instead: the encoder assumed every
    piece leaves a chunk behind, and a chunk holding only fill value does not.
    """
    folder = tmp_path / "transfer"
    folder.mkdir()
    _write_a_tile(folder / "Tile0.ome.zarr", 0, (0.0, 0.0))
    # Three pieces away on both axes, fractionally, so the pieces between the
    # two tiles belong to the picture and hold nothing at all.
    apart_um = 3 * PIECE * VOXEL_UM[1] + 0.15
    _write_a_tile(folder / "Tile1.ome.zarr", 1, (apart_um, apart_um))

    mosaic = read_the_transfer(folder)
    composer = Composer(mosaic, piece=PIECE)
    assert composer.bytes_for(0, 0, 2, 2) is None
    assert composer.bytes_for(0, 0, 0, 0) is not None

    store = declare_a_built_picture(tmp_path / "views", folder, name="built",
                                    piece=PIECE)
    served.forget(store)
    assert served.the_bytes_behind(store, "0/c/0/2/2") is None
    assert served.the_bytes_behind(store, "0/c/0/0/0") is not None
    served.forget(store)


def _counting_builds(composer):
    """Wrap the composer's slab building so a test can see when it happens."""
    built = []
    original = composer._build_slab
    composer._build_slab = lambda *asked: (built.append(asked),
                                           original(*asked))[1]
    return built


def test_warming_builds_the_coarse_ground_before_anyone_asks(a_transfer: Path):
    """After the warm pass, every coarse piece answers without building.

    The cold start the operator feels is the first look paying to build the
    coarse levels -- the ones whose every piece meets many tiles. The warmer
    spends that cost up front, so asking afterwards finds every slab of every
    pinned level already made.
    """
    mosaic = read_the_transfer(a_transfer)
    composer = Composer(mosaic)
    composer.warm_the_coarse_levels()

    built = _counting_builds(composer)
    coarsest = mosaic.levels - 1
    deep, down, across = composer.grid(coarsest)
    for plane in range(deep):
        for row in range(down):
            for column in range(across):
                composer.bytes_for(coarsest, plane, row, column)
    assert built == [], (
        f"asking for warmed ground built {len(built)} slabs over again"
    )


def test_warmed_ground_survives_a_flood_of_fine_ground(a_transfer: Path):
    """The pinned levels are never the ones let go when memory runs short.

    The slab cache is byte-bounded and lets the least recently used go. If the
    warmed coarse slabs lived under that rule, warming a large survey would
    evict its own beginning before its end -- so the pinned levels are held
    apart from the bound, and a flood of full-resolution work cannot push the
    whole-survey look out.
    """
    mosaic = read_the_transfer(a_transfer)
    composer = Composer(mosaic, weighing_at_most=1)
    composer.warm_the_coarse_levels()

    _, down, across = composer.grid(0)
    for row in range(down):
        for column in range(across):
            composer.bytes_for(0, 0, row, column)

    built = _counting_builds(composer)
    coarsest = mosaic.levels - 1
    deep, down, across = composer.grid(coarsest)
    for row in range(down):
        for column in range(across):
            composer.bytes_for(coarsest, 0, row, column)
    assert built == [], "the flood of fine ground evicted the warmed slabs"


def test_warmed_pieces_are_byte_identical_to_fresh_ones(a_transfer: Path):
    """Warming must change when the work happens, never what it makes."""
    mosaic = read_the_transfer(a_transfer)
    warmed = Composer(mosaic)
    warmed.warm_the_coarse_levels()
    fresh = Composer(mosaic)

    coarsest = mosaic.levels - 1
    _, down, across = warmed.grid(coarsest)
    for row in range(down):
        for column in range(across):
            assert (warmed.bytes_for(coarsest, 0, row, column)
                    == fresh.bytes_for(coarsest, 0, row, column))


def test_opening_a_served_picture_starts_the_warming(a_transfer: Path,
                                                     tmp_path: Path):
    """The viewer's first request sets the warm pass going in the background.

    Polled rather than waited on a fixed pause, and through the served
    registry, because that is the composer the viewer actually talks to.
    """
    import time

    store = declare_a_built_picture(tmp_path / "views", a_transfer, name="built",
                                    piece=PIECE)
    served.forget(store)
    assert served.the_bytes_behind(store, "0/c/0/0/0") is not None
    _, composer = served._composers[store.resolve()]
    deadline = time.time() + 10
    while time.time() < deadline and not composer.coarse_levels_are_warm:
        time.sleep(0.05)
    assert composer.coarse_levels_are_warm, (
        "ten seconds after the first request, the coarse levels of a four-tile "
        "picture are still cold, so no warmer can be running"
    )
    served.forget(store)


def test_a_baked_picture_shows_its_coarse_ground_without_the_tiles(
        a_transfer: Path, tmp_path: Path):
    """Baking writes the coarse ground as real files, served with no building.

    The cold start was the first look paying to build the coarse levels from
    every tile, at every opening, in front of whoever looked. Baking pays it
    once at declare time. Proved the strong way: the whole transfer is renamed
    off the map after declaring, and every piece of every baked level must
    still answer, byte-identical to before -- files owe nothing to tiles.
    """
    store = declare_a_built_picture(tmp_path / "views", a_transfer, name="built",
                                    piece=PIECE, bake=True)
    served.forget(store)
    described = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    baked = described["attributes"]["zmart"]["baked"]
    assert baked, "a baked picture must say which levels it carries as files"

    remembered = {}
    for level in baked:
        shape = json.loads((store / str(level) / "zarr.json")
                           .read_text(encoding="utf-8"))["shape"]
        for plane in range(shape[0]):
            for row in range(-(-shape[1] // PIECE)):
                for column in range(-(-shape[2] // PIECE)):
                    asked = f"{level}/c/{plane}/{row}/{column}"
                    remembered[asked] = served.the_bytes_behind(store, asked)
    assert any(body is not None for body in remembered.values())

    a_transfer.rename(a_transfer.with_name("transfer-walked-away"))
    served.forget(store)
    try:
        for asked, before in remembered.items():
            assert served.the_bytes_behind(store, asked) == before, (
                f"{asked} changed once the tiles were gone, so it was built, "
                "not read"
            )
    finally:
        a_transfer.with_name("transfer-walked-away").rename(a_transfer)
        served.forget(store)


def test_baking_extends_the_pyramid_until_the_picture_is_one_piece(
        tmp_path: Path):
    """The picture's own levels keep halving y and x until one piece holds it.

    The tiles' pyramids stop where a tile stops making sense; the picture's
    must stop where the *survey* fits the screen, and the bigger the run the
    further out an operator stands. Every extended level is averaged from the
    picture level below it, so no tile is touched a second time. A 5-by-5 run
    rather than the little fixture, because a picture that already fits one
    piece at the tiles' coarsest level rightly earns no extension at all.
    """
    folder = tmp_path / "transfer"
    folder.mkdir()
    for number in range(25):
        row, column = divmod(number, 5)
        _write_a_tile(folder / f"Tile{number:02d}.ome.zarr", number,
                      (row * STEP_UM, column * STEP_UM))
    store = declare_a_built_picture(tmp_path / "views", folder, name="built",
                                    piece=PIECE, bake=True)
    described = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    levels = described["attributes"]["ome"]["multiscales"][0]["datasets"]
    assert len(levels) > LEVELS, "baking added no levels beyond the tiles' own"

    top = json.loads((store / str(len(levels) - 1) / "zarr.json")
                     .read_text(encoding="utf-8"))
    assert top["shape"][1] <= PIECE and top["shape"][2] <= PIECE, (
        f"the top level is {top['shape']}, still more than one piece"
    )
    for one, two in zip(levels[LEVELS - 1:], levels[LEVELS:], strict=False):
        finer = one["coordinateTransformations"][0]["scale"]
        coarser = two["coordinateTransformations"][0]["scale"]
        assert coarser[1] == finer[1] * 2 and coarser[2] == finer[2] * 2, (
            "extended levels must halve y and x by exactly two"
        )
    served.forget(store)


def test_worker_processes_build_the_same_bytes(a_transfer: Path):
    """Pieces built by worker processes are identical to ones built in place.

    The workers exist because the coarse ground is interpreter-bound -- twelve
    threads built the 12,800-position survey's coarsest level no faster than
    one -- so real parallelism needs separate processes. They must change only
    where the work happens, never the bytes: every piece of every level is
    compared against the single-process build, asked for in a parallel storm
    the way a browser asks, because that is how the shared-encoder bug once
    slipped past every polite check.
    """
    from concurrent.futures import ThreadPoolExecutor

    mosaic = read_the_transfer(a_transfer)
    alone = Composer(mosaic)
    together = Composer(mosaic, workers=2)
    try:
        for level in range(mosaic.levels):
            deep, down, across = together.grid(level)
            asked = [(level, plane, row, column)
                     for plane in range(deep)
                     for row in range(down)
                     for column in range(across)]
            with ThreadPoolExecutor(max_workers=8) as pool:
                answered = list(pool.map(lambda one: together.bytes_for(*one),
                                         asked))
            for one, answer in zip(asked, answered, strict=True):
                assert answer == alone.bytes_for(*one), (
                    f"piece {one} differs between the worker build and the "
                    "in-place build"
                )
    finally:
        together.close()


def test_workers_stay_off_unless_asked_for(a_transfer: Path):
    """The single-process path is the default, so the two can be compared.

    Optional on purpose: the switch is what lets the same picture be served
    both ways side by side, and it means every existing measurement keeps
    describing the code it measured.
    """
    mosaic = read_the_transfer(a_transfer)
    composer = Composer(mosaic)
    composer.bytes_for(0, 0, 0, 0)
    assert composer.working_alone, (
        "a composer nobody asked for workers is using them"
    )


def test_a_declared_picture_holds_no_pixels(a_transfer: Path, tmp_path: Path):
    """The folder is a description and nothing else; the tiles keep the picture."""
    store = declare_a_built_picture(tmp_path / "views", a_transfer, name="built",
                                    piece=PIECE)
    written = sorted(one.name for one in store.rglob("*") if one.is_file())
    assert written == ["tiles.json"] + ["zarr.json"] * (LEVELS + 1)

    described = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    assert described["attributes"]["zmart"]["tiles"] == 4
    assert (Path(described["attributes"]["zmart"]["built_from"]).resolve()
            == a_transfer.resolve())
    served.forget(store)


def test_a_declared_picture_opens_from_its_own_ledger(a_transfer: Path,
                                                      tmp_path: Path):
    """Opening reads what was declared, never walking the tiles again.

    Declaring a picture reads every tile once and knows the whole geometry;
    throwing that away and re-deriving it at every opening is what made a
    12,800-position survey sit dark for nine seconds before its first pixel.
    The declaration now keeps the tiles' geometry as a ledger of its own, and
    opening reads that one file however many positions there are.

    Proved by making the walk impossible: every tile's own description is
    renamed away, and the picture must still open and serve the same bytes,
    because the pixels' arrays are untouched and everything else is in the
    ledger. This is the same principle the live run obeys under the gate --
    opening reads ledgers (there, the manifest and layout), never positions.
    """
    store = declare_a_built_picture(tmp_path / "views", a_transfer, name="built",
                                    piece=PIECE)
    served.forget(store)
    before = served.the_bytes_behind(store, "0/c/0/0/0")
    assert before is not None

    for tile in sorted(a_transfer.glob("*.ome.zarr")):
        (tile / "zarr.json").rename(tile / "zarr.json.walked-away")

    served.forget(store)
    try:
        assert served.the_bytes_behind(store, "0/c/0/0/0") == before
    finally:
        for tile in sorted(a_transfer.glob("*.ome.zarr")):
            (tile / "zarr.json.walked-away").rename(tile / "zarr.json")
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


def test_a_transfer_of_five_axes_builds_carrying_its_room(tmp_path: Path):
    """Five-axis tiles build now, their (t, c) room riding on each copy.

    This used to be a refusal ("ours are shown by pointing instead"), and
    it retired with the grown picture: a tile behind a (t, c) pair is an
    ordinary spatial tile whose front-axes room the served description
    carries. Only an axis order with no agreed meaning is still refused.
    """
    folder = tmp_path / "five"
    folder.mkdir()
    store = folder / "Tile0.ome.zarr"
    zarr.create_array(store=str(store / "0"), shape=(3, 2, 2, 8, 8),
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

    mosaic = read_the_transfer(folder)
    assert mosaic.axes == ("z", "y", "x"), "the mosaic itself stays spatial"
    assert mosaic.frame_room == (3, 2), "the (t, c) room must ride along"

    # An axis order nobody agreed on still has no meaning to draw.
    weird = folder / "Tile0.ome.zarr" / "zarr.json"
    described = json.loads(weird.read_text())
    described["attributes"]["ome"]["multiscales"][0]["axes"] = [
        {"name": one} for one in "cztyx"]
    weird.write_text(json.dumps(described), encoding="utf-8")
    with pytest.raises(ValueError, match="axes"):
        read_the_transfer(folder)


def test_an_empty_folder_says_so(tmp_path: Path):
    """The commonest mistake is opening the folder above the transfer."""
    (tmp_path / "nothing").mkdir()
    with pytest.raises(ValueError, match="no OME-Zarr images"):
        read_the_transfer(tmp_path / "nothing")


def test_declaring_again_over_a_new_tile_serves_it_without_a_restart(
        tmp_path: Path):
    """A tile that lands mid-run must reach whoever is already being served.

    A growing survey re-declares its picture as tiles arrive, and the serving
    side keeps a mark of the declaration so a re-declared picture is rebuilt
    rather than remembered (review finding D5). This holds that promise to the
    case that found its edge at the microscope: the survey's extent pinned by
    its corner tiles, so a landing changes which tiles exist without moving
    the picture's shape. Seen live as a picture that grew only after a reload,
    while every plane looked frozen at whatever moment it was first visited.

    Deliberately no ``served.forget`` between the declares: production never
    forgets, so the mark alone must notice the landing.
    """
    folder = tmp_path / "transfer"
    folder.mkdir()
    # Three of the four: both far corners are down, so the picture's extent --
    # and with it the description -- is already what it will always be.
    for number, (row, column) in [(0, (0, 0)), (2, (1, 0)), (3, (1, 1))]:
        _write_a_tile(folder / f"Tile{number}.ome.zarr", number,
                      (row * STEP_UM, column * STEP_UM))
    store = declare_a_built_picture(tmp_path / "views", folder, name="built",
                                    piece=PIECE)
    try:
        # Ground only the missing tile will cover: the top-right piece, past
        # tile 0's right edge and above the second row's top.
        empty = served.the_bytes_behind(store, "0/c/0/0/3")
        assert empty is None, "ground no tile covers must be served as absent"

        _write_a_tile(folder / "Tile1.ome.zarr", 1, (0.0, STEP_UM))
        again = declare_a_built_picture(tmp_path / "views", folder,
                                        name="built", piece=PIECE)
        assert again == store

        grown = served.the_bytes_behind(store, "0/c/0/0/3")
        assert grown is not None, (
            "the tile that landed is still being served as absent ground -- "
            "the remembered composer outlived the declaration that replaced it"
        )
    finally:
        served.forget(store)



def test_a_transfer_of_four_axes_builds_with_channel_room(tmp_path: Path):
    """(c, z, y, x) tiles — the ordinary multi-channel position — build too.

    Their room is (1, channels): no time axis, colour riding in front. The
    reading has to index each store by CHANNEL alone, the one front axis it
    actually has. That is the trap this gate holds shut: the front axes are
    always drawn from (t, c), so a lazy "first however-many of (moment,
    channel)" would feed the MOMENT to a single-front-axis store and quietly
    serve channel 0's pixels for every colour.
    """
    folder = tmp_path / "four"
    folder.mkdir()
    store = folder / "Tile0.ome.zarr"
    made = zarr.create_array(
        store=str(store / "0"), shape=(2, 3, 8, 8), chunks=(1, 3, 8, 8),
        dtype="uint16", zarr_format=3,
        dimension_names=["c", "z", "y", "x"], overwrite=True)
    frames = np.empty((2, 3, 8, 8), "uint16")
    for channel in range(2):
        frames[channel] = 1000 * (channel + 1)
    made[:] = frames
    (store / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "name": "four", "axes": [{"name": one} for one in "czyx"],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0, 0.5, 0.5]},
                {"type": "translation", "translation": [0.0] * 4}]}],
        }]}},
        "zarr_format": 3, "node_type": "group",
    }), encoding="utf-8")

    mosaic = read_the_transfer(folder)
    assert mosaic.axes == ("z", "y", "x"), "the mosaic itself stays spatial"
    assert mosaic.frame_room == (1, 2), "no time room, two colours of room"

    composer = Composer(mosaic, piece=8)
    try:
        from numcodecs import Zstd

        first = composer.bytes_for(0, 0, 0, 0, moment=0, channel=0)
        second = composer.bytes_for(0, 0, 0, 0, moment=0, channel=1)
        assert first is not None and second is not None
        decode = Zstd().decode
        assert np.frombuffer(decode(first), "uint16").max() == 1000
        assert np.frombuffer(decode(second), "uint16").max() == 2000, (
            "channel 1 must serve its own pixels, not channel 0's"
        )
    finally:
        composer.close()


def _write_a_grown_tile(store: Path, number: int, at_um: tuple[float, float],
                        *, moments: int = 2, channels: int = 2) -> None:
    """A five-axis tile whose every (t, c) frame holds its own brightness.

    The values are chosen so a frame served in another frame's place is
    unmistakable in one comparison: position, moment and channel each move
    the counts by amounts no rounding can confuse.
    """
    room = (moments, channels)
    picture = np.empty(room + TILE, "uint16")
    for moment in range(moments):
        for channel in range(channels):
            picture[moment, channel] = (500 + number * 900
                                        + moment * 40 + channel * 4000)
    datasets = []
    for level in range(LEVELS):
        shrink = 2 ** level
        shaped = picture[..., ::shrink, ::shrink]
        array = zarr.create_array(
            store=str(store / str(level)), shape=shaped.shape,
            chunks=(1, 1) + shaped.shape[2:], dtype="uint16", zarr_format=3,
            dimension_names=["t", "c", "z", "y", "x"], overwrite=True,
        )
        array[:] = shaped
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0, VOXEL_UM[0],
                                            VOXEL_UM[1] * shrink,
                                            VOXEL_UM[2] * shrink]},
                {"type": "translation",
                 "translation": [0.0, 0.0, 0.0, at_um[0], at_um[1]]},
            ],
        })
    (store / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {
            "version": "0.5",
            "multiscales": [{
                "name": store.name, "type": "nearest",
                "axes": [{"name": one} for one in "tczyx"],
                "datasets": datasets,
            }],
        }},
        "zarr_format": 3, "node_type": "group",
    }), encoding="utf-8")


def test_a_grown_picture_bakes_one_file_per_frame(tmp_path: Path):
    """The hard copy of a grown picture holds every (t, c) frame.

    This used to be a refusal -- "the bake writes one file per flat piece,
    baking it would freeze one frame and serve it for every other" -- and
    this test is that refusal retiring. Every baked file must hold exactly
    the bytes composing that frame would put on the wire, the extended
    coarse levels above the tiles must carry the full (t, c) room, and the
    serving door must answer grown pieces from the files alone.
    """
    folder = tmp_path / "grown"
    folder.mkdir()
    # One row of four, so the picture is wide enough that the pyramid keeps
    # halving above the tiles' own coarsest copy.
    for number in range(4):
        _write_a_grown_tile(folder / f"Tile{number}.ome.zarr", number,
                            (0.0, number * STEP_UM))

    store = declare_a_built_picture(tmp_path / "views", folder, name="built",
                                    piece=PIECE, bake=True)

    mosaic = read_the_transfer(folder)
    composer = Composer(mosaic, piece=PIECE)
    try:
        moments, channels = composer.mosaic.frame_room
        assert (moments, channels) == (2, 2)
        pinned = sorted(composer.pinned_levels)
        assert pinned, "the fixture must pin at least its coarsest level"
        for level in pinned:
            deep, down, across = composer.grid(level)
            for moment in range(moments):
                for channel in range(channels):
                    for plane in range(deep):
                        for row in range(down):
                            for column in range(across):
                                body = composer.bytes_for(
                                    level, plane, row, column,
                                    moment=moment, channel=channel)
                                baked = store.joinpath(
                                    str(level), "c", str(moment),
                                    str(channel), str(plane), str(row),
                                    str(column))
                                if body is None:
                                    assert not baked.exists(), (
                                        f"empty ground must stay unwritten, "
                                        f"but {baked} exists"
                                    )
                                    continue
                                assert baked.is_file(), (
                                    f"frame ({moment}, {channel}) of level "
                                    f"{level} was not baked at {baked}"
                                )
                                assert baked.read_bytes() == body, (
                                    f"the baked file at {baked} does not "
                                    "hold what composing this frame gives"
                                )
    finally:
        composer.close()

    # The picture's own levels above the tiles carry the full room, and a
    # frame up there is its own frame -- not moment (0, 0) frozen for all.
    described = json.loads((store / "zarr.json").read_text())
    levels = described["attributes"]["ome"]["multiscales"][0]["datasets"]
    assert len(levels) > mosaic.levels, (
        "a picture this wide must keep halving above its tiles"
    )
    top = zarr.open_array(str(store / levels[-1]["path"]), mode="r")
    assert top.shape[:2] == (2, 2), "the extended levels must keep the room"
    ceiling = np.asarray(top)
    assert ceiling[0, 0].mean() != ceiling[0, 1].mean(), (
        "the extended level serves one frame for another"
    )

    # And the files alone answer, with the tiles walked away.
    served.forget(store)
    for tile in sorted(folder.glob("*.ome.zarr")):
        (tile / "zarr.json").rename(tile / "zarr.json.walked-away")
    try:
        coarsest = mosaic.levels - 1
        one = served.the_bytes_behind(store, f"{coarsest}/c/1/1/0/0/0")
        other = served.the_bytes_behind(store, f"{coarsest}/c/0/0/0/0/0")
        assert one is not None and other is not None
        assert one != other, "two frames must answer two different pictures"
    finally:
        for tile in sorted(folder.glob("*.ome.zarr")):
            (tile / "zarr.json.walked-away").rename(tile / "zarr.json")
        served.forget(store)


def test_a_built_picture_is_measured_where_the_operator_is_looking(
        a_transfer: Path, tmp_path: Path):
    """Auto zoomed in must read the built picture, not its baked thumbnail.

    A built picture carries only its coarse levels as files; the fine ones
    are declared and made on demand, which is how the browser gets detail
    the folder does not hold. The brightness measurement read files only, so
    at any zoom past the baked levels it fell back to the coarsest thumbnail
    -- one pixel of it, for a box around one cell -- and answered with a
    window of almost no width. Everything on screen then went black or
    saturated (seen on the HA-1a plate, 2026-08-20).

    So it asks the same door the browser asks. Measured against the tiles
    themselves: the corner of every tile in this fixture is written to the
    type's brightest value, and a box on that corner must come back holding
    it. A thumbnail cannot: three pixels of white averaged into a coarse
    piece are gone.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from contrast import measure_here  # noqa: PLC0415

    # Unbaked on purpose: then NOTHING in the folder holds pixels, which is
    # what every level past the baked ones looks like on a real plate.
    store = declare_a_built_picture(tmp_path / "views", a_transfer,
                                    name="built", piece=PIECE, bake=False)
    served.forget(store)

    # The top-left corner of the picture, which is the top-left corner of
    # Tile0: three rows and three columns of the brightest value the type
    # holds, against a flat 500 elsewhere.
    corner = ((0.0, 0.0), (0.06, 0.06))
    found = measure_here(store, channel=0, box=corner)
    assert found is not None, "the corner of the picture measured as nothing"
    low, high = found["window"]
    assert high > 60_000, (
        f"the window came back {low:.0f}-{high:.0f}, so the white edge of "
        "Tile0 was never read: this is a thumbnail's answer, not the "
        "picture's"
    )
