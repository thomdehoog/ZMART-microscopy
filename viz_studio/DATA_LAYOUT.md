# How a smart-microscopy run should be stored, and why

This records the decisions we reached about how an experiment's images are written
to disk and how the viewer presents them. It is written down because these are
the kind of choices that are cheap to make now and expensive to change later:
once a few months of experiments are stored one way, that way is the standard
whether it was right or not.

Every claim about cost in this document was measured rather than assumed. The
script `measure_canvas.py` next to this file reproduces the measurements, so if
the data grows or the engine changes you can check whether the reasoning still
holds instead of trusting a document written in July 2026.

## The decisions, in short

Everything below is the reasoning. This is the conclusion, for anyone who needs it
without the argument.

**On disk.** One store per position. Each holds one image as `t, c, z, y, x`, its
shrunk-down copies, and its place on the stage as a `translation` in its own metadata.
Masks live inside the store they describe, under `labels/`. Folders stay flat — there
is no container folder per acquisition type, because the engine cannot see one and
something of ours would have to list its contents anyway.

**How things grow.** A new position is a new store. A new frame is written into the
store that already exists, whose length in time was declared generously up front. A new
mask is a folder under `labels/`. Nothing that is already being read ever changes shape.

**On screen.** Rows are gathered under their acquisition type, one row per channel — and
a mask is simply another row, drawn with its own controls. Every position of one
acquisition type feeds the same row, and they become one picture because the engine
places each by its translation. What the panel shows is therefore acquisition types and
channels; the fact that a position is a separate folder never surfaces.

**Getting data in, two ways.** While a run is producing data, the control application
says "this position is ready" and the viewer hands the engine one more address. For data
that is finished, point the viewer at a folder: it finds what is there, shows it, and
then stops asking, because nothing can change. New *frames* need no announcing at all —
the engine fetches them when you go and look, since it already has the address.

**The rule behind all of it.** *Add alongside; do not reshape.* And a position's place in
the world lives in its metadata — not in a grid, not in a filename, not in the shape of
the folders.

### What is deliberately still open

**Who writes the OME-Zarr.** The mesoSPIM writes its own, and our driver copies the
frame files it produced rather than writing zarr itself. So a writer is either a
conversion step after acquisition or a change to what the driver writes. That has not
been decided, and it changes what gets built.

**Where measurements go.** A table of intensities per object, or a classification per
target, is neither pixels nor geometry, so neither a store nor the annotation file beside
it is the right home. This will come up the first time somebody classifies pixels, and it
deserves its own decision rather than being squeezed into one of the above.

## What the viewer is, and what it is not

The viz-studio is a **viewer**. Its job is to show large, three-dimensional,
multi-channel, changing images well, and to let you mark places in them.

It deliberately does **not** talk to the microscope. Driving the stage, starting
an acquisition, deciding what to image next — all of that belongs to the control
application. The two meet at a file: the viewer saves the targets you draw to
`zmart-annotations.json` beside the image data, and the control application reads
that file.

Keeping them apart buys something concrete. The viewer can be opened on any data,
on any machine, by anyone — a colleague looking at last week's run, a student on a
laptop — with no possibility of it moving an instrument. A test asserts that no
endpoint exists which could, so the separation cannot be undone by accident.

## The shape of an experiment

A run has **acquisition types**: a prescan, an overview, a target scan, and
whatever else an experiment invents. Each type is acquired at one or more
**positions** on the stage, and each acquisition produces an image with
**channels**, **z planes**, and — over the course of the run — **timepoints**.

In the standard OME-Zarr ordering that image is `t, c, z, y, x`.

## Decision 1: one store per position, carrying its own place in space

An OME-Zarr image can state where it sits in physical space: a `translation`
alongside the voxel size in its own metadata. A viewer reads that and puts the image
where it belongs, and so does any other tool that understands the format.

That one field is what makes this decision simple. **A position does not need to be
stored in any shared grid — it needs to carry its own x, y, z.** Everything else
follows:

- **No canvas has to be declared**, because nothing shares an array. An experiment
  need not know the region it will cover, which was the objection that started this
  whole question.
- **No alignment rule.** Since no two acquisitions ever write to the same file, the
  concurrent-write hazard described further down cannot arise at all.
- **Overlap is preserved**, so stitching still has both views of a shared region to
  compare. This is the one that rules out the alternative for raw data.
- **A position discovered mid-run just appears.** A target scan the workflow decided
  on a minute ago writes its own store with its own translation, and nothing already
  written has to change.

The cost is that assembling the specimen happens when it is displayed rather than
when it is written, so the viewer opens many stores instead of one. That is a
question of speed, and it has been dealt with where it was slow: counting a
timelapse's frames is now incremental, the answer to "what is open" is kept against
a cheap fingerprint rather than rebuilt, and the paths that grew with the square of
the number of stores are linear. Finished data can be opened in static mode, which
stops the looking altogether.

A "store" is one OME-Zarr, which is a *folder* on disk rather than a single file.
One store holds one image, its shrunk-down copies, and a little metadata.

**Write one store per acquisition**, named the way the driver already names things
— the acquisition type, then the position:

```
run_2026-07-26/
  overview_pos001.ome.zarr        each one t,c,z,y,x, carrying its own
  overview_pos002.ome.zarr        place on the stage in its metadata
  targetscan_cell042.ome.zarr
```

This is what `canonical_stem()` in the driver already produces, so nothing about
the writing side has to change.

### Why not gather each acquisition type into one big image

There is a real alternative, and it was seriously considered: give each acquisition
type a single image the size of the whole stage area — a "canvas" — and write each
position into its proper place inside it. It has one genuine advantage, and it was
measured.

Alongside the full-resolution image, an OME-Zarr keeps progressively smaller copies
— half size, quarter size, and so on. That is what lets a huge image feel light:
zoomed out, the viewer reads a small coarse copy instead of hauling every pixel
across. With one canvas those copies cover the **whole mosaic**, so seeing
everything at once costs almost nothing:

| On an 8192 × 8192 canvas holding nine tiles | Chunk files fetched |
|---|---|
| The whole mosaic, zoomed out | **12** |
| A single tile at full resolution | **6** |

Looking at the entire mosaic cost about the same as looking at one tile, whatever
the canvas size. And it was affordable, because **a piece of image nobody wrote
does not exist on disk**: that canvas declared 1.00 GiB and occupied 50 MiB, 4.9%
of itself, with the nine tiles written.

**So why not do it?** Because it has to be declared before anything is imaged, and
that is a promise a smart-microscopy run cannot make. A tracking workflow does not
know where it will end up. The canvas could be sized to the stage's travel range —
that bound is known, and sparsity makes it free — but growing one afterwards is a
poor escape: it changes the file's shape, which forces the viewer to re-read the
image and throw away everything it had already loaded, and an array can only grow
at its far edge, never backwards. Both were measured.

Per-position stores ask for no promise at all. A new position is simply a new
store, which is the cheapest thing that can happen: the viewer adds it and nothing
already on screen is disturbed.

### What that costs, measured

Seeing the whole mosaic means opening every store rather than reading a few files
from one. On this machine, after the server was made to answer more efficiently:

| Positions | Whole mosaic ready |
|---|---|
| 25 | **2.1 s** |
| 100 | **4.1 s** |
| 225 | **10.5 s** |

Roughly 45 milliseconds a position. Unnoticeable for a few dozen; a real wait for
a few hundred. Note what that time is made of: at 225 positions the viewer asked
about eighteen hundred questions to receive eighteen chunks of actual picture.
Almost all of it is each store being asked to describe itself, which is why making
those answers cheap helped so much and why a graphics card would not help at all.

### If a run ever turns out big enough to mind

Stitch it into one canvas **after the run has finished**, as a separate step. By
then every position is known, so nothing has to be predicted, and the canvas's
advantage applies in full to a finished dataset that will be looked at many times.
The viewer reads both shapes already, so this costs no viewer work — only a
conversion when you decide a particular run deserves it.

### Three things to get right when writing

- **Give every store its stage position** in the metadata (a `translation`). That
  is what lets the viewer lay the pieces out; without it they all pile up at the
  origin.
- **Keep the pyramid shallow for small tiles.** Each resolution level is another
  small file the viewer must read before drawing. A 256-pixel tile does not need
  four levels; one or two is plenty, and it cuts the reading proportionally.
- **File the pieces in folders, not side by side in one directory.** In zarr terms
  that means `dimension_separator: "/"`, so a piece lands at `0/3/1/8/0/0` rather
  than being named `0/3.1.8.0.0`. Neuroglancer reads both, and this was checked
  rather than assumed. Two things make the folders worth insisting on. A long
  timelapse otherwise ends up with millions of files in a single directory, which
  most filesystems handle badly and some tools refuse outright. And the viewer can
  then tell how far a run has got simply by counting the folders at the top level
  — one per timepoint — instead of walking through every piece ever written. That
  is the difference between the time slider knowing where the live edge is
  instantly and the viewer giving up on the question, which is what it does when
  a directory turns out to hold more pieces than it is sensible to count.

### What a writer has to get right

Everything the viewer needs from a store, in one place, so a writer can be built
against it. Each item is either measured or read out of the engine's own source.

**The format.** Zarr version 2, inside an OME-NGFF 0.4 image. The viewer asks the
engine for `zarr2` explicitly, so a version 3 store will not open.

**The axes.** `t, c, z, y, x`, in that order, each named in the `multiscales` block.
Fewer is fine — a store with no time axis simply gets no time slider — but the order
of those present must be that one. Spatial axes must declare a length unit
(`micrometer` is what we use); the scale bar looks for a length and ignores anything
else, which is why a time axis never produces one.

**The pieces must be filed in folders**, which in zarr terms is
`dimension_separator: "/"`, so a piece lands at `0/3/1/8/0` rather than being named
`0/3.1.8.0`. The engine reads both. Two things make the folders necessary anyway: a
long timelapse otherwise puts millions of files in one directory, which most
filesystems handle badly; and it lets the viewer see how far a run has got by asking
about one folder rather than reading every piece ever written.

**Chunk size in y and x: a few hundred pixels, and not more than about a thousand.**
256 is a good choice. This is not only about transfer size. When the viewer measures
how bright a new image is, it reads a bounded sample — but the smallest thing that
can be read from a store is one whole chunk, so very large chunks force it to read
far more than it uses. Measured on a store chunked 8192 x 8192: **537 MB read to
obtain 4 million voxels**, a sixty-fold waste, two thirds of a second per store.

**One plane per chunk in z, c and t.** A chunk spanning several planes means fetching
all of them to show one, which is most of what makes scrolling through a stack feel
slow.

**A pyramid, and let it reach a small top.** The coarsest level is what the viewer
measures brightness from and what the engine draws when zoomed out, so it should be
small enough to read quickly — a few megabytes at most. A store with no pyramid still
opens, but it will be slow to open and coarse views will fetch full-resolution data.

**An `omero` block** naming each channel, giving it a colour, and giving a starting
brightness window. The viewer honours all three, so an acquisition arrives looking
sensible instead of flat grey. Without it, channels are named by number and the
window is measured from the pixels, which costs a read.

**Write each piece complete, or not at all.** The viewer tells the browser it may
keep a piece it has fetched, because a piece is written once and never rewritten. A
half-written piece that is readable would be kept in that state. Writing to a
temporary name and moving it into place gives this for nothing on every filesystem
we care about.

**Never rewrite or resize a piece that already exists.** Growing the declared shape
is fine and is described above; changing what a chunk contains is not, because a
reader may already be holding it.

## Decision 1b: one stitched image, afterwards, if it is wanted

Everything above describes data as it comes off an instrument. There is a second,
optional artefact worth having once a run is finished and the alignment is known:
**a single OME-Zarr image with the positions written into their places.**

One image is the better thing to keep, hand to a colleague, or archive. It is a
picture rather than a set of pieces plus instructions for arranging them, so any
tool can open it without understanding how the acquisition was organised, and the
viewer has one source to work from instead of hundreds.

It is deliberately *not* how acquisition writes, for the reason immediately below.

### Why this is not how acquisition writes: overlap cannot survive it

One image holds **one value per voxel**. So where two tiles overlap, the second one
written replaces the first in the shared region — the two versions of that region
cannot both be kept, because there is only one place to put them.

That matters because overlap is usually there on purpose. Tiles are acquired with a
few per cent of overlap precisely so that stitching can afterwards compare the two
views of the same specimen and work out the true alignment, correcting for whatever
the stage got slightly wrong. Flattening the tiles into one image at acquisition time
throws that comparison away before it can be made, and no later step can recover it.

So the honest position is that these are two different artefacts, at two different
stages, and a run that intends to stitch needs both:

**The raw tiles, one store per position, overlap intact.** This is what stitching
reads, and what the viewer shows while a run is in progress, because it is what exists
at that moment. That is Decision 1 above.

**One stitched image, written afterwards.** An image assembled once the alignment is
known, whether by a stitcher or simply by trusting the stage coordinates. It is the right thing to keep,
to hand to a colleague, and to view for the rest of the data's life.

A run that never intends to stitch — one that trusts the stage — can skip the first
and write the second directly, and then everything above applies with no caveat.

This is why the viewer has to handle both, and why the work on opening many stores
quickly matters: during acquisition, many stores is what there is.

### Why a canvas can be declared at all

Writing one image looks impossible at first, for one reason: an OME-Zarr image has a
declared shape, so a single image covering the whole stage means saying how large
the stage region is before the first tile has been taken. That could not be
answered — it changes with every experiment.

Two measurements dissolve that.

**Declared size is not occupied size.** An image is stored as many small chunk
files, and a chunk file only comes into existence when something writes to it. The
declared shape is a statement in a metadata file, not a reservation of disk. We
measured a declared 4 TiB image occupying **59 MiB** on disk. So the canvas does not
have to be known — only generously over-estimated, which is a much easier thing to
do. Declare a metre of stage travel if you like; it costs nothing until imaged.

**And the shape can be raised afterwards.** Chunks are addressed by their index, so
extending an image outward leaves every existing chunk exactly where it was.
Measured: an image declared with two timepoints, grown to five after the fact, kept
both original frames intact, accepted a write at frame five, and read the frames
never written as empty. Timepoints can therefore be added retrospectively, which is
what a timelapse of unpredictable length needs.

The one thing that is **not** allowed is extending *backwards* past the origin.
That would shift every index by one and invalidate every chunk already written. So
the origin goes at a corner of the region and growth only ever goes outward.

### How big to make the canvas

Since declared space is free and the shape can be raised later, the temptation is to
declare something enormous and never think about it again. That is nearly right, and
there is one bound worth respecting: **declare the stage travel the experiment can
actually use, not the largest number that will fit.** A stage has a real range, and
it is generous next to a specimen without being absurd.

Two things scale with the declared size rather than with the data, and both go wrong
quietly if the canvas is wildly over-declared.

**The brightness measurement.** The window an image first appears with is measured
from the smallest copy in the pyramid, and how big that copy is follows from the
canvas. On a canvas a hundred times larger than the specimen, that copy is almost
entirely empty, so the measurement is taken mostly from nothing and the window comes
out wrong — the specimen then appears black, or washed out. It reads as a broken
viewer rather than as a metadata choice.

**The opening view.** The viewer opens showing the whole declared extent. Over-declare
by a large factor and the specimen is a few pixels in the corner of an empty field,
which again looks like a fault rather than a choice.

A canvas a little larger than the stage can reach avoids both, and leaves growth as
the rare answer to a genuine surprise rather than something relied upon — which suits
it, since growth is the one operation with a restriction attached.

### If the experiment does not say: use the stage limits

An experiment should state the region it means to cover, because it usually knows —
that is the same decision as choosing where to image and at what magnification. But
it will not always say, and a viewer that refuses to open until someone fills in a
number is no use at the microscope.

**So where no canvas is given, the canvas is the stage's own travel limits.**

This is a good default rather than a resigned one, for three reasons.

It is already known. The travel limits are established during setup, before any
imaging, because the instrument needs them to keep from driving into its own end
stops. Nothing has to be guessed or asked for.

It cannot be too small. The stage physically cannot reach outside its limits, so no
tile can ever land beyond the canvas — which means growth is not merely rare, it is
impossible, and the one operation with a restriction attached never has to happen.
The origin sits at the low end of travel in each spatial axis, so there is nothing
behind it either.

And it is not wildly too large. A stage's range is a few centimetres, which is
generous next to a specimen but nowhere near the hundred-fold over-declaration that
would spoil the brightness measurement or open the view on an empty field. It sits
comfortably inside the bound described above.

The cost is honest and small: an experiment covering one corner of the stage gets a
canvas larger than it needed, so it opens zoomed further out than ideal and its
first brightness measurement is taken from a sparser picture. An experiment that
cares can say so and get something tighter. One that does not care still works.
### What this buys

The viewer receives one multiscale image per acquisition type and lets Neuroglancer
do what it is good at: choose a resolution level, fetch only the tiles under the
current view, and keep what it has fetched. Assembling the specimen stops being the
viewer's job — the pieces are already one image.

It also removes a great deal of work that only existed to cope with many images:
naming hundreds of stores distinctly, merging positions into one row per channel,
measuring the brightness of each store separately, and reading every store's
description each time the panel is refreshed.

### The constraint that makes it safe: tiles must land on chunk boundaries

This is the real cost of the change, and it falls on the writing side.

Two tiles written at the same moment are safe only if they do not share a chunk
file. Where they do share one, both processes read that chunk, each adds its own
tile to its own copy, and each writes the whole chunk back — so whichever finishes
second erases the other's contribution. This is not a theoretical worry. Measured,
with four tiles written concurrently into one image:

| how the tiles sat | result |
|---|---|
| each tile occupying whole chunks of its own | every tile intact |
| tiles straddling chunk edges | **up to 75% of a tile's voxels lost** |

With one image per position this could not happen, because no two writers ever
touched the same file. With a shared image it happens silently — no error, no
warning, just missing data in a picture that looks plausible.

So, for the driver:

- **Choose the chunk size and the tile step together**, so that a tile begins and
  ends on a chunk boundary in y and x. A tile that is a whole multiple of the chunk
  size, stepped by that same multiple, satisfies this.
- **Overlap between tiles is the thing to watch.** Tiled acquisitions usually
  overlap by a few per cent for stitching, and an overlap that is not a whole
  number of chunks puts two tiles in one chunk. Either round the step to a chunk
  multiple, or write overlapping tiles one at a time rather than concurrently.
- **If neither is possible, serialise the writes** for tiles that share chunks. One
  writer per chunk at any moment is all that is required.

### One thing the viewer must do differently

The small files describing an image are currently served with permission for the
browser to keep them for an hour, which is right for finished data and wrong for an
image still growing: a canvas that got larger, or a timelapse that gained frames,
would not be noticed until that hour was up. In live mode those description files
must not be cached. Static mode should keep caching them, since nothing can change.

---

## Decision 2: declare time generously, and never resize

Time is a dimension *inside* the store's array, not a set of separate stores. Each
new timepoint is written into the next slot along `t`.

How many timepoints a smart-microscopy run will produce **cannot be predicted** —
that is the point of it being smart; the experiment decides as it goes. So declare
`t` with a generous ceiling you will not reach, and write into slots as
acquisitions happen.

The reason is what happens to the viewer when the array's shape changes. An
array's shape lives in one small text file (`.zarray`). Growing the array rewrites
that file — and Neuroglancer read it once, when it opened the image, and cached
what it said. To notice a new shape it has to open the image afresh, which throws
away every piece of image it had already loaded. On a large volume that is a
visible reload, and it would happen on *every* timepoint.

Writing into a slot that was declared up front does not touch `.zarray` at all.
Measured: declaring ten thousand timepoints cost 6.1 MiB with three of them
written, and writing a fourth left `.zarray` byte-for-byte identical. Calling
`resize()` instead changed it.

So: **generous ceiling, write into slots, never `resize()`.** Unwritten timepoints
are free, exactly as unwritten canvas is.

The one consequence for the viewer is ours to handle rather than the engine's: a
store declaring ten thousand timepoints would offer a slider with ten thousand
frames when four exist. The panel is our own code, so the server reports how many
frames have really been written and the slider stops there.

## Decision 3: what the layer list looks like

The viewer's panel is organised the way the experiment is:

```
overview                        an acquisition type — a group
  ├─ structure                  a channel — one row, with colour, contrast, opacity
  ├─ marker-a                   another channel
  └─ nuclei                     a segmentation mask — a row of a different kind
targetscan
  ├─ marker-a
  └─ cells
```

Underneath, Neuroglancer's own layer list is flat — it has no notion of a group or
a sub-layer. So the grouping is presentation, drawn by our panel; the engine
receives one layer per channel and draws it. We organise, it renders.

Each channel row is one Neuroglancer layer reading the store and pinned to that
channel. The channel's **name and colour come from the store's own description**
(the `omero` block), not from its filename. That change matters: while every
channel was a separate file, a `Ch488` in the name could identify it, but once
several channels live inside one store the name cannot say which is which. On the
demo volume, reading the description surfaced three channels where the viewer had
previously shown one and silently hidden two.

Time and z are **sliders**, not rows, and each appears only when the store really
has that axis. A single-moment volume shows only Z; a flat overview shows neither.

### Data that is already stored per position

Existing mesoSPIM transfers write one store per tile and channel. Those still
open: a single row can take **several stores as its sources**, and Neuroglancer
places them using each store's own recorded stage position. Measured: twenty-four
position stores presented as three channel rows, every visible chunk loaded. This
is the path for data that already exists, not the shape we design new runs around.

### Segmentation masks are a different kind of layer

A mask is not dim image data. Its pixel values are object identities, so drawing
it as a greyscale image would be close to useless.

Neuroglancer has a first-class layer type for exactly this, which gives every
object its own colour, lets you click one to select it, and lets you hide
individual objects. That is the engine's original purpose, so masks should use it
rather than being squeezed into an image layer. A mask row therefore shows
different controls — opacity and which objects to show, rather than black and
white contrast handles, which mean nothing on an identity number.

For the viewer to know a channel is a mask, the writing side should use the
OME-NGFF standard for it: a `labels/` subgroup inside the image, carrying
`image-label` metadata. That is self-describing, so nothing has to be guessed from
naming conventions.

**Not yet verified:** that Neuroglancer's segmentation layer works in this stack
over a zarr label image. It is the engine's core competence and there is little
reason to doubt it, but it has not been proved here, and it should be before the
writing side commits to the layout.

## Decision 4: what live updating will require

During a run, two things happen and only two:

1. **A new store appears** — a new acquisition type begins.
2. **An existing store gains a timepoint** — written into a slot along `t`.

Both are cheap under the decisions above, which is the point of them.

A new store is a new group in the panel. Nothing already loaded is disturbed,
because it is new data in a new place.

A new timepoint is just new chunk files. Because `t` was declared up front,
`.zarray` does not change, so Neuroglancer does not have to re-open anything and
keeps everything it has already loaded.

What the viewer still needs, and does not yet have, is a reason to look again:

- `/api/config` is currently built **once**, when the server starts, so a store
  that appears later is never noticed.
- Image chunks are served with an hour-long cache instruction, which is wrong for
  a folder that is still being written to.
- The page fetches its configuration once and never asks again.

None of those are hard, and all three are honest bugs for live data rather than
design problems. They are listed here so the work is not rediscovered later.

## Status

Decided and measured: where the split goes, why time is pre-declared, how the
layer list is organised, and what live updating will cost.

Built so far: reading acquisition types, positions and channels from what is on
disk (`backend/stores.py`), with tests.

Not built yet: the grouped panel itself, one layer per channel, and the three
live-refresh items above. The measurements that show the approach will work are in
`measure_canvas.py`; the interface work is still ahead.
