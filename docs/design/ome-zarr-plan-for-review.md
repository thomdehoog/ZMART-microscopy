# ZMART's OME-Zarr: a plan, and a request for a second opinion

Written 7 August 2026. **This document is self-contained on purpose** — it is
meant to be handed to somebody, or something, that has not seen the conversation
it came from. It sets out what the project is, what was measured, what was
decided and what is proposed; if you are reviewing it, the questions we most want
attacked are at the end.

---

## 1. What the project is

**ZMART** drives microscopes for *smart microscopy*: image a specimen broadly,
analyse what was seen while the specimen is still on the stage, and use the answer
to decide where to look next. The loop has to close in seconds, not overnight.

The instruments are a Leica Stellaris confocal (a point scanner, so the scan
format is whatever the operator sets), a mesoSPIM light-sheet, and a Molecular
Devices ImageXpress high-content screener. Everything runs on **one microscope
computer**, usually Windows. There is no cluster.

Three pieces of software:

| | |
| --- | --- |
| `zmart_storage` | writes runs to disk as OME-Zarr. Depends on `zarr` and `numpy` and nothing else. |
| `viz_studio` | the operator's viewer — a Python standard-library HTTP server and a browser page built on **Neuroglancer**. |
| `smart-analysis` | a separate repository: a queue plus a pipeline engine that runs each step in its own conda environment. |

Runs reach **five terabytes**. A run of **ten thousand positions** is a target,
not a hypothetical.

---

## 2. How a run is arranged on disk

```text
<experiment>/
  overview.ome.zarr/               a "view" — one image for the viewer
    zarr.json                      multiscales, omero, and our own `zmart` block
    0/ 1/ 2/ 3/                    declared levels; almost no pixels of its own
    positions/
      overview_pos00000.ome.zarr   a tile, whole, exactly as acquired
      overview_pos00001.ome.zarr
      ...
  zmart-coverage/                  ours — where the run has really imaged
```

**The positions hold every pixel.** Each is an ordinary OME-Zarr image with five
axes (`t, c, z, y, x`), its own pyramid, and its own place on the stage.

**The view is the unusual part.** It is a valid OME-Zarr image that stores almost
no pixels. A `zmart` attribute in its metadata says which chunk of the picture is
which chunk of which position, and the viewer's server forwards the position's
bytes untouched when Neuroglancer asks. Opened by anything else it reads as zeros.

**Why the view exists** is the one thing to understand before the rest makes
sense. Neuroglancer builds a rendering layer per source, and every layer takes
part in every frame. Measured on identical files, one run opened two ways:

| positions | view: first pixel | separate: first pixel | view: requests | separate: requests | separate: worst frame |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 3.04 s | 2.53 s | 101 | 197 | 17 ms |
| 200 | 2.14 s | 7.91 s | 115 | 647 | 17 ms |
| 600 | 2.19 s | 3.66 s | **120** | **1,547** | **733 ms** |

The view is flat; the alternative grows without limit. At fifty positions they are
equal — so a small run does not need it. It earns its place somewhere between two
hundred and six hundred.

On the run this was measured on, the view cost **6 files and 20 KB** with
2048-voxel tiles, because it points at the positions' own pyramid levels and only
computes the few coarsest ones that no single tile can supply. The pointer map
carries one line per position, so it grows with the run: at **ten thousand
positions it comes to roughly 1.2 MB** once the whitespace is stripped out, still
very small beside a multi-terabyte run.

*(All drawing numbers came from a software renderer with no graphics card. The
shapes carry; the absolute values do not.)*

---

## 3. What is broken

**A position is invalid against the official OME-Zarr schema.** It states its
place on the stage as a lone `translation` in the image-wide block, where the
format requires a list to begin with a `scale`. Verified against the schemas
shipped with `ngff-zarr`:

```
BROKEN position: INVALID against the official 0.4 image schema
FIXED  position: VALID
```

Two consequences, and the second is worse:

- **ngio refuses to open it** — loud, immediate.
- **`ngff-zarr` reads only the per-dataset transforms**, finds no translation, and
  places the image at the origin. So `multiview-stitcher`, which reads through it,
  puts **every tile of a run on top of every other**. Silent.

It survived because ZMART's own reader looks in the same wrong place its writer
wrote to. Writer and reader agreed perfectly.

**The fix is already written** on a branch: put the translation beside each
resolution, after the scale, and remove the image-wide one.

### More faults, found while this plan was being reviewed

**On a multi-channel run, the view's own coarsest levels keep only whichever
channel arrived first.** An earlier pass blamed the smaller-copy routine in
`zmart_storage/canvas.py`; that was checked and is wrong, since it handles every
channel at every level. The real defect sits in `positions.Run`, and touches only
the levels the *view* writes for itself — those too coarse for any single
position to supply. `positions.Run.write` tells the view about a place the first
time it sees it, and the view fills those levels by reading that position at that
instant, before the later channels exist on disk. Writing channel 1 first
reverses which one survives. The positions' own pyramids, `TileCanvases` and the
batch path that links finished tiles are all correct. At the microscope it looks
like this: on a two-channel run the second channel is right until you zoom far
enough out, and then goes blank.

**Build item B1 and the view's reader must be fixed in the same change.** B1
writes each position's place on the stage beside every pyramid level, which is
where the format requires it. But the view's reader, `_where_the_view_begins` in
`zmart_storage/linked.py:695-713`, adds the image-wide translation once and then
adds *every* dataset's translation as well. Built with a true origin of (3, 5, 7)
micrometres over three levels, it reads back (3, 5, 7) as things are written
today, **(9, 15, 21)** if B1 lands on its own, and four times the origin if both
places are filled. So the multiplier is the number of levels, not two: B1 alone
puts each position N times too far out, and the deeper the pyramid the worse it
gets. The repair is to combine the image-wide transform with **one** chosen
dataset, normally the first, rather than walking every level. Reader and writer
are one change, not two.

**A per-dataset translation is necessary but not sufficient.** In the same probe,
a channel declared without an explicit display window was still refused by the
validator, because the start and end brightness values it requires are missing;
given a window, the position opens. That is worth saying, since these documents
treat passing validation as the test that B1 is done.

---

## 4. What was decided

### Settled for the project

| | decision | why |
| --- | --- | --- |
| Format version | **0.5** | 0.4 cannot bundle chunks into files; a 5 TB run then means 153 million files |
| What holds the pixels | **the tiles, whole, overlap included** | the only complete record; the overlap is the only evidence of where the stage really went |
| How the viewer gets one image | **a view that points, copying nothing** | copying costs 1.98× the acquisition; stitching on the fly costs 647 ms a chunk against 4.6 |
| Analysis results | **inside the tile** — `labels`, `tables` | where ngio, napari and Fiji look |
| Our own bookkeeping | **beside the images, never inside** | a stray file inside makes zarr warn whoever opens it |
| HCS plate layout | **not used, on any instrument** | well and field become columns of a run-level table; one arrangement everywhere |
| The overlap | **never cut out of the pixels** | accounted for by the viewer and the analysis separately |

### A standing preference, which the ngio proposal is one instance of

> **Where a package from the ecosystem enforces the standard and gives the same
> result, use it instead of our own code.**

The fault in section 3 exists because we write the metadata by hand. A library
that writes it cannot make that mistake, and it keeps us honest as the format
moves. So the burden of proof runs the other way: our own code has to *earn* its
place by doing something no available package does — writing the view, appending
the pointer map, recording coverage, watching a run fill in — rather than merely
being there first.

**With one exception, and it must be measured rather than assumed.** If the
ecosystem's answer is too slow for the loop it sits in, that is sufficient reason
to keep our own, and we have one on record. `multiview-stitcher` presents a set
of tiles to a browser as one image without writing anything, which is
conceptually exactly right, and takes **647 milliseconds a chunk against 4.6 to
read the same piece from disk** — a hundred and forty times too slow to look
through a specimen.

So the rule has two clauses, and the second is a test, not an excuse:

> Use the ecosystem's package **unless it is measurably too slow for the loop it
> sits in.** Measure before deciding, and write the number down beside the
> decision.

Which made one thing a task rather than an opinion: **timing ngio's write path
against ours.** That has since been done, and the numbers are recorded in
[`ome-zarr-plan-review.md`](ome-zarr-plan-review.md). On matched pixel layouts an
independent benchmark measured ngio at **2.39× for a single 512-voxel plane and
1.45× for sixteen planes** — so roughly one and a half to two and a half times
our own path, with larger writes closer to parity. The absolute time a position
takes matters more than the ratio, because the only question that counts is
whether the microscope has to wait. On these numbers "not today" is well
supported; "never" is not.

**And it applies to the viewer as much as to the writer.** `viz_studio` is a
hand-written standard-library HTTP server and a hand-built Neuroglancer front end.
If something the community maintains would do the same job, that is preferable,
because standardisation is worth more here than owning the code. The capability
that must survive is the one section 2 measures: **one source over N tiles**, with
**live update while a run is still being acquired**. If nothing does that,
keeping our own is justified; if something does, ours should go.

**One candidate has now been measured, and the result is encouraging without
being conclusive.** Google's `tensorstore` library has an `overlay` driver, which
composes many separate stores into one virtual array — which is precisely what
the view does by hand. Reading through an overlay of **ten thousand positions**
served over local HTTP took a **median of 0.586 ms** per read, and an independent
reproduction on Linux measured the same warm ten-thousand-position overlay at
**0.505 ms at the median and 1.004 ms at the 95th percentile**, decoding and
compression included. Two people, close agreement, comfortably inside the gate
below.

The caveat deserves equal weight: both runs used a warm cache, a Linux
filesystem, hard-linked rather than separate physical files, and a single reader
asking for one thing at a time. Neither tested several readers filling a screen
at once, nor positions being replaced while the viewer runs. The microscope
computers this has to run on are **Windows machines with NTFS filesystems**,
where the cache is often cold. Until it is measured there, the number settles
nothing.

The acceptance gate is written down now, before the benchmark is run, so whoever
runs it knows what counts as a pass: a **median read under 5 ms**, a
**95th-percentile read under 10 ms**, and **rebuilding the overlay in under
100 ms** when a new position is added. That last one matters because during a
smart-microscopy run positions keep arriving, and the viewer must not stall every
time one does.

**That fixes the order of work: run the Windows benchmark first, and build the
custom inner-chunk server only if the overlay fails the gate.** Building our own
machinery first would go against the preference stated just above, since one
afternoon of measurement may remove the need for it altogether. Adopting the
overlay would take away most of the custom coordinate lookup, cropping and
alignment code. What would stay ours is the view's OME metadata, the placement
manifest, filling the empty ground where nothing has been imaged yet, encoding
for the web, and updating safely while a run is live. One capability would be
lost, and it is worth naming: TensorStore decodes and re-encodes every chunk, so
a position's compressed bytes could no longer be passed straight through. The
pixel values stay exact; the bytes themselves do not.

A reviewer should apply this to everything below, not only to ngio. If some part
of this arrangement duplicates what `ngio`, `ngff-zarr`, plain `zarr`, the
`neuroglancer` Python package or anything else already does correctly, that is
exactly the bloat we are asking to have found.

### Derived, never chosen by a person

The frame is given by the camera. From it and an overlap *intent* the writer
derives the chunk, the bundle size, the trim, the number of levels, and the exact
overlap — then reports what it picked.

```
frame (given) → chunk (largest that divides it, 128–288) → overlap (whatever that allows)
                bundle (one tile plane) absorbs the file-count problem separately
```

The operator chooses two things per run: what kind of scan it is, and an overlap
intent — **none**, **modest** or **generous**. Never a percentage, because a
literal 10% is impossible on a 1024 frame.

### Overlap, and who accounts for it

- **The viewer** hides it by pointing at fewer chunks — no pixels cut.
- **The analysis** segments the *whole* tile, so no cell is ever cut in half, then
  keeps only objects whose centre falls in the tile's owned rectangle, recorded as
  `tables/owned_ROI_table`. Each object counted exactly once.
- Both use **the same rectangle**, so a cell can never be shown on one tile and
  counted on another.

---

## 5. The plan

Nothing below is built, and **no production code has changed** — this document
records decisions and measurements, not work in progress. B1–B3 are repairs, and
the arrangement does not do what section 4 claims until they are done. As things
stand the writer still bundles only the full-resolution level, a 16-voxel crop
from a 128-voxel bundle is still refused, TensorStore is not integrated, the
pyramid still shrinks by taking every nth voxel, and the coverage, cropped and
linking modules are all still in place.

| | change | note |
| --- | --- | --- |
| **B1** | Per-dataset translation on positions | repair; already written on a branch, but it must land together with the view's reader — see section 3 |
| **B2** | Bundle every level, not only the full-resolution one | repair, but **it must not be implemented as written** while the view points at capped smaller levels — see below; 2 TB is about 20.5 M files today and about 1.19 M with every level bundled |
| **B3** | The viewer's server reads a bundle index | repair; a bundled chunk is a byte range, not a file |
| B4 | Two interop tests — schema validation, and opening with ngio | how B1 would have been caught the day it appeared |
| B5 | `plan_a_grid` — frame + intent → chunk, overlap, step | the workflow takes `piece=128` today and hopes |
| B6 | `tables/owned_ROI_table` in every tile | |
| B7 | Chunk-aligned seams | removes the second copy from every overlapping run |
| B8 | Unique label numbers across a run | else cell 7 in two tiles becomes one object |
| B9 | A view for segmentations | else a labelled run meets the cliff the view avoids |
| B10 | A run-level table | else a question about a run means opening 10,000 tables |
| B11 | 0.5 as the default in every writer | one writer already does; two do not |

**How B2's file counts actually work, because they are easy to get wrong.**
Bundling does not merge one pyramid level into another: every level of every
position still needs its own bundle file for each plane, so bundling the whole
pyramid *multiplies* the level-0 count by the number of levels. On a
two-terabyte run with five levels that is **238,419** bundled files at full
resolution plus **20,265,615** loose ones in the pyramid above, since every tile
plane leaves 64 + 16 + 4 + 1 chunk files across levels 1 to 4 — about
**20.50 million** all told, against **about 1.19 million** once every level is
bundled. A seventeen-fold reduction, and clearly worth doing.

**But B2 must not be implemented as written while the view points at capped
smaller levels.** A bundle capped to a small level's own extent is not
interchangeable with a full-sized one. Measured: a level 1 holding 256×256
voxels, capped to 256×256, came to **112,220 bytes** against **112,412** for an
uncapped bundle of exactly the same pixels. The 192-byte difference is the
bundle's own index — a 512-voxel bundle lists 4 × 4 = 16 inner chunks at 16 bytes
each, a capped 256-voxel one lists 2 × 2 = 4 — and that index carries a checksum,
so handing capped bytes to a reader expecting the uncapped shape fails outright.
There are two ways out, and they are not equal.

- **Preferred: have the view advertise the small inner chunks, and let the server
  (or TensorStore) return an inner chunk rather than a whole bundle file.** This
  closes the hazard and keeps the property the whole design exists for — the view
  goes on pointing at the positions' own smaller copies and never builds a
  pyramid of its own. It also sets the price: one pointed smaller level needs
  origins and owned extents aligned to chunk × 8, and three pointed levels to
  chunk × 64. Handing over whole 2048-voxel tile planes instead would need
  16,384-voxel alignment even for the first smaller level, which is why the
  bundle and the pointing unit cannot both be the whole plane.
- **Fallback: point only at the full-resolution level and let the view write its
  own smaller copies.** This certainly works, and it surrenders exactly what the
  view was designed to avoid.

### The proposal on top: let ngio write the positions

`ngio` (BioVisionCenter) is a strict OME-Zarr library. A position was written
entirely through it at 0.5, with the chunk, bundle, ladder, levels, translation
and version all specified, and put in front of the four readers a position must
satisfy:

```
official 0.5 image schema : VALID
ngio                      : opens; axes (t,c,z,y,x), pixel size (2.0, 0.35, 0.35)
   level 0: ['scale', 'translation']      ← the fault, gone by construction
ZMART's viewer reader     : accepts it
chunk layout for pointing : codecs ['sharding_indexed'], one file per level
```

It settles **B1, B2, B6 and B11** — two of the three repairs — because the API
takes a `translation` and bundles every level, capping the small ones itself.
That capping is the very thing the paragraph above warns about, so it would have
to be paired with inner-chunk serving.

**It does not settle B3, and makes it urgent**: ngio bundles by default, so the
server must read a bundle index from the first run written this way.

**The line it draws:** the *position* is ngio's; the *run* is ours. No library
will ever write the view, the pointer map or the coverage record, and none should.

**Its costs:** 61 packages on the microscope computer where two suffice today;
no `resize`, so runs must declare generously and fill in — which is already what
`zmart_storage` does, and for a position only the time axis is over-declared.

---

## 6. Where a second opinion is most wanted

**Before the specific questions, the general one, and it matters more than any of
them:**

> **What here is bloat?** What is over-engineered, what could be done far more
> simply, and what could be deleted outright — *without losing capability*? We
> would rather have a smaller arrangement that does the same work than a clever
> one. If a decision below buys less than it costs, say so plainly. If two
> mechanisms do one job, say which to keep. If something exists only because it
> was interesting to build, it should go.

Some candidates we already suspect, offered so they can be confirmed or dismissed:

- The **coverage record** — a second bookkeeping mechanism beside the pointer map.
  Could declared geometry replace it? `multiview-stitcher` bounds work from the
  stores' own extents and needs no such record. Only in part, on review: it also
  holds the moment, the channel, the write order, repeated visits to one place
  and whether a leg was abandoned, so it can go only once an append-only run
  event manifest exists.
- **Two writers** — `canvas.py` copies, `linked.py`/`positions.py` points. If
  chunk-aligned seams (B7) make pointing work for overlapping runs too, does the
  copying writer still need to exist for anything but foreign data?
- **The `zmart` pointer map** — is a per-chunk map necessary, or could the same
  answer be computed from each tile's declared origin and shape, which every tile
  already states?
- **Declaring an enormous canvas up front** — the stage's whole travel range,
  mostly empty. Necessary, or an artefact of wanting one array?
- **Five axes always**, even when a run has one moment and one colour.

Then the specific places we are least confident, in rough order.

1. **Is the view the right answer at all, or a workaround that will age badly?**
   It exists because Neuroglancer builds a layer per source. It is the one part
   of the arrangement that is not standard OME-Zarr. RFC-5 "scenes" in version 0.6
   describe our workflow almost word for word — but Neuroglancer has no notion of
   a scene (checked: the word does not appear in its zarr reader) and ngio cannot
   read 0.6 at all. Is waiting right, or is there a better structure now?

2. **A view served entirely from memory.** We deleted the view folder, answered
   for it from a small HTTP server, and an ordinary zarr client read every tile
   back correctly. Only the pointed level was tested. Is a synthesised view a
   better idea than a written one, and what breaks at ten thousand positions?

3. **The pyramid.** It costs 36% of a run at a halving ladder. A quartering ladder
   costs 7.6% and loses nothing; an eighth costs 1.8% but *striding* loses 37% of
   small cells while *averaging* keeps 98%. Averaging within a tile equals
   averaging the whole canvas, but only where the tile's origin and owned extent
   are whole multiples of the total shrink of the deepest level built tile by
   tile — 512 for three levels of an eighth-sized ladder, not the 8 an earlier
   pass recorded. A seam at voxel 1,632 is out by 32.0 at level 2 and 96.0 at
   level 3, and the existing guard does not catch it, since it checks only the
   levels the view points at. So the stated reason for striding ("averaging would
   mix voxels across the join between two positions") holds only off that grid,
   and the phase check has to stay. Is that reasoning right? Would you take an
   eighth-sized averaged ladder — **about 90 GB** instead of 1.8 TB on five
   terabytes? That is the measured 1.8% applied to five terabytes; the arithmetic
   alone gives a little under 79 GB, the gap being compression bookkeeping and
   bundle indexes.

4. **Adopting ngio on the acquisition machine.** Sixty-one packages, on a Windows
   microscope PC, in the path of a live experiment. Is the standards-compliance
   worth it, or is validating our own output (`ngff_zarr.validate`, a few
   milliseconds per position, dev dependency only) the better trade?

5. **Bundling and buffering.** Writing 32 planes one at a time into plane-sized
   bundles took 565 ms; into one whole-tile bundle, 2,290 ms — four times slower,
   because each plane rewrites more of the bundle. Buffering a whole tile before
   writing would fix it but delays live viewing and costs ~800 MB per tile in
   flight. Where would you put that dial?

6. **The overlap ownership rule.** Segment the whole tile, keep objects whose
   centre lands in the owned rectangle. It fails for objects larger than the
   overlap, which can be clipped in every tile. We plan to flag border-touching
   objects. Is there a better rule that does not require stitching first?

7. **Anything we have not thought to ask.** The arrangement has been developed
   against one viewer and one analysis library. What breaks when somebody else
   opens it?

---

## 7. What is measured, what is calculated, and what is assumed

Worth separating, since the plan leans on all three.

**Measured here:** the schema violation; ngio and ZMART's reader both accepting an
ngio-written position; view against N sources at 50/200/600 positions; the copying
writer at 1.98×; ladder cost and cell survival at 2×, 4× and 8×; averaging within
a tile equalling averaging the canvas where the placements line up, and the errors
at a seam of 1,632 where they do not; bundle write speed; a view served from memory; every frame width from 512 to 5000 having a workable chunk; a TensorStore
overlay of ten thousand positions read over local HTTP at a median of 0.586 ms,
reproduced independently at 0.505 ms; the capped and uncapped bundles at 112,220
against 112,412 bytes; the byte ranges a small read really asks for; the
translation multiplier reading back as (9, 15, 21) over three levels.

**Two figures whose basis has to be stated, or they will be compared wrongly.**
The 1.98× above is measured against what the camera produced, while the 1.3×
quoted for chunk-aligned seams is the cost of overlap against unique specimen
area — the two do not divide by the same thing. And the 144, 400 and 100
"requests" a tile-plane quoted elsewhere are counts of chunks rather than of
complete web requests, since bundled reading also asks for the bundle's index,
usually cached after the first. The arithmetic is right; the true request totals
are a little higher.

**The existing tests pass, and that is less reassuring than it sounds.** There
are 148 in the storage suite, and 105 passed with 1 skipped across the storage,
server and linking suites together, the skip being a rendering test that needs a
real browser and a built front end. But they describe the whole-bundle design as
it stands. Nothing yet covers a capped small level against an uncapped one,
validation of a position whose channel has no display window, or a per-dataset
translation across several levels — which is exactly why targeted probes found
all three faults.

**Calculated, not measured: the file counts at 2 and 5 TB.** They are arithmetic
done on paper, and an earlier version of this document had them wrong by a factor
of sixty-five — which is not a mistake a measurement could have made.

**Assumed, not measured:** that a real graphics card does not change the shape of
the drawing results; that HTTP/2 would help as much as the round-trip arithmetic
suggests; that a synthesised view scales to ten thousand positions; that
buffer-then-write recovers the 4×; that ngio's dependencies install cleanly on the
microscope PC; that the TensorStore overlay timing survives a Windows NTFS
machine with a cold cache and several readers at once.
