# The recipe: exactly how ZMART writes an OME-Zarr

Written 7 August 2026. This is the decided arrangement, written out precisely
enough that somebody adding a driver, or writing an analysis step, can follow it
without reading the writer's source.

It is a companion to
[`ome-zarr-for-analysis-and-neuroglancer.md`](ome-zarr-for-analysis-and-neuroglancer.md),
which is the evidence: what was measured, what other libraries do with our files,
and why each choice below was made. This document is the conclusion of that one.
Where the two disagree, the measurements win.

**Status of each part is marked.** Some of this is written and running, some is
decided but not yet built, and one part is waiting on a specification that is
still a release candidate. Nothing below is a guess about what we might like.

---

## 0. Why OME-Zarr at all, and what each decision buys

We did not choose this format because it is fashionable. We chose it so that a
run can be opened by software nobody here wrote — a colleague's napari, a
stitcher, an analysis library, a viewer written years from now. Every decision
below is answerable to that, so it is worth saying plainly which ones serve it:

| decision | what it buys |
| --- | --- |
| scale then translation, beside each resolution (§2) | every reader places the tile where it really was |
| five axes always, named (§2) | nobody has to guess which dimension is depth |
| 0.5 by default, 0.6 only where 0.5 cannot state the truth (§4, §6) | read by everything today, honest about deskews and rotations when it must be |
| labels and tables *inside* the image (§5) | ngio, Fractal, napari and Fiji find a segmentation without being told |
| our own bookkeeping beside the images (§5) | nothing we invented ever appears inside an image somebody else opens |
| whole tiles kept as the ground truth (§7, §8.0) | a stitcher can always go back to what the camera saw |
| the chunk derived from the camera (§8.1) | no microscope has to change its format to suit us |

**And one place where we knowingly trade it away.** The view is a valid OME-Zarr
image whose pixels live in the positions, so it opens elsewhere and reads blank.
That is the price of handing Neuroglancer one source instead of ten thousand, and
it is paid in exactly one object, which is why the rule "point analysis at the
positions" matters so much. §6 describes the scene that would let us stop paying
it.

**Interoperability is not achieved by intending it.** It is achieved by a test
that runs somebody else's reader over our output — which is how the fault in §2
was found, and how it would have been found the day it was introduced. Changes 1
and 4 on the list at the end are the ones that matter most, and they are both
about being readable rather than about being clever.

---

## 1. What a run leaves on disk

*Status: written and running, except where noted.*

```text
<experiment>/
  overview.ome.zarr/                 the view — one image for the viewer
    zarr.json                        multiscales, omero, and our own `zmart` block
    0/  1/  2/  3/                   descriptions only; holds no full-size picture
    positions/
      zarr.json                      a zarr group, so nothing warns when opened
      overview_pos00000.ome.zarr/    a position — an ordinary image, real pixels
      overview_pos00001.ome.zarr/
      ...
  targetscan.ome.zarr/               a second kind of scan, same shape
    positions/ ...
  zmart-coverage/                    ours — where the run has actually imaged
    overview.ome.zarr/
  overview.writing                   ours — a lock, so two writers cannot collide
```

**One acquisition type, one view.** A smart experiment usually has a wide survey
and the detailed scans it led to. Each gets its own `<name>.ome.zarr` at the top,
with its own `positions` inside it, because they have different voxel sizes and
different numbers of levels and cannot share a picture.

**A position is named `<name>_pos<NNNNN>.ome.zarr`**, numbered from zero in the
order the stage visited. The number is an index, not a coordinate: where the
position sits is stated inside the image, never in its name.

**Point analysis at the positions, never at the view.** The view is a complete and
valid OME-Zarr image that holds no chunk files of its own — every piece of it is
one of the positions' pieces, handed over by the viewer's server. Opened by
anything else it is correct in every respect and blank. See section 6 for why it
exists at all and what will replace it.

---

## 2. What every image says about itself

*Status: written and running, except the position of the translation — see the
box at the end of this section.*

Every image this project writes, view and position alike, declares **five axes**,
whether or not the run had a moment or a colour to put in them. A run that images
one plane in one colour still says `t, c, z, y, x`. Constant shape is worth more
than economy here: a reader never has to ask which axes exist, and a workflow does
not change behaviour because an operator happened to use one channel.

```json
"axes": [
  {"name": "t", "type": "time",    "unit": "second"},
  {"name": "c", "type": "channel"},
  {"name": "z", "type": "space",   "unit": "micrometer"},
  {"name": "y", "type": "space",   "unit": "micrometer"},
  {"name": "x", "type": "space",   "unit": "micrometer"}
]
```

**Where the image sits is stated beside each resolution, and only there:**

```json
"datasets": [
  {"path": "0", "coordinateTransformations": [
     {"type": "scale",       "scale":       [1.0, 1.0, 2.0, 0.35, 0.35]},
     {"type": "translation", "translation": [0.0, 0.0, 11.0, 5.5, 7.25]}
  ]},
  {"path": "1", "coordinateTransformations": [
     {"type": "scale",       "scale":       [1.0, 1.0, 2.0, 0.70, 0.70]},
     {"type": "translation", "translation": [0.0, 0.0, 11.0, 5.5, 7.25]}
  ]}
]
```

Three things are decided here and each has a reason:

- **Scale first, then translation, in that order.** The format requires the list
  to begin with a scale. A lone translation is refused by ngio outright, and
  quietly ignored by `ngff-zarr`, which places the image at the origin instead.
- **Per dataset, and never also at the multiscales level.** A reader composes the
  two, so an image stating its position in both places is moved twice, ending up
  at double the distance from the stage's zero.
- **The translation is the corner of the first voxel, not its middle**, and every
  level carries the same one. Under the corner reading the levels nest perfectly.
  Some readers assume the middle and will place the picture half a voxel off; that
  is theirs to correct, because a file that shifts itself to suit one reader is
  wrong for every other. The arithmetic is in `zmart_storage/VOXEL_PLACEMENT.md`.

> **Not yet true of positions.** Today `zmart_storage/canvas.py` writes the
> position's translation at the multiscales level instead, which is why ngio
> refuses to open a position. The correction exists on
> `claude/ngff-translation-per-dataset` and is change number one on the list. The
> view already does it the right way.

**Channel names, colours and brightness go in the `omero` block.** It is a
transitional part of the specification and a future version may move it, but it is
what readers understand today, and it is what makes an acquisition open at the
brightness it asked for rather than at the camera's full range.

---

## 3. How the smaller copies are made

*Status: written and running.*

Every second voxel is kept along **y and x**; nothing is averaged, and **z is never
reduced** — scrolling a stack should show the planes that were really acquired.

```json
"type": "nearest",
"metadata": {
  "method": "slice",
  "description": "Every second voxel kept along y and x at each level; nothing is averaged, so each coarse voxel is one original voxel."
}
```

This is deliberate and load-bearing rather than lazy. Because no voxels are
combined, a zoomed-out voxel comes from exactly one position — which is what lets
the view point at the positions' own zoomed-out copies instead of writing a second
set. Averaging would mix voxels across the join between two positions and no
position would own the result.

It has a visible consequence worth telling operators: a zoomed-out picture is a
*sample* of the specimen rather than a smoothed version of it. Bright specks
survive at every zoom instead of fading, and a faint object lying between two kept
rows can disappear when you zoom out.

### How wide should the ladder be, and should it stride at all?

*Measured 7 August 2026. This questions the two choices above rather than
restating them.*

The pyramid costs a third of the run on disk, so it is fair to ask whether it has
to. Written three ways over the same 4096 × 4096 picture:

| ladder | pyramid costs | levels | first pixel | requests | **cells still visible** |
| --- | ---: | ---: | ---: | ---: | ---: |
| halve each time (today) | **+36%** | 6 | 2.52 s | 113 | 100% |
| **quarter each time** | **+7.6%** | 3 | **1.60 s** | 89 | 100% |
| eighth each time | +1.8% | 2 | 1.66 s | 84 | **63%** |

A wider ladder is better on every count that is easy to measure — less disk, fewer
levels, quicker to open, fewer requests. **What stops it is the last column.**

On a sparse specimen — two thousand cells of two to four voxels' radius, which is
exactly the target-finding case — an eighth-sized step *by striding* loses **37% of
the cells** from the zoomed-out view. For a survey whose whole purpose is finding
cells, that is a broken instrument rather than a softer picture.

**So with striding, four is the limit.** It keeps every cell, costs 7.6% instead
of 36%, and halves the number of levels.

### But the striding is what caps it, and the reason for striding does not hold

The same test with **averaging** keeps **98%** of cells at an eighth-sized step. So
the cap comes from the choice of striding, not from the ladder.

The argument for striding is quoted above: averaging "would mix voxels across the
join between two positions, and no position would own its result", which would
break the view's ability to point at the tiles' own copies. **That argument does
not survive checking.** An averaging window can only straddle a join if a tile is
not a whole number of windows — and the writer already requires a tile to begin on
a multiple of the piece size *times the largest shrink*, which is far stronger
than needed. Measured directly:

```
averaging by 2x: whole-canvas == tile-by-tile ?  True  (max difference 0.000000)
averaging by 4x: whole-canvas == tile-by-tile ?  True  (max difference 0.000000)
averaging by 8x: whole-canvas == tile-by-tile ?  True  (max difference 0.000000)
```

Averaging within a tile is bit-for-bit what averaging the whole canvas would give,
so every coarse voxel still comes from exactly one position and the view can still
point at it.

**Which puts an eighth-sized averaged ladder on the table: a 1.8% pyramid instead
of 36%, with 98% of cells surviving rather than 63%.** On five terabytes that is
the difference between 1.7 TB of smaller copies and 90 GB.

Two honest costs before adopting it:

- **Averaging is arithmetic where striding is a memory copy.** It is a mean over
  f² voxels, and it produces 1/f² as much data as it reads, so the cost is
  bounded — but it is no longer free, and on a live run it competes with the
  acquisition.
- **A coarse voxel stops being a real measurement.** Under striding, every voxel
  at every zoom is something the instrument actually recorded; under averaging the
  zoomed-out picture is a smoothed version. Nobody quantifies on the pyramid, so
  this is about honesty in what the operator is shown rather than about analysis —
  but the sentence above about specks surviving would need rewriting the other way
  round.

---

## 4. How the pixels are stored

*Status: written and running; the default version is change number three.*

| | decided | why |
| --- | --- | --- |
| OME-Zarr version | **0.5** (zarr v3) by default; 0.4 on request; **0.6 when the acquisition needs a transformation 0.5 cannot express** — see section 6 | 0.5 is read by everything today and can bundle chunks; 0.6 is the only way to state a deskew, a rotation between views, or a place that changes with time |
| chunk | `(1, 1, 1, piece, piece)`, with `piece` **derived from the tile shape and the wanted overlap** at run setup — see §8.1 | one plane per piece, so showing a single plane never fetches its neighbours; and the chunk cannot be changed afterwards without rewriting every byte, so it must be right the first time |
| bundling (sharding) | **every level**, one tile plane per bundle, capped at the level's own extent for the small ones | a two-terabyte run at a 128-voxel chunk leaves 20.6 million files if only the full-size level is bundled, because the pyramid then dominates — and 318,000 if every level is. That is the file count of a 2048-voxel chunk with the 32 KB fetches of a 128-voxel one. **The writer bundles level 0 only today**, which is blocking item 3 |
| number type | whatever the camera gives, usually `uint16` | never converted; a run stores what was recorded |
| compression | zstd | fast enough to keep up with acquisition |
| unwritten chunks | left unwritten, fill value `0` | a declared canvas is far larger than any run fills, and empty room must cost nothing |
| dimension names | written into each array in 0.5 | the specification requires it, and it lets one level be opened on its own |

`start_a_run` already defaults to 0.5. `canvas.TileCanvases` and
`cropped.TilesAndCanvas` still default to 0.4 and should be brought into line.

**What a run must satisfy.** These are ours, not the format's, and they exist so
that a position's own file can be handed to the browser without touching a voxel:
every position begins on a multiple of the chunk size times the largest shrink,
and all positions in one acquisition are written the same way — the same number
type, compression, chunk size, axis order and number of levels. A run that breaks
this is refused when the view is built, with a message saying what would work.

---

## 5. What goes inside an image, and what goes beside it

*Status: the rule is running; `owned_ROI_table` is change number two.*

**The rule: things the format has a place for go inside; things it has no place
for go beside.**

Inside an image:

| path | what it is | written by |
| --- | --- | --- |
| `labels/<name>` | segmentations | analysis, via ngio `derive_label` |
| `tables/<name>` | measurements and regions | analysis, via ngio `add_table` |
| `tables/owned_ROI_table` | the part of this tile that it owns — see section 7 | the writer |

Beside the images, never inside:

| path | what it is |
| --- | --- |
| `zmart-coverage/<image>/` | where the run has actually imaged so far |
| `<name>.writing` | the lock that stops two writers sharing one image |

A stray file *inside* a `.ome.zarr` folder makes zarr warn whoever opens it —
*"Object at zmart-links.json is not recognized as a component of a Zarr
hierarchy"* — and a colleague meets a warning about a file they have never heard
of. That is what the rule protects against.

**One exception, stated plainly.** The view's own `zarr.json` carries a top-level
`"zmart"` attribute holding the map of which piece of the picture is which piece
of which position. That is a custom *attribute*, not a stray object, so it causes
no warning and no reader trips over it. It is the one place we put our own data
inside an image, and section 6 is about replacing it with something standard.

---

## 6. The view today, and the scene that should replace it

*Status: the view is running. The scene is a decision to prepare for, not to build
yet.*

### Measured: one view against N sources, on the same files

Taken 7 August 2026. The repository's two existing harnesses measure different
things, so their numbers could not be set beside each other — one times a
page-open call, the other times open-until-something-is-drawn. This is a
like-for-like run instead: **one run of positions written once, then opened
twice** — as the view that points at them, and as the positions handed over one
by one. Nothing differs but how many sources the drawing engine is given.

| positions | view: first pixel | separate: first pixel | view: requests | separate: requests | separate: worst frame |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 3.04 s | 2.53 s | 101 | 197 | 17 ms |
| 200 | 2.14 s | 7.91 s | 115 | 647 | 17 ms |
| **600** | **2.19 s** | 3.66 s | **120** | **1,547** | **733 ms** |

**The view is flat.** From fifty positions to six hundred, it needs 101 to 120
requests and about two seconds to the first pixel. That is the whole claim of the
arrangement, and this is the first time it has been checked against the
alternative on identical files.

**At fifty positions the two are equal**, and the view is if anything marginally
slower. So a small run genuinely does not need it — the apparatus earns its place
somewhere between two hundred and six hundred positions.

**Two costs make the separate arrangement worse as it grows, and they differ in
kind:**

- **Metadata requests, paid before anything is drawn.** The engine resolves each
  store as it is added — about 2.6 requests a position here — through a browser
  that opens roughly six connections at a time. At six hundred positions that is
  1,547 requests queueing before the first pixel.
- **A drawing layer per source, paid on every frame.** Every layer takes part in
  every redraw whether or not it is visible. That is what produces the 733
  millisecond worst frame at six hundred, where the view stays at 17.

**Read the worst frame rather than the middle one.** At six hundred separate
sources the *middle* frame is still 17 ms — typical frames are fine. It is the
worst that blows out, so it is felt as a **hitch while panning** rather than a
uniformly sluggish viewer, which is often the more annoying of the two.

**And do not read much into the first-pixel column for separate sources** — 2.5,
7.9, 3.6 is erratic because it depends on when a tile that happens to sit under
the middle of the screen arrives. Requests and worst frame are the stable
signals.

As with everything else here, this was drawn in software with no graphics card. A
real card would lift the frame rates; it would not change the request counts, and
the per-layer bookkeeping it measures is processor work rather than drawing work.

### Why the view exists

The view does **two different jobs**, and separating them is the most important
thing in this document:

1. **It says where each tile is.** That is a statement of fact about the
   experiment.
2. **It gives Neuroglancer one thing to draw.** That is a performance device.
   Neuroglancer builds a drawing layer per source and every one takes part in
   every frame: a thousand separate positions drew twenty-four frames in five
   seconds where one image managed 255.

Our `zmart` link map does both at once, which is why it feels like a private
format. It is only really private about the first job.

### OME-Zarr 0.6 does the first job properly

Version 0.6 — [released as a release candidate in July
2026](https://gerbi-gmb.de/2026/07/06/ngff-specification-0-6-rc0-released-a-milestone-for-open-microscopy-data/)
— adopts [RFC-5, coordinate systems and
transformations](https://ngff.openmicroscopy.org/rfc/5/), which introduces a
**scene**: a group above several images that declares how they sit in one shared
coordinate system.

The RFC's own motivation describes this project's workflow almost word for word:

> a store for the scene can be created at the beginning of a tiled image
> acquisition. The acquired tile can then be stored as individual OME-Zarr images
> on-the-fly inside this store. Finally, the microscope only needs to keep track
> of the necessary metadata to express the spatial relationship between all saved
> tiles. **In this context, it does not matter whether tiles overlap or not,**
> transformations simply express each tile's location in a common world coordinate
> system.

That last clause is the overlap problem, answered by the format rather than by us.
And the RFC handles the other thing a smart run needs — a tile whose place changes
between timepoints, as in drift correction or a tracking workflow — through
per-timepoint transformations, built from `sequence` and `byDimension` wrappers
rather than needing anything new.

Our layout already has the right shape for it. `overview.ome.zarr` is a group
holding a `positions` group of images; a scene is a group holding images. The
`zmart` attribute becomes a `scene` dictionary, and the same facts are written in
the format's own words.

### What a scene does not do — checked, not assumed

Two libraries were read in source on 7 August 2026 rather than taken on trust.

**Neuroglancer reads 0.6 images but knows nothing about scenes.** Its zarr reader
lists `0.4`, `0.5-dev`, `0.5`, `0.6.dev1`, `0.6.dev3` and `0.6` as supported, and
it parses the new `coordinateSystems` block on a multiscale image
(`src/datasource/zarr/ome.ts`). The word `scene` does not appear anywhere in its
zarr reader. So a scene of ten thousand tiles gives it nothing: it is still ten
thousand images, still ten thousand drawing layers, and the frame-rate cliff does
not move because the metadata got better. The RFC itself says downstream software
should "create a seamless mosaic on-demand" — which is exactly the work our
viewer's server already does.

**ngio 1.0.0 cannot read 0.6 at all.** Its declared versions are `0.4` and `0.5`,
and its default is `0.4`. Writing 0.6 today would mean writing something our
analysis library cannot open, to gain a feature the viewer cannot use.

So the decided direction is:

> **When the tools catch up, the scene becomes the truth about where tiles are,
> and the view stays — demoted to what it really is: a drawing device, built from
> the scene, that a viewer may use and anything else may ignore.**

That is a better arrangement than we have now, because nothing that matters about
the experiment would live in a file only we can read. But it is a direction, not a
change to make this month.

### What it would and would not fix for overlapping tiles

Worth being exact, because "it handles overlap" is easy to over-read.

| the trouble | does a scene fix it? |
| --- | --- |
| **Saying where an overlapping tile is.** Today a run whose tiles overlap cannot go into one image, so the canvas writer refuses it and `cropped.py` trims to work around that. | **Yes, completely.** A scene states each tile's place in a common world; whether tiles overlap simply does not come up. The trimming would no longer be needed *in order to describe the run*. |
| **Drawing an overlapping run quickly.** | **No.** Neuroglancer still wants one source and still cannot be handed ten thousand. The view stays. |
| **Deciding what to show in the overlap.** | **No.** The format states where tiles are; it has no opinion on which of two tiles a viewer should draw, or how to blend them. |
| **Not counting a cell twice.** | **No.** Ownership is an analysis decision. `tables/owned_ROI_table` is still needed. |

The pattern is worth remembering: **RFC-5 fixes the describing. It does not fix
the drawing or the counting.** Those two remain ours, and they are the two the
overlap problem actually consists of.

### What 0.6 wins at the image level, which is a separate question

A scene is not the only thing 0.6 brings, and the rest of it is winnable now,
because Neuroglancer already reads 0.6 images. The schemas say exactly what
changes:

| | transformations allowed beside a resolution |
| --- | --- |
| 0.4 and 0.5 | exactly one `scale`, optionally one `translation`. **Nothing else.** |
| 0.6 | `affine`, `rotation`, `sequence`, `byDimension`, `mapAxis`, `displacements`, `coordinates`, `bijection`, `identity`, plus scale and translation |

So for an **upright, axis-aligned raster** — the confocal overview and target scan
this project mostly runs — 0.5 already says everything there is to say, and 0.6
adds nothing a viewer could use. No win.

But for three kinds of acquisition, 0.5 cannot state the truth at all:

- **Oblique-plane and light-sheet deskewing.** The correction is an affine shear.
  In 0.5 it cannot be written down, so such data must either be deskewed and
  rewritten as new pixels, or drawn wrong.
- **Multi-view light-sheet.** Views related by a rotation, which 0.5 cannot
  express either.
- **A tile whose place changes between timepoints** — drift correction, and a
  tracking run. Per-timepoint transformations need `sequence` or `byDimension`.

For those the choice is not "0.5 with less detail" against "0.6". It is **wrong
against right**, and the cost of choosing 0.6 is smaller than it first appears:
ngio cannot read 0.6, but for a sheared or rotated acquisition ngio could not have
placed it correctly in 0.5 either, because 0.5 has no way to say it. Nothing
correct is being given up.

**So the rule is per acquisition type, not per project:**

> Write **0.5** by default. Write **0.6** when the acquisition needs a
> transformation 0.5 cannot express — a deskew, a rotation between views, or a
> place that changes with time.

### And the choice is reversible, which settles the nerves

`ngff_zarr.upgrade_ome_zarr` upgrades a store in place from 0.5 to 0.6 by
rewriting the root group's metadata only: *"Every array chunk on disk is left
byte-for-byte untouched."* Even 0.4 to 0.5 or 0.6 in place is metadata-only,
because the existing chunk files are made to resolve unchanged.

That means committing to 0.5 today is barely a commitment. A finished run can be
lifted to 0.6 later by rewriting one `zarr.json`, not by rewriting terabytes. The
only direction that costs a copy is going backwards across the zarr v2/v3 line,
which we would never do.

### When to act

For an ordinary raster: not yet. Three reasons, in order of weight:

1. **ngio cannot read 0.6**, and it is the library our analysis will be written
   against. That alone settles it.
2. **Neuroglancer gains us nothing from a scene**, only from 0.6 images — and it
   already reads our 0.5 images perfectly well.
3. **0.6 is a release candidate.** The parts we would lean on hardest are the ones
   most likely to be adjusted before the final release.

What to do meanwhile, all of it useful whatever happens:

1. Keep writing 0.5, with the per-dataset transformation of section 2. None of it
   is wasted — a scene refers to exactly these per-image statements, so getting
   them right *is* the preparation.
2. Keep the `zmart` map as an attribute rather than a file, so replacing it with a
   `scene` dictionary later is a change to one block of JSON.
3. Watch ngio's version list. `ngio.NgffVersions` gaining `"0.6"` is the practical
   signal, and it is one line to check.
4. When it lands, write the scene **as well as** the view, and find out whether
   other software can then open a run without our viewer. That is the test worth
   running, and it can be run the week support arrives.

---

## 7. Overlap: what a tile owns

*Status: the trimming is running; `owned_ROI_table` is change number two.*

Tiles are acquired overlapping on purpose, because the shared strip is the only
evidence of where the stage really went. That causes two troubles which are
actually one:

- **Analysis** would count every cell in the shared strip twice.
- **The viewer** cannot write two values into one voxel.

Both are settled by one rectangle, computed from two numbers the run could not
have started without:

```text
overlap on an axis        = tile size − stage step
what comes off each edge  = half of that
```

with tiles at the edge of the raster keeping their outer strips, because there is
no neighbour there to replace what would be cut. `Trimming.of(tile_shape,
tile_step)` in `zmart_storage/cropped.py` already computes it, and the trimmed
canvas already uses it.

**The rule for analysis, which is not "analyse part of a tile":**

> Segment the **whole** tile, overlap and all, so no cell is ever cut in half.
> Then keep only the objects whose **centre** falls inside the owned rectangle.

Every object is then counted exactly once, because the owned rectangles butt up
and cover the ground with no gaps and no double cover. Trimming applies to
results, not to pixels.

Recording that rectangle as `tables/owned_ROI_table` inside each tile is what makes
the viewer's crop and the analysis filter the *same* decision rather than two that
happen to agree — so a cell can never be shown on one tile and counted on another.

Where the rule breaks is written out in the companion document: objects larger than
the overlap, a stage that drifts, and runs with no regular step.

---

## 8. What should change, given all of it at once

*Status: none of these are built. This section is the answer to "given overlap,
efficient viewing, efficient analysis, and label layers — what should change?"*

Taken one at a time the earlier sections each suggest a small correction. Taken
together they point at four changes, and the first is much larger than it looks.

### 8.0 The principle, and what it costs today

Stated once, because everything in this section serves it:

> **Keep the ground truth once — every tile whole, exactly as the camera recorded
> it — and let the viewer and the analysis each account for the overlap in their
> own way, without either of them copying a voxel.**

A run of five terabytes makes this a requirement rather than a preference. Here is
what the two writers cost, measured on noise so that the numbers describe the
arrangement rather than how compressible the specimen happened to be.

| written by | on disk, as a multiple of what the camera made | five terabytes becomes |
| --- | --- | --- |
| `cropped.py`, **no overlap at all** | **1.98 ×** — archive 0.86 ×, canvas 1.12 × | **9.9 TB** |
| `positions.py` + `linked.py` | each voxel once, plus its own smaller copies; the view writes nothing at all | about 1.3 TB over the raw |

The first row is the one to look at twice. That run had **no overlap** — nothing
was shared, nothing needed trimming — and it still wrote the whole acquisition
twice, because that writer always writes an archive and a canvas. An overlapping
run is worse, since the canvas carries its own pyramid on top.

The second row is not a plan; it is what `linked.py` already does, and
`zmart_storage/tests/test_a_view_that_writes_nothing.py` is the test that holds it
to it. The whole of §8 is about extending that arrangement to the cases it does
not yet cover.

### 8.1 Trim on a chunk boundary, and the second copy disappears

**The wart.** A run whose tiles do not overlap is written once: positions, plus a
view that points at them and copies nothing. A run whose tiles *do* overlap — the
common case, and the one every stitcher needs — is written **twice**: whole tiles
for the archive, and a trimmed canvas for the viewer with every voxel copied into
it. So the ordinary case pays a full second copy in disk, in time, and in waiting.

**Why the copy exists.** Trimming today happens at an arbitrary number of voxels —
half the overlap, whatever that comes to — and a view can only hand over *whole
chunk files*. A trim that cuts through the middle of a chunk cannot be expressed
by pointing; it has to be cut, and cutting means copying.

**The change, and it is smaller than it looks, because half of it is already
enforced.** `cropped.py` will not accept a run whose *trimmed tile* is not a whole
number of chunks across — `_refuse_a_trim_that_does_not_land_on_whole_pieces`
refuses it and helpfully lists the overlaps that would have worked:

```
trimming this acquisition would leave a tile of 460 voxels in y, and the canvas
stores its picture in pieces 128 voxels across, so a trimmed tile is 3.59 pieces
rather than a whole number of them.
...
Overlaps that would work here, in voxels: 0, 128, 256, 384.
```

So operators are already choosing overlaps from a short list, and the discipline
this needs is one they have already accepted. What the existing rule aligns is the
trimmed tile's **width**. Pointing also needs its **start** to fall on a chunk
boundary, which is one step stricter: with a 128-voxel chunk, an overlap of 128
leaves a half-overlap of 64 — half a chunk — so the kept part begins in the middle
of a chunk file and cannot be handed over whole.

Require the overlap to be **an even whole number of chunks** — 0, 256, 512 rather
than 0, 128, 256, 384. Then the half-overlap is a whole number of chunks, a trimmed
tile begins *and* ends on the grid, and trimming becomes *pointing at fewer chunks*,
which costs nothing.

The arithmetic is undemanding. With a 2048-voxel tile and a 128-voxel chunk, an
overlap of two chunks is 256 voxels, or 12.5% — close enough to the usual ten per
cent that an operator would not notice the difference. Stated as a rule for the
acquisition:

> The tile is a whole number of chunks across, and the stage steps so that the
> overlap is an even whole number of chunks.

Both are facts the run has to settle before it starts anyway, and both can be
checked and adjusted when the run is set up rather than discovered afterwards.

**What it buys.** One arrangement instead of two. Overlapping and butting runs
become the same thing — positions plus a view — and `cropped.py`'s copying path
becomes the fallback for runs that cannot satisfy the alignment: foreign transfers,
irregular smart scans, anything we did not write ourselves.

#### How free is the choice of overlap?

Not a percentage at all, which is the thing to understand. The rule is **an even
whole number of chunks, on each axis**, and the percentage is whatever that comes
to for the tile you are imaging. So the freedom is set by the chunk size, and the
chunk size is ours to choose.

For a camera giving 2048 voxels across:

| chunk | overlaps that allow a tile to be handed over whole |
| --- | --- |
| 32 | 0%, 3.1%, 6.2%, **9.4%**, 12.5% … |
| 64 | 0%, 6.2%, **12.5%**, 18.8%, 25% |
| **128** (our default) | 0%, **12.5%**, 25%, 37.5% |
| 256 | 0%, 25% |

So a plain ten per cent is not on the list at our chunk size, and **12.5% is the
nearest thing to it**. Fifteen is not available either; the neighbours are 12.5%
and 25%.

**Some frame sizes have no usable chunk at all**, which is what makes the next
part necessary rather than clever. A frame 2308 voxels across is 4 × 577, and 577
is prime — so **not one number between 64 and 256 divides it**. No amount of
choosing helps; that frame simply cannot be chunked for pointing.

That particular width is hypothetical, and it is worth saying so rather than
leaving a wrong fact in a design document. The real cameras are kinder: a
Hamamatsu ORCA-Fusion BT is **2304 × 2304**, which is 2⁸ × 9 and divides by 64,
72, 96, 128, 144, 192 and 256; an ORCA-Flash4.0 is 2048; an ORCA-Quest is
4096 × 2304. Where arbitrary widths genuinely do arise is a point scanner, whose
format is whatever the operator set it to — 1608 and 700 in the tables below are
that case, not a camera.

##### Let the writer drop a few voxels, and everything lands on 10%

Allow the frame to be trimmed by **less than one per cent** before it is stored,
and the whole difficulty evaporates:

| sensor across | store | dropped | chunk | overlap | which is |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2304 | 2300 | 4 (0.17%) | 115 | 230 | **10.0%** |
| 2308 (hypothetical) | 2300 | 8 (0.35%) | 115 | 230 | **10.0%** |
| 2048 | 2040 | 8 (0.39%) | 102 | 204 | **10.0%** |
| 2044 | 2040 | 4 (0.20%) | 102 | 204 | **10.0%** |
| 1608 | 1600 | 8 (0.50%) | 80 | 160 | **10.0%** |

Every width, including the one with no divisor at all, lands on **exactly ten per
cent** — the number microscopists actually ask for — by giving up two to four
voxels at each edge. Note the second row of real value here: 2048, the commonest
sensor there is, gives 12.5% untrimmed and 10.0% for the sake of eight voxels.

**This is a good trade and it is worth being explicit about why.** The alternative
is accepting 12.5% instead of 10%, and covering a fixed area needs `1/(1−v)²`
times as many tiles: 1.235× at ten per cent against 1.306× at twelve and a half.
So refusing to trim costs about **six per cent more tiles, time and disk**, while
trimming costs **a third of one per cent of the field**. Twenty times cheaper, and
it buys the round number as well.

It is also the *right* few voxels to lose. The outermost pixels of a sensor are
the ones with vignetting and edge artefacts, and on a point scanner the outer
columns are the scanner's turnaround. Nobody quantifies cells there.

**Two guards, so this cannot become a place data quietly disappears:**

- **A hard cap of one per cent**, refused rather than exceeded. If a frame cannot
  be made to fit within that, it does not get trimmed — it falls back to the
  copying path and says so.
- **The trim is recorded and reported at setup**, in voxels and per cent, in the
  same voice the writer already uses: *"storing 2300 of 2308 columns, dropping 4
  at each edge (0.35%), which allows a 115-voxel chunk and an overlap of exactly
  10%."* An operator who objects can then say so before the run rather than after.

##### Best of all: align the format, the chunk and the overlap together

The tables in this section take the frame as given and derive the rest. Choosing
all three at once does better, and on the sensors actually in use it does better
*with no frame fitting at all* — nothing shaved off, nothing discarded:

| sensor | chunk | overlap | chunks per tile-plane |
| --- | ---: | ---: | ---: |
| **2304** (ORCA-Fusion) | **192** | **16.7%** | **144** |
| 2304 | 256 | 22.2% | 81 |
| **4096** (ORCA-Quest) | **256** | **12.5%** | 256 |
| 2048 | 128 | 12.5% | 256 |
| 2048 | 256 | 25.0% | 64 |

**This supersedes the advice below for a 2304 sensor.** Compare what aligning all
three gives against what optimising for an exact ten per cent gave:

| | chunk | overlap | requests per tile-plane | voxels discarded |
| --- | ---: | ---: | ---: | ---: |
| optimise for exactly 10% | 115 | 10.0% | 400 | 4 an edge |
| **align all three** | **192** | 16.7% | **144** | **none** |

Two point eight times fewer requests, nothing lost, and 16.7% sits squarely in the
range that stitches well. It costs about seventeen per cent more imaging than ten
per cent would. For *optimal* meaning snappy, lossless and stitchable, the aligned
answer wins.

**2048 is the genuinely awkward sensor**, and now the reason is precise: its
divisors are all powers of two, so it offers 12.5% at chunk 128 or 25% at chunk
256 and nothing in between.

**Where the format is ours to set — the point scanners — ask for one of these:**

| scan format | chunk | overlap | requests per tile-plane |
| ---: | ---: | ---: | ---: |
| **2880** | 288 | 20.0% | **100** |
| 3456 | 288 | 16.7% | 144 |
| 4608 | 288 | 12.5% | 256 |

A confocal set to 2880 rather than 2048 gets a larger chunk, a better overlap and
a quarter of the requests — better on every axis at once, for the cost of typing a
different number into the acquisition software.

##### Correction: prefer the large chunk, not the exact overlap

The tables above choose the chunk that lands nearest the requested overlap. That
is the wrong variable to optimise, and it was measured after the fact.

The browser keeps only about **six requests in flight** over HTTP/1.1, and
`canvas.py` already notes that each piece costs a few milliseconds of the
browser's own bookkeeping whatever its size. So the chunk *count* is what decides
whether a view feels snappy. For a 2048 tile:

| chunk | overlap it allows | imaging cost | requests to fill a 4K screen | round trips at six in flight |
| ---: | ---: | ---: | ---: | ---: |
| 102 | 10% | 1.23 × | ~836 | ~700 ms |
| 128 | 12.5% | 1.31 × | 527 | ~440 ms |
| **204** | **20%** | 1.56 × | **209** | **~175 ms** |
| 256 | 25% | 1.78 × | 144 | ~120 ms |

**Chunk 102 is the worst of both**: it buys 2.5% less imaging at the cost of sixty
per cent more requests than a 128 would need. Optimising for an exact ten per cent
produced it.

**So the order is: take the largest chunk that gives an acceptable overlap, rather
than the overlap that gives an exact number.** On a 2048 sensor that is chunk 204
at twenty per cent — two and a half times fewer requests than 128, and twenty per
cent is what Fiji defaults to anyway, so nothing is wasted. Where imaging time
binds harder than snappiness, chunk 128 at 12.5% is the other sensible point.

**A larger sensor removes the squeeze.** 2048 is only eight chunks across at 256,
which is why it forces 25%:

| frame | what chunk 256 allows |
| --- | --- |
| 2048 | 25% overlap |
| 2560 | 20% |
| 3072 | 16.7% |
| 4096 | 12.5% |

**Which changes what `plan_a_grid` should be asked.** Not "what overlap do you
want" alone, but **which matters more here — snappy viewing or cheap imaging** —
and then the largest chunk consistent with the answer.

##### And if snappiness still binds: HTTP/2

The six-in-flight limit is a property of HTTP/1.1, which is what
`ThreadingHTTPServer` speaks. HTTP/2 raises it to about a hundred streams, which
would take a 527-chunk screen fill from ~440 ms of round trips to ~26 ms.

It does **not** fix the per-chunk bookkeeping or the decoding, which scale with
chunk count whatever the transport — so it complements a larger chunk rather than
replacing it.

Its cost is real though: browsers speak HTTP/2 only over TLS, so the microscope
computer would need a certificate, and a self-signed one means a warning or a
locally trusted authority. That breaks the *run it and it works* property the
web viewer is built around, and it needs a dependency against the current
standard-library-only rule.

**So take the chunk size first** — it is free — and measure what remains before
taking on a certificate. Chunk 256 over plain HTTP/1.1 is 144 requests and about
120 ms, which may well settle the question. There is no easy win left on the
server side, incidentally: the map of pointers is already cached on the listing's
modification time and length, so a chunk request costs two `stat` calls, a lookup
and a file read.

##### Does this hold for any sensor? Tested, yes

Every whole number from 512 to 5000 was tried as a frame width — 4,489 of them:

- **sizes with no solution: none.**
- **3,699 of them (82%) land within half a per cent of ten per cent**, trimming
  under one per cent of the frame.

The only sizes that land far off are small frames — 519 to 638 across come out at
25–28%, because with a 64-voxel floor on the chunk a tile that small is only seven
or eight chunks wide and the overlap grid is coarse. Everything above roughly 700
across, which is every real camera, lands on ten per cent.

**So the exact sensor size stops being something anybody has to know or agree on.**
The driver reports it, the writer works out the rest, and the operator reads one
line saying what was chosen. Whether a particular Hamamatsu is 2304 or 2308 or
something else entirely does not need settling.

The one case worth remembering: a small frame — 512 or 640 across, which a
confocal may well be set to — cannot have a fine overlap grid. If that turns up
and 25% is more imaging than the experiment can afford, the fix is to let the
chunk go below 64 for that run and accept more files. Worth knowing; not worth
designing around until it happens.

**If you would rather not trim at all**, the answer reverts to the table above:
take 12.5% on a 2048 sensor and 11.1% on a 2304, accept the six per cent, and note
that a 2308 sensor cannot be pointed at and will be written twice.

##### Is ten per cent actually right? Nobody quite knows

Worth recording, because "ten per cent" is repeated as though it were settled and
it is not. Fiji's Grid/Collection stitching **defaults to 20%**; published practice
runs from 5% to 30%; and the usual advice is to use the least overlap you can get
away with, since more costs imaging time and stitching time alike.

What actually sets the floor is two things about a particular setup, neither of
them a percentage:

- **The stage's positional error.** The overlap has to comfortably exceed how far
  the stage misses by. At 0.35 µm a voxel, ten per cent of a 2048 frame is 204
  voxels, about 71 µm — enormous next to any decent stage.
- **Whether the strip contains anything to correlate.** This is the one that
  actually bites. On a sparse specimen — a few cells in a mostly empty field — a
  ten per cent strip can hold no features at all, and the stitch fails however
  generous the percentage. Sparse samples are why people go to twenty or thirty.

**And we are unusually well placed to stop guessing.** Every tile is kept whole,
so after a run a stitcher can report how far each tile really moved from where the
stage said it was. If those offsets are a handful of voxels against an overlap of
204, the run is paying for ten times what it needs — and that would be known from
this instrument and this specimen rather than from what people say. Worth doing
once per microscope, and it is exactly the measurement the archive exists to make
possible.

**What the overlap is actually for sets the floor.** It exists so a stitcher has a
strip to correlate, so it needs to be comfortably wider than the stage's own error
and wide enough to contain real features. At 2048 voxels, ten per cent is 204
voxels, which is generous. Well below about five per cent a stage error can exceed the
overlap itself, and then the strip cannot do its job.

##### How flexible is it, and should we fix one number?

Measured, for a trim of up to one per cent:

| asked for | 2048 sensor gives | 2304 sensor gives |
| ---: | ---: | ---: |
| 5% | 6.25% | 5.56% |
| 7.5% | 7.69% | 7.41% |
| **10%** | **10.00%** | **10.00%** |
| 12.5% | 12.50% | 12.50% |
| 15% | 15.38% | 14.81% |
| 20% | 20.00% | 20.00% |
| 25% | 25.00% | 25.00% |

Ten, twelve and a half, twenty and twenty-five are hit **exactly**; seven and a
half and fifteen land within four tenths of a per cent. Only five per cent misses,
because a 64-voxel floor on the chunk makes the smallest possible overlap 128
voxels, which is 6.25% of a 2048 frame. The rigid case is a small frame: a
512-wide confocal scan comes out at 25% whatever is asked, since it is only eight
chunks across.

##### Decided: three choices, not a number

The maintainer would rather the workflow allowed a short list than a free number,
and that is the better design — not merely simpler. Each option on a list can be
checked against the frame size **at run setup**, so the writer can promise the run
will be pointed at rather than copied. A free-form percentage cannot be
pre-validated: somebody types 13% on a 512 frame and finds out at the end of five
terabytes that it was written twice.

The arithmetic picks the list. **Nought, ten and twenty per cent are hit exactly
on both real sensors; fifteen is not** — 2048 gives 15.38% and 2304 gives 14.81%.

| choice | when to use it | imaging cost |
| --- | --- | --- |
| **none** | a survey you will look at and pick targets from, and never stitch | 1.00 × |
| **ten per cent** — the default | ordinary mosaics, where the specimen fills the field | 1.23 × |
| **twenty per cent** | sparse specimens, light-sheet volumes, anything to be stitched properly | 1.56 × |

**Ten is the default** because it is the cheapest overlap that reliably works when
there is signal across the whole field, and because at 0.35 µm a voxel it is about
71 µm of shared strip — far more than any decent stage's error.

**Twenty is the escape**, and it answers the failure that actually bites: a sparse
specimen where a ten per cent strip contains nothing to correlate. That is a
property of the sample rather than of the stage, so no amount of stage accuracy
fixes it. It is also Fiji's own default. Light-sheet volumes take it for the same
reason.

**None deserves its place on the list.** Many overview scans exist to find targets
rather than to make a publication mosaic, and paying a quarter again in imaging
for an overlap nobody will stitch is waste. It should be labelled for what it is —
*for finding things, not for making a picture* — so that nobody chooses it and
then asks for a stitch.

**Fifteen is left off** deliberately: it sits between two options that already
bracket the useful range, it is not exactly achievable on either sensor, and three
choices are far easier to explain to a biologist than four.

##### But the names are rigid and the numbers are derived

Checking the three options against every frame width from 512 to 5000 turned up
something that would have bitten:

| option | widths that cannot honour it | worst error |
| --- | ---: | ---: |
| none | **0** | — |
| ten per cent | **594** of 4,489 | 18.6% |
| twenty per cent | 142 of 4,489 | 8.6% |

And the failures are not exotic. **A 1024 frame cannot do ten per cent**: with a
64-voxel floor on the chunk it is sixteen chunks across, so the finest available
overlap is two chunks — 128 voxels, or 12.5%. A confocal set to 1024 is entirely
ordinary.

So the **names** are fixed and the **numbers** are worked out per frame at setup:

| frame | none | modest | generous |
| --- | --- | --- | --- |
| 2048 | 0% | 10.0% | 20.0% |
| 2304 | 0% | 10.0% | 20.0% |
| 4096 | 0% | 10.0% | 20.0% |
| **1024** | 0% | **12.5%** | 20.0% |

The operator chooses an intent — none, modest, generous — sees the number it
resolved to, and the writer guarantees the run will be pointed at rather than
copied. It is the same pattern as everything else here: rigid where a person
chooses, derived where arithmetic can do better than a person.

A literal "10%" written into the workflow would have failed silently on a 1024
scan — refused, or written twice, and discovered at the end of five terabytes.

##### What each layer does, at run setup

The workflow **offers** the choices; storage **says what they resolve to**. That
distinction is the whole protection: a workflow that named percentages could name
one this frame cannot honour.

1. The workflow asks the driver for the frame shape — `Session.get_info()`.
2. It asks `zmart_storage` what `none`, `modest` and `generous` come to *for that
   frame*.
3. It shows the operator the three options with their real numbers — *"none ·
   modest (12.5%) · generous (20%)"*.
4. The operator picks an intent.
5. The workflow lays the centres out on the resulting step, and hands the chunk to
   the writer.

The workflow owns the choice and the raster. Storage owns what is possible. The
driver owns the fact. None of them needs to know the others' business, and the
workflow never names a percentage the frame cannot honour, because it never names
a percentage at all.

That is also what makes it safe to be rigid. The list is short and fixed in
*intent*, so an operator has three things to understand, while the arithmetic
underneath adapts to whatever camera or scan format turns up.

 Ten earns the default — it is
exactly achievable on every real sensor and it is the number microscopists expect —
but it has to stay adjustable, because a light-sheet often wants fifteen or twenty
for reliable stitching through a volume, a fast survey that will never be stitched
should not pay for overlap it will not use, and a 512 format cannot do better than
twenty-five however politely it is asked.

Whichever is chosen, the writer reports what it actually managed: *"overlap 10.0%
(230 of 2300 voxels)"*. The same shape as every other decision here — the operator
chooses in the terms they think in, and the writer answers with what it could do.

**And it is per axis.** Most runs overlap across the specimen and not at all in
depth, and an axis with no overlap is trimmed by nothing and costs nothing. `z`
does not have to follow `y` and `x`.

#### How far does this constraint actually reach?

It is worth saying plainly, because "the tile must be a whole number of chunks"
sounds like it reaches across the whole project, and it does not. It binds **the
tiles inside one acquisition type**, and nothing else.

| | must they agree on a format? |
| --- | --- |
| Two microscopes — a Stellaris and a mesoSPIM | **No.** They are never the same run. |
| Two acquisition types in one experiment — a 512 overview and a 1024 target scan | **No.** Each has its own folder, its own view, its own chunk size and its own voxel size. |
| Two positions inside one acquisition type | **Yes** — and they already must, because the view hands their files over untouched. This is not a new rule. |

The chunk size is written into every array's own metadata; there is no
project-wide constant that has to divide everything. So different microscopes
having different formats costs nothing at all — each run declares the chunk that
fits the format it was acquired with.

And within one run the format is fixed by the acquisition anyway. Nobody changes
the scan format halfway through a raster.

**The worst case is today's behaviour.** If a run's format genuinely cannot be
made to fit any chunk, it falls back to being written twice — which is what
happens right now for *every* overlapping run, whatever its format. So nothing
gets worse than it is; some runs get much better. That is the honest measure of
this change, and it is why the awkward formats are an annoyance rather than a
threat to the arrangement.

#### The decision: derive the chunk from the format, and stop asking

Everything above makes this sound like a burden on whoever sets up a run. It is
not, and the reason is one fact that is easy to miss:

> **A zarr chunk does not have to be a power of two.** 73 is as valid a chunk as
> 128.

So the format never has to be standardised. The **chunk is derived from the
format**, at run setup, by the writer — and the operator is never asked about it
at all. They say what overlap they want, in the ordinary way a microscopist
thinks about it, and the writer picks the chunk and the exact overlap together:
the pair that divides the tile and lands nearest what was asked, preferring a
larger chunk when two are equally close.

Asking for "about 10%", here is what that gives on real sensors:

| sensor across | chunk chosen | chunks per tile | overlap | which is |
| ---: | ---: | ---: | ---: | ---: |
| 512 | 64 | 8 | 128 | 25.0% |
| 1024 | 64 | 16 | 128 | 12.5% |
| 2048 | 128 | 16 | 256 | 12.5% |
| **2304** (Hamamatsu Orca) | 128 | 18 | 256 | **11.1%** |
| 2560 | 128 | 20 | 256 | **10.0%** |
| 4096 | 64 | 64 | 384 | 9.4% |
| 1608 | 67 | 24 | 134 | 8.3% |
| 2044 | 73 | 28 | 146 | 7.1% |
| 1200 | 75 | 16 | 150 | 12.5% |

Every one of them works, including the awkward ones — and 2304, the size that
prompted the worry, lands **closer to ten per cent than 2048 does**. The odd
chunk sizes in the last few rows are not a compromise; they are ordinary zarr.

Two honest notes on the table. A small tile cannot have a fine overlap grid —
512 across can only manage 25% — but a 512 tile is cheap, so the extra imaging
costs little. And where a very small chunk is chosen (67, 73) the run leaves more
files behind; if that matters on a particular filesystem, the writer can be asked
to prefer a larger chunk and accept an overlap further from the request — 2044
would then take a 146-voxel chunk and a 14.3% overlap.

**So the decision is: nobody chooses a format, and nobody chooses a chunk.** The
camera decides the format, the operator asks for an overlap in per cent, and the
writer works out the rest and says what it picked. The only thing that needs
writing down is that sentence.

#### Can the chunk be changed afterwards? No — and that is why it is derived

A chunk is not a description of the data, it **is** the file on disk. Changing the
chunk size repartitions every byte, so it is a full rewrite of the run, not an
edit to its metadata. That makes it the one decision that genuinely cannot be
deferred.

It is worth keeping the two straight, because they feel similar and are not:

| changing this, after a run is written | costs |
| --- | --- |
| the OME-Zarr version, 0.5 → 0.6 | **metadata only** — one `zarr.json`, chunks untouched |
| where the image says it sits, or its channel colours | **metadata only** |
| adding `labels`, `tables`, another view | **new files beside the old** — nothing existing is touched |
| **the chunk shape** | **a full rewrite** — every byte read, repartitioned and written again |
| the compression | **a full rewrite** |

On five terabytes a rewrite is hours of reading and writing and twice the disk
while it runs. It is something you do once, deliberately — converting a foreign
dataset that arrived badly chunked, say — and never casually.

**Which is exactly why the chunk is derived at run setup rather than chosen
later.** Everything needed to work it out is already known before the first tile
is written: the run declares its tile shape, and the operator has said what
overlap they want. So the writer has both facts in hand at the moment it must
decide, and there is nothing to postpone.

The practical rule that follows: **`start_a_run` should take the wanted overlap as
a fraction and work the chunk out, instead of taking `piece=128` and hoping it
fits the camera.** That is a small change to one signature, and it is what turns
"which chunk size?" from a question anybody has to answer into one nobody is asked.

#### Which layer decides — and why the driver must not

Microscopes do not hand us OME-Zarr; we write it. So the question is not how to
cope with somebody else's choice, it is which of our own layers gets to make it.
The overlap already lives in the **workflow**, which is correct and should stay
that way: an overlap is a property of the acquisition *plan*, not of the
instrument. A stage does not have an overlap; a raster does.

That leaves each layer with exactly one thing to know:

| layer | knows | never hears about |
| --- | --- | --- |
| **driver** | the frame shape in voxels, the voxel size, and on a point scanner which formats it can be set to | chunks, overlap, storage |
| **controller** | passes those through, microscope-agnostic | chunks, overlap, storage |
| **workflow** | where the tile centres go, hence the overlap | how a chunk is worked out |
| **`zmart_storage`** | how to turn a tile shape and a wanted overlap into a chunk | anything about instruments |

**Do not instruct the driver to use a chunk size.** Two reasons, and the second is
the decisive one:

- A chunk is a storage idea, not an instrument idea. Teaching five drivers about
  it means five drivers to change the next time the storage layout moves.
- The driver *cannot* work it out even if told to, because it does not know the
  raster. Only the workflow knows how far apart the centres will be.

**What the workflow needs instead is one small function**, asked *before* it lays
out the raster — because the step it chooses has to be one the chunk grid allows:

```python
grid = zmart_storage.plan_a_grid(tile_shape=frame_shape, wanted_overlap=0.10)
# -> chunk, overlap in voxels, the fraction that really came out, and the step
```

The workflow takes `frame_shape` from `Session.get_info()`, calls this, lays the
centres out on `grid.step`, and hands `grid.chunk` to the writer. Nothing new is
coupled: the driver still knows nothing about storage, the controller still knows
nothing about storage, and the workflow gets a straight answer before it commits
to anything.

**The one thing worth saying to a driver** is a *scan format*, and only on a point
scanner where the format is actually settable — "scan 2048 rather than 2044". That
is an instrument instruction in an instrument's own vocabulary, and it belongs in
the driver. But it is a nicety rather than a requirement: with the chunk derived
per run, 2044 already works.

#### When the vendor writes the files, not us

For a good many camera-based systems the acquisition software writes its own
files and we never see a frame in flight. That sounds like it takes the chunk
decision away from us. It does not, and the reason is the one this section opened
with: **nobody hands us OME-Zarr, so we are always the ones writing it.**

Two cases, and both already exist in this repository:

- **ZMART drives the acquisition** and receives frames, so it writes the
  OME-Zarr directly. The chunk is chosen at run setup, as described above.
- **The vendor writes first** — LAS X native autosave, a mesoSPIM run, anything
  with its own format — and we convert afterwards.
  `acquisition/materialize.py` already does exactly this, reading a source plane
  and writing a canonical ZMART file. Its target today is OME-TIFF; pointed at
  OME-Zarr instead, **the conversion is the moment the chunk is chosen**, and
  everything above applies unchanged.

So what we genuinely do not control costs us less than it seems:

| not ours to choose | what it costs |
| --- | --- |
| the sensor size | nothing — the chunk is derived from whatever it is |
| the vendor's own file format | one conversion, which we were doing anyway |
| **a vendor handing us OME-Zarr already chunked** | the only real case: either accept it and fall back to copying, or rechunk, which is a full rewrite |

**Converting is not free and should be budgeted rather than discovered.** A run the
vendor wrote as five terabytes of TIFF is a five-terabyte read and a
five-terabyte write to bring across, once. That is the price of the format itself
rather than of anything decided here, and it is paid at a moment of our choosing —
after the specimen is off the stage — rather than during the acquisition.

And the asymmetry is the right way round. For the runs ZMART acquires itself —
the long ones, the five-terabyte ones, the ones where a second copy would really
hurt — we hold the pen from the first frame. The awkward case is data somebody
else acquired, which is exactly where a one-off conversion is an acceptable price.

#### Point scanners, which can scan almost any format

A camera gives one size and that is that. A confocal is a point scanner: the
operator sets the scan format, and 512, 1024, 2048, non-square shapes and odd
zoom-cropped regions are all ordinary choices. So "the tile is a whole number of
chunks" is a much sharper constraint on a confocal than on a camera, and it is
fair to ask whether we should simply insist on one format — 2048 × 2048 — and be
done with it.

**No, and it would be the wrong kind of rule.** A scan format is a scientific
choice, not a preference: it sets the pixel size, the dwell time, how fast a frame
comes back and how much the specimen is bleached. Insisting on 2048 × 2048 would
cost a live-cell experiment real photons and real time to save us an
inconvenience. The rule has to bend to the microscope rather than the other way
round.

**Three rules instead, in order of who they bind.**

1. **One format per acquisition type, not one per project.** Every position in a
   run must already be written the same way, so the format is fixed *within* a
   run regardless. An overview at a fast 512 and a target scan at 1024 with more
   zoom are two acquisition types, each internally consistent, and that is
   exactly the arrangement §1 already describes.
2. **The chunk is derived from the format**, as just described, per run and per
   axis. A 1024 × 256 strip is as workable as a square.
3. **When a format genuinely will not fit, say so at setup and write twice.** An
   odd zoom-cropped region — 700 voxels across, say — divides by nothing useful,
   and no chunk choice makes its tiles handable-over whole. That run falls back to
   the copying writer, which is correct and costs about twice the disk. What
   matters is that the operator is told **when the run is being set up**, in the
   same helpful voice the writer already uses for overlaps: *this format cannot be
   handed over whole, so the run will be written twice and take about twice the
   space; a format of 640 or 768 would avoid it.* Discovering that at the end of a
   five-terabyte run is the failure worth designing against.

### 8.2 A view is only metadata, so write more than one

Once trimming is done by pointing, a view costs a few hundred bytes and no pixels
at all. That makes the show-the-overlap question stop being a decision taken at
write time:

```text
overview.ome.zarr/          the trimmed view — tiles butt, no seam, nothing shown twice
overview-full.ome.zarr/     the same positions, every chunk pointed at, overlap visible
  positions/                ... shared; neither view holds pixels
```

The operator picks a view instead of the run being written one way. The trimmed one
is the default because it is what you want to look at; the full one is what you open
when you are checking the stage, judging an overlap, or wondering whether a seam is
real. Neither costs anything to keep.

This is also the honest place for the later-wins problem that
`viz_studio/INTEROP.md` §3 records: a hard seam and an intensity-threshold shader
that cannot tell "never imaged" from "imaged and genuinely dark". With the trimmed
view there is no overlap to blend, so the shader stops having to guess.

### 8.3 Give a segmentation its own view, or the viewer falls over the same cliff

**The problem, which is the original problem wearing a different hat.** Analysis
writes `labels/nuclei` inside each position, which is right. But a run of ten
thousand positions then has ten thousand label images, and Neuroglancer builds a
drawing layer per source — the exact cliff the view was invented to avoid. Showing
a segmentation over a whole run would undo everything the view achieved.

**The answer falls straight out of what already exists.** A label is an ordinary
multiscale array, so it can have a view of its own, pointing at the positions'
labels the same way the image view points at their pixels:

```text
overview.ome.zarr/
  labels/
    nuclei/            a view over the positions' labels — one drawing layer
      0/ 1/ 2/
  positions/
    overview_pos00000.ome.zarr/
      labels/nuclei/   the real label, written by the pipeline
```

**This was checked rather than assumed.** A label written by ngio's `derive_label`
comes out with the image's own y and x chunking, the image's per-resolution scale
*and translation* — so it already sits in the right place on the stage — the
standard `{"labels": ["nuclei"]}` listing on the group, `uint32` values, and axes
`t, z, y, x` with the colour axis dropped, which is correct because a segmentation
is one number per voxel rather than one per channel.

Three rules make the pointing work, and all three are worth writing into the
pipeline contract rather than hoping for:

- **A label keeps its image's chunking.** ngio does this already; it must not be
  overridden.
- **A label keeps its image's number of levels.** ngio derives as many as the image
  has, so an image with one level gives a label with one — which is fine, but a
  label view can only point at the levels that exist.
- **Label numbers are unique across the whole run.** This is the one that will
  otherwise bite silently: if each position numbers its cells from one, then cell
  7 in one tile and cell 7 in its neighbour become *the same object* the moment
  they are drawn in one layer, and they will be selected, coloured and counted
  together. Offsetting each position's numbers by its index — position 42's cells
  starting at 42,000,001, say — costs nothing and prevents an error nobody would
  think to look for.

### 8.4 One table for the run, beside the tables for the tiles

Per-position tables are right for writing: a pipeline finishes a position and puts
its measurements there, where they belong with the pixels. They are wrong for
asking, because the only questions worth asking are about the run — how many cells,
which are brightest, where the interesting ones are — and answering one means
opening ten thousand small tables.

So keep the per-position tables and add a **run-level table on the view**, holding
the same rows with a column saying which position each came from. It is appended
to as positions finish, so it costs a write per position and no re-reading, and it
is what the discovery step and the operator's plots actually query.

### 8.5 A tile that moves over time is not one image with a time axis

**The requirement.** A timelapse whose tiles stay put is easy and is what the
writer does today. A **tracking** run is different: the microscope follows
something, so the same tracked object is imaged at a different place at each
timepoint. The run has to be able to say *where each tile was at each moment*.

**What the writer does today cannot express that.** `start_a_run(frames=N)`
declares the time axis up front, and a position imaged again at a later moment
writes into the image it wrote into the first time — which carries one
translation for all time. The arrangement has "a position stays where it was"
built into it.

**What 0.6 offers, and its limit.** RFC-5 allows a `translation`, `scale`,
`affine` or `rotation` to be stored *as a Zarr array* at a `path` rather than as
literal numbers, so its value can vary along an axis; and `displacements` and
`coordinates` give whole fields. That is genuinely how the specification means
drift correction to be written down.

But it will not be drawn. Neuroglancer's 0.6 reader handles `identity`, `scale`,
`translation`, `rotation`, `mapAxis`, `affine` and `sequence`, each read from
literal JSON numbers. It has no `byDimension`, no `displacements`, no
`coordinates`, and no reading of a transformation from an array. So a
time-varying transformation can be *stated* at 0.6 and shown by nothing.

**So the answer is a structural one, and it works today in 0.5:**

> If a tile can move, a new moment is a new **image**, not a new index along a
> time axis. Keep the time axis for a tile that stays where it is.

A tracking run then writes one ordinary OME-Zarr image per observation, each
stating its own place with a plain scale and translation that every reader
already understands. Nothing waits on 0.6, nothing waits on Neuroglancer, and the
arrangement is not a workaround — it is a more truthful description of what
happened. A tile that moved is not one thing photographed repeatedly from one
place; it is a sequence of observations, each somewhere else.

What follows from it:

- **The name gains the moment**: `<name>_pos<NNNNN>_t<TTTTT>.ome.zarr`, with the
  same rule as before — the numbers are indices, and where a tile *was* is stated
  inside the image.
- **The view stays one image per moment.** A view already points at whichever
  tiles it is told to; pointing at the tiles belonging to one timepoint is the
  same operation, so the viewer is handed one source per moment rather than one
  per tile.
- **A table says which images are the same tracked object.** That is the thing a
  tracking analysis actually asks for, and it belongs beside the run's other
  tables (§8.4).
- **It maps straight onto a scene when 0.6 arrives.** A scene is a group of
  images each with its own transformation, which is exactly what this produces —
  so nothing written this way has to be rewritten later.

The cost is more images, and it is not much of a cost: a run already holds
thousands, and an image that holds one tile is small and cheap to declare.

**Keep the time axis for what it is good at.** A position that genuinely stays
still through a timelapse should still use `t` inside one image — fewer files,
and the moments belong together. The rule is about *movement*, not about time.

### 8.6 Say where a tile is by its centre; store its corner

**The observation.** A microscope does not know where a tile's corner is. It knows
where the stage was sent, and the field of view is centred on that point. The
workflow already thinks this way — `discovery.py` passes `center_frame_um` around
and converts through `overview_pixel_to_frame(..., image_center_frame_um=...)`.
Only the storage layer speaks in corners, and every place the two meet is a place
to get a half-tile wrong.

**But the file must keep storing the corner.** OME-Zarr's `translation` applies to
the array's first element, so it *means* the corner of voxel zero. Writing a centre
there would not be a different convention, it would be a false statement, and every
reader in the world would place the tile half a tile away from where it belongs.
This is not the same question as the corner-versus-middle-of-a-voxel choice in
section 2, which is about half a *voxel*; this is about half a *tile*.

**So: speak centres, store corners, and convert in exactly one place.**

```
corner = centre − (tile shape in voxels ÷ 2) × voxel size
```

The conversion is exact rather than approximate, and it is worth saying why:
§8.1 already requires a tile to be a whole number of chunks across, so a tile's
size in voxels is always even, and half of it is a whole number of voxels. There
is no rounding and no half-voxel to worry about.

**What it buys, beyond fewer mistakes.** The acquisition stops having to reason
about overlap at all. It says where the centres go; the overlap is then simply the
tile size minus the spacing between centres, which is exactly what
`Trimming.of(tile_shape, tile_step)` already takes. Overlapping edges are not
something anybody arranges — they fall out of imaging a tile-sized field at
centres closer together than a tile.

That also makes the operator's side of it honest. "Image every 1.8 mm with a 2 mm
field" is a sentence a microscopist can check against the stage. "Put the corners
at these coordinates" is one they cannot.

### 8.7 Worth exploring: one file per position, per level

*Status: an idea with one measurement behind it. Not decided.*

**The idea.** Push bundling to its natural end and make each position's level a
**single file**. Windows then never sees more than a few tens of thousands of
files however large the run, while the chunks *inside* each file stay small, so
the viewer still fetches thirty-two kilobytes at a time rather than eight hundred
megabytes.

| bundle is… | files, for 10,000 positions × 100 planes × 5 levels |
| --- | ---: |
| nothing — a chunk is a file | ~20 million |
| one tile **plane** | ~600,000 |
| **one whole tile level** | **~50,000** |

**First, a premise to correct**, because it is a natural thing to assume: keeping
the positions *outside* a containing OME-Zarr does not help. Twenty million chunk
files is twenty million whether they sit inside `overview.ome.zarr/positions/` or
beside it. Directory structure costs nothing; **chunk-per-file** is the problem,
and only bundling removes it.

**And the measurement that makes this an open question rather than a
recommendation.** Writing thirty-two planes into one array, one plane at a time as
a camera would deliver them:

| | files left | time |
| --- | ---: | ---: |
| shard = one plane | 33 | **565 ms** |
| shard = whole tile | **2** | 2,290 ms — **four times slower** |

Writing into a large shard a plane at a time is a read-modify-write: each plane
rewrites more of the shard than the last, so the penalty grows with the number of
planes per shard. On a light-sheet stack of a few hundred planes it would be far
worse than four times.

**So the thing to explore is buffering.** Accumulate a whole tile in memory and
write its shard once, which should give the file count *and* the speed. What has
to be found out:

- **Does buffer-then-write actually recover the time?** It should, but it has not
  been measured.
- **How much memory does it cost?** A 2048 × 2048 × 100 tile in `uint16` is 800 MB
  in flight. That may be fine on a microscope computer with 64 GB and impossible
  on one with 16.
- **What does it do to live viewing?** A tile buffered in memory is a tile the
  operator cannot see yet. Watching a run fill in is the point of the viewer, so a
  whole-tile buffer may trade away something worth more than the file count.
- **Does a large shard cost more to read?** The server reads an index and seeks;
  whether that index grows expensive at whole-tile size is unmeasured.

**Until it is explored, one tile plane per bundle is the safe default** — 600,000
files on a five-terabyte run, written at full speed, and every plane visible the
moment it lands.

**One thing this does not change.** The view is still needed, and it is what
actually delivers the requirement that started this: ten thousand positions,
snappy, in Neuroglancer. That comes from handing the viewer one source rather than
ten thousand — measured flat from a hundred tiles to six thousand four hundred,
against twenty-four frames in five seconds for a thousand separate ones. Bundling
solves the filesystem; the view solves the viewer; neither substitutes for the
other.

### What these have in common

They all move work from *copying pixels* to *saying something about pixels that
already exist*. The trim becomes metadata, the show/hide choice becomes metadata,
the segmentation overlay becomes metadata, and the run summary becomes one small
table instead of ten thousand reads. That is the same principle the view was built
on, applied to the three things that were left out of it.

---

## 9. Changes still to make

In the order I would do them. The first four are corrections; the rest are the
changes of section 8, which are larger and should follow rather than lead.

1. **Per-dataset translation for positions.** Already written on
   `claude/ngff-translation-per-dataset`; needs merging, plus a guard so the view
   is not moved twice. Nothing else on this list matters until this is done,
   because until then no position we write can be opened by ngio, `ngff-zarr` or
   `multiview-stitcher`.
2. **`tables/owned_ROI_table` in every tile.**
3. **0.5 as the default in every writer**, not only `start_a_run`.
4. **An ngio test beside the `ngff-zarr` one**, so a validation failure is caught
   the day it is introduced rather than months later.
5. **Chunk-aligned trimming** (§8.1), which removes the second copy from every
   overlapping run and collapses two arrangements into one.
6. **A label view** (§8.3), with globally unique label numbers, so a segmentation
   can be shown over a whole run at all.
7. **A run-level table** (§8.4) and a second, untrimmed view (§8.2).
8. **A new image per moment for tiles that move** (§8.5), which is what a tracking
   run needs and what no viewer will draw from a time-varying transformation.
9. **Centres in, corners on disk** (§8.6), converted in one place.
10. **Write 0.6 for acquisitions 0.5 cannot describe** — a deskewed light-sheet
   run, multiple views related by a rotation, a tile that moves between
   timepoints. Neuroglancer reads 0.6 images already, and the upgrade back and
   forth is metadata-only.
11. **Watch `ngio.NgffVersions` for `"0.6"`**, then write the scene alongside the
   view and find out whether a run opens elsewhere without our viewer.

Deliberately not on the list: adopting the high-content-screening plate layout,
and rearranging anything to suit it. The companion document explains why.
