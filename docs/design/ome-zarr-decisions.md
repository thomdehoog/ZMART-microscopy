# The decisions: writing OME-Zarr for smart microscopy

One page. Every decision that is genuinely yours to make, what was chosen, and
what it affects. Everything not listed here is worked out by the software from
the frame shape and the overlap you asked for.

Detail lives in [`ome-zarr-checklist.md`](ome-zarr-checklist.md), the arrangement
in [`zmart-ome-zarr-recipe.md`](zmart-ome-zarr-recipe.md), and the measurements in
[`ome-zarr-for-analysis-and-neuroglancer.md`](ome-zarr-for-analysis-and-neuroglancer.md).

---

## The model that makes the rest obvious

Four numbers, each with one job, and the constraint flows in one direction only.
There is no circularity to reason about:

| | its job | what constrains it |
| --- | --- | --- |
| **frame** | given | the camera, or the acquisition settings. Nobody negotiates with it. |
| **shard** | absorbs the file-count problem | one tile plane — about 596,000 files on a five-terabyte run instead of 153 million |
| **chunk** | chosen for how the viewer behaves | must divide the frame; 128–288 is the sensible band |
| **overlap** | **the slack** | whatever the chunk allows, inside the range that stitches |

So the algorithm is three steps:

1. **The frame is given.**
2. **Take the largest chunk that divides it**, within the band.
3. **The overlap is whatever that chunk allows** — the operator's intent picks
   which multiple when there is more than one.

**Sharding is what makes this simple**, and it is worth understanding why. Without
it, the chunk *is* the file, so chunk size has to serve the filesystem and the
viewer at once — two masters pulling opposite ways. Bundle the chunks and the file
count becomes the shard's business entirely, leaving the chunk free to be picked
for viewing alone. One of the three tensions disappears.

> **But only if every level is bundled, and today only level 0 is.** The writer's
> comment says the smaller copies are "few enough not to need it", which is wrong
> by a factor of sixty-five on a two-terabyte run: level 0 bundled comes to
> 238,000 files while the unbundled pyramid above it comes to **20.3 million**.
> Once the full-resolution level is bundled, the pyramid *dominates* the count.
>
> Bundling every level brings the same run to **318,000 files** — the file count
> of a 2048-voxel chunk with the 32 KB fetches of a 128-voxel one. Until that is
> fixed, a large run really does need a bigger chunk, and the trade this section
> says has disappeared has not disappeared. It is a small change to
> `_make_the_copies`: bundle every level, capping the bundle at the level's own
> extent for the small ones.

The chunk's band has honest reasons at both ends, and neither is about files any
more: too small and you pay the browser's per-piece bookkeeping many times over;
too large and every fetch drags bytes you did not need.

**This is also why 2304 behaves well and 2048 does not.** A good frame size is one
with *many divisors*. 2304 has 128, 144, 192, 256 and 288 inside the band, so
there is an overlap near whatever you want. 2048's divisors there are only 128 and
256, so the overlap jumps from 12.5% straight to 25% with nothing between. 2880
and 3456 are better still, which is what to ask for when the format is settable.

---

## Decided once, for the whole project

| # | decision | chosen | why it matters |
| --- | --- | --- | --- |
| 1 | **Which version of the format** | **0.5** | 0.4 cannot bundle files, and a five-terabyte run then means 153 million of them |
| 2 | **What holds the pixels** | **the tiles**, whole, exactly as acquired | the only complete record; a stitcher can always go back to it |
| 3 | **How the viewer gets one image** | **a view that points at the tiles**, copying nothing | copying costs 1.98× the acquisition; stitching on the fly costs 647 ms a chunk against 4.6 |
| 4 | **Where analysis results go** | **inside the tile** — `labels`, `tables` | where ngio, napari and Fiji look; our viewer already finds them |
| 5 | **Where our own bookkeeping goes** | **beside the images**, never inside | a stray file inside makes zarr warn whoever opens it |
| 6 | **Plate layout for screening runs** | **no, on any instrument** | well and field become columns of the run table; one arrangement everywhere |
| 7 | **What ngio is for** | **reading, checking and analysing — never writing** | its version ceiling would otherwise become ours |
| 8 | **Whether the overlap is trimmed from the pixels** | **no** — it is accounted for in the viewer and in the analysis | the overlap is the only evidence of where the stage really went |

---

## Decided once per microscope

| # | decision | how to answer |
| --- | --- | --- |
| 9 | **Does this instrument need 0.6?** | Only if it acquires something 0.5 cannot describe — a light-sheet deskew, or rotations between views. Confocal and widefield: no. |
| 10 | **Snappy viewing, or cheap imaging?** | Sets which chunk gets chosen. Best is to align frame, chunk and overlap together: a **2304 sensor takes chunk 192 at 16.7% overlap with nothing shaved off** — 144 requests a tile-plane against 400 for chasing an exact 10%. A 4096 takes chunk 256 at 12.5%. 2048 is the awkward one: 12.5% or 25%, nothing between. |
| 11 | **What overlap does this stage really need?** | Measure it rather than believe it. The tiles are kept whole, so a stitcher can report how far each really moved. Offsets of a few voxels against a 204-voxel overlap mean you are paying for ten times what you need. |

---

## Decided per run — only two

| # | decision | options |
| --- | --- | --- |
| 11b | **On a point scanner, what scan format?** | Where the format is settable, ask for one that aligns: **2880** gives chunk 288, 20% overlap and only 100 requests a tile-plane; 3456 gives 16.7%; 4608 gives 12.5%. Better than 2048 on every axis at once. |
| 12 | **What kind of scan is this?** | `overview`, `targetscan`, … — it names the folder and separates acquisition types |
| 13 | **How much overlap?** | **none** (a survey you will never stitch, 1.0×) · **modest** (ordinary mosaics, ~1.3×) · **generous** (sparse specimens, light-sheet, ~1.6×) |

Give an **intent**, never a percentage. `modest` resolves to 10% on a 2048 or 2304
sensor and 12.5% on a 1024 scan — a literal 10% written into a workflow is
impossible on a 1024 frame and the run would be refused or silently written twice.

---

## Still to decide

| # | decision | the trade |
| --- | --- | --- |
| 14 | **Adopt chunk-aligned seams?** | Puts the join between two tiles exactly on a chunk edge, so the viewer can *skip* the shared strip instead of the writer *cutting* it. Removes the second copy from every overlapping run — 1.98× down to about 1.3×. **Deletes nothing:** the tiles stay whole. Costs a slightly stricter overlap grid. **Recommended.** |
| 15 | **HTTP/2 for the viewer?** | Takes a screen fill from ~440 ms of round trips to ~26 ms, but browsers speak it only over TLS, so a certificate on every microscope PC. **Take the bigger chunk first — it is free — then measure.** |
| 16 | **When to adopt scenes (0.6, RFC-5)?** | They describe our workflow exactly and would make the view stop being ours. But Neuroglancer has no notion of a scene and ngio cannot read 0.6 at all. **Wait for `ngio.NgffVersions` to gain `"0.6"`.** |
| 17c | **Widen the pyramid ladder, and average instead of stride?** | Measured: a 4× ladder costs 7.6% of the run against 36% for 2×, with no cells lost. An 8× ladder costs 1.8% but *striding* loses 37% of small cells — while *averaging* keeps 98%. And averaging was shown to preserve the pointing exactly (tile-by-tile is bit-for-bit whole-canvas), so the reason for striding does not hold. **An 8× averaged ladder would take the pyramid from 1.7 TB to 90 GB on a five-terabyte run.** Costs: averaging is arithmetic rather than a memory copy, and a coarse voxel stops being a real measurement. |
| 17b | **One file per position per level?** | Bundling taken to its end: ~50,000 files for a 10,000-position run instead of ~600,000, with small chunks still inside. But writing a plane at a time into a whole-tile shard measured **four times slower**, so it needs buffering — which costs memory and delays live viewing. **Explore; keep one tile plane per bundle meanwhile.** |
| 17 | **Fix the no-copy path for a drifting stage?** | It currently refuses runs whose tiles miss an exact grid, so an ordinary run falls back to copying. |

---

## One thing that does discard voxels, and it is your choice

Everything above keeps every voxel the camera recorded. There is exactly one
exception, and it should not be confused with the chunk-aligned seam above:

**Frame fitting.** To make a frame divide into whole chunks, the writer may store
2300 columns of a 2304 sensor — and those four columns are *never written*. It is
0.35% of the field, taken from the sensor's worst edge, and it is what allows an
overlap of exactly ten per cent rather than 12.5%.

It is capped at 1%, reported at setup in voxels and per cent, and refused rather
than exceeded. **And it is optional**: forbid it and nothing is discarded, at the
cost of taking 12.5% overlap on a 2048 sensor instead of 10%.

---

## Not decisions — the software settles these

Chunk size · how many voxels to trim from the frame · bundle size · how many
smaller copies · where the position is written in the metadata · the axes · file
and folder naming · whether a run is pointed at or copied.

All of them follow from the frame shape and the overlap intent. **Rigid where a
person chooses, derived where arithmetic does better than a person.**

---

## Before any of it: two things are blocking

1. **The per-dataset translation.** What we write today is invalid against the
   official schema, so ngio refuses our tiles and `ngff-zarr` stacks them all at
   the origin. The fix is written on `claude/ngff-translation-per-dataset`.
2. **Reading a bundle index in the viewer's server.** Without it there is no
   bundling, and without bundling a five-terabyte run cannot be copied.
3. **Bundling every level, not only the full-resolution one.** Measured on two
   terabytes: bundling level 0 alone leaves 20.6 million files, because the
   pyramid above it is unbundled and dominates. Bundling all of them leaves
   318,000. Until this is done, chunk size still has to serve the filesystem as
   well as the viewer.
