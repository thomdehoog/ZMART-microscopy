"""The sealed profile declares how many moments a run keeps room for.

Until this change, the timepoint room lived only in a writer constructor
argument and, once pixels existed, in the arrays — so nothing could say
"this is a timelapse" before the first position landed, and the viewer's
refusal to truncate time could not fire on an empty run. The c-and-t
plan orders the room into the profile, following the channels precedent
exactly: the profile is the declaration, and a writer argument that
disagrees with it is refused rather than quietly winning.

The migration rule is byte-level and deliberate: a profile keeping room
for one moment writes no ``timepoints`` field at all, so every profile
sealed before this change keeps its exact stored form and therefore its
fingerprint — a fingerprint that moved would orphan every run already on
disk, whose profile_id ends in the fingerprint of its own contents.
"""

from __future__ import annotations

import pytest

from zmart_live.identity import fingerprint_of_a_profile
from zmart_live.model import AcquisitionProfile, GridCell, ZmartLiveError
from zmart_live.profiles import plan_the_writing

FRAME = 384  # the smallest frame the geometry planner accepts


def test_plan_the_writing_carries_the_room_into_the_profile():
    profile, _ = plan_the_writing("overview", frame=FRAME, timepoints=5)
    assert profile.timepoints == 5


def test_one_moment_is_the_default_and_writes_no_field():
    """Absent means one moment — that is the whole migration.

    Every profile sealed before this change lacks the field; loading it
    must mean what it always meant. And a flat profile sealed today must
    serialize exactly as it did yesterday, or its fingerprint moves and
    every stored run's profile name stops matching its contents.
    """
    flat, _ = plan_the_writing("overview", frame=FRAME)
    assert flat.timepoints == 1
    assert "timepoints" not in flat.to_json()
    assert AcquisitionProfile.from_json(flat.to_json()).timepoints == 1

    deep, _ = plan_the_writing("overview", frame=FRAME, timepoints=3)
    assert deep.to_json()["timepoints"] == 3
    assert AcquisitionProfile.from_json(deep.to_json()).timepoints == 3


def test_the_room_is_part_of_the_fingerprint():
    """Two profiles differing only in their room are different profiles."""
    flat, _ = plan_the_writing("overview", frame=FRAME)
    deep, _ = plan_the_writing("overview", frame=FRAME, timepoints=3)
    assert fingerprint_of_a_profile(flat) != fingerprint_of_a_profile(deep)


def test_the_writer_takes_the_room_from_the_profile(tmp_path):
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, timepoints=3)
    run = LivePublisher(tmp_path / "run", profile, run_id="room-from-profile",
                        cells={GridCell(0, 0): "p00"})
    assert run.timepoints == 3


def test_a_writer_argument_that_disagrees_is_refused(tmp_path):
    """The channels rule, applied to time: the profile cannot be overridden."""
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, timepoints=3)
    with pytest.raises(ZmartLiveError, match="profile"):
        LivePublisher(tmp_path / "run", profile, run_id="room-disagrees",
                      cells={GridCell(0, 0): "p00"}, timepoints=2)


def test_a_profile_refuses_a_room_with_no_moments():
    with pytest.raises(ZmartLiveError):
        plan_the_writing("overview", frame=FRAME, timepoints=0)
