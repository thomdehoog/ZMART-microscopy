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

It always puts the file back, including when it is interrupted.

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

from ._fault_check import replace_source, require_green_baseline, run_pytest

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
        "os.fsync(writing.fileno())\n        os.replace",
        "os.replace",
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
        "give the extra pixel of an odd overlap to both neighbours",
        "half_before = overlap // 2 if has_one_before else 0",
        "half_before = (overlap - overlap // 2) if has_one_before else 0",
    ),
    (
        "let a tile keep its far strip even when a neighbour needs it",
        "if has_one_beyond or not keep_the_far_edge:",
        "if False:",
    ),
    (
        "take an interior tile from an offset instead of its own corner",
        "shown[axis] = Interval(0, step)",
        "shown[axis] = Interval(overlap, step + overlap)",
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
        "let one position sit in two squares",
        "if position_id in seen:",
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
        "if not path.exists():\n                complaints.append(",
        "if False:\n                complaints.append(",
    ),
    (
        "call the pixels ready even when something was complained about",
        "pyramids_ready=pieces_read > 0 and not about_pixels,",
        "pyramids_ready=True,",
    ),
    (
        "let an unpublished position into the run-wide picture",
        "if placement.position_id not in committed:",
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
    # The raw overlap view. Every fault below ends with one of two measurements
    # of the same specimen quietly gone, which is the one thing that view is
    # built to make impossible.
    (
        "let the tile written last win in the overlap",
        "self.tile_stop_of(placement.position_id),",
        "0,",
    ),
    (
        "drop the dimension that keeps overlapping tiles apart",
        "self.tile_stop_count,\n            self.timepoints,",
        "1,\n            self.timepoints,",
    ),
    (
        "let an unpublished position into the raw overlap view",
        "# Not published yet means not shown here either, exactly as in the\n"
        "            # seamless view above.\n"
        "            if placement.position_id not in committed:",
        "# Not published yet means not shown here either, exactly as in the\n"
        "            # seamless view above.\n"
        "            if False:",
    ),
    (
        "call the raw overlap view ready without looking at it",
        "raw_overlap_ready=compared > 0 and not about_the_overlaps,",
        "raw_overlap_ready=True,",
    ),
    (
        "say a raw overlap view that is missing is merely unreadable",
        "if not self.raw_overlap_store.exists():\n"
        "            complaints.append(\n"
        '                "The raw overlap view has not been built yet,',
        "if False:\n"
        "            complaints.append(\n"
        '                "The raw overlap view has not been built yet,',
    ),
    (
        "trust the raw overlap view instead of comparing it to the pixels",
        "if as_stored.shape != as_written.shape or not np.array_equal(\n"
        "                as_stored, as_written\n"
        "            ):",
        "if False and np.array_equal(\n"
        "                as_stored, as_written\n"
        "            ):",
    ),
    (
        "report the raw overlap comparison as done without saying how much",
        "return int(as_stored.size)",
        "return 1",
    ),
]

#: Which faults belong to which file, and which tests should notice them.
SUBJECTS: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    ("the commit record", "manifest.py", "test_manifest.py", MANIFEST_FAULTS),
    ("seam ownership", "ownership.py", "test_ownership.py", OWNERSHIP_FAULTS),
    ("stored layout ownership", "model.py", "test_ownership.py", LAYOUT_FAULTS),
    ("the zoomed-out picture", "coarse.py", "test_coarse.py", COARSE_FAULTS),
    (
        "earning the right to publish",
        "coordinator.py",
        "test_coordinator.py",
        COORDINATOR_FAULTS,
    ),
]


def main() -> int:
    unnoticed: list[str] = []

    for title, source_name, test_name, faults in SUBJECTS:
        source = PACKAGE / source_name
        tests = HERE.parent / test_name
        original = source.read_text(encoding="utf-8")

        if not require_green_baseline(REPO, tests):
            return 2

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


if __name__ == "__main__":
    raise SystemExit(main())
