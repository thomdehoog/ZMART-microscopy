# Zarr sharding spike: writing a z-stack without the shard write penalty

## The problem

Zarr version 3 can pack many small chunks into one big file called a *shard*.
Shards matter for microscopy because a whole-brain OME-Zarr with small chunks
can otherwise become millions of tiny files, which is very slow to copy and
hard on network storage.

But sharding has a trap. The shard file is the smallest thing Zarr can store,
so if you write only *part* of a shard — one camera frame into a shard that
spans 16 frames — Zarr has to read the whole shard file back from disk, unpack
it, swap in your new frame, repack everything, and write the whole file out
again. Streaming an acquisition frame by frame into deep shards therefore
writes the same data over and over, and saving becomes several times slower
than without sharding. That is exactly the slowdown that motivated this spike.

## The strategies

`zarr_write_strategies.py` implements five ways to stream a stack, all behind
the same small interface (create the writer, `append(frame)` once per camera
frame in z order, `close()` at the end):

| Strategy             | Idea                                                            | Cost                        |
| -------------------- | --------------------------------------------------------------- | --------------------------- |
| `unsharded`          | No shards; every chunk is its own file.                         | Huge file count             |
| `naive-sharded`      | Deep shards written one frame at a time — the slow case, kept as the baseline to beat. | Rewrites each shard many times |
| `plane-shards`       | Shards exactly one frame thick, so a frame write always covers whole shards. | Shards can never span frames |
| `buffered-sharded`   | Deep shards, but frames collect in a RAM buffer that is flushed one whole shard at a time. | RAM for one shard of frames |
| `write-then-reshard` | Acquire unsharded at full speed, repack into shards afterwards. | Writes everything twice; temporary disk |

## What the benchmark showed

Measured on a 64 × 2048 × 2048 uint16 stack (537 MB, synthetic microscopy-like
data), streaming frame by frame, with the default Zarr compressor. *Write
amplification* is bytes actually sent to disk divided by the bytes in the
stack — 1.0 × the compression ratio is perfect; more means the same data was
packed and written repeatedly. `read_MB` is data read *back* from disk while
writing, which should be zero.

| strategy           | chunk | shard_z | wall_s | cpu_s | MB/s | write_amp | read_MB | files |
| ------------------ | ----: | ------: | -----: | ----: | ---: | --------: | ------: | ----: |
| unsharded          |   512 |       – |   3.14 |  7.48 |  171 |      0.55 |       0 |  1025 |
| naive-sharded      |   512 |      16 |   6.73 | 10.36 |   80 |      4.69 |    2225 |     5 |
| plane-shards       |   512 |       1 |   3.50 |  7.45 |  154 |      0.55 |       0 |    65 |
| buffered-sharded   |   512 |      16 |   3.59 |  7.99 |  150 |      0.55 |       0 |     5 |
| write-then-reshard |   512 |      16 |   8.52 | 18.91 |   63 |      1.10 |     296 |     5 |

The same pattern holds at every chunk size we swept (256, 512, 1024 pixels)
and every shard depth (8, 16, 32 frames on a 67 MB stack too):

- **`naive-sharded` is the problem, measurably.** With 16-frame shards it
  pushed 4.7× the necessary bytes to disk and read 2.2 GB back while "writing"
  a 537 MB stack — that is the read-modify-write cycle happening once per
  frame. The deeper the shard, the worse it gets (8.9× amplification at 32
  frames per shard). This is the slowdown you see when you stream frames
  naively into a sharded array.
- **`buffered-sharded` wins overall.** It matches unsharded speed (within a
  few percent, and it was the outright fastest run in the whole sweep at
  200 MB/s), keeps write amplification at exactly the compression ratio with
  zero read-back, and produces 5 files instead of 1025. The price is RAM for
  one shard of frames: 16 frames of 2048 × 2048 uint16 is 128 MB.
- **`plane-shards` is the zero-RAM runner-up.** Essentially the same speed,
  no buffer at all, and still a 16-fold file-count reduction (one file per
  frame). Choose it when memory is tight and one-frame-deep shards are
  acceptable for how the data will be read later.
- **`write-then-reshard` is honest but expensive**: about 2–3× the wall time
  and the most CPU of any strategy, because the whole stack is compressed and
  written twice. It only makes sense when acquisition itself must be as lean
  as possible and repacking can happen later (between positions, overnight).
- **Chunk size matters as much as strategy.** 256-pixel chunks were ~2× slower
  to write than 1024-pixel chunks across the board — many small chunks mean
  many per-chunk compressor calls and (unsharded) many files. For writing,
  bigger chunks are cheaper; for interactive *reading* (napari tiles), smaller
  chunks are nicer. Sharding is exactly the tool that lets you keep read-sized
  chunks (e.g. 256–512 px) inside write-sized files.

**Recommendation:** stream with `buffered-sharded` — chunks around
1 × 512 × 512, shards 16–32 frames deep covering the full frame — and fall
back to `plane-shards` when the buffer RAM is not available.

## How time scales with chunks per shard

A dedicated sweep (32 × 1024 × 1024 stack, 67 MB, 256-pixel chunks, shard
depth 1–32 frames, so 16–512 chunks per shard) pins down the scaling law:

| shard depth | chunks/shard | naive wall_s | naive write_amp | buffered wall_s | buffered write_amp |
| ----------: | -----------: | -----------: | --------------: | --------------: | -----------------: |
|           1 |           16 |         0.71 |            0.55 |            0.56 |               0.55 |
|           2 |           32 |         0.74 |            0.82 |            0.52 |               0.55 |
|           4 |           64 |         0.68 |            1.37 |            0.48 |               0.55 |
|           8 |          128 |         0.73 |            2.47 |            0.50 |               0.55 |
|          16 |          256 |         1.17 |            4.64 |            0.49 |               0.55 |
|          32 |          512 |         1.78 |            8.93 |            0.50 |               0.55 |

What this says, strategy by strategy:

- **`naive-sharded` grows linearly with shard depth.** Each frame write
  repacks everything already in the shard, so filling an *N*-frame shard
  writes it out *N* times at growing sizes — about (*N* + 1)/2 times the
  shard's bytes in total. The measured amplification follows that formula
  exactly: 0.55 × (*N* + 1)/2 (0.55 is the compression ratio). Wall time
  looks flat at small depths only because fixed per-write costs dominate on
  fast local disk; once the rewrite traffic outweighs them (here around
  depth 8) time climbs linearly, and on slower network storage the linear
  term takes over almost immediately.
- **Every other strategy is flat** — constant in shard depth, because each
  fills every shard in exactly one write. `buffered-sharded` sits at
  ~0.5 s and amplification 0.55 whether shards hold 16 or 512 chunks;
  `plane-shards` is the depth-1 point of the same flat line;
  `write-then-reshard` is a flat line at roughly 2× (constant amplification
  1.10, everything written twice); `unsharded` has no shards to scale with.
- **It is the number of writes per shard that matters, not the chunk count
  itself.** At a fixed 16-frame depth, naive writing was slow at 1024, 256,
  and 64 chunks per shard alike (its amplification stayed ≈ 4.7 in all
  three) — varying *how many chunks* a shard holds changes little, while
  varying *how many separate writes* fill it changes everything. Chunk size
  has its own independent, gentler effect through per-chunk compressor and
  file overhead (small chunks cost more for every strategy).

So the rule of thumb for any writer: you may make shards as deep as you
like — chunks per shard is free — as long as each shard is written in a
single operation. The moment a shard is filled in *N* separate writes, you
pay for it roughly *N*/2 times over.

## The take-away, as usable code

The winning strategy is packaged as a standalone, production-ready writer in
[`buffered_zarr_writer.py`](buffered_zarr_writer.py) — one class, depending
only on `numpy` and `zarr >= 3`, that you can copy into any project as-is:

```python
from buffered_zarr_writer import ZarrStackWriter

with ZarrStackWriter("stack.zarr", shape=(128, 2048, 2048)) as writer:
    for frame in camera:          # 2-D numpy arrays, in z order
        writer.append(frame)
```

It buffers one shard's worth of frames and flushes each shard in a single
write, validates every frame on arrival, refuses to overwrite existing data
unless asked, and fails loudly if a stack ends short. Its own test suite is
[`test_buffered_zarr_writer.py`](test_buffered_zarr_writer.py) — including a
test instrumenting the store to prove the slow read-back path is never taken,
a seeded randomized sweep over 30 awkward geometries, and a cross-check that
reads the written store back with tensorstore (an independent C++ Zarr
implementation, skipped when not installed) to confirm the files conform to
the Zarr v3 format itself, not merely to zarr-python's own round trip.
(`zarr_write_strategies.py` remains the benchmark/comparison harness; the
writer file is the one to take home.)

## Running it yourself

The spike needs `zarr >= 3` (not part of the canonical ZMART environment;
install it just for this experiment):

```
pip install "zarr>=3"

# correctness + mechanism tests (byte-count based, no flaky timings)
pytest test_zarr_write_strategies.py

# the benchmark: sweeps chunk sizes and shard depths, prints a table
python zarr_write_strategies.py
python zarr_write_strategies.py --shape 64 2048 2048 --chunk-sizes 256 512 1024 --shard-depths 16 --csv results.csv
```

The benchmark synthesizes a microscopy-like stack (dark background, bright
blobs, shot noise — so the compressor does a realistic amount of work), holds
it in RAM, and then times only the writing. A byte-counting store wrapper
measures true disk traffic in both directions, so the rewrite problem shows up
as hard numbers instead of vibes.

One caveat worth knowing: these runs used fast local scratch storage. On a
network share or spinning disk, the gap only widens — `naive-sharded` pays for
its extra gigabytes of traffic even more dearly, and `unsharded` pays more for
its thousands of file creations. The winners stay the same for the same
reasons.
