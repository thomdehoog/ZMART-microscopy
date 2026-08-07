# The decisions: writing OME-Zarr for smart microscopy

One page. Every decision that is genuinely yours to make, what was chosen, and
what it affects. Everything not listed here is worked out by the software from
the frame shape and the overlap you asked for.

Detail lives in [`ome-zarr-checklist.md`](ome-zarr-checklist.md), the arrangement
in [`zmart-ome-zarr-recipe.md`](zmart-ome-zarr-recipe.md), the measurements in
[`ome-zarr-for-analysis-and-neuroglancer.md`](ome-zarr-for-analysis-and-neuroglancer.md),
and the case for letting ngio write the positions in
[`ome-zarr-writing-through-ngio.md`](ome-zarr-writing-through-ngio.md).

---

## The model that makes the rest obvious

Four numbers, each with one job, and the constraint flows in one direction only.
There is no circularity to reason about:

| | its job | what constrains it |
| --- | --- | --- |
| **frame** | given | the camera, or the acquisition settings. Nobody negotiates with it. |
| **shard** | absorbs the file-count problem | one tile plane — for the *full-resolution level* of a five-terabyte run, about 596,000 files against 153 million unbundled. The smaller copies above it need shards of their own, which brings the whole run to about 2.98 million files. |
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
> comment says the smaller copies are "few enough not to need it", and counting
> them says otherwise. On a two-terabyte run, level 0 bundled comes to **238,419
> files** while the unbundled pyramid above it comes to **20.27 million** — about
> **20.50 million** all told. Once the full-resolution level is bundled, it is the
> *unbundled pyramid* that dominates the count, so bundling every level is the
> change that matters.
>
> Bundling does not merge the levels into one another. Each level of each tile
> still needs a bundle of its own for every plane, so bundling all five levels
> gives 238,419 × 5 = **about 1.19 million files** — a seventeen-fold reduction,
> clearly worth doing, but not the collapse to a handful of files it might sound
> like, and a very large run may still prefer a bigger chunk. It is a small change
> to `_make_the_copies`: bundle every level, capping the bundle at the level's own
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
| 1 | **Which version of the format** | **0.5** | 0.4 cannot bundle files, and a five-terabyte run then means 153 million of them at full resolution, about 203 million with the smaller copies |
| 2 | **What holds the pixels** | **the tiles**, whole, exactly as acquired | the only complete record; a stitcher can always go back to it |
| 3 | **How the viewer gets one image** | **a view that points at the tiles**, copying nothing | copying costs 1.98× the acquisition; stitching on the fly costs 647 ms a chunk against 4.6 |
| 4 | **Where analysis results go** | **inside the tile** — `labels`, `tables` | where ngio, napari and Fiji look; our viewer already finds them |
| 5 | **Where our own bookkeeping goes** | **beside the images**, never inside | a stray file inside makes zarr warn whoever opens it |
| 6 | **Plate layout for screening runs** | **no, on any instrument** | well and field become columns of the run table; one arrangement everywhere |
| 7 | **What ngio is for** | **reading, validating and analysing — not writing.** See [`ome-zarr-plan-review.md`](ome-zarr-plan-review.md) | Three reasons. It cannot resize an array, so a run would have to declare its whole extent generously up front and fill it in afterwards; it cannot write the view, which is not something any standards-compliant library would produce; and it brings roughly sixty packages onto the microscope computer, where `zmart_storage` needs only zarr and numpy. Speed is a smaller reason than it first looked, but not nothing: the original comparison of 4.5–5.5× was unfair, because the two paths were not doing the same amount of work, and configured the way a ZMART run needs, ngio costs about twice. Validate against its schemas in CI either way: the fault was a writer bug that shipped because nothing checked. |
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
| 12 | **On a point scanner, what scan format?** | Where the format is settable, ask for one that aligns: **2880** gives chunk 288, 20% overlap and only 100 requests a tile-plane; 3456 gives 16.7%; 4608 gives 12.5%. Better than 2048 on every axis at once. |
| 13 | **What kind of scan is this?** | `overview`, `targetscan`, … — it names the folder and separates acquisition types |
| 14 | **How much overlap?** | **none** (a survey you will never stitch, 1.0×) · **modest** (ordinary mosaics, ~1.3×) · **generous** (sparse specimens, light-sheet, ~1.6×) |

Give an **intent**, never a percentage. `modest` resolves to 10% on a 2048 or 2304
sensor and 12.5% on a 1024 scan — a literal 10% written into a workflow is
impossible on a 1024 frame and the run would be refused or silently written twice.

---

## Still to decide

| # | decision | the trade |
| --- | --- | --- |
| 15 | **Adopt chunk-aligned seams?** | Puts the join between two tiles exactly on a chunk edge, so the viewer can *skip* the shared strip instead of the writer *cutting* it. Removes the second copy from every overlapping run — 1.98× down to about 1.3×. **Deletes nothing:** the tiles stay whole. Costs a slightly stricter overlap grid. **Recommended.** |
| 16 | **HTTP/2 for the viewer?** | Takes a screen fill from ~440 ms of round trips to ~26 ms, but browsers speak it only over TLS, so a certificate on every microscope PC. **Take the bigger chunk first — it is free — then measure.** |
| 17 | **When to adopt scenes (0.6, RFC-5)?** | They describe our workflow exactly and would make the view stop being ours. But Neuroglancer has no notion of a scene and ngio cannot read 0.6 at all. **Wait for `ngio.NgffVersions` to gain `"0.6"`.** |
| 18 | **Widen the pyramid ladder, and average instead of stride?** | Measured: a 4× ladder costs 7.6% of the run against 36% for 2×, with no cells lost. An 8× ladder costs 1.8% but *striding* loses 37% of small cells — while *averaging* keeps 98%. And averaging was shown to preserve the pointing exactly (tile-by-tile is bit-for-bit whole-canvas), so the reason for striding does not hold. **On a five-terabyte run those measured percentages are about 1.8 TB of smaller copies today against about 90 GB for an 8× averaged ladder** — the arithmetic alone would say 79 GB, and the gap is the bookkeeping that compression and bundle indexes add. Costs: averaging is arithmetic rather than a memory copy, and a coarse voxel stops being a real measurement. |
| 19 | **One file per position per level?** | Bundling taken to its end, with small chunks still inside: on a 10,000-position run that is roughly **110,000 files**, where one bundle per tile plane per level gives **5,000,000**. But writing a plane at a time into a whole-position bundle measured **four times slower**, so it needs buffering, which costs memory and delays live viewing. The middle ground of a bundle holding eight to sixteen planes carries a cost of its own: the view refuses any store whose handed-over piece spans more than one plane (`zmart_storage/linked.py:552-558`), so it would have to be changed too. The arithmetic is in section 8.7 of [`zmart-ome-zarr-recipe.md`](zmart-ome-zarr-recipe.md). **Measure before committing to either extreme; keep one tile plane per bundle meanwhile.** |
| 20 | **Fix the no-copy path for a drifting stage?** | It currently refuses runs whose tiles miss an exact grid, so an ordinary run falls back to copying. |

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

## What has to be built, in order

Decisions above are numbered **1–20**; the work below is **B1–B11**, so a
reference is never ambiguous.

> **Revised 7 August 2026 after review.** See
> [`ome-zarr-plan-review.md`](ome-zarr-plan-review.md). That review called B2's
> stated implementation dangerous; a later reviewer checked the claim two ways and
> then measured it, and it does not hold, so B2 stands as it was first written.
> **The old B3, the server reading a bundle index, was struck out as already
> built — but B2 and B7 need more of it than was built, so it comes back as their
> prerequisite.** The struck-out B9 is deferred, B11 is a real work item now that
> `cropped.py` is staying, and two items are added that were missing. The review
> also reverses the proposal to write positions through ngio: adopt it for
> reading, validating and analysis only. Three of these are repairs — the
arrangement does not do what this page says it does until they are done. The rest
are improvements.

| | change | why |
| ---: | --- | --- |
| **B1** | **Per-dataset translation** on positions — **together with the matching change to the reader** | **repair.** Invalid against the official schema, so ngio refuses our tiles and `ngff-zarr` stacks them at the origin. Written on `claude/ngff-translation-per-dataset`. **The two halves must ship in one change.** `_where_the_view_begins` (`zmart_storage/linked.py:695-713`) currently adds up *both* places the translation can be written, the image-wide one and the per-level one, so the moment B1 lands on its own every position's position is counted twice and the whole canvas comes apart. |
| **B2** | **Bundle every level**, not only the full-resolution one, capping the bundle at the level's own extent so a small level does not declare a bundle larger than the data it holds | **repair.** 2 TB leaves 20.50 million files instead of about 1.19 million. An earlier review believed a capped bundle and an uncapped one would resolve differently and quietly hand back the wrong bytes; that was refuted twice over and then measured — the two resolve bit-for-bit identically — so the cap is safe. **Read the note below on B2 and B7 before starting either.** |
| ~~B3~~ | ~~The server reads a bundle index~~ | **deleted — already built.** `server.py` parses suffix ranges and serves byte windows; the pointer map is denominated in *shards*, so a whole shard file is handed over and the browser reads its index itself. Tested end to end — but only as far as the whole shard, so it has to come back for B2 and B7, which need a single chunk served from inside one. |
| **B3** | **Stop re-reading every tile the view has just written** | **repair, and new.** `_fill_this_tile_in` reopens and decompresses the array `positions.Run.write` was holding a moment earlier — five terabytes of pointless read in the live path. Pass the array through instead, and shrink from the coarsest level that already exists. |
| B4 | **Two interop tests** — schema validation and an ngio open | how change B1 would have been caught the day it appeared |
| B5 | **`plan_a_grid`** — frame + overlap intent → chunk, overlap, step | the workflow currently takes `piece=128` and hopes it suits the camera |
| B6 | **`tables/owned_ROI_table`** in every tile | makes the viewer's seam and the analysis filter one decision instead of two |
| B7 | **Chunk-aligned seams** | removes the second copy from every overlapping run. **Read the note below on B2 and B7 before starting either.** |
| B8 | **Unique label numbers across a run** | else cell 7 in two neighbouring tiles becomes one object |
| ~~B9~~ | ~~A view for segmentations~~ | **deferred.** A second copy of the whole view mechanism, for labelled runs that do not exist yet. Build it when one actually meets the cliff. |
| B9 | **Delete `zmart-coverage`** | ~1,700 lines read only by a benchmark. The pointer map already holds each tile's origin and size, and the per-channel residue is one column of B10. It is no longer free, though: `cropped.py` writes this record and is now staying, so that writer has to be changed as part of the deletion. |
| B10 | **A run-level table** | else a question about the run means opening ten thousand tables |
| B11 | **0.5 as the default in every writer** | both writers need it, because **`cropped.py` is staying**: with one bundle per tile plane, reading a small rectangle out of a tile still drags the whole plane's bundle off disk, so a path that reads a sub-rectangle efficiently still earns its place. |

---

## B2 and B7 get in each other's way — read this before starting either

As written today, **B2 takes B7 away.** B7 places each tile so that its join with
the next falls on a chunk edge, and the rule for where a tile may sit
(`zmart_storage/linked.py:1435-1439`) reads the chunk shape ZMART recorded for the
store, scaled up by however much the coarsest copy is shrunk so the placement
works at every level. For a bundled store that recorded shape is the **bundle**,
so once B2 gives every level one bundle per whole tile plane, a tile can only sit
on multiples of a whole tile, and such a grid cannot express any overlap. A
smaller bundle only shrinks the grid by its own size, never enough.

The way out is the struck-out **B3** above: the server handing over one chunk from
inside a bundle rather than the whole file. Until it can, reading the bundle shape
is *correct* rather than a bug. Once it can, the view side is **one line**:
`linked.py` already keeps the small chunk shape (`stored.inside_a_bundle`, line
477) and prefers it at lines 991 and 1107 — only the placement check does not.
**Do the server work first, and treat B2 and B7 as depending on it.**

---

## Before any of it

Changes **B1 and B2** above: the positions cannot be opened by anybody else's
software, and a run past a terabyte leaves twenty million files. B2 cannot land
without the server first serving a single chunk out of a bundle — the struck-out
**B3**, which B7 needs too — so that comes ahead of both. The live **B3** is not
blocking but costs five terabytes of pointless reading on a five-terabyte run.

**And one fault found in passing, which belongs here because it silently spoils
data.** In `zmart_storage/canvas.py`, the routine that builds the smaller copies
writes only the first channel. On any run with more than one channel, every
channel after the first is blank at every zoomed-out level. The run looks right at
full resolution and goes empty the moment you zoom out, which is an unkind way to
meet a bug in the middle of an experiment.
