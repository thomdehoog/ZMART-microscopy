"""How long it takes to say where one chunk lives, on shards the size we really write.

Why this file exists
--------------------

The seamless view answers every request the viewer makes by naming a file, a
first byte and a number of bytes. Filling one screen with picture takes dozens of
those answers, so the cost of a single answer is not a detail — it is the
difference between a picture that appears and a picture that never settles.

This script measures that cost on bundles the size an acquisition actually
produces, and prints it. It is not part of the test suite: it writes hundreds of
megabytes and takes a couple of minutes, and a suite nobody is willing to wait
for stops being run. Run it deliberately::

    python -m zmart_live.tests.measure_the_resolver

What is measured, and why in this shape
---------------------------------------

The house rule for measuring here is written down in
``zmart-viewer/LESSONS_ome_zarr_and_neuroglancer.md``: one row is not a trend, so
every claim is made across several sizes and read as a shape rather than as a
figure; counts are reported beside timings, because a count is the same on a busy
machine and a timing is not; and the machine is named, because an absolute
millisecond travels badly between computers while a slope travels well.

The sizes come from the acquisition profile rather than from what is convenient
to loop over. :func:`zmart_live.profiles.plan_the_writing` bundles one whole
frame across ``y`` and ``x`` together with a slab of ``z`` planes chosen to land
near a target file size, so for the overview plan — a 1152-pixel frame in
128-pixel chunks — one bundle holds nine chunks by nine chunks by ninety-six
planes, which is 7,776 chunk positions and a table of contents 124 kilobytes
long. That table is what has to be read and checked before any chunk in the
bundle can be pointed at.

Only two planes of each bundle are actually filled in. That is deliberate and it
does not weaken the measurement: a bundle's table has one entry for every chunk
position it could hold whether or not anything was written there, so the table is
exactly as large as a full bundle's, while the file takes seconds rather than
minutes to write.

The three ways of answering that are compared
---------------------------------------------

*As it was.* Every request read the whole table off the disk and checked it, and
the check was made one bit at a time as the definition of the checksum is
written. This script keeps its own copy of that arrangement, so that the before
and the after are measured in the same place on the same afternoon rather than
being remembered from a note.

*Reading afresh, now.* The same full read of the table, but the check made by
looking each byte up in a small table worked out once when the module is
imported. This is the cost that still has to be paid whenever a bundle really has
changed — which, while a run is going, is every time the acquisition writes into
the bundle the viewer is watching.

*Remembered.* The table kept from the previous request, because the bundle's file
is byte for byte the one already read. This is the ordinary case for everything a
run has finished with, which is nearly all of a long run.

A fourth measurement, in its own small table at the end, is what it costs to read
an array's own ``zarr.json`` again for every request instead of once. That one
was not guessed at: it was too small to see behind the table reading, and only
became worth doing something about once the table reading stopped dominating.
"""

from __future__ import annotations

import platform
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import zarr

from zmart_live import shardlink
from zmart_live.shardlink import (
    ShardIndex,
    forget_every_remembered_index,
    how_the_array_is_stored,
    how_the_remembering_is_going,
    where_one_chunk_lives,
)

#: The arrangements measured, each being a frame width in pixels, the chunk that
#: frame is cut into, and how many planes one bundle spans. The first four are the
#: overview plan at growing bundle depths, which is what makes a shape visible
#: rather than a single figure; the last is the larger frame the same profile
#: chooses for a bigger camera.
ARRANGEMENTS: tuple[tuple[int, int, int], ...] = (
    (1152, 128, 12),
    (1152, 128, 24),
    (1152, 128, 48),
    (1152, 128, 96),
    (2304, 256, 24),
)

#: How many planes of each bundle are filled in. Two is enough for every chunk
#: asked about below to be a real one, and the table of contents is the full size
#: either way.
PLANES_WRITTEN = 2

#: About how many chunks the viewer asks for to fill one screen. A screenful of a
#: 1152-pixel frame in 128-pixel chunks is a few dozen, and measuring a run of
#: about that many in a row is the situation this whole arrangement exists for.
CHUNKS_IN_A_SCREENFUL = 48


def the_checksum_one_bit_at_a_time(content: bytes) -> int:
    """The checksum exactly as it used to be worked out, kept here for comparison.

    This is a copy of what :mod:`zmart_live.shardlink` did before, following the
    definition of the checksum literally: eight turns of a loop for every byte.
    Keeping the old arrangement here is what lets the before and the after be
    measured side by side in one run, on one machine, rather than one of them
    being a number somebody wrote down last week.
    """
    checksum = 0xFFFFFFFF
    for byte in content:
        checksum ^= byte
        for _ in range(8):
            checksum = (checksum >> 1) ^ 0x82F63B78 if checksum & 1 else checksum >> 1
    return (~checksum) & 0xFFFFFFFF


def a_position(folder: Path, frame: int, chunk: int, slab: int) -> Path:
    """Write one position bundled the way the overview profile bundles them.

    The picture is a slab of planes of a single frame, cut into square chunks and
    packed so that one file holds the whole frame across every plane of the slab.
    Only the first couple of planes are filled in, which is what a position looks
    like a moment after the run reaches it.
    """
    array = zarr.create_array(
        store=str(folder),
        shape=(1, 1, slab, frame, frame),
        chunks=(1, 1, 1, chunk, chunk),
        shards=(1, 1, slab, frame, frame),
        dtype="uint16",
        compressors="auto",
        fill_value=0,
    )
    specimen = np.random.default_rng(0).integers(
        0, 60000, size=(PLANES_WRITTEN, frame, frame), dtype=np.uint16
    )
    array[0, 0, 0:PLANES_WRITTEN] = specimen
    return folder


def a_screenful(chunks_across: int) -> list[tuple[int, int, int, int, int]]:
    """The chunk coordinates the viewer asks for to fill one screen.

    A viewer never asks for one chunk. It asks for every chunk that touches the
    part of the specimen on screen, which is a few dozen of them, one after
    another, nearly all out of the same bundle. Measuring a single request on its
    own would miss the whole point, so a run of them is measured and the cost
    reported per request.
    """
    wanted = [
        (0, 0, plane, row, column)
        for plane in range(PLANES_WRITTEN)
        for row in range(chunks_across)
        for column in range(chunks_across)
    ]
    return wanted[:CHUNKS_IN_A_SCREENFUL]


def seconds_per_request(ask, wanted, rounds: int = 3, at_least: float = 0.2) -> float:
    """Time a screenful of requests, several times over, and take the middle round.

    The middle round rather than the fastest or the mean, because this machine is
    shared: one round that happened to run while something else was busy would
    otherwise decide the answer. When a single screenful goes by too quickly to
    time honestly, it is repeated until enough time has passed to measure.
    """
    taken = []
    for _ in range(rounds):
        answered = 0
        started = time.perf_counter()
        while True:
            for coordinate in wanted:
                ask(coordinate)
            answered += len(wanted)
            elapsed = time.perf_counter() - started
            if elapsed >= at_least:
                break
        taken.append(elapsed / answered)
    return statistics.median(taken)


def roughly_how_many_bytes(index: ShardIndex) -> int:
    """About how much memory one remembered table takes.

    Rough on purpose: it counts the list of answers and each written entry inside
    it, which is where nearly all of it is, and does not chase every last object
    header. It is here to put a real number against the limit the module sets on
    how much may be remembered, rather than leaving that limit as a guess.
    """
    total = sys.getsizeof(index.places)
    for place in index.places:
        if place is not None:
            total += sys.getsizeof(place) + sum(sys.getsizeof(number) for number in place)
    return total


def reading_the_table(position: Path, wanted) -> dict[str, float]:
    """Measure the three ways of answering, on one position."""
    answers: dict[str, float] = {}

    forget_every_remembered_index()
    ordinary = shardlink._crc32c
    shardlink._crc32c = the_checksum_one_bit_at_a_time
    try:
        stored = how_the_array_is_stored(position)
        answers["as it was"] = seconds_per_request(
            lambda at: _without_remembering(stored, at), wanted, rounds=1, at_least=0.0
        )
    finally:
        shardlink._crc32c = ordinary

    forget_every_remembered_index()
    stored = how_the_array_is_stored(position)
    answers["afresh now"] = seconds_per_request(
        lambda at: _without_remembering(stored, at), wanted, rounds=3, at_least=0.0
    )

    forget_every_remembered_index()
    stored = how_the_array_is_stored(position)
    stored.where_one_chunk_lives(wanted[0])
    answers["remembered"] = seconds_per_request(stored.where_one_chunk_lives, wanted)
    return answers


def _without_remembering(stored, at) -> None:
    """Ask where a chunk lives with the memory of tables emptied first.

    Emptying it before each request is how the old behaviour — read and check the
    whole table again, every single time — is reproduced exactly.
    """
    forget_every_remembered_index()
    stored.where_one_chunk_lives(at)


def main() -> int:
    print("Where one chunk lives: what it costs to answer, per request")
    print()
    print(f"machine   {platform.platform()}")
    print(f"processor {platform.processor()}")
    print(f"python    {sys.version.split()[0]}    zarr {zarr.__version__}")
    print()
    print("Reading the bundle's table of contents")
    print()
    header = (
        f"{'frame':>6} {'chunk':>6} {'planes':>7} {'entries':>9} {'table KB':>9} "
        f"{'as it was':>11} {'afresh now':>11} {'remembered':>11} {'held KB':>9}"
    )
    print(header)
    print("-" * len(header))

    workspace = Path(tempfile.mkdtemp(prefix="measure-the-resolver-"))
    positions: list[tuple[int, int, int, Path]] = []
    try:
        for frame, chunk, slab in ARRANGEMENTS:
            position = a_position(workspace / f"pos-{frame}-{slab}", frame, chunk, slab)
            positions.append((frame, chunk, slab, position))

            stored = how_the_array_is_stored(position)
            entries = stored.bundling.chunks_per_shard_total
            wanted = a_screenful(frame // chunk)
            answers = reading_the_table(position, wanted)

            forget_every_remembered_index()
            stored.where_one_chunk_lives(wanted[0])
            held = sum(roughly_how_many_bytes(index) for index in shardlink._REMEMBERED.values())

            print(
                f"{frame:>6} {chunk:>6} {slab:>7} {entries:>9,} {entries * 16 / 1024:>9,.0f} "
                f"{answers['as it was'] * 1000:>10.2f}m"
                f"{answers['afresh now'] * 1000:>10.2f}m"
                f"{answers['remembered'] * 1e6:>10.1f}u"
                f"{held / 1024:>9,.0f}"
            )

        print()
        print("(m is milliseconds per request, u is microseconds per request.)")
        print()
        print("How many tables were read off the disk, for one screenful of "
              f"{CHUNKS_IN_A_SCREENFUL} requests")
        print()
        counts = f"{'frame':>6} {'planes':>7} {'read from disk':>15} {'from memory':>12}"
        print(counts)
        print("-" * len(counts))
        for frame, chunk, slab, position in positions:
            forget_every_remembered_index()
            stored = how_the_array_is_stored(position)
            for at in a_screenful(frame // chunk):
                stored.where_one_chunk_lives(at)
            going = how_the_remembering_is_going()
            print(
                f"{frame:>6} {slab:>7} {going.read_from_disk:>15} "
                f"{going.answered_from_memory:>12}"
            )

        print()
        print("Reading the array's own description again for every request, "
              "instead of once")
        print()
        again = f"{'frame':>6} {'planes':>7} {'read each time':>15} {'read once':>11}"
        print(again)
        print("-" * len(again))
        for frame, chunk, slab, position in positions:
            wanted = a_screenful(frame // chunk)
            forget_every_remembered_index()
            where_one_chunk_lives(position, wanted[0])
            each_time = seconds_per_request(
                lambda at, position=position: where_one_chunk_lives(position, at), wanted
            )
            stored = how_the_array_is_stored(position)
            once = seconds_per_request(stored.where_one_chunk_lives, wanted)
            print(
                f"{frame:>6} {slab:>7} {each_time * 1e6:>14.1f}u {once * 1e6:>10.1f}u"
            )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
