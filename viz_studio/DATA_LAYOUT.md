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

## Decision 1: one store per acquisition type

A "store" is one OME-Zarr, which is a *folder* on disk rather than a single file.
One store holds one image, its shrunk-down copies, and a little metadata.

**Write one store per acquisition type**, with all of that type's positions pasted
into a single canvas inside it:

```
run_2026-07-26/
  prescan.ome.zarr        each one t,c,z,y,x, with every position of that
  overview.ome.zarr       type written into one canvas at its stage offset
  targetscan.ome.zarr
```

**Not** one store per position (`overview_pos001.ome.zarr`,
`overview_pos002.ome.zarr`, …).

### Why the split lands on acquisition type

Acquisition types have **different pixel sizes** — an overview is coarse, a target
scan is fine — and an OME-Zarr image has exactly one pixel size. A coarse overview
and a fine target scan therefore cannot share a store. That makes the acquisition
type the natural boundary, and it is not a matter of taste.

### Why it should not split further, down to positions

Because of the **pyramid**, and this is the whole argument.

Alongside the full-resolution image, an OME-Zarr keeps progressively smaller
copies — half size, quarter size, and so on. That is what lets a huge image feel
light: zoomed out, the viewer reads a small coarse copy instead of hauling every
pixel across.

If every position is its own store, every position has its own separate pyramid.
There is then no coarse copy *of the mosaic* — only coarse copies of its pieces —
so seeing the whole specimen means opening every store at once and streaming from
all of them.

If the positions share one canvas, the pyramid is **global**. Zoomed out, the
viewer reads a handful of chunks from one coarse copy that covers the entire
mosaic, however many positions went into it.

Measured on an 8192 × 8192 canvas holding nine tiles:

| What is on screen | Chunk files fetched |
|---|---|
| The whole mosaic, zoomed out | **12** |
| A single tile at full resolution | **6** |

Looking at the entire mosaic costs about the same as looking at one tile. The size
of the canvas does not enter into it, because the cost tracks *how many pixels are
on the screen*, not how much data exists. That is the property the whole design
rests on, and per-position stores give it up.

### The obvious objection, and why it does not hold

A canvas covering the whole stage at target-scan resolution sounds enormous. It is
enormous — as an address space — and that turns out not to matter, because **a
chunk nobody wrote does not exist on disk**. An OME-Zarr is a folder of small
files, one per piece of image actually written; unwritten regions are simply
absent, and a reader treats them as empty background.

Measured on the same canvas:

| | |
|---|---|
| Canvas declared, at full resolution | **1.00 GiB** |
| Pixels actually imaged (nine tiles) | 36 MiB |
| On disk, including all six pyramid levels | **50 MiB** |
| Fraction of the declared canvas | **4.9%** |

So the file weighs what you imaged plus about 39% for the pyramid, which is the
expected overhead for halving in y and x. Sizing the canvas to the stage's travel
range costs nothing.

### Two things this asks of the writing side

- **Keep tiles aligned to chunk boundaries.** A tile that straddles a chunk forces
  the writer to read that chunk, modify it and write it back, which is slower and
  unsafe if two tiles are written at the same moment. Aligned tiles are
  independent writes.
- **Resolve overlap when writing**, since there is only one canvas. That is
  usually what you want anyway: a stitched mosaic rather than doubly-bright seams.

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
