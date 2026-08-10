"""Tests for the Zarr sharded-write strategies.

Two kinds of checks live here:

* **Correctness** -- every strategy must put exactly the frames we streamed
  onto disk, including the awkward cases (stack length not a whole number of
  shards, image size not a whole number of chunks).
* **The mechanism itself** -- using the byte-counting store to prove, without
  any flaky timing assertions, that the naive one-frame-at-a-time sharded
  write really rewrites data over and over, and that the buffered and
  plane-aligned strategies really do not.

Run:  pytest test_zarr_write_strategies.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr

from zarr_write_strategies import (
    STRATEGIES,
    WRITERS,
    BufferedShardedWriter,
    NaiveShardedWriter,
    PlaneShardWriter,
    UnshardedWriter,
    run_grid,
    run_one,
    synthesize_stack,
)


def _stream(writer_cls, path: Path, stack: np.ndarray, **kwargs):
    """Feed a stack frame by frame through a writer, the way a camera would."""
    writer = writer_cls(path, stack.shape, **kwargs)
    for frame in stack:
        writer.append(frame)
    writer.close()
    return writer


def _readback(path: Path) -> np.ndarray:
    return zarr.open_array(store=str(path))[:]


@pytest.fixture()
def stack() -> np.ndarray:
    # 10 planes with shard depth 4 exercises the partial final shard, and
    # 96x96 images with 32-pixel chunks divide evenly (the uneven-image case
    # gets its own test below).
    return synthesize_stack((10, 96, 96), seed=1)


# ---------------------------------------------------------------------------
# Correctness: what we stream in is exactly what lands on disk.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_roundtrip_every_strategy(strategy, stack, tmp_path):
    writer_cls = WRITERS[strategy]
    path = tmp_path / f"{strategy}.zarr"
    _stream(writer_cls, path, stack, chunk_yx=32, shard_z=4)
    np.testing.assert_array_equal(_readback(path), stack)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_roundtrip_with_uneven_chunks(strategy, tmp_path):
    # 100x100 images with 32-pixel chunks leave partial chunks at the edges;
    # every strategy must still store them faithfully.
    stack = synthesize_stack((6, 100, 100), seed=2)
    path = tmp_path / f"{strategy}.zarr"
    _stream(WRITERS[strategy], path, stack, chunk_yx=32, shard_z=3)
    np.testing.assert_array_equal(_readback(path), stack)


def test_buffered_partial_final_shard(tmp_path):
    # 10 planes / shard depth 4 = two full shards + a 2-plane tail. The tail
    # flush must land in the right place -- this pins the flush bookkeeping.
    stack = synthesize_stack((10, 64, 64), seed=3)
    path = tmp_path / "buffered.zarr"
    _stream(BufferedShardedWriter, path, stack, chunk_yx=32, shard_z=4)
    np.testing.assert_array_equal(_readback(path), stack)


def test_buffered_exact_multiple_of_shards(tmp_path):
    # No tail at all: close() must not flush an empty buffer or write junk.
    stack = synthesize_stack((8, 64, 64), seed=4)
    path = tmp_path / "buffered.zarr"
    _stream(BufferedShardedWriter, path, stack, chunk_yx=32, shard_z=4)
    np.testing.assert_array_equal(_readback(path), stack)


def test_appending_too_many_frames_raises(stack, tmp_path):
    writer = UnshardedWriter(tmp_path / "a.zarr", stack.shape, chunk_yx=32)
    for frame in stack:
        writer.append(frame)
    with pytest.raises(ValueError, match="full"):
        writer.append(stack[0])


def test_closing_an_incomplete_stack_raises(stack, tmp_path):
    writer = UnshardedWriter(tmp_path / "a.zarr", stack.shape, chunk_yx=32)
    writer.append(stack[0])
    with pytest.raises(ValueError, match="incomplete"):
        writer.close()


def test_reshard_cleans_up_its_temporary_store(stack, tmp_path):
    path = tmp_path / "resharded.zarr"
    _stream(
        WRITERS["write-then-reshard"], path, stack, chunk_yx=32, shard_z=4
    )
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == [], "temporary acquisition store was not removed"


# ---------------------------------------------------------------------------
# The mechanism: prove the rewrite problem (and its fixes) with byte counts,
# which are deterministic, rather than with timings, which are not.
# ---------------------------------------------------------------------------


def test_naive_sharded_writes_the_same_data_many_times(stack, tmp_path):
    naive = _stream(
        NaiveShardedWriter, tmp_path / "naive.zarr", stack, chunk_yx=32, shard_z=5
    )
    buffered = _stream(
        BufferedShardedWriter,
        tmp_path / "buffered.zarr",
        stack,
        chunk_yx=32,
        shard_z=5,
    )
    # Writing one frame at a time into 5-deep shards repacks each shard about
    # 5 times, so the naive writer must push several times the bytes of the
    # buffered writer -- and read shard data back, which buffered never does.
    assert naive.store.bytes_written > 2 * buffered.store.bytes_written
    assert naive.store.bytes_read > 0
    assert buffered.store.bytes_read == 0


def test_buffered_writes_each_byte_once(stack, tmp_path):
    buffered = _stream(
        BufferedShardedWriter,
        tmp_path / "buffered.zarr",
        stack,
        chunk_yx=32,
        shard_z=4,
    )
    store_path = tmp_path / "buffered.zarr"
    on_disk = sum(
        p.stat().st_size for p in store_path.rglob("*") if p.is_file()
    )
    # Everything written should still be there: no byte was written twice.
    # (A small tolerance covers the metadata document.)
    assert buffered.store.bytes_written <= on_disk + 4096


def test_plane_shards_never_read_back(stack, tmp_path):
    writer = _stream(
        PlaneShardWriter, tmp_path / "plane.zarr", stack, chunk_yx=32
    )
    assert writer.store.bytes_read == 0


def test_sharding_reduces_file_count(stack, tmp_path):
    unsharded = tmp_path / "unsharded.zarr"
    buffered = tmp_path / "buffered.zarr"
    _stream(UnshardedWriter, unsharded, stack, chunk_yx=32)
    _stream(BufferedShardedWriter, buffered, stack, chunk_yx=32, shard_z=5)
    count = lambda p: sum(1 for f in p.rglob("*") if f.is_file())  # noqa: E731
    # 10 planes of 96x96 in 32-pixel chunks is 90 chunk files + metadata;
    # two 5-deep shards collapse that to 2 shard files + metadata.
    assert count(unsharded) == 91
    assert count(buffered) == 3


# ---------------------------------------------------------------------------
# The benchmark harness itself.
# ---------------------------------------------------------------------------


def test_run_one_verifies_and_reports(stack, tmp_path):
    result = run_one(
        "buffered-sharded",
        stack,
        tmp_path / "bench.zarr",
        chunk_yx=32,
        shard_z=4,
    )
    assert result.wall_s > 0
    assert result.cpu_s >= 0
    assert result.n_files == 4  # ceil(10/4) = 3 shards + zarr.json
    assert result.chunks_per_shard == 4 * 3 * 3
    assert result.write_amplification > 0


def test_run_grid_covers_every_strategy(tmp_path):
    small = synthesize_stack((4, 64, 64), seed=5)
    results = run_grid(
        small, tmp_path, chunk_sizes=[32], shard_depths=[2]
    )
    assert {r.strategy for r in results} == set(STRATEGIES)
    # Depth-independent strategies run once; the rest once per depth.
    assert len(results) == 5
