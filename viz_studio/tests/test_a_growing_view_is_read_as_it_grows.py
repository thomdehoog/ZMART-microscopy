"""Does the viewer see a tile as soon as it lands?

A run still on the microscope adds tiles to its view one at a time, and the whole
point of that is for the operator to watch the plate fill in. So the half of this
that answers requests has to notice a tile the moment it is added — not when the
run finishes, and not when something happens to clear a cache.

That is easy to get wrong in a way nothing reports. The list of pointers is read
once and remembered, because reading it for every piece of every frame would be
wasteful; if the remembering is keyed on something that does not change when a tile
lands, the viewer keeps answering from the old list and simply never shows the new
tiles. Nothing errors. The plate just stops filling in, and the operator has no way
to tell that from a microscope that has stopped acquiring.

These tests read through :mod:`linking` exactly as the viewer's server does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import linking  # noqa: E402

from zmart_storage.canvas import Channel, _declare_one  # noqa: E402
from zmart_storage.linked import (  # noqa: E402

    PlacedTile,
    start_a_growing_view,
)

TILE = (1, 64, 64)
PIECE = 32
VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (3.0, 1.5, 2.25)
ACROSS = 4


@pytest.fixture(autouse=True)
def _forget_between_tests():
    """Start each test with nothing remembered, so one cannot mask another."""
    linking._known.clear()
    yield
    linking._known.clear()


def a_tile(folder: Path, index: int) -> PlacedTile:
    """Write one tile of a small mosaic and say where it belongs."""
    lands_y = (index // ACROSS) * TILE[1]
    lands_x = (index % ACROSS) * TILE[2]
    store = folder / f"tile{index:04d}.ome.zarr"
    arrays = _declare_one(
        store,
        canvas_shape=TILE,
        frames=1,
        channels=1,
        dtype="uint16",
        chunk=PIECE,
        levels=1,
        voxel_size_um=VOXEL_UM,
        origin_um=(ORIGIN_UM[0],
                   ORIGIN_UM[1] + lands_y * VOXEL_UM[1],
                   ORIGIN_UM[2] + lands_x * VOXEL_UM[2]),
        channel_blocks=[Channel("488", window=(0, 65535)).described(65535)],
    )
    arrays[0][0, 0] = np.full(TILE, 1000 + index, dtype="uint16")
    return PlacedTile(store=store, lands_at=(0, lands_y, lands_x))


def where_that_tile_is(index: int) -> str:
    """The address of the piece at a tile's own corner, as the browser asks for it."""
    lands_y = (index // ACROSS) * TILE[1] // PIECE
    lands_x = (index % ACROSS) * TILE[2] // PIECE
    return f"0/0/0/0/{lands_y}/{lands_x}"


def test_a_tile_is_answered_for_the_moment_it_lands(tmp_path):
    """Each tile must be visible immediately, not once the run has finished.

    Checked after every single tile rather than at the end, because a reader that
    picked tiles up in batches — or only when something else happened to change —
    would pass a test that looked once.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    arriving = [a_tile(folder, index) for index in range(ACROSS * ACROSS)]

    with start_a_growing_view(
        folder, name="v", like=arriving[0],
        view_shape=(TILE[0], ACROSS * TILE[1], ACROSS * TILE[2]), levels=1,
    ) as view:
        for index, tile in enumerate(arriving):
            # Before it lands there is nothing at that address.
            assert linking.the_bytes_behind(view.path, where_that_tile_is(index)) is None

            view.add(tile)

            found = linking.the_bytes_behind(view.path, where_that_tile_is(index))
            assert found is not None, (
                f"tile {index} had landed and the reader still answered 'nothing "
                "here'. A run being watched would stop filling in, with nothing "
                "anywhere to say why."
            )
            assert tile.store.name in found.path

            # And every tile before it is still answered for.
            for earlier in range(index):
                assert linking.the_bytes_behind(
                    view.path, where_that_tile_is(earlier)) is not None


def test_the_view_still_reads_after_the_run_has_finished(tmp_path):
    """Closing the run folds the added lines away; the answers must not change.

    A finished view keeps every tile in the list itself and the companion file goes,
    so this is the moment the reader's two sources become one. Every address that
    answered during the run has to answer the same way afterwards.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    arriving = [a_tile(folder, index) for index in range(ACROSS * ACROSS)]

    view = start_a_growing_view(
        folder, name="v", like=arriving[0],
        view_shape=(TILE[0], ACROSS * TILE[1], ACROSS * TILE[2]), levels=1)
    for tile in arriving:
        view.add(tile)
    during = {
        index: linking.the_bytes_behind(view.path, where_that_tile_is(index))
        for index in range(len(arriving))
    }
    finished = view.finish()

    assert not linking.where_the_list_is(finished.path)[1].exists(), (
        "the companion file was left behind on a finished run"
    )
    after = {
        index: linking.the_bytes_behind(finished.path, where_that_tile_is(index))
        for index in range(len(arriving))
    }
    assert after == during, (
        "a view answers differently once its run has finished, so the picture "
        "would change under an operator who was watching it"
    )


def test_a_line_caught_half_written_is_simply_not_there_yet(tmp_path):
    """The companion file is read while it is being written, so this must be safe.

    A reader can catch the last line partway through. It should leave that line out
    and answer for everything before it — the tile appears a moment later, on the
    next look — rather than refusing the whole view, which would blank a picture
    the operator is watching.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    arriving = [a_tile(folder, index) for index in range(4)]

    with start_a_growing_view(
        folder, name="v", like=arriving[0],
        view_shape=(TILE[0], ACROSS * TILE[1], ACROSS * TILE[2]), levels=1,
    ) as view:
        for tile in arriving:
            view.add(tile)

        # Truncate the final line, the way a reader arriving mid-write would see it.
        added = linking.where_the_list_is(view.path)[1]
        whole = added.read_text(encoding="utf-8")
        lines = whole.splitlines()
        added.write_text("\n".join(lines[:-1]) + "\n" + lines[-1][: len(lines[-1]) // 2],
                         encoding="utf-8")
        linking._known.clear()

        for index in range(len(arriving) - 1):
            assert linking.the_bytes_behind(
                view.path, where_that_tile_is(index)) is not None, (
                "a half-written last line stopped the tiles before it being read"
            )

        # Put it back, so closing the view writes a list that holds every tile.
        added.write_text(whole, encoding="utf-8")
