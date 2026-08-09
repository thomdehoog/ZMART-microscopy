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

It always puts the file back, including when it is interrupted.

The faults are the ones this particular module invites. Measuring alignment in
the wrong unit is the first, because getting it right is the whole reason the
module was written and getting it wrong looks entirely reasonable in the source.
The rest are the confusions that live one line apart: a bundle's coordinate used
where a chunk's belongs, a position's own corner forgotten, a piece nobody has
written yet advertised anyway, a byte range widened until it is the whole file
again.
"""

from __future__ import annotations

from pathlib import Path

from ._fault_check import replace_source, require_green_baseline, run_pytest

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
        "                return block, tuple(\n"
        "                    block.low[axis] + within[axis] for axis in range(3)\n"
        "                )",
        "                return block, tuple(\n"
        "                    within[axis] for axis in range(3)\n"
        "                )",
    ),
    (
        "mistake a chunk's coordinate for its bundle's",
        "        held = where_one_chunk_lives(block.stored.array, coordinate)",
        "        held = where_one_chunk_lives(\n"
        "            block.stored.array,\n"
        "            (\n"
        "                *coordinate[:-3],\n"
        "                *(\n"
        "                    index // per\n"
        "                    for index, per in zip(\n"
        "                        coordinate[-3:],\n"
        "                        (block.stored.bundling.chunks_per_shard or (1, 1, 1, 1, 1))[-3:],\n"
        "                        strict=True,\n"
        "                    )\n"
        "                ),\n"
        "            ),\n"
        "        )",
    ),
    (
        "advertise ground a position covers but has not written",
        "        return self.where_this_chunk_is(chunk_coordinate) is not None",
        "        return self._position_covering(tuple(chunk_coordinate)[-3:]) is not None",
    ),
    (
        "treat a chunk that was never written as though it held data",
        "        if held is None:\n"
        "            # Nothing was ever written at that chunk. The view should advertise",
        "        if held is None and False:\n"
        "            # Nothing was ever written at that chunk. The view should advertise",
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
        "let two positions claim the same piece of the view",
        "    _refuse_two_positions_claiming_the_same_piece(blocks)",
        "    pass",
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
        "            index >= extent for index, extent in zip(coordinate, grid, strict=True)\n"
        "        ):",
        "        if False:",
    ),
]


def main() -> int:
    original = SOURCE.read_text(encoding="utf-8")
    unnoticed: list[str] = []

    repository = SOURCE.parent.parent
    if not require_green_baseline(repository, TESTS):
        return 2

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
                replace_source(SOURCE, original)

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
        replace_source(SOURCE, original)

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
