"""Does a picture that was never written down show the same thing as one that was?

:mod:`zmart_storage.linked` presents a folder of tiles to the viewer as one image
without copying any of the full-size picture into it. A piece of that image *is* a
piece of one tile, byte for byte, and the viewer's server hands the tile's own file
over unchanged.

That is a strong claim and it fails quietly if it is wrong. A pointer to the wrong
file, a description that says the wrong kind of number, a piece cut half a piece
out of step — none of those produce an error. They produce a picture, and the
picture is wrong, and nothing anywhere says so.

So the check here is the strictest one available: **the same run is written both
ways over the same tiles, and every voxel of the pointed-at view is compared with
every voxel of the written canvas.** Not sampled. If they differ anywhere, at any
zoom, in any moment or colour, these tests fail.

The pointed-at view is read *through the viewer's own server*, over HTTP, exactly
as the browser reads it. That is deliberate and it is what makes this worth
running: it exercises the description the view invents for itself, the pointers,
the answer given for ground no tile covers, and — because the bytes are decoded
using the description rather than the tile's — that the two agree about compression
and about the kind of number a voxel is.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest
import zarr
from server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.cropped import TilesAndCanvas  # noqa: E402
from zmart_storage.linked import PlacedTile, link_the_tiles  # noqa: E402

# A small run whose tiles butt up against one another — the stage stepping by a
# whole tile, so nothing is trimmed and nothing overlaps. This is the arrangement
# pointing is built for, and it is small enough to write, point at and compare
# voxel by voxel in a second or two.
TILE = (2, 64, 64)
GRID = 3
CHUNK = 64
VOXEL_UM = (2.0, 0.35, 0.35)

# Where the run sits on the stage. Deliberately not the origin: a view has to work
# out its own corner from the tiles, and a run at nought would let a view that had
# lost the corner entirely still look right.
ORIGIN_UM = (11.0, 5.5, 7.25)

WINDOW = (0, 4000)
CHANNELS = ("488", "561")
FRAMES = 2


def _a_tile(seed: int) -> np.ndarray:
    """One tile of something that looks like a specimen rather than a flat block.

    Noisy on purpose. A picture of one value compresses to almost nothing and would
    make a comparison of two stores pass for reasons that have nothing to do with
    whether the pointers are right.
    """
    rng = np.random.default_rng(seed)
    depth, height, width = TILE
    z, y, x = np.indices(TILE, dtype=np.float32)
    picture = 400 + 200 * (y / height) + rng.normal(0, 50, size=TILE)
    for _ in range(4):
        at_y, at_x = rng.uniform(8, height - 8), rng.uniform(8, width - 8)
        spread = rng.uniform(5, 12)
        along = ((y - at_y) ** 2 + (x - at_x) ** 2) / (2 * spread ** 2)
        picture = np.maximum(picture, rng.uniform(1500, 3500) * np.exp(-along))
    return np.clip(picture, 0, 4000).astype("uint16")


def _a_run_written_both_ways(folder: Path, *, leave_out: set | None = None):
    """Write a raster as a canvas, and point at the same tiles as a second image.

    Both come out of one set of tiles, which is the whole point: any difference
    between the two pictures afterwards is the arrangement rather than the data.

    ``leave_out`` drops some places from the raster, so that the view has ground no
    tile covers — the ordinary state of a scattered run, and the case the server has
    to answer "there is nothing here" for rather than with a piece of black.
    """
    skipped = leave_out or set()
    run = TilesAndCanvas.create(
        folder,
        name="written",
        canvas_shape=(TILE[0], GRID * TILE[1], GRID * TILE[2]),
        tile_shape=TILE,
        tile_step=TILE,
        tile_grid=(1, GRID, GRID),
        voxel_size_um=VOXEL_UM,
        origin_um=ORIGIN_UM,
        channels=[Channel(name, window=WINDOW) for name in CHANNELS],
        frames=FRAMES,
        chunk=CHUNK,
    )
    placed: list[PlacedTile] = []
    for frame in range(FRAMES):
        for channel in range(len(CHANNELS)):
            for row in range(GRID):
                for column in range(GRID):
                    if (row, column) in skipped:
                        continue
                    where = run.write(
                        _a_tile(row * GRID + column + channel * 5 + frame * 7),
                        origin=(0, row * TILE[1], column * TILE[2]),
                        channel=channel,
                        frame=frame,
                        tile_index=(0, row, column),
                    )
                    if frame == 0 and channel == 0:
                        placed.append(PlacedTile(
                            store=where, lands_at=(0, row * TILE[1], column * TILE[2])
                        ))
    run.close()
    view = link_the_tiles(
        folder,
        name="pointed",
        tiles=placed,
        view_shape=(TILE[0], GRID * TILE[1], GRID * TILE[2]),
    )
    return run, view


# -- reading a store the way the browser does ----------------------------------


def _levels_of(store: Path) -> list[str]:
    described = json.loads((store / ".zattrs").read_text(encoding="utf-8"))
    return [str(one["path"]) for one in described["multiscales"][0]["datasets"]]


def _fetched_through_the_server(folder: Path, image: str, into: Path) -> Path:
    """Ask the viewer's server for every piece of an image, and rebuild it on disk.

    This is how the browser reads a store — one small request per piece — so doing
    it here means the answer being checked is the one the viewer would actually get,
    pointers and all. What comes back is written out as an ordinary store so that
    zarr can decode it, which is itself part of the check: the bytes are decoded
    using the *view's* description, so if the view and the tiles disagreed about
    compression or about the kind of number a voxel is, this is where it would show.

    A piece the server says there is nothing for is simply not written, which is
    exactly what zarr expects of unwritten ground.
    """
    server = make_server(
        port=0, data_dir=folder, site_dir=folder, store=image, live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_address[1]}/data/0/{image}"
    rebuilt = into / image
    rebuilt.mkdir(parents=True, exist_ok=True)
    try:
        for describing in (".zgroup", ".zattrs"):
            _fetch(f"{address}/{describing}", rebuilt / describing)
        for level in _levels_of(folder / image):
            (rebuilt / level).mkdir(exist_ok=True)
            _fetch(f"{address}/{level}/.zarray", rebuilt / level / ".zarray")
            described = json.loads((rebuilt / level / ".zarray").read_text("utf-8"))
            for named in _every_piece_of(described):
                _fetch(f"{address}/{level}/{named}", rebuilt / level / named)
    finally:
        server.shutdown()
        thread.join(timeout=5)
    return rebuilt


def _every_piece_of(described: dict):
    """The name of every piece an image of this shape could have, in order."""
    shape = [int(n) for n in described["shape"]]
    chunks = [int(n) for n in described["chunks"]]
    separator = described.get("dimension_separator", ".")
    counts = [-(-shape[axis] // chunks[axis]) for axis in range(len(shape))]
    for frame in range(counts[0]):
        for channel in range(counts[1]):
            for z in range(counts[2]):
                for y in range(counts[3]):
                    for x in range(counts[4]):
                        yield separator.join(
                            str(n) for n in (frame, channel, z, y, x)
                        )


def _fetch(address: str, into: Path) -> bool:
    """Ask for one piece. Returns whether there was anything there."""
    try:
        with urllib.request.urlopen(address, timeout=30) as answer:
            body = answer.read()
    except urllib.error.HTTPError as why:
        if why.code == 404:
            return False
        raise
    into.parent.mkdir(parents=True, exist_ok=True)
    into.write_bytes(body)
    return True


def _all_of(store: Path, level: str) -> np.ndarray:
    return np.asarray(zarr.open_group(str(store), mode="r")[level][:])


# -- the tests -----------------------------------------------------------------


def test_the_pointed_at_view_is_the_same_picture_voxel_for_voxel(tmp_path):
    """Every voxel, at every zoom, in every moment and colour.

    This is the test the whole arrangement stands on. A view that draws quickly and
    draws the wrong thing is worse than no view at all, because there is nothing on
    screen to say which it is doing.
    """
    run = tmp_path / "run"
    _a_run_written_both_ways(run)
    rebuilt = _fetched_through_the_server(run, "pointed.ome.zarr", tmp_path / "asked")

    canvas = run / "written.ome.zarr"
    assert _levels_of(rebuilt) == _levels_of(canvas), (
        "the pointed-at view keeps a different number of copies of the picture from "
        "the canvas, so the two cannot be compared level for level"
    )
    for level in _levels_of(canvas):
        written = _all_of(canvas, level)
        pointed = _all_of(rebuilt, level)
        assert pointed.shape == written.shape, (
            f"copy {level} of the pointed-at view is {pointed.shape} and the "
            f"canvas is {written.shape}"
        )
        differing = int((pointed != written).sum())
        assert differing == 0, (
            f"copy {level} of the pointed-at view differs from the written canvas "
            f"in {differing} of {written.size} voxels. The two were built from the "
            "same tiles, so this is the pointing rather than the data."
        )


def test_nothing_of_the_full_size_picture_is_written_down(tmp_path):
    """The full-size copy holds its description and not one piece of picture.

    This is what "nothing is copied" means in practice, and it is worth asserting
    rather than assuming: a view that quietly wrote the picture out as well would
    pass every other test here while costing exactly what it was built to save.
    """
    run = tmp_path / "run"
    _, view = _a_run_written_both_ways(run)
    describing = {".zarray", ".zattrs", ".zgroup", "zarr.json"}
    picture = sorted(
        child.name for child in (view.path / "0").iterdir()
        if child.name not in describing
    )
    assert picture == [], (
        f"the full-size copy of the pointed-at view holds {picture} besides the small "
        "files describing it, and it should hold no picture at all — those voxels are "
        "supposed to stay in the tiles"
    )
    # And the same is *not* true of the zoomed-out copies, which genuinely are
    # written. Without this the assertion above would also pass on a view that had
    # been built over nothing at all.
    copies = sorted(
        child.name for child in (view.path / "1").iterdir()
        if child.name not in describing
    )
    assert copies, (
        "the half-size copy holds no picture at all, so this view would draw as "
        "nothing when zoomed out"
    )


def test_ground_no_tile_covers_answers_the_same_way_as_an_unwritten_canvas(tmp_path):
    """A hole in the raster is answered "there is nothing here", not with black.

    Most of a scattered run's picture is ground nobody imaged, and the server
    already answers that plainly for a canvas — the comment in ``server.py`` explains
    why it matters, and it is about the connection being kept open rather than about
    the picture. The pointing path has to do the same rather than inventing a piece
    of black, both so the cost stays the same and so that the two arrangements can be
    compared at all.
    """
    run = tmp_path / "run"
    missing = {(1, 1)}
    _, view = _a_run_written_both_ways(run, leave_out=missing)

    server = make_server(
        port=0, data_dir=run, site_dir=run, store="pointed.ome.zarr", live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_address[1]}/data/0/pointed.ome.zarr"
    try:
        # The middle of the raster, which no tile covers.
        assert not _fetch(f"{address}/0/0/0/0/1/1", tmp_path / "nothing"), (
            "the server answered with a piece of picture for ground no tile covers"
        )
        # And a corner that one does, so the check above is not passing because
        # nothing at all is being served.
        assert _fetch(f"{address}/0/0/0/0/0/0", tmp_path / "something"), (
            "the server answered nothing for a piece a tile plainly covers"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    # And the picture still matches the canvas, hole and all.
    rebuilt = _fetched_through_the_server(run, "pointed.ome.zarr", tmp_path / "asked")
    for level in _levels_of(view.path):
        differing = int((_all_of(rebuilt, level) != _all_of(run / "written.ome.zarr", level)).sum())
        assert differing == 0, (
            f"with a hole in the raster, copy {level} differs in {differing} voxels"
        )


def test_it_says_where_it_sits_beside_every_copy_of_the_picture(tmp_path):
    """The view's place on the stage is written beside each resolution.

    OME-Zarr allows the position in two places, and a large part of the Python
    imaging world reads only the per-copy one — ``viz_studio/INTEROP.md`` §1 measures
    what that costs, which is every image drawn on top of every other at the origin.
    So the view says it there, and only there: saying it in both places would move
    the picture twice for any reader that composes them, and the viewer's own engine
    does compose them.
    """
    run = tmp_path / "run"
    _, view = _a_run_written_both_ways(run)
    described = json.loads((view.path / ".zattrs").read_text(encoding="utf-8"))
    multiscale = described["multiscales"][0]

    assert "coordinateTransformations" not in multiscale, (
        "the view states its position for the image as a whole as well as beside "
        "each copy, so a reader that composes the two would place it twice as far "
        "from the origin as it really is"
    )
    for dataset in multiscale["datasets"]:
        moved = [
            one for one in dataset["coordinateTransformations"]
            if one["type"] == "translation"
        ]
        assert len(moved) == 1, (
            f"copy {dataset['path']} of the view does not say where it sits, so it "
            "would be drawn at the stage's zero"
        )
        assert tuple(moved[0]["translation"][2:]) == ORIGIN_UM, (
            f"copy {dataset['path']} says it sits at {moved[0]['translation'][2:]} "
            f"and the run was acquired at {ORIGIN_UM}"
        )


def test_it_refuses_a_tile_that_would_not_land_on_whole_pieces(tmp_path):
    """A placement half a piece out is refused, with the reason and the way out.

    This is the rule the whole arrangement rests on. Half a piece out, answering a
    request would mean cutting pixels out of one file and pasting them into another,
    which is the copying that pointing exists to avoid — so it is refused at the
    door rather than done slowly and silently.
    """
    run = tmp_path / "run"
    written = TilesAndCanvas.create(
        run, name="written",
        canvas_shape=(TILE[0], 2 * TILE[1], 2 * TILE[2]),
        tile_shape=TILE, tile_step=TILE, tile_grid=(1, 2, 2),
        voxel_size_um=VOXEL_UM, origin_um=ORIGIN_UM,
        channels=[Channel("488", window=WINDOW)], chunk=CHUNK,
    )
    where = written.write(_a_tile(0), origin=(0, 0, 0), tile_index=(0, 0, 0))
    written.close()

    with pytest.raises(ValueError) as refused:
        link_the_tiles(
            run, name="pointed",
            tiles=[PlacedTile(store=where, lands_at=(0, 0, CHUNK // 2))],
        )
    said = str(refused.value)
    assert "whole number of them" in said
    assert "pieces" in said


def test_it_refuses_tiles_that_were_not_stored_the_same_way(tmp_path):
    """Tiles compressed or numbered differently cannot be one picture.

    A view hands a tile's bytes over untouched under one description it wrote
    itself, so a difference here does not produce an error — it produces a picture
    of noise. It is therefore compared exactly and refused rather than hoped about.
    """
    run = tmp_path / "run"
    written = TilesAndCanvas.create(
        run, name="written",
        canvas_shape=(TILE[0], 2 * TILE[1], 2 * TILE[2]),
        tile_shape=TILE, tile_step=TILE, tile_grid=(1, 2, 2),
        voxel_size_um=VOXEL_UM, origin_um=ORIGIN_UM,
        channels=[Channel("488", window=WINDOW)], chunk=CHUNK,
    )
    first = written.write(_a_tile(0), origin=(0, 0, 0), tile_index=(0, 0, 0))
    second = written.write(_a_tile(1), origin=(0, 0, TILE[2]), tile_index=(0, 0, 1))
    written.close()

    # The second tile, restated as holding a different kind of number. Nothing about
    # its bytes changes, which is exactly the situation this guard is for.
    described = json.loads((second / "0" / ".zarray").read_text(encoding="utf-8"))
    described["dtype"] = "<u1"
    (second / "0" / ".zarray").write_text(json.dumps(described), encoding="utf-8")

    with pytest.raises(ValueError) as refused:
        link_the_tiles(run, name="pointed", tiles=[
            PlacedTile(store=first, lands_at=(0, 0, 0)),
            PlacedTile(store=second, lands_at=(0, 0, TILE[2])),
        ])
    assert "dtype" in str(refused.value)


def test_it_refuses_a_tile_placed_somewhere_it_was_not_acquired(tmp_path):
    """Every tile has to agree about where the view's corner is.

    Each tile records the place on the stage it came from, and each is told where it
    lands in the view, so each on its own says where the view must begin. Two of them
    disagreeing means a tile has been placed somewhere other than where it was
    imaged, and the picture would be drawn with that tile in the wrong place — which
    looks perfectly ordinary on screen.
    """
    run = tmp_path / "run"
    written = TilesAndCanvas.create(
        run, name="written",
        canvas_shape=(TILE[0], 2 * TILE[1], 2 * TILE[2]),
        tile_shape=TILE, tile_step=TILE, tile_grid=(1, 2, 2),
        voxel_size_um=VOXEL_UM, origin_um=ORIGIN_UM,
        channels=[Channel("488", window=WINDOW)], chunk=CHUNK,
    )
    first = written.write(_a_tile(0), origin=(0, 0, 0), tile_index=(0, 0, 0))
    second = written.write(_a_tile(1), origin=(0, 0, TILE[2]), tile_index=(0, 0, 1))
    written.close()

    with pytest.raises(ValueError) as refused:
        link_the_tiles(run, name="pointed", tiles=[
            PlacedTile(store=first, lands_at=(0, 0, 0)),
            # Put where its neighbour belongs rather than where it was acquired.
            PlacedTile(store=second, lands_at=(0, 0, 0)),
        ])
    assert "low corner" in str(refused.value)


def test_the_pointers_survive_the_run_being_moved(tmp_path):
    """A run copied to another folder still draws, because the pointers are relative.

    Runs get moved: off the instrument, onto a share, into somebody's home folder.
    A view holding the full path of every tile would break the moment that happened,
    and it would break by drawing nothing rather than by saying anything.
    """
    run = tmp_path / "run"
    _a_run_written_both_ways(run)
    moved = tmp_path / "somewhere else" / "run"
    moved.parent.mkdir()
    shutil.copytree(run, moved)

    rebuilt = _fetched_through_the_server(moved, "pointed.ome.zarr", tmp_path / "asked")
    differing = int(
        (_all_of(rebuilt, "0") != _all_of(moved / "written.ome.zarr", "0")).sum()
    )
    assert differing == 0, (
        f"after the run was copied elsewhere the pointed-at view differs from the "
        f"canvas in {differing} voxels, so its pointers did not survive the move"
    )
