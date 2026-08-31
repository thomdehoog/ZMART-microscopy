"""Names that can be trusted, and records that stay put once they are written.

Three separate promises are checked here, and all three were found to be broken
by an outside reviewer before this file existed. Each class below opens by saying
what the code actually did at the time, so that nobody has to take on trust that
these tests were ever red.

The three promises are worth stating plainly, because they are the difference
between a run you can go back to and a run you can only hope about.

**A profile has to be findable again.** A published position names the profile it
was written under. If that profile only ever existed in the memory of the process
that ran the acquisition, then next week the name refers to nothing, and the
pixels on disk have no description at all.

**A name has to mean one thing.** Two acquisitions that differ in pixel type, in
depth, in colours or in voxel size are two different acquisitions. If they can
end up sharing a name, then a reader who resolves that name gets an answer that
may or may not describe the pixels in front of them, and there is no way to tell
which.

**A name has to be safe to put in a path.** A position called ``../../escaped``
is not an exotic attack; it is what a badly filled-in position list looks like.
Written straight into a folder name it puts image data somewhere nobody will
look for it, outside the run entirely.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from zmart_live import identity, manifest
from zmart_live.identity import (
    fingerprint_of_a_profile,
    latest_layout_revision,
    load_a_layout_revision,
    load_the_profile,
    record_the_layout,
    store_a_layout_revision,
    store_the_profile,
    stored_layout_revisions,
    stored_profile_ids,
)
from zmart_live.model import (
    Box,
    GridCell,
    PositionPlacement,
    SceneLayoutRevision,
    ZmartLiveError,
    check_the_name_is_safe,
    is_a_safe_name,
)
from zmart_live.profiles import plan_the_writing


def a_placement(position_id: str, row: int, column: int) -> PositionPlacement:
    """One tile, described just fully enough to sit in a layout snapshot."""
    return PositionPlacement(
        position_id=position_id,
        component_id="component-0",
        cell=GridCell(row, column),
        origin={"y": row * 8, "x": column * 8},
        analysis_input_roi=Box.of(y=(0, 10), x=(0, 10)),
        analysis_core_roi=Box.of(y=(0, 8), x=(0, 8)),
    )


def a_layout(*positions: PositionPlacement, revision: int = 1) -> SceneLayoutRevision:
    """A snapshot of a small mosaic, ready to be handed to the recorder."""
    return SceneLayoutRevision(
        revision=revision,
        schema_version="zmart-live-layout/1",
        run_id="run-1",
        acquisition_type="overview",
        profile_id="overview-test",
        positions=positions,
        created_at="2026-08-09 10:00",
    )


class TestANameThatWouldEscapeTheRunFolder:
    """Observed before this was fixed: nothing checked position names at all.

    ``LivePublisher.position_store`` built a folder name straight from the
    position's identifier, so a position called ``../../escaped`` wrote its image
    two directories above the run. No error was raised and no warning was
    printed; the run simply left part of itself somewhere else on the disk.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "../../escaped",
            "..",
            ".",
            "a/b",
            "a\\b",
            "/absolute",
            "C:\\Windows",
            "C:relative",
            "pos:0,0",
            "",
            "   ",
            "trailing.",
            "trailing ",
            " leading",
            "with\x00null",
            "with\nnewline",
        ],
    )
    def test_it_is_refused(self, name):
        assert not is_a_safe_name(name)
        with pytest.raises(ZmartLiveError):
            check_the_name_is_safe(name, what="position")

    @pytest.mark.parametrize(
        "name",
        ["CON", "con", "PRN", "aux", "NUL", "COM1", "lpt9", "CON.txt", "nul.ome.zarr"],
    )
    def test_a_reserved_windows_device_name_is_refused(self, name):
        """These run on Windows microscope computers, where ``CON`` is a device.

        A folder called ``CON`` cannot be created on Windows at all, and a file
        opened under that name talks to the console instead of the disk. The
        reserved name still applies when an extension is added, which is why
        ``CON.txt`` is refused as well.
        """
        assert not is_a_safe_name(name)
        with pytest.raises(ZmartLiveError):
            check_the_name_is_safe(name, what="position")

    @pytest.mark.parametrize(
        "name",
        ["sample.generation-1", "sample.Generation-12", "x.generation-0003"],
    )
    def test_a_replacement_store_suffix_is_reserved(self, name):
        """Two distinct position identifiers must never resolve to one folder."""
        assert not is_a_safe_name(name)
        with pytest.raises(ZmartLiveError, match="replacement stores"):
            check_the_name_is_safe(name, what="position")

    @pytest.mark.parametrize(
        "name",
        [
            "pos000",
            "posA",
            "run-2026-08-08",
            "component-0",
            "overview-1152-128-ab12cd34ef56",
            "x",
            "console",
            "communications",
            "tile.ome",
        ],
    )
    def test_an_ordinary_name_is_accepted(self, name):
        """The rule has to stay out of the way of names people actually use.

        ``console`` and ``communications`` matter here: a check that refused
        anything merely *starting* with ``CON`` or ``COM`` would be a nuisance
        rather than a protection.
        """
        assert is_a_safe_name(name)
        assert check_the_name_is_safe(name, what="position") == name

    def test_the_refusal_says_what_was_wrong_and_what_is_allowed(self):
        with pytest.raises(ZmartLiveError) as raised:
            check_the_name_is_safe("../../escaped", what="position")
        message = str(raised.value)
        assert "position" in message
        assert "../../escaped" in message

    def test_a_placement_cannot_be_built_with_one(self):
        """The refusal has to sit in the record, not only in a helper.

        This is what makes the guard hard to walk around. A layout that named an
        escaping position could never be written down in the first place, so no
        later code has to remember to check.
        """
        with pytest.raises(ZmartLiveError):
            a_placement("../../escaped", 0, 0)


class TestAProfileCanBeFoundAgainAfterTheRun:
    """Observed before this was fixed: nothing wrote a profile to disk anywhere.

    ``plan_the_writing`` returned a sealed profile, every commit event recorded
    its identifier, and no code path in the package ever stored it. A run
    finished with published positions referring by name to a description that had
    only ever existed in memory.
    """

    def test_it_reads_back_as_the_same_profile(self, tmp_path):
        profile, _ = plan_the_writing("confocal", frame=1152, z_planes=8)
        store_the_profile(tmp_path, profile)
        again = load_the_profile(tmp_path, profile.profile_id)
        assert again.to_json() == profile.to_json()

    def test_a_profile_with_a_name_that_omits_its_fingerprint_is_not_stored(
        self, tmp_path
    ):
        profile, _ = plan_the_writing("confocal", frame=1152, z_planes=8)
        badly_named = replace(profile, profile_id="confocal-tuesday")

        with pytest.raises(ZmartLiveError, match="refuses to load later"):
            store_the_profile(tmp_path, badly_named)

        assert stored_profile_ids(tmp_path) == ()

    def test_storing_it_twice_is_harmless(self, tmp_path):
        """Rerunning the setup step of a run must not be a destructive act."""
        profile, _ = plan_the_writing("overview", frame=2304)
        first = store_the_profile(tmp_path, profile)
        second = store_the_profile(tmp_path, profile)
        assert first == second
        assert load_the_profile(tmp_path, profile.profile_id).to_json() == profile.to_json()

    def test_every_stored_profile_can_be_listed(self, tmp_path):
        overview, _ = plan_the_writing("overview", frame=2304)
        confocal, _ = plan_the_writing("confocal", frame=1152, z_planes=40)
        store_the_profile(tmp_path, overview)
        store_the_profile(tmp_path, confocal)
        assert stored_profile_ids(tmp_path) == tuple(
            sorted((overview.profile_id, confocal.profile_id))
        )

    def test_profile_names_that_share_one_windows_file_are_refused(self, tmp_path):
        first, _ = plan_the_writing(
            "overview", frame=2304, readable_prefix="Tuesday-overview"
        )
        second, _ = plan_the_writing(
            "overview", frame=2304, readable_prefix="tuesday-overview"
        )
        assert first.profile_id != second.profile_id
        assert first.profile_id.casefold() == second.profile_id.casefold()

        store_the_profile(tmp_path, first)
        with pytest.raises(ZmartLiveError, match="case-insensitive Windows"):
            store_the_profile(tmp_path, second)

    def test_asking_for_one_that_was_never_stored_says_what_is_there(self, tmp_path):
        profile, _ = plan_the_writing("overview", frame=2304)
        store_the_profile(tmp_path, profile)
        with pytest.raises(ZmartLiveError) as raised:
            load_the_profile(tmp_path, "overview-never-written")
        assert profile.profile_id in str(raised.value)

    def test_a_profile_edited_on_disk_no_longer_answers_to_its_own_name(self, tmp_path):
        """The name is the fingerprint, so tampering is visible rather than silent.

        Somebody opening the stored file and changing the pixel type would
        otherwise leave a description that disagrees with the pixels while still
        carrying the name every published position points at.
        """
        profile, _ = plan_the_writing("confocal", frame=1152, z_planes=8)
        where = store_the_profile(tmp_path, profile)
        tampered = json.loads(where.read_text())
        tampered["dtype"] = "uint8"
        where.write_text(json.dumps(tampered))

        with pytest.raises(ZmartLiveError) as raised:
            load_the_profile(tmp_path, profile.profile_id)
        assert "fingerprint" in str(raised.value).lower()

    def test_it_is_put_in_place_in_one_step(self, tmp_path, monkeypatch):
        """A half-written profile must never be readable.

        The contents are written beside the destination and renamed over it, and
        the bytes are pushed to the disk before the rename. Renaming is the one
        filesystem step that is genuinely all-or-nothing, so a reader sees either
        the whole old file or the whole new one.
        """
        actions: list[str] = []
        really_push = manifest.os.fsync
        really_replace = manifest.os.replace

        def watching_push(descriptor):
            actions.append("push")
            return really_push(descriptor)

        def watching_replace(source, destination):
            actions.append("replace")
            return really_replace(source, destination)

        monkeypatch.setattr(manifest.os, "fsync", watching_push)
        monkeypatch.setattr(manifest.os, "replace", watching_replace)

        profile, _ = plan_the_writing("overview", frame=2304)
        store_the_profile(tmp_path, profile)

        assert "replace" in actions
        assert "push" in actions[: actions.index("replace")]


class TestAProfileNameCoversEverythingThatMakesItDifferent:
    """Observed before this was fixed: the name was built from three things only.

    The identifier was ``f"{acquisition_type}-{frame}-{chunk}"``. Two confocal
    profiles with a 1152 frame therefore both came out as ``confocal-1152-128``
    however much else differed — 16-bit against 8-bit pixels, eight planes
    against a hundred, one colour against six, a 0.2 micrometre voxel against a
    0.5 micrometre one. A profile whose name does not cover its contents is not
    sealed in any useful sense.
    """

    def a_pair(self, **changes):
        settled = {"frame": 1152, "z_planes": 8, "dtype": "uint16"}
        first, _ = plan_the_writing("confocal", **settled)
        second, _ = plan_the_writing("confocal", **{**settled, **changes})
        return first, second

    def test_two_profiles_differing_only_in_dtype_get_different_names(self):
        first, second = self.a_pair(dtype="uint8")
        assert first.dtype != second.dtype
        assert first.profile_id != second.profile_id

    @pytest.mark.parametrize(
        "changes",
        [
            {"dtype": "uint8"},
            {"z_planes": 100},
            {"channels": ("green", "red")},
            {"voxel_size": (2.0, 0.2, 0.2)},
            {"voxel_unit": "nanometer"},
        ],
    )
    def test_any_difference_at_all_gives_a_different_name(self, changes):
        first, second = self.a_pair(**changes)
        assert first.profile_id != second.profile_id

    def test_the_reviewers_two_profiles_no_longer_collide(self):
        """The exact pair an outside reviewer built, which both came out
        ``confocal-1152-128``."""
        first, _ = plan_the_writing(
            "confocal",
            frame=1152,
            dtype="uint16",
            z_planes=8,
            channels=("green",),
            voxel_size=(2.0, 0.5, 0.5),
        )
        second, _ = plan_the_writing(
            "confocal",
            frame=1152,
            dtype="uint8",
            z_planes=100,
            channels=("green", "red", "far red"),
            voxel_size=(1.0, 0.2, 0.2),
        )
        assert first.profile_id != second.profile_id

    def test_the_same_acquisition_always_gets_the_same_name(self):
        """Two runs set up the same way have to agree, or nothing can be compared."""
        first, _ = plan_the_writing("confocal", frame=1152, z_planes=8)
        second, _ = plan_the_writing("confocal", frame=1152, z_planes=8)
        assert first.profile_id == second.profile_id
        assert fingerprint_of_a_profile(first) == fingerprint_of_a_profile(second)

    def test_the_name_still_reads_like_something(self):
        """A fingerprint alone would be unreadable in a log, so it keeps a prefix."""
        profile, geometry = plan_the_writing("confocal", frame=1152, z_planes=8)
        assert profile.profile_id.startswith(f"confocal-1152-{geometry.chunk}-")

    def test_a_chosen_prefix_still_carries_the_fingerprint(self):
        """A run may name its profile for a person, and still cannot cause a clash."""
        first, _ = plan_the_writing(
            "confocal", frame=1152, z_planes=8, readable_prefix="tuesday-confocal"
        )
        second, _ = plan_the_writing(
            "confocal", frame=1152, z_planes=8, dtype="uint8", readable_prefix="tuesday-confocal"
        )
        assert first.profile_id.startswith("tuesday-confocal-")
        assert first.profile_id != second.profile_id

    def test_the_name_is_safe_to_put_in_a_path(self):
        profile, _ = plan_the_writing("confocal", frame=1152, z_planes=8)
        assert is_a_safe_name(profile.profile_id)


class TestALayoutRevisionIsNeverOverwritten:
    """Observed before this was fixed: every layout was revision 1, written flat.

    ``LivePublisher`` built its snapshot with ``revision=1`` and never changed
    it, and ``write_the_layout`` wrote ``layout.json`` straight over the previous
    contents on every single commit. Two things followed from that. A position
    arriving later could not create a later snapshot, so a smart run that adds
    positions as it goes had no way to record the arrangement changing. And a
    published measurement saying "layout revision 1" pointed at a file whose
    contents were replaced repeatedly while the run went on, so it did not point
    at a fixed thing at all.
    """

    def test_the_first_arrangement_is_revision_one(self, tmp_path):
        recorded = record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0)))
        assert recorded.revision == 1
        assert stored_layout_revisions(tmp_path) == (1,)

    def test_a_changed_arrangement_becomes_a_later_revision(self, tmp_path):
        record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0)))
        second = record_the_layout(
            tmp_path, a_layout(a_placement("posA", 0, 0), a_placement("posB", 0, 1))
        )
        assert second.revision == 2
        assert stored_layout_revisions(tmp_path) == (1, 2)

    def test_the_earlier_revision_still_says_what_it_always_said(self, tmp_path):
        """This is the whole point. A result published against revision 1 has to
        keep meaning what it meant when it was published."""
        record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0)))
        before = load_a_layout_revision(tmp_path, 1).to_json()

        record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0), a_placement("posB", 0, 1)))

        assert load_a_layout_revision(tmp_path, 1).to_json() == before
        assert load_a_layout_revision(tmp_path, 1).position_ids == ("posA",)

    def test_a_moment_that_changes_nothing_spatial_reuses_the_revision(self, tmp_path):
        """Decision 26 of the architecture record, in one test.

        A later timepoint over tiles that are already in place has not moved
        anything, so it references the snapshot that already exists and gets its
        own commit record instead. Minting a fresh identical snapshot for every
        moment of a timelapse would fill the run with thousands of copies of the
        same arrangement.
        """
        first = record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0)))
        again = record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0)))
        assert again.revision == first.revision == 1
        assert stored_layout_revisions(tmp_path) == (1,)

    def test_a_revision_that_already_exists_cannot_be_written_over(self, tmp_path):
        """The fail-closed guard underneath the reuse rule.

        Even if a caller works out the revision number itself and gets it wrong,
        the stored snapshot does not move.
        """
        store_a_layout_revision(tmp_path, a_layout(a_placement("posA", 0, 0), revision=1))
        with pytest.raises(ZmartLiveError) as raised:
            store_a_layout_revision(
                tmp_path,
                a_layout(a_placement("posA", 0, 0), a_placement("posB", 0, 1), revision=1),
            )
        assert "1" in str(raised.value)
        assert load_a_layout_revision(tmp_path, 1).position_ids == ("posA",)

    def test_rewriting_an_identical_revision_is_harmless(self, tmp_path):
        """Repeating the same snapshot is not a change, so it is not a conflict."""
        layout = a_layout(a_placement("posA", 0, 0), revision=1)
        store_a_layout_revision(tmp_path, layout)
        store_a_layout_revision(tmp_path, layout)
        assert stored_layout_revisions(tmp_path) == (1,)

    def test_the_newest_arrangement_can_be_found_without_knowing_its_number(self, tmp_path):
        assert latest_layout_revision(tmp_path) is None
        record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0)))
        record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0), a_placement("posB", 0, 1)))
        newest = latest_layout_revision(tmp_path)
        assert newest is not None
        assert newest.revision == 2
        assert newest.position_ids == ("posA", "posB")

    def test_the_convenience_pointer_follows_the_newest_revision(self, tmp_path):
        """``layout.json`` stays where the rest of the code already looks for it.

        It is a copy of the newest snapshot, replaced in one indivisible step so
        that a reader never sees half of it. The numbered files beside it are the
        records that never move.
        """
        record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0)))
        record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0), a_placement("posB", 0, 1)))
        pointer = identity.the_records_folder(tmp_path) / "layout.json"
        stored = SceneLayoutRevision.from_json(json.loads(pointer.read_text()))
        assert stored.revision == 2
        assert stored.to_json() == load_a_layout_revision(tmp_path, 2).to_json()

    def test_a_moved_tile_counts_as_a_change_even_with_the_same_names(self, tmp_path):
        """Membership is where the tiles are, not merely which ones exist.

        Two snapshots naming the same positions in different places describe
        different specimen, so the second has to be a new revision.
        """
        record_the_layout(tmp_path, a_layout(a_placement("posA", 0, 0)))
        moved = record_the_layout(tmp_path, a_layout(a_placement("posA", 3, 4)))
        assert moved.revision == 2
