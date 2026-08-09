"""Breaking the image description on purpose, to see whether the tests notice.

A passing test tells you nothing until you have watched it fail for the right
reason. Checks quietly rot: a rename, a refactor, an assertion that was always
true, and something that used to catch a real fault stops catching anything while
still reporting success every morning. Nothing about a green suite reveals that.

So this introduces one fault at a time into :mod:`zmart_live.omezarr`, runs
``test_omezarr.py``, and reports whether the tests caught it. A fault nobody
catches is a claim the tests are not really making, and it should either be
tested properly or written down as a gap somebody has decided to accept.

This module is the one most in need of the treatment, because almost everything
that can go wrong in it goes wrong *quietly*. A picture placed at the wrong
corner still draws. A voxel size that does not grow as you zoom out still draws.
Axes described in the wrong order still draw. The specimen is simply somewhere
else, or the wrong size, or the wrong way round, and nothing anywhere reports a
problem — least of all on the machine that wrote the file, where our own reader
and our own writer share whatever misunderstanding produced it. The faults below
are therefore all of that kind: each one leaves an image that opens perfectly
well and says something untrue about the specimen.

This is not part of the ordinary test run. It takes a few seconds and it edits a
source file while it works, so it is a thing you run deliberately::

    python -m zmart_live.tests.check_the_omezarr_tests_can_fail

It puts the file back after completion, exceptions, Ctrl-C and SIGTERM. No
process can recover after SIGKILL or loss of power; after either, restore the
mutation subject from version control before running anything else. It also
refuses to draw any conclusion unless the unmodified tests are green first — a
red baseline makes every later failure meaningless.
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


def _forget_the_compiled_copy(source: Path) -> None:
    """Throw away Python's saved translation of a file we have just rewritten.

    This is not housekeeping; leaving it out gave a wrong answer here, and the
    wrong answer was invisible.

    Python translates each source file once and keeps the translation in a
    ``__pycache__`` folder beside it. To decide whether that saved copy is still
    good, it compares two things about the source: the second it was last changed
    and how many characters long it is. That is enough almost always, and it is
    not enough here. A fault that swaps one letter for another — ``mode="a"``
    becoming ``mode="w"`` — leaves the file exactly as long as it was, and this
    check introduces it and puts the file back within the same second. Both
    tests therefore say "unchanged", and Python goes on running the saved
    translation of the **broken** version, in every later run, until something
    happens to touch the file again.

    That is precisely what happened while this check was being written. The
    campaign reported every fault caught, put the source back correctly, and the
    ordinary test run afterwards failed in eight places for a fault that was no
    longer anywhere in the file. So the saved translation is thrown away after
    every rewrite, and the next run is made to read the source again.
    """
    cache = source.parent / "__pycache__"
    if not cache.is_dir():
        return
    for saved in cache.glob(f"{source.stem}.*.pyc"):
        saved.unlink(missing_ok=True)


def _put_back(source: Path, original: str) -> None:
    """Restore a mutated file, and make sure the next run really reads it."""
    replace_source(source, original)
    _forget_the_compiled_copy(source)

#: Each entry is a plain-language description of the fault, the text to find, and
#: what to replace it with. They are chosen to be faults a tired person could
#: genuinely introduce on a Friday afternoon — a factor left out of an
#: arithmetic, a guard turned off, two lines written in the order they came to
#: mind — rather than absurd ones nobody would write.
OMEZARR_FAULTS: list[tuple[str, str, str]] = [
    (
        "declare the axes in alphabetical order",
        '    described = []\n    for axis in profile.axes:',
        '    described = []\n    for axis in sorted(profile.axes):',
    ),
    (
        "leave out the version a reader needs before anything else",
        '        "version": OME_ZARR_VERSION,\n        "multiscales": [multiscale],',
        '        "multiscales": [multiscale],',
    ),
    (
        "forget that a zoomed-out voxel covers more ground",
        "                float(profile.voxel_size.get(axis, 1.0)) "
        "* float(level.downsampling.get(axis, 1))",
        "                float(profile.voxel_size.get(axis, 1.0))",
    ),
    (
        "leave every copy's dimensions unnamed",
        '    held["dimension_names"] = names',
        "    pass",
    ),
    (
        "name the dimensions in an order of their own",
        '    names = [axis["name"] for axis in axes]',
        '    names = sorted(axis["name"] for axis in axes)',
    ),
    (
        "never say where on the stage the position sits",
        "        if origin_pixels is not None:",
        "        if False:",
    ),
    (
        "write the corner before the scale it follows",
        '            placing.append(\n                {\n                    "type": "translation",',
        '            placing.insert(\n                0,\n                {\n'
        '                    "type": "translation",',
    ),
    (
        "give the corner as a count of pixels rather than a distance",
        "            float(origin_pixels.get(axis, 0.0)) "
        "* float(profile.voxel_size.get(axis, 1.0))",
        "            float(origin_pixels.get(axis, 0.0))",
    ),
    (
        "measure the voxels in a unit other software ignores",
        '            entry["unit"] = profile.voxel_unit',
        '            entry["unit"] = "um"',
    ),
    (
        "list the copies smallest first",
        "    datasets = []\n    for level in profile.levels:",
        "    datasets = []\n    for level in reversed(profile.levels):",
    ),
    (
        "state the corner for the whole image as well as for each copy",
        '        "datasets": datasets,\n    }',
        '        "datasets": datasets,\n'
        '        "coordinateTransformations": datasets[0]["coordinateTransformations"],\n    }',
    ),
    (
        "leave the colours of light undescribed",
        '    if channels:\n        described["omero"]',
        '    if False:\n        described["omero"]',
    ),
    (
        "call the averaged copies sampled instead",
        '        "type": smaller_copies_made_by,',
        '        "type": "nearest",',
    ),
    (
        "describe a position whose copies were never written",
        "    if missing:",
        "    if False:",
    ),
    (
        "empty the position's folder on the way in",
        '    group = zarr.open_group(str(store), mode="a", zarr_format=3)',
        '    group = zarr.open_group(str(store), mode="w", zarr_format=3)',
    ),
]


# These two faults live in the production coordinator rather than the metadata
# helper.  Keeping them in this campaign matters: an excellent description
# routine is irrelevant if the path used by a live microscope never calls it.
PRODUCTION_PATH_FAULTS: list[tuple[str, str, str]] = [
    (
        "leave a position written by a live run undescribed",
        "        describe_the_position(\n"
        "            store,\n"
        "            self.profile,\n"
        "            name=position_id,\n"
        "            channels=self.channels,\n"
        "            origin_pixels=placement.origin,\n"
        "        )",
        "        pass",
    ),
    (
        "leave the live seamless pyramid undescribed",
        "        describe_the_position(\n"
        "            self.seamless_store,\n"
        "            self.profile,\n"
        '            name="overview-seamless",\n'
        "            channels=self.channels,\n"
        '            origin_pixels={"z": 0, "y": 0, "x": 0},\n'
        "        )",
        "        pass",
    ),
]


#: Which faults belong to which file, and which tests should notice them. Kept in
#: the same shape as the other fault checks in this folder so that a reader who
#: has seen one has seen them all.
SUBJECTS: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    (
        "a position described as a proper image",
        "omezarr.py",
        "test_omezarr.py",
        OMEZARR_FAULTS,
    ),
    (
        "the real live writer calling that description",
        "coordinator.py",
        "test_omezarr.py",
        PRODUCTION_PATH_FAULTS,
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
                _forget_the_compiled_copy(source)
                try:
                    result = run_pytest(REPO, tests)
                finally:
                    _put_back(source, original)

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
            _put_back(source, original)
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
