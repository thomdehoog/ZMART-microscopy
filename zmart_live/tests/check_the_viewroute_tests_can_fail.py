"""Breaking the view route on purpose, to see whether the tests notice.

A passing test tells you nothing until you have watched it fail for the right
reason, and that is truer here than almost anywhere else in this project. Nothing
this module does can go wrong loudly. A piece served from one chunk too far to
the left is still a real chunk of a real position; it decodes perfectly, it looks
like a micrograph, and the specimen is simply drawn wrong. Measuring a seam in
bundles rather than chunks does not produce an error either — it produces a
refusal, which an operator reads as "this run cannot be shown" and works around
by changing their acquisition. The tests are the only thing standing between a
small arithmetic slip and a viewer confidently showing the wrong slide.

So this introduces one fault at a time into :mod:`zmart_live.viewroute`, runs the
tests, and reports whether they caught it. A fault nobody catches is a claim the
tests are not really making, and it should either be tested properly or written
down as a gap somebody has decided to accept.

This is not part of the ordinary test run. It edits a source file while it works,
so it is something you run deliberately::

    python -m zmart_live.tests.check_the_viewroute_tests_can_fail

It puts the file back after completion, exceptions, Ctrl-C and SIGTERM. No
process can recover after SIGKILL or loss of power; after either, restore the
mutation subject from version control before running anything else.

The faults are the ones this particular module invites. Measuring alignment in
the wrong unit is the first, because getting it right is the whole reason the
module was written and getting it wrong looks entirely reasonable in the source.
The rest are the confusions that live one line apart: a bundle's coordinate used
where a chunk's belongs, a position's own corner forgotten, a piece nobody has
written yet advertised anyway, a byte range widened until it is the whole file
again.

Three of them are about what the route keeps between requests, which is where
this module was made quicker. Keeping the wrong thing here is unusually tempting
and unusually quiet: remembering the answer for each piece looks like an obvious
saving and would stop a running acquisition from ever filling in; asking the wrong
position for a piece draws the right specimen from the wrong place on the slide;
and reading each position's description again for every piece is not wrong at all,
merely slow, which is why it is caught by a test that counts rather than by one
that compares pixels.
"""

from __future__ import annotations

from pathlib import Path
from shutil import rmtree

from ._fault_check import (
    make_interruptions_reach_finally,
    replace_source,
    require_green_subject,
    require_restored_subject,
    run_pytest,
)

HERE = Path(__file__).resolve()
SOURCE = HERE.parent.parent / "viewroute.py"
TESTS = HERE.parent / "test_viewroute.py"

#: Each entry is a plain-language description of the fault, the text to find in
#: the source, and what to put in its place.
FAULTS: list[tuple[str, str, str]] = [
    (
        "measure a placement in whole bundles instead of chunks",
        "    inner = stored.bundling.inner_chunk[-3:]\n"
        "    bundle = stored.bundling.shard_shape[-3:] if stored.bundling.sharded else None",
        "    bundle = stored.bundling.shard_shape[-3:] if stored.bundling.sharded else None\n"
        "    inner = bundle if bundle is not None else stored.bundling.inner_chunk[-3:]",
    ),
    (
        "tell the view its piece is the bundle rather than the chunk",
        "        chunk=first.bundling.inner_chunk,",
        "        chunk=first.bundling.shard_shape or first.bundling.inner_chunk,",
    ),
    (
        "count a position's place in pixels rather than in chunks",
        "                begins=tuple(tidy.lands_at[axis] // inner[axis] for axis in range(3)),",
        "                begins=tuple(tidy.lands_at[axis] for axis in range(3)),",
    ),
    (
        "start each position one chunk further along the view",
        "            within = tuple(at[axis] - block.begins[axis] for axis in range(3))",
        "            within = tuple(at[axis] - block.begins[axis] + 1 for axis in range(3))",
    ),
    (
        "forget which of its own chunks a trimmed position starts at",
        "                            block.low[axis] + within[axis] for axis in range(3)",
        "                            within[axis] for axis in range(3)",
    ),
    (
        "mistake a chunk's coordinate for its bundle's",
        "        held = self._stored.where_one_chunk_lives(self.inside_the_position)",
        "        held = self._stored.where_one_chunk_lives(\n"
        "            (\n"
        "                *self.inside_the_position[:-3],\n"
        "                *(\n"
        "                    index // per\n"
        "                    for index, per in zip(\n"
        "                        self.inside_the_position[-3:],\n"
        "                        (self._stored.bundling.chunks_per_shard or (1, 1, 1, 1, 1))[-3:],\n"
        "                        strict=True,\n"
        "                    )\n"
        "                ),\n"
        "            )\n"
        "        )",
    ),
    (
        "draw the earliest arrival on top instead of the latest",
        "        found.sort(key=lambda entry: entry[0].arrival, reverse=True)",
        "        found.sort(key=lambda entry: entry[0].arrival)",
    ),
    (
        "read the position's description again for every piece",
        "        held = self._stored.where_one_chunk_lives(self.inside_the_position)",
        "        held = how_the_array_is_stored(self._stored.array)"
        ".where_one_chunk_lives(self.inside_the_position)",
    ),
    (
        "remember the answer for each piece, so a run stops filling in",
        "        held = self._stored.where_one_chunk_lives(self.inside_the_position)",
        '        held = globals().setdefault("_answers_already_given", {}).setdefault(\n'
        "            (self.position, self.inside_the_position),\n"
        "            self._stored.where_one_chunk_lives(self.inside_the_position),\n"
        "        )",
    ),
    (
        "advertise ground a position covers but has not written",
        "        return self.where_this_chunk_is(chunk_coordinate) is not None",
        "        return bool(self.claims_on(chunk_coordinate))",
    ),
    (
        "treat a chunk that was never written as though it held data",
        "        held = self._stored.where_one_chunk_lives(self.inside_the_position)\n"
        "        if held is None:\n"
        "            return None",
        "        held = self._stored.where_one_chunk_lives(self.inside_the_position)\n"
        "        if held is None:\n"
        "            held = self._stored.where_one_chunk_lives(\n"
        "                tuple(0 for _ in self.inside_the_position)\n"
        "            )\n"
        "        if held is None:\n"
        "            return None",
    ),
    (
        "hand over the whole bundle rather than the chunk inside it",
        "        return Serving(\n"
        "            path=held.path,\n"
        "            offset=held.offset,\n"
        "            length=held.length,",
        "        return Serving(\n"
        "            path=held.path,\n"
        "            offset=0,\n"
        "            length=held.path.stat().st_size,",
    ),
    (
        "start every piece one byte early",
        "        opened.seek(serving.offset)",
        "        opened.seek(serving.offset - 1)",
    ),
    (
        "hand back one byte too few for every piece",
        "        found = opened.read(serving.length)",
        "        found = opened.read(serving.length - 1)",
    ),
    (
        "let a position answer for ground beyond the part it shows",
        "            if all(0 <= within[axis] < block.extent[axis] for axis in range(3)):",
        "            if all(0 <= within[axis] for axis in range(3)):",
    ),
    (
        "ignore where a position is taken from when sizing what it shows",
        "        size = tidy.size or tuple(\n"
        "            shape[axis] - tidy.taken_from[axis] for axis in range(3)\n"
        "        )",
        "        size = tidy.size or tuple(shape[axis] for axis in range(3))",
    ),
    (
        "accept a position stored differently from the rest",
        "            _refuse_positions_stored_differently(first, stored)",
        "            pass",
    ),
    (
        "declare the view with the bundle's codecs rather than the chunk's",
        "        chunk_codecs = tuple(inside)",
        "        chunk_codecs = tuple(content.get('codecs') or ())",
    ),
    (
        "let a view declare bundles it is not being served",
        "    if bundled:",
        "    if False:",
    ),
    (
        "answer for a moment the position has never recorded",
        "        if any(\n"
        "            index >= extent\n"
        "            for index, extent in zip(self.inside_the_position, grid, strict=True)\n"
        "        ):",
        "        if False:",
    ),
]


def put_the_source_back(original: str) -> None:
    """Restore the mutated file, and throw away Python's compiled copy of it.

    Restoring the text is not quite enough on its own, and the reason is worth
    knowing because it once made a whole run of this check meaningless. Python
    keeps a compiled copy of each module beside it and decides whether that copy
    is still good by looking at the source file's size and the second in which it
    last changed. A fault that replaces one character with another leaves the file
    exactly the same size, and putting it back a fraction of a second later leaves
    it in the same second — so the compiled copy of the *faulty* module goes on
    being used afterwards, and every later result is about code nobody meant to
    run. Throwing the compiled copy away costs a few milliseconds and removes the
    possibility entirely.
    """
    replace_source(SOURCE, original)
    for compiled in SOURCE.parent.rglob("__pycache__"):
        rmtree(compiled, ignore_errors=True)


def _main() -> int:
    unnoticed: list[str] = []

    repository = SOURCE.parent.parent
    if not require_green_subject(repository, TESTS, SOURCE):
        return 2
    original = SOURCE.read_text(encoding="utf-8")

    print(f"{'fault introduced':<52}{'caught?':>9}   noticed by")
    print("-" * 100)
    try:
        for description, find, replace_with in FAULTS:
            if find not in original:
                print(f"{description:<52}{'STALE':>9}   the code has moved on; update this list")
                unnoticed.append(f"{description} (could not be introduced)")
                continue

            replace_source(SOURCE, original.replace(find, replace_with, 1))
            try:
                result = run_pytest(repository, TESTS)
            finally:
                put_the_source_back(original)

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
        put_the_source_back(original)
    if not require_restored_subject(repository, TESTS, SOURCE, original):
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
