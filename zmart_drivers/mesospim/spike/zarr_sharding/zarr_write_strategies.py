"""How to stream a z-stack into a sharded OME-Zarr-style array without the
write penalty.
======================================================================

Why this spike exists
---------------------
Zarr version 3 can pack many small chunks into one big file called a *shard*.
Shards keep the file count low (a whole-brain dataset with small chunks can
otherwise be millions of tiny files, which network drives handle very badly).
The catch: the shard is the smallest thing Zarr can store. If you write only
*part* of a shard -- say one camera frame into a shard that spans 32 frames --
Zarr must read the whole shard file back, unpack it, swap in your new chunks,
repack it, and write the whole file out again. Do that once per frame and you
write the same data over and over: acquisition becomes many times slower.

This module implements every strategy from the discussion, all behind one tiny
"frames arrive one at a time, in order" interface (the way a camera delivers
them), plus a benchmark that sweeps chunk sizes and chunks-per-shard so you
can see for yourself what wins in wall-clock time and in CPU work:

* ``unsharded``       -- no shards at all; every chunk is its own file.
                         Fast to write, but the file count explodes.
* ``naive-sharded``   -- shards spanning many frames, written one frame at a
                         time. This is the slow case you observed; it is here
                         as the baseline to beat.
* ``plane-shards``    -- shards that are exactly one frame thick, so every
                         frame write covers whole shards and nothing is ever
                         rewritten. No buffering needed.
* ``buffered-sharded``-- deep shards, but frames are collected in a memory
                         buffer and flushed one whole shard at a time. Costs
                         some RAM; keeps deep shards *and* full speed.
* ``write-then-reshard`` -- acquire into a plain unsharded array at full
                         speed, then repack into the sharded layout
                         afterwards. Needs temporary disk space.

Run the benchmark (writes to a temporary folder by default)::

    python zarr_write_strategies.py
    python zarr_write_strategies.py --shape 64 2048 2048 --chunk-sizes 256 512

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import argparse
import csv
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zarr
import zarr.storage

DTYPE = np.uint16  # what scientific cameras deliver

STRATEGIES = (
    "unsharded",
    "naive-sharded",
    "plane-shards",
    "buffered-sharded",
    "write-then-reshard",
)


# ---------------------------------------------------------------------------
# A store that counts every byte moving to and from disk.
#
# This is how we *measure* the rewrite problem instead of guessing at it: if a
# strategy writes a 64 MB stack but the store reports 300 MB written, the
# extra 236 MB is the same data being packed and re-packed. We call that ratio
# "write amplification" -- 1.0 is perfect, bigger is wasted work.
# ---------------------------------------------------------------------------


class CountingStore(zarr.storage.LocalStore):
    """A normal on-disk Zarr store that also tallies bytes read and written."""

    def __init__(self, root: str | Path) -> None:
        super().__init__(root)
        self.bytes_written = 0
        self.bytes_read = 0

    async def set(self, key, value):  # noqa: ANN001 - signature fixed by zarr
        self.bytes_written += _buffer_nbytes(value)
        return await super().set(key, value)

    async def get(self, key, prototype, byte_range=None):  # noqa: ANN001
        out = await super().get(key, prototype, byte_range)
        if out is not None:
            self.bytes_read += _buffer_nbytes(out)
        return out


def _buffer_nbytes(buf) -> int:
    """Size in bytes of a zarr Buffer, tolerant of zarr-internal API changes."""
    try:
        return len(buf)
    except TypeError:
        return len(buf.to_bytes())


# ---------------------------------------------------------------------------
# The writer strategies.
#
# All of them share one contract, shaped like an acquisition: you create the
# writer with the final stack shape, call ``append(frame)`` once per camera
# frame in z order, and ``close()`` when the stack is done. After ``close()``
# the data on disk is complete and correct for every strategy -- they differ
# only in how much time, CPU, RAM, and temporary disk they spend getting there.
# ---------------------------------------------------------------------------


class FrameStreamWriter:
    """Base class: an in-order, one-frame-at-a-time writer for one z-stack.

    Parameters
    ----------
    path:
        Folder the Zarr array is created in (it must not exist yet).
    shape:
        Final stack shape as ``(planes, height, width)``.
    chunks / shards:
        The Zarr chunk shape, and optionally the shard shape (``None`` means
        no sharding). Shard sizes must be whole multiples of chunk sizes --
        a shard is literally a box of chunks.
    """

    def __init__(
        self,
        path: str | Path,
        shape: tuple[int, int, int],
        *,
        chunks: tuple[int, int, int],
        shards: tuple[int, int, int] | None = None,
    ) -> None:
        self.shape = shape
        self.store = CountingStore(path)
        self.array = zarr.create_array(
            store=self.store,
            shape=shape,
            chunks=chunks,
            shards=shards,
            dtype=DTYPE,
        )
        self._next_z = 0

    def append(self, frame: np.ndarray) -> None:
        """Add the next frame (a 2-D image) to the stack."""
        if self._next_z >= self.shape[0]:
            raise ValueError(f"stack is full ({self.shape[0]} planes)")
        self._write(self._next_z, frame)
        self._next_z += 1

    def _write(self, z: int, frame: np.ndarray) -> None:
        self.array[z] = frame

    def close(self) -> None:
        """Finish the stack. All frames must have been appended."""
        if self._next_z != self.shape[0]:
            raise ValueError(
                f"stack incomplete: {self._next_z} of {self.shape[0]} planes"
            )


def _shard_edge(image_edge: int, chunk_edge: int) -> int:
    """Smallest whole number of chunks that covers one edge of the image.

    Zarr insists that a shard is an exact box of chunks, so if the image is
    100 pixels wide with 32-pixel chunks, the shard must be 128 pixels wide
    (4 chunks); the part hanging past the image edge simply stays empty.
    """
    return -(-image_edge // chunk_edge) * chunk_edge


class UnshardedWriter(FrameStreamWriter):
    """No shards: every chunk is its own file, frames write straight in.

    This is the fast, simple baseline. Its weakness is not speed but file
    count -- with small chunks, big volumes turn into a huge number of tiny
    files, which is slow to copy and hard on network storage.
    """

    def __init__(self, path, shape, *, chunk_yx: int, **_ignored) -> None:
        super().__init__(path, shape, chunks=(1, chunk_yx, chunk_yx))


class NaiveShardedWriter(FrameStreamWriter):
    """Deep shards written one frame at a time -- the slow case, on purpose.

    Each shard spans ``shard_z`` frames, but frames arrive singly, so every
    ``append`` makes Zarr read the shard file back, merge one frame, and
    rewrite the whole file. Expect roughly ``shard_z`` times the necessary
    writing. It is included so the benchmark can show the cost, not because
    anyone should use it.
    """

    def __init__(self, path, shape, *, chunk_yx: int, shard_z: int) -> None:
        super().__init__(
            path,
            shape,
            chunks=(1, chunk_yx, chunk_yx),
            shards=(
                shard_z,
                _shard_edge(shape[1], chunk_yx),
                _shard_edge(shape[2], chunk_yx),
            ),
        )


class PlaneShardWriter(FrameStreamWriter):
    """Shards exactly one frame thick: frame writes always cover whole shards.

    Because a shard never spans more than one frame, writing a frame replaces
    complete shards and nothing is ever read back or rewritten. You still get
    far fewer files than unsharded (one file per frame instead of one per
    chunk), with no buffering and no extra RAM. The trade-off: you cannot
    make shards any bigger than one frame.
    """

    def __init__(self, path, shape, *, chunk_yx: int, **_ignored) -> None:
        super().__init__(
            path,
            shape,
            chunks=(1, chunk_yx, chunk_yx),
            shards=(
                1,
                _shard_edge(shape[1], chunk_yx),
                _shard_edge(shape[2], chunk_yx),
            ),
        )


class BufferedShardedWriter(FrameStreamWriter):
    """Deep shards, written correctly: buffer frames, flush whole shards.

    Frames accumulate in a RAM buffer that is exactly one shard deep. When it
    fills, the whole slab is written in a single assignment aligned to the
    shard boundary, so Zarr packs each shard file exactly once -- same speed
    as unsharded, same low file count as deep shards. The cost is the buffer:
    ``shard_z * height * width * 2`` bytes of RAM (e.g. 32 frames of
    2048 x 2048 uint16 is 256 MB).

    If the stack length is not a whole number of shards, the final flush
    writes a shorter slab; the region still covers the (shorter) last shard
    completely, so even that write is rewrite-free.
    """

    def __init__(self, path, shape, *, chunk_yx: int, shard_z: int) -> None:
        super().__init__(
            path,
            shape,
            chunks=(1, chunk_yx, chunk_yx),
            shards=(
                shard_z,
                _shard_edge(shape[1], chunk_yx),
                _shard_edge(shape[2], chunk_yx),
            ),
        )
        self._buffer = np.empty((shard_z, shape[1], shape[2]), dtype=DTYPE)
        self._filled = 0
        self._flushed = 0  # planes already written to disk

    def _write(self, z: int, frame: np.ndarray) -> None:
        self._buffer[self._filled] = frame
        self._filled += 1
        if self._filled == self._buffer.shape[0]:
            self._flush()

    def _flush(self) -> None:
        start = self._flushed
        self.array[start : start + self._filled] = self._buffer[: self._filled]
        self._flushed += self._filled
        self._filled = 0

    def close(self) -> None:
        super().close()
        if self._filled:
            self._flush()


class WriteThenReshardWriter(FrameStreamWriter):
    """Acquire unsharded at full speed, repack into shards afterwards.

    During acquisition this behaves exactly like :class:`UnshardedWriter`,
    writing into a temporary array next to the final path. ``close()`` then
    copies the stack, one shard-deep slab at a time, into the final sharded
    array and deletes the temporary one. Nothing is ever partially rewritten,
    but the whole stack is written twice (and read once in between), and you
    briefly need double the disk space. This is the right shape when
    acquisition must be as fast as possible and repacking can happen later,
    e.g. between positions or overnight.
    """

    def __init__(self, path, shape, *, chunk_yx: int, shard_z: int) -> None:
        self._final_path = Path(path)
        self._temp_path = self._final_path.with_name(
            self._final_path.name + ".acquiring"
        )
        self._shard_z = shard_z
        self._chunk_yx = chunk_yx
        super().__init__(self._temp_path, shape, chunks=(1, chunk_yx, chunk_yx))

    def close(self) -> None:
        super().close()
        final_store = CountingStore(self._final_path)
        final = zarr.create_array(
            store=final_store,
            shape=self.shape,
            chunks=(1, self._chunk_yx, self._chunk_yx),
            shards=(
                self._shard_z,
                _shard_edge(self.shape[1], self._chunk_yx),
                _shard_edge(self.shape[2], self._chunk_yx),
            ),
            dtype=DTYPE,
        )
        for start in range(0, self.shape[0], self._shard_z):
            stop = min(start + self._shard_z, self.shape[0])
            final[start:stop] = self.array[start:stop]
        # Fold the acquisition-phase traffic into the final store's totals so
        # the benchmark sees both writes, then swap the finished array into
        # place and drop the temporary one.
        final_store.bytes_written += self.store.bytes_written
        final_store.bytes_read += self.store.bytes_read
        shutil.rmtree(self._temp_path)
        self.array = final
        self.store = final_store


WRITERS: dict[str, type[FrameStreamWriter]] = {
    "unsharded": UnshardedWriter,
    "naive-sharded": NaiveShardedWriter,
    "plane-shards": PlaneShardWriter,
    "buffered-sharded": BufferedShardedWriter,
    "write-then-reshard": WriteThenReshardWriter,
}


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


@dataclass
class BenchResult:
    """One benchmark run: a strategy at one chunk-size / shard-depth setting."""

    strategy: str
    chunk_yx: int
    shard_z: int  # 0 for the unsharded strategy (shards do not apply)
    chunks_per_shard: int  # ditto
    wall_s: float  # elapsed stopwatch time for the whole write
    cpu_s: float  # CPU time actually burned (compression, repacking, ...)
    mb_per_s: float  # stack megabytes / wall seconds
    write_amplification: float  # bytes sent to disk / bytes in the stack
    bytes_read_mb: float  # data read *back* during writing (rewrites, repack)
    n_files: int  # files on disk at the end
    store_mb: float  # final size on disk (compressed)


def synthesize_stack(shape: tuple[int, int, int], seed: int = 0) -> np.ndarray:
    """Make a microscopy-like test stack: dark background, bright blobs, noise.

    Real camera data compresses partway -- neither random static (which does
    not compress) nor flat zeros (which compress too well). A few Gaussian
    blobs on a noisy background lands in that realistic middle ground, so the
    compressor does a representative amount of work.
    """
    rng = np.random.default_rng(seed)
    nz, ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    background = rng.poisson(100, size=shape).astype(np.float32)
    n_blobs = 12
    cy = rng.uniform(0, ny, n_blobs)
    cx = rng.uniform(0, nx, n_blobs)
    cz = rng.uniform(0, nz, n_blobs)
    sigma = max(8.0, min(ny, nx) / 24)
    for z in range(nz):
        for b in range(n_blobs):
            depth = np.exp(-((z - cz[b]) ** 2) / (2 * (nz / 6) ** 2))
            background[z] += (
                8000.0
                * depth
                * np.exp(
                    -((yy - cy[b]) ** 2 + (xx - cx[b]) ** 2) / (2 * sigma**2)
                )
            )
    return np.clip(background, 0, np.iinfo(DTYPE).max).astype(DTYPE)


def run_one(
    strategy: str,
    stack: np.ndarray,
    path: Path,
    *,
    chunk_yx: int,
    shard_z: int,
    verify: bool = True,
) -> BenchResult:
    """Stream ``stack`` through one strategy and measure everything.

    The stack is fully in RAM before the clock starts, so the numbers reflect
    only the writing itself, not the synthetic-data generation.
    """
    writer_cls = WRITERS[strategy]
    stack_bytes = stack.nbytes

    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    writer = writer_cls(
        path, stack.shape, chunk_yx=chunk_yx, shard_z=shard_z
    )
    for frame in stack:
        writer.append(frame)
    writer.close()
    wall = time.perf_counter() - wall_start
    cpu = time.process_time() - cpu_start

    if verify:
        readback = zarr.open_array(store=str(path))
        if not np.array_equal(readback[:], stack):
            raise AssertionError(f"{strategy}: data on disk != data written")

    files = [p for p in path.rglob("*") if p.is_file()]
    sharded = strategy not in ("unsharded",)
    effective_shard_z = {"unsharded": 0, "plane-shards": 1}.get(strategy, shard_z)
    chunks_per_shard = 0
    if sharded:
        ny, nx = stack.shape[1:]
        chunks_per_shard = (
            max(effective_shard_z, 1)
            * -(-ny // chunk_yx)  # ceil division: partial edge chunks count
            * -(-nx // chunk_yx)
        )
    return BenchResult(
        strategy=strategy,
        chunk_yx=chunk_yx,
        shard_z=effective_shard_z,
        chunks_per_shard=chunks_per_shard,
        wall_s=wall,
        cpu_s=cpu,
        mb_per_s=stack_bytes / 1e6 / wall,
        write_amplification=writer.store.bytes_written / stack_bytes,
        bytes_read_mb=writer.store.bytes_read / 1e6,
        n_files=len(files),
        store_mb=sum(p.stat().st_size for p in files) / 1e6,
    )


def run_grid(
    stack: np.ndarray,
    out_dir: Path,
    *,
    chunk_sizes: list[int],
    shard_depths: list[int],
    strategies: list[str] | None = None,
    keep_stores: bool = False,
) -> list[BenchResult]:
    """Sweep every strategy across chunk sizes and shard depths.

    ``unsharded`` and ``plane-shards`` do not depend on shard depth, so they
    run once per chunk size instead of once per (chunk, depth) pair.
    """
    strategies = list(strategies or STRATEGIES)
    results: list[BenchResult] = []
    for chunk_yx in chunk_sizes:
        for strategy in strategies:
            depths = shard_depths if strategy in _DEPTH_DEPENDENT else [shard_depths[0]]
            for shard_z in depths:
                path = out_dir / f"{strategy}_c{chunk_yx}_s{shard_z}.zarr"
                result = run_one(
                    strategy, stack, path, chunk_yx=chunk_yx, shard_z=shard_z
                )
                results.append(result)
                print(_format_row(result), flush=True)
                if not keep_stores:
                    shutil.rmtree(path)
    return results


_DEPTH_DEPENDENT = {"naive-sharded", "buffered-sharded", "write-then-reshard"}

_COLUMNS = (
    ("strategy", 20),
    ("chunk", 7),
    ("shard_z", 7),
    ("chunks/shard", 12),
    ("wall_s", 8),
    ("cpu_s", 8),
    ("MB/s", 8),
    ("write_amp", 9),
    ("read_MB", 9),
    ("files", 7),
    ("disk_MB", 8),
)


def _format_header() -> str:
    line = "  ".join(name.rjust(width) for name, width in _COLUMNS)
    return line + "\n" + "-" * len(line)


def _format_row(r: BenchResult) -> str:
    cells = (
        r.strategy,
        str(r.chunk_yx),
        str(r.shard_z) if r.shard_z else "-",
        str(r.chunks_per_shard) if r.chunks_per_shard else "-",
        f"{r.wall_s:.2f}",
        f"{r.cpu_s:.2f}",
        f"{r.mb_per_s:.0f}",
        f"{r.write_amplification:.2f}",
        f"{r.bytes_read_mb:.0f}",
        str(r.n_files),
        f"{r.store_mb:.0f}",
    )
    return "  ".join(
        cell.rjust(width) for cell, (_, width) in zip(cells, _COLUMNS)
    )


def write_csv(results: list[BenchResult], path: Path) -> None:
    """Save the results as a CSV so they can be plotted or archived."""
    fields = list(BenchResult.__dataclass_fields__)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in results:
            writer.writerow({f: getattr(r, f) for f in fields})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Zarr sharded-write strategies for a z-stack."
    )
    parser.add_argument(
        "--shape",
        nargs=3,
        type=int,
        default=[32, 1024, 1024],
        metavar=("Z", "Y", "X"),
        help="stack shape in planes, height, width (default: 32 1024 1024)",
    )
    parser.add_argument(
        "--chunk-sizes",
        nargs="+",
        type=int,
        default=[128, 256, 512],
        help="XY chunk edge lengths to sweep (default: 128 256 512)",
    )
    parser.add_argument(
        "--shard-depths",
        nargs="+",
        type=int,
        default=[8, 32],
        help="frames per shard to sweep (default: 8 32)",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=STRATEGIES,
        default=None,
        help="subset of strategies to run (default: all)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="folder for the benchmark stores (default: a temporary folder)",
    )
    parser.add_argument(
        "--csv", type=Path, default=None, help="also write results to this CSV"
    )
    parser.add_argument(
        "--keep-stores",
        action="store_true",
        help="keep the written arrays instead of deleting them after timing",
    )
    args = parser.parse_args(argv)

    shape = tuple(args.shape)
    print(f"synthesizing {shape} {np.dtype(DTYPE).name} stack "
          f"({np.prod(shape) * 2 / 1e6:.0f} MB) ...")
    stack = synthesize_stack(shape)

    out_dir = args.out or Path(tempfile.mkdtemp(prefix="zarr_shard_bench_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"writing benchmark stores under {out_dir}\n")
    print(_format_header())
    results = run_grid(
        stack,
        out_dir,
        chunk_sizes=args.chunk_sizes,
        shard_depths=args.shard_depths,
        strategies=args.strategies,
        keep_stores=args.keep_stores,
    )
    if args.csv:
        write_csv(results, args.csv)
        print(f"\nresults saved to {args.csv}")
    if not args.keep_stores and args.out is None:
        shutil.rmtree(out_dir, ignore_errors=True)

    best = min(results, key=lambda r: r.wall_s)
    print(
        f"\nfastest: {best.strategy} at chunk {best.chunk_yx}"
        + (f", shard depth {best.shard_z}" if best.shard_z else "")
        + f" -- {best.mb_per_s:.0f} MB/s"
    )


if __name__ == "__main__":
    main()
