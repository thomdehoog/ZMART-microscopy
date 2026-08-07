# Building ZMART's OME-Zarrs: the summary and the checklist

Written 7 August 2026. This is the front door. It summarises what was decided and
lists what has to be thought about when writing a run that must be both **viewed**
in the operator's viewer and **analysed** by the pipelines.

Two longer documents sit behind it and should be read when a decision here needs
its reasoning:

| | |
| --- | --- |
| [`zmart-ome-zarr-recipe.md`](zmart-ome-zarr-recipe.md) | the exact arrangement — layout, metadata, chunking, overlap, what changes and in what order |
| [`ome-zarr-for-analysis-and-neuroglancer.md`](ome-zarr-for-analysis-and-neuroglancer.md) | the measurements — what other libraries do with our files, and what each choice cost or bought |

---

## In one paragraph

A run writes **every tile whole, exactly as the camera recorded it**, as an
ordinary OME-Zarr image that any software can open. Beside those sits a **view** —
a complete OME-Zarr image that holds no pixels of its own and instead points at
the tiles, so the viewer is handed one image however many thousand tiles there
are. Overlap is never removed from the tiles; it is *accounted for* separately by
the viewer, which is shown fewer chunks, and by the analysis, which counts only
the objects a tile owns. Nothing is copied twice, and the ground truth is written
once and only once.

---

## The decisions, settled

| | decided |
| --- | --- |
| **format version** | 0.5 by default. 0.6 only where 0.5 cannot state the truth — a deskew, a rotation between views. 0.4 on request. **0.5 is required for light-sheet**, because 0.4 cannot bundle files. |
| **where the pixels live** | in the positions. The view holds none. Point analysis at the positions, never at the view. |
| **where an image says it sits** | `scale` then `translation`, beside **each** resolution, never also at the multiscales level. The translation is the corner of voxel zero. |
| **axes** | always five — `t, c, z, y, x` — whether or not the run used them. |
| **smaller copies** | every second voxel in y and x; nothing averaged; z never reduced. |
| **analysis results** | `labels` and `tables` **inside** the image. Our own bookkeeping (`zmart-coverage`, the lock) **beside** it. |
| **plate layout** | **not used, on any instrument.** Well and field are columns of the run-level table instead. |
| **overlap** | three named intents — **none / modest / generous** — resolved to real percentages per frame at setup. Never a hard-coded number. |
| **chunk** | derived at setup from the frame shape and the chosen intent. Never chosen by hand, never changed afterwards. |
| **bundling (sharding)** | one tile plane per bundle on any run large enough to matter. |
| **tile position** | given as the **centre** (which is what the stage knows), stored as the **corner** (which is what the format means). |
| **a tile that moves over time** | a new **image**, not a new index along the time axis. |
| **ngio** | read with it, check our files with it, analyse with it. **Never write our format through it.** |

---

## The checklist

### A — Before the run starts

- [ ] **Ask the driver for the frame shape.** Everything else depends on it and it
      must be known before the first tile.
- [ ] **Resolve the overlap intent against that frame**, and show the operator the
      number it came to. `modest` is 10% on a 2048 or 2304 sensor and 12.5% on a
      1024 scan — the intent is fixed, the number is not.
- [ ] **Derive the chunk** from the frame and the intent. A chunk need not be a
      power of two; 73 is as valid as 128.
- [ ] **Report any trim.** If a few voxels come off the frame to make it fit, say
      so in voxels and per cent. Cap it at 1% and refuse rather than exceed.
- [ ] **Decide the bundle size** — one tile plane for anything large. Below about
      a terabyte it hardly matters; above it, it decides whether the run can be
      copied at all.
- [ ] **Warn if the run will be written twice.** A format that fits no chunk falls
      back to copying. The operator should hear that now, not after five
      terabytes.
- [ ] **Fix the format for the whole acquisition type.** Different acquisition
      types may differ freely; positions within one may not.

### B — While writing

- [ ] **Write every tile whole**, overlap included. The overlap is the only
      evidence of where the stage really went.
- [ ] **Never write a voxel twice.** If an arrangement needs a second copy, that
      is a bug to fix rather than disk to buy.
- [ ] **Write the position beside each resolution**, scale first.
- [ ] **Record the owned rectangle** as `tables/owned_ROI_table` in every tile.
- [ ] **Keep the coverage record** — a canvas declares far more room than any run
      fills, and unwritten ground reads back identical to genuinely dark specimen.
- [ ] **Leave unwritten chunks unwritten.** Empty room must cost nothing.

### C — For viewing

- [ ] **Hand the viewer one image.** Neuroglancer builds a drawing layer per
      source: a thousand positions drew 24 frames in five seconds where one image
      managed 255.
- [ ] **Hide the overlap by pointing at fewer chunks**, not by cutting pixels.
- [ ] **Consider writing two views** — trimmed for looking at, untrimmed for
      judging a seam or checking the stage. A view is only metadata.
- [ ] **Give every segmentation its own view too**, or a labelled run meets the
      same cliff the view was invented to avoid.
- [ ] **Check byte-compatibility.** Every chunk a view serves must match what the
      view declared — dtype, chunk shape, compression, axis order — because the
      bytes are handed over untouched.
- [ ] **Teach the server to read a bundle index**, once bundling is on. A bundled
      chunk is a byte range, not a file.

### D — For analysis

- [ ] **Point at the positions, never at the view.** The view reads back as zeros
      everywhere.
- [ ] **Segment the whole tile**, overlap and all, so no object is ever cut in
      half.
- [ ] **Keep only objects whose centre falls in the owned rectangle.** Trimming
      applies to results, not to pixels.
- [ ] **Flag objects that touch a tile border.** They are the ones the ownership
      rule cannot be trusted for — an object larger than the overlap can be
      clipped in every tile.
- [ ] **Make label numbers unique across the run.** Otherwise cell 7 in two
      neighbouring tiles becomes one object the moment they are drawn together.
- [ ] **Write results back into the position** — `derive_label`, `add_table`.
- [ ] **Append to a run-level table** as well, with the position, well and field
      as columns. Every question worth asking is about the run, and answering one
      should not mean opening ten thousand tables.
- [ ] **Pass paths, not pixels**, across environment boundaries. The engine's
      `data_transfer: "file_paths"` mode exists for exactly this.
- [ ] **Keep `ngio` in the analysis environment only.** It brings 60 packages;
      the acquisition side needs `zarr` and `numpy`.

### E — For scale

- [ ] **Count the files before the run, not after.** Five terabytes at a
      128-voxel chunk is 153 million files unbundled; bundled a plane at a time it
      is about 596,000 of roughly 8 MB.
- [ ] **Remember the chunk cannot be changed afterwards.** Version, position and
      channel colours are metadata edits; chunk shape and compression are full
      rewrites.
- [ ] **Budget the conversion** when a vendor wrote the files first. Bringing five
      terabytes across is a five-terabyte read and write, once.
- [ ] **Keep the second copy for data we did not acquire.** For runs ZMART writes,
      a second copy is a bug; for a foreign transfer it is a fair price.

### F — For interoperability

- [ ] **Validate against the official schemas** shipped with `ngff-zarr`. That is
      the format's own words, not a library's reading of them.
- [ ] **Open every kind of image we write with ngio**, in the test suite. Our own
      reader and writer share our misunderstandings and cancel them out; a
      stranger's library does not.
- [ ] **Never put an unrecognised file inside a `.ome.zarr`.** It makes zarr warn
      whoever opens it. A custom *attribute* is fine; a stray file is not.
- [ ] **Say plainly, in the operator docs, that the view is the one object that
      does not travel.**

---

## What is blocking, right now

1. **The per-dataset translation.** A position as written today is **invalid
   against the official OME-Zarr 0.4 schema** — verified, not inferred — so ngio
   refuses it and `ngff-zarr` silently places it at the origin. Nothing else on
   this page matters until it is fixed, and for light-sheet, where a stitcher is
   the only way to read the data, it is the difference between usable and not.
   The correction is written on `claude/ngff-translation-per-dataset`.
2. **Reading a bundle index in the viewer's server.** Without it, bundling cannot
   be switched on; without bundling, a five-terabyte run cannot be copied. This
   decides whether large light-sheet data is viewable at all.

---

## What is still open

- **Chunk-aligned trimming**, which would remove the second copy from every
  overlapping run — measured at 1.98× the camera's output even with *no* overlap.
- **The no-copy path for a drifting stage.** It currently refuses a run whose
  tiles do not land on an exact grid, so an ordinary run falls back to copying.
- **Whether ten per cent is right at all.** Fiji defaults to 20%, practice runs
  5–30%, and what actually matters is the stage's error and whether the strip
  contains features. We keep every tile whole, so this is measurable on our own
  instruments rather than borrowed from advice.
- **Scenes, when the tools catch up.** RFC-5 describes our exact workflow, but
  Neuroglancer has no notion of a scene and ngio cannot read 0.6 at all. The
  signal to revisit is `ngio.NgffVersions` gaining `"0.6"`.
- **Drawing measured on real hardware.** Every frame rate in these documents came
  from a software renderer with no graphics card.
