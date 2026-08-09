"""Breaking the chunk resolver on purpose, to see whether the tests notice.

A passing test tells you nothing until you have watched it fail for the right
reason. That is true everywhere, and it is especially true here. Almost nothing
this module does can go wrong loudly: a byte offset that is one too small still
points at a real place in a real file, and the picture that comes back still
looks like a micrograph. Nobody would notice by looking. The tests are the only
thing standing between a small arithmetic slip and a viewer confidently showing
the wrong specimen.

So this introduces one fault at a time into :mod:`zmart_live.shardlink`, runs the
tests, and reports whether they caught it. A fault nobody catches is a claim the
tests are not really making, and it should either be tested properly or written
down as a gap somebody has decided to accept.

This is not part of the ordinary test run. It edits a source file while it works,
so it is something you run deliberately::

    python -m zmart_live.tests.check_the_shardlink_tests_can_fail

It always puts the file back, including when it is interrupted.

The faults are chosen to be ones a tired person could genuinely make on a
Thursday afternoon: starting to read the table one byte off, forgetting the
checksum that sits beside it, taking the axes in the wrong order, trusting an
offset without checking it fits inside the file, or mistaking "nothing was ever
written here" for "here is a chunk".
"""

from __future__ import annotations

from pathlib import Path

from ._fault_check import replace_source, require_green_baseline, run_pytest

HERE = Path(__file__).resolve()
SOURCE = HERE.parent.parent / "shardlink.py"
TESTS = HERE.parent / "test_shardlink.py"

#: Each entry is a plain-language description of the fault, the text to find in
#: the source, and what to put in its place.
FAULTS: list[tuple[str, str, str]] = [
    (
        "start reading the table one byte late",
        "table_starts_at = -(table_bytes + trailing)",
        "table_starts_at = -(table_bytes + trailing) + 1",
    ),
    (
        "forget the checksum sitting beside the table",
        "trailing = _BYTES_PER_CHECKSUM if has_checksum else 0",
        "trailing = 0",
    ),
    (
        "read an index whose checksum says its bytes changed",
        "if actual != expected:",
        "if False:",
    ),
    (
        "look for the table at the wrong end of the shard",
        'if index_location == "start":',
        'if index_location == "end":',
    ),
    (
        "take the axes in the wrong order",
        "for extent, index in zip(self.chunks_per_shard, within_shard, strict=True):",
        "for extent, index in zip(\n            tuple(reversed(self.chunks_per_shard)),\n"
        "            tuple(reversed(within_shard)),\n            strict=True,\n        ):",
    ),
    (
        "list a shard's chunks under swapped coordinates",
        "    return tuple(reversed(coordinate))",
        "    return tuple(coordinate)",
    ),
    (
        "treat a never-written chunk as though it held data",
        "if offset == _NEVER_WRITTEN and length == _NEVER_WRITTEN:",
        "if False:",
    ),
    (
        "accept an entry marked absent in only one of its numbers",
        "if offset == _NEVER_WRITTEN or length == _NEVER_WRITTEN:",
        "if False:",
    ),
    (
        "trust an offset without checking it fits in the file",
        "if length == 0 or offset + length > shard_bytes or overlaps_index:",
        "if length == 0 or False or overlaps_index:",
    ),
    (
        "let a shard shorter than its own table through",
        "if shard_bytes < table_bytes + trailing:",
        "if False:",
    ),
    (
        "hand back one byte too few for every chunk",
        "return Held(path=shard_file, offset=offset, length=length)",
        "return Held(path=shard_file, offset=offset, length=length - 1)",
    ),
    (
        "start every chunk one byte early",
        "return Held(path=shard_file, offset=offset, length=length)",
        "return Held(path=shard_file, offset=offset - 1, length=length + 1)",
    ),
    (
        "mistake a chunk's coordinate for its shard's",
        "        index // per_shard\n"
        "        for index, per_shard in zip(coordinate, bundling.chunks_per_shard, "
        "strict=True)",
        "        index\n"
        "        for index, per_shard in zip(coordinate, bundling.chunks_per_shard, "
        "strict=True)",
    ),
    (
        "forget that positions start again at zero inside each shard",
        "        index % per_shard\n"
        "        for index, per_shard in zip(coordinate, bundling.chunks_per_shard, "
        "strict=True)",
        "        index\n"
        "        for index, per_shard in zip(coordinate, bundling.chunks_per_shard, "
        "strict=True)",
    ),
    (
        "take an unbundled array to be bundled anyway",
        "    if settings is None:",
        "    if False:",
    ),
    (
        "read the bundle shape as though it were the chunk",
        'inner_chunk = _whole_numbers(settings["chunk_shape"], "chunk shape inside the bundle")',
        "inner_chunk = grid_chunk",
    ),
    (
        "assume the table is always at the end",
        'index_location = str(settings.get("index_location", "end"))',
        'index_location = "end"',
    ),
    (
        "assume a chunk out of range is merely absent",
        "        if not 0 <= index < extent:",
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
