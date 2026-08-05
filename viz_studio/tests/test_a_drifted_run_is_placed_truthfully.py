"""Does a run off a real stage get drawn where the stage says it went?

A microscope asked to step 1792 voxels steps 1792 give or take a couple. Those few
voxels are harmless for the science — a stitcher measures the real offset afterwards,
which is why the tiles overlap in the first place — but they are exactly what breaks
a view built out of pointers. A view hands the viewer a tile's own file untouched,
and it can only do that when a piece of the view is precisely a piece of a tile. A
tile beginning seven voxels late has no such file to offer.

The way round it is not in the viewer. It is in how the tile is written: pad the
tile's low edge by however far the stage overshot, so the tile's own grid of pieces
sits on the run's grid. Every piece inside the tile is then a piece of the view,
exactly, and the drift costs nothing at all.

These tests check that claim the strictest way available. The tiles hold
**coordinate-coded** pixels — every voxel holds ``1000 +`` the position it was
acquired at — so where a tile really ended up on screen can be read straight off the
picture rather than worked out from it. If a tile is drawn even one voxel from where
the stage put it, the numbers say so immediately.

The picture is read back **through the viewer's own server**, over HTTP, exactly as
the browser reads it. That matters: it is the pointers, the description the view
invents for itself, and the agreement between the two that are being checked, not
just some arithmetic in isolation.
"""

from __future__ import annotations

import json
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

from zmart_storage.canvas import Channel, _declare_one  # noqa: E402
from zmart_storage.linked import PlacedTile, link_the_tiles  # noqa: E402

# How large one piece of storage is, across y and x. This is the number an
# acquisition has to choose, and it is what everything here turns on: a tile has to
# be cut into pieces much smaller than itself before it can be placed at all.
PIECE = 128

# One plane, 128 voxels tall, 512 across. Small enough to write and compare in a
# moment, large enough to be several pieces wide, which is the case that matters.
CONTENT = (1, 128, 512)

# Neighbours overlap by 128 voxels — one piece. A real run should overlap by two,
# so that the padded edge is always covered whatever the stage does; one is enough
# here because these drifts are known.
STEP = 384

# How far past the nominal step each tile really landed. None of these is a whole
# number of pieces, which is the entire point: this is what a real stage does and
# what the tidy grids in the other tests never exercise.
DRIFT = (0, 7, 16)

VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (11.0, 5.5, 7.25)

# A value that appears nowhere in the specimen, written into the padding so that
# padding served as though it were picture would be obvious rather than plausible.
PADDING_MARK = 60000


def _an_aligned_tile(folder: Path, lands_x: int) -> tuple[Path, int, int]:
    """Write one tile with its pieces sitting on the run's grid of pieces.

    The stage put this tile's first real voxel at ``lands_x``, which is generally not
    a whole number of pieces along. So the tile is stored starting a little earlier —
    at the piece boundary just before — with the gap filled in and marked as padding.
    Its recorded position is that earlier corner, which is the honest thing to record:
    it is where the stored image really begins.

    Returns the folder, where the stored image begins, and how wide it is.
    """
    pad = lands_x % PIECE
    array_origin = lands_x - pad
    width = pad + CONTENT[2]

    arrays = _declare_one(
        folder,
        canvas_shape=(CONTENT[0], CONTENT[1], width),
        frames=1,
        channels=1,
        dtype="uint16",
        chunk=PIECE,
        levels=1,
        voxel_size_um=VOXEL_UM,
        origin_um=(
            ORIGIN_UM[0], ORIGIN_UM[1], ORIGIN_UM[2] + array_origin * VOXEL_UM[2],
        ),
        channel_blocks=[Channel("488", window=(0, 4000)).described(65535)],
    )
    if pad:
        arrays[0][0, 0, :, :, :pad] = PADDING_MARK
    across = np.arange(lands_x, lands_x + CONTENT[2], dtype=np.uint16)
    arrays[0][0, 0, :, :, pad:] = np.broadcast_to(1000 + across, CONTENT)
    return folder, array_origin, width


def _a_drifted_run(folder: Path) -> tuple[list[PlacedTile], int]:
    """A row of tiles that drifted, each written so its pieces still line up.

    Also works out which pieces of the view each tile should supply: a tile can only
    supply the pieces it fills completely, and where two of them could both supply a
    piece the seam is put on the piece boundary between them.
    """
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for index, drift in enumerate(DRIFT):
        lands_x = index * STEP + drift
        store, array_origin, width = _an_aligned_tile(
            folder / f"tile{index}.ome.zarr", lands_x
        )
        # The pieces this tile fills completely: the first whole one at or after its
        # real pixels begin, through the last whole one ending before they run out.
        fills = (
            array_origin + (PIECE if lands_x % PIECE else 0),
            array_origin + (width // PIECE) * PIECE,
        )
        written.append((store, array_origin, fills))

    placed: list[PlacedTile] = []
    owned_up_to = written[0][2][0]
    for index, (store, array_origin, fills) in enumerate(written):
        low = owned_up_to
        high = fills[1] if index == len(written) - 1 else written[index + 1][2][0]
        placed.append(PlacedTile(
            store=store,
            lands_at=(0, 0, low),
            taken_from=(0, 0, low - array_origin),
            size=(CONTENT[0], CONTENT[1], high - low),
        ))
        owned_up_to = high
    return placed, owned_up_to


# -- reading the view back the way the browser does ----------------------------


def _fetch(address: str, into: Path) -> bool:
    """Ask for one piece of the picture. Returns whether there was anything there."""
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


def _fetched_through_the_server(folder: Path, image: str, into: Path) -> Path:
    """Ask the viewer's server for every piece of an image and rebuild it on disk."""
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
        described_image = json.loads((folder / image / ".zattrs").read_text("utf-8"))
        for dataset in described_image["multiscales"][0]["datasets"]:
            level = str(dataset["path"])
            (rebuilt / level).mkdir(exist_ok=True)
            _fetch(f"{address}/{level}/.zarray", rebuilt / level / ".zarray")
            described = json.loads((rebuilt / level / ".zarray").read_text("utf-8"))
            shape = [int(n) for n in described["shape"]]
            chunks = [int(n) for n in described["chunks"]]
            separator = described.get("dimension_separator", ".")
            counts = [-(-shape[axis] // chunks[axis]) for axis in range(5)]
            for frame in range(counts[0]):
                for channel in range(counts[1]):
                    for z in range(counts[2]):
                        for y in range(counts[3]):
                            for x in range(counts[4]):
                                named = separator.join(
                                    str(n) for n in (frame, channel, z, y, x)
                                )
                                _fetch(
                                    f"{address}/{level}/{named}", rebuilt / level / named
                                )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    return rebuilt


# -- the tests -----------------------------------------------------------------


def test_a_drifted_run_draws_every_voxel_where_the_stage_put_it(tmp_path):
    """The whole arrangement, end to end, on a run that drifted.

    Every voxel of these tiles knows the position it was acquired at, so this asks
    the picture directly: is voxel x holding the number that was recorded at x? A
    tile drawn even one voxel out fails here, which is the point — that failure is
    invisible on screen and would otherwise be found by a biologist, months later,
    wondering why two channels of the same specimen do not line up.
    """
    run = tmp_path / "run"
    placed, view_width = _a_drifted_run(run)
    view = link_the_tiles(
        run, name="pointed", tiles=placed,
        view_shape=(CONTENT[0], CONTENT[1], view_width),
    )

    rebuilt = _fetched_through_the_server(run, "pointed.ome.zarr", tmp_path / "asked")
    served = np.asarray(zarr.open_group(str(rebuilt), mode="r")["0"][0, 0, 0])
    expected = np.broadcast_to(
        1000 + np.arange(view_width, dtype=np.uint16), (CONTENT[1], view_width)
    )

    wrong = np.argwhere(served != expected)
    assert len(wrong) == 0, (
        f"{len(wrong)} of {served.size} voxels of the drifted run were drawn "
        f"somewhere other than where they were acquired — displaced by "
        f"{sorted({int(served[y, x]) - 1000 - int(x) for y, x in wrong})} voxels"
    )
    assert view.tiles == len(DRIFT)


def test_none_of_the_padding_is_ever_served_as_picture(tmp_path):
    """A tile supplies only pieces it fills completely, so its padding stays hidden.

    Aligning a tile means giving it a little padding at its low edge, and padding
    drawn as though it were specimen would look like a dark band at every seam. A
    tile is therefore given only the pieces it can fill entirely from its own
    pixels, and this is the check that it really was.
    """
    run = tmp_path / "run"
    placed, view_width = _a_drifted_run(run)
    link_the_tiles(
        run, name="pointed", tiles=placed,
        view_shape=(CONTENT[0], CONTENT[1], view_width),
    )
    rebuilt = _fetched_through_the_server(run, "pointed.ome.zarr", tmp_path / "asked")
    served = np.asarray(zarr.open_group(str(rebuilt), mode="r")["0"][0, 0, 0])

    showing = int((served == PADDING_MARK).sum())
    assert showing == 0, (
        f"{showing} voxels of a tile's padding were served as though they were "
        "specimen, which would appear as a band along a seam"
    )


def test_nothing_of_the_full_size_picture_is_written(tmp_path):
    """The drift is absorbed by the tiles, not by copying the picture out.

    Worth asserting separately: an arrangement that quietly wrote the full-size
    picture would pass both tests above while costing exactly what it exists to
    save.
    """
    run = tmp_path / "run"
    placed, view_width = _a_drifted_run(run)
    view = link_the_tiles(
        run, name="pointed", tiles=placed,
        view_shape=(CONTENT[0], CONTENT[1], view_width),
    )
    describing = {".zarray", ".zattrs", ".zgroup", "zarr.json"}
    picture = sorted(
        child.name for child in (view.path / "0").iterdir()
        if child.name not in describing
    )
    assert picture == [], (
        f"the full-size copy holds {picture} besides the files describing it, and "
        "it should hold no picture at all"
    )


def test_a_tile_that_was_not_aligned_is_still_refused(tmp_path):
    """An unaligned tile is refused rather than drawn a few voxels out.

    This is the guard the measurements earn. Handed a tile whose pieces do not sit
    on the run's grid, the list of pointers has no way to say "seven voxels along" —
    it counts in whole pieces — so the tile would be drawn displaced by the drift,
    with nothing on screen to say so. Refusing is the only honest answer, and the
    message has to say what to change.
    """
    run = tmp_path / "run"
    run.mkdir()
    store, array_origin, _ = _an_aligned_tile(run / "tile.ome.zarr", 0)

    with pytest.raises(ValueError) as refused:
        link_the_tiles(
            run, name="pointed",
            # Seven voxels along: what a stage really does, and what a tile written
            # without the aligning padding would ask the view to draw.
            tiles=[PlacedTile(store=store, lands_at=(0, 0, 7))],
        )
    said = str(refused.value)
    assert "whole number of them" in said
    assert "pieces" in said
