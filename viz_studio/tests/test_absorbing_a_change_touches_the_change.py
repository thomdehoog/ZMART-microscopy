"""One landing must cost the same on a small survey and a large one.

This gate pins the promise the whole derive economy was built for: absorbing
one position's landing costs the change, not the survey. Tiles are carried
over as objects, geometry is cached per layout revision, and the bake reuses
its scaffolding -- so the steady per-landing derive time must not follow the
survey's size. Measured when this test was written: 26.7 ms at 64 positions
and 26.5 ms at 1,024, flat within noise, with the bake excluded.

A finding worth keeping is folded into this file's history. The snapshot's
bookkeeping (``_compose_the_snapshot``) genuinely walks the whole survey on
every derive -- the published fold, the ``drawing`` and ``tiles``
dictionaries and the ordered tile list are rebuilt in full for a
one-position change, and ``accounting["last_snapshot_swept"]`` counts it
happening. This test's first draft assumed that walk must therefore be the
next scaling cost, extrapolated it to ~150 ms per landing at ten thousand
positions, and stood ready to demand a risky copy-on-write rework of the
immutable-snapshot design. The measurement said no: the walk is ordinary
dictionary work, well under a millisecond at a thousand positions, and the
flat timings above are the proof. The counter stays because it is the right
diagnostic THE DAY a much larger survey changes that verdict; no red gate
demands a fix the numbers do not justify.

The bake's own per-landing costs have their own gate
(test_a_landing_costs_the_change_not_the_survey); this one uses UNBAKED
pictures so file work cannot muddy the bookkeeping signal.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

import measure_a_governed_run_at_scale as harness  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from governed import GovernedRun  # noqa: E402


# The scaling comparison's two sizes. Sixteen times the positions: a
# bookkeeping cost that followed the survey would show as many times the
# steady per-landing time; a cost that follows the change stays flat.
SMALL_ACROSS = 8
LARGE_ACROSS = 32

# The bound of three is the generous middle ground: far above timer noise
# on a busy shared machine, far below any per-survey growth -- a term that
# walked the survey would put sixteen times the positions' worth of work on
# every landing, and the measured baseline is flat at 1.0x.
STEADY_RATIO_ALLOWED = 3.0

# How many steady-state landings to measure per size. Medians over five are
# steady enough to survive a noisy neighbour without making the fixture
# writes the longest part of the test.
STEADY_LANDINGS = 5


def _steady_landings(tmp_path: Path, across: int) -> tuple[list[float],
                                                           list[int], int]:
    """Per-landing derive times and sweep counts on one unbaked survey.

    Returns the steady-state derive milliseconds, the matching sweep
    counters, and the survey's position count. The first landing after the
    cold open is absorbed without being measured, because first landings
    legitimately build session state that later landings must not rebuild.
    """
    harness.FIXTURES = tmp_path / f"survey-{across}"
    run, order = harness.the_run(across)
    landings = order[-(STEADY_LANDINGS + 1):]
    for position_id in order[:-(STEADY_LANDINGS + 1)]:
        harness.fast_publish(run, position_id)
    shown = run.folder / "views" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live",
                                       bake=False)
    opened = GovernedRun(run.folder, store=store)
    try:
        opened.composer()
        harness.fast_publish(run, landings[0])
        opened.composer()
        timings: list[float] = []
        sweeps: list[int] = []
        for position_id in landings[1:]:
            harness.fast_publish(run, position_id)
            began = time.perf_counter()
            opened.composer()
            timings.append((time.perf_counter() - began) * 1000)
            sweeps.append(opened.accounting["last_snapshot_swept"])
        return timings, sweeps, len(order)
    finally:
        opened.close()


def test_a_landing_costs_the_same_on_a_small_and_a_large_survey(tmp_path):
    """Steady per-landing derive time must not follow the survey's size."""
    small_ms, small_sweeps, small_n = _steady_landings(tmp_path, SMALL_ACROSS)
    large_ms, large_sweeps, large_n = _steady_landings(tmp_path, LARGE_ACROSS)
    small = statistics.median(small_ms)
    large = statistics.median(large_ms)
    print(f"STEADY LANDING: {small_n} positions {small:.2f} ms "
          f"(swept {max(small_sweeps)}), {large_n} positions {large:.2f} ms "
          f"(swept {max(large_sweeps)}), ratio "
          f"{large / max(small, 1e-9):.1f}x", flush=True)
    assert large <= small * STEADY_RATIO_ALLOWED + 2.0, (
        f"one landing derives in {small:.2f} ms on {small_n} positions but "
        f"{large:.2f} ms on {large_n} positions -- the identical change, "
        "with no bake involved, so the difference is per-survey work being "
        "done per landing. The sweep counters above say how many position "
        "entries the snapshot bookkeeping handled; if they follow the "
        "survey AND the time now does too, the walk that was measured "
        "harmless at a thousand positions has started to bite, and "
        "carrying the snapshot's dictionaries forward copy-on-write is the "
        "known (and load-bearing, so far deliberately unbuilt) candidate."
    )
