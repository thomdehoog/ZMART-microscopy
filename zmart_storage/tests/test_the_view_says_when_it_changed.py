"""The view carries a counter that moves on every change, however quiet.

Most changes to a run announce themselves: a position landing makes the
companion file longer, and rebuilding the list of pointers rewrites the
description. The dangerous changes are the quiet ones — pixels landing in a
moment the view had already declared room for, a position rewritten in place —
where every file a watcher could look at keeps its length and its name, and the
operator would be shown a stale picture with nothing on screen to say so.
``OPEN_a_run_that_changes_while_you_watch.md`` is the record of that danger.

The answer is one number in the view's own description, ``generation``, which
goes up on every rewrite of the list and can be moved by hand — through
:func:`zmart_storage.linked.note_a_change` — for exactly the changes nothing
else can see. These tests pin both halves, and that moving the counter never
disturbs the map beside it.
"""

from __future__ import annotations

import numpy as np

from zmart_storage.canvas import Channel, _declare_one
from zmart_storage.linked import (
    PlacedTile,
    link_the_tiles,
    note_a_change,
    start_a_growing_view,
    the_map_inside,
)

TILE = (1, 64, 64)
PIECE = 32
VOXEL_UM = (2.0, 0.35, 0.35)


def _one_tile(folder, name="tile.ome.zarr"):
    store = folder / name
    arrays = _declare_one(
        store, canvas_shape=TILE, frames=1, channels=1, dtype="uint16",
        chunk=PIECE, levels=1, voxel_size_um=VOXEL_UM,
        origin_um=(0.0, 0.0, 0.0),
        channel_blocks=[Channel("488", window=(0, 4000)).described(65535)],
    )
    arrays[0][0, 0] = np.full(TILE, 7, dtype="uint16")
    return store


def test_building_and_finishing_each_move_the_counter(tmp_path):
    """Every rewrite of the list counts as a change, because it is one."""
    store = _one_tile(tmp_path)
    built = link_the_tiles(
        tmp_path, name="v", tiles=[PlacedTile(store=store, lands_at=(0, 0, 0))],
        levels=1, view_shape=TILE)
    first = the_map_inside(built.path)["generation"]
    assert first >= 1, "a freshly built view should already count one change"

    grown = start_a_growing_view(
        tmp_path, like=PlacedTile(store=store, lands_at=(0, 0, 0)),
        view_shape=TILE, name="g", levels=1)
    at_the_start = the_map_inside(grown.path)["generation"]
    grown.add(PlacedTile(store=store, lands_at=(0, 0, 0)))
    finished = grown.finish()
    at_the_end = the_map_inside(finished.path)["generation"]
    assert at_the_end > at_the_start, (
        "folding the list at the end of a run rewrites it, and a watcher "
        "comparing counters must see that"
    )


def test_a_change_nothing_else_can_see_still_counts(tmp_path):
    """The counter can be moved by hand, and moving it disturbs nothing else."""
    store = _one_tile(tmp_path)
    built = link_the_tiles(
        tmp_path, name="v", tiles=[PlacedTile(store=store, lands_at=(0, 0, 0))],
        levels=1, view_shape=TILE)
    before = the_map_inside(built.path)

    counted = note_a_change(built.path)
    assert counted == before["generation"] + 1, (
        "the counter should move by exactly one per noted change"
    )
    assert note_a_change(built.path) == counted + 1, (
        "and keep moving, once per call"
    )

    after = the_map_inside(built.path)
    untouched = {key: value for key, value in after.items() if key != "generation"}
    expected = {key: value for key, value in before.items() if key != "generation"}
    assert untouched == expected, (
        "noting a change must move the counter and touch nothing else — the "
        "map beside it is what the viewer answers from"
    )
