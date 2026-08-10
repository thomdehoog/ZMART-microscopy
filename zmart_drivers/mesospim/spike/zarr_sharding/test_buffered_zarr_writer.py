"""Tests for the standalone buffered Zarr stack writer.

These cover the contract a user of :class:`ZarrStackWriter` relies on:

* what goes in comes back out, bit for bit -- including the awkward shapes
  (a stack that is not a whole number of shards, a frame that is not a
  whole number of chunks, a stack shorter than one shard);
* mistakes fail loudly and early (wrong frame size, wrong dtype, too many
  frames, a stack closed before it is complete, an output folder that
  already exists);
* the sharding actually happens (a handful of files, not thousands), and
  filling a shard never triggers Zarr's slow read-back-and-rewrite path.

Run:  pytest test_buffered_zarr_writer.py
"""

from __future__ import annotations

import numpy as np
import pytest
import zarr

from buffered_zarr_writer import ZarrStackWriter


def make_stack(shape: tuple[int, int, int], seed: int = 0) -> np.ndarray:
    """A small random uint16 stack; content is irrelevant, fidelity is not."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2**16, size=shape, dtype=np.uint16)


def write_stack(path, stack: np.ndarray, **kwargs) -> ZarrStackWriter:
    writer = ZarrStackWriter(path, stack.shape, **kwargs)
    for frame in stack:
        writer.append(frame)
    writer.close()
    return writer


def read_back(path) -> np.ndarray:
    return zarr.open_array(store=str(path))[:]


# ---------------------------------------------------------------------------
# Fidelity: what goes in comes back out.
# ---------------------------------------------------------------------------


def test_roundtrip(tmp_path):
    stack = make_stack((10, 96, 96))
    write_stack(tmp_path / "s.zarr", stack, chunk_size=32, frames_per_shard=4)
    np.testing.assert_array_equal(read_back(tmp_path / "s.zarr"), stack)


def test_roundtrip_partial_final_shard(tmp_path):
    # 10 frames at 4 per shard = two full shards + a 2-frame tail; the tail
    # flush must land in the right place.
    stack = make_stack((10, 64, 64))
    write_stack(tmp_path / "s.zarr", stack, chunk_size=32, frames_per_shard=4)
    np.testing.assert_array_equal(read_back(tmp_path / "s.zarr"), stack)


def test_roundtrip_frame_not_multiple_of_chunks(tmp_path):
    # 100 px frames with 32 px chunks leave partial chunks at two edges.
    stack = make_stack((6, 100, 100))
    write_stack(tmp_path / "s.zarr", stack, chunk_size=32, frames_per_shard=3)
    np.testing.assert_array_equal(read_back(tmp_path / "s.zarr"), stack)


def test_stack_shorter_than_one_shard(tmp_path):
    # frames_per_shard is trimmed to the stack; the buffer must not demand
    # more memory than the whole stack needs.
    stack = make_stack((3, 64, 64))
    writer = write_stack(
        tmp_path / "s.zarr", stack, chunk_size=32, frames_per_shard=16
    )
    assert writer._buffer.shape[0] == 3
    np.testing.assert_array_equal(read_back(tmp_path / "s.zarr"), stack)


def test_other_dtypes_roundtrip(tmp_path):
    stack = make_stack((4, 64, 64)).astype(np.float32)
    write_stack(
        tmp_path / "s.zarr", stack, dtype=np.float32, chunk_size=32,
        frames_per_shard=2,
    )
    np.testing.assert_array_equal(read_back(tmp_path / "s.zarr"), stack)


def test_context_manager_closes_and_completes(tmp_path):
    stack = make_stack((4, 64, 64))
    with ZarrStackWriter(
        tmp_path / "s.zarr", stack.shape, chunk_size=32, frames_per_shard=2
    ) as writer:
        for frame in stack:
            writer.append(frame)
    np.testing.assert_array_equal(read_back(tmp_path / "s.zarr"), stack)


# ---------------------------------------------------------------------------
# Mistakes fail loudly and early.
# ---------------------------------------------------------------------------


def test_wrong_frame_shape_raises(tmp_path):
    writer = ZarrStackWriter(tmp_path / "s.zarr", (4, 64, 64), chunk_size=32)
    with pytest.raises(ValueError, match="shape"):
        writer.append(np.zeros((32, 32), dtype=np.uint16))


def test_wrong_dtype_raises(tmp_path):
    writer = ZarrStackWriter(tmp_path / "s.zarr", (4, 64, 64), chunk_size=32)
    with pytest.raises(ValueError, match="dtype"):
        writer.append(np.zeros((64, 64), dtype=np.float64))


def test_too_many_frames_raises(tmp_path):
    stack = make_stack((2, 64, 64))
    writer = ZarrStackWriter(
        tmp_path / "s.zarr", stack.shape, chunk_size=32, frames_per_shard=2
    )
    for frame in stack:
        writer.append(frame)
    with pytest.raises(ValueError, match="all 2 frames"):
        writer.append(stack[0])


def test_incomplete_close_raises(tmp_path):
    writer = ZarrStackWriter(tmp_path / "s.zarr", (4, 64, 64), chunk_size=32)
    writer.append(np.zeros((64, 64), dtype=np.uint16))
    with pytest.raises(ValueError, match="incomplete"):
        writer.close()


def test_existing_path_refused_unless_overwrite(tmp_path):
    stack = make_stack((2, 64, 64))
    write_stack(tmp_path / "s.zarr", stack, chunk_size=32, frames_per_shard=2)
    with pytest.raises(FileExistsError):
        ZarrStackWriter(tmp_path / "s.zarr", stack.shape, chunk_size=32)
    # With permission, the same path is reusable and correct.
    stack2 = make_stack((2, 64, 64), seed=1)
    write_stack(
        tmp_path / "s.zarr", stack2, chunk_size=32, frames_per_shard=2,
        overwrite=True,
    )
    np.testing.assert_array_equal(read_back(tmp_path / "s.zarr"), stack2)


def test_bad_sizes_raise(tmp_path):
    with pytest.raises(ValueError):
        ZarrStackWriter(tmp_path / "a.zarr", (0, 64, 64))
    with pytest.raises(ValueError):
        ZarrStackWriter(tmp_path / "b.zarr", (4, 64, 64), chunk_size=0)
    with pytest.raises(ValueError):
        ZarrStackWriter(tmp_path / "c.zarr", (4, 64, 64), frames_per_shard=0)


def test_exception_in_with_block_propagates(tmp_path):
    # The original error must surface, not be shadowed by an "incomplete
    # stack" complaint from close().
    with pytest.raises(RuntimeError, match="camera dropped"):
        with ZarrStackWriter(tmp_path / "s.zarr", (4, 64, 64), chunk_size=32):
            raise RuntimeError("camera dropped a frame")


# ---------------------------------------------------------------------------
# The sharding actually happens, and the slow path is never taken.
# ---------------------------------------------------------------------------


def test_file_count_is_shards_plus_metadata(tmp_path):
    stack = make_stack((10, 96, 96))
    write_stack(tmp_path / "s.zarr", stack, chunk_size=32, frames_per_shard=4)
    files = [p for p in (tmp_path / "s.zarr").rglob("*") if p.is_file()]
    # ceil(10 / 4) = 3 shard files, plus the zarr.json metadata document --
    # not the 90 chunk files an unsharded layout would produce.
    assert len(files) == 4


def test_randomized_shapes_roundtrip(tmp_path):
    # A seeded sweep over random geometry: plane counts that are not shard
    # multiples, frames that are not chunk multiples, chunks bigger than the
    # frame, single-pixel edge cases, three dtypes. Any bookkeeping slip in
    # the buffer/flush logic (an off-by-one plane, a misplaced tail) would
    # surface as an inequality somewhere in this space. The seed makes the
    # sweep reproducible -- a failure here fails the same way every run.
    rng = np.random.default_rng(42)
    for case in range(30):
        planes = int(rng.integers(1, 40))
        height = int(rng.integers(1, 130))
        width = int(rng.integers(1, 130))
        chunk = int(rng.integers(1, 70))
        fps = int(rng.integers(1, 50))
        dtype = rng.choice([np.uint8, np.uint16, np.float32])
        if np.issubdtype(dtype, np.integer):
            stack = rng.integers(
                0, np.iinfo(dtype).max, size=(planes, height, width)
            ).astype(dtype)
        else:
            stack = rng.random((planes, height, width)).astype(dtype)

        path = tmp_path / f"case_{case}.zarr"
        write_stack(
            path, stack, dtype=dtype, chunk_size=chunk, frames_per_shard=fps
        )
        np.testing.assert_array_equal(
            read_back(path),
            stack,
            err_msg=f"case {case}: shape={stack.shape} chunk_size={chunk} "
            f"frames_per_shard={fps} dtype={np.dtype(dtype)}",
        )


def test_independent_reader_agrees(tmp_path):
    # The strongest correctness check we have: read the written store back
    # with tensorstore, a C++ Zarr implementation that shares no code with
    # zarr-python. If both implementations decode our files to the same
    # pixels, the store conforms to the Zarr v3 format itself, not merely to
    # zarr-python's own round trip. Skips when tensorstore is not installed
    # (it is an optional, heavyweight dependency).
    ts = pytest.importorskip("tensorstore")

    # Awkward on purpose: planes not a shard multiple, frame not a chunk
    # multiple, so shard padding and edge chunks are exercised too.
    stack = make_stack((10, 75, 90))
    path = tmp_path / "xcheck.zarr"
    write_stack(path, stack, chunk_size=32, frames_per_shard=4)

    arr = ts.open(
        {"driver": "zarr3", "kvstore": {"driver": "file", "path": str(path)}}
    ).result()
    back = arr.read().result()
    np.testing.assert_array_equal(back, stack)


def test_never_reads_back_while_writing(tmp_path):
    # Zarr's read-modify-write path starts by reading the shard file back.
    # If the writer keeps its one-write-per-shard promise, the store sees
    # zero read traffic during the whole write, even with a partial tail.
    reads = []

    class ReadCountingStore(zarr.storage.LocalStore):
        async def get(self, key, prototype, byte_range=None):
            out = await super().get(key, prototype, byte_range)
            if out is not None:
                reads.append(key)
            return out

    stack = make_stack((10, 64, 64))
    writer = ZarrStackWriter(
        tmp_path / "s.zarr", stack.shape, chunk_size=32, frames_per_shard=4
    )
    writer._array = zarr.create_array(
        store=ReadCountingStore(tmp_path / "counted.zarr"),
        shape=stack.shape,
        chunks=writer._array.chunks,
        shards=writer._array.shards,
        dtype=stack.dtype,
    )
    for frame in stack:
        writer.append(frame)
    writer.close()
    assert reads == []
    np.testing.assert_array_equal(read_back(tmp_path / "counted.zarr"), stack)
