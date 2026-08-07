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

*Status: written and running; the default version is change number three.*

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

## 8. Five changes the whole picture argues for

*Status: none of these are built. This section is the answer to "given overlap,
efficient viewing, efficient analysis, and label layers — what should change?"*

Taken one at a time the earlier sections each suggest a small correction. Taken
together they point at four changes, and the first is much larger than it looks.

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

**The change.** Require the overlap to be **an even whole number of chunks**. Then
half of it is a whole number of chunks, a trimmed tile still begins and ends on the
chunk grid, and trimming becomes *pointing at fewer chunks* — which costs nothing.

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

### What these have in common

The first four move work from *copying pixels* to *saying something about pixels that
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
9. **Write 0.6 for acquisitions 0.5 cannot describe** — a deskewed light-sheet
   run, multiple views related by a rotation, a tile that moves between
   timepoints. Neuroglancer reads 0.6 images already, and the upgrade back and
   forth is metadata-only.
10. **Watch `ngio.NgffVersions` for `"0.6"`**, then write the scene alongside the
   view and find out whether a run opens elsewhere without our viewer.

Deliberately not on the list: adopting the high-content-screening plate layout,
and rearranging anything to suit it. The companion document explains why.
