"""Patching the bake for one landing should read the landing, not the survey.

The phase ledger reduced a landing's cost to one dominant name: composing the
dirty piece of the coarsest composed level, 50-70 ms per landing at survey
scale, roughly constant in survey size. The reason it costs that much is not
the landed position -- it is everyone underneath the same piece: a coarse
piece covers a hundred-odd positions, one of them changed, and the patch
recomposes the piece from every tile beneath it. The candidate cure is
paste-over: decode the existing baked piece, lay the landed position's
downsampled footprint over it, encode it back -- the same read-through-the-
recipe trick that already pays for the re-halved levels -- making the patch
cost the landing instead of the neighbourhood.

This file is the instrument that must exist before that cure may be built,
and it has two halves with two different jobs.

The OVERLAP PROOF is green today and must stay green forever. Microscope
tiles deliberately overlap their neighbours (64 pixels in these fixtures),
and where they overlap, the composer lays the LATER-committed tile on top --
commit order is draw order, by first arrival, and a replacement does not
move a position up the pile. A naive paste-over would break exactly this:
painting the replaced position's whole footprint over the piece would put it
on top of a later neighbour in their shared band. This test replaces an
early-committed position with pixels dim enough to tell apart, and holds the
overlap band to the later neighbour's bright pixels while the replaced
position's own ground goes dim. Full recomposition passes it today; any
paste-over that cannot pass it is wrong, whatever it costs.

The COST GATE is deliberately red today, strictly: a steady-state landing's
bake patch reads a count of tile rectangles that follows the piece's
coverage, and the gate demands it follow the landing. When paste-over lands
and the gate turns green, the strict marker makes that loud (an unexpected
pass fails the run), which is the reminder to remove it -- and the overlap
proof beside it is the reason the green can be trusted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

import measure_a_governed_run_at_scale as harness  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from governed import GovernedRun  # noqa: E402


# The replacement's brightness: far below the fixtures' BRIGHT window
# (46,000-62,000) and far above zero, so the three grounds this file must
# tell apart -- bright neighbour, dim replacement, empty fill -- can never
# be mistaken for one another, downsampling and averaging included.
DIM = 700

# How many steady-state landings the cost gate checks.
STEADY_LANDINGS = 3

# The cost gate's allowance: the landed position itself, its overlapping
# neighbours (up to eight), and slack for a tile being read in more than one
# rectangle. A recomposition of a coarse piece reads the HUNDREDS of tiles
# beneath it at survey scale; the gap between that and this allowance is the
# whole point, so the bound is not delicate.
TILE_READS_ALLOWED = 24


def _grid_neighbours(run, order):
    """Two horizontally adjacent positions, the earlier-committed one first.

    Found from the layout's own placements rather than assumed from names,
    and required to genuinely overlap: the step between them must be smaller
    than the frame, or this file's overlap band would be empty and the proof
    would be about nothing.
    """
    placed = {one: run.layout.placement(one).origin for one in order}
    for earlier in order:
        origin = placed[earlier]
        for later in order:
            if order.index(later) <= order.index(earlier):
                continue
            beside = placed[later]
            if (beside.get("y", 0) == origin.get("y", 0)
                    and 0 < beside.get("x", 0) - origin.get("x", 0)
                    < harness.FRAME):
                return earlier, later
    raise AssertionError(
        "no two committed positions overlap horizontally in this layout, so "
        "the overlap band this file's proof depends on does not exist"
    )


def test_the_overlap_band_belongs_to_the_later_commit(tmp_path):
    """Replacing an early tile must not paint over its later neighbour."""
    harness.FIXTURES = tmp_path
    run, order = harness.the_run(4)
    for position_id in order:
        harness.fast_publish(run, position_id)
    early, later = _grid_neighbours(run, order)
    origin = run.layout.placement(early).origin
    step = (run.layout.placement(later).origin["x"] - origin["x"])

    shown = tmp_path / "overlap" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live",
                                       bake=True)
    opened = GovernedRun(run.folder, store=store)
    try:
        held = opened.composer()
        # The coarsest level the patcher COMPOSES (rather than re-halves)
        # is where paste-over would live, so it is where the proof looks.
        baked = tuple(json.loads((store / "zarr.json").read_text(
            encoding="utf-8"))["attributes"]["zmart"]["baked"])
        level = max(one for one in baked if one < held.mosaic.levels)
        down = int(run.profile.level(level).downsampling.get("x", 1))

        import zarr

        def pixel(y: int, x: int) -> int:
            plane = zarr.open_array(str(store / str(level)), mode="r")
            return int(plane[0, y // down, x // down])

        # One point in the replaced position's OWN ground -- inside its
        # frame, clear of every neighbour's overlap band -- and one in the
        # band it shares with its later-committed neighbour.
        own = (origin["y"] + harness.FRAME // 2,
               origin["x"] + (harness.FRAME - step) + step // 3)
        shared = (origin["y"] + harness.FRAME // 2,
                  origin["x"] + step + (harness.FRAME - step) // 2)

        bright_low = harness.BRIGHT[0]
        assert pixel(*own) >= bright_low and pixel(*shared) >= bright_low, (
            "before the replacement both sample points must show bright "
            "specimen, or this proof is sampling the wrong ground"
        )

        run.replace_a_position(early, np.full(
            (1, harness.FRAME, harness.FRAME), DIM, dtype="uint16"))
        opened.composer()

        replaced = pixel(*own)
        band = pixel(*shared)
        # The discrimination the proof rests on, stated as its own check:
        # the replacement really reached the baked file. Without this, a
        # patch that silently did nothing would pass the band assertion.
        assert replaced < bright_low // 2, (
            f"the replaced position's own ground still reads {replaced} at "
            f"level {level} -- the replacement never reached the baked "
            "file, so the band assertion below would be vacuous"
        )
        assert band >= bright_low, (
            f"the overlap band reads {band} at level {level}, but the "
            f"later-committed neighbour's bright pixels (>= {bright_low}) "
            "must own that band: commit order is draw order, and a "
            "replacement does not move a position up the pile. A patch "
            "that painted the replaced tile's whole footprint over the "
            "piece has just been caught doing exactly that."
        )
    finally:
        opened.close()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "patching the bake for one landing recomposes the dirty coarse "
        "piece from every tile beneath it -- a hundred-odd tile reads for a "
        "one-position change at survey scale, measured as the dominant "
        "50-70 ms of every landing by the phase ledger. The candidate cure "
        "is paste-over: decode the baked piece, lay the landing's "
        "downsampled footprint over it, encode it back -- but only beneath "
        "the overlap proof above, which pins the commit-order layering a "
        "naive paste-over would break. Strict, so the cure turns this red "
        "gate into a loud unexpected pass, which is the reminder to remove "
        "the marker and let the gate stand."
    ),
)
def test_patching_a_piece_reads_only_the_landed_ground(tmp_path):
    """A steady landing's bake patch must read O(landing) tile rectangles."""
    harness.FIXTURES = tmp_path
    run, order = harness.the_run(12)
    landings = order[-(STEADY_LANDINGS + 1):]
    for position_id in order[:-(STEADY_LANDINGS + 1)]:
        harness.fast_publish(run, position_id)
    shown = tmp_path / "reads" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live",
                                       bake=True)
    opened = GovernedRun(run.folder, store=store)
    try:
        opened.composer()
        harness.fast_publish(run, landings[0])
        opened.composer()
        for number, position_id in enumerate(landings[1:], 1):
            harness.fast_publish(run, position_id)
            opened.composer()
            composed = opened.accounting["last_bake_pieces_composed"]
            reads = opened.accounting["last_bake_tile_reads"]
            # Blindness guard: zeros only mean something if pieces were
            # actually composed and the composing read something.
            assert composed > 0 and reads > 0, (
                "this landing composed no pieces or read no tiles, so the "
                "cost this gate watches never arose and its numbers are "
                "blindness, not thrift -- the survey or the landing choice "
                "is wrong for this instrument"
            )
            assert reads <= TILE_READS_ALLOWED, (
                f"steady-state landing {number} read {reads} tile "
                f"rectangles to patch {composed} dirty piece(s) -- the "
                "neighbourhood beneath the piece, not the landing. One "
                "landed position plus its overlapping neighbours is "
                f"{TILE_READS_ALLOWED} reads with slack; everything beyond "
                "that is recomposition of ground the landing never touched, "
                "and it is the dominant cost of every landing at survey "
                "scale."
            )
    finally:
        opened.close()
