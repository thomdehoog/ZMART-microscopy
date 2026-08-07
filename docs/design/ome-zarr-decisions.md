# The decisions: writing OME-Zarr for smart microscopy

One page. Every decision that is genuinely yours to make, what was chosen, and
what it affects. Everything not listed here — chunk size, frame trim, bundle size,
the axes, naming, whether a run is pointed at or copied — follows from the frame
shape and the overlap intent. **Rigid where a person chooses, derived where
arithmetic does better than a person.**

**No production code has changed yet** — this page is a plan: the writer still
bundles only level 0, the smaller copies still take every nth voxel and never
shrink the depth, and the view, coverage and `cropped.py` are all still there.

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
| 18 | **How much each smaller copy shrinks** | **by half, always** | halving is what the ecosystem assumes — ngio, ngff-zarr, napari and Fiji all default to it. Quarter- and eighth-step ladders are legal OME-Zarr and much cheaper, 7.6% and 1.8% of the run against **36%**, but interoperability is the whole reason this project chose the format, and disk is not worth being the odd file out for. So the cost is taken: the pyramid adds about a third again to a run, and a 4096-voxel tile gets six levels where quartering needed three. Taking every nth voxel rather than averaging stays too, since at halving it loses no cells. Which axes halve, and from where, is **B12**. |

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
| 17 | **When to adopt scenes (0.6, RFC-5)?** | They describe our workflow exactly and would let the view stop being ours. **Neuroglancer already reads 0.6** — its supported set is `0.4, 0.5-dev, 0.5, 0.6.dev1, 0.6.dev3, 0.6` — so the version was never what stood in the way. What stands in the way is that its reader takes **one image per group**: `parseOmeMetadata` returns on the first entry of `multiscales` it can parse, and there is no handling of plates, wells or collections anywhere in the driver. A group naming ten images therefore draws the first and **silently ignores the other nine** — no error, no warning, which is worse than a refusal because it looks as though it worked. Nor is there a way round it in metadata: the per-resolution transformations that look like the place to put ten positions describe *zoom levels of one picture*, and using them for tiles would claim the ten are ten shrinkings of the same field. **So wait for Neuroglancer to honour more than the first image, and for `ngio.NgffVersions` to gain `"0.6"` — the format is ready and the readers are not.** |
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

Decisions above are numbered **1–20**, the work below **B1–B12**.

> **Revised 7 August 2026, and corrected again each time a reviewer ran the
> code.** See [`ome-zarr-plan-review.md`](ome-zarr-plan-review.md). Four of these
> are repairs: the arrangement does not do what this page says until they are done.

| | change | why |
| ---: | --- | --- |
| **B1** | **Per-dataset translation** on positions — **together with the matching change to the reader** | **repair.** Invalid against the official schema, so ngio refuses our tiles and `ngff-zarr` stacks them at the origin. Written on `claude/ngff-translation-per-dataset`. **The two halves must ship together**, because our reader adds the image-wide translation and then every dataset's as well, so the writer's fix arriving alone would multiply each position's offset by the number of levels. |
| **B2** | **Bundle every level**, not only the full-resolution one — but **not with the bundle capped at the level's own extent** while the view points at those levels | **repair, re-qualified.** Still required — the counts are above. But the capping hazard, recorded here as refuted, is **real**: a capped bundle and an uncapped one holding the same pixels are different files, because they index a different number of inner chunks and that index is checksummed, so a browser handed capped bytes under the view's declared shape rejects them (the checklist has the byte counts). So **B2 must not be built as written while the view points at capped smaller levels.** Preferably, let the view advertise the small inner chunks and have the server, or TensorStore, hand back one inner chunk rather than a whole file; failing that, point the view at full resolution alone and let it write its own smaller copies, giving up the very thing it was built to avoid. |
| ~~B3~~ | ~~The server reads a bundle index~~ | **deleted — already built**, but only as far as a whole shard file, which the browser then indexes itself. B2 and B7 need one chunk from *inside* a bundle, so it comes back. |
| **B3** | **Refresh the view's own coarse levels on every write, for the channel being written** — and stop re-reading the tile the writer is still holding | **repair, and blocking.** `positions.Run.write` tells the view about a place only the first time it sees that place, and the view then fills the coarse levels it writes for *itself* by reading the position store at that instant, before the run's later channels exist. Reproduced both ways round: whichever channel is written first is the only one with a picture when the operator zooms out, and the checklist has the numbers. The repair is to update the current moment-and-channel's view levels on **every** write, while still adding the position's pointer the first time only. Handing that update the image already in memory also stops `_fill_this_tile_in` re-reading the array the writer was holding a moment earlier, five terabytes of pointless reading in the live path. `canvas.py`, the positions' own copies and the batch path are all correct on this point; what they do with the depth is B12. |
| B4 | **Two interop tests** — schema validation and an ngio open | how B1 would have been caught the day it appeared |
| B5 | **`plan_a_grid`** — frame + overlap intent → chunk, overlap, step | the workflow currently takes `piece=128` and hopes it suits the camera |
| B6 | **`tables/owned_ROI_table`** in every tile | makes the viewer's seam and the analysis filter one decision instead of two |
| B7 | **Chunk-aligned seams** | removes the second copy from every overlapping run. **Read the note below first.** |
| B8 | **Unique label numbers across a run** | else cell 7 in two neighbouring tiles becomes one object |
| ~~B9~~ | ~~A view for segmentations~~ | **deferred.** A second copy of the whole view mechanism, for labelled runs that do not exist yet. |
| B9 | **Delete `zmart-coverage`, but only once something else records what it records** | ~1,700 lines read by nothing but a benchmark, so removing it looks nearly free — and it is not. Beyond each tile's origin and size, which the pointer map holds, the record keeps the moment in time and the channel, the order things were written in, the exact origin and shape, the scan's own numbering of its tiles, repeated visits to one place, and whether a leg of the run finished or was abandoned. No column of B10's table replaces any of that, so the deletion is safe **after** an append-only record of run events takes those duties over, and not before. `cropped.py` writes this record and is staying, so that writer changes too. |
| B10 | **A run-level table** | else a question about the run means opening ten thousand tables |
| B11 | **0.5 as the default in every writer** | both writers need it, because **`cropped.py` is staying** — though not for either reason recorded here before. It is a writer, not a rectangle reader, and not the only path that can represent overlap: a no-copy view of two 128-voxel tiles acquired 96 voxels apart, cropped 16 voxels at the shared seam, was built and read back through `linked.py`'s existing `taken_from` and `size` fields, so the view holds an overlapping run wherever the tiles are aligned. What keeps `cropped.py` is being the only **turnkey writer** for one: in a single pass it trims half the shared strip from each meeting edge so the tiles butt together, keeps every original tile whole in a separate archive for the stitcher, and leaves a **portable OME-Zarr with real pixels in it** that opens in napari or Fiji alone, where the view is meaningless without its positions folder. (`TileCanvases` still refuses overlapping tiles outright, since one voxel holds one value.) Revisit once inner-chunk serving or TensorStore works. |
| **B12** | **Halve the depth too, once a voxel is as wide as the planes are far apart** | **repair, and blocking, but not self-contained.** Every smaller copy divides only height and width, so on a real 75 GB stack with 3.40 µm between planes the coarsest level comes out 144 × 147 voxels with all **833** planes — a voxel eight times deeper than it is wide. Little disk is wasted, but a zoomed-out view fetches eight times the planes it needs for the same picture, a three-dimensional view of that level stands eight times too tall, and anything measured there is measuring a voxel that is not cubic, with nothing to warn of it. Light-sheet and confocal stacks feel it most, and they are most of what this project acquires. Halving the depth once the voxel turns cubic is ordinary practice, and what real files do. **Check first** — the view addresses a position's planes directly and refuses any piece spanning more than one plane, so it must shrink the depth in step from there; nobody has looked at what that takes. |

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

**The alignment rule from 18 is simple again.** A tile's origin and the ground it
owns must be multiples of the chunk doubled once per smaller level the view points
at — 1,632 voxels for a 2048-voxel tile at chunk 204, which is what `linked.py`
already enforces. A bundle-sized placement grid would inflate that to
16,384.

> **How deep a view can point, worked out and then measured.** That rule has a
> consequence nobody had drawn out, and it decides the arrangement on its own:
>
> **the deepest level a view can point at is 1 + log₂( gcd(step, tile) ÷ chunk ).**
>
> On the Hamamatsu at the overlap chosen here — a 2,304-voxel tile, a step of
> 2,016 — that greatest common divisor is 288, which is exactly the overlap. So a
> chunk of 288 buys **one** pointed level; 144 buys two; 72 buys three; and 36
> points at all four and writes nothing at all, at about sixty times the files.
>
> **So the chunk chosen here leaves no choice: the view writes its own smaller
> copies.** That was already the decision, taken to avoid handing on the bytes of
> a capped bundle — and it turns out the geometry forces it anyway. Two unrelated
> routes to the same answer, which is the most confidence anything here has had.
>
> Checked rather than reasoned: nine overlapping positions at that geometry, each
> giving up the shared chunk, came back with **all 484 pieces of the picture
> answered by exactly one tile, none by two, none by none**, the smaller copies
> exact, and every voxel still on disk in the positions.
>
> **And it holds at survey size.** Ten thousand overlapping tiles, ownership worked
> out for every one of them, open in **0.53 seconds** — against 0.21 for four
> hundred, so twenty-five times the tiles for two and a half times the wait. Not a
> piece of the picture was left with nothing behind it, and not one was owned
> twice. All of the growth is the one document that lists the tiles, which went
> from 0.09 MB to 2.19; reading it takes 14 milliseconds and finding a tile in it
> takes none, because it is indexed by row rather than searched. This was run under
> the same restriction the sensor above imposes — one pointed level, everything
> coarser written — so it is the constrained case rather than a flattering one.
>
> **The law sets three things, not one.** How deep the view can point; how much of
> the picture it must therefore write for itself; and, because what it writes grows
> with the ground covered rather than the number of tiles, how a long survey
> behaves. Measured: 0.7 MB written at a hundred positions, 3.4 MB at four hundred,
> so tens of megabytes on a survey — written while the microscope is running. The
> chunk that buys pointing depth is the same chunk that buys this back, and at a
> frame divided by eight you are at the end of the dial in both directions.
>
> Two small things are missing before a run can do this, both in the writer and
> neither in the idea. There is **no way to say "point at one level and write the
> rest"** — how far a view points is the smaller of the view's levels and the
> positions' own, so the only lever is to give the positions no pyramid. And
> **`Run.write` cannot state a seam**: it hands the view a place and never the
> ground the tile owns, though `PlacedTile` and the view beneath it both take it.

**Benchmark TensorStore first; build the inner-chunk server only if it fails the
gate.** Its overlay driver may remove the need for that machinery, which is what
this project prefers. A warm overlay of ten thousand positions already clears the
gate on Linux, but says nothing about a cold Windows filesystem or several readers
filling a screen at once, so **the deciding run is on a microscope computer.** The
checklist has the gate and the timings.

> **Time the opening, not only the drawing.** The gate above is written in frame
> times, and frame times turn out to be the forgiving half of the question.
> Measured on both a software renderer and a real graphics card, at four hundred
> separate sources: drawing came down from 121.7 ms a frame to 2.4 ms once the
> card did the work, about fifty times better — while **the wait before anything
> appears did not improve at all**, staying at roughly three and a half seconds.
> Opening and fetching are not the card's work; they are setting up each source
> and reading from disk, and a faster machine does not help.
>
> Worse, that wait grows faster than the run does. Doubling the positions
> multiplied it by nearly four and then by more than five, so it is at least
> squaring while the frame time merely doubles. An arrangement can therefore look
> perfectly smooth once it is up and still take minutes to show anything.
>
> This is what makes the arrangement chosen here the right one, and for a better
> reason than speed of drawing: **one picture opens in about a fifth of a second
> whatever it is made of** — flat from five positions to four hundred — because
> the viewer is handed one thing to set up rather than one per position. Any
> future gate, TensorStore's included, should say how long an operator waits
> before seeing anything, not only how smoothly it moves afterwards.
>
> **And the cost is not the reading.** A recording of the viewer at work names
> the growing part exactly: as each store is handed over, the viewer binds it into
> the space all the stores share, and every bind walks every store bound before
> it. Three of those per store, each one telling every store already there to
> rebuild itself. So the work per store *doubles when the number of stores
> doubles* — measured at 2.65, 4.48 and 9.36 milliseconds a store for one, two and
> four hundred of them. Reading the descriptions, by contrast, stays flat at about
> four requests and a third of a millisecond a store at every size.
>
> Two things follow, and both are worth having. **Declaring everything once would
> not help** — it removes reading, and reading is the part that already scales.
> And the repair is small and precisely placed: bind all the stores and combine
> once, rather than combining after each. That is somebody else's code to change,
> but it is one loop, and it is the difference between growing with the square of
> the run and growing with the run.

---

## Before any of it

**B1, B2 and B3 come first.** Nobody else's software can open the positions; a run
past a terabyte leaves twenty million files; and a two-channel run written today
looks correct until the operator zooms out and one channel goes blank, which is a
bad way to discover a fault in the middle of an experiment. B2 waits on the
benchmark above, and B12 belongs with them once its check has been done.
