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
store that already exists, whose length in time grows by one as the frame lands. A new
mask is a folder under `labels/`. Nothing that is already being read ever changes shape.

**On screen.** Rows are gathered under their acquisition type, one row per channel — and
a mask is simply another row, drawn with its own controls. Every position of one
acquisition type feeds the same row, and they become one picture because the engine
places each by its translation. What the panel shows is therefore acquisition types and
channels; the fact that a position is a separate folder never surfaces.

**How much to open.** Whatever the operator asked for. Point it at a folder and it opens the
folder; the viewer never decides to show less than it was given. What that asks of the
interface is that narrowing down be easy and be offered *before* the loading starts — open
one acquisition type rather than a whole folder. See Decision 5.

**Getting data in, two ways.** While a run is producing data, the control application
says "this position is ready" and the viewer hands the engine one more address. For data
that is finished, point the viewer at a folder: it finds what is there, shows it, and
then stops asking, because nothing can change. New *frames* need no announcing at all —
the engine fetches them when you go and look, since it already has the address.

**What to be good at.** One image that keeps being added to, since that is what smart
microscopy actually is. So the care goes into not re-reading what is already known and into
telling the page precisely what changed — not into cleverness about huge finished folders,
which must simply not fail. See Decision 6.

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

**A timelapse grows its own length; it is not declared in advance.** When a frame is
written, the array's shape is raised by one. The store then always says what it actually
contains, which is the honest arrangement: the time slider ends where the data ends,
with nothing having to hide frames that do not exist yet.

The alternative — declaring a generous length up front and never changing it — was
considered and rejected as untidy. It works, and it has one merit: the description never
changes, so it could be kept by the browser indefinitely. But it means the store claims
frames it does not have, and something then has to stop the operator reaching them,
because the engine remembers "there is nothing here" for a frame looked at too early and
will not look again.

Growing it is affordable, which is what makes the tidier choice the practical one too. A
store's description is a few hundred bytes whether the array holds one frame or ten
thousand — only a number in it changes — and re-reading it does not touch a single voxel,
because a piece of image keeps its address when the array grows.

**What that means for keeping copies.** The two kinds of file are treated oppositely, and
the reason is exactly this decision:

- **Pieces of image: kept for a year, and marked as never changing.** Written once,
  never rewritten. An acquisition can run for many hours, so anything shorter would have
  a piece expire mid-run, and returning to somewhere already visited would fetch it all
  again.
- **The files describing a store: never kept at all.** They are what changes when a
  timelapse grows. A stale copy, even a few seconds old, would leave the engine believing
  the old length — so a frame sitting on disk would simply not appear, with nothing to
  explain why. The cost of always asking is a round trip, not a read: a few hundred bytes,
  answered from memory.

**One depth per image, and let it be the camera's own.** The kind of number a voxel
is — 16-bit, 8-bit — is read from the store itself, so nothing has to be told and an
8-bit acquisition from some other instrument opens and displays correctly. What matters
is that **every level of one image shares it.**

A pyramid is one picture at several sizes, so the format gives it a single data type,
and the engine compiles a single small display program against that type. Levels of
different depths are not a valid multiscale image and would fail to open rather than
merely look odd.

It is worth saying why this is tempting and why it does not pay, because the idea comes
up. Storing the shrunk-down copies at 8-bit to save room saves almost nothing: every
level above the first adds up to roughly a third of the full-resolution data, and it
compresses better than the original because it is smoother, so halving the depth of the
small copies is a few per cent of the store at most. Against that, the contrast window
is a *range of numbers* — 800 to 9800 means nothing on a scale that stops at 255 — so
the picture would jump in brightness every time zooming crossed a level boundary, and
the Auto button would set a window correct for one level and wrong for the rest.

If a smaller, cheaper picture is genuinely wanted, make it a **separate image** with its
own consistent depth, viewed as its own layer. That is honest: it is a different
picture, not a different level of the same one. Though an experiment that already
acquires an overview has this covered.

To make the pyramid cheaper without any of that: use **fewer levels** — a 256-pixel tile
does not need four — and lean on compression, which does unusually well on smooth
downsampled data.

**Write each piece complete, or not at all.** The viewer tells the browser it may
keep a piece it has fetched, because a piece is written once and never rewritten. A
half-written piece that is readable would be kept in that state. Writing to a
temporary name and moving it into place gives this for nothing on every filesystem
we care about.

**Never rewrite or resize a piece that already exists.** Growing the declared shape
is fine and is described above; changing what a chunk contains is not, because a
reader may already be holding it.

## Decision 1b: one stitched image — **considered and rejected**

> **This is not going to be built.** It is kept because the reasoning below is sound on its
> own terms and someone will propose it again, and because the measurements in it are real.
> What changed is not the arithmetic but what the arithmetic was being asked to solve.
>
> Fusing the positions of an acquisition type into a single image was the answer to one
> question: opening a folder of many thousands of positions is slow. It would have worked —
> one source, one pyramid, and the engine handles every zoom unaided.
>
> But it is a second copy of the data, made by a step that has to run, kept somewhere, and
> kept in step with the original. That is a large thing to take on, and the problem it
> solves turns out not to need solving. **The viewer should not be opening forty thousand
> positions in the first place.** See Decision 5.
>
> Stitching for *scientific* reasons — correcting where the stage actually put each tile —
> is a separate matter and is not what this section was about. Nothing here argues against
> it. It argues only against fusing in order to make the viewer quick.

### The original reasoning, kept for the record

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

### What the viewer does about copies while a run is going

An image that is still being written cannot be copied and kept, so during a run the
server tells the browser to hold nothing at all: neither the small files describing
an image nor the pieces of image themselves. A copy held while the instrument is
still writing can go on showing an old version of a region, and — this is the part
that matters — there is nothing on screen to say that it is old. Someone watching a
live experiment would be reading a stale picture. A round trip to a server on the
same machine is a cheap price for not doing that.

Finished data is the opposite case and is treated as such: the pieces of image may
be kept for a year and marked as never changing, which is what makes moving around
an old acquisition feel instant.

The one thing never kept in either mode is the small files describing a store, for
the reason set out under Decision 2 below: they are exactly what changes as an image
grows, and they are cheap to ask for.

---

## Decision 2: a timelapse grows its own length

Time is a dimension *inside* the store's array, not a set of separate stores. When a
frame is written, the array's shape is raised by one and the frame goes into the new
slot.

So the store always says what it actually holds. That is what makes the time slider
honest: it ends where the data ends, and nothing has to hide frames that do not exist.

### Why not declare a generous ceiling instead

The other way round was built first, and rejected: declare `t` as some large number you
will not reach, write into the slots as they arrive, and never change the shape. It
works, and it has one real merit — the description never changes, so a browser could
keep it indefinitely.

But the store then claims frames it does not have, and something has to stop the
operator reaching them. That is not optional politeness: **the engine remembers "there
is nothing here" for a frame it looked at too early, and will not look again.** A frame
glanced at before it existed stays blank for the rest of the session, even once the
microscope has written it — a frame on disk that refuses to appear, with nothing on
screen to explain it. Guarding against that means the interface has to know how many
frames are real anyway, which is most of the work the ceiling was meant to avoid.

So it is a workaround with an untruth in it, and the untruth has to be papered over.
Growing the array removes both.

### Growing is cheap, which is what makes the tidier choice practical

Two measurements, both reproducible:

- **Raising the shape keeps the data.** An array declared with two frames, grown to
  five, kept both original frames intact, accepted a write at frame five, and read the
  frames never written as empty. Safe because a piece of image is addressed by its
  index, and extending the *first* axis moves nothing.
- **The description does not grow with the data.** It is a few hundred bytes whether the
  array holds one frame or ten thousand — only a number in it changes. Re-reading it
  touches no voxels at all.

So the cost of a new frame is: the frame, plus a few hundred bytes rewritten. Not a
re-read of a twenty-gigabyte timepoint.

### One cost this underestimated, found later and measured

The paragraph above is about what it costs to *write* a frame, and it is right. What
it did not account for is what it costs the viewer to notice one, and that turned out
not to be free.

The engine files each piece of decoded image under a key that includes the array's
shape. So when the shape genuinely changes — which is the whole point of this decision
— the pieces currently on screen are suddenly filed under a key nobody is looking for,
and the frame being viewed is fetched again. It is bounded: the frame on screen, not
the whole timelapse, and once per growth rather than continuously. But a viewer left
watching a timelapse that gains a frame every few seconds will pay it every few
seconds, and during a live run nothing is kept by the browser, so each one is a real
request rather than a read from memory.

This does not overturn the decision. The alternative still has an untruth in it, and
the untruth still has to be papered over. But it is worth knowing before anyone points
a viewer at a very fast timelapse and wonders why it is busier than expected, and it is
the measurement to take first if that ever becomes a complaint.

The happier half of the same fact: when a store's description comes back *unchanged*,
the key is unchanged too and nothing at all is re-fetched. An acquisition that declares
its length up front and fills in frames it already promised costs the viewer nothing to
follow. That is pinned by
`test_engine_is_not_disturbed.py::TestDataArrivingWhileYouWatch::test_frames_arriving_do_not_disturb_what_is_shown`.

### What follows for keeping copies

This decision is the whole reason the files describing a store are never kept by the
browser, in either mode. They are exactly what changes when a timelapse grows. A
stale copy, even seconds old, leaves the engine believing the old length, so a frame
sitting on disk does not appear and nothing explains why. Always asking costs a round
trip rather than a read: a few hundred bytes, answered from memory.

The pieces of image are kept or not according to whether the run is finished, which
is set out under Decision 1 above. In short: nothing is kept while the instrument is
writing, because nothing on disk is settled; once the run is done, a piece may be
kept for a year and marked as never changing, since it is written once and never
rewritten.

### The browser's copy is not the only copy

The paragraph above is about the browser's own store of things it has fetched, which
the server controls through the headers it sends. That much was right and is still
right. But it is not the only place an answer can be kept, and assuming it was cost us
a session.

The engine keeps its own memory, inside the page, of everything it has worked out about
a store: how long it is, how big a voxel is, where the pyramid levels are. Nothing in an
HTTP header can reach that memory. It has no time limit and no size limit, and the engine
never lets go of an entry once it has made one, so it lasts exactly as long as the page
is open. Telling the browser not to keep a copy of a description therefore achieves
nothing on its own — the engine simply never asks the browser in the first place, because
it already believes it knows.

That was measured rather than reasoned about: after an announcement, a page that had been
asked in every available way to read the store again fetched no description files at all.

So the viewer drops what the engine remembers about that one store first, and only then
asks it to resolve the store again. What is dropped is only what was *read*; the decoded
image is remembered separately and is deliberately left alone. See
`forgetWhatWasReadAbout` in `frontend/src/engine.js`.

Two things follow that are worth keeping in mind. This memory dies with the page, so
closing the viewer clears it and there is nothing to tidy up on the way out. And because
dropping it makes the next question genuinely reach the disk, it is done only for a row
whose frame count has actually moved — a row can hold a store for every place the
microscope visited, and asking all of them on every announcement would be thousands of
small requests to no purpose. That guard is pinned by
`test_a_run_arriving.py::test_a_store_is_only_read_again_when_it_has_actually_grown`.

### What the viewer needs for this

Growing the array only helps if the viewer re-reads the description, so something has to
tell the page that it has grown. That is the same channel from server to page that
announcing a new position needs, and one mechanism serves both. It is built: see
"Telling the page" below. Being told is necessary but not sufficient — see the section
just above for the second half.

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

A new store is a new group, or a new row in an existing group. Nothing already on
screen is disturbed, because it is new data in a new place — and the engine is given
one more address rather than a fresh description of the whole scene, which is what
made an earlier version throw everything away and rebuild it.

A new timepoint raises the store's declared length by one. The pieces themselves need
no announcing at all: the engine already holds that store's address and fetches the new
chunks when you go and look. What it does need is to re-read the description, so that it
knows the length has moved.

**Both therefore come down to one thing: something has to tell the page.**

### Telling the page

The viewer used to find out by asking — reading the modification times of everything
open, several times a second, for as long as the window was open. That works, but it can
only ever *infer* that a write has finished, which is not something a timestamp can say,
and it has been wrong more than once. The worst of them: a store is created before it is
readable, so a new acquisition was noticed at the one moment it could not be opened, and
then never looked at again. It stayed invisible for the whole session with nothing
anywhere reporting a problem.

The control application does not have to infer anything. It called for the acquisition
and waited for the write to finish, so at that moment it holds the fact we were trying to
guess. It says so with `POST /api/announce`, and every open page is told at once.

An open page hears about it over a connection it holds open, at `GET /api/events`. This
is the browser's own server-sent-events mechanism: the page opens it once, the server
writes a line when there is something to say, and nothing at all is sent the rest of the
time. No library is involved on either side.

The message carries no detail, and that is deliberate. Hearing one means "ask again", and
the answer is read from disk — so there is only ever one description of the world and it
is the true one. Sending the detail instead would mean keeping a second description in
step with the first, which is a way to be subtly wrong.

Both of the announcements above go through it:

- **"this position is ready"** → the page asks again, and hands the engine one more
  address. (`POST /api/stores/open` also does this directly, and announces.)
- **"this position now has *n* frames"** → the page asks again, re-reads the store's
  description, and the time slider reaches the new frame.

Announcements arrive at the rate acquisitions finish — a handful a minute at most, since
an exposure takes seconds. So this is a small, quiet mechanism, and it does no work at
all when nothing is happening.

### The disk is still watched, as a safety net

Watching the folder has not gone away, but it has moved. Not everything that writes will
announce: a mesoSPIM writes its own OME-Zarr, and an operator may open the viewer on a
folder being filled by something that has never heard of us. In those cases nothing is
going to say "this position is ready" and the only way to notice is to look.

What changed is *where* the looking happens. The page no longer asks; the server looks
once on its own behalf, however many pages are open, and announces through the same
channel when something moves. On finished data it does not run at all.

It remains the weaker of the two mechanisms, for the reason above, and an announcement
should be preferred wherever there is one.

## Decision 5: the operator decides how much is open; the viewer never does

Point the viewer at a folder and it opens what is in the folder. All of it. It does not
choose an overview for you, does not hold anything back, and does not decide that forty
thousand positions is more than you meant. If you asked for it, you get it.

This was very nearly decided the other way, and the reason for landing here is worth
keeping. A viewer that quietly limits what it shows has to be right about what you wanted,
and when it is wrong it is wrong invisibly — you are looking at part of your specimen with
no way to tell. That is the same failure as the silent ceiling described further up, only
deliberate. Better to be slow and honest than quick and economical with the truth.

**What follows from it is a duty on the interface, not on the loader.** If the viewer will
not narrow things down, then narrowing them down has to be easy, obvious, and available
before the loading starts:

- **Opening one acquisition type rather than a folder.** The panel already closes by
  acquisition type; choosing at the moment of opening is the other half of that and is what
  makes the whole thing workable. Somebody who wants their overview should be able to say so
  and get it in a moment, without waiting for the target scans they were not going to look at.
- **Saying what something will cost before doing it.** "This folder holds 40 000 positions"
  is worth showing, because it lets the operator decide rather than guess. A viewer that
  appears frozen and a viewer that is working through what it was asked for look identical,
  and only one of them is a problem.
- **Closing what is not being used**, and having that genuinely give the memory back.

So the speed of a large folder is accepted rather than engineered around. The mechanisms
that were proposed to engineer around it are both rejected — a window of only the positions
in view (see the note in `engine.js`) and a fused image (Decision 1b) — and this is the
reason: neither was worth its complexity once the operator could simply open less.

**Feeding stores in groups is unaffected**, and is not a form of limiting. It exists so that
nothing is *silently lost*, which is the one thing that must never happen whatever the
operator asks for. It changes the order requests are made in, never which data arrives.

### What "as fast as possible" means, given all that

Three things, in order, and only the first is about loading:

1. **First pixel before completeness.** Draw what has arrived rather than waiting for
   everything. Somebody watching a run wants their specimen on screen now.
2. **Controls that never stall.** Turning a contrast handle must not stutter, whatever is
   open. This is why layers are adjusted rather than rebuilt, and why costs that grew with
   the number of positions mattered so much — they were paid on the thread the engine draws
   with. This is most of what makes the viewer *feel* fast, and it is independent of how
   much is open.
3. **Completeness last, and never silently.** Anything not on screen must be something the
   operator chose not to open — never something the viewer failed to load and said nothing
   about.

## Decision 6: the case to be good at is one store that keeps growing

The previous decision says what the viewer will not do. This one says where the care
should go instead, because "do less" is only half an instruction.

Smart microscopy, as we actually do it, is **one image that is added to over time**. The
microscope decides where to look next, writes another frame or another position, and the
person watching wants to see it appear. That is the case worth being genuinely good at.
Forty thousand finished stores opened in one go is a real thing an operator may ask for and
must not fail — that is what Decision 5 and the grouped feeding are about — but it is not
the shape of the work, and the design should not be bent around it.

The distinction matters because it tells you which problem is worth complexity. In the
growing case almost nothing is new on any given update: one more frame, or one more
position among hundreds already open. Everything else on screen is unchanged and should
not be touched, refetched, or thought about again. So the two things that deserve real
attention are:

- **Not throwing away what is already known.** Both in the browser, where a piece of image
  already fetched must not be fetched again, and on the server, where what a store contains
  is read once and remembered. This is why layers are adjusted rather than rebuilt, and why
  the cheap "has anything changed?" question exists separately from the expensive "what is
  here?" one.
- **Telling the page what changed, promptly and precisely.** Not "something changed, look
  again at everything" but as close to "this position, this many frames" as we can manage.
  Decision 4 covers the channel this travels down.

### On simplicity

A viewer that is a **plain, honest use of Neuroglancer** is the goal — not a clever one.
Where there is an abstraction of ours that is not paying for itself, remove it; where there
is a special case fitted to one measurement on one machine, be suspicious of it. Two
concrete things follow. The engine is given the same treatment whether data is live or
finished, with nothing anywhere asking which it is. And each of the two things above should
be one mechanism doing one job, not a mechanism plus a fallback that quietly compensates
for it — a fallback that is always running is not a safety net, it is the design.

## Status

**Decided, and written above:** one store per position with its place in its own
metadata; a stitched image as a separate later artefact; a timelapse that grows its own
length; one data type per image; how the layer list is organised; and what caching
follows from all of it.

**Built and tested:** reading acquisition types, positions and channels from what is on
disk; the panel with grouped rows, one shared set of display settings, colour maps and
masks; Z and T sliders that appear only when the axis exists; targets saved beside the
data; applying changes to the engine by adjusting layers rather than rebuilding them;
and the channel from server to page described under Decision 4, so an open page is told
when something changes instead of asking.

There is also a test that looks at the picture and fails if the panel is a flat colour.
That sounds obvious and was not there: the viewer spent weeks opening on an empty grey
rectangle with three hundred tests passing, because every one of them asked the engine
about itself and an engine can hold all its data and still draw nothing.

**Not built:** a writer. The mesoSPIM writes its own OME-Zarr today and our driver copies
frame files rather than writing zarr, so where the writer belongs — a conversion step, or
a change to what the driver writes — is still open.

**Settled since this was written:** the specimen does appear on screen. The slice view
was drawing only its own background because the magnification had been fixed before the
images said how big a voxel was, so the specimen was drawn about a ten-thousandth of a
pixel wide. It was never a storage question. See the commit for the full account.
