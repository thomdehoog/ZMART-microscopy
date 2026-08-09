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
import shutil
import struct
import warnings
from pathlib import Path

import numpy as np
import pytest
import zarr

from zmart_live.model import ZmartLiveError
from zmart_live.shardlink import (
    Held,
    describe_the_bundling,
    read_the_index,
    where_one_chunk_lives,
)

# Zarr's older creation entry point is the only one that lets us choose where the
# table of contents sits, and it warns that it is on its way out. We use it only
# in the one test that needs that choice, and we are not interested in the notice.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="zarr")


# ---------------------------------------------------------------------------
# Building images to test against, and taking chunks back out of them
# ---------------------------------------------------------------------------


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
