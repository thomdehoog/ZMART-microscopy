"""Joining a run back into one picture, and what reading it costs either way.

Two questions here. First, that fusing works at all — that a run spread over
several images can be turned into one, which is what makes keeping the overlap a
deferral rather than a commitment. Second, what analysis pays for the run being
spread out, since analysis reads the images during the run to decide where to
look next, and that cost is the one real argument against the arrangement.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel, TileCanvases
from zmart_storage.fuse import fuse

TILE = (2, 128, 128)
STEP = (2, 112, 112)
GRID = 5


def _planes(array) -> np.ndarray:
    """The image as (z, y, x), stepping past whatever leading axes it declares."""
    return np.asarray(array[(0,) * (array.ndim - 3)])


def _a_run(folder: Path, *, single: bool = False) -> TileCanvases:
    side = (GRID - 1) * STEP[1] + TILE[1]
    canvases = TileCanvases.create(
        folder,
        name="overview",
        canvas_shape=(TILE[0], side, side),
        tile_shape=TILE, tile_step=STEP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488", window=(0, 4000))],
        chunk=64, levels=2,
        # These tiles overlap, which is the case that must not be written into
        # one image by default -- so both arrangements here are asked for
        # outright. That is the only way to get either.
        slots=(1, 1, 1) if single else (1, 2, 2),
    )
    for row in range(GRID):
        for col in range(GRID):
            canvases.write(
                np.full(TILE, 1000 + row * GRID + col, dtype="uint16"),
                origin=(0, row * STEP[1], col * STEP[2]),
                tile_index=(0, row, col),
            )
    return canvases


# -- fusing is possible afterwards -------------------------------------------


@pytest.mark.parametrize("how", ["first", "mean", "blend"])
def test_a_run_can_be_joined_into_one_image(tmp_path, how):
    """The whole run becomes a single image, however the joins are handled."""
    _a_run(tmp_path / "run")
    joined = fuse(tmp_path / "run", tmp_path / f"joined_{how}.ome.zarr",
                  where_they_meet=how, levels=2, chunk=64)

    picture = _planes(zarr.open_group(str(joined), mode="r")["0"])
    # Every place a tile covered now holds something, and nothing is left of the
    # gaps between the run's separate images.
    covered = picture[:, :(GRID - 1) * STEP[1] + TILE[1],
                      :(GRID - 1) * STEP[2] + TILE[2]]
    assert (covered > 0).all(), (
        f"{int((covered == 0).sum())} places the run imaged came out empty"
    )


def test_keeping_the_first_recording_leaves_the_numbers_untouched(tmp_path):
    """With ``first``, every voxel is one tile's own reading, not a mixture.

    This is the choice to make when the values themselves matter — a measurement
    of brightness, say — because an average of two tiles is a number the
    microscope never actually recorded.
    """
    _a_run(tmp_path / "run")
    joined = fuse(tmp_path / "run", tmp_path / "joined.ome.zarr",
                  where_they_meet="first", levels=2, chunk=64)

    picture = _planes(zarr.open_group(str(joined), mode="r")["0"])
    values = set(np.unique(picture).tolist()) - {0}
    acquired = {1000 + row * GRID + col for row in range(GRID) for col in range(GRID)}
    assert values <= acquired, (
        f"{values - acquired} appear in the joined picture but were never acquired"
    )


def test_blending_only_changes_the_shared_strips(tmp_path):
    """Away from a join, a blended picture is the tile's own value untouched."""
    pytest.importorskip("scipy")
    _a_run(tmp_path / "run")
    joined = fuse(tmp_path / "run", tmp_path / "joined.ome.zarr",
                  where_they_meet="blend", levels=2, chunk=64)

    picture = _planes(zarr.open_group(str(joined), mode="r")["0"])
    # Well inside the first tile, past where any neighbour reaches.
    assert (picture[:, 8:100, 8:100] == 1000).all()


def test_the_overlap_is_still_there_to_be_compared(tmp_path):
    """Both recordings of a shared strip survive, which is what stitching needs.

    This is the property the whole arrangement exists for. A single image would
    have kept one of the two, and no later step could recover the other.
    """
    canvases = _a_run(tmp_path / "run")
    pictures = [_planes(zarr.open_group(str(p), mode="r")["0"])
                for p in canvases.paths]

    # The strip shared by the tiles at column 0 and column 1.
    y0, x0 = 0, STEP[2]
    strip = [p[:, y0:y0 + TILE[1], x0:x0 + TILE[2] - STEP[2]] for p in pictures]
    found = {int(np.unique(s)[0]) for s in strip if s.max() > 0}
    assert found >= {1000, 1001}, (
        f"only {found} survived in the shared strip — both recordings should be there"
    )


# -- not joining a run on top of itself ---------------------------------------
#
# Making the joined image begins by emptying whatever is already at the path it was
# asked for, and the run is only read afterwards. So a target inside the run is the
# worst kind of mistake: the run goes first, then the joining stops part way with a
# complaint about missing description, and there is neither a run nor a joined
# image left. Reproduced before this was fixed, `fuse(run, run / "overview.ome.zarr")`
# turned a tile of 4242 into zeros and died with `KeyError: 'multiscales'`.


def _a_plain_run(folder: Path) -> TileCanvases:
    """One image with one tile in it, which is all these need."""
    canvases = TileCanvases.create(
        folder, name="overview",
        canvas_shape=(2, 256, 256),
        tile_shape=TILE, tile_step=TILE,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")], chunk=64, levels=2,
    )
    canvases.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                   tile_index=(0, 0, 0))
    return canvases


def _the_run_is_still_readable(canvases: TileCanvases) -> None:
    picture = _planes(zarr.open_group(str(canvases.paths[0]), mode="r")["0"])
    assert (picture[:, :TILE[1], :TILE[2]] == 4242).all(), (
        "the run was destroyed by a fuse that should have been refused"
    )


def test_joining_a_run_on_top_of_its_own_image_is_refused(tmp_path):
    """The run must still be there when the joining is over, or refused before it."""
    run = tmp_path / "run"
    canvases = _a_plain_run(run)

    with pytest.raises(ValueError, match="would empty the run's own image"):
        fuse(run, run / "overview.ome.zarr", levels=2, chunk=64)

    _the_run_is_still_readable(canvases)


def test_joining_into_a_place_inside_the_runs_image_is_refused(tmp_path):
    """Inside one of the run's images is inside the run, and just as destructive."""
    run = tmp_path / "run"
    canvases = _a_plain_run(run)

    with pytest.raises(ValueError, match="would empty the run's own image"):
        fuse(run, run / "overview.ome.zarr" / "joined", levels=2, chunk=64)

    _the_run_is_still_readable(canvases)


def test_joining_on_top_of_the_run_folder_is_refused(tmp_path):
    """The run folder holds every image of the run, so this would take all of them."""
    run = tmp_path / "run"
    canvases = _a_plain_run(run)

    with pytest.raises(ValueError, match="would empty the whole run folder"):
        fuse(run, run, levels=2, chunk=64)

    _the_run_is_still_readable(canvases)
    assert (run / "overview.ome.zarr").is_dir()


def test_joining_into_the_run_folder_beside_its_images_is_refused(tmp_path):
    """Nothing is destroyed by this, but the joined image would join the run.

    A run's folder is read by gathering every image in it, so a joined image left
    there becomes one of that run's own images from then on: the viewer draws it as
    part of the acquisition, and joining the run a second time reads the first
    joined image back in as though it had been acquired. Somewhere outside the run
    is both safer and easier to explain.
    """
    run = tmp_path / "run"
    _a_plain_run(run)

    with pytest.raises(ValueError, match="inside the run folder"):
        fuse(run, run / "joined.ome.zarr", levels=2, chunk=64)


def test_joining_beside_the_run_is_what_works(tmp_path):
    """The refusals must leave the ordinary way of doing this untouched."""
    run = tmp_path / "run"
    _a_plain_run(run)

    joined = fuse(run, tmp_path / "run_joined.ome.zarr", levels=2, chunk=64)

    picture = _planes(zarr.open_group(str(joined), mode="r")["0"])
    assert (picture[:, :TILE[1], :TILE[2]] == 4242).all()


# -- what analysis pays ------------------------------------------------------


def test_reading_a_region_costs_about_the_same_either_way(tmp_path, capsys):
    """Analysis reads regions during the run; this is what the spread costs it.

    Most of a region falls inside one tile, so only one of the images has
    anything there and the others answer "nothing here" without reading a thing.
    The question is whether those empty answers are cheap enough not to matter.
    """
    spread = _a_run(tmp_path / "spread")
    single = _a_run(tmp_path / "single", single=True)

    def read_many(paths, rounds=40):
        arrays = [zarr.open_group(str(p), mode="r")["0"] for p in paths]
        rng = np.random.default_rng(0)
        began = time.perf_counter()
        for _ in range(rounds):
            y = int(rng.integers(0, (GRID - 1) * STEP[1]))
            x = int(rng.integers(0, (GRID - 1) * STEP[2]))
            patch = None
            for array in arrays:
                here = np.asarray(array[(0,) * (array.ndim - 3)][:, y:y + 64, x:x + 64])
                patch = here if patch is None else np.where(patch == 0, here, patch)
        return (time.perf_counter() - began) / rounds * 1000

    one = read_many(single.paths)
    four = read_many(spread.paths)
    with capsys.disabled():
        print(f"\n  reading a 64x64 region: one image {one:.2f} ms, "
              f"four images {four:.2f} ms  ({four / one:.1f}x)")

    # Not a performance promise -- machines differ. This only catches the spread
    # turning out to be far more expensive than the arithmetic suggests, which
    # would mean the empty answers are not cheap after all.
    assert four < one * 8
