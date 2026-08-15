"""The bake patch's semantics guards -- and the record of a reverted cure.

These tests were built as the instrument for paste-over: patching a dirty
coarse piece by re-laying only the changed ground over the decoded chunk,
instead of recomposing the piece from every tile beneath it. The cure was
implemented, its cost gate went green (tile reads per landing fell from 143
to 4), its overlap proof and pixel-equality oracle both held -- and the
survey ladder then showed every landing had become SLOWER, three times
slower on a small survey. The cure was reverted on that measurement, and
the cost gate -- a proxy the wall clock had contradicted -- was removed
with it. The compose anatomy built afterwards corrected the post-mortem
too: the dirty piece's slab is rebuilt every landing (zero warm hits), so
tile reading really is most of the compose cost and the read-cutting was
aimed at real money -- the chunk-file paste lost on ~50 ms of overhead of
its own that was never attributed. The standing instruction: a second
attempt patches the INHERITED SLAB in memory instead of chunk files, and
begins with a red gate denominated in bake_compose_read milliseconds,
plus a phase split of its own path.

What stands are the two guards that were never about the cure's speed,
only its honesty, and they hold for full recomposition just as well:

The OVERLAP PROOF: microscope tiles deliberately overlap their neighbours
(64 pixels in these fixtures), the composer lays the LATER-committed tile
on top, and a replacement does not move a position up the pile. Whatever
patches the bake must keep a replaced tile beneath its later neighbours in
their shared band, and this test catches any patcher that does not.

The EQUALITY ORACLE: after landings and a replacement, every baked chunk
file of the coarsest composed level must decode pixel-identical to a
fresh, full composition of the same piece -- the files on disk and the
composer must never learn to disagree, or the picture would change across
a session restart.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

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

    shown = run.folder / "views" / "shown"
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


def test_the_baked_files_equal_a_fresh_composition(tmp_path):
    """Every baked chunk must be pixel-identical to a fresh composition.

    The overlap proof above checks the two points where a clever patcher is
    most likely to go wrong; this oracle checks everywhere. After landings
    and a replacement have both been patched, every chunk file of the
    coarsest composed level is decoded and compared against the composer's
    own freshly composed answer for the same piece. Exact equality: the
    files and the composer describe the same manifest state, so any
    difference at all is a bug, not a tolerance -- it would mean the
    picture changes across a session restart.
    """
    from numcodecs import Zstd

    harness.FIXTURES = tmp_path
    run, order = harness.the_run(6)
    landings = order[-2:]
    for position_id in order[:-2]:
        harness.fast_publish(run, position_id)
    shown = run.folder / "views" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live",
                                       bake=True)
    opened = GovernedRun(run.folder, store=store)
    try:
        opened.composer()
        for position_id in landings:
            harness.fast_publish(run, position_id)
            opened.composer()
        early, _later = _grid_neighbours(run, order)
        run.replace_a_position(early, np.full(
            (1, harness.FRAME, harness.FRAME), DIM, dtype="uint16"))
        held = opened.composer()
        baked = tuple(json.loads((store / "zarr.json").read_text(
            encoding="utf-8"))["attributes"]["zmart"]["baked"])
        level = max(one for one in baked if one < held.mosaic.levels)
        deep, rows, columns = held.grid(level)
        unpacking = Zstd()
        compared = 0
        for plane in range(deep):
            for row in range(rows):
                for column in range(columns):
                    fresh = held.bytes_for(level, plane, row, column)
                    file = (Path(store) / str(level) / "c" / str(plane)
                            / str(row) / str(column))
                    if fresh is None:
                        assert not file.is_file(), (
                            f"piece {level}/{plane}/{row}/{column} is "
                            "all-fill by composition but a baked file "
                            "exists for it"
                        )
                        continue
                    assert file.is_file(), (
                        f"piece {level}/{plane}/{row}/{column} holds "
                        "specimen by composition but no baked file exists"
                    )
                    on_disk = np.frombuffer(
                        unpacking.decode(file.read_bytes()), dtype="<u2")
                    composed = np.frombuffer(
                        unpacking.decode(fresh), dtype="<u2")
                    differing = int((on_disk != composed).sum())
                    assert differing == 0, (
                        f"piece {level}/{plane}/{row}/{column} differs from "
                        f"a full recomposition at {differing} of "
                        f"{composed.size} pixels after paste-over patching "
                        "-- the pasted file no longer says what composing "
                        "says, and the serving door would answer "
                        "differently before and after a session restart"
                    )
                    compared += 1
        assert compared > 0, (
            "no piece was compared at all -- the level under test holds "
            "nothing, and this oracle proved nothing"
        )
    finally:
        opened.close()
