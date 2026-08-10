"""Buffered Zarr stack writer -- stream camera frames into a sharded array,
fast.
==========================================================================

A standalone, single-file implementation. It depends only on ``numpy`` and
``zarr >= 3`` (``pip install "zarr>=3" numpy``) and can be copied into any
project as-is.

What this is for
----------------
A microscope camera delivers a z-stack one frame at a time. This module
writes those frames into a Zarr version 3 array that uses *shards* -- big
files that each hold many compressed chunks -- so a large stack ends up as
a handful of files instead of thousands of tiny ones. (Thousands of tiny
files are slow to copy and put real strain on network storage, which is
where microscopy data usually lives.)

The one rule that makes this fast
---------------------------------
A shard file is the smallest thing Zarr can store. If you write only *part*
of a shard -- one frame into a shard that spans sixteen frames -- Zarr must
read the whole shard file back from disk, unpack it, merge in your frame,
repack everything, and write the whole file out again. Streaming frames
straight into deep shards therefore rewrites the same data over and over,
and saving becomes several times slower than not sharding at all.

The fix is simple: **collect frames in memory until a whole shard's worth
has arrived, then write that shard in a single operation.** A whole-shard
write is packed exactly once, Zarr compresses its chunks on several CPU
cores by itself, and nothing is ever read back or rewritten.

That buffering rule is the entire trick, and :class:`ZarrStackWriter` below
is its simplest complete implementation. Use it like this::

    with ZarrStackWriter("stack.zarr", shape=(128, 2048, 2048)) as writer:
        for frame in camera:          # 2-D numpy arrays, in z order
            writer.append(frame)
    # leaving the `with` block checks the stack is complete

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import zarr


class ZarrStackWriter:
    """Write one z-stack to disk, one frame at a time, without the shard
    write penalty.

    Frames must arrive in z order (frame 0 first), each as a 2-D numpy array
    matching the height, width, and dtype declared up front. Call
    :meth:`append` once per frame and :meth:`close` at the end -- or, more
    safely, use the writer as a ``with`` block, which closes it for you.

    Args:
        path: folder the Zarr array is created in. Refuses to touch a folder
            that already exists unless ``overwrite=True``, so a stack can
            never silently clobber an earlier one.
        shape: final stack shape as ``(planes, height, width)``.
        dtype: pixel type of the incoming frames (default ``uint16``, what
            scientific cameras deliver).
        chunk_size: edge length in pixels of the square chunks inside each
            shard. Chunks stay the unit of random access when the data is
            *read* (a viewer like napari fetches one chunk at a time), so
            512 is a good compromise between write speed and read comfort.
        frames_per_shard: how many frames one shard file spans -- which is
            also how many frames are held in memory between flushes. The
            buffer needs ``frames_per_shard * height * width * itemsize``
            bytes: 16 frames of 2048 x 2048 uint16 is 128 MB. More frames
            per shard means fewer files but a bigger buffer; 16-32 is a
            sensible range. If the stack is shorter than one shard, the
            depth is trimmed to the stack automatically.
        overwrite: replace an existing array at ``path`` instead of raising.

    Raises:
        ValueError: a size argument is not a positive whole number.
        FileExistsError: ``path`` exists and ``overwrite`` is False.
    """

    def __init__(
        self,
        path: str | Path,
        shape: tuple[int, int, int],
        *,
        dtype: np.dtype | type = np.uint16,
        chunk_size: int = 512,
        frames_per_shard: int = 16,
        overwrite: bool = False,
    ) -> None:
        planes, height, width = shape
        if min(planes, height, width) < 1:
            raise ValueError(f"shape must be three positive sizes, got {shape}")
        if chunk_size < 1 or frames_per_shard < 1:
            raise ValueError("chunk_size and frames_per_shard must be at least 1")

        self.path = Path(path)
        if self.path.exists() and not overwrite:
            raise FileExistsError(
                f"{self.path} already exists; pass overwrite=True to replace it"
            )

        self.shape = (planes, height, width)
        self.dtype = np.dtype(dtype)

        # A shard never needs to span more frames than the stack has, and a
        # smaller shard means a smaller memory buffer.
        depth = min(frames_per_shard, planes)

        # Zarr requires a shard to be an exact box of chunks. One shard
        # covers the full frame, so its height and width are the frame's,
        # rounded UP to whole chunks (e.g. 2000 px with 512-px chunks
        # becomes 2048); the sliver past the frame edge simply stays empty.
        shard_height = -(-height // chunk_size) * chunk_size
        shard_width = -(-width // chunk_size) * chunk_size

        self._array = zarr.create_array(
            store=str(self.path),
            shape=self.shape,
            # Chunks are one frame thick: a viewer scrolling through z then
            # only ever decompresses the planes it is actually looking at.
            chunks=(1, chunk_size, chunk_size),
            shards=(depth, shard_height, shard_width),
            dtype=self.dtype,
            overwrite=overwrite,
        )

        # The heart of the strategy: frames accumulate here until the buffer
        # holds exactly one shard's worth, then _flush() writes them all in
        # a single shard-aligned operation.
        self._buffer = np.empty((depth, height, width), dtype=self.dtype)
        self._buffered = 0  # frames waiting in the buffer
        self._written = 0  # frames already flushed to disk

    @property
    def frames_appended(self) -> int:
        """How many frames have been handed to the writer so far."""
        return self._written + self._buffered

    def append(self, frame: np.ndarray) -> None:
        """Add the next frame of the stack.

        The frame must match the height, width, and dtype the writer was
        created with; anything else raises ``ValueError`` immediately, so a
        wiring mistake surfaces on frame one rather than as a corrupted
        dataset discovered weeks later.
        """
        expected = self.shape[1:]
        if frame.shape != expected:
            raise ValueError(f"frame shape {frame.shape} != expected {expected}")
        if frame.dtype != self.dtype:
            raise ValueError(f"frame dtype {frame.dtype} != expected {self.dtype}")
        if self.frames_appended >= self.shape[0]:
            raise ValueError(f"stack already has all {self.shape[0]} frames")

        self._buffer[self._buffered] = frame
        self._buffered += 1
        if self._buffered == self._buffer.shape[0]:
            self._flush()

    def _flush(self) -> None:
        """Write the buffered frames as complete shards, in one operation.

        Because the buffer is exactly one shard deep and starts on a shard
        boundary, this single assignment always covers whole shards -- Zarr
        packs each shard file once and never reads anything back. (The last
        flush of a stack may hold fewer frames, but it still covers the
        final -- shorter -- shard completely, so the rule is not broken.)
        """
        stop = self._written + self._buffered
        self._array[self._written : stop] = self._buffer[: self._buffered]
        self._written = stop
        self._buffered = 0

    def close(self) -> None:
        """Flush any remaining frames and confirm the stack is complete.

        Raises:
            ValueError: fewer frames were appended than ``shape`` promised.
                The data written so far stays on disk for inspection, but a
                short stack is an acquisition error and should never pass
                silently as a finished dataset.
        """
        if self._buffered:
            self._flush()
        if self._written != self.shape[0]:
            raise ValueError(
                f"stack incomplete: {self._written} of {self.shape[0]} frames"
            )

    def __enter__(self) -> ZarrStackWriter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Close (which checks completeness) only after a clean run. If the
        # block is already failing, closing would raise a second, confusing
        # error on top of the real one -- let the original problem surface.
        if exc_type is None:
            self.close()
