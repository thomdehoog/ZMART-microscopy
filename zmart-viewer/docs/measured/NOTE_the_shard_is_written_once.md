# Note: a shard is written once, or paid for about N/2 times

> Findings from the shard-write spike on branch
> `claude/zarr-shard-write-perf-fq0upm` (commit `22a9e17`, the spike and its
> 38 tests live under `zmart_drivers/mesospim/spike/zarr_sharding/` there),
> read against this branch's writer on 2026-08-14. The spike's numbers are
> its own README's; the file:line claims below are this branch's.

## What the spike pins

Zarr v3's slow path with sharded arrays is a genuine read-modify-write of
the whole shard file on every partial write: fill an N-deep shard in N
separate writes and the bytes written total about (N+1)/2 times the shard's
size. The spike measures amplification growing 0.55 → 8.93 as shard depth
goes 1 → 32 under frame-at-a-time writing, following that formula exactly,
and pins the mechanism with byte-counting stores rather than stopwatches —
a buffered writer that flushes one whole shard per operation stays flat at
0.55 and reads nothing back.

The sharpening that matters for design: **chunks per shard is free; the
number of separate write operations per shard is what costs.** At a fixed
depth the amplification was the same at 1024, 256 and 64 chunks per shard.
And zarr compresses one shard's chunks across several cores by itself, so
the buffering is about write count, not about adding concurrency.

## Where this branch already complies

The live writer is compliant by construction. Each position level's shard
spans the whole level (``zmart_live/profiles.py:788``), and
``_write_one_level`` (``zmart_live/coordinator.py:604``) fills it with a
single assignment per (timepoint, channel) — one shard, one write. The
pyramid levels fan out over threads, each thread owning a different array,
so no shard is ever filled piecemeal.

``zmart_storage/canvas.py:912`` pinned the *correctness* half of the same
mechanism long ago — concurrent partial writes into one bundle lose tiles,
so the exclusion grain is ``array.shards or array.chunks``. The spike's
finding is the *speed* half of the identical read-modify-write, measured.

## The trap worth writing down

The per-commit bake is **unsharded on purpose**, though until now nothing
said so. ``declare.py`` writes baked pieces as raw chunk files and
``governed.py``'s ``_keep_the_bake_true`` patches single pieces in place —
cheap precisely because a piece is a file. Sharding the baked levels is an
attractive thought (they are the many-tiny-files case sharding exists for),
and it would put every one-piece patch on the spike's slow path: a whole
shard read, merged, rewritten, per patch, at the (N+1)/2 factor. Shard the
bake only together with a patcher that rebuilds whole shards.

## What the fixture write is actually spending

The ladder's fixture writes looked like a candidate for this finding and
are not. The arithmetic clears them: 8,281 positions is 3.24 GB written in
505 s — 6.4 MB/s, some twenty-five times below even the spike's *slow*
strategy — and the cost is linear in position count at ~65 ms per position
whatever the pixel bytes say. The time is per-position metadata work,
about thirteen small-file operations each, two of them avoidable:

- ``coordinator.py:603`` re-opens, via a fresh read of ``zarr.json``, the
  very array ``zarr.create_array`` returned a handle for two lines above.
- ``omezarr.py:628`` reads and rewrites each level's ``zarr.json`` a second
  time to name its dimensions, on every publish — where passing
  ``dimension_names=`` at creation (as ``declare.py`` already does for its
  arrays) would write the document right the first time.

Fixing those two plausibly cuts the fixture write two- to three-fold, and
unlike a fixture-only trick it speeds every real acquisition publish. The
fixture writer is also embarrassingly parallel across positions, each being
its own store tree, which attacks the fixed cost from the other side.

## Worth lifting from the spike, when the time comes

- The ~15-line byte-counting store, as a regression guard: nothing in
  ``zmart_live/tests`` today would catch a refactor that turned the one
  whole-shard assignment into a per-plane loop; a test asserting zero bytes
  read during ``write_a_position`` would pin it for good.
- ``ZarrStackWriter`` itself, for any driver that streams camera planes.
  The mesoSPIM profile sizes its slab from 512 MB ``target_shard_bytes``
  (``profiles.py:773``), so a real light-sheet stack gets shards many
  planes deep — a per-plane write loop against that geometry is exactly the
  naive case, at the spike's measured four- to nine-fold amplification.
