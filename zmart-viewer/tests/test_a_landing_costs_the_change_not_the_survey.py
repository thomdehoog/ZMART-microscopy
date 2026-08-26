"""Landing one position must cost the change, not the size of the survey.

The whole derive economy of a governed picture is built on this promise: a
position landing re-reads nothing per-survey (tiles are carried over as
objects, geometry is cached per layout revision), so an operator's
landing-to-visible wait is the same on position 60 of 64 as on position
1,000 of 1,024. Measured with the accounting this module keeps, that promise
held for the derive itself -- and was quietly broken by the bake patcher
beneath it. Every landing rebuilt the patcher's own scaffolding from
scratch: for each extended pyramid level it tore down and recreated a
staging folder, copied the level's metadata, and re-opened zarr arrays,
all under the bake lock that page requests wait on. On an 8x8 survey a
landing derived in about 20 ms; on a 32x32 the very same one-position
change took about 150 ms, most of it this rebuilding -- profiled, not
guessed, in the session that wrote this test.

None of that scaffolding changes between landings. The declared store's
geometry is fixed at declaration (re-declaring serves a whole fresh run),
and the staging folder is emptied by the patch itself, so everything can be
built once per opened run and reused. This test pins that promise with the
run's own accounting, which is deterministic and machine-independent where
a wall-clock bound would flake: after the first landing has built the
scaffolding, every later landing must report ZERO arrays opened and ZERO
staging folders built. When this test was first written it was red against
the rebuild-per-landing behaviour -- several arrays and stagings per
landing, every landing -- and the counters it reads exist precisely so
that this cost can never creep back unnoticed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "app" / "picture"))

import measure_a_governed_run_at_scale as harness  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from governed import GovernedRun  # noqa: E402

# Wide enough that the picture has extended pyramid levels to keep true --
# they are where the per-landing rebuilding lived -- and small enough that
# writing the fixture stays a matter of seconds. Sixteen across is the
# smallest survey whose coarsest profile level is still wider than one
# piece, so at least one extended level must exist and be re-halved per
# landing. This matters more than it looks: the first draft of this test
# used a twelve-wide survey, which has NO extended level, so the machinery
# under test never ran and the test passed against the very behaviour it
# was written to catch. The precondition below makes that blindness loud
# instead of silent.
SURVEY_ACROSS = 16

# How many steady-state landings to check. One would do; a few make sure the
# zero is a steady state rather than an accident of the first iteration.
STEADY_LANDINGS = 3


def test_a_landing_costs_the_change_not_the_survey(tmp_path):
    """After the first landing, the bake patcher reuses all its scaffolding."""
    harness.FIXTURES = tmp_path
    run, order = harness.the_run(SURVEY_ACROSS)
    landings = order[-(STEADY_LANDINGS + 1):]
    for position_id in order[:-(STEADY_LANDINGS + 1)]:
        harness.fast_publish(run, position_id)

    shown = run.folder / "views" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live",
                                       bake=True)
    opened = GovernedRun(run.folder, store=store)
    try:
        # The cold open, and then one landing that is allowed to build
        # whatever it needs: handles and staging folders have to come into
        # being somewhere, and the first change of a session is where.
        opened.composer()
        harness.fast_publish(run, landings[0])
        opened.composer()

        # The instrument must be able to see before its zeros mean anything:
        # a survey with no extended pyramid level never runs the re-halving
        # machinery at all, and every counter reads zero for the wrong
        # reason. The first landing leaves a staging folder behind exactly
        # when that machinery ran, so its absence means this test is blind,
        # not that the code is frugal.
        assert any(Path(store).glob(".patching-*")), (
            "no extended level was re-halved by the first landing, so the "
            "scaffolding this test watches never came into being -- the "
            "survey is too small for this instrument, and its zeros would "
            "be blindness, not thrift. Grow SURVEY_ACROSS."
        )

        # From here on the survey does not change size, the store does not
        # change shape, and the staging folders are empty again -- so a
        # landing that builds ANY of it anew is doing per-landing work that
        # belongs to the session, and paying for it under the bake lock
        # while page requests wait.
        for number, position_id in enumerate(landings[1:], 1):
            harness.fast_publish(run, position_id)
            opened.composer()
            opened_arrays = opened.accounting["last_bake_arrays_opened"]
            built_stagings = opened.accounting["last_bake_stagings_built"]
            assert opened_arrays == 0 and built_stagings == 0, (
                f"steady-state landing {number} re-opened {opened_arrays} "
                f"zarr arrays and rebuilt {built_stagings} staging folders. "
                "Nothing about the store changed between landings, so this "
                "is scaffolding being rebuilt per landing -- the cost that "
                "made one landing ~7x dearer on a 32x32 survey than on an "
                "8x8, paid under the bake lock while page requests wait. "
                "Whatever a landing needs beyond its own pixels must be "
                "built once per opened run and reused."
            )
    finally:
        opened.close()


def test_a_landing_rehalves_with_pixel_work_not_library_machinery(tmp_path):
    """Re-truing the coarse levels must not pay zarr's dispatcher per landing.

    The zarr library routes every array operation through an internal
    asynchronous dispatcher -- the right design for cloud storage, where many
    slow requests want to be in flight together, and a toll of milliseconds
    per operation when the operation is a tiny local read. A landing's
    re-halve is exactly that: read four small chunk files, average pixels,
    write one small chunk file. Profiled at 32x32, the pixel arithmetic was
    about a millisecond per landing while roughly 100 ms sat in the
    dispatcher's thread handoffs -- machinery, not work, paid under the bake
    lock on every landing.

    The chunk files' encoding is written down in each level's own zarr.json,
    so the patcher can read and write them directly through the same recipe
    -- the courier is skipped, the bytes still say exactly what zarr would
    have said, and test_the_rehalved_level_reads_back_true holds the pixels
    to that. This gate pins the machinery side: a steady-state landing must
    perform ZERO region operations through the zarr array API. An encoding
    this repository did not write falls back to the zarr path -- correct
    everywhere, fast where it matters -- and the fallback announces itself
    on this counter, so a fixture drifting off the direct path turns this
    gate red instead of quietly slowing every landing down.
    """
    harness.FIXTURES = tmp_path
    run, order = harness.the_run(SURVEY_ACROSS)
    landings = order[-(STEADY_LANDINGS + 1):]
    for position_id in order[:-(STEADY_LANDINGS + 1)]:
        harness.fast_publish(run, position_id)

    shown = run.folder / "views" / "shown"
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
            rehalved = opened.accounting["last_bake_pieces_rehalved"]
            # The blindness guard, as in the test above: zeros only mean
            # something if the machinery under test actually ran.
            assert rehalved > 0, (
                "no piece of any extended level was re-halved by this "
                "landing, so the machinery this test watches never ran -- "
                "the survey is too small for this instrument. Grow "
                "SURVEY_ACROSS."
            )
            round_trips = opened.accounting["last_bake_zarr_ops"]
            assert round_trips == 0, (
                f"steady-state landing {number} re-halved {rehalved} pieces "
                f"using {round_trips} region operations through the zarr "
                "array API. Each such operation pays the library's "
                "dispatcher toll -- thread handoffs worth milliseconds per "
                "call, against about one millisecond of actual pixel "
                "arithmetic -- under the bake lock, on every landing. The "
                "chunk encoding is in the level's own zarr.json, so the "
                "patch must read and write the chunk files directly through "
                "that recipe, and leave the array API for encodings this "
                "repository did not write."
            )
    finally:
        opened.close()


def test_the_rehalved_level_reads_back_true(tmp_path):
    """Every extended level equals the 2x2 mean of the level below, exactly.

    The direct re-halving path above writes chunk files through the recipe
    in the level's own zarr.json rather than through the zarr array API, so
    this is the oracle that keeps it honest: after real landings have been
    patched, each extended level is read back with PLAIN zarr -- the same
    reader any other tool would use -- and every pixel must equal the same
    averaging arithmetic applied to the whole level below. Exact equality,
    not approximate: the arithmetic is fixed (average 2x2, round, cast), so
    any difference at all means the direct path and the recipe disagree
    about what the files say. Reading back through zarr is half the point:
    it proves the files are still ordinary zarr to the rest of the world.
    """
    import zarr

    harness.FIXTURES = tmp_path
    run, order = harness.the_run(SURVEY_ACROSS)
    landings = order[-(STEADY_LANDINGS + 1):]
    for position_id in order[:-(STEADY_LANDINGS + 1)]:
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
    finally:
        opened.close()

    rehalved_levels = sorted(
        int(folder.name.split("-")[1])
        for folder in Path(store).glob(".patching-*"))
    assert rehalved_levels, (
        "no extended level was re-halved, so this oracle checked nothing -- "
        "the survey is too small for this instrument. Grow SURVEY_ACROSS."
    )
    import numpy as np

    for level in rehalved_levels:
        below = zarr.open_array(str(Path(store) / str(level - 1)),
                                mode="r")[:]
        served = zarr.open_array(str(Path(store) / str(level)), mode="r")[:]
        deep, height, width = served.shape
        evened = np.pad(below,
                        ((0, 0), (0, 2 * height - below.shape[1]),
                         (0, 2 * width - below.shape[2])), mode="edge")
        expected = (evened.reshape(deep, height, 2, width, 2)
                    .mean(axis=(2, 4)).round().astype(served.dtype))
        differing = int((expected != served).sum())
        assert differing == 0, (
            f"extended level {level} disagrees with the 2x2 mean of level "
            f"{level - 1} at {differing} of {expected.size} pixels after "
            "real landings were patched. The files no longer say what the "
            "arithmetic says, so either the direct chunk path or its "
            "reading of the recipe is wrong -- and every other tool reading "
            "this picture sees the same wrong pixels."
        )
