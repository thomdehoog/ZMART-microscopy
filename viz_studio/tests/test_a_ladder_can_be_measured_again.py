"""Runs already written can be measured again without writing them again.

Writing the ladder is nearly all of what it costs. Out to ten thousand positions
it is about fifty minutes of writing against five of measuring, at roughly a sixth
of a second a position — so a measurement repeated to see how wide the spread is,
or repeated because the browser was launched differently, pays fifty minutes for
nothing each time.

That matters more than saving an afternoon. The one thing a frame measurement on a
contended machine needs is repeats, and this project has already been caught once
by a threshold set from a single reading. Repeats have to be cheap or they do not
happen.

So a ladder left on disk by ``--keep`` can be handed back with ``--from``, and only
the sizes missing from it are written. What is on disk is found by looking, rather
than by trusting a list written down beside it, because a run interrupted halfway
leaves a folder that exists and holds nothing usable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from measure_a_run_of_positions import runs_already_written  # noqa: E402


def _a_run_that_was_written(folder: Path, count: int,
                            positions: int | None = None) -> Path:
    """The shape a finished step leaves behind, or an unfinished one.

    ``positions`` writes fewer than the name promises, which is what a ladder
    interrupted partway through a step actually looks like on disk.
    """
    picture = folder / f"n{count}" / "experiment.ome.zarr"
    inside = picture / "positions"
    inside.mkdir(parents=True)
    (picture / "zarr.json").write_text(json.dumps({"node_type": "group"}))
    (inside / "zarr.json").write_text(json.dumps({"node_type": "group"}))
    for index in range(count if positions is None else positions):
        (inside / f"experiment_pos{index:05d}.ome.zarr").mkdir()
    return picture


def test_nothing_on_disk_is_no_runs(tmp_path):
    assert runs_already_written(tmp_path) == {}


def test_a_folder_that_does_not_exist_is_no_runs(tmp_path):
    """Asked for a ladder that was never kept, say so by finding none of it."""
    assert runs_already_written(tmp_path / "never-written") == {}


def test_each_finished_step_is_found_by_the_count_in_its_name(tmp_path):
    for count in (1, 100, 400):
        _a_run_that_was_written(tmp_path, count)
    found = runs_already_written(tmp_path)
    assert sorted(found) == [1, 100, 400]
    assert found[100] == tmp_path / "n100" / "experiment.ome.zarr"


def test_a_step_interrupted_before_it_had_a_picture_is_not_offered(tmp_path):
    """A folder that exists and holds nothing usable is worse than no folder.

    Reusing one would measure an empty picture and report a splendid frame rate
    over nothing at all, which is the exact fault this suite keeps meeting.
    """
    _a_run_that_was_written(tmp_path, 100)
    (tmp_path / "n400" / "experiment.ome.zarr").mkdir(parents=True)
    assert sorted(runs_already_written(tmp_path)) == [100]


def test_a_step_that_stopped_partway_through_its_positions_is_not_offered(tmp_path):
    """The dangerous one: a picture that opens, holding fewer positions than it says.

    A step killed halfway has its description written — that happens first — and
    only some of its positions. Offering it measures four hundred positions and
    labels the row a thousand, which is a wrong number rather than a missing one,
    and nothing downstream could tell.
    """
    _a_run_that_was_written(tmp_path, 100)
    _a_run_that_was_written(tmp_path, 400, positions=390)
    assert sorted(runs_already_written(tmp_path)) == [100]


def test_more_positions_than_the_name_promises_is_also_refused(tmp_path):
    """Not a case that should arise, and it means the folder is not what we think."""
    _a_run_that_was_written(tmp_path, 400, positions=401)
    assert runs_already_written(tmp_path) == {}


def test_folders_that_are_not_steps_are_ignored(tmp_path):
    _a_run_that_was_written(tmp_path, 400)
    (tmp_path / "notes").mkdir()
    (tmp_path / "nXYZ").mkdir()
    (tmp_path / "n").mkdir()
    assert sorted(runs_already_written(tmp_path)) == [400]
