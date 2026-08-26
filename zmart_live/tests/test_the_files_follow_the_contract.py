"""The acceptance test the contract names, written as a standing gate.

The contract (``zmart-viewer/app/picture/CONTRACT_the_files_the_viewer_needs.md``)
ends with one test that rules everything: *delete views/, hand data/ to a
stranger with a community tool and no ZMART anything, and everything must
work*. This file is that sentence as code, plus the structural promises
around it: an experiment is exactly config/ and acquisitions/, an
acquisition is exactly data/ and views/, the collection declares only
complete current-generation members, no chunk ever spans time or channel,
and nothing in data/ so much as mentions views/.

Every fixture here builds the real structure the contract draws — not an
ad-hoc test folder — so that any drift between what the code writes and
what the contract promises breaks this file first, loudly, before it
confuses anybody at a microscope.
"""

import json
import shutil

import numpy as np
import pytest
import zarr

from zmart_live.coordinator import LivePublisher
from zmart_live.model import GridCell
from zmart_live.profiles import plan_the_writing

FRAME = 1152


def a_specimen(value: int) -> np.ndarray:
    seed = np.random.default_rng(value)
    return seed.integers(200, 4000, (1, FRAME, FRAME)).astype("uint16")


@pytest.fixture
def experiment(tmp_path):
    """One experiment folder, shaped exactly as the contract draws it.

    The controller's pen writes config/ (the canvas and its diary) before
    anything runs; then two acquisitions run in acquisitions/, each with its
    own publisher. The overview acquisition also retakes one position, so the
    generation machinery is exercised, not just the happy path.
    """
    folder = tmp_path / "experiment-2026-08-15"
    config = folder / "config"
    config.mkdir(parents=True)
    (config / "canvas.json").write_text(json.dumps({
        "units": "micrometer", "origin": [0.0, 0.0], "orientation": "yx",
    }, indent=2))
    (config / "record.json").write_text(json.dumps({
        "acquisitions": ["overview", "targets"],
    }, indent=2))

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    overview = LivePublisher(
        folder / "acquisitions" / "overview", profile, run_id="contract-overview",
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
        # The contract below is drawn for a run whose linked view is kept true
        # as it goes, which is no longer the default -- see the gate under
        # this one for the folder a DEFAULT run shows mid-flight. Both are
        # written down because both now happen, and a contract that described
        # only one of them would mislead whoever wrote to it.
        linked_view="per_publish",
    )
    overview.write_and_publish("posA", a_specimen(1))
    overview.write_and_publish("posB", a_specimen(2))
    overview.replace_a_position("posA", a_specimen(3), timepoint=0)

    targets = LivePublisher(
        folder / "acquisitions" / "targets", profile, run_id="contract-targets",
        cells={GridCell(0, 0): "cell042"},
    )
    targets.write_and_publish("cell042", a_specimen(4))
    return folder


def names_inside(folder):
    return sorted(child.name for child in folder.iterdir())


def test_the_experiment_is_exactly_config_and_acquisitions(experiment):
    assert names_inside(experiment) == ["acquisitions", "config"], (
        "the experiment's top level is two folders with one meaning each: "
        "config/ explains the world, acquisitions/ holds what happened in it"
    )
    assert names_inside(experiment / "acquisitions") == ["overview", "targets"]


def test_an_acquisition_is_exactly_data_and_views(experiment):
    for name in ("overview", "targets"):
        acquisition = experiment / "acquisitions" / name
        assert names_inside(acquisition) == ["data", "views"], (
            f"acquisition {name!r} must hold exactly the microscope's pen "
            "(data/) and ours (views/), nothing else"
        )
        assert names_inside(acquisition / "data") == ["survey.ome.zarr"], (
            "data/ holds the one collection zarr and nothing beside it"
        )


def test_the_views_folder_holds_exactly_the_view_and_its_metadata(experiment):
    live = experiment / "acquisitions" / "overview" / "views" / "live"
    assert names_inside(live.parent) == ["live"]
    assert names_inside(live) == ["live.ome.zarr", "metadata"]
    # The metadata folder is the contract's minimum and nothing more: what is
    # signed, the history, where things sit, how they are written, the route
    # map, and the writer's lock. A file appearing here uninvited is a new
    # obligation on every future reader, so the list is exact.
    assert names_inside(live / "metadata") == [
        "events.jsonl", "links.json", "locations", "locations.json",
        "profiles", "publication.lock", "signed.json",
    ]


def test_a_run_that_defers_its_view_has_none_to_show_until_it_finishes(tmp_path):
    """The same folder for a run whose view is written at the end.

    A run asked to defer its view keeps all of its bookkeeping true as it
    goes, and simply has not written the view beside it yet. Nothing is
    missing -- what a viewer draws mid-run is the governed picture, on its
    own route -- but a reader who went looking for plain files would find
    none until the run finishes, which is the whole of what was traded for a
    publish that does not slow down as the survey grows.
    """
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    run = LivePublisher(
        tmp_path / "run", profile, run_id="contract-default",
        cells={GridCell(0, 0): "posA"}, linked_view="at_run_end",
    )
    run.write_and_publish("posA", a_specimen(1))

    live = tmp_path / "run" / "views" / "live"
    assert names_inside(live) == ["metadata"], (
        "a deferring run writes its view at the end, so mid-flight the view "
        f"folder holds its bookkeeping and nothing else; saw {names_inside(live)}")
    assert names_inside(live / "metadata") == [
        "events.jsonl", "locations", "locations.json",
        "profiles", "publication.lock", "signed.json",
    ], "everything the contract asks for except the route map, which the view takes with it"

    run.finish_the_run()
    assert names_inside(live) == ["live.ome.zarr", "metadata"], (
        "and the run ends with the view the contract draws")
    assert "links.json" in names_inside(live / "metadata")


def test_only_complete_current_generations_are_declared(experiment):
    collection = experiment / "acquisitions" / "overview" / "data" / "survey.ome.zarr"
    declared = json.loads((collection / "zarr.json").read_text())
    members = declared["attributes"]["zmart"]["members"]
    assert members == ["posA.generation-1", "posB"], (
        "membership is declaration, not presence: the retaken position is "
        "declared at its current generation only, the bystander at its plain "
        "name, and nothing else"
    )
    # The superseded generation stays on disk -- a reader mid-flight keeps
    # honest ground -- but it is not offered to the community.
    assert (collection / "posA").is_dir()
    assert "posA" not in members


def test_each_member_declares_its_written_moments(tmp_path):
    """The declaration carries each member's complete moment count.

    The contract makes one small file both the community's membership
    metadata and the arrival signal a watcher polls: a new position
    appears in the member list, and a new timepoint moves that member's
    declared moment count, riding beside the list. The count is the
    contiguous complete prefix from moment zero — a reader iterating
    t = 0 .. count-1 always finds complete frames, and a gap in the
    record simply stops the count, never overclaims across it.
    """
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1,
                                  timepoints=4)
    run = LivePublisher(
        tmp_path / "acquisitions" / "timelapse", profile,
        run_id="contract-moments",
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
    )
    collection = run.collection

    def declared_moments():
        described = json.loads((collection / "zarr.json").read_text())
        return described["attributes"]["zmart"]["moments"]

    run.write_and_publish("posA", a_specimen(1), timepoint=0)
    assert declared_moments() == {"posA": 1}

    run.write_and_publish("posA", a_specimen(2), timepoint=1)
    assert declared_moments() == {"posA": 2}

    # posB arrives, then skips moment 1 and lands moment 2: the record
    # holds the gap honestly, and the declared count stops before it.
    run.write_and_publish("posB", a_specimen(3), timepoint=0)
    run.write_and_publish("posB", a_specimen(4), timepoint=2)
    assert declared_moments() == {"posA": 2, "posB": 1}

    # A retake advances every published moment (the record's set
    # semantics), so the member is renamed to its new generation and its
    # moment count comes with it.
    run.replace_a_position("posA", a_specimen(5), timepoint=0)
    assert declared_moments() == {"posA.generation-1": 2, "posB": 1}


def test_a_stranger_with_plain_zarr_can_read_everything(experiment):
    """The heart of the acceptance test, before views/ is even touched."""
    collection = experiment / "acquisitions" / "overview" / "data" / "survey.ome.zarr"
    declared = json.loads((collection / "zarr.json").read_text())
    for member in declared["attributes"]["zmart"]["members"]:
        image = zarr.open_group(collection / member, mode="r")
        multiscales = image.attrs["ome"]["multiscales"][0]
        assert [axis["name"] for axis in multiscales["axes"]] == ["t", "c", "z", "y", "x"], (
            "five axes in canonical order, time and channel first, even while "
            "they are singletons -- so the day either grows, nothing moves"
        )
        level0 = zarr.open_array(collection / member / "0", mode="r")
        assert level0.shape[3:] == (FRAME, FRAME)
        assert int(level0[0, 0, 0, 10, 10]) >= 0  # the pixels actually read


def test_no_chunk_ever_spans_time_or_channel(experiment):
    """One (t, c) frame is one write-once unit on disk.

    Acquisition runs go per channel and per time. Keeping every chunk to a
    single moment and a single channel means a new moment or a new channel
    only ever ADDS files -- nothing already written is rewritten or extended,
    which is the property that lets published pixels be immutable while the
    run keeps growing.
    """
    collection = experiment / "acquisitions" / "overview" / "data" / "survey.ome.zarr"
    declared = json.loads((collection / "zarr.json").read_text())
    for member in declared["attributes"]["zmart"]["members"]:
        image = zarr.open_group(collection / member, mode="r")
        for dataset in image.attrs["ome"]["multiscales"][0]["datasets"]:
            level = zarr.open_array(collection / member / dataset["path"], mode="r")
            # Two shapes matter, and they are different promises. The SHARD
            # is the file on disk -- the unit a rewrite would actually touch
            # -- and zarr reports it as ``shards`` (falling back to
            # ``chunks`` for an unsharded array). The inner chunk is the
            # unit a reader decodes. Both must stay within one moment and
            # one channel: the file so published bytes are never rewritten,
            # the chunk so no reader ever decodes across the boundary.
            file_unit = level.shards if level.shards is not None else level.chunks
            assert file_unit[0] == 1 and file_unit[1] == 1, (
                f"level {dataset['path']} of {member} stores a file spanning "
                f"t or c: shard shape {file_unit} -- a retake or a new "
                "channel would rewrite already-published bytes"
            )
            assert level.chunks[0] == 1 and level.chunks[1] == 1, (
                f"level {dataset['path']} of {member} decodes across t or c: "
                f"chunk shape {level.chunks}"
            )


def test_nothing_in_data_references_views(experiment):
    """The arrow points one way: views believe data, data has never heard of views."""
    data = experiment / "acquisitions" / "overview" / "data"
    for path in data.rglob("*.json"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "views/" not in text and '"views"' not in text, (
            f"{path.relative_to(data)} mentions the views folder -- data/ must "
            "stand alone, deletable views/ and all"
        )


def test_deleting_views_loses_no_science(experiment):
    """Delete views/. Hand data/ to a stranger. Everything must work."""
    acquisition = experiment / "acquisitions" / "overview"
    shutil.rmtree(acquisition / "views")

    assert names_inside(acquisition) == ["data"], (
        "after deleting views/ nothing of ours remains anywhere in the "
        "acquisition -- the one gesture removes every file we ever wrote"
    )
    collection = acquisition / "data" / "survey.ome.zarr"
    declared = json.loads((collection / "zarr.json").read_text())
    for member in declared["attributes"]["zmart"]["members"]:
        level0 = zarr.open_array(collection / member / "0", mode="r")
        middle = np.asarray(level0[0, 0, 0, FRAME // 2, FRAME // 2])
        assert middle.dtype == np.uint16  # still opens, still reads
