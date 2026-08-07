"""Adding a tile to a view while the run is still going.

A run being acquired hands the viewer one tile at a time, and the view has to keep
up. Building it again for every tile that lands works and costs the same each time
as building the whole thing, so a long run spends most of its effort redoing what it
already knew — measured at six thousand four hundred tiles, one more tile cost a
second and a half.

:func:`zmart_storage.linked.start_a_growing_view` opens the view once and keeps it
open. These tests check the two things that has to be true about: that the picture
it produces is the same one, and that adding a tile does not get slower as the run
goes on.
"""

from __future__ import annotations

import json
import statistics
import time

import numpy as np
import pytest

from zmart_storage.canvas import Channel, _declare_one
from zmart_storage.linked import (
    the_map_inside,
    where_the_list_goes,
    PlacedTile,
    link_the_tiles,
    start_a_growing_view,
)

# Small enough that a test writes a hundred of them in a moment, and cut into
# pieces smaller than the tile so that a tile is several pieces of the view rather
# than one indivisible block.
TILE = (2, 64, 64)
PIECE = 32
VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (3.0, 1.5, 2.25)


def a_tile(folder, index: int, across: int):
    """Write one tile of a mosaic, and say where it belongs in the picture.

    The pixels encode where the tile came from, so that a picture built out of them
    can be checked against where each tile was meant to land rather than merely
    checked for being non-empty.
    """
    lands_y = (index // across) * TILE[1]
    lands_x = (index % across) * TILE[2]
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
    y, x = np.indices(TILE[1:], dtype=np.int32)
    coded = (1000 + (lands_y + y) * 41 + (lands_x + x)).astype("uint16")
    arrays[0][0, 0] = np.broadcast_to(coded, TILE)
    return PlacedTile(store=store, lands_at=(0, lands_y, lands_x))


def test_a_grown_view_is_the_same_as_one_built_all_at_once(tmp_path):
    """The picture must not depend on whether the tiles arrived together.

    This is the check the whole idea rests on. If a view grown a tile at a time
    differed from one built in a single call, the faster path would be a different
    picture rather than the same picture sooner, and nothing on screen would say
    which one the operator was looking at.
    """
    across, how_many = 4, 16
    at_once = tmp_path / "at_once"
    grown = tmp_path / "grown"
    at_once.mkdir()
    grown.mkdir()

    together = [a_tile(at_once, index, across) for index in range(how_many)]
    link_the_tiles(at_once, name="v", tiles=together,
                   view_shape=(TILE[0], across * TILE[1], across * TILE[2]))

    arriving = [a_tile(grown, index, across) for index in range(how_many)]
    with start_a_growing_view(
        grown, name="v", like=arriving[0],
        view_shape=(TILE[0], across * TILE[1], across * TILE[2]),
    ) as view:
        for tile in arriving:
            view.add(tile)

    def described(folder):
        held = json.loads((folder / "v.ome.zarr" / ".zattrs").read_text())
        return held["multiscales"], held["omero"]

    assert described(grown) == described(at_once), (
        "a grown view describes itself differently from one built all at once"
    )

    def pointers(folder):
        held = the_map_inside(folder / "v.ome.zarr")
        # The tiles live in different folders, so compare everything but the name.
        return sorted(
            (one["at"], one["size"], one["from"], one["held_as"])
            for one in held["tiles"]
        )

    assert pointers(grown) == pointers(at_once), (
        "a grown view points at different pieces from one built all at once"
    )


def test_the_zoomed_out_copies_come_out_the_same(tmp_path):
    """The smaller copies are the part that is genuinely written, so compare them.

    The full-size picture is pointed at and identical by construction. The smaller
    copies are made from the tiles' own pixels as they land, which is where the two
    paths could really differ, so they are compared voxel for voxel.
    """
    import zarr

    across, how_many = 4, 16
    at_once = tmp_path / "at_once"
    grown = tmp_path / "grown"
    at_once.mkdir()
    grown.mkdir()
    shape = (TILE[0], across * TILE[1], across * TILE[2])

    together = [a_tile(at_once, index, across) for index in range(how_many)]
    built = link_the_tiles(at_once, name="v", tiles=together, view_shape=shape,
                           levels=3)

    arriving = [a_tile(grown, index, across) for index in range(how_many)]
    with start_a_growing_view(grown, name="v", like=arriving[0],
                              view_shape=shape, levels=3) as view:
        for tile in arriving:
            view.add(tile)

    assert built.levels == 3
    for level in ("1", "2"):
        one = np.asarray(zarr.open_group(str(at_once / "v.ome.zarr"), mode="r")[level])
        other = np.asarray(zarr.open_group(str(grown / "v.ome.zarr"), mode="r")[level])
        assert np.array_equal(one, other), (
            f"the zoomed-out copy {level} differs between a grown view and one "
            "built all at once"
        )


def test_adding_a_tile_does_not_get_slower_as_the_run_goes_on(tmp_path):
    """The whole point: the cost of a tile must not depend on how many came before.

    Rebuilding the view for each tile costs more and more as the run grows, which
    over a long acquisition is most of the work done. This checks the cost is flat
    instead, by comparing the last tiles of a run against the first.

    An earlier version of this test allowed the last tiles to be five times the cost
    of the first, which is so loose that it passed while the cost was in fact
    climbing steadily — measured at sixteen hundred tiles, from 4 ms to 19 ms. The
    allowance here is still generous, because a shared machine is noisy and this
    should not fail for reasons that have nothing to do with the code, but it is now
    tight enough to notice a cost that grows with the run.
    """
    across, how_many = 24, 576
    folder = tmp_path / "run"
    folder.mkdir()
    arriving = [a_tile(folder, index, across) for index in range(how_many)]

    each = []
    with start_a_growing_view(
        folder, name="v", like=arriving[0],
        view_shape=(TILE[0], across * TILE[1], across * TILE[2]),
    ) as view:
        for tile in arriving:
            began = time.perf_counter()
            view.add(tile)
            each.append(time.perf_counter() - began)

    first = statistics.median(each[:100])
    last = statistics.median(each[-100:])
    assert last < first * 2 + 0.002, (
        f"adding a tile got slower as the run went on: about {first * 1000:.1f} ms "
        f"at the start and {last * 1000:.1f} ms at the end. The cost of one tile "
        "should not depend on how many have already landed."
    )


def a_tile_with_moments_and_colours(folder, index: int, across: int,
                                    frames: int, channels: int):
    """One tile of a mosaic that holds several moments and several colours.

    The pixels encode the moment, the colour and the place they came from, so that
    the picture can be checked for having put every one of them where it belongs
    rather than merely for having something in it.
    """
    lands_y = (index // across) * TILE[1]
    lands_x = (index % across) * TILE[2]
    store = folder / f"tile{index:04d}.ome.zarr"
    arrays = _declare_one(
        store,
        canvas_shape=TILE,
        frames=frames,
        channels=channels,
        dtype="uint16",
        chunk=PIECE,
        levels=1,
        voxel_size_um=VOXEL_UM,
        origin_um=(ORIGIN_UM[0],
                   ORIGIN_UM[1] + lands_y * VOXEL_UM[1],
                   ORIGIN_UM[2] + lands_x * VOXEL_UM[2]),
        channel_blocks=[
            Channel(name, window=(0, 65535)).described(65535)
            for name in ("488", "561", "640")[:channels]
        ],
    )
    y, x = np.indices(TILE[1:], dtype=np.int32)
    for frame in range(frames):
        for channel in range(channels):
            coded = (100 + frame * 10000 + channel * 1000
                     + (lands_y + y) * 3 + (lands_x + x)).astype("uint16")
            arrays[0][frame, channel] = np.broadcast_to(coded, TILE)
    return PlacedTile(store=store, lands_at=(0, lands_y, lands_x))


def test_a_run_with_several_moments_and_colours_grows_the_same_way(tmp_path):
    """A run is five axes — moment, colour, depth, and across the specimen.

    Every other test here uses a single moment and a single colour, which is the
    simplest case and not the usual one: a timelapse in three colours is ordinary
    work. The moments and the colours pass through a view untouched, so they are
    the part most likely to be quietly forgotten, and this checks they are not.
    """
    import zarr

    across, how_many, frames, channels = 3, 9, 3, 2
    at_once = tmp_path / "at_once"
    grown = tmp_path / "grown"
    at_once.mkdir()
    grown.mkdir()
    shape = (TILE[0], across * TILE[1], across * TILE[2])

    together = [a_tile_with_moments_and_colours(at_once, index, across,
                                                frames, channels)
                for index in range(how_many)]
    built = link_the_tiles(at_once, name="v", tiles=together, view_shape=shape,
                           levels=3)

    arriving = [a_tile_with_moments_and_colours(grown, index, across,
                                                frames, channels)
                for index in range(how_many)]
    with start_a_growing_view(grown, name="v", like=arriving[0],
                              view_shape=shape, levels=3) as view:
        for tile in arriving:
            view.add(tile)

    assert built.frames == frames and built.channels == channels

    def described(folder):
        held = json.loads((folder / "v.ome.zarr" / ".zattrs").read_text())
        names = [axis["name"] for axis in held["multiscales"][0]["axes"]]
        return names, held["multiscales"], held["omero"]

    names, _, _ = described(grown)
    assert names == ["t", "c", "z", "y", "x"], (
        f"a grown view does not declare the five axes a run has: {names}"
    )
    assert described(grown) == described(at_once)

    # The zoomed-out copies keep every moment and every colour, and each of them
    # holds what that moment and colour actually recorded.
    for level in ("1", "2"):
        one = np.asarray(zarr.open_group(str(at_once / "v.ome.zarr"), mode="r")[level])
        other = np.asarray(zarr.open_group(str(grown / "v.ome.zarr"), mode="r")[level])
        assert one.shape[0] == frames and one.shape[1] == channels, (
            f"copy {level} lost a moment or a colour: {one.shape}"
        )
        assert np.array_equal(one, other)
        # Different moments and colours must not have been written over each other.
        for frame in range(frames):
            for channel in range(channels):
                block = other[frame, channel]
                assert block.max() > 0, (
                    f"moment {frame} colour {channel} of copy {level} is empty"
                )


def test_a_tile_that_lands_outside_the_declared_room_is_refused(tmp_path):
    """Room is declared before the run, so a tile beyond the edge has to be refused.

    The alternative would be to quietly grow the picture, which cannot be done while
    the viewer is reading its description.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    first = a_tile(folder, 0, 2)
    beyond = a_tile(folder, 1, 2)

    with start_a_growing_view(folder, name="v", like=first,
                              view_shape=TILE) as view:
        view.add(first)
        with pytest.raises(ValueError, match="declared with room for"):
            view.add(beyond)


def test_a_tile_from_somewhere_else_is_refused(tmp_path):
    """A tile that says it was acquired elsewhere is refused rather than misplaced.

    Each tile records where it came from and is told where it goes, so each says on
    its own where the picture's corner must be. One disagreeing means it is being
    put somewhere it was not acquired, or that it belongs to another run — and drawn
    rather than refused, it would be a specimen in the wrong place with nothing to
    say so.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    first = a_tile(folder, 0, 4)
    second = a_tile(folder, 1, 4)
    shape = (TILE[0], 4 * TILE[1], 4 * TILE[2])

    with start_a_growing_view(folder, name="v", like=first,
                              view_shape=shape) as view:
        view.add(first)
        # Put the second tile where the third belongs, a whole tile out.
        misplaced = PlacedTile(store=second.store, lands_at=(0, 0, 2 * TILE[2]))
        with pytest.raises(ValueError, match="corner"):
            view.add(misplaced)


def test_the_list_of_pointers_is_never_seen_half_written(tmp_path):
    """The list is replaced in one step, so a reader gets all of it or none.

    The viewer reads this file while the run is going. Written straight into place
    there is an instant when it is a truncated fragment, and a reader catching it
    then sees a run with most of its tiles missing. Renaming a finished file over
    the old one removes that instant.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    arriving = [a_tile(folder, index, 4) for index in range(16)]
    shape = (TILE[0], 4 * TILE[1], 4 * TILE[2])

    with start_a_growing_view(folder, name="v", like=arriving[0],
                              view_shape=shape) as view:
        held = view.path
        for expected, tile in enumerate(arriving, start=1):
            view.add(tile)
            # Read it back the way the viewer's server does. It must always parse,
            # and it must never claim a tile that has not been added -- a list that
            # is a little behind is fine and is what the throttling is for, but a
            # list running ahead of the run would point at nothing.
            listed = the_map_inside(held)
            assert 0 <= len(listed["tiles"]) <= expected
        # The half-written copy is renamed over the description rather than left
        # beside it, so nothing of that kind should be in the picture's folder.
        # ``.zattrs`` and ``.zgroup`` are zarr's own and belong here.
        leftover = [one.name for one in held.iterdir()
                    if one.name.endswith(".being-written")]
        assert leftover == [], f"a temporary file was left behind: {leftover}"
        path = view.path

    # Closed, the list holds the whole run -- whatever the throttling deferred.
    listed = the_map_inside(path)
    assert len(listed["tiles"]) == len(arriving), (
        "a view closed after its last tile does not hold the whole run on disk"
    )
