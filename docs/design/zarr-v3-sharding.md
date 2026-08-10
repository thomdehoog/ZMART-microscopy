# Zarr v3 sharding, and what it would cost us — design note

- **Status:** investigation, 2026-08-10. Nothing in ZMART is built on this yet.
  This note records what was measured so that a later decision about OME-Zarr
  output does not have to rediscover it.
- **Scope:** the future image-writing story for ZMART (today every driver writes
  OME-TIFF), and the `zmart_drivers/mesospim/` bench-validation item that still
  lists the non-TIFF writers as unconfirmed.
- **Owner:** Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch ·
  thomdehoog@gmail.com

## Why this came up

ZMART currently saves an acquisition as **one OME-TIFF file per two-dimensional
plane**. You can see this in the Leica driver's
`acquisition/save.py`, which walks every plane of every position and writes each
one to its own file. That layout is easy to reason about and easy to inspect —
you can open a single plane in any viewer — but it produces a great many files.
A modest tiled z-stack can reach several thousand, and thousands of small files
are slow to copy to a server, slow to back up, and unpleasant to move between
institutes.

OME-Zarr is the community's answer to that problem, and its current version
(0.5) is built on version 3 of the Zarr storage format. Zarr v3 added a feature
called **sharding**, which is aimed squarely at the file-count problem. This note
asks two questions: does sharding actually help, and is the widely repeated
warning that "writing with shards is an order of magnitude slower" true?

## Chunks and shards, in plain language

A Zarr array is not one big file. It is cut into **chunks** — small rectangular
blocks of the image, each compressed and stored separately, so that a viewer can
read just the part of the data you are looking at instead of the whole volume.
That is what makes Zarr pleasant for large images.

The catch is that, in the original design, **one chunk means one file on disk**.
Choose chunks small enough to be useful for browsing and you are back to
thousands of files.

A **shard** is a single file that holds many chunks side by side, plus a small
table at the end recording where each chunk starts and how long it is. Readers
use that table to jump straight to the one chunk they want, so browsing stays
fast, while the operating system only ever sees a handful of files. In short: a
chunk is the unit you *read*, and a shard is the unit you *store*.

## The finding: the warning is about one specific mistake

The concern about slow sharded writing is real, but it is not a property of
sharding. It is a property of **filling a shard a little at a time**.

A shard file has to be written out as one continuous piece, because the table of
contents sits at the end and every entry has to be correct. So if you write one
plane into a shard that has room for many, the library has to rewrite the whole
shard file — everything already in it, plus the new plane, plus a fresh table.
Do that once per plane and you rewrite the same file over and over. This
pattern has a name in the storage world, **read-modify-write**: to change a small
part you must read the whole thing back, change it, and put the whole thing back.

The cost follows a simple rule, which the measurements below confirm exactly. If
a shard holds **N** chunks and you fill it one chunk at a time, you end up
writing

> (N + 1) / 2 times as many bytes as your data actually contains.

That extra work is called **write amplification** — the gap between the bytes
you meant to save and the bytes the disk really had to absorb. With 32 chunks
per shard you write about 16 times your data, which is where "an order of
magnitude" comes from. Write whole shards instead, and the amplification is
exactly 1.0 — no waste at all.

## What was measured

Timing alone is misleading here, and it is worth understanding why before
trusting any benchmark on this subject. Operating systems keep recently written
data in spare memory (the **page cache**) and flush it to disk later. If a test
rewrites the same file repeatedly, the cache quietly absorbs most of that work,
and a pattern that would be punishing on a real acquisition disk or a network
share can look almost free on a developer laptop with plenty of free memory. A
first attempt at this measurement produced a fifteen-fold difference, and a
second attempt on a warm cache produced barely twofold — same code, same data.

So the number reported here is not time but **the bytes the process actually
handed to the kernel**, read from `/proc/self/io`. That figure does not depend on
how much memory happens to be free, which makes it the honest one to compare.

Measured with zarr 3.3.0 on Python 3.12, writing a 101 MB stack
(48 × 1024 × 1024, 16-bit), which compresses to 86 MB on disk in every case
below — only the traffic needed to get it there differs:

| layout | how it was written | bytes written | files |
|---|---|---|---|
| unsharded, one plane per chunk | plane at a time | 87 MB | 49 |
| unsharded, 256×256 chunks | plane at a time | 90 MB | 769 |
| sharded, one plane per chunk | plane at a time | **732 MB** | 4 |
| sharded, one plane per chunk | whole shards at a time | 86 MB | 4 |
| sharded, 256×256 chunks | whole shards at a time | 86 MB | 4 |

The third row is the trap: 732 MB written to store 86 MB of images. The fourth
row is the same layout written sensibly, and it costs nothing extra — in that
run it was also the fastest of all five, because four large writes suit a disk
better than forty-nine small ones.

The amplification rule was checked directly, and it holds precisely:

| chunks per shard | predicted (N+1)/2 | measured |
|---|---|---|
| 4 | 2.5× | 2.5× |
| 8 | 4.5× | 4.5× |
| 16 | 8.5× | 8.5× |
| 32 | 16.5× | 16.5× |

One thing this is *not*: a bug in a particular release. Zarr 3.1.6 and 3.3.0
produce identical figures, so anyone who hit this on an older version would hit
it today. The write pattern is what matters, not the version.

## How mesoSPIM-control handles it

mesoSPIM-control already ships an OME-Zarr writer, so it is a useful worked
example — and a relevant one, because our own mesoSPIM driver still lists the
non-TIFF writers as bench-pending. Its writers live in
`mesoSPIM/src/plugins/ImageWriters/` with the real machinery in
`plugins/support_files/`, and they pin `zarr==3.1.3`.

**They avoid the trap, deliberately.** Planes arriving from the camera are
buffered in memory until a full chunk-depth has accumulated, and only then
written as one contiguous block. With their default settings on a 2048 × 2048
camera, each flush writes exactly one complete shard. Driving Zarr with their own
shard-planning function and their own write pattern gives an amplification of
**1.0×** — their design claim of "no read-modify-write" is accurate.

Four observations are worth carrying forward, because they are about the
*shape of the risk* rather than about their code quality:

- **The good behaviour rests on a configuration value, not on a check.** The
  alignment holds because the chunk depth and the shard depth happen to match.
  Both are operator-editable, and the only thing protecting the match is a
  sentence of advice in a docstring. Setting the chunk depth to 1 — which looks
  like an innocuous tuning choice — produced 32.5× amplification and a run
  roughly twenty-five times slower in our reproduction.
- **Sharding is not free even when perfectly aligned.** With identical bytes
  written, the sharded runs still took noticeably longer in wall-clock time than
  unsharded ones, because each shard requires many separate compressions plus
  index assembly. In their pipeline that work happens on background threads while
  the camera streams, so it may well be invisible in practice; the point is that
  the byte count alone does not capture the whole cost.
- **Completion signalling differs between their two closing paths.** A `.READY`
  marker file is written when finalisation runs in the background, but not when
  it runs synchronously — so a reader that waits for that marker will wait
  forever in the synchronous mode. Any ZMART driver that watches for completion
  needs to know which mode is configured.
- **The tail of a stack is padded, then trimmed.** A partly filled final chunk is
  padded — by default with *duplicated copies of the last plane* — written out,
  and then hidden again by shrinking the array. This is correct as written, but
  it means a crash at the wrong moment could leave fabricated planes on disk that
  look like real data.

## What this means for ZMART

**Sharding is the right tool for our file-count problem, and our situation is a
favourable one.** The Leica driver does not receive planes one at a time and race
to store them. It saves *after* the fact: `collect_lasx_native_autosave` returns
lazy references to plane files that LAS X has already written, and
`_persist_export` then walks them. Because every plane already exists before we
write anything, we are free to visit them in whatever order suits the storage
layout. Writing whole shards would be a change to loop ordering, not a
re-engineering of acquisition.

The memory cost is modest. A shard holding sixteen planes of 2048 × 2048 16-bit
pixels is about 128 MB — a comfortable buffer on any machine that runs a
microscope.

Three things to settle before anyone builds this:

1. **The interpreter.** Zarr 3.2.0 and later require Python 3.12 or newer, and
   `environment.yml` pins Python 3.11. The last release supporting 3.11 is 3.1.6.
   Adopting current Zarr therefore means moving the whole environment, which is a
   larger decision than adding a writer.
2. **Whether to replace OME-TIFF or sit beside it.** One plane per file is easy
   to inspect and easy to explain, and that has real value for people learning.
   An OME-Zarr writer alongside the existing one, chosen per acquisition, is
   probably kinder than a migration.
3. **Guard the geometry in code.** If we do build this, the chunk and shard
   shapes should be validated where the array is created, with a clear error
   rather than a comment. The lesson from the measurements is that a
   configuration that looks reasonable can cost thirty times the disk traffic,
   and nothing about the resulting file will tell you that it did.

## Reproducing the measurements

The numbers above came from short scripts that create arrays with different
chunk and shard shapes, write them with a given pattern, call `fsync` so the data
genuinely reaches storage, and read `/proc/self/io` before and after to count
bytes. They were run in a Linux container, so the wall-clock timings reflect that
filesystem and should be treated as indicative; the byte counts are a property of
the format and the write pattern, and should reproduce anywhere.

If you repeat this, the one thing worth preserving is the discipline of counting
bytes rather than seconds, and of writing to a fresh directory each time. Almost
every confusing result in this investigation came from measuring the page cache
by accident.
