"""One replacement moves a position's whole published timeline, and we know it.

Sometimes a moment has to be imaged again -- the focus was wrong, the laser
was off. The manifest's rule for that case is deliberate: one replacement
commit advances EVERY already-published moment of that position to the new
generation, because a position's store is copied whole before the one moment
is rewritten, and no moment may ever mix files from two generations.

The rule is correct, and it has a price that is easy to forget until an
overnight timelapse pays it: the change from that single commit is not the
size of one landing. It is one position times every moment it has published
-- on a five-hundred-moment run, one retake dirties five hundred moments'
worth of ground at once, a sudden spike in an otherwise steady stream of
small, cheap landings. The viewer serves only the first moment today, so the
spike costs little yet; the day the served picture grows its time axis, this
number multiplies the landing budget.

So this file pins the rule and its price while both are cheap to state:
exactly the published moments advance (none missed, none invented, no
neighbour touched, withheld moments still withheld), the spike is exactly
their count, a reader already drawing the old generation is still reading
published truth, and the incremental fold agrees with a cold replay.
"""

from zmart_live.coordinator import LivePublisher
from zmart_live.gateway import _LiveRun
from zmart_live.model import GridCell
from zmart_live.profiles import plan_the_writing

from .test_coordinator import FRAME, some_specimen


def a_timelapse_run(folder, *, timepoints):
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    return LivePublisher(
        folder,
        profile,
        run_id="replacement-spike-run",
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
        timepoints=timepoints,
    )


def test_a_replacement_advances_exactly_the_published_moments(tmp_path):
    run = a_timelapse_run(tmp_path, timepoints=6)
    # posA publishes four of its six moments; two stay unwritten. posB is
    # the bystander whose ground must not move at all.
    published_moments = (0, 1, 2, 3)
    for moment in published_moments:
        run.write_and_publish("posA", some_specimen(1700 + moment),
                              timepoint=moment)
    run.write_and_publish("posB", some_specimen(900))

    # The reader that has been following along, and its view of the world
    # the instant before the replacement.
    following = _LiveRun(run.folder)
    before = set(following._published_units())

    run.replace_a_position("posA", some_specimen(3100), timepoint=1)

    after = set(following._published_units())

    # The spike, pinned as a set rather than a count: what changed is
    # EXACTLY every published moment of posA at the new generation --
    # nothing missed, nothing invented, and nothing of posB's. Its size is
    # the number of published moments, which is the O(moments) cost a long
    # timelapse pays for one retake.
    expected_spike = {("posA", moment, 1) for moment in published_moments}
    assert after - before == expected_spike, (
        f"one replacement changed {sorted(after - before)!r} where exactly "
        f"{sorted(expected_spike)!r} was owed: every already-published "
        "moment of the replaced position advances to the new generation, "
        "and nothing else in the run moves"
    )
    assert len(after - before) == len(published_moments)

    # The moments that were never published stay withheld -- a replacement
    # copies the whole store, fill-value room for future moments included,
    # and copied room must not become published ground.
    for moment in (4, 5):
        assert not any(unit[0] == "posA" and unit[1] == moment
                       for unit in after), (
            f"moment {moment} of posA was never published, but the "
            "replacement made it visible -- copied fill-value room has "
            "become published ground"
        )

    # A reader already drawing the old generation is mid-flight on ground
    # that WAS honestly published; the old units remain answerable rather
    # than being torn out from under it.
    for moment in published_moments:
        assert ("posA", moment, 0) in after, (
            f"generation 0 of posA moment {moment} vanished from the "
            "published set -- a reader mid-flight on the old generation "
            "has had honest ground torn out from under it"
        )

    # And a reader who arrives cold -- replaying the whole history from
    # nothing -- must see exactly what the follower folded incrementally.
    # Two readings of one record that disagree would be two truths.
    cold = set(_LiveRun(run.folder)._published_units())
    assert cold == after, (
        "a cold replay of the history disagrees with the incremental fold "
        "-- the same record is telling two different stories"
    )
