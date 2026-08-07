# ZMART's OME-Zarr: what to think about, and what never to think about again

Written 7 August 2026, at the end of a session that settled most of this.

**Looking for just the decisions?** [`ome-zarr-decisions.md`](ome-zarr-decisions.md)
is one page listing every choice that is genuinely yours, and nothing else. This
page is the next level down: the same ground with the reasoning attached.

| | |
| --- | --- |
| [`zmart-ome-zarr-recipe.md`](zmart-ome-zarr-recipe.md) | the exact arrangement — layout, metadata, chunking, overlap, and what changes in what order |
| [`ome-zarr-for-analysis-and-neuroglancer.md`](ome-zarr-for-analysis-and-neuroglancer.md) | the measurements — what other people's libraries do with our files, and what each choice cost or bought |

The purpose of this page is **to make the list of things you carry in your head
shorter**. Most of what follows is arranged by that: what the software should
settle on its own, what you decide once per instrument, and what remains open.

---

## The model, in one paragraph

A run writes **every tile whole, exactly as the camera recorded it**, each one an
ordinary OME-Zarr image that any software can open. Beside them sits a **view** —
also a real OME-Zarr image, but holding no pixels of its own; it points at the
tiles, so the viewer can be handed one image however many thousand tiles there
are. The overlap is never cut out of the tiles. It is *accounted for* twice over,
in different ways: the viewer is shown fewer chunks, and the analysis counts only
the objects a tile owns. Nothing is written twice, and the ground truth exists
once.

Everything below follows from that sentence.

---

## Never think about these again — the software settles them

These are all worked out at run setup from things the microscope and the operator
have already said. None of them should ever appear in a conversation, a notebook
cell or a driver.

| | how it is settled |
| --- | --- |
| **chunk size** | derived from the frame shape and the overlap intent, choosing the **largest** chunk that gives an acceptable overlap. A chunk need not be a power of two — 73 is as valid as 128. |
| **how many voxels to shave off the frame** | up to 1% may come off so the frame divides into whole chunks — the one place voxels are genuinely discarded; capped, reported, refused rather than exceeded, and switchable off. Not to be confused with the seam between tiles, which discards nothing. |
| **bundle (shard) size** | one tile plane, on any run large enough for file counts to matter. |
| **how many smaller copies** | as many as the tile can support before a level falls below one chunk. |
| **where the position is written** | `scale` then `translation`, beside each resolution, never at the multiscales level. |
| **the axes** | always five — `t, c, z, y, x` — used or not. |
| **file and folder naming** | `<name>_pos<NNNNN>.ome.zarr` inside the view's folder. |
| **whether a run is pointed at or copied** | decided at setup and reported; copying only when a format fits no chunk grid. |

The rule behind all of them: **rigid where a person chooses, derived where
arithmetic does better than a person.** Every one of these is arithmetic.

---

## Decide once per microscope, then forget

| question | how to answer it |
| --- | --- |
| **Does this instrument need OME-Zarr 0.6?** | Only if its acquisitions cannot be described in 0.5 — a light-sheet deskew (an affine shear), or rotations between views. A confocal or widefield mosaic never needs it. Everything else stays 0.5. |
| **Snappy viewing or cheap imaging?** | This sets which chunk is chosen. On a 2048 sensor: chunk 204 with a 20% overlap fills a screen in ~209 requests; chunk 128 with 12.5% takes 527. Pick the end you care about; the software does the rest. |
| **What overlap does this instrument actually need?** | Worth measuring once rather than believing. Every tile is kept whole, so a stitcher can report how far each tile really moved from where the stage said. If those offsets are a handful of voxels against a 204-voxel overlap, the run is paying for ten times what it needs. |

---

## Decide per run — and it is only two things

1. **What kind of scan is this?** — `overview`, `targetscan`. It names the folder
   and separates one acquisition type from another.
2. **How much overlap?** — as an intent, not a number:

| intent | for | costs |
| --- | --- | --- |
| **none** | a survey you will look at and pick targets from, never stitch | 1.00 × the imaging |
| **modest** | ordinary mosaics, specimen filling the field | ~1.3 × |
| **generous** | sparse specimens, light-sheet volumes, anything to be stitched properly | ~1.6 × |

The writer resolves the intent against the actual frame and reports the number it
arrived at — `modest` is 10% on a 2048 or 2304 sensor and 12.5% on a 1024 scan.
**Never write a percentage into a workflow**: a literal 10% is impossible on a
1024 frame, and the run would be refused or silently written twice.

---

## The analysis contract — four rules that do not change

1. **Point at the positions, never at the view.** The view holds no pixels and
   reads back as zeros everywhere. It is the one object in the whole arrangement
   that does not travel.
2. **Segment the whole tile, then keep only what it owns.** Run the segmentation
   over the entire tile, overlap included, so no cell is ever cut in half — then
   discard objects whose centre falls outside the tile's owned rectangle, which
   is recorded as `tables/owned_ROI_table`. Every object in the run is then
   counted exactly once. *Trimming applies to results, not to pixels.*
3. **Give every object a number unique across the whole run.** Otherwise cell 7 in
   one tile and cell 7 in its neighbour become the same object the moment a
   segmentation is drawn as one layer.
4. **Write results back inside the position** — `labels` for segmentations,
   `tables` for measurements — and append a row to the **run-level table** as
   well, with position, well and field as columns. Per-tile tables are right for
   writing; the run table is what anything actually queries.

`ngio` in the analysis environment only. It brings sixty packages; the acquisition
side needs `zarr` and `numpy` and should stay that way.

---

## Things that turned out not to be problems

Worth recording, because each cost a stretch of worrying:

- **Different microscopes having different frame sizes.** Nothing has to agree.
  The chunk is per-image metadata, derived per run. Every frame width from 512 to
  5000 was tried and all of them work.
- **Hamamatsu's "weird number".** It is 2304, which is 2⁸ × 9 — one of the
  friendliest numbers available.
- **Point scanners with arbitrary formats.** Handled by the same derivation, with
  a fallback to writing twice if a format fits nothing, announced at setup.
- **Whether the vendor writes the files.** We always write the OME-Zarr, so the
  chunk is always ours to choose — at acquisition, or at conversion.
- **Nesting positions inside the view's folder.** Purely organisational. ngio and
  multiview-stitcher open a nested position exactly as they would a loose one.
- **The plate layout.** Not used, on any instrument. Well and field are columns of
  the run-level table instead.

---

## What is genuinely blocking

1. **The per-dataset translation.** A position as written today is **invalid
   against the official OME-Zarr schema** — checked, not inferred. ngio refuses
   it; `ngff-zarr` silently places it at the origin, which means every tile of a
   run lands on top of every other. For light-sheet, where a stitcher is the only
   way to read the data at all, that is the difference between usable and not.
   The correction is already written on `claude/ngff-translation-per-dataset`.
2. **Reading a bundle index in the viewer's server.** Bundling is what makes a
   five-terabyte run copyable — 596,000 files instead of 153 million. But a
   bundled chunk is a byte range inside a file rather than a file, so the server
   must learn to read the index and seek. Until it does, bundling stays off and
   large light-sheet runs cannot be handled at all.

Everything else on this page can wait. These two cannot.

---

## Still open

- **Chunk-aligned seams**, which would remove the second copy from every
  overlapping run — the join between two tiles falls on a chunk edge, so the
  viewer skips the shared strip instead of the writer cutting it. Nothing is
  deleted; the tiles stay whole. Measured: the copying writer costs **1.98 ×** the
  camera's output even with *no* overlap, so five terabytes becomes nearly ten.
- **The no-copy path for a drifting stage.** It currently refuses runs whose tiles
  do not land on an exact grid, so an ordinary run falls back to copying.
- **HTTP/2 for the viewer**, which would take a screen fill from ~440 ms of round
  trips to ~26 ms — but browsers speak it only over TLS, so it means a certificate
  on every microscope computer. Take the larger chunk first, since that is free,
  and measure what remains before taking this on.
- **Scenes (OME-Zarr 0.6, RFC-5)**, which describe our exact workflow and would
  let the view stop being ours. Neuroglancer has no notion of a scene and ngio
  cannot read 0.6 at all, so the signal to revisit is `ngio.NgffVersions` gaining
  `"0.6"`.
- **Drawing measured on real hardware.** Every frame rate anyone has quoted here
  came from a machine with no graphics card.

---

## The one habit worth keeping

The fault in change 1 sat in the writer for months and no test of ours could see
it, because our reader and our writer shared the same misunderstanding and
cancelled it out. Twenty minutes with somebody else's library found it.

So: **keep two tests that judge our files by other people's rules** — validation
against the official schemas that ship with `ngff-zarr`, and opening every kind of
image we write with `ngio`. Interoperability is not achieved by intending it. It
is achieved by something that fails loudly on the day it stops being true.
