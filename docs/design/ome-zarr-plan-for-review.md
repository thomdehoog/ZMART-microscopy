# ZMART's OME-Zarr: a plan, and a request for a second opinion

Written 7 August 2026. **This document is self-contained on purpose** — it is
meant to be handed to somebody, or something, that has not seen the conversation
it came from. It sets out what the project is, what was measured, what was
decided, what is proposed, and where a second opinion would be most valuable.

If you are reviewing it, the questions we most want attacked are at the end.

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

The view costs **6 files and 20 KB** with 2048-voxel tiles, because it points at
the positions' own pyramid levels and only computes the few coarsest ones that no
single tile can supply.

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

Nothing below is built. **B1–B3 are repairs; the arrangement does not do what
section 4 claims until they are done.**

| | change | note |
| --- | --- | --- |
| **B1** | Per-dataset translation on positions | repair; already written on a branch |
| **B2** | Bundle every level, not only the full-resolution one | repair; 2 TB is 20.6 M files today, 318 k done right |
| **B3** | The viewer's server reads a bundle index | repair; a bundled chunk is a byte range, not a file |
| B4 | Two interop tests — schema validation, and opening with ngio | how B1 would have been caught the day it appeared |
| B5 | `plan_a_grid` — frame + intent → chunk, overlap, step | the workflow takes `piece=128` today and hopes |
| B6 | `tables/owned_ROI_table` in every tile | |
| B7 | Chunk-aligned seams | removes the second copy from every overlapping run |
| B8 | Unique label numbers across a run | else cell 7 in two tiles becomes one object |
| B9 | A view for segmentations | else a labelled run meets the cliff the view avoids |
| B10 | A run-level table | else a question about a run means opening 10,000 tables |
| B11 | 0.5 as the default in every writer | one writer already does; two do not |

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
  stores' own extents and needs no such record.
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
   small cells while *averaging* keeps 98%. We also showed averaging within a tile
   is bit-for-bit averaging the whole canvas, so the stated reason for striding
   ("averaging would mix voxels across the join between two positions") appears not
   to hold. Is that reasoning right? Would you take an eighth-sized averaged
   ladder — 90 GB instead of 1.7 TB on five terabytes?

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

## 7. What is measured, and what is assumed

Worth separating, since the plan leans on both.

**Measured here:** the schema violation; ngio and ZMART's reader both accepting an
ngio-written position; view against N sources at 50/200/600 positions; file counts
at 2 and 5 TB; the copying writer at 1.98×; ladder cost and cell survival at 2×,
4× and 8×; averaging within a tile equalling averaging the canvas; bundle write
speed; a view served from memory; every frame width from 512 to 5000 having a
workable chunk.

**Assumed, not measured:** that a real graphics card does not change the shape of
the drawing results; that HTTP/2 would help as much as the round-trip arithmetic
suggests; that a synthesised view scales to ten thousand positions; that
buffer-then-write recovers the 4×; that ngio's dependencies install cleanly on the
microscope PC.
