# The decisions: writing OME-Zarr for smart microscopy

One page. Every decision that is genuinely yours to make, what was chosen, and
what it affects. Everything not listed here — chunk size, frame trim, bundle size,
how many smaller copies, where the position is written, the axes, naming, whether
a run is pointed at or copied — follows from the frame shape and the overlap
intent. **Rigid where a person chooses, derived where arithmetic does better than
a person.**

**No production code has changed yet.** This page is a plan, not a description of
the system: the writer still bundles only level 0, the smaller copies still take
every nth voxel, and the view, coverage and `cropped.py` are all still there.

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
size must serve the filesystem and the viewer at once — two masters pulling
opposite ways. Bundle the chunks and the file count becomes the bundle's business,
leaving the chunk free for viewing alone.

> **But only if every level is bundled, and today only level 0 is.** The writer's
> comment says the smaller copies are "few enough not to need it", and counting
> says otherwise: on a two-terabyte run a bundled level 0 is **238,419 files**
> against **20.27 million** loose ones above it. Each level still needs a bundle of
> its own for every plane, so bundling all five brings the run to **about 1.19
> million** — a seventeen-fold reduction. But **how** they are bundled matters; see
> B2.

The band has honest reasons at both ends: too small and you pay the browser's
per-piece bookkeeping many times over; too large and every fetch drags bytes you
never needed.

**This is also why 2304 behaves well and 2048 does not.** A good frame size has
*many divisors*: 2304 offers 128, 144, 192, 256 and 288 inside the band, so there
is an overlap near whatever you want; 2048 offers only 128 and 256, so the overlap
jumps from 12.5% to 25%.

---

## Decided once, for the whole project

| # | decision | chosen | why it matters |
| --- | --- | --- | --- |
| 1 | **Which version of the format** | **0.5** | 0.4 cannot bundle files: unbundled, a five-terabyte run is 153 million at full resolution, about 203 million with the smaller copies |
| 2 | **What holds the pixels** | **the tiles**, whole, exactly as acquired | the only complete record; a stitcher can always go back to it |
| 3 | **How the viewer gets one image** | **a view that points at the tiles**, copying nothing | copying costs 1.98× what the camera produced; stitching on the fly costs 647 ms a chunk against 4.6 |
| 4 | **Where analysis results go** | **inside the tile** — `labels`, `tables` | where ngio, napari and Fiji look; our viewer already finds them |
| 5 | **Where our own bookkeeping goes** | **beside the images**, never inside | a stray file inside makes zarr warn whoever opens it |
| 6 | **Plate layout for screening runs** | **no, on any instrument** | well and field become columns of the run table; one arrangement everywhere |
| 7 | **What ngio is for** | **reading, validating and analysing — not writing, for now.** See [`ome-zarr-plan-review.md`](ome-zarr-plan-review.md) | **Not today, rather than never** — permanent rejection would sit badly with this project's preference for ecosystem packages. What decides it now: ngio caps its bundles on the small levels, which are not byte-compatible with a view that forwards bytes (see B2), and it has never been qualified on a Windows microscope computer. Older reasons stand: it cannot resize an array, so a run must declare its whole extent up front; it cannot write the view; and it brings roughly sixty packages onto the microscope computer, where `zmart_storage` needs zarr and numpy. Speed is the smallest — about twice like for like, 2.39× for one 512-voxel plane and 1.45× for sixteen, not the 4.5–5.5× first quoted. |
| 8 | **Whether the overlap is trimmed from the pixels** | **no** — it is accounted for in the viewer and in the analysis | the overlap is the only evidence of where the stage really went |

---

## Decided once per microscope

| # | decision | how to answer |
| --- | --- | --- |
| 9 | **Does this instrument need 0.6?** | Only if it acquires something 0.5 cannot describe — a light-sheet deskew, or rotations between views. Confocal and widefield: no. |
| 10 | **Snappy viewing, or cheap imaging?** | Sets which chunk gets chosen; best is to align frame, chunk and overlap. A **2304 sensor takes chunk 192 at 16.7% overlap with nothing shaved off** — 144 chunks a tile-plane against 400 for chasing an exact 10%; a 4096 takes chunk 256 at 12.5%. (Chunk counts, not web requests: a bundled read also fetches the bundle's index, so true totals run slightly higher.) |
| 11 | **What overlap does this stage really need?** | Measure it rather than believe it. The tiles are kept whole, so a stitcher can report how far each really moved; offsets of a few voxels against a 204-voxel overlap mean you are paying ten times over. |

---

## Decided per run — only two

| # | decision | options |
| --- | --- | --- |
| 12 | **On a point scanner, what scan format?** | Where the format is settable, ask for one that aligns: **2880** gives chunk 288, 20% overlap and only 100 chunks a tile-plane; 3456 gives 16.7%; 4608 gives 12.5%. |
| 13 | **What kind of scan is this?** | `overview`, `targetscan`, … — it names the folder and separates acquisition types |
| 14 | **How much overlap?** | **none** (a survey you will never stitch, 1.0×) · **modest** (ordinary mosaics, ~1.3×) · **generous** (sparse specimens, light-sheet, ~1.6×) — each a multiple of the *unique specimen area*. |

Give an **intent**, never a percentage: `modest` is 10% on a 2048 or 2304 sensor
and 12.5% on a 1024 scan. A literal 10% in a workflow is impossible on a 1024
frame, and the run would be refused or silently written twice.

---

## Still to decide

| # | decision | the trade |
| --- | --- | --- |
| 15 | **Adopt chunk-aligned seams?** | Puts the join between two tiles exactly on a chunk edge, so the viewer *skips* the shared strip instead of the writer *cutting* it: the second copy goes, and the writer's **1.98×** (against what the camera produced) falls to about **1.3×** (the overlap's own cost against unique specimen area) — different denominators, not one scale. **Deletes nothing:** the tiles stay whole. Costs a slightly stricter overlap grid. **Recommended.** |
| 16 | **HTTP/2 for the viewer?** | Takes a screen fill from ~440 ms of round trips to ~26 ms, but browsers speak it only over TLS — a certificate on every microscope PC. **Take the bigger chunk first, since it is free, then measure.** |
| 17 | **When to adopt scenes (0.6, RFC-5)?** | They describe our workflow exactly and would make the view stop being ours, but Neuroglancer knows nothing of scenes and ngio cannot read 0.6 at all. **Wait for `ngio.NgffVersions` to gain `"0.6"`.** |
| 18 | **Widen the pyramid ladder, and average instead of stride?** | Measured: a 4× ladder costs 7.6% of the run against 36% for 2×, losing no cells; an 8× ladder costs 1.8%, but *striding* loses 37% of small cells where *averaging* keeps 98% — about 1.8 TB of smaller copies today against about 90 GB on five terabytes. Averaging tile by tile equals averaging the whole canvas **only where the tiles line up with the averaging blocks**: on every coarsened axis a tile's origin *and* the extent of ground it owns must be whole multiples of the deepest level's total shrink (8 for an 8× ladder), or the two differ by the seam's remainder. Reassuringly, striding needs the same alignment and `linked.py` already refuses placements that do not shrink cleanly, so averaging asks for no new rule — only that the existing one keeps being enforced. Costs: averaging is arithmetic rather than a copy, and a coarse voxel is no longer a real measurement. |
| 19 | **One file per position per level?** | Bundling taken to its end, small chunks still inside: roughly **110,000 files** on a 10,000-position run against **5,000,000** for one bundle per tile plane per level. But writing a plane at a time into a whole-position bundle measured **four times slower**, so it needs buffering, which costs memory and delays live viewing; and eight to sixteen planes per bundle runs into the view refusing any handed-over piece spanning more than one plane (`zmart_storage/linked.py:552-558`). §8.7 of [`zmart-ome-zarr-recipe.md`](zmart-ome-zarr-recipe.md) has the arithmetic. **Measure first; keep one tile plane per bundle meanwhile.** |
| 20 | **Fix the no-copy path for a drifting stage?** | It currently refuses runs whose tiles miss an exact grid, so an ordinary run falls back to copying. |

---

## The one thing that discards voxels

Everything above keeps every voxel the camera recorded, with one exception, not to
be confused with the chunk-aligned seam: **frame fitting.** To make a frame divide
into whole chunks, the writer may store 2300 columns of a 2304 sensor, and those
four columns are *never written* — 0.35% of the field, from the sensor's worst
edge, and what allows an overlap of exactly ten per cent rather than 12.5%. It is
capped at 1%, reported at setup, refused rather than exceeded, and **optional**:
forbid it and nothing is discarded, at the cost of 12.5% overlap on a 2048 sensor.

---

## What has to be built, in order

Decisions above are numbered **1–20**, the work below **B1–B11**.

> **Revised 7 August 2026 after review, and corrected again once a reviewer ran
> the code.** See [`ome-zarr-plan-review.md`](ome-zarr-plan-review.md). The
> refutation recorded here of B2's capping hazard was itself wrong, so B2 is
> re-qualified below and **the struck-out B3 comes back**, behind a TensorStore
> benchmark that may remove the need for it. Three of these are repairs: the
> arrangement does not do what this page says until they are done.

| | change | why |
| ---: | --- | --- |
| **B1** | **Per-dataset translation** on positions — **together with the matching change to the reader** | **repair.** Invalid against the official schema, so ngio refuses our tiles and `ngff-zarr` stacks them at the origin. Written on `claude/ngff-translation-per-dataset`. **The two halves must ship together**: `_where_the_view_begins` (`zmart_storage/linked.py:695-713`) adds the image-wide translation once and then *every* dataset's translation as well, so B1 alone would not double a position but multiply it by the number of levels — a true origin of (3, 5, 7) µm came back as **(9, 15, 21)** on a three-level pyramid, worse the deeper the pyramid goes. The reader's half is to combine the image-wide transform with **one** chosen dataset, normally the first, rather than walking every level. |
| **B2** | **Bundle every level**, not only the full-resolution one — but **not with the bundle capped at the level's own extent** while the view points at those levels | **repair, re-qualified.** Still required — the counts are above. But the capping hazard, recorded here as refuted, is **real**: a level holding 256×256 voxels wrote a capped bundle of **112,220 bytes** against **112,412** uncapped for the same pixels, and the 192-byte difference is the index — 16 inner chunks against 4 — which is checksummed, so forwarding capped bytes under the view's declared 512-voxel bundle **fails with a checksum error**. The old refutation asked whether a capped bundle's *pixels* decode when read on its own; they do, but the view never reads one on its own — it hands the bytes to the browser under its *own* declared shape. So **B2 must not be implemented as written while the view points at capped smaller levels.** Preferably: let the view advertise the small inner chunks and have the server, or TensorStore, hand back an inner chunk rather than a whole bundle file — the same fix the B2/B7 note below asks for, and the view goes on pointing at the positions' own smaller copies. Failing that: point it only at full resolution and let it write its own smaller copies, which works but gives up the very thing the view was built to avoid. |
| ~~B3~~ | ~~The server reads a bundle index~~ | **deleted — already built**, but only as far as a whole shard file: the pointer map is denominated in *shards*, so the browser reads the shard's index itself. B2 and B7 need one chunk from inside a bundle, so it comes back — see the note below. |
| **B3** | **Stop re-reading every tile the view has just written** | **repair, and new.** `_fill_this_tile_in` reopens and decompresses the array `positions.Run.write` was holding a moment earlier — five terabytes of pointless reading in the live path. Pass the array through instead, and shrink from the coarsest level that already exists. |
| B4 | **Two interop tests** — schema validation and an ngio open | how B1 would have been caught the day it appeared |
| B5 | **`plan_a_grid`** — frame + overlap intent → chunk, overlap, step | the workflow currently takes `piece=128` and hopes it suits the camera |
| B6 | **`tables/owned_ROI_table`** in every tile | makes the viewer's seam and the analysis filter one decision instead of two |
| B7 | **Chunk-aligned seams** | removes the second copy from every overlapping run. **Read the B2/B7 note below first.** |
| B8 | **Unique label numbers across a run** | else cell 7 in two neighbouring tiles becomes one object |
| ~~B9~~ | ~~A view for segmentations~~ | **deferred.** A second copy of the whole view mechanism, for labelled runs that do not exist yet. |
| B9 | **Delete `zmart-coverage`** | ~1,700 lines read only by a benchmark. The pointer map already holds each tile's origin and size, and the per-channel residue is one column of B10. Not free: `cropped.py` writes this record and is staying, so that writer changes too. |
| B10 | **A run-level table** | else a question about the run means opening ten thousand tables |
| B11 | **0.5 as the default in every writer** | both writers need it, because **`cropped.py` is staying** — though not for the reason recorded here. A small read does *not* drag the whole bundle off disk: a 10×10 read from an 855,499-byte bundle fetched 53,744 bytes, 6.28% — a small read's cost is set by the inner chunk, not the bundle. And `cropped.py` is a **writer**, not a rectangle reader. Two things keep it: it alone handles an acquisition whose **tiles overlap**, trimming half the shared strip from each meeting edge so the tiles butt together while keeping every tile whole in a separate archive for the stitcher, where `TileCanvases` refuses overlapping tiles outright since one voxel holds one value; and it writes a **portable OME-Zarr with real pixels in it**, which opens in napari or Fiji alone, where the view is meaningless without its pointer list and positions folder. Revisit once inner-chunk serving or TensorStore works. |

---

## B2 and B7 get in each other's way

As written today, **B2 takes B7 away.** B7 puts each tile's join with the next on
a chunk edge, but the rule for where a tile may sit
(`zmart_storage/linked.py:1435-1439`) reads the chunk shape ZMART recorded for the
store, and for a bundled store that shape is the **bundle**. So once B2 gives
every level one bundle per whole tile plane, a tile can only sit on multiples of a
whole tile — a grid that cannot express any overlap.

The way out is the struck-out **B3**: the server handing over one chunk from
inside a bundle rather than the whole file. Until it can, reading the bundle shape
is *correct* rather than a bug; once it can, the view side is **one line**:
`linked.py` already keeps the small chunk shape (`stored.inside_a_bundle`, line
477) and prefers it at lines 991 and 1107 — only the placement check does not.

**Benchmark TensorStore first; build the inner-chunk server only if it fails the
gate.** This project prefers an ecosystem package where it gives the same
result, and TensorStore's overlay driver may remove the need for that machinery —
one benchmark settles it. The gate: median read under 5 ms, 95th percentile under
10 ms, rebuild under 100 ms. A warm 10,000-position overlay measured **0.505 ms
median and 1.004 ms at the 95th percentile on Linux**, decoding and compression
included — comfortably clear, but that run tests neither a cold NTFS filesystem,
nor several readers filling a screen at once, nor positions arriving while the
viewer runs, so **the deciding run is on a Windows microscope computer.**

---

## Before any of it

**B1 and B2 come first**: nobody else's software can open the positions, and a run
past a terabyte leaves twenty million files. B2 waits on the TensorStore benchmark
above.

**And one fault found in passing, which belongs here because it silently spoils
data.** It is not in `zmart_storage/canvas.py`, which handles every channel
correctly at every level, checked with a two-channel run. It is in
`positions.Run.write`: it tells the view about a place only the first time it sees
that place, and the view then fills the coarse levels it writes for *itself* by
reading the position store at that instant, before the later channels exist. So at
those levels only whichever channel arrived first holds any picture: on a
two-channel run the second channel looks correct until you zoom far enough out,
then goes blank. The positions' own pyramids, `TileCanvases` and the batch path
are all fine.
