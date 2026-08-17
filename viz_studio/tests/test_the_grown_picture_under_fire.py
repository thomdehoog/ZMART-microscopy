"""Trying to break the grown picture, on purpose.

The gates elsewhere confirm the grown serving does what it should. These
try to make it do what it should NOT: tear a frame under a mid-serving
retake, leak a withdrawn moment after a rollback, muddle frames under
concurrent fire across all three axes, accept a malformed address, or
quietly explode in cost when the declared room is large and mostly
unwritten. Every fixture is small; what is large here is the hostility.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

from check import decode  # noqa: E402
from governed import GovernedRun  # noqa: E402

FRAME = 384
PLANES = 3
COLOURS = 2


def the_stamp(moment: int, channel: int, plane: int) -> int:
    return 1000 * moment + 100 * channel + plane + 7


def a_stack(moment: int, *, retaken: bool = False) -> np.ndarray:
    stack = np.empty((COLOURS, PLANES, FRAME, FRAME), dtype="uint16")
    for channel in range(COLOURS):
        for plane in range(PLANES):
            stack[channel, plane] = (the_stamp(moment, channel, plane)
                                     + (50000 if retaken else 0))
    return stack


def a_grown_run(folder, *, timepoints=3):
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=PLANES,
                                  timepoints=timepoints,
                                  channels=("green", "red"))
    return LivePublisher(folder, profile, run_id="under-fire",
                         cells={GridCell(0, 0): "p00"})


def test_a_retake_mid_fire_never_shows_a_torn_frame(tmp_path):
    """Readers hammer every frame while a moment is retaken.

    Every answer must decode to EXACTLY the old stamp or EXACTLY the new
    one — a mixture inside one piece would mean a reader caught the
    replacement halfway, which the snapshot rule exists to make
    impossible. Afterwards, the set semantics: every published moment of
    the retaken position serves the new generation's pixels.
    """
    run = a_grown_run(tmp_path)
    for moment in range(2):
        run.write_and_publish("p00", a_stack(moment), timepoint=moment)

    opened = GovernedRun(run.folder)
    torn: list[str] = []
    try:
        composerless = opened.composer()  # warm the first snapshot
        piece = composerless.piece

        def hammer(_):
            for moment in range(2):
                for channel in range(COLOURS):
                    for plane in range(PLANES):
                        composer = opened.composer()
                        body = composer.bytes_for(0, plane, 0, 0,
                                                  moment, channel)
                        if body is None:
                            continue
                        decoded = decode(body, piece,
                                         str(composer.mosaic.dtype),
                                         composer.mosaic.axes)
                        seen = set(np.unique(decoded[:FRAME, :FRAME]))
                        old = {the_stamp(moment, channel, plane)}
                        new = {the_stamp(moment, channel, plane) + 50000}
                        if seen != old and seen != new:
                            torn.append(
                                f"(t={moment}, c={channel}, z={plane}) "
                                f"decoded {sorted(seen)[:4]}")
            return True

        with ThreadPoolExecutor(max_workers=6) as pool:
            readers = [pool.submit(hammer, wave) for wave in range(3)]
            run.replace_a_position("p00", a_stack(0, retaken=True),
                                   timepoint=0)
            assert all(reader.result() for reader in readers)
        assert not torn, f"{len(torn)} torn frames under fire: {torn[:3]}"

        # The set semantics, checked frame by frame: EVERY published moment
        # advanced to the new generation, whose carried-over pixels for
        # moment 1 are the old stamps (the copy), and whose moment 0 holds
        # the retake.
        fresh = opened.composer()
        for channel in range(COLOURS):
            for plane in range(PLANES):
                body = fresh.bytes_for(0, plane, 0, 0, 0, channel)
                decoded = decode(body, piece, str(fresh.mosaic.dtype),
                                 fresh.mosaic.axes)
                assert set(np.unique(decoded[:FRAME, :FRAME])) == {
                    the_stamp(0, channel, plane) + 50000}
                body = fresh.bytes_for(0, plane, 0, 0, 1, channel)
                decoded = decode(body, piece, str(fresh.mosaic.dtype),
                                 fresh.mosaic.axes)
                assert set(np.unique(decoded[:FRAME, :FRAME])) == {
                    the_stamp(1, channel, plane)}
    finally:
        opened.close()


def test_concurrent_fire_across_every_axis_stays_frame_pure(tmp_path):
    """Every (t, c, z) piece asked at once, repeatedly, from many threads.

    The frame caches share state across requests; the one wrong outcome is
    an answer wearing another frame's pixels. Byte-compare each concurrent
    answer against the quiet sequential truth.
    """
    run = a_grown_run(tmp_path)
    for moment in range(3):
        run.write_and_publish("p00", a_stack(moment), timepoint=moment)

    opened = GovernedRun(run.folder)
    try:
        composer = opened.composer()
        addresses = [(0, plane, 0, 0, moment, channel)
                     for moment in range(3)
                     for channel in range(COLOURS)
                     for plane in range(PLANES)]
        quiet = {address: composer.bytes_for(*address)
                 for address in addresses}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for _ in range(3):
                answers = list(pool.map(
                    lambda address: composer.bytes_for(*address),
                    addresses * 2))
                for address, body in zip(addresses * 2, answers):
                    assert body == quiet[address], (
                        f"{address} answered differently under concurrency"
                    )
    finally:
        opened.close()


def test_malformed_and_boundary_addresses_answer_absent_never_crash(tmp_path):
    """The wire door under abuse: junk in, ``None`` out, no exceptions."""
    import served

    run = a_grown_run(tmp_path)
    run.write_and_publish("p00", a_stack(0), timepoint=0)
    from declare import declare_a_governed_picture

    store = declare_a_governed_picture(run.folder / "views" / "shown",
                                       run.folder, name="live")
    hostile = [
        "0/c/0/0/0/0",            # six parts: neither flat nor grown
        "0/c/0/0/0/0/0/0",        # eight parts
        "0/c/-1/0/0/0/0",         # negative moment
        "0/c/999/0/0/0/0",        # far past the room
        "0/c/0/99/0/0/0",         # far past the channels
        "0/c/0/0/999999/0/0",     # far past the planes
        "0/c/a/0/0/0/0",          # not a number
        "0/c//0/0/0/0",           # the doubled slash
        "99/c/0/0/0/0/0",         # no such level
        "0/c/0/0/0/0/../0",       # a path escape dressed as a piece
    ]
    for inside in hostile:
        assert served.the_bytes_behind(store, inside) is None, (
            f"the hostile address {inside!r} was answered"
        )


def test_a_large_mostly_unwritten_room_costs_almost_nothing(tmp_path):
    """Declared 60, written 2: the empty tail must be free.

    The generous-ceiling rule is only honest if unimaged room costs
    nothing to hold and nothing to skip. Absent frames must answer fast
    (no store is ever opened for them) and build no slabs.
    """
    import time

    run = a_grown_run(tmp_path, timepoints=60)
    for moment in range(2):
        run.write_and_publish("p00", a_stack(moment), timepoint=moment)

    opened = GovernedRun(run.folder)
    try:
        composer = opened.composer()
        composer.bytes_for(0, 0, 0, 0, 0, 0)  # pay the cold costs once
        built_before = composer.costs["slabs_built"]
        began = time.perf_counter()
        for moment in range(2, 60):
            for channel in range(COLOURS):
                assert composer.bytes_for(0, 0, 0, 0, moment, channel) is None
        spent = time.perf_counter() - began
        assert spent < 2.0, (
            f"answering 116 absent frames took {spent:.2f}s -- the unwritten "
            "tail is being paid for"
        )
        # Building empty slabs for absent frames is not free -- they are
        # zeros the size of a piece stack. A handful is tolerable; one per
        # absent frame means the ceiling has a per-frame cost.
        built = composer.costs["slabs_built"] - built_before
        assert built <= 4, (
            f"{built} slabs were built for ground that is entirely absent"
        )
    finally:
        opened.close()
