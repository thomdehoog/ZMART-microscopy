"""Breaking the code on purpose, to see whether the tests notice.

A passing test tells you nothing until you have watched it fail for the right
reason. Checks quietly rot: a rename, a refactor, an assertion that was always
true, and something that used to catch a real fault stops catching anything while
still reporting success every morning. Nothing about a green suite reveals that.

So this introduces one fault at a time into :mod:`zmart_live.manifest`, runs the
tests, and reports whether they caught it. A fault nobody catches is a claim the
tests are not really making, and it should either be tested properly or written
down as a known gap.

This is not part of the ordinary test run. It takes a few seconds and it edits a
source file while it works, so it is a thing you run deliberately::

    python -m zmart_live.tests.check_the_tests_can_fail

It puts the file back after completion, exceptions, Ctrl-C and SIGTERM. No
process can recover after SIGKILL or loss of power; after either, restore the
mutation subject from version control before running anything else.

One real gap it found
---------------------

Removing the step that pushes the record to the disk before renaming it was
caught by nothing at all. That step matters only when the power fails, which a
test suite cannot arrange, so the suite now checks that the step is *taken*
rather than that it works. That is a weaker claim, honestly made, and it is
better than the silence that was there before.
"""

from __future__ import annotations

from pathlib import Path

from ._fault_check import (
    make_interruptions_reach_finally,
    replace_source,
    require_green_subject,
    require_restored_subject,
    run_pytest,
)

HERE = Path(__file__).resolve()
PACKAGE = HERE.parent.parent
REPO = PACKAGE.parent

#: Each entry is a plain-language description of the fault, the text to find, and
#: what to replace it with. They are chosen to be faults a tired person could
#: genuinely introduce, not absurd ones: dropping a guard, forgetting to record
#: something, losing track of where a reader had got to.
MANIFEST_FAULTS: list[tuple[str, str, str]] = [
    (
        "publish anything, ready or not",
        "if not event.ready:",
        "if False:",
    ),
    (
        "let the counter stand still instead of going up",
        "expected = max(state.revision, last_recorded) + 1\n"
        "            if event.revision != expected:",
        "expected = max(state.revision, last_recorded) + 1\n            if False:",
    ),
    (
        "forget to record which position changed",
        "moved_on[event.position_id] = event.revision",
        "pass",
    ),
    (
        "never notice that anything changed",
        "return (\n"
        "            stamp.st_mtime_ns,\n"
        "            stamp.st_ctime_ns,\n"
        "            stamp.st_size,\n"
        '            getattr(stamp, "st_ino", 0),\n'
        "        )",
        "return (0, 0, 0, 0)",
    ),
    (
        "ignore where the reader had got to",
        "if event.revision > after and (",
        "if True and (",
    ),
    (
        "skip pushing to the disk before renaming",
        "            os.fsync(writing.fileno())\n        written_despite_brief_holds",
        "        written_despite_brief_holds",
    ),
    (
        "silently skip every complete history record",
        "if stripped:",
        "if False:",
    ),
    (
        "accept duplicate or out-of-order history revisions",
        "expected = len(self._events_cache) + len(new_events) + 1\n"
        "                if event.revision != expected:",
        "expected = len(self._events_cache) + len(new_events) + 1\n                if False:",
    ),
    (
        "extend a truth file whose published history has disappeared",
        "if state.revision > last_recorded:",
        "if False:",
    ),
    (
        "keep stale cached events after the history file disappears",
        "if not self.history.exists():\n            self._reset_history_reader()",
        "if not self.history.exists():\n            pass",
    ),
    (
        "trust the history over what was actually announced",
        "and (ceiling is None or event.revision <= ceiling)",
        "and True",
    ),
    (
        "accept a commit belonging to another run",
        "if event.run_id != state.run_id:",
        "if False:",
    ),
    (
        "leave an unpublished crash tail in the active history",
        "history.truncate(keep_to)",
        "history.truncate(self._read_to)",
    ),
]


#: The seam rules are where a silent wrong answer is most likely to hide, because
#: a mosaic assembled with the boundary one pixel out looks entirely normal.
OWNERSHIP_FAULTS: list[tuple[str, str, str]] = [
    (
        "let a negative grid coordinate become a slice from the array's far edge",
        "if any(\n"
        "        not isinstance(index, int) or isinstance(index, bool) or index < 0\n"
        "        for index in coordinates\n"
        "    ):",
        "if False:",
    ),
    (
        "give the extra pixel of an odd overlap to both neighbours",
        "half_before = overlap // 2 if has_one_before else 0",
        "half_before = (overlap - overlap // 2) if has_one_before else 0",
    ),
    (
        "count right to the edge even where a neighbour exists",
        "counted[axis] = Interval(half_before, frame - half_beyond)",
        "counted[axis] = Interval(0, frame)",
    ),
    (
        "accept a mosaic held together only at a corner",
        "if reached != occupied:",
        "if False:",
    ),
    (
        "let one position sit twice or two names resolve to one Windows folder",
        "if disk_name in seen_on_disk:",
        "if False:",
    ),
    (
        "call a mosaic with a hole in it complete",
        "complete=not holes,",
        "complete=True,",
    ),
    (
        "hand a model only the part it owns, with no context",
        "looked_at[axis] = Interval(0, frame)",
        "looked_at[axis] = Interval(0, step)",
    ),
]

LAYOUT_FAULTS: list[tuple[str, str, str]] = [
    (
        "silently choose the first tile when a stored layout has two owners",
        "if len(owners) > 1:",
        "if False:",
    ),
    (
        "store two component positions under one Windows folder name",
        "if disk_name in seen_component_names:",
        "if False:",
    ),
    (
        "store two layout positions under one Windows folder name",
        "if layout_disk_name in seen_layout_names:",
        "if False:",
    ),
]

#: The zoomed-out picture is where an unfinished position would show up quietly,
#: at low magnification, looking exactly like specimen.
COARSE_FAULTS: list[tuple[str, str, str]] = [
    (
        "let an uncommitted position into the zoomed-out picture",
        "if placement.position_id in committed",
        "if True",
    ),
    (
        "name one more piece than the position actually touches",
        "last = (span.stop - 1) // across",
        "last = span.stop // across",
    ),
    (
        "forget that a piece covers more ground the further out it is",
        "across = chunk[axis] * scale[axis]",
        "across = chunk[axis]",
    ),
    (
        "count the arriving position as one of its own neighbours",
        "if other.position_id != position_id:",
        "if True:",
    ),
    (
        "rebuild only the coarsest level and leave the rest stale",
        "for level in wanted:",
        "for level in wanted[-1:]:",
    ),
    (
        "treat a piece as covering only the ground of the first position in it",
        ".overlaps(shows)",
        ".overlaps(shows) and placement is placements[0]",
    ),
]

#: The coordinator is the piece that turns a readiness claim into something
#: earned, so the faults worth introducing here are the ones that would quietly
#: turn it back into a rubber stamp. Every one of these leaves a run that looks
#: entirely normal and publishes something unfinished.
COORDINATOR_FAULTS: list[tuple[str, str, str]] = [
    (
        "publish without looking at what landed",
        "if not found.everything_checks_out:",
        "if False:",
    ),
    (
        "treat a missing zoomed-out copy as acceptable",
        "            if not path.exists():\n"
        "                complaints.append(\n"
        "                    f\"'{position_id}' promises a zoomed-out copy at level \"\n"
        "                    f\"{level.level}, but it has not been written. A viewer zooming \"\n"
        "                    f\"out would find nothing there.\"\n"
        "                )\n"
        "                continue",
        "            if not path.exists():\n"
        "                continue",
    ),
    (
        "call the pixels ready even when something was complained about",
        "pyramids_ready=pieces_read > 0 and not about_pixels,",
        "pyramids_ready=True,",
    ),
    (
        "accept copied chunks in the seamless virtual view",
        'if (path / "c").exists():',
        "if False:",
    ),
    (
        "stop checking that the arrangement can be read back",
        "layout_ready=layout_ok and not about_the_layout,",
        "layout_ready=True,",
    ),
    (
        "count a piece as read without reading it",
        "everything = array[:]",
        "everything = np.zeros(1)",
    ),
    (
        "accept a pointer whose bytes decode to the wrong picture",
        "if not _the_same_picture(lifted, array, corner):",
        "if False:",
    ),
    (
        "compare a piece against the padding rather than the specimen",
        "slice(place * size, min(place * size + size, reach))",
        "slice(place * size, place * size + size)",
    ),
    # The one linked view draws positions whole, later commit on top, and the
    # stored order is that draw order.
    (
        "route positions in layout order instead of commit order",
        "showing = [\n"
        "            position_id\n"
        "            for position_id in self._positions_in_commit_order()\n"
        "            if position_id in showing_set\n"
        "        ]",
        "showing = []",
    ),
    (
        "call the view ready without looking at it",
        "view_ready=validated > 0 and not about_the_picture,",
        "view_ready=True,",
    ),
    # One position at one moment is what gets published, so every check has to
    # be about that moment. Each fault below ends with a moment nobody wrote, or
    # a piece nobody stored, being published as finished.
    (
        "look at the same moment whichever one was asked about",
        "moment = 0 if timepoint is None else timepoint",
        "moment = 0",
    ),
    (
        "believe a level is complete without asking which pieces it holds",
        "piece for piece in owed if where_one_chunk_lives(path, piece) is None",
        "piece for piece in owed if False",
    ),
    # Both virtual descriptions and the arrangement can be readable and wrong.
    (
        "accept view metadata that cannot decode its routes",
        "                refuse_a_view_stored_differently(path, routed[level.level])",
        "                pass",
    ),
    (
        "make the zoomed-out picture one plane deep whatever was recorded",
        '            depth // smaller.get("z", 1),',
        "            1,",
    ),
    (
        "accept an arrangement belonging to another run",
        "if found != wanted:",
        "if False:",
    ),
    # The map saying which position answers for which piece of the overview.
    (
        "never write down where the overview's pieces come from",
        "self.write_the_link_map(units)",
        "pass",
    ),
    (
        "check two corner pointers instead of every piece served",
        "ranges += self._follow_the_stored_pointers(\n"
        "                position_id, moment, about_pointers\n"
        "            )",
        "ranges += 0",
    ),
    (
        "serve the overview from any map that happens to parse",
        "if stored.get(key) != wanted:",
        "if False:",
    ),
    # Colours are separate measurements, and published pixels are somebody's
    # evidence. Both faults below leave a run that looks entirely ordinary.
    (
        "put one colour's pixels into every colour",
        "array[timepoint, channel] = pixels[channel]",
        "array[timepoint, channel] = pixels[0]",
    ),
    (
        "let a moment somebody has already been shown be written over",
        "if (position_id, timepoint) in self._committed_units():",
        "if False:",
    ),
    (
        "let a replacement overwrite the generation it is replacing",
        "self.generations[position_id] = now",
        "pass",
    ),
    (
        "forget the replacement generation after a restart",
        "self._restore_generations_from_the_manifest()",
        "pass",
    ),
    (
        "reopen one run under a different profile or spatial plan",
        "newest is not None\n"
        "            and spatial_fingerprint_of_a_layout(newest)\n"
        "            != spatial_fingerprint_of_a_layout(candidate_layout)",
        "False",
    ),
    (
        "let a live image have no declared channel",
        "if not profile_channels:",
        "if False:",
    ),
    (
        "label fixed-order array indexes with a different axis order",
        "if self.profile.axes != expected_axes:",
        "if False:",
    ),
    (
        "let the writer's channel identities contradict its sealed profile",
        "if self.channels != profile_channels:",
        "if False:",
    ),
    (
        "allow a run to declare no timepoints",
        "or self.timepoints < 1",
        "or False",
    ),
    (
        "reopen existing arrays with a different declared shape",
        "if tuple(found.shape) != expected:",
        "if False:",
    ),
    (
        "write a frame whose shape contradicts the acquisition profile",
        "if tuple(settled.shape[1:]) != expected_shape:",
        "if False:",
    ),
    (
        "leave the acquisition profile only in process memory",
        "store_the_profile(self.folder, self.profile)",
        "pass",
    ),
    (
        "leave the initial layout only in process memory",
        "self.layout = record_the_layout(self.folder, self.layout)",
        "pass",
    ),
]

#: What a name is allowed to be. These faults all end the same way: a position
#: writes its images somewhere outside the run, or under a name that cannot exist
#: on the Windows machine the microscope is actually attached to. None of them
#: raises anything at the time; the run simply leaves part of itself elsewhere.
NAMING_FAULTS: list[tuple[str, str, str]] = [
    (
        "let a name hold anything at all, separators included",
        '_ALLOWED_IN_A_NAME = re.compile(r"^[A-Za-z0-9._-]+$")',
        '_ALLOWED_IN_A_NAME = re.compile(r"^.+$")',
    ),
    (
        "forget that Windows keeps CON and NUL for its own hardware",
        'if name.split(".")[0].lower() in RESERVED_DEVICE_NAMES:',
        "if False:",
    ),
    (
        "accept a name ending in a dot or a space",
        'if name[0] in " ." or name[-1] in " .":',
        "if False:",
    ),
    (
        "let an ordinary position collide with an immutable replacement store",
        "if _GENERATION_SUFFIX.search(name):",
        "if False:",
    ),
    (
        "stop checking a tile's name where the tile is described",
        'check_the_name_is_safe(self.position_id, what="position")\n'
        '        check_the_name_is_safe(self.component_id, what="mosaic component")',
        "pass",
    ),
]

#: Naming a profile after its contents, and keeping the run's descriptions where
#: they can be found again. Every fault here leaves a published position pointing
#: at something that either is not there, or is no longer what it was.
IDENTITY_FAULTS: list[tuple[str, str, str]] = [
    (
        "name a profile without its fingerprint",
        'return f"{readable_prefix}-{fingerprint_of_a_profile(profile)}"',
        "return readable_prefix",
    ),
    (
        "fingerprint only the kind of acquisition, not its contents",
        "described = profile.to_json()",
        'described = {"acquisition_type": profile.acquisition_type}',
    ),
    (
        "store a profile under a name that does not cover its contents",
        "if not profile.profile_id.endswith(expected):",
        "if False:",
    ),
    (
        "store two profiles under one Windows file name",
        "if stored_id != profile.profile_id and stored_id.casefold() == profile.profile_id.casefold():",
        "if False:",
    ),
    (
        "never actually write the profile down",
        "    _put_in_place_in_one_step(where, text)\n    return where",
        "    return where",
    ),
    (
        "write a stored profile without the rename that makes it all-or-nothing",
        "    _put_in_place_in_one_step(where, text)\n    return where",
        "    where.parent.mkdir(parents=True, exist_ok=True)\n"
        "    where.write_text(text)\n"
        "    return where",
    ),
    (
        "trust a stored profile without checking it still matches its name",
        "if not profile_id.endswith(expected):",
        "if False:",
    ),
    (
        "write a new arrangement over the snapshot already there",
        "    where = _layout_file(run_folder, layout.revision)\n"
        '    text = json.dumps(layout.to_json(), indent=2, sort_keys=True) + "\\n"\n'
        "    if where.exists():",
        "    where = _layout_file(run_folder, layout.revision)\n"
        '    text = json.dumps(layout.to_json(), indent=2, sort_keys=True) + "\\n"\n'
        "    if False:",
    ),
    (
        "keep every arrangement at revision one for ever",
        "revision=(newest.revision + 1) if newest is not None else 1,",
        "revision=1,",
    ),
    (
        "mint a fresh snapshot for every moment of a timelapse",
        "if newest is not None and spatial_fingerprint_of_a_layout(newest) == fingerprint:",
        "if False:",
    ),
]

#: Planning the writing for a frame that is not square. A fault here produces a
#: profile describing a frame the microscope never produced, which nothing
#: downstream can detect: the pixels simply land in the wrong shape of box.
PROFILE_PLANNING_FAULTS: list[tuple[str, str, str]] = [
    (
        "use the frame's height for its width as well",
        'frame_shape={"z": z_planes, "y": height, "x": width},',
        'frame_shape={"z": z_planes, "y": height, "x": height},',
    ),
    (
        "bundle only part of a rectangular frame into one file",
        '                    "x": level_shape[1],',
        '                    "x": level_shape[0],',
    ),
    (
        "measure the width's overlap against the height",
        "        else _axis_choices(\n            width,",
        "        else _axis_choices(\n            height,",
    ),
    (
        "enumerate overlaps that do not survive every pyramid level",
        "for overlap in range(first, high + 1, deepest):",
        "for overlap in range(low, high + 1):",
    ),
    (
        "choose the smallest valid chunk instead of the largest",
        "chunks.append(max(permitted))",
        "chunks.append(min(permitted))",
    ),
    (
        "leave every coarse canonical level unsharded",
        "                shard={",
        "                shard=None if level else {",
    ),
    (
        "hand back one side of a rectangle when asked for 'the' frame",
        "if not self.is_square:",
        "if False:",
    ),
]


# Publication has to be enforced again at the HTTP boundary.  These mutations
# target the shared gateway used by the real backend, rather than the synthetic
# browser server, so a green result demonstrates the path an operator uses.
GATEWAY_FAULTS: list[tuple[str, str, str]] = [
    (
        "serve a canonical position before its commit",
        "return (position_id, moment, generation) in self._published_units()",
        "return True",
    ),
    (
        "serve a virtual seamless chunk before its commit",
        "if not self.published(position_id, moment, generation):",
        "if False:",
    ),
    (
        "accept copied chunks in the linked view at the serving boundary",
        'if (view_array / "c").exists():',
        "if False:",
    ),
    (
        "blank published ground while its successor is withheld",
        "            if not self.published(position_id, moment, generation):\n"
        "                continue",
        "            if not self.published(position_id, moment, generation):\n"
        "                return LiveResponse(False)",
    ),
    (
        "serve the overview in whatever order the map happens to say",
        "                    ] != committed_order:",
        "                    ] != committed_order and False:",
    ),
    (
        "hide inherited published moments after replacing one moment",
        "for inherited in already_visible",
        "for inherited in ()",
    ),
    (
        "trust a live link map belonging to another run",
        "if held.get(key) != expected:",
        "if False:",
    ),
    (
        "trust a live link map that moves a tile",
        'tuple(entry["lands_at"]) != expected_lands_at',
        "False",
    ),
    (
        "misread a canonical position name as a replacement suffix",
        'if store_name == f"{position_id}.ome.zarr":',
        "if False:",
    ),
]


REPLACEMENT_GATE_FAULTS: list[tuple[str, str, str]] = [
    (
        "leave the candidate generation's map behind after a failed replacement",
        "self.write_the_view()\n"
        "        self.write_the_link_map(frozenset(self._committed_units()))",
        "self.write_the_view()",
    ),
    (
        "leave failed replacement pixels and routing in the shared views",
        "self._restore_shared_state_after_failed_replacement(\n"
        "                    position_id, timepoint\n"
        "                )",
        "pass",
    ),
]

#: The per-commit metadata rewrites die under a reader's hold without their
#: patience, and a tired person removes a wrapper like this believing it
#: redundant. Only the hold tests notice, because only they hold the file.
HOLD_PATIENCE_FAULTS: list[tuple[str, str, str]] = [
    (
        "replace the marker with no patience for a reader's hold",
        "written_despite_brief_holds(lambda: os.replace(handle.name, destination))",
        "os.replace(handle.name, destination)",
    ),
]

HOLD_PATIENCE_OMEZARR_FAULTS: list[tuple[str, str, str]] = [
    (
        "replace an array description with no patience for a hold",
        "written_despite_brief_holds(lambda: os.replace(beside, target))",
        "os.replace(beside, target)",
    ),
    (
        "write the group description with no patience for a hold",
        'written_despite_brief_holds(lambda: group.attrs.__setitem__("ome", described))',
        'group.attrs["ome"] = described',
    ),
]

#: Which faults belong to which file, and which tests should notice them.
SUBJECTS: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    ("the commit record", "manifest.py", "test_manifest.py", MANIFEST_FAULTS),
    ("seam ownership", "ownership.py", "test_ownership.py", OWNERSHIP_FAULTS),
    ("stored layout ownership", "model.py", "test_ownership.py", LAYOUT_FAULTS),
    ("what a name may be", "model.py", "test_identity.py", NAMING_FAULTS),
    ("naming and keeping the records", "identity.py", "test_identity.py", IDENTITY_FAULTS),
    (
        "planning a frame that is not square",
        "profiles.py",
        "test_profiles.py",
        PROFILE_PLANNING_FAULTS,
    ),
    ("the zoomed-out picture", "coarse.py", "test_coarse.py", COARSE_FAULTS),
    (
        "earning the right to publish",
        "coordinator.py",
        "test_coordinator.py",
        COORDINATOR_FAULTS,
    ),
    (
        "enforcing publication at the real serving boundary",
        "gateway.py",
        "test_gateway.py",
        GATEWAY_FAULTS,
    ),
    (
        "gating and rolling back position replacements",
        "coordinator.py",
        "test_gateway.py",
        REPLACEMENT_GATE_FAULTS,
    ),
    (
        "patience for a reader's hold on the marker",
        "manifest.py",
        "test_metadata_survives_brief_holds.py",
        HOLD_PATIENCE_FAULTS,
    ),
    (
        "patience for a reader's hold on descriptions",
        "omezarr.py",
        "test_metadata_survives_brief_holds.py",
        HOLD_PATIENCE_OMEZARR_FAULTS,
    ),
]


def _main() -> int:
    unnoticed: list[str] = []

    for title, source_name, test_name, faults in SUBJECTS:
        source = PACKAGE / source_name
        tests = HERE.parent / test_name

        if not require_green_subject(REPO, tests, source):
            return 2
        original = source.read_text(encoding="utf-8")

        print()
        print(f"== {title} ==")
        print(f"{'fault introduced':<52}{'caught?':>9}   noticed by")
        print("-" * 100)
        try:
            for description, find, replace_with in faults:
                if find not in original:
                    print(
                        f"{description:<52}{'STALE':>9}   the code has moved on; update this list"
                    )
                    unnoticed.append(f"{description} (could not be introduced)")
                    continue

                replace_source(source, original.replace(find, replace_with, 1))
                try:
                    result = run_pytest(REPO, tests)
                finally:
                    replace_source(source, original)

                if result.caught_the_fault:
                    print(f"{description:<52}{'yes':>9}   {result.first_failure[:40]}")
                elif result.could_not_run_tests:
                    print(f"{description:<52}{'ERROR':>9}   pytest did not finish")
                    print(result.output)
                    return 2
                else:
                    print(f"{description:<52}{'NO':>9}   nothing noticed")
                    unnoticed.append(description)
        finally:
            replace_source(source, original)
        if not require_restored_subject(REPO, tests, source, original):
            return 2

    print()
    if unnoticed:
        print("These faults went unnoticed, so the tests do not really make these")
        print("claims. Each one should be tested properly, or written down as a")
        print("gap somebody has decided to accept:")
        for description in unnoticed:
            print(f"  - {description}")
        return 1

    print("Every fault was caught. The tests are making the claims they appear to.")
    return 0


def main() -> int:
    with make_interruptions_reach_finally():
        return _main()


if __name__ == "__main__":
    raise SystemExit(main())
