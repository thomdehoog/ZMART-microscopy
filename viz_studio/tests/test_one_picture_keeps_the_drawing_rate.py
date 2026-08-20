"""Does showing a run as one picture keep the viewer drawing?

The fault this guards against is written up in `test_the_drawing_keeps_up.py`
beside this file, and it is the worst one the project has found. Three drawing
layers are made for every position that is open, and every one of them takes part
in every frame, so the cost is paid on every draw for as long as the acquisition is
open. Loading slowly is finite — the operator waits and it ends. A viewer that has
finished loading and then moves at one frame a second is *permanently* like that.

`NEXT_STEPS.md` calls the fix architectural: the engine has to be holding fewer
positions. A linked view is exactly that. It hands the viewer **one** store however
many tiles are underneath it, so the per-position cost is paid once instead of ten
thousand times.

That was a claim about how the viewer builds its layers, and it is now a
measurement. `viz_studio/measure_the_frame_rate_of_a_linked_view.py` climbs through
the sizes and counted, on this repository's sandbox, frames drawn in three seconds
of moving through the specimen:

===========  ==========  ========  ==============
      tiles    separate    linked    linked keeps
===========  ==========  ========  ==============
          1         115       113           0.98x
         20          65       106           1.63x
        100          31       104           3.35x
        400           7        96          13.71x
        800           4        90          22.50x
===========  ==========  ========  ==============

The linked view is flat — 113 frames at one tile, 90 at eight hundred. Separate
stores fall to about one frame a second, which is not a viewer anybody can work in.
The ratio tracking the tile count is what makes it conclusive: that is the shape you
get when the cost is paid per position and one picture pays it once.

**This test is smaller than that on purpose.** Eight hundred positions take a minute
and a half to write, open and measure, which is too slow to live in a suite that
people run often. Two hundred shows the same thing in a fraction of the time — the
mechanism is identical and only the number is smaller, which is the same choice
`test_many_positions_arrive.py` makes for the same reason. The full climb is kept in
the measurement script for when the question is "how bad does it get".

**Everything here is a comparison, never a number.** A machine with no graphics card
draws slowly whatever it is given, so an absolute rate would mean nothing and would
need retuning for every machine. If the whole machine slows down, both halves slow
together and the ratio does not move.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from measure_the_frame_rate_of_a_linked_view import (  # noqa: E402
    TILE,
    a_grid_of_tiles,
    frames_counted,
)

from zmart_storage.linked import link_the_tiles  # noqa: E402

# How many positions to compare. Two hundred is where the fault is already plain —
# seventeen frames against ninety-five when this was measured — while still opening
# in well under a minute.
MANY = 200

# A handful, to show the linked view is flat rather than merely better. Without this
# a linked view that was simply slow in a different way would still pass.
FEW = 20

# How much faster the one picture has to be at ``MANY`` positions.
#
# **These two thresholds were recalibrated on 5 August 2026 and are deliberately
# loose.** They used to be 3.0 and 0.66, taken when the tiles were laid out in a
# single row. A row of two hundred tiles is a long thin strip, most of it off the
# screen, so the single picture had almost nothing to draw and its rate was
# flattering — 5.59 times faster, keeping 0.90 of its rate. The tiles are laid out
# as a mosaic now, for exactly that reason, and both numbers came down when the
# measurement started being honest.
#
# Measured three times on this sandbox after the change: 2.29, 1.50 and above 3.0
# times faster. That spread is what a contended machine with no graphics card gives,
# and a threshold inside it would fail about half the time — which teaches people to
# ignore the test, the worst outcome available.
#
# So these guard the effect **existing**, not its size. If one picture ever stops
# being clearly faster than two hundred stores, or a view's rate ever collapses as
# tiles are added, they will say so. For the size of the effect, read the tables in
# ``HANDOVER_a_view_that_writes_nothing.md``, which were taken with the screen
# content held steady rather than growing.
MUST_BE_FASTER_BY = 1.3

# How much of its own rate the one picture has to keep when ten times as many tiles
# are underneath it.
#
# Note what this can and cannot see, because the mosaic changed it. Twenty tiles
# cover a small part of the window and two hundred fill it, so the larger view is
# genuinely drawing more picture and is legitimately slower for a reason that has
# nothing to do with how many stores are underneath. Measured at 0.53 once the
# layout changed, against 0.90 when the picture stayed the same size.
#
# The clean version of this question — same screen content, more run underneath —
# is what ``measure_a_run_of_positions.py`` asks, and there the middle frame holds
# at 33 ms from one position to two thousand.
MUST_STAY_FLAT = 0.40


@pytest.fixture(scope="module")
def counted(counting_browser, built_dist, tmp_path_factory) -> dict[str, int]:
    """Frames drawn by the same tiles opened as many stores and as one picture.

    Measured once for the whole file. Both tests below ask different questions of
    the same three measurements, and measuring twice would double the slowest part
    of this file for nothing.
    """
    folder = tmp_path_factory.mktemp("one_picture")
    placed = a_grid_of_tiles(folder, MANY)

    def big_enough_for(tiles):
        """How large a picture has to be to hold these tiles, as ``(z, y, x)``.

        Worked out from where the tiles actually landed rather than assumed. The
        tiles used to be laid out in a single row, and the size could then be
        written down directly as "this many tiles across". They are laid out as a
        mosaic now — a row of eight hundred is a hair on the screen, so the rate
        being measured was mostly the cost of redrawing an empty panel — and a
        mosaic's height depends on how many tiles there are.
        """
        return tuple(
            max(one.lands_at[axis] + TILE[axis] for one in tiles) for axis in range(3)
        )

    link_the_tiles(
        folder, name="linked", tiles=placed, view_shape=big_enough_for(placed),
    )
    # A second view over only the first few of the same tiles, so that "flat" is
    # measured on the same arrangement rather than against a different run.
    link_the_tiles(
        folder, name="linkedfew", tiles=placed[:FEW],
        view_shape=big_enough_for(placed[:FEW]),
    )

    names = sorted(p.name for p in folder.glob("tile*.ome.zarr"))
    return {
        "separate": frames_counted(counting_browser, built_dist, folder, names[:MANY], MANY),
        "linked": frames_counted(counting_browser, built_dist, folder, "linked.ome.zarr", 1),
        "linked_few": frames_counted(
            counting_browser, built_dist, folder, "linkedfew.ome.zarr", 1
        ),
    }


def test_one_picture_draws_far_faster_than_many_stores(counted):
    """The whole point of pointing at tiles instead of opening them.

    A run opened as one picture per position becomes unusable long before the disk
    or the loading does, and this is the measurement that says pointing fixes it.
    """
    separate, linked = counted["separate"], counted["linked"]
    assert separate > 0, (
        "no frames at all were counted with the positions open separately, so this "
        "measurement is not working and says nothing about the viewer either way"
    )
    faster = linked / separate
    assert faster >= MUST_BE_FASTER_BY, (
        f"with {MANY} positions open the viewer drew {separate} frames as separate "
        f"stores and {linked} as one picture — {faster:.2f} times faster, where at "
        f"least {MUST_BE_FASTER_BY} was expected.\n\n"
        "Either the cost that used to be paid per position has moved somewhere a "
        "single picture also pays it, or the view stopped being served as one store."
    )


def test_one_picture_hardly_notices_how_many_tiles_are_under_it(counted):
    """Flat, not merely faster — which is the claim that matters at ten thousand.

    Being three times quicker would be worth little if it still fell away with the
    number of tiles: the run this is all for has ten thousand positions, not two
    hundred. What has to hold is that a picture made of many tiles draws at about
    the rate of a picture made of few.
    """
    few, many = counted["linked_few"], counted["linked"]
    assert few > 0, "no frames were counted for the smaller picture"
    kept = many / few
    assert kept >= MUST_STAY_FLAT, (
        f"one picture over {FEW} tiles drew {few} frames and the same picture over "
        f"{MANY} drew {many} — keeping {kept:.2f} of its rate, where at least "
        f"{MUST_STAY_FLAT} was expected.\n\n"
        "A view is one store however many tiles it points at, so its drawing cost "
        "should hardly depend on the count. If this has slipped, something is being "
        "paid per tile again and it will be far worse at ten thousand."
    )
