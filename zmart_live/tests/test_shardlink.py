"""Proving that a chunk lifted out by byte range really is the same chunk.

This is the check the whole linked-view idea rests on. The seamless quick-look
view does not copy pixels; it points at the ones already written. If a pointer is
off by even one byte, the viewer does not fail — it shows a picture. It shows the
wrong picture, confidently, and nothing anywhere says so. So the tests here are
built around one comparison, made over and over in different circumstances:

    take the bytes this module says a chunk occupies, hand them to Zarr to
    decode, and check they come back exactly equal to what Zarr itself returns
    for that region of the image.

Nothing weaker than "exactly equal" is any use. A shifted or partly-wrong chunk
still looks like a micrograph.

How the comparison is made
--------------------------

To decode an extracted chunk we do not reach into Zarr's internals. We build a
second, very small image on disk — one chunk in size, chunked and compressed
exactly the way the chunks inside the shard are — and drop the extracted bytes in
as its one and only chunk file. Reading that little image back through the
ordinary ``zarr.open_array`` is then a genuine end-to-end decode, using the same
code path a viewer would. If the byte range were wrong, the decode would either
fail outright or produce different pixels, and either way the test notices.

The arrays here are deliberately small — 512 by 512 pixels, chunked 128 and
bundled 256 — so the whole file runs in a couple of seconds. The arithmetic being
tested does not care how big the image is, and a test suite nobody is willing to
wait for stops being run.

A note on what could not be tested directly
-------------------------------------------

Zarr will happily write the table of contents at either end of the shard, so both
are exercised against real files. What is *not* available is a way to make Zarr
write a shard with no checksum after the table, since it always includes one. The
parser is therefore tested against a hand-built shard for that case, which is
weaker — it proves the parser reads such a file correctly, not that a real writer
produces one we agree with.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import time
import warnings
from pathlib import Path

import numpy as np
import pytest
import zarr

from zmart_live import shardlink
from zmart_live.model import ZmartLiveError
from zmart_live.shardlink import (
    STAMPS_STILL_MOVING_NS,
    Held,
    describe_the_bundling,
    forget_every_remembered_index,
    how_the_array_is_stored,
    how_the_remembering_is_going,
    read_the_index,
    where_one_chunk_lives,
)

# Working out the checksum is the writer's job, not a reader's, but two tests
# below have to stand in for a writer: they alter a shard's table of contents on
# purpose and then have to leave a checksum that matches, or the reader would
# refuse the file for the wrong reason. Borrowing the module's own is the only way
# to be sure the two agree.
from zmart_live.shardlink import _crc32c as the_checksum_of

# Zarr's older creation entry point is the only one that lets us choose where the
# table of contents sits, and it warns that it is on its way out. We use it only
# in the one test that needs that choice, and we are not interested in the notice.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="zarr")


# ---------------------------------------------------------------------------
# Building images to test against, and taking chunks back out of them
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def start_with_nothing_remembered():
    """Give every test the same empty memory of shard tables to start from.

    The tables already read are kept for the whole program, which is the point of
    keeping them, but it means one test could otherwise be answered from something
    an earlier test left behind. Several of the tests below count how many tables
    were read off the disk, and a count is only worth anything if it starts at
    zero.
    """
    forget_every_remembered_index()
    yield
    forget_every_remembered_index()


def a_picture(shape, seed=0):
    """Some pixels with plenty of variety in them.

    Real specimen images are not smooth, and a chunk of flat grey would compress
    to almost nothing and would look identical to its neighbours — which is
    exactly the situation in which a wrong byte range would go unnoticed. Random
    values make every chunk distinguishable from every other one.
    """
    generator = np.random.default_rng(seed)
    return generator.integers(0, 60000, size=shape, dtype=np.uint16)


def an_image(folder, shape, chunk, shard, compressed=True, pixels=None):
    """Write a small sharded image and return it along with the pixels put in it."""
    codecs = "auto" if compressed else None
    array = zarr.create_array(
        store=str(folder),
        shape=shape,
        chunks=chunk,
        shards=shard,
        dtype="uint16",
        compressors=codecs,
        fill_value=0,
    )
    if pixels is None:
        pixels = a_picture(shape)
    array[...] = pixels
    return folder, pixels


def decoded(extracted_bytes, folder, chunk, like):
    """Decode one chunk's raw bytes by letting Zarr read them as a tiny image.

    ``like`` is the array the bytes came out of; its encoding settings are copied
    so that the little scratch image decodes them exactly as the original would.
    Doing it this way keeps the test honest: the decode goes through Zarr's own
    public reading path rather than through anything this test knows about the
    format.
    """
    description = json.loads((Path(like) / "zarr.json").read_text())
    inner_codecs = None
    for codec in description["codecs"]:
        if codec.get("name") == "sharding_indexed":
            inner_codecs = codec["configuration"]["codecs"]
    assert inner_codecs is not None, "this helper is only for sharded images"

    compressed = any(c.get("name") not in ("bytes",) for c in inner_codecs)
    shutil.rmtree(folder, ignore_errors=True)
    scratch = zarr.create_array(
        store=str(folder),
        shape=chunk,
        chunks=chunk,
        dtype="uint16",
        compressors="auto" if compressed else None,
        fill_value=0,
    )
    del scratch

    # The scratch image must encode its pixels the same way the shard's chunks
    # were encoded, or the bytes we are about to drop in would not be readable.
    # Checking it here turns a confusing decode failure into a clear message.
    scratch_codecs = json.loads((Path(folder) / "zarr.json").read_text())["codecs"]
    assert scratch_codecs == inner_codecs, (
        f"the scratch image encodes chunks as {scratch_codecs}, but the shard's "
        f"chunks are encoded as {inner_codecs}"
    )

    target = Path(folder).joinpath("c", *("0" for _ in chunk))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(extracted_bytes)
    return zarr.open_array(str(folder))[...]


def region_of(coordinate, chunk):
    """The slice of the whole image that one chunk coordinate covers."""
    return tuple(
        slice(index * step, (index + 1) * step)
        for index, step in zip(coordinate, chunk, strict=True)
    )


def every_chunk(bundling):
    """Walk every chunk coordinate in an image, in a settled order."""
    from itertools import product

    return product(*(range(extent) for extent in bundling.chunks_in_array))


def check_every_chunk_matches(tmp_path, image, pixels, chunk):
    """The load-bearing comparison, made for every chunk of an image.

    For each chunk in turn: ask where it lives, read exactly those bytes, decode
    them, and require the result to equal what Zarr gives for the same region.
    Chunks that were never written are required to be reported as absent *and* to
    be all fill value in the image, which is the other half of the same claim.
    """
    bundling = describe_the_bundling(image)
    source = zarr.open_array(str(image))
    scratch = tmp_path / "scratch.zarr"

    seen_written = 0
    seen_absent = 0
    for coordinate in every_chunk(bundling):
        held = where_one_chunk_lives(image, coordinate)
        expected = source[region_of(coordinate, chunk)]

        if held is None:
            seen_absent += 1
            assert np.array_equal(expected, np.zeros_like(expected)), (
                f"chunk {coordinate} was reported as never written, but the image "
                f"has real pixels there"
            )
            continue

        seen_written += 1
        with held.path.open("rb") as opened:
            opened.seek(held.offset)
            raw = opened.read(held.length)
        assert len(raw) == held.length
        assert np.array_equal(decoded(raw, scratch, chunk, image), expected), (
            f"chunk {coordinate} decoded from its byte range does not match what "
            f"zarr reads for the same region"
        )

    assert seen_written > 0, "the image under test had no written chunks at all"
    return seen_written, seen_absent


# ---------------------------------------------------------------------------
# The load-bearing test, in the ordinary cases
# ---------------------------------------------------------------------------


class TestAChunkTakenOutByByteRangeIsTheSameChunk:
    """Every written chunk, extracted as bytes, decodes to identical pixels."""

    def test_with_compression(self, tmp_path):
        image, pixels = an_image(tmp_path / "compressed.zarr", (512, 512), (128, 128), (256, 256))
        written, absent = check_every_chunk_matches(tmp_path, image, pixels, (128, 128))
        assert written == 16, "a 512x512 image chunked at 128 holds sixteen chunks"
        assert absent == 0, "every chunk was written, so none should be reported absent"

    def test_without_compression(self, tmp_path):
        """The same claim for raw, uncompressed chunks.

        Compression changes how long each chunk is and therefore where the next
        one starts, so an arithmetic mistake can easily show up in one case and
        not the other. Both are worth checking.
        """
        image, pixels = an_image(
            tmp_path / "raw.zarr", (512, 512), (128, 128), (256, 256), compressed=False
        )
        written, absent = check_every_chunk_matches(tmp_path, image, pixels, (128, 128))
        assert (written, absent) == (16, 0)

    def test_in_three_dimensions(self, tmp_path):
        """A z-stack, where getting the axis order wrong has somewhere to hide.

        With two axes and a square shard, several plausible mistakes about entry
        order happen to give the same answer. A stack with a different number of
        chunks along each axis removes that coincidence.
        """
        image, pixels = an_image(
            tmp_path / "stack.zarr", (8, 256, 512), (2, 128, 128), (4, 256, 256)
        )
        bundling = describe_the_bundling(image)
        assert bundling.chunks_per_shard == (2, 2, 2)
        assert bundling.chunks_in_array == (4, 2, 4)
        written, absent = check_every_chunk_matches(tmp_path, image, pixels, (2, 128, 128))
        assert (written, absent) == (32, 0)


# ---------------------------------------------------------------------------
# Chunks that were never written
# ---------------------------------------------------------------------------


class TestAChunkThatWasNeverWritten:
    """An absent chunk is reported as absent, and its neighbours still resolve."""

    def test_absent_and_present_chunks_in_one_shard(self, tmp_path):
        """Both halves of the claim together, because either alone proves little.

        A resolver that always answered "never written" would pass a test that
        only checked the absent chunk, and a resolver that never noticed absence
        would pass one that only checked the present chunk. The two chunks here
        sit in the *same* shard file, so the same table of contents is being read
        for both answers.
        """
        pixels = np.zeros((512, 512), dtype=np.uint16)
        pixels[0:128, 0:128] = a_picture((128, 128), seed=3)
        image, _ = an_image(
            tmp_path / "sparse.zarr",
            (512, 512),
            (128, 128),
            (256, 256),
            compressed=False,
            pixels=pixels,
        )

        present = where_one_chunk_lives(image, (0, 0))
        absent = where_one_chunk_lives(image, (1, 0))

        assert absent is None, "a chunk holding only the fill value should be absent"
        assert present is not None, "the written neighbour in the same shard was lost"
        assert present.path.name == "0", "both chunks live in the shard c/0/0"

        with present.path.open("rb") as opened:
            opened.seek(present.offset)
            raw = opened.read(present.length)
        assert np.array_equal(
            decoded(raw, tmp_path / "scratch.zarr", (128, 128), image), pixels[0:128, 0:128]
        )

    def test_a_shard_that_was_never_written_at_all(self, tmp_path):
        """A whole missing bundle is absence, not damage.

        While a run is in progress, most of the image does not exist yet. Asking
        about a chunk out there has to be an ordinary "nothing there" rather than
        an error, or the viewer could not ask about anything it had not already
        seen.
        """
        pixels = np.zeros((512, 512), dtype=np.uint16)
        pixels[0:128, 0:128] = 11
        image, _ = an_image(
            tmp_path / "partly.zarr",
            (512, 512),
            (128, 128),
            (256, 256),
            compressed=False,
            pixels=pixels,
        )
        assert not (Path(image) / "c" / "1" / "1").exists()
        assert where_one_chunk_lives(image, (3, 3)) is None
        assert where_one_chunk_lives(image, (0, 0)) is not None


# ---------------------------------------------------------------------------
# Where the table of contents sits
# ---------------------------------------------------------------------------


def an_image_with_the_table_at_the_start(folder, shape, chunk, shard):
    """Write a sharded image whose table of contents sits at the front of the file.

    The format allows the table at either end, and readers in the wild produce
    both. Zarr's newer creation call has no setting for it, so this goes through
    the older one, which accepts a fully described codec.
    """
    from zarr.codecs import BytesCodec, ShardingCodec, ZstdCodec

    bundling = ShardingCodec(
        chunk_shape=chunk,
        codecs=[BytesCodec(), ZstdCodec()],
        index_location="start",
    )
    array = zarr.create(
        store=str(folder),
        shape=shape,
        chunks=shard,
        dtype="uint16",
        zarr_format=3,
        codecs=[bundling],
        fill_value=0,
    )
    pixels = a_picture(shape, seed=5)
    array[...] = pixels
    return folder, pixels


class TestTheTableOfContentsAtEitherEnd:
    """Both permitted places for the table are read correctly."""

    def test_the_table_at_the_end(self, tmp_path):
        image, _ = an_image(tmp_path / "at_end.zarr", (512, 512), (128, 128), (256, 256))
        assert describe_the_bundling(image).index_location == "end"

    def test_the_table_at_the_start(self, tmp_path):
        image, pixels = an_image_with_the_table_at_the_start(
            tmp_path / "at_start.zarr", (512, 512), (128, 128), (256, 256)
        )
        bundling = describe_the_bundling(image)
        assert bundling.index_location == "start"
        assert bundling.chunks_per_shard == (2, 2)

        written, absent = check_every_chunk_matches(tmp_path, image, pixels, (128, 128))
        assert (written, absent) == (16, 0)

    def test_a_shard_with_no_checksum_after_the_table(self, tmp_path):
        """Read a hand-built shard that carries no checksum bytes.

        Zarr always writes a checksum after the table, so there is no way to have
        it produce this file for us. The parser still has to cope, because the
        format permits it and other writers use it. Building the shard by hand
        proves the parser reads it correctly; it does not, and cannot, prove that
        a real writer would agree with us about it. That is a genuine limit of
        this test and is written down rather than glossed over.
        """
        first = b"first chunk bytes"
        second = b"the second chunk, longer"
        table = struct.pack(
            "<QQQQQQQQ",
            0,
            len(first),
            2**64 - 1,
            2**64 - 1,
            len(first),
            len(second),
            2**64 - 1,
            2**64 - 1,
        )
        shard = first + second + table

        index = read_the_index(
            shard,
            inner_chunk=(128, 128),
            shard_shape=(256, 256),
            index_location="end",
            has_checksum=False,
        )
        assert index.chunks_per_shard == (2, 2)
        assert index.how_many_written == 2
        assert index.place_of((0, 0)) == (0, len(first))
        assert index.place_of((0, 1)) is None
        assert index.place_of((1, 0)) == (len(first), len(second))
        assert index.place_of((1, 1)) is None
        assert shard[0 : len(first)] == first
        assert shard[len(first) : len(first) + len(second)] == second

    def test_entries_are_in_row_major_order(self, tmp_path):
        """The last axis varies fastest, and a lopsided shard proves which is which.

        This shard is one chunk tall and four wide, so a reader that walked the
        axes the other way round would run off the end rather than quietly
        returning a neighbour's bytes. The lengths are all different so that any
        confusion between entries shows up immediately.
        """
        lengths = [3, 5, 7, 11]
        offsets = [0, 3, 8, 15]
        table = b"".join(
            struct.pack("<QQ", offset, length)
            for offset, length in zip(offsets, lengths, strict=True)
        )
        shard = bytes(sum(lengths)) + table

        index = read_the_index(
            shard,
            inner_chunk=(128, 128),
            shard_shape=(128, 512),
            index_location="end",
            has_checksum=False,
        )
        assert index.chunks_per_shard == (1, 4)
        assert [index.place_of((0, column)) for column in range(4)] == [
            (0, 3),
            (3, 5),
            (8, 7),
            (15, 11),
        ]


# ---------------------------------------------------------------------------
# Images that are not bundled at all
# ---------------------------------------------------------------------------


class TestAnImageThatIsNotBundled:
    """One chunk per file is reported as such, not mistaken for a shard."""

    def test_it_is_reported_as_unsharded(self, tmp_path):
        folder = tmp_path / "plain.zarr"
        array = zarr.create_array(
            store=str(folder),
            shape=(512, 512),
            chunks=(128, 128),
            dtype="uint16",
            compressors=None,
            fill_value=0,
        )
        array[...] = a_picture((512, 512), seed=7)

        bundling = describe_the_bundling(folder)
        assert bundling.sharded is False
        assert bundling.inner_chunk == (128, 128)
        assert bundling.shard_shape is None
        assert bundling.chunks_per_shard is None
        assert bundling.chunks_in_array == (4, 4)
        assert bundling.chunks_per_shard_total == 1

    def test_a_chunk_of_it_is_its_whole_file(self, tmp_path):
        """With nothing bundled, the chunk is the file, so the answer is the file.

        Answering this rather than refusing means a linked view can be built the
        same way whether or not the source happens to be bundled, which is one
        fewer special case for the caller to get wrong.
        """
        folder = tmp_path / "plain.zarr"
        array = zarr.create_array(
            store=str(folder),
            shape=(512, 512),
            chunks=(128, 128),
            dtype="uint16",
            compressors=None,
            fill_value=0,
        )
        pixels = np.zeros((512, 512), dtype=np.uint16)
        pixels[0:128, 0:128] = a_picture((128, 128), seed=9)
        array[...] = pixels

        held = where_one_chunk_lives(folder, (0, 0))
        assert held is not None
        assert held.offset == 0
        assert held.length == held.path.stat().st_size
        assert held == Held(path=held.path, offset=0, length=128 * 128 * 2)

        assert where_one_chunk_lives(folder, (3, 3)) is None

    def test_the_bundled_and_unbundled_answers_agree(self, tmp_path):
        """The same pixels stored both ways give the same bytes for a chunk.

        This is the sharpest statement of what the module is for. Bundling is
        supposed to change only the number of files, not the contents of a chunk,
        and here that is checked rather than assumed.
        """
        pixels = a_picture((512, 512), seed=11)

        plain = tmp_path / "plain.zarr"
        array = zarr.create_array(
            store=str(plain),
            shape=(512, 512),
            chunks=(128, 128),
            dtype="uint16",
            compressors=None,
            fill_value=0,
        )
        array[...] = pixels

        bundled, _ = an_image(
            tmp_path / "bundled.zarr",
            (512, 512),
            (128, 128),
            (256, 256),
            compressed=False,
            pixels=pixels,
        )

        for coordinate in [(0, 0), (1, 2), (3, 3)]:
            here = where_one_chunk_lives(plain, coordinate)
            there = where_one_chunk_lives(bundled, coordinate)
            assert here is not None and there is not None
            with here.path.open("rb") as opened:
                opened.seek(here.offset)
                loose = opened.read(here.length)
            with there.path.open("rb") as opened:
                opened.seek(there.offset)
                packed = opened.read(there.length)
            assert loose == packed, f"chunk {coordinate} differs between the two layouts"


# ---------------------------------------------------------------------------
# Damage, and refusing to guess
# ---------------------------------------------------------------------------


class TestDamagedOrUnreadableFiles:
    """A shard that cannot be trusted is refused rather than half-read."""

    def test_a_shard_cut_short_is_refused(self, tmp_path):
        """Truncation must raise, because the alternative is silent nonsense.

        A shard cut off partway — a disk that filled up, a copy interrupted —
        still looks like a file. If we read its table anyway we would hand back a
        byte range that a viewer would dutifully display. Refusing is the only
        safe answer, and the message says what most likely happened.
        """
        image, _ = an_image(
            tmp_path / "cut.zarr", (512, 512), (128, 128), (256, 256), compressed=False
        )
        shard = Path(image) / "c" / "0" / "0"
        whole = shard.read_bytes()
        assert where_one_chunk_lives(image, (0, 0)) is not None

        shard.write_bytes(whole[: len(whole) // 2])
        with pytest.raises(ZmartLiveError) as refusal:
            where_one_chunk_lives(image, (0, 0))
        assert any(
            phrase in str(refusal.value)
            for phrase in ("cut short", "shorter than it says", "checksum")
        )

    def test_a_shard_with_only_its_table_left_is_refused(self, tmp_path):
        """Losing the chunks but keeping the table is caught by the length check.

        This is the awkward case: the table parses perfectly and every entry
        looks sensible, but the bytes it points at are gone. The only thing that
        catches it is insisting that each chunk end inside the file it claims to
        be in.
        """
        image, _ = an_image(
            tmp_path / "hollow.zarr", (512, 512), (128, 128), (256, 256), compressed=False
        )
        shard = Path(image) / "c" / "0" / "0"
        whole = shard.read_bytes()
        table_and_checksum = 4 * 16 + 4
        shard.write_bytes(whole[-table_and_checksum:])

        with pytest.raises(ZmartLiveError) as refusal:
            where_one_chunk_lives(image, (0, 0))
        assert "cut short" in str(refusal.value)

    def test_a_shard_too_small_to_hold_its_own_table_is_refused(self, tmp_path):
        """A file far shorter than the table it should contain is stopped early.

        This is the crudest kind of damage — a shard of a handful of bytes, which
        is what an interrupted write can leave behind — and it deserves its own
        check because it has to be caught *before* anything tries to read a table
        out of it. Without an early refusal the reader would be asked to seek to
        a position before the beginning of the file, and what came back would
        depend on the operating system rather than on anything we decided.
        """
        stub = tmp_path / "barely_written"
        stub.write_bytes(b"not much here")
        with pytest.raises(ZmartLiveError) as refusal:
            read_the_index(
                stub,
                inner_chunk=(128, 128),
                shard_shape=(256, 256),
                index_location="end",
            )
        assert "table of contents alone" in str(refusal.value)

        with pytest.raises(ZmartLiveError) as refusal:
            read_the_index(
                b"not much here",
                inner_chunk=(128, 128),
                shard_shape=(256, 256),
                index_location="end",
            )
        assert "table of contents alone" in str(refusal.value)

    def test_an_entry_cannot_point_beyond_the_end_without_touching_the_index(self):
        """An out-of-file offset must not be caught only by index-overlap checks."""
        table = struct.pack("<QQ", 100, 4)
        shard = bytes(16) + table

        with pytest.raises(ZmartLiveError, match="file is only 32 bytes"):
            read_the_index(
                shard,
                inner_chunk=(128, 128),
                shard_shape=(128, 128),
                index_location="end",
                has_checksum=False,
            )

    def test_a_half_marked_entry_is_refused(self, tmp_path):
        """An entry absent in one number and present in the other is damage.

        A never-written chunk is marked absent in *both* its numbers. One of each
        cannot happen by design, so it means the bytes have been corrupted, and
        reading on would mean inventing an interpretation.
        """
        table = struct.pack("<QQ", 2**64 - 1, 40) + struct.pack("<QQ", 0, 40)
        shard = bytes(80) + table
        with pytest.raises(ZmartLiveError) as refusal:
            read_the_index(
                shard,
                inner_chunk=(128, 128),
                shard_shape=(128, 256),
                index_location="end",
                has_checksum=False,
            )
        assert "half marked" in str(refusal.value)

    def test_a_corrupted_index_checksum_is_refused(self, tmp_path):
        """A changed but in-bounds offset can otherwise show the wrong real chunk."""
        image, _ = an_image(
            tmp_path / "bad-checksum.zarr",
            (512, 512),
            (128, 128),
            (256, 256),
            compressed=False,
        )
        shard = Path(image) / "c" / "0" / "0"
        damaged = bytearray(shard.read_bytes())
        damaged[-1] ^= 1
        shard.write_bytes(damaged)

        with pytest.raises(ZmartLiveError, match="CRC32C checksum"):
            where_one_chunk_lives(image, (0, 0))

    def test_two_index_entries_cannot_claim_the_same_bytes(self):
        table = struct.pack("<QQ", 0, 16) + struct.pack("<QQ", 8, 16)
        with pytest.raises(ZmartLiveError, match="overlapping bytes"):
            read_the_index(
                bytes(32) + table,
                inner_chunk=(128, 128),
                shard_shape=(128, 256),
                index_location="end",
                has_checksum=False,
            )

    def test_a_file_that_is_not_an_array_is_refused(self, tmp_path):
        empty = tmp_path / "nothing"
        empty.mkdir()
        with pytest.raises(ZmartLiveError) as refusal:
            describe_the_bundling(empty)
        assert "zarr.json" in str(refusal.value)

    def test_a_bundle_that_is_not_a_whole_number_of_chunks_is_refused(self, tmp_path):
        with pytest.raises(ZmartLiveError) as refusal:
            read_the_index(
                bytes(4096),
                inner_chunk=(100, 100),
                shard_shape=(256, 256),
                index_location="end",
            )
        assert "whole number of chunks" in str(refusal.value)

    def test_a_coordinate_outside_the_image_is_refused(self, tmp_path):
        """Asking for a chunk that cannot exist is a mistake, not an absence.

        This is deliberately different from asking for a chunk that could exist
        but was never written, which comes back as ``None``. A coordinate past
        the edge of the image is a caller's arithmetic error, and saying so is
        far more use than a quiet "nothing there".
        """
        image, _ = an_image(
            tmp_path / "edge.zarr", (512, 512), (128, 128), (256, 256), compressed=False
        )
        with pytest.raises(ZmartLiveError) as refusal:
            where_one_chunk_lives(image, (0, 99))
        assert "count chunks rather than pixels" in str(refusal.value)

        with pytest.raises(ZmartLiveError) as refusal:
            where_one_chunk_lives(image, (0, 0, 0))
        assert "one number per axis" in str(refusal.value)

        with pytest.raises(ZmartLiveError, match="whole numbers"):
            where_one_chunk_lives(image, (0.5, 0))

    def test_an_unknown_index_byte_order_is_refused(self, tmp_path):
        image, _ = an_image(
            tmp_path / "big-endian-index.zarr",
            (512, 512),
            (128, 128),
            (256, 256),
            compressed=False,
        )
        description = Path(image) / "zarr.json"
        metadata = json.loads(description.read_text(encoding="utf-8"))
        sharding = next(
            codec for codec in metadata["codecs"] if codec["name"] == "sharding_indexed"
        )
        sharding["configuration"]["index_codecs"][0]["configuration"]["endian"] = "big"
        description.write_text(json.dumps(metadata), encoding="utf-8")

        with pytest.raises(ZmartLiveError, match="little-endian"):
            describe_the_bundling(image)

    def test_chunk_metadata_cannot_escape_the_array_folder(self, tmp_path):
        folder = tmp_path / "unsafe-key.zarr"
        zarr.create_array(
            store=str(folder),
            shape=(128, 128),
            chunks=(128, 128),
            dtype="uint16",
            compressors=None,
            fill_value=0,
        )
        description = folder / "zarr.json"
        metadata = json.loads(description.read_text(encoding="utf-8"))
        metadata["chunk_key_encoding"]["configuration"]["separator"] = "/../"
        description.write_text(json.dumps(metadata), encoding="utf-8")

        with pytest.raises(ZmartLiveError, match="outside its array folder"):
            where_one_chunk_lives(folder, (0, 0))


# ---------------------------------------------------------------------------
# Describing a whole shard in one pass
# ---------------------------------------------------------------------------


class TestDescribingAWholeShard:
    """Walking a shard's contents gives every written chunk and nothing else."""

    def test_written_chunks_are_listed_with_their_places(self, tmp_path):
        # The two written chunks sit side by side rather than on the diagonal.
        # A pair on the diagonal reads the same whichever way round the axes are
        # taken, so it would let a swapped row and column pass unnoticed.
        pixels = np.zeros((512, 512), dtype=np.uint16)
        pixels[0:128, 0:128] = a_picture((128, 128), seed=13)
        pixels[0:128, 128:256] = a_picture((128, 128), seed=17)
        image, _ = an_image(
            tmp_path / "twoofour.zarr",
            (512, 512),
            (128, 128),
            (256, 256),
            compressed=False,
            pixels=pixels,
        )
        bundling = describe_the_bundling(image)
        index = read_the_index(
            Path(image) / "c" / "0" / "0",
            inner_chunk=bundling.inner_chunk,
            shard_shape=bundling.shard_shape,
            index_location=bundling.index_location,
            has_checksum=bundling.has_checksum,
        )

        assert index.entry_count == 4
        assert index.how_many_written == 2
        listed = dict(index.written_chunks())
        assert set(listed) == {(0, 0), (0, 1)}
        for coordinate, (offset, length) in listed.items():
            assert index.place_of(coordinate) == (offset, length)
            assert offset + length <= index.shard_bytes
        assert not index.holds((1, 0))
        assert not index.holds((1, 1))
        assert index.holds((0, 1))

    def test_a_position_outside_the_shard_is_refused(self, tmp_path):
        index = read_the_index(
            bytes(64) + b"".join(struct.pack("<QQ", offset, 16) for offset in (0, 16, 32, 48)),
            inner_chunk=(128, 128),
            shard_shape=(256, 256),
            index_location="end",
            has_checksum=False,
        )
        with pytest.raises(ZmartLiveError) as refusal:
            index.place_of((2, 0))
        assert "falls outside this shard" in str(refusal.value)


# ---------------------------------------------------------------------------
# Remembering what a shard's table of contents said
# ---------------------------------------------------------------------------


def swap_two_entries_in_the_table(shard, first, second, entries):
    """Exchange two entries in a shard's table, writing the file back in place.

    This stands in for a writer that has produced the bundle differently — the
    same chunks, packed in another order — which is the change most likely to go
    unnoticed, because the file stays exactly the same length and every byte range
    it describes still points at real, decodable pixels.

    The file is opened for updating rather than replaced, so it keeps the same
    inode: the file system's own numbered slot for it. That matters, because it
    means this test is checking that a changed *file* is noticed, not merely that
    a *new* file is.

    The checksum is worked out again afterwards, since a reader would otherwise
    refuse the shard for the wrong reason and the test would pass without ever
    having asked the question.
    """
    raw = bytearray(Path(shard).read_bytes())
    table_at = len(raw) - entries * 16 - 4
    here, there = table_at + first * 16, table_at + second * 16
    raw[here : here + 16], raw[there : there + 16] = (
        raw[there : there + 16],
        raw[here : here + 16],
    )
    table = bytes(raw[table_at : table_at + entries * 16])
    raw[table_at + entries * 16 :] = the_checksum_of(table).to_bytes(4, "little")
    with Path(shard).open("r+b") as opened:
        opened.write(bytes(raw))


def the_bytes_at(held):
    """Read exactly the stretch of a file one answer describes."""
    with held.path.open("rb") as opened:
        opened.seek(held.offset)
        return opened.read(held.length)


def the_clock_can_tell_a_change_now(file) -> None:
    """Wait until ``file`` is old enough for its next change to move its stamps.

    A table read while its file is younger than ``STAMPS_STILL_MOVING_NS`` is
    used but deliberately not remembered, because a rewrite that soon might not
    move the file's timestamps at all. Tests below that are about the
    remembering itself — counting reads, watching the memory's limits, or
    watching a changed identity get noticed — first let their freshly written
    fixtures age past that reach, the way any real bundle has by the time a
    viewer returns to it.
    """
    while True:
        age = time.time_ns() - os.stat(file).st_mtime_ns
        if age >= STAMPS_STILL_MOVING_NS:
            return
        time.sleep(max((STAMPS_STILL_MOVING_NS - age) / 1e9, 0.005))


class TestRememberingWhatABundlesTableSaid:
    """A table already read is reused, and only ever for the file it came from.

    Reading a bundle's table is the expensive part of answering, and a viewer
    filling one screen asks about dozens of chunks out of the same few bundles. So
    a table that has been read is kept. Everything in this class is about the one
    danger that creates: a table that no longer describes the file it came from
    does not produce an error. It produces a byte range that decodes perfectly and
    shows the wrong part of the specimen.
    """

    def test_one_bundle_is_read_once_however_often_it_is_asked_about(self, tmp_path):
        """Four questions about one bundle, and only the first reads the table.

        The count is what is checked rather than a stopwatch. A count says the
        same thing on a busy machine as on an idle one, which a timing does not.
        """
        image, _ = an_image(
            tmp_path / "one.zarr", (256, 256), (128, 128), (256, 256), compressed=False
        )
        # A table is only remembered once its file has cooled; this test is
        # about the remembering, so the freshly written bundle ages first.
        the_clock_can_tell_a_change_now(Path(image) / "c" / "0" / "0")
        stored = how_the_array_is_stored(image)
        for coordinate in ((0, 0), (0, 1), (1, 0), (1, 1)):
            assert stored.where_one_chunk_lives(coordinate) is not None

        going = how_the_remembering_is_going()
        assert going.read_from_disk == 1, "the same bundle should be read once"
        assert going.answered_from_memory == 3
        assert going.bundles_held == 1

    def test_a_bundle_written_again_is_never_answered_from_the_old_table(self, tmp_path):
        """The test this whole arrangement has to pass.

        The bundle is written again with its chunks in a different order. It keeps
        exactly the same length and exactly the same inode, so nothing about it
        looks new except when it changed. A reader still holding the old table
        would hand back a byte range that is a real chunk, decodes without
        complaint, and shows the wrong quarter of the frame — which is the failure
        nobody would catch by looking at the screen.

        So the check is not that the answer changed. It is that the pixels the
        answer leads to are the ones now stored at that place.

        Two different mechanisms carry that promise, and both are exercised here.
        A rewrite can land so soon after the write before it that the file's
        timestamps do not move at all — Windows stamps files from a clock cached
        for about sixteen milliseconds, and its ``st_ctime`` is creation time
        besides — and there the protection is that a table this fresh was never
        remembered in the first place (``STAMPS_STILL_MOVING_NS``). Once the file
        has cooled the table IS remembered, and the protection changes hands: a
        later rewrite necessarily moves the stamp, and the changed identity is
        what makes the old table unusable.
        """
        image, pixels = an_image(
            tmp_path / "rewritten.zarr", (256, 256), (128, 128), (256, 256), compressed=False
        )
        stored = how_the_array_is_stored(image)
        before = stored.where_one_chunk_lives((0, 0))
        its_neighbour = stored.where_one_chunk_lives((0, 1))
        assert before is not None and its_neighbour is not None

        shard = Path(image) / "c" / "0" / "0"
        was = shard.stat()
        swap_two_entries_in_the_table(shard, 0, 1, entries=4)
        now = shard.stat()

        # If either of these ever stops being true, this test has quietly lost its
        # teeth and would pass without asking anything, so it says so instead.
        assert now.st_size == was.st_size, "the point is a file that did not change size"
        assert now.st_ino == was.st_ino, "the point is the same file, not a new one"

        after = stored.where_one_chunk_lives((0, 0))
        assert after is not None
        assert (after.offset, after.length) == (its_neighbour.offset, its_neighbour.length)
        assert np.array_equal(
            decoded(the_bytes_at(after), tmp_path / "scratch.zarr", (128, 128), image),
            pixels[0:128, 128:256],
        ), "the chunk served is not the one now stored at that place in the bundle"

        # Now with the file cooled, so this reading is remembered and the next
        # rewrite must be noticed by the identity moving rather than by never
        # having been remembered.
        the_clock_can_tell_a_change_now(shard)
        remembered = stored.where_one_chunk_lives((0, 0))
        assert remembered is not None
        swap_two_entries_in_the_table(shard, 0, 1, entries=4)  # back the way it was
        assert shard.stat().st_mtime_ns != now.st_mtime_ns, (
            "a rewrite of a cooled file did not move its modification time, so "
            "the identity a remembered table is checked against cannot notice "
            "changes on this file system at all"
        )
        restored = stored.where_one_chunk_lives((0, 0))
        assert restored is not None
        assert (restored.offset, restored.length) == (before.offset, before.length)
        assert np.array_equal(
            decoded(the_bytes_at(restored), tmp_path / "scratch2.zarr", (128, 128), image),
            pixels[0:128, 0:128],
        ), "the chunk served is not the one now stored at that place in the bundle"

    def test_a_bundle_the_run_is_still_writing_into_fills_in(self, tmp_path):
        """A position half written now must not look half written for ever.

        This is the worry that once kept tables from being remembered at all, and
        it is the reason the memory is tied to the file rather than to the path.
        While a run is going, chunks are still landing in a bundle the viewer is
        already watching. A remembered table would go on saying "nothing was ever
        written there" long after something was, and an operator would watch a
        position stop filling in and never recover.
        """
        pixels = np.zeros((256, 256), dtype=np.uint16)
        pixels[0:128, 0:128] = a_picture((128, 128), seed=21)
        image, _ = an_image(
            tmp_path / "growing.zarr",
            (256, 256),
            (128, 128),
            (256, 256),
            compressed=False,
            pixels=pixels,
        )
        stored = how_the_array_is_stored(image)
        assert stored.where_one_chunk_lives((0, 0)) is not None
        assert stored.where_one_chunk_lives((1, 1)) is None, (
            "nothing has been written in that corner yet"
        )

        arrived = a_picture((128, 128), seed=22)
        zarr.open_array(str(image), mode="r+")[128:256, 128:256] = arrived

        held = stored.where_one_chunk_lives((1, 1))
        assert held is not None, "the chunk that has since arrived is still reported absent"
        assert np.array_equal(
            decoded(the_bytes_at(held), tmp_path / "scratch.zarr", (128, 128), image),
            arrived,
        )

    def test_two_positions_whose_bundles_share_a_name_are_not_confused(self, tmp_path):
        """Every position calls its first bundle ``c/0/0``, and they are all different.

        A run has thousands of positions, and the file inside each of them is named
        by where the chunk sits in *that* position, so the names repeat endlessly.
        Two positions whose bundles happen to be packed differently would then be
        served each other's byte ranges, which is a picture of the right specimen
        taken from the wrong place on the slide.
        """
        crowded = a_picture((256, 256), seed=31)
        one, _ = an_image(
            tmp_path / "posA.zarr",
            (256, 256),
            (128, 128),
            (256, 256),
            compressed=False,
            pixels=crowded,
        )
        nearly_empty = np.zeros((256, 256), dtype=np.uint16)
        nearly_empty[128:256, 128:256] = a_picture((128, 128), seed=32)
        other, _ = an_image(
            tmp_path / "posB.zarr",
            (256, 256),
            (128, 128),
            (256, 256),
            compressed=False,
            pixels=nearly_empty,
        )

        from_one = where_one_chunk_lives(one, (1, 1))
        from_other = where_one_chunk_lives(other, (1, 1))
        assert from_one is not None and from_other is not None
        assert from_one.path.name == from_other.path.name == "0", (
            "both positions really do name this bundle the same"
        )
        assert from_one.offset != from_other.offset, (
            "the two bundles happen to be packed alike, so this test cannot tell "
            "whether they were confused"
        )
        assert np.array_equal(
            decoded(the_bytes_at(from_other), tmp_path / "scratch.zarr", (128, 128), other),
            nearly_empty[128:256, 128:256],
        )

    def test_a_bundle_read_as_a_different_shape_is_not_answered_from_memory(self, tmp_path):
        """The same file, read as though it were bundled differently, is read afresh.

        How large a chunk is and how many of them a bundle holds come from the
        array's own description, and they decide where in the file the table sits
        and how long it is. So they are part of what a remembered table is
        remembered against. Reading the same file under a different pair of shapes
        has to go back to the file, where it finds — correctly — that the bytes
        there are not a table of that size.
        """
        image, _ = an_image(
            tmp_path / "shapes.zarr", (256, 256), (128, 128), (256, 256), compressed=False
        )
        shard = Path(image) / "c" / "0" / "0"
        proper = read_the_index(shard, inner_chunk=(128, 128), shard_shape=(256, 256))
        assert proper.entry_count == 4

        with pytest.raises(ZmartLiveError):
            read_the_index(shard, inner_chunk=(256, 256), shard_shape=(256, 256))

    def test_a_shard_handed_over_as_bytes_is_never_remembered(self, tmp_path):
        """Bytes in memory have no file behind them to notice a change in.

        Remembering them would mean remembering against nothing at all, so it is
        not done. Reading the same bytes twice reads them twice.
        """
        image, _ = an_image(
            tmp_path / "asbytes.zarr", (256, 256), (128, 128), (256, 256), compressed=False
        )
        raw = (Path(image) / "c" / "0" / "0").read_bytes()
        for _ in range(2):
            read_the_index(raw, inner_chunk=(128, 128), shard_shape=(256, 256))
        going = how_the_remembering_is_going()
        assert (going.read_from_disk, going.answered_from_memory) == (2, 0)
        assert going.bundles_held == 0

    def test_the_remembering_can_be_turned_off(self, tmp_path):
        """Asked not to remember, it reads the table every time.

        This is what the benchmark uses to find out what reading one cold really
        costs, so it has to genuinely read.
        """
        image, _ = an_image(
            tmp_path / "cold.zarr", (256, 256), (128, 128), (256, 256), compressed=False
        )
        shard = Path(image) / "c" / "0" / "0"
        for _ in range(3):
            read_the_index(
                shard, inner_chunk=(128, 128), shard_shape=(256, 256), remember=False
            )
        going = how_the_remembering_is_going()
        assert (going.read_from_disk, going.answered_from_memory) == (3, 0)
        assert going.bundles_held == 0


class TestTheMemoryHasALimit:
    """A run lasting all night cannot fill memory with tables it no longer needs.

    The limits are set deliberately low here so the tests stay quick. What is being
    checked is that there *is* a limit and that reaching it forgets something, not
    what the everyday numbers happen to be.
    """

    def three_bundles(self, tmp_path):
        """Three separate positions, each with one bundle holding four chunks.

        Aged past the clock's reach before they are handed over, because every
        test asking for them is about the remembering and its limits, and a
        table is only remembered once its file has cooled.
        """
        images = [
            an_image(
                tmp_path / f"pos{which}.zarr",
                (256, 256),
                (128, 128),
                (256, 256),
                compressed=False,
                pixels=a_picture((256, 256), seed=40 + which),
            )[0]
            for which in range(3)
        ]
        the_clock_can_tell_a_change_now(Path(images[-1]) / "c" / "0" / "0")
        return images

    def test_one_description_is_read_once_however_often_it_is_asked(
            self, tmp_path):
        """Asking about the same array twice reads its zarr.json once.

        The number this pins was measured, not imagined: publishing one
        position at 12,769 committed re-read every position's description —
        152,300 zarr.json opens, thirty-three of the forty-eight seconds a
        single replacement cost. The description is written once with the
        store and rewritten only by the writer's own describe step, so it
        earns the same remembering the shard tables already have.
        """
        image, _ = an_image(
            tmp_path / "one.zarr", (256, 256), (128, 128), (256, 256),
            compressed=False)
        # A description is only remembered once its file has cooled; this test
        # is about the remembering, so the freshly written store ages first.
        the_clock_can_tell_a_change_now(Path(image) / "zarr.json")
        first = how_the_array_is_stored(image)
        second = how_the_array_is_stored(image)
        assert second.description == first.description
        going = how_the_remembering_is_going()
        assert going.descriptions_read_from_disk == 1, (
            "the second ask re-read a description that cannot have changed"
        )
        assert going.descriptions_answered_from_memory == 1

    def test_a_description_written_again_is_never_answered_from_memory(
            self, tmp_path):
        """The remembering must not outlive the file — the shard tables' rule.

        The writer rewrites a store's description whenever it writes the
        position again; an answer from memory after that would describe the
        store as it used to be, and every number downstream — chunk shapes,
        bundle layout — would be quietly wrong about real bytes.
        """
        import os
        import time

        image, _ = an_image(
            tmp_path / "rewritten.zarr", (256, 256), (128, 128), (256, 256),
            compressed=False)
        how_the_array_is_stored(image)

        described = Path(image) / "zarr.json"
        held = json.loads(described.read_text(encoding="utf-8"))
        held["attributes"] = {"rewritten": "yes"}
        described.write_text(json.dumps(held), encoding="utf-8")
        later = time.time_ns() + 2_000_000_000
        os.utime(described, ns=(later, later))

        second = how_the_array_is_stored(image)
        assert second.description.get("attributes") == {"rewritten": "yes"}, (
            "the rewritten description was answered from memory"
        )
        assert how_the_remembering_is_going().descriptions_read_from_disk == 2

    def test_only_so_many_bundles_are_kept(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shardlink, "BUNDLES_REMEMBERED_AT_MOST", 2)
        monkeypatch.setattr(shardlink, "PLACES_REMEMBERED_AT_MOST", 10**9)

        for image in self.three_bundles(tmp_path):
            assert where_one_chunk_lives(image, (0, 0)) is not None

        going = how_the_remembering_is_going()
        assert going.bundles_held == 2, "a third bundle should have pushed the first out"
        assert going.read_from_disk == 3

    def test_only_so_many_chunk_positions_are_kept(self, tmp_path, monkeypatch):
        """The limit that really matters is counted in chunk positions.

        Bundles are not all the same size — one of the overview plan's holds nearly
        eight thousand chunk positions — so a limit counted in bundles alone would
        mean something quite different on one instrument than on another. The
        lesson behind that is in ``zmart-viewer/LESSONS_ome_zarr_and_neuroglancer.md``:
        an index with an entry per chunk, kept for a whole run, was once sixteen
        gigabytes of memory.
        """
        monkeypatch.setattr(shardlink, "BUNDLES_REMEMBERED_AT_MOST", 10**9)
        monkeypatch.setattr(shardlink, "PLACES_REMEMBERED_AT_MOST", 6)

        for image in self.three_bundles(tmp_path):
            assert where_one_chunk_lives(image, (0, 0)) is not None
            assert how_the_remembering_is_going().places_held <= 6

        going = how_the_remembering_is_going()
        assert going.bundles_held == 1, "each bundle holds four positions, so only one fits"

    def test_the_bundle_being_used_is_the_one_kept(self, tmp_path, monkeypatch):
        """When something has to be forgotten, it is what nobody has asked for.

        A viewer looks at one part of the slide for a while, so the bundles it has
        just used are the ones it is about to use again. Forgetting those and
        keeping the ones nobody has touched would leave the limit in place and the
        benefit gone.
        """
        monkeypatch.setattr(shardlink, "BUNDLES_REMEMBERED_AT_MOST", 2)
        monkeypatch.setattr(shardlink, "PLACES_REMEMBERED_AT_MOST", 10**9)
        first, second, third = self.three_bundles(tmp_path)

        where_one_chunk_lives(first, (0, 0))
        where_one_chunk_lives(second, (0, 0))
        where_one_chunk_lives(first, (0, 1))
        assert how_the_remembering_is_going().read_from_disk == 2

        # The third bundle fills the memory. What has to go is the one nobody has
        # looked at since, which is the second, not the first.
        where_one_chunk_lives(third, (0, 0))
        where_one_chunk_lives(first, (0, 1))
        assert how_the_remembering_is_going().read_from_disk == 3, (
            "the bundle in use was forgotten in favour of one that was not"
        )


class TestTheChecksumOverTheTable:
    """The quick way of working out the checksum agrees with the slow definition.

    The checksum is defined one bit at a time, and following that literally was
    measured to be almost the whole cost of resolving a chunk on a real bundle. It
    is now worked out by looking each byte up in a small table prepared once. That
    is only safe if the two give identical answers, so this checks them against
    each other and against a published value.
    """

    def the_definition(self, content):
        """The checksum exactly as it is written down, one bit at a time."""
        checksum = 0xFFFFFFFF
        for byte in content:
            checksum ^= byte
            for _ in range(8):
                checksum = (checksum >> 1) ^ 0x82F63B78 if checksum & 1 else checksum >> 1
        return (~checksum) & 0xFFFFFFFF

    def test_it_matches_the_published_value(self):
        """``123456789`` is the string every CRC implementation is checked against."""
        assert the_checksum_of(b"123456789") == 0xE3069283

    def test_it_matches_the_definition_at_every_length(self):
        """Including the empty table and the odd lengths where an error would hide."""
        generator = np.random.default_rng(99)
        for length in (0, 1, 2, 3, 7, 15, 16, 17, 64, 255, 4096):
            content = generator.integers(0, 256, size=length, dtype=np.uint8).tobytes()
            assert the_checksum_of(content) == self.the_definition(content), length

    def test_a_table_whose_checksum_disagrees_is_refused(self, tmp_path):
        """A bundle whose table has been damaged is not read at all.

        Serving a byte range out of a damaged table would give a chunk that decodes
        to something, which is worse than an error, so the shard is refused.
        """
        image, _ = an_image(
            tmp_path / "damaged.zarr", (256, 256), (128, 128), (256, 256), compressed=False
        )
        shard = Path(image) / "c" / "0" / "0"
        raw = bytearray(shard.read_bytes())
        raw[-1] ^= 0xFF
        shard.write_bytes(bytes(raw))

        with pytest.raises(ZmartLiveError) as refusal:
            read_the_index(shard, inner_chunk=(128, 128), shard_shape=(256, 256))
        assert "CRC32C" in str(refusal.value)
