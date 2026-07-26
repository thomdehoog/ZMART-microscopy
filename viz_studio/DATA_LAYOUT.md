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

## Decision 1: one store per acquisition, per position

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
