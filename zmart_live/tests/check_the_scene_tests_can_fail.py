"""Breaking the scene on purpose, to see whether the tests notice.

A passing test tells you nothing until you have watched it fail for the right
reason. Checks quietly rot: a rename, a refactor, an assertion that was always
true, and something that used to catch a real fault stops catching anything while
still reporting success every morning. Nothing about a green suite reveals that.

So this introduces one fault at a time into :mod:`zmart_live.scene`, runs
``test_scene.py``, and reports whether the tests caught it. A fault nobody catches
is a claim the tests are not really making, and it should either be tested
properly or written down as a gap somebody has decided to accept.

The faults are the ones this part of the system is genuinely prone to, and two of
them have cost this project real time before:

**Handing the drawing engine one source per position.** It is the obvious thing to
do — each position knows where it sits, so why not let the engine place them? —
and it was measured making a viewer draw twenty-four frames in five seconds where
one linked image managed 255.

**Putting the revision in the store's address.** It looks like the tidy way to
defeat a stale cache. It makes the engine treat every commit as a brand new data
source and never let the old one go.

This is not part of the ordinary test run. It takes a few seconds and it edits a
source file while it works, so it is a thing you run deliberately::

    python -m zmart_live.tests.check_the_scene_tests_can_fail

It puts the file back after completion, exceptions, Ctrl-C and SIGTERM. No
process can recover after SIGKILL or loss of power; after either, restore the
mutation subject from version control before running anything else.
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
#: genuinely introduce on a Friday afternoon — a tidy-looking shortcut, a dropped
#: term from a key, a number taken from the run when a better one was to hand.
SCENE_FAULTS: list[tuple[str, str, str]] = [
    (
        "hand the engine one source per position",
        "        if image.role == POSITION_ROLE:",
        "        if False:",
    ),
    (
        "put the revision in the store's address",
        "            url=_the_address_of(store_root, image.path),",
        "            url=_the_address_of(store_root, image.path)"
        ' + f"?revision={_revision_for(image, committed)}",',
    ),
    (
        "let the two overviews share one row of controls",
        "    return (image.role, image.image_id, channel)",
        "    return (image.image_id, channel)",
    ),
    (
        "leave the part an image plays out of its identity",
        '        return f"{self.role}/{self.image_id}"',
        "        return self.image_id",
    ),
    (
        "place every position at the run's origin",
        "            axis: float(placement.origin.get(axis, 0)) * voxel_size[axis] "
        "for axis in axes",
        "            axis: 0.0 for axis in axes",
    ),
    (
        "sort the axes instead of keeping the declared order",
        "    axes = tuple(profile.axes)",
        "    axes = tuple(sorted(profile.axes))",
    ),
    (
        "ignore what has actually been committed",
        "            revision=_revision_for(image, committed),",
        "            revision=0,",
    ),
    (
        "use the run-wide counter where a per-position one was known",
        "    return max(committed.by_store.get(position_id, 0) for position_id in image.draws)",
        "    return committed.revision",
    ),
    (
        "forget the voxel size, so everything is one unit across",
        "    return {axis: float(profile.voxel_size.get(axis, 1.0)) for axis in profile.axes}",
        "    return {axis: 1.0 for axis in profile.axes}",
    ),
    (
        "build a seamless view for positions that never touched",
        '    return profile.topology == "grid" and bool(profile.tiled_axes)',
        "    return True",
    ),
    (
        "leave the raw view with no way to step between overlapping tiles",
        '    images.append(an_overview("non_seamless", "raw", "tile"))',
        '    images.append(an_overview("non_seamless", "raw", None))',
    ),
    (
        "pin every row to the first channel",
        "                channel_index=first_index,",
        "                channel_index=0,",
    ),
    (
        "let a view forget which positions it shows",
        "            draws=position_ids,",
        "            draws=(),",
    ),
    (
        "list every position in what goes to the browser",
        '            "draws_positions": self.draws_positions,',
        '            "draws_positions": self.draws_positions,'
        ' "draws": list(range(self.draws_positions)),',
    ),
]

#: Which faults belong to which file, and which tests should notice them.
SUBJECTS: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    ("the scene and what the viewer is handed", "scene.py", "test_scene.py", SCENE_FAULTS),
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
        print(f"{'fault introduced':<58}{'caught?':>9}   noticed by")
        print("-" * 106)
        try:
            for description, find, replace_with in faults:
                if find not in original:
                    print(
                        f"{description:<58}{'STALE':>9}   the code has moved on; update this list"
                    )
                    unnoticed.append(f"{description} (could not be introduced)")
                    continue

                replace_source(source, original.replace(find, replace_with, 1))
                try:
                    result = run_pytest(REPO, tests)
                finally:
                    replace_source(source, original)

                if result.caught_the_fault:
                    print(f"{description:<58}{'yes':>9}   {result.first_failure[:40]}")
                elif result.could_not_run_tests:
                    print(f"{description:<58}{'ERROR':>9}   pytest did not finish")
                    print(result.output)
                    return 2
                else:
                    print(f"{description:<58}{'NO':>9}   nothing noticed")
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
