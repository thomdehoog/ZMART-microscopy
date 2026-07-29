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
store that already exists, into room declared for it at the start — so a store gains
pieces of image but never changes its declared shape. A new mask is a folder under
`labels/`. Nothing that is already being read ever changes shape.

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

**One store or many.** Where a run does not need its overlap kept, it should create one
image at the start and write each tile into its place: no copy, no extra step, and the
viewer holds a single store from the first moment, which is much faster to open and smoother
to draw. Where the overlap must survive for stitching, the tiles stay separate and the
viewer shows them side by side. Both work; the first is what we are aiming for. What is
*rejected* is fusing finished positions into a copy afterwards just to make the viewer
quick. See Decision 1b.

**The rule, decided.** *One image per acquisition type, and its tiles do not overlap.* A run
has a handful of acquisition types — a prescan, an overview, a target scan — so the viewer
holds a handful of images, each growing as its tiles land. That is a small, fixed number
that does not grow with the run, which is the whole of what made many stores slow.

**And if a run does overlap its tiles, it does not write into one image at all.** It keeps
its tiles separate while it runs and is stitched into one picture afterwards, once every
tile exists and the alignment can actually be solved. The two are different paths rather
than settings of one, because overlap written into a single image is destroyed at the moment
of writing: measured, a run overlapping by an eighth loses **18% of everything the camera
recorded**, and no later step can recover it. The writer refuses rather than allowing it
quietly. See Decision 1b.

**Why not overlap and keep it anyway.** It can be done — spread the tiles over four images
so neighbours never share one — and it measures well: 0.6 seconds to open against 0.5, the
same sixty draws a second, nothing lost. It is available and tested. It is not the rule
because it makes every reader deal with four images instead of one, and analysis reads these
images too. See "If a run must keep its overlap" under Decision 1b.

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

**A timelapse declares its length up front and fills it in.** A run declares room for
comfortably more moments than it could record — ten thousand is a sensible figure — and
writes each frame into its place as the experiment goes. This is the same arrangement as
the room in space, which is declared to the stage's whole travel range rather than grown
to fit, and for the same reason: a moment nothing has been written to occupies no space
on disk at all, so declaring generously costs only the number written in the store's
description.

**This reverses an earlier decision, and the reversal is worth understanding.** The
document previously said the opposite — that a timelapse should raise its own length by
one as each frame lands, so the store always said exactly what it held. The objection to
declaring up front was recorded here as: *the store claims frames it does not have, and
something then has to stop the operator reaching them, because the engine remembers
"there is nothing here" for a frame looked at too early and will not look again.*

That objection was sound, and it is now spent, because the something exists.
`written_timepoints` in the viewer's `stores.py` reads how far the images on disk reach
and stops the time slider there, and the viewer opens a timelapse at its first moment
rather than half way along. Both are built and tested. With those in place the operator is
never offered a moment beyond the furthest one imaged, whatever the store declares — so
the property that growing bought is delivered by the viewer instead, and bought nothing
that is still needed.

One qualification, because the earlier wording here promised more than the code delivers
and that is worth correcting rather than leaving to be discovered. What is stopped at is
the furthest moment written, not the number of moments written, and the two differ
whenever a moment in the middle holds nothing. A canvas imaged at the moments a workflow
chooses does that by design, and so does a frame that came out entirely black, since zarr
stores no piece at all for a chunk that is only fill value. In those cases the moments in
between are offered too, and draw as empty. That is the deliberate choice: stopping
earlier would put real, readable data out of reach with nothing on screen to say it was
there. It is written out in full in the `written_timepoints` docstring.

What growing cost, by contrast, does not go away. Changing an array's shape changes the
key under which the engine files the pieces it has decoded, so a viewer following the run
re-reads the frame on screen every time the length moves — once per moment, for the whole
length of the run. Declaring up front costs that exactly once, which is to say never. The
description also stops changing, which means it could in principle be kept by the browser
rather than re-fetched; that is not done today and is noted here as available rather than
claimed.

**Counting has to stay cheap, and that is a constraint on the layout, not a hope.** The
viewer now depends on counting written moments, so the pieces of a store must be filed in
folders — one per moment — rather than heaped side by side in a single directory. That is
already required for other reasons and is stated below; it is simply load-bearing now.
Where a store does not do it and the folder is too large to look through, the viewer
declines to limit the slider rather than making the operator wait, and an unwritten moment
then shows as empty rather than as missing.

**What that means for keeping copies.** The two kinds of file are treated oppositely:

- **Pieces of image: kept for a year, and marked as never changing.** Written once,
  never rewritten. An acquisition can run for many hours, so anything shorter would have
  a piece expire mid-run, and returning to somewhere already visited would fetch it all
  again.
- **The files describing a store: never kept at all.** This rule was written for the
  growing arrangement, where the description was what changed as a timelapse lengthened
  and a stale copy would have left the engine believing the old length — a frame sitting
  on disk simply not appearing, with nothing to explain why. Declaring the length up front
  removes that: during a run the description of an existing store no longer changes at
  all. The rule is kept because it is cheap and certainly correct — a round trip for a few
  hundred bytes, answered from memory — and because nothing has measured a case where it
  costs anything. Letting the browser keep a copy and check it is the obvious refinement,
  and it is listed in `NEXT_STEPS.md` under the smaller things worth doing; it should be
  done on evidence rather than on this paragraph.

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

## Decision 1b: one image covering the whole specimen

This section is about a single OME-Zarr that stands for the whole specimen, rather than one
store per position. There are two quite different ways to arrive at one, they have opposite
verdicts, and telling them apart is the whole point of this section.

> **Writing into one store as the run goes: this is what we are aiming for.** Create the
> image empty at the start, sized to cover the ground the experiment will visit, and have
> the microscope write each tile straight into its place. There is no second copy and no
> extra step — the tile is written once, where it belongs. The viewer then holds one store
> from the first moment, which is worth a great deal: **one store describing about a hundred
> and thirty-seven gigabytes reaches the screen in 1.4 seconds on 38 requests, where three
> hundred separate positions — a far smaller specimen — take 2.4 seconds on 1 125 requests
> and then draw at a quarter of the rate.** Everything below about how large to make the
> image, what to do when the experiment cannot say, and why tiles must land on chunk
> boundaries, is about this. `check_writing_into_one_store.py` runs it end to end.
>
> It comes with one condition, which the viewer already handles: a tile landing where the
> viewer has already looked changes nothing that any description would show, so the run has
> to say so. See "What the viewer does about copies while a run is going" below, and
> Decision 4.
>
> **Fusing finished positions into one image afterwards: rejected.** Same destination,
> reached by copying. It would have worked, and it was the answer to one question — opening
> a folder of many thousands of positions is slow — but it is a second copy of the data,
> made by a step that has to run, kept somewhere, and kept in step with the original. That
> is a large thing to take on for a problem that turns out not to need solving: **the viewer
> should not be opening forty thousand positions in the first place.** See Decision 5.
>
> **And one store per position is not going away**, because a run that intends to stitch
> needs its tiles kept separately with their overlap intact — see the section immediately
> below, which is the reason writing into one store is a choice rather than the rule. It is
> also what the mesoSPIM already writes. So the viewer has to be good at both, and is.
>
> Stitching for *scientific* reasons — working out where the stage actually put each tile —
> is a third thing again, and nothing here argues against it. What is rejected is only
> copying data in order to make the viewer quick.

### Why one image is worth having at all

Decision 1 describes data as it comes off an instrument: one store per position, each
carrying its own place on the stage. The alternative is **a single OME-Zarr image with the
positions written into their places.**

One image is the better thing to keep, hand to a colleague, or archive. It is a
picture rather than a set of pieces plus instructions for arranging them, so any
tool can open it without understanding how the acquisition was organised, and the
viewer has one source to work from instead of hundreds.

That is the case for it, and it is a strong one. What follows is the case against doing it
at acquisition time, which is real but applies only to runs that intend to stitch.

### The one thing it costs: overlap cannot survive it

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

**A run that never intends to stitch — one that trusts the stage — can skip the first
entirely and write straight into one image as it goes.** That is the aim stated at the top
of this section, and this is the condition on it: it is available exactly when nobody needs
the overlap back. For smart microscopy, where the point is to watch the specimen and decide
where to look next rather than to assemble a publication mosaic, that is usually the case.

This is why the viewer has to handle both, and why the work on opening many stores
quickly matters: for a run that does keep its tiles, many stores is what there is.

### The rule that follows: no overlap in an image written as the run goes

The cost above is real and cannot be worked around inside one image, so it becomes a rule
rather than a caution:

> **An image written while the run goes has tiles that do not overlap. A run that overlaps
> its tiles keeps them separate and is stitched once it has finished.**

Two different paths, not two settings of one. The first is for a run that trusts the stage,
which is most smart-microscopy work, where the point is to watch the specimen and decide
where to look next rather than to assemble a publication mosaic. The second is for a run
whose alignment must be computed, which can only happen once every tile exists.

The writer enforces this at the moment the images are created rather than letting a run
discover it later from a picture that looks subtly wrong — see
`zmart_storage/canvas.py`, and the refusal is pinned by
`test_a_run_with_overlapping_tiles_is_refused`.

**What follows for the tile size.** Since there is no overlap, the step can be chosen freely,
and it should be chosen so that a tile is a whole number of pieces of image. Then no two
tiles ever land in the same piece, and they can be written at the same moment with no waiting
at all. The size to divide into is `chunk × 2^(levels−1)` — the piece of the *smallest* copy,
which covers the most ground. With 256-voxel pieces and three levels that is 1024, so a
2048-voxel tile works and a 1500-voxel one does not. Getting it wrong is not dangerous, only
slower, and the writer says so when it happens.

### If a run must keep its overlap: several images, deliberately

This is available, measured, and not the rule. It is recorded because the reasoning is worth
having and because somebody will ask.

Go back to what actually made many stores slow. It was never that there was more than one
image. It was that the number of images grew with the run, and the work of keeping track of
them is paid *again every time a tile lands*, not once at the start. Measured on this
repository's own rig: a tile arriving cost 0.1 seconds with 25 stores open, 0.3 seconds
with 100, and 3.7 seconds with 225. A run of a few thousand tiles is far outside that.

So the thing to avoid is the growth, not the plurality. **A small number of images, fixed
before the run starts, is as cheap to follow as one and keeps every pixel.**

#### How many images that takes, and why it is a small number

Tiles overlap their immediate neighbours. But if the tiles are dealt out to several images
in rotation, two tiles that end up in the same image are further apart than neighbours —
and past a certain separation they stop touching at all.

That separation is easy to work out. Tiles placed a step apart, each a tile-width across,
are two steps apart when one is skipped, so they clear each other whenever two steps is at
least one tile wide. That holds for any overlap up to half a tile. Since no tiled
acquisition overlaps by more than half, **two images per axis is always enough**:

| how the run is tiled | images needed |
|---|---|
| in y and x, which is the usual case | **4** |
| in y, x and z as well | **8** |
| not tiled at all | 1 |

The number depends only on how much the tiles overlap. It does not depend on how many tiles
the run acquires, which is the whole point — it is four whether the run visits fifty places
or five thousand.

#### What it costs, measured

The same 9 × 9 raster of tiles overlapping by 12%, written both ways, with the viewer
opened on each. Reproduced by `measure_canvas_vs_checkerboard.py` beside this file.

| | one image | four images |
|---|---|---|
| writing one tile, median | 63.7 ms | 54.1 ms |
| sources the viewer opens | 1 | 4 |
| opening the run | 0.5 s | 0.6 s |
| description files read to open | 8 | 32 |
| draws per second, idle | 60 | 60 |
| draws per second, while tiles land | 60 | 60 |
| **acquired data overwritten** | **21.0%** | **0.0%** |

Opening costs a tenth of a second more. The viewer holds a steady sixty draws a second in
both, and — this is the number that matters for a live run — it stays at sixty while tiles
are being written underneath it, so the page is no harder to steer during an acquisition.
Writing is if anything slightly quicker, though that difference is small enough not to lean
on.

Against that, the single image destroys **a fifth of everything the camera recorded**. Note
that this is larger than the 12% overlap, and it should be: a tile in the middle of the
raster is eaten into from both sides in both directions, so it loses considerably more than
one overlap's worth.

One further figure worth having, from the same script: **44% of the time spent writing a
tile goes on the smaller copies** that keep the zoomed-out view current. That is the first
dial to reach for if writing ever cannot keep up with the camera — fewer levels, or build
the coarse ones behind the acquisition rather than in step with it, at the cost of a
zoomed-out view that lags a little behind the run.

#### The subtlety that is easy to get wrong

Two tiles written at the same moment are unsafe when they **share a piece of image** — not
when they overlap each other. Those are different things, and confusing them is the kind of
mistake that leaves no trace.

Where two writers share a piece, each reads it, each adds its own tile to its own copy, and
each writes the whole piece back, so whichever finishes second erases the other's
contribution. Nothing reports it; the picture simply comes out with parts missing.

The trap is that two tiles can sit well apart, not overlapping at all, and still both fall
inside one piece of image — which is just as destructive. A guard that holds back
overlapping tiles therefore lets exactly the wrong pairs through. The writer here widens
each tile's claim to whole pieces before comparing, and it claims by the pieces of the
*smallest* copy, since those cover the most ground and the finer ones nest inside them.

This was found by a test rather than by reasoning, which is the argument for having it:
`zmart_storage/tests/test_canvas.py` writes four tiles at once and checks that the strip
belonging to each one alone survives.

#### What it costs elsewhere

The viewer pays nothing worth minding, but two other readers do.

**Analysis has several images to read instead of one.** Asking for the pixels around a cell
becomes "read that region from four images and combine them", which puts the joining-up
back into the analysis path. That wants a small helper next to the writer, so analysis code
can ask for a region and be handed one array without knowing there were four. It is not
built yet.

**Anything else that opens the data sees four images.** A colleague's tool, or napari, will
show four layers rather than one and will not know they belong together. Each is a valid
OME-NGFF image saying honestly what it is, so nothing is broken — but assembling them is
knowledge that lives here rather than in the files.

Neither is a reason against it for a run whose overlap is worth keeping. Both are reasons to
write a single fused image afterwards if the data is going to be handed on, which is
Decision 1b's original recommendation and is unaffected.

The writer is `zmart_storage/canvas.py`, deliberately outside the viewer: the drivers know
instruments, the viewer knows pictures, and neither should have to know how a run is laid
out on disk.

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
never written as empty.

That measurement is the reason the first one is safe to rely on: over-estimating the
declared size is not a decision anybody is stuck with, because a run that somehow
outgrows what it declared can still be extended. It is an escape hatch and not the
design — the writer declares its room at the start and does not grow it, because
growing changes the shape, and changing the shape makes a viewer following the run
re-read the frame on screen each time. Declare generously and the hatch is never
needed.

The one thing that is **not** allowed is extending *backwards* past the origin.
That would shift every index by one and invalidate every chunk already written. So
the origin goes at a corner of the region and growth only ever goes outward.

### How big to make the canvas

Since declared space is free and the shape can be raised later, the temptation is to
declare something enormous and never think about it again. That is nearly right across
the specimen, and wrong in depth, and the difference between the two is worth reading
before choosing a number: **declare the stage travel the experiment can actually use in
y and x, and declare in z the depth the run means to image.** A stage's range across the
specimen is generous next to a specimen without being absurd; its range in depth is not,
for the measured reason below.

Two things scale with the declared size rather than with the data. One of them is a
matter of taste. The other has since been measured, and it is a good deal sharper than
this document used to say — sharp enough that the advice below had to change.

**The brightness measurement, which is the one that bites.** The window an image first
appears with is measured from the smallest copy in the pyramid. That copy is still far
too large to read whole on a real acquisition, so a bounded sample is taken instead:
four planes, spread evenly through the depth, each cropped to a square about the middle.
Spreading the samples evenly through the depth is exactly right for an ordinary stack,
where every plane holds specimen. On a canvas it is a trap, because most of the declared
depth was never imaged, and a sample plane landing in never-imaged space reads as
nothing but zeros.

Depth is where this bites, for a reason that is easy to walk past: **the smaller copies
shrink an image in y and x only.** Depth is carried at full length on every level, which
is right in itself — a stack of a few hundred planes has nothing to spare — but it means
the coarsest copy of a canvas declared to the stage's travel is a very tall, very thin
thing, and the four sampled planes are spread across the whole of that travel while the
specimen occupies one band somewhere inside it.

The arithmetic is unforgiving, and the measurement agrees with it. The four planes sit at
the top, at the bottom, and at the two thirds between, so they stand a third of the
declared depth apart. A band of imaged specimen is certain to be caught only while it is
thicker than that gap — which is to say, **only while the declared depth is no more than
about three times the depth actually imaged.** Measured on a canvas imaging sixty-four
planes, with the specimen in the middle of the canvas, which is where a run puts it:

| declared depth | times what was imaged | of the sample, imaged | window that came out |
| --- | --- | --- | --- |
| 64   | 1×   | 100% | (3557, 4194) |
| 128  | 2×   | 50%  | (3430, 4096) |
| 192  | 3×   | 25%  | (3275, 4027) |
| 224  | 3.5× | 0%   | **(0, 1)** |
| 2048 | 32×  | 0%   | **(0, 1)** |

Past that point every sampled plane misses the specimen, every value read is zero, and
the volume window, the histogram and the contrast slider's Auto button all come back as
`(0, 1)` — which is not a window that is slightly wrong, but no usable range at all. The
script is `viz_studio/measure_declared_room.py`, and it confirms the reassuring half of
the story in the same table: the bytes on disk are **identical** across every row of it.
Declaring generously really is free of everything except this.

Width is far more forgiving, and for a pleasant reason: the sample is cropped *about the
middle*, and the middle of the stage's travel is roughly where a specimen sits. The same
measurement over-declared y and x eight-fold and the window came back sound.

**The opening view.** The viewer opens showing the whole declared extent, so a large
over-declaration leaves the specimen as a few pixels in the middle of an empty field.
This one is only a nuisance — the operator can zoom — but it does look like a fault
rather than a choice.

A canvas a little larger than the specimen avoids both, and leaves growth as the rare
answer to a genuine surprise rather than something relied upon — which suits it, since
growth is the one operation with a restriction attached.

### If the experiment does not say: use the stage limits

An experiment should state the region it means to cover, because it usually knows —
that is the same decision as choosing where to image and at what magnification. But
it will not always say, and a viewer that refuses to open until someone fills in a
number is no use at the microscope.

**So where no canvas is given, the canvas is the stage's own travel limits.**

This is a good default rather than a resigned one, for two reasons — and it carries one
qualification, in depth, which was measured after the default was chosen.

It is already known. The travel limits are established during setup, before any
imaging, because the instrument needs them to keep from driving into its own end
stops. Nothing has to be guessed or asked for.

It cannot be too small. The stage physically cannot reach outside its limits, so no
tile can ever land beyond the canvas — which means growth is not merely rare, it is
impossible, and the one operation with a restriction attached never has to happen.
The origin sits at the low end of travel in each spatial axis, so there is nothing
behind it either.

**Across the specimen, it is not too large.** A stage's range in y and x is a few
centimetres, which is generous next to a specimen without being absurd — and the
brightness sample is cropped about the middle of what is declared, which is roughly
where the specimen sits. Measured at an eight-fold over-declaration in each of y and x,
the window came out sound.

**In depth it is too large, and this is the one place the default has to be qualified.**
A stage travels a few millimetres in z where a stack is a few hundred microns, so
declaring the travel is routinely ten to fifty times the depth actually imaged — well
past the three-fold bound measured above. A canvas declared that way opens its volume
view, its histogram and its Auto button with no usable range at all, and it does so
silently.

So the default holds in y and x, and **in depth the canvas is declared to the depth the
experiment means to image**, with room to spare, rather than to the stage's whole travel.
That is a number an experiment nearly always has, because it is the stack it asked for;
it is only the extent across the specimen that a run genuinely may not know in advance.
Depth also does not need the same generosity, because the reason for declaring generously
— that the stage may wander further across the specimen than planned — does not apply to
a stack whose range the experiment chose.

Where the imaged depth genuinely is not known, declare the travel and give each channel
a brightness window in its `omero` block. That is honoured for the plane view and costs
no read at all. Be aware that it is only half a cure today: the volume window and the
histogram are still worked out from pixels whatever the block says, so they will still
come back empty. That gap is recorded in `viz_studio/NEXT_STEPS.md` and closing it would
make a declared window a complete answer.

The cost of the default is otherwise honest and small: an experiment covering one corner
of the stage gets a canvas larger than it needed, so it opens zoomed further out than
ideal and its first brightness measurement is taken from a sparser picture. An experiment
that cares can say so and get something tighter. One that does not care still works.
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
- **Closing what is not being used**, and having that genuinely give the memory back. This
  one is built: closing an acquisition drops everything the server had remembered about
  those stores — their descriptions, their frame counts, the brightness measured from their
  pixels, and the small files already handed to the page. Before that, memory only ever grew,
  so somebody working through one folder after another kept every folder they had visited
  until they quit the viewer, which made "close what you are not using" advice the viewer
  did not honour.

So the speed of a large folder of separate positions is accepted rather than engineered
around. The two mechanisms proposed to engineer around it are both rejected — a window of
only the positions in view (see the note in `engine.js`) and fusing finished positions into
a copy (Decision 1b) — and this is the reason: neither was worth its complexity once the
operator could simply open less.

Note what this does *not* argue against. Writing into one image as the run goes, also in
Decision 1b, makes a folder faster to open by a wide margin and is what we are aiming for.
It is a different thing entirely: it changes how the data is written in the first place
rather than adding a second copy of it or a second idea of what is on screen, and it makes
the viewer's work smaller rather than cleverer.

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

**Decided, and written above:** one store per position with its place in its own metadata,
for runs that keep their tiles; one image written into as the run goes, for runs that do not
need the overlap back, which is what we are aiming for; a timelapse that grows its own
length; one data type per image; how the layer list is organised; how much is open being the
operator's choice and never the viewer's; and what caching follows from all of it.

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
