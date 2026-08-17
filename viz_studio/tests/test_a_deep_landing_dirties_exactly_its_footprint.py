"""A landing into a deep survey changes its own ground and nothing else.

The whole derive economy rests on this: absorbing one position's landing
costs the change, not the survey. In depth the promise has a new way to
fail quietly — slab state, per-plane pieces, and the pyramid's halving
all offer places for a landing to smudge a neighbour's pixels or for a
plane to inherit another's — so the gate is byte-level and exhaustive:
photograph every piece of every plane of every level, land one position,
photograph again, and demand that exactly the landing's own piece
columns changed, at every plane, and everything else came back
byte-identical.

The expected footprint is computed here from the layout's own numbers
(the landing's frame, divided to each level with the ceiling rule). The
depth plan orders ONE named dirty shape shared by all consumers once
slabs exist; when that shape lands, this test imports it instead of
computing its own, and the comparison becomes the proof there is exactly
one definition.

The second gate re-runs the parallel-encoder trap in depth: many pieces
asked for at once, across planes, must decode to exactly the bytes the
same pieces give one at a time — shared slab state is new in depth, and
a race here would show as one plane wearing another's specimen only
under concurrency, which no sequential test can see.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

from governed import GovernedRun  # noqa: E402

from zmart_live.model import GridCell, rounded_up  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

DEPTH = 13   # ragged, per the depth test plan's fixture rule
FRAME = 384
PIECE = 128  # small pieces, so one landing's footprint is several columns
             # of many, and "outside the footprint" genuinely exists


def a_stamped_stack(base: int) -> np.ndarray:
    planes = np.empty((DEPTH, FRAME, FRAME), dtype="uint16")
    for plane in range(DEPTH):
        planes[plane] = base + plane
    return planes


def a_deep_survey(folder):
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=DEPTH)
    cells = {GridCell(row, column): f"p{row}{column}"
             for row in range(2) for column in range(2)}
    return LivePublisher(folder / "experiment" / "acquisitions" / "deep",
                         profile, run_id="deep-footprint", cells=cells)


def every_piece_of(composer) -> dict[tuple[int, int, int, int], bytes | None]:
    took = {}
    for level in range(composer.mosaic.levels):
        deep, height, width = composer.mosaic.shape(level)
        for plane in range(deep):
            for row in range(rounded_up(height, PIECE)):
                for column in range(rounded_up(width, PIECE)):
                    took[(level, plane, row, column)] = composer.bytes_for(
                        level, plane, row, column)
    return took


def the_footprint_of(run, position_id, composer) -> set[tuple[int, int]]:
    """Which (row, column) pieces one position's frame touches, per level.

    From the layout's own numbers: the frame's edges divided to the level
    with the ceiling rule, then to piece indices. Returned as
    (level, row, column)-free pairs keyed by level via tuples
    (level, row, column).
    """
    placement = run.layout.placement(position_id)
    touched = set()
    for level in range(composer.mosaic.levels):
        down = run.profile.level(level).downsampling
        top = int(placement.origin["y"]) // int(down.get("y", 1))
        left = int(placement.origin["x"]) // int(down.get("x", 1))
        bottom = rounded_up(int(placement.origin["y"]) + FRAME, int(down.get("y", 1)))
        right = rounded_up(int(placement.origin["x"]) + FRAME, int(down.get("x", 1)))
        for row in range(top // PIECE, rounded_up(bottom, PIECE)):
            for column in range(left // PIECE, rounded_up(right, PIECE)):
                touched.add((level, row, column))
    return touched


def test_a_deep_landing_changes_exactly_its_own_pieces(tmp_path):
    run = a_deep_survey(tmp_path)
    for number, position_id in enumerate(("p00", "p01", "p10")):
        run.write_and_publish(position_id, a_stamped_stack(1000 * (number + 1)))

    opened = GovernedRun(run.folder, piece=PIECE)
    try:
        before = every_piece_of(opened.composer())
        run.write_and_publish("p11", a_stamped_stack(9000))
        after = every_piece_of(opened.composer())

        assert set(before) == set(after), "the picture's piece grid moved"
        footprint = the_footprint_of(run, "p11", opened.composer())
        changed = {address for address in before
                   if before[address] != after[address]}

        outside = {address for address in changed
                   if (address[0], address[2], address[3]) not in footprint}
        assert not outside, (
            f"{len(outside)} pieces changed OUTSIDE the landing's footprint "
            f"(first few: {sorted(outside)[:4]}) -- a landing must never "
            "touch a neighbour's ground"
        )
        # The landing must actually show, and at every plane: a stack lands
        # whole, so each of its 13 planes gains pixels in the footprint.
        for plane in range(DEPTH):
            assert any(address[1] == plane for address in changed), (
                f"plane {plane} shows no change anywhere after a 13-plane "
                "landing -- a plane of the stack went missing"
            )
    finally:
        opened.close()


def test_pieces_asked_for_all_at_once_are_not_muddled(tmp_path):
    """The parallel-encoder trap, re-run in depth."""
    run = a_deep_survey(tmp_path)
    run.write_and_publish("p00", a_stamped_stack(1000))
    run.write_and_publish("p01", a_stamped_stack(3000))

    opened = GovernedRun(run.folder, piece=PIECE)
    try:
        composer = opened.composer()
        alone = every_piece_of(composer)
        addresses = list(alone)
        with ThreadPoolExecutor(max_workers=8) as pool:
            answers = list(pool.map(
                lambda address: composer.bytes_for(*address), addresses))
        together = dict(zip(addresses, answers, strict=True))
        muddled = [address for address in addresses
                   if alone[address] != together[address]]
        assert not muddled, (
            f"{len(muddled)} pieces decode differently under concurrency "
            f"(first few: {muddled[:4]}) -- shared slab or encoder state is "
            "leaking between planes"
        )
    finally:
        opened.close()
