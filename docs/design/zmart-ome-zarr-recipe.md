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

---

## 4. How the pixels are stored

*Status: written and running; the default version is change number three.*

| | decided | why |
| --- | --- | --- |
| OME-Zarr version | **0.5** (zarr v3) by default; 0.4 on request; **0.6 when the acquisition needs a transformation 0.5 cannot express** — see section 6 | 0.5 is read by everything today and can bundle chunks; 0.6 is the only way to state a deskew, a rotation between views, or a place that changes with time |
| chunk | `(1, 1, 1, piece, piece)`, with `piece` **derived from the tile shape and the wanted overlap** at run setup — see §8.1 | one plane per piece, so showing a single plane never fetches its neighbours; and the chunk cannot be changed afterwards without rewriting every byte, so it must be right the first time |
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

**Take 12.5% and do not chase 10%.** Two reasons:

- **It costs almost nothing.** Covering a fixed area needs `1/(1−v)²` times as
  many tiles, so ten per cent costs 1.235× and twelve and a half costs 1.306×.
  Moving from one to the other is about **6% more tiles, time and disk** — a few
  minutes on a long run.
- **Chasing 10% means shrinking the chunk, and that is the worse trade.** Getting
  to 9.4% needs 32-voxel chunks, which is sixteen times as many files and sixteen
  times the browser's per-piece bookkeeping — and `canvas.py` already notes that a
  piece costs a few milliseconds whatever its size, with only about six fetched at
  a time. A viewer made slower to save six per cent of disk is a bad bargain.

**What the overlap is actually for sets the floor.** It exists so a stitcher has a
strip to correlate, so it needs to be comfortably wider than the stage's own error
and wide enough to contain real features. At 2048 voxels, 12.5% is 256 voxels,
which is generous. Well below about five per cent a stage error can exceed the
overlap itself, and then the strip cannot do its job.

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
