# The decisions: writing OME-Zarr for smart microscopy

One page. Every decision that is genuinely yours to make, what was chosen, and
what it affects. Everything not listed here — chunk size, frame trim, bundle size,
the axes, naming, whether a run is pointed at or copied — follows from the frame
shape and the overlap intent. **Rigid where a person chooses, derived where
arithmetic does better than a person.**

**No production code has changed yet** — this page is a plan: the writer still
bundles only level 0, the smaller copies still take every nth voxel, and the view,
coverage and `cropped.py` are all still there.

Detail lives in [`ome-zarr-checklist.md`](ome-zarr-checklist.md), the arrangement
in [`zmart-ome-zarr-recipe.md`](zmart-ome-zarr-recipe.md), the measurements in
[`ome-zarr-for-analysis-and-neuroglancer.md`](ome-zarr-for-analysis-and-neuroglancer.md),
and the ngio-as-writer case in
[`ome-zarr-writing-through-ngio.md`](ome-zarr-writing-through-ngio.md).

---

## The model that makes the rest obvious

Four numbers, each with one job, the constraint flowing one way only:

| | its job | what constrains it |
| --- | --- | --- |
| **frame** | given | the camera, or the acquisition settings — nobody negotiates with it |
| **shard** | absorbs the file-count problem | one tile plane — about 596,000 files for a five-terabyte run's *full-resolution level*, against 153 million unbundled |
| **chunk** | chosen for how the viewer behaves | must divide the frame; 128–288 is the sensible band |
| **overlap** | **the slack** | whatever the chunk allows, inside the range that stitches |

So: **the frame is given**; **take the largest chunk that divides it**, within the
band; and **the overlap is whatever that chunk allows**.

**Sharding is what makes this simple.** Without it the chunk *is* the file, so its
size has to serve the filesystem and the viewer at once. Bundle the chunks and the
file count becomes the bundle's business, leaving the chunk free for viewing.

> **But only if every level is bundled, and today only level 0 is.** The writer
> calls the smaller copies "few enough not to need it"; counting says otherwise. On
> a two-terabyte run a bundled level 0 is **238,419 files** against **20.27
> million** loose ones above it, and bundling every level brings the run to **about
> 1.19 million**. But **how** they are bundled matters; see B2.

The band has honest reasons at both ends: too small and the browser's per-piece
bookkeeping dominates; too large and every fetch drags bytes you never needed.

**This is also why 2304 behaves well and 2048 does not.** A good frame size has
*many divisors*: 2304 offers 128, 144, 192, 256 and 288 inside the band, so there
is an overlap near whatever you want, where 2048 offers only 128 and 256.

---

## Decided once, for the whole project

| # | decision | chosen | why it matters |
| --- | --- | --- | --- |
| 1 | **Which version of the format** | **0.5** | 0.4 cannot bundle files at all, and unbundled a five-terabyte run is about 203 million of them |
| 2 | **What holds the pixels** | **the tiles**, whole, exactly as acquired | the only complete record; a stitcher can always go back to it |
| 3 | **How the viewer gets one image** | **a view that points at the tiles**, copying nothing | copying costs 1.98× what the camera produced; stitching on the fly costs 647 ms a chunk against 4.6 |
| 4 | **Where analysis results go** | **inside the tile** — `labels`, `tables` | where ngio, napari and Fiji look; our viewer already finds them |
| 5 | **Where our own bookkeeping goes** | **beside the images**, never inside | a stray file inside makes zarr warn whoever opens it |
| 6 | **Plate layout for screening runs** | **no, on any instrument** | well and field become columns of the run table, so one arrangement serves everywhere |
| 7 | **What ngio is for** | **reading, validating and analysing — not writing, for now.** See [`ome-zarr-plan-review.md`](ome-zarr-plan-review.md) | **Not today, rather than never**, since permanent rejection would sit badly with this project's preference for ecosystem packages. What decides it now: ngio caps its bundles on the small levels, which a view that forwards bytes cannot use (see B2), and it has never been qualified on a Windows microscope computer. The older reasons stand: it cannot resize an array, so a run must declare its whole extent up front; it cannot write the view; and it brings roughly sixty packages onto a computer where `zmart_storage` needs two. |
| 8 | **Whether the overlap is trimmed from the pixels** | **no** — it is accounted for in the viewer and in the analysis | the overlap is the only evidence of where the stage really went |

---

## Decided once per microscope

| # | decision | how to answer |
| --- | --- | --- |
| 9 | **Does this instrument need 0.6?** | Only if it acquires something 0.5 cannot describe — a light-sheet deskew, or rotations between views. Confocal and widefield: no. |
| 10 | **Snappy viewing, or cheap imaging?** | Sets which chunk gets chosen; best is to align frame, chunk and overlap. A **2304 sensor takes chunk 192 at 16.7% overlap with nothing shaved off**, which is 144 chunks a tile-plane against 400 for chasing an exact 10%. |
| 11 | **What overlap does this stage really need?** | Measure it rather than believe it. The tiles are kept whole, so a stitcher can report how far each really moved, and offsets of a few voxels against a 204-voxel overlap mean you are paying ten times over. |

---

## Decided per run — only two

| # | decision | options |
| --- | --- | --- |
| 12 | **On a point scanner, what scan format?** | Where the format is settable, ask for one that aligns: **2880** gives chunk 288, 20% overlap and only 100 chunks a tile-plane, while 3456 and 4608 give 16.7% and 12.5%. |
| 13 | **What kind of scan is this?** | `overview`, `targetscan`, … — it names the folder and separates acquisition types |
| 14 | **How much overlap?** | **none** (a survey you will never stitch, 1.0×) · **modest** (ordinary mosaics, ~1.3×) · **generous** (sparse specimens, light-sheet, ~1.6×) — each a multiple of the *unique specimen area*. |

Give an **intent**, never a percentage: `modest` is 10% on a 2048 sensor and 12.5%
on a 1024 scan, and a literal 10% written into a workflow is impossible on a 1024
frame.

---

## Still to decide

| # | decision | the trade |
| --- | --- | --- |
| 15 | **Adopt chunk-aligned seams?** | Puts the join between two tiles exactly on a chunk edge, so the viewer *skips* the shared strip instead of the writer *cutting* it: the second copy goes, and the writer's **1.98×** against what the camera produced falls to about **1.3×**, the overlap's own cost against unique specimen area. **Deletes nothing**, since the tiles stay whole; costs a slightly stricter overlap grid. **Recommended.** |
| 16 | **HTTP/2 for the viewer?** | Takes a screen fill from ~440 ms of round trips to ~26 ms, but browsers speak it only over TLS — a certificate on every microscope PC. **Take the bigger chunk first, since it is free, then measure.** |
| 17 | **When to adopt scenes (0.6, RFC-5)?** | They describe our workflow exactly and would let the view stop being ours, but Neuroglancer knows nothing of scenes and ngio cannot read 0.6. **Wait for `ngio.NgffVersions` to gain `"0.6"`.** |
| 18 | **Widen the pyramid ladder, and average instead of stride?** | Measured: a 4× ladder costs 7.6% of the run against 36% for 2×, losing no cells; an 8× ladder costs 1.8%, but *striding* loses 37% of small cells where *averaging* keeps 98%. Shrinking each tile on its own matches shrinking the finished canvas **only where the tiles line up with the blocks being averaged**, and that alignment is much coarser than this page first said. Each level shrinks by the ladder's step *again*, so an 8× ladder stands at total shrinks of 8, then 64, then 512, and a tile's origin and the extent of ground it owns must be whole multiples of the total shrink of **the deepest level the view builds tile by tile** — 512 for a three-level 8× ladder, not 8. At an ordinary seam of 1,632 voxels (chunk 204 × 8) level 1 came out exact, while level 2 was out by 32 and level 3 by 96, each with one coarse voxel no tile could supply. The error is the seam's remainder against that level's total shrink, so seams at 2,048 or 4,096 stay exact throughout. **The reassurance once recorded here was half true**: `linked.py` checks alignment against the levels the view *points at*, not the deeper ones it builds for itself, which is exactly where this appears. The phase check must therefore stay, either widened to the deepest level built that way, or replaced by joining the tiles before shrinking. Costs: a coarse voxel is then an average rather than a real measurement. |
| 19 | **One file per position per level?** | Bundling taken to its end: roughly **110,000 files** on a 10,000-position run against **5,000,000** for one bundle per tile plane per level. But writing a plane at a time into a whole-position bundle measured **four times slower**, so it needs buffering, which costs memory and delays live viewing; and the view refuses any handed-over piece spanning more than one plane. §8.7 of [`zmart-ome-zarr-recipe.md`](zmart-ome-zarr-recipe.md) has the arithmetic. **Measure first; keep one tile plane per bundle meanwhile.** |
| 20 | **Fix the no-copy path for a drifting stage?** | It currently refuses runs whose tiles miss an exact grid, so an ordinary run falls back to copying. |

---

## The one thing that discards voxels

Everything above keeps every voxel the camera recorded, with one exception, not to
be confused with the chunk-aligned seam: **frame fitting.** To make a frame divide
into whole chunks the writer may store 2300 columns of a 2304 sensor, and those
four columns are *never written* — 0.35% of the field, from the sensor's worst
edge, and what buys an overlap of exactly ten per cent. It is capped at 1%,
reported at setup, and **optional**: forbid it and nothing is discarded, at the
cost of a 12.5% overlap on a 2048 sensor.

---

## What has to be built, in order

Decisions above are numbered **1–20**, the work below **B1–B11**.

> **Revised 7 August 2026, and corrected again each time a reviewer ran the
> code.** See [`ome-zarr-plan-review.md`](ome-zarr-plan-review.md). Three of these
> are repairs: the arrangement does not do what this page says until they are done.

| | change | why |
| ---: | --- | --- |
| **B1** | **Per-dataset translation** on positions — **together with the matching change to the reader** | **repair.** Invalid against the official schema, so ngio refuses our tiles and `ngff-zarr` stacks them at the origin. Written on `claude/ngff-translation-per-dataset`. **The two halves must ship together**, because our reader adds the image-wide translation and then every dataset's as well, so the writer's fix arriving alone would multiply each position's offset by the number of levels. |
| **B2** | **Bundle every level**, not only the full-resolution one — but **not with the bundle capped at the level's own extent** while the view points at those levels | **repair, re-qualified.** Still required — the counts are above. But the capping hazard, recorded here as refuted, is **real**: a capped bundle and an uncapped one holding the same pixels are different files, because they index a different number of inner chunks and that index is checksummed, so a browser handed capped bytes under the view's declared shape rejects them (the checklist has the byte counts). So **B2 must not be built as written while the view points at capped smaller levels.** Preferably, let the view advertise the small inner chunks and have the server, or TensorStore, hand back one inner chunk rather than a whole file; failing that, point the view at full resolution alone and let it write its own smaller copies, giving up the very thing it was built to avoid. |
| ~~B3~~ | ~~The server reads a bundle index~~ | **deleted — already built**, but only as far as a whole shard file, which the browser then indexes itself. B2 and B7 need one chunk from *inside* a bundle, so it comes back. |
| **B3** | **Refresh the view's own coarse levels on every write, for the channel being written** — and stop re-reading the tile the writer is still holding | **repair, and blocking.** `positions.Run.write` tells the view about a place only the first time it sees that place, and the view then fills the coarse levels it writes for *itself* by reading the position store at that instant, before the run's later channels exist. Reproduced both ways round: with full resolution holding 11 and 29 for two channels, writing channel 0 first left the view's levels 1 and 2 holding 11 and 0, and writing channel 1 first left 0 and 29. The repair is to update the current moment-and-channel's view levels on **every** write, while still adding the position's pointer the first time only. Handing that update the image already in memory also stops `_fill_this_tile_in` re-reading the array the writer was holding a moment earlier, five terabytes of pointless reading in the live path. `canvas.py`, the positions' own copies and the batch path are all correct. |
| B4 | **Two interop tests** — schema validation and an ngio open | how B1 would have been caught the day it appeared |
| B5 | **`plan_a_grid`** — frame + overlap intent → chunk, overlap, step | the workflow currently takes `piece=128` and hopes it suits the camera |
| B6 | **`tables/owned_ROI_table`** in every tile | makes the viewer's seam and the analysis filter one decision instead of two |
| B7 | **Chunk-aligned seams** | removes the second copy from every overlapping run. **Read the note below first.** |
| B8 | **Unique label numbers across a run** | else cell 7 in two neighbouring tiles becomes one object |
| ~~B9~~ | ~~A view for segmentations~~ | **deferred.** A second copy of the whole view mechanism, for labelled runs that do not exist yet. |
| B9 | **Delete `zmart-coverage`, but only once something else records what it records** | ~1,700 lines read by nothing but a benchmark, so removing it looks nearly free — and it is not. Beyond each tile's origin and size, which the pointer map holds, the record keeps the moment in time and the channel, the order things were written in, the exact origin and shape, the scan's own numbering of its tiles, repeated visits to one place, and whether a leg of the run finished or was abandoned. No column of B10's table replaces any of that, so the deletion is safe **after** an append-only record of run events takes those duties over, and not before. `cropped.py` writes this record and is staying, so that writer changes too. |
| B10 | **A run-level table** | else a question about the run means opening ten thousand tables |
| B11 | **0.5 as the default in every writer** | both writers need it, because **`cropped.py` is staying** — though not for either reason recorded here before. It is a writer, not a rectangle reader, and not the only path that can represent overlap: a no-copy view of two 128-voxel tiles acquired 96 voxels apart, cropped 16 voxels at the shared seam, was built and read back through `linked.py`'s existing `taken_from` and `size` fields, so the view holds an overlapping run wherever the tiles are aligned. What keeps `cropped.py` is being the only **turnkey writer** for one: in a single pass it trims half the shared strip from each meeting edge so the tiles butt together, keeps every original tile whole in a separate archive for the stitcher, and leaves a **portable OME-Zarr with real pixels in it** that opens in napari or Fiji alone, where the view is meaningless without its positions folder. (`TileCanvases` still refuses overlapping tiles outright, since one voxel holds one value.) Revisit once inner-chunk serving or TensorStore works. |

---

## B2 and B7 get in each other's way

As written today, **B2 takes B7 away.** B7 puts each tile's join with the next on
a chunk edge, but the rule for where a tile may sit reads the chunk shape ZMART
recorded for the store, and for a bundled store that shape is the **bundle**. So
once B2 gives every level one bundle per whole tile plane, a tile can only sit on
multiples of a whole tile — a grid that cannot express any overlap.

The way out is the struck-out **B3**: the server handing over one chunk from
inside a bundle rather than the whole file. Until it can, reading the bundle shape
is *correct* rather than a bug; once it can, the view side is **one line**, since
`linked.py` already keeps the small chunk shape and prefers it everywhere except
the placement check.

**The alignment rule in 18 sharpens the same tension.** A wide ladder and pointing
at the positions' smaller copies are not inherently at odds: pointing at three
smaller levels asks for tiles aligned to chunk × 64, as the first review said, and
pointing at one can work if the inner chunks are exposed and origins and extents
line up to chunk × 8. What cannot work is pointing at smaller levels while a whole
2048-voxel tile plane is the smallest thing placeable, since even the first
smaller level would then need 16,384-voxel alignment.

**Benchmark TensorStore first; build the inner-chunk server only if it fails the
gate.** Its overlay driver may remove the need for that machinery, which is what
this project prefers. A warm overlay of ten thousand positions already clears the
gate on Linux by a wide margin, but says nothing about a cold Windows filesystem
or several readers filling a screen at once, so **the deciding run is on a
microscope computer.** The checklist has the gate and the timings.

---

## Before any of it

**B1, B2 and B3 come first.** Nobody else's software can open the positions; a run
past a terabyte leaves twenty million files; and a two-channel run written today
looks entirely correct until the operator zooms out, at which point one channel
goes blank — a bad way to discover a fault in the middle of an experiment, and the
reason B3 belongs here rather than among the things that can wait. B2 waits on the
benchmark above.
