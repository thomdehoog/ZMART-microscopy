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

---

## 4. How the pixels are stored

*Status: written and running; the default version is change number five.*

| | decided | why |
| --- | --- | --- |
| OME-Zarr version | **0.5** (zarr v3) by default; 0.4 on request; **0.6 when the acquisition needs a transformation 0.5 cannot express** — see section 6 | 0.5 is read by everything today and can bundle chunks; 0.6 is the only way to state a deskew, a rotation between views, or a place that changes with time |
| chunk | `(1, 1, 1, piece, piece)`, `piece` = 128 by default | one plane per piece, so showing a single plane never fetches its neighbours |
| bundling (sharding) | full-size copy only, when asked for | a long run otherwise leaves millions of small files, which Windows and most backup software handle badly |
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

## 8. Changes still to make

In the order I would do them:

1. **Per-dataset translation for positions.** Already written on
   `claude/ngff-translation-per-dataset`; needs merging, plus a guard so the view
   is not moved twice. Nothing else on this list matters until this is done,
   because until then no position we write can be opened by ngio, `ngff-zarr` or
   `multiview-stitcher`.
2. **`tables/owned_ROI_table` in every tile.**
3. **0.5 as the default in every writer**, not only `start_a_run`.
4. **An ngio test beside the `ngff-zarr` one**, so a validation failure is caught
   the day it is introduced rather than months later.
5. **Write 0.6 for acquisitions 0.5 cannot describe** — a deskewed light-sheet
   run, multiple views related by a rotation, a tile that moves between
   timepoints. Neuroglancer reads 0.6 images already, and the upgrade back and
   forth is metadata-only.
6. **Watch `ngio.NgffVersions` for `"0.6"`**, then write the scene alongside the
   view and find out whether a run opens elsewhere without our viewer.

Deliberately not on the list: adopting the high-content-screening plate layout,
and rearranging anything to suit it. The companion document explains why.
