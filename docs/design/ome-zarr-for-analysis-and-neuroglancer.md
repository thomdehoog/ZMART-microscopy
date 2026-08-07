# One OME-Zarr that can be both viewed and analysed

Written 7 August 2026, by opening the files our writer produces with somebody
else's library rather than with our own reader.

The viewer work settled how an OME-Zarr should be arranged so that Neuroglancer
can draw a run of thousands of positions as one picture. That question is
answered. This document asks the other half of it — **can the same files be
analysed**, without a biologist having to convert anything first — and then
follows the one problem that turns out to sit underneath both halves at once:
what to do about tiles that overlap.

The library used for the test is [ngio](https://github.com/BioVisionCenter/ngio)
(version 1.0.0) from the BioVision Center in Zurich. It reads and writes OME-Zarr,
it is what the Fractal analysis framework is built on, and it is strict: it checks
an image against the format's own rules and refuses to open one that breaks them.
That strictness is what makes it a good witness. Our own reader and our own writer
share whatever misunderstanding we happen to have, so they always agree with each
other; a stranger's library does not.

Everything measured below was measured on a small run written by `zmart_storage`,
not reasoned about. The branch under test is
`claude/frame-rate-stores-scaling-cngfct`, which is where the storage and viewer
work lives; `main` does not yet carry `zmart_storage` at all.

**Contents**

1. [The short answer](#the-short-answer)
2. [What was measured](#what-was-measured)
3. [Where analysis results belong](#where-analysis-results-belong)
4. [The plate layout, and why we do not use it](#the-plate-layout-and-why-we-do-not-use-it)
5. [Which generation of OME-Zarr to write](#which-generation-of-ome-zarr-to-write)
6. [Overlap: the problem underneath both halves](#overlap-the-problem-underneath-both-halves)
7. [Where ngio helps, and where it would hurt](#where-ngio-helps-and-where-it-would-hurt)
8. [How ngio fits the analysis engine](#how-ngio-fits-the-analysis-engine)
9. [Fractal: not the tool for us, but worth reading](#fractal-not-the-tool-for-us-but-worth-reading)
10. [What I would change, in order](#what-i-would-change-in-order)

---

## The short answer

**One thing is wrong, it is small, and the fix is already written.**

A position — the image that actually holds the pixels, the one we tell everybody
to point their analysis at — cannot be opened by ngio today. It fails validation
before a single voxel is read. The view, which holds no pixels, opens perfectly.
That is exactly the wrong way round.

The cause is one line in `zmart_storage/canvas.py`, and the correction already
exists on the branch `claude/ngff-translation-per-dataset`. With it applied,
everything works: positions open, the pixels come back unchanged, the voxel size
and the place on the stage are right, and a segmentation written by ngio shows up
in our own viewer without any further work.

Underneath that sits a larger question that no library can answer for us — what a
tile *owns* when tiles overlap — and section 6 sets out an answer that serves the
viewer and the analysis with one decision instead of two.

---

## What was measured

### As the latest branch stands today

| opened with ngio | result |
| --- | --- |
| the view (`overview.ome.zarr`) | opens |
| a position (`positions/overview_pos00000.ome.zarr`) | **refused** |

The refusal is a validation error, not a missing feature. An OME-Zarr image says
where it sits in the world with a short list of transformations, and the format
requires that list to begin with a **scale** — how large one voxel is — optionally
followed by a **translation** — where the image's corner sits. Our positions write
a translation on its own, with no scale in front of it, in the block that
describes the image as a whole. ngio reads that list, finds a translation where a
scale must be, and stops.

This is not an ngio quirk. `viz_studio/INTEROP.md` records the same family of
problem being found on the microscope computer against `ngff-zarr`, which
`multiview-stitcher` and a good part of the Python imaging world read through.
Two independent libraries, the same disagreement.

The view escapes it because `zmart_storage/linked.py` already writes the view's
position beside each resolution instead — see `_say_where_each_resolution_sits`,
whose docstring explains exactly why. The positions were simply never given the
same treatment.

### With the correction applied

Applying `claude/ngff-translation-per-dataset` to the writer, and making the
view's own writer leave a translation alone when one is already there — otherwise
the two both write one and the picture is moved twice — gives this:

| opened with ngio | result |
| --- | --- |
| the view | opens; axes `t, c, z, y, x`; voxel size `(2.0, 0.35, 0.35)` µm; **reads back all zeros** |
| a position | opens; same axes and voxel size; channel named `488`; every pixel back as written |

Both OME-Zarr 0.4 and 0.5 behave identically, so the choice of generation does not
enter into it.

The view reading back as zeros is expected and is not a fault: a view holds no
chunk files of its own, because every piece of it is one of the positions'
pieces. This is the one genuine divergence in the whole arrangement, and it is
already written down in `viz_studio/HOW_OURS_DIFFERS_FROM_OME_ZARR.md`. **Point
analysis at the positions, never at the view.** With the correction in place, that
sentence becomes true rather than aspirational.

### Can analysis write its results back?

Yes, and this is the part that turned out better than expected.

Working on a single position, ngio was asked to do what a segmentation pipeline
does: read the image, threshold it, write the result back as a label image, and
write a table of regions beside it. All of it worked:

```
labels now       : ['nuclei']
label read back  : (1, 1, 64, 64) matches: True
tables now       : ['image_ROI_table']
```

The position folder afterwards holds `0`, `labels` and `tables`, and it still
opens as an ordinary image with its pixels untouched.

Then the same position was handed to **our own viewer's reader**, which had never
been told any of this had happened:

```
is_store          : True
axis_names        : ['t', 'c', 'z', 'y', 'x']
voxel_size        : (2.0, 0.35, 0.35)
channels          : [{'name': '488', ...}]
label_images      : ['nuclei']
```

The viewer found the segmentation on its own. A pipeline written against ngio, in
its own conda environment, can segment a run and the operator will see the result
in the viewer with no glue code between them.

---

## Where analysis results belong

**Inside the image, whenever the format has a place for it.** Segmentations belong
in `labels`, measurements belong in `tables`; both are part of OME-Zarr, both are
where ngio, Fractal, napari and Fiji look for them, and the measurement above
shows our own viewer already finds a label written there.

The rule we already follow is the right one and only needs stating more precisely:
**things the format has a place for go inside; things it has no place for go
beside.** `zmart-links` and `zmart-coverage` are ours and stay outside every
`.ome.zarr` folder, because putting an unrecognised file inside one makes zarr
warn whoever opens it. That is not a reason to keep *labels* outside — they are
not ours, they are the format's.

---

## The plate layout, and why we do not use it

We do not use it today. A run writes a plain group of position images:

```
overview.ome.zarr/
  0/ 1/ 2/            the view — descriptions only, no picture of its own
  positions/
    overview_pos00000.ome.zarr
    overview_pos00001.ome.zarr
```

There is no `plate` or `well` metadata anywhere. (The commit that says "let one
folder hold a whole plate" is about putting the positions inside the view's
folder, not about the high-content-screening layout that OME-Zarr calls a plate.)

**Recommendation: leave it as it is, on every instrument.** The reasons are
practical rather than principled:

- The plate layout addresses images by row and column — `B/3/0`. A smart
  experiment on a light-sheet or a confocal images wherever the specimen is, and
  forcing arbitrary stage positions into a grid of well names invents structure
  that the experiment does not have.
- It buys nothing for viewing. Neuroglancer does not read plate metadata; it reads
  one multiscale image. The view is what solves that, and it would still be
  needed.
- It buys real things for analysis — ngio and Fractal pipelines iterate over wells
  and fields natively — but only when the specimen genuinely sits in a plate.

Where it *would* pay off is exactly the case our position labels already
anticipate: `K` is a carrier and `M` is a compartment, so a real multiwell run has
a well to name. If plate-based analysis becomes something people want, the honest
move is to write plate metadata **as well**, over the same position images, rather
than to rearrange anything. It is metadata, not a different layout.

### Decided: no plate layout, on any instrument

Amended 7 August 2026. On being told the instrument list includes a **Molecular
Devices ImageXpress**, a high-content screener, this document briefly recommended
writing plate metadata for that one instrument. **The maintainer's decision is not
to**, and on reflection it is the better call: it keeps one arrangement for every
microscope rather than a special shape for one of them, which is the principle the
rest of the project is built on.

**What that gives up is narrower than it sounds.** Not the ability to analyse a
plate — only `ngio.open_ome_zarr_plate` and any Fractal task that insists on a
plate. ngio opens individual images perfectly well, as measured above, and Fractal
was already decided against for reasons of its own.

**Well and field identity does not need the plate layout.** It needs to be
*recorded*, and the run-level table of §8.4 is the place:

| position | well | field | cells | mean intensity |
| --- | --- | --- | --- | --- |
| `pos00417` | B03 | 2 | 143 | 812 |

Analysis then groups by `well` in one line, without any plate metadata, without a
row-and-column folder hierarchy, and without a second arrangement to keep working.
The screener's runs stay exactly the same shape as the confocal's and the
light-sheet's.

The workflow's position label already carries what those columns need — `K` for
the carrier, `M` for the compartment, `V` for the view within it — so the
screener's driver has only to report them, which it must do anyway.

---

## Which generation of OME-Zarr to write

**0.5, and it should be the default everywhere.** Both generations were measured
and ngio opens either one identically, so nothing about analysis forces the
choice — but three things point the same way. 0.5 is where the format is going,
Neuroglancer has read it since late 2023, and it is the generation that allows
many chunks to be bundled into one file, which matters a great deal when a long
run would otherwise leave millions of small files on a filesystem that handles
them badly.

The writer is only half-way there. `zmart_storage.positions.start_a_run` already
defaults to `"0.5"`, but `canvas.TileCanvases` and `cropped.TilesAndCanvas` still
default to `"0.4"`, and `viz_studio/HOW_OURS_DIFFERS_FROM_OME_ZARR.md` still
describes 0.4 as the default. Those three should be brought into line with the
first, keeping 0.4 available for anyone who has to read a run with older software.

One thing to check before bundling is switched on for real runs, because it was
not measured here: a view hands a position's own chunk file to the browser exactly
as it is, and once chunks are bundled a chunk is no longer a file of its own. The
writer already bundles only the full-size copy and its comments say why, so the
thinking has been done — but it deserves a test against the viewer rather than an
assumption.

---

## Overlap: the problem underneath both halves

Microscopists acquire with the tiles deliberately overlapping, ten or fifteen per
cent being usual. The overlap is not waste — it is the only evidence of where the
stage *really* put each tile, as opposed to where it said it did, because the
strip two tiles both photographed can afterwards be compared.

That one fact causes trouble twice, and the two troubles look different enough
that it is easy to solve them separately and end up with two answers that
disagree.

### The trouble for analysis: counting the same cell twice

If ten per cent of a tile is also on the neighbouring tile, then every cell in
that strip is segmented twice, measured twice and counted twice. A run of a
thousand tiles reports perhaps a tenth more cells than the specimen contains, and
no amount of care later can tell which of two measurements of the same cell to
throw away.

The obvious answer is to analyse only the part of a tile that is not shared. It is
also the wrong shape of answer, and it is worth saying why: a cell sitting on the
seam would then be cut in half, and half a cell measured is worse than no cell
measured, because it looks like a real result.

**The right answer is to separate what is segmented from what is owned.**

> Segment the **whole** tile, overlap and all, so every cell is seen whole and
> with its proper surroundings. Then keep only those objects whose **centre**
> falls inside the tile's owned rectangle.

Every object in the run is then counted exactly once, because its centre lands in
exactly one owned rectangle — the owned rectangles butt up against one another and
cover the ground with no gaps and no double cover. A cell straddling the seam is
measured properly on whichever tile owns its centre, and discarded on the other
one after it was measured whole, not clipped. Nothing about the segmentation
changes. What changes is one filter at the end.

### The trouble for viewing: one value per point

An image holds a single value per point, so writing overlapping tiles into a
single image means the second tile written replaces the strip it shares with the
first. `viz_studio/DATA_LAYOUT.md` measures the loss at 21% of everything the
camera recorded on a run overlapping by an eighth. And the viewer really does want
a single image, because Neuroglancer builds a drawing layer per source: a thousand
separate positions drew twenty-four frames in five seconds where one image managed
255.

**This half is already built.** `zmart_storage/cropped.py` writes the run twice —
every tile whole in a small image of its own, overlap intact, for the stitcher;
and every tile trimmed at the midline into one canvas for the viewer. Trimmed that
way the tiles butt up and touch nowhere, so nothing is written over.
`HANDOVER_overlapping_runs.md` is the record of what was decided and built, the
tests pass, and the sweep was taken from one tile to ten thousand.

Two things about that are worth carrying forward:

- **Every frame rate in those documents came from a software renderer**, on a
  machine with no graphics card. They are not yet facts about the viewer. Running
  `viz_studio/measure_the_overlapping_run.py` on real hardware is the first thing
  to do.
- **The no-copy path is the part still unfinished.** `zmart_storage/linked.py`
  shows the same run without copying a single voxel, but only when the tiles land
  on an exact grid; a real stage drifts a voxel or two and such a run is currently
  refused rather than shown, so it falls back to copying the whole run a second
  time. That is a stage-drift problem rather than an overlap problem, and
  `LINKING_INSTEAD_OF_COPYING.md` sets out how to finish it.

### One seam, two consumers

Here is the point of putting both troubles in one section. The rectangle the
viewer trims a tile down to and the rectangle analysis lets a tile own are **the
same rectangle**, and it is already computed — `Trimming.of(tile_shape,
tile_step)` in `zmart_storage/cropped.py`:

```
overlap on an axis        = tile size − stage step
what comes off each edge  = half of that
```

with tiles at the edge of the raster keeping their outer strips, because there is
no neighbour there to replace what would be cut. Nothing about it is chosen or
switched on: it is worked out from two numbers the run could not have started
without, so there is no setting that can be wrong for a whole run before anybody
notices.

So this is not the same problem twice. It is **one seam with two consumers** — the
canvas the viewer draws, and the ownership rule the pipeline filters by. Decide it
once, in the writer, and the two agree by construction, which also means a cell can
never be shown on one tile and counted on another.

The practical step is to record it where a pipeline can read it: write the owned
rectangle into each tile as an OME-Zarr **region-of-interest table**, at
`tables/owned_ROI_table`, beside the whole-image table ngio already writes. A
pipeline then opens a tile, segments it whole, filters by that table and writes its
results back — and never needs to know how the seam was derived.

### Where the ownership rule breaks, honestly

- **An object bigger than the overlap.** With ten per cent of a 2048-pixel tile
  you own about 200 pixels of slack, and a nucleus at 30 pixels is comfortably
  safe. Something large enough to be clipped in *every* tile is recovered by
  nothing short of stitching. A cheap guard is to flag any kept object that
  touches the tile's border; those are the ones to distrust, and they should be
  rare.
- **The seam assumes the stage told the truth**, which is the very thing the
  overlap exists to disprove. For analysis that only shifts which tile owns a
  borderline object, which is harmless. For viewing it is a visible line. Same
  seam, different tolerance — and it is why the archive keeps every tile whole, so
  a stitcher can settle it properly afterwards.
- **Irregular positions.** This is a rule for a regular raster. Smart target scans
  that overlap arbitrarily have no single "step", so ownership there needs
  something else — first-wins by acquisition order, or nearest-centre in stage
  coordinates. Worth deciding before such a run turns up rather than after.

If none of that is tolerable, the alternative is to analyse every tile
independently and merge objects across the seams by matching them in stage
coordinates. It is strictly more correct and meaningfully more work, and it is
worth reaching for only if the border-touching flag starts firing often.

---

## Where ngio helps, and where it would hurt

### First, the question underneath: is it really our bug?

Before deciding whether to depend on a library, it is worth knowing whether the
library was right. ngio refuses our positions — but a strict library can be
strict about the wrong thing.

It was not. `ngff-zarr` ships the **official OME-Zarr schemas**, and our files were
checked against them directly rather than against anybody's opinion:

```
BROKEN (as the latest branch writes a position): INVALID against the official 0.4 image schema
FIXED  (per-dataset translation):                VALID
```

So this is a specification violation, not a disagreement. ngio was right to
refuse, `ngff-zarr` was right to ignore the transformation, and the files we write
today are simply wrong in a way our own reader could never have told us.

That single result is the strongest argument in this document for depending on
somebody else's library at all — in some role.

### Should we use ngio? Yes, in three roles out of four

**1. As a check on what we write — yes, and this is the highest value for the
smallest cost.** ngio found in minutes a fault that had been in the writer for
some time and that no test of ours could catch, because our reader and our writer
shared the misunderstanding. Add it to the development requirements and let the
test suite open every kind of image we write. Alongside it, validate against
`ngff-zarr`'s bundled schemas, which are the format's own words rather than a
library's reading of them.

**2. As the analysis library — yes**, in the analysis conda environment. See
below for what it gives us.

**3. As the way we read other people's data — yes.** A mesoSPIM transfer or a
collaborator's plate opens with the same few lines as our own runs.

**4. As the thing that defines our format — no.** We should keep writing the
metadata ourselves and checking it against the schemas, rather than writing
through ngio's writer. The reason is concrete rather than proud: **ngio 1.0.0
declares only 0.4 and 0.5**, while `ngff-zarr` 0.41 already supports 0.4 through
0.6 and ships a `scene.schema`. Writing through ngio would quietly make its
version ceiling our version ceiling, on exactly the part of the format — scenes
and coordinate systems — that section 6 of the recipe says we most want to grow
into. Reading through it costs us nothing of the kind.

The short form: **let ngio read our files and judge them; do not let it write
them.**

### Where it helps, in detail

ngio is the right tool for part of this and the wrong tool for another part, and
the line between them is clear enough to state.

**Use it on the analysis side, completely.** It has `Roi` and `RoiSlice`,
`get_roi` and `set_roi`, `MaskedImage`, and ready-made iterators
(`SegmentationIterator`, `FeatureExtractorIterator`, `ImageProcessingIterator`).
Cropping a region out of a tile and placing it somewhere becomes a few lines
rather than hand-rolled slicing, segmenting region by region is a loop it already
writes for you, and results go back with `derive_label` and `add_table`.
Everything described in "What was measured" above was done this way.

**Use it for foreign data too.** A mesoSPIM transfer arrives as a folder of
overlapping tiles somebody else wrote, in whatever arrangement they chose. Reading
those with ngio, trimming them, and writing one canvas the viewer can open has no
live constraint on it at all, so nothing about ngio's copying gets in the way.
That is the job `viz_studio/PLAN_showing_many_stores_as_one.md` describes, and
ngio would shorten it considerably.

**Do not put it on the acquisition path.** Three reasons, and the third is the one
that would bite:

- ngio copies pixels. `zmart_storage/linked.py` exists precisely so that a run's
  voxels are written once and never again.
- It is not built for appending while a viewer watches. The careful parts of our
  writer — leaving unwritten chunks unwritten, replacing the list of pointers in a
  single step so a reader never catches it half-written, counting how many moments
  have really been recorded — are exactly what that arrangement depends on.
- It brings `dask`, `anndata`, `polars`, `pyarrow`, `scipy`, `pandas`, `pillow`
  and `aiohttp` with it: 61 packages installed in the test environment here. That
  is entirely normal for an analysis environment and not something to add to the
  microscope computer, where `zmart_storage` today needs `zarr` and `numpy` and
  nothing else.

That split also fits how the analysis engine already works: ngio lives in the
analysis conda environment, and the acquisition side never imports it.

---

## How ngio fits the analysis engine

The `smart-analysis` engine was built to do two things: **queue analysis that runs
while the microscope is still going**, and **run a recipe whose steps need
different Python environments**. It is worth saying plainly how ngio sits with
each, because the answer to both is "it does not get in the way", and that is not
obvious from the outside.

**ngio has no runtime of its own.** It is a library a step imports, like
`scikit-image` or `numpy`. There is no server, no scheduler, no daemon and no
background process. So the queue is untouched: `engine.submit(queue, ...)`,
`engine.status(queue)` and `engine.results(queue)` keep working exactly as they
do, and nothing about how work is handed out or drained changes.

**The multiple-environment part actually gets easier.** Today a step running in
another conda environment receives either a JSON payload of file paths or a
pickle, and a pickle of a large image has to be written, sent and read back at
every environment boundary. An OME-Zarr position removes the question: the pixels
stay on disk, each environment opens the same folder, and only a path crosses
between processes. That is the engine's existing `data_transfer: "file_paths"`
mode, used for what it was designed for.

**And most of what the payload carries today is already inside the file.** The
target-acquisition workflow currently submits something like this per overview:

```python
engine.submit(queue, {
    "image_path": ..., "tile_id": ..., "tile_stage_xy_um": ...,
    "source_pixel_size_um": ..., "source_image_size_px": ...,
    "image_to_stage": ...,
})
```

Every one of those spatial fields — the pixel size, the image size, where the tile
sits on the stage, how image coordinates become stage coordinates — is something
an OME-Zarr position states about itself, in the very transformations this
document is about. Pointing a step at a store means it reads them from the image
rather than being told them alongside, which removes a whole class of quiet fault:
a payload that disagrees with the file it describes.

**Running while the microscope is going still works**, and works a little better.
A position is a complete, valid image the moment it is written, so it can be
queued the moment it lands rather than at the end of a run. And because results go
back into the position as `labels` and `tables`, the operator sees a segmentation
appear in the viewer while the next position is still being acquired — the
measurement earlier in this document shows the viewer's reader finding an
ngio-written label with nothing told to it.

### What the change looks like

- Add a step that takes a **store path and a position name** instead of an image
  array, and opens it with `ngio.open_ome_zarr_container(...)`.
- Have the segmentation step write its result with `derive_label(...)` and its
  measurements with `add_table(...)`, into the position it read.
- Have it read `tables/owned_ROI_table` and drop objects whose centre falls
  outside, so an overlapping run is not counted twice.
- Put `ngio` in the analysis environment only, never in the acquisition one.

None of this needs the pipeline engine itself to change.

### The one thing to be careful about

Two processes writing into the same store at the same time. Different positions
are different folders and do not interfere, so the acquisition writer appending a
new position while a pipeline segments an earlier one is safe. Two analysis steps
writing into the *same* position is not, and the queue is what keeps that from
happening: one item at a time per position. It is worth stating in the recipe
rather than relying on it by accident.

---

## Fractal: not the tool for us, but worth reading

The same group that writes ngio also writes
[Fractal](https://fractal-analytics-platform.github.io/), which does something
that sounds like what our analysis engine does: it runs modular tasks over
OME-Zarr, each task in its own environment, orchestrated locally or on a cluster.
It is reasonable to ask whether we should simply use it.

**We should not, and the reason is in its own description.** Fractal is built to
convert terabytes of finished image data into OME-Zarr and process it at scale,
which means it assumes the dataset exists before the analysis starts, and it is
happiest with high-content screening plates on a cluster. Smart microscopy is the
opposite arrangement: the analysis has to answer *while the specimen is still on
the stage*, within seconds, so that the microscope can be told where to look next.
A framework designed to be scheduled is the wrong shape for a loop that has to
close before the next position is acquired.

The second reason is simpler and just as decisive: **we do not have a cluster.**
Everything here runs on the microscope computer — one machine, usually Windows,
with whatever graphics card is in it, writing to a local or network drive. Half of
what Fractal is for is distributing work across machines, and none of that is
available to us or needed by us. It is also why the small-files problem matters so
much more here than it would on a cluster filesystem, and therefore why OME-Zarr
0.5 and its bundling are worth having.

That does not make it uninteresting. Several things in it are worth taking, and
they are cheap:

- **Tasks declare what they take and what they give back.** A Fractal task is
  described in a machine-readable manifest, built from the function's own typed
  arguments, so a workflow can be checked before it runs. Our steps carry a small
  `METADATA` dictionary and are otherwise checked by running them. Declaring the
  contract means a recipe with a mistake in it fails at submission rather than at
  step four, twenty minutes into an acquisition — which on a live run is the
  difference between an annoyance and a lost specimen.
- **The unit of parallel work is one image, not one job.** Fractal separates tasks
  that run per image from tasks that need the whole set, and that distinction is
  exactly what makes it safe to start analysing while more images are still
  arriving. Our queue already works position by position; saying out loud which
  steps are allowed to be per-position and which need the whole run would make
  that safety explicit rather than incidental.
- **Tasks pass references, never pixels.** A Fractal task receives the address of
  a store and returns a small description of what it changed. That is the same
  arrangement recommended above, and it is worth knowing it is proven at scale
  rather than merely reasonable.
- **Region-of-interest tables are the bookkeeping unit.** Fractal uses ROI tables
  to say what a task should work on. That is independent confirmation that
  `owned_ROI_table` is the right mechanism for the overlap problem rather than an
  invention of ours.
- **Their task code is a reference implementation.** `fractal-tasks-core` contains
  OME-Zarr conversion, illumination correction and registration written by people
  who argue about this format for a living. Even taking nothing from it, it is the
  place to check a doubt about how something should be written.

And there is a payoff that only exists if the correction in this document is made.
If our runs are OME-Zarr that ngio opens, then Fractal becomes *available* without
being adopted: the live loop stays with our own engine, and a heavy offline pass
over a finished experiment — whole-run feature extraction, registration, a proper
stitch — can be handed to Fractal on the same files, with nobody converting
anything. That is the whole argument for writing the format properly, stated in
one sentence.

---

## What I would change, in order

1. **Write each position's place on the stage beside each resolution**, not once
   for the image as a whole. The correction is already written on
   `claude/ngff-translation-per-dataset`; it needs merging into the storage
   branch, plus the small guard in `linked.py` so the view is not moved twice.
   Without this, no position we write can be opened by ngio, `ngff-zarr`,
   `multiview-stitcher`, or anything built on them — and for an overlapping or
   light-sheet run, where a stitcher is the only way to read the data at all, that
   is not a tidiness point but the difference between usable and not.
2. **Record the owned rectangle as `tables/owned_ROI_table` in every tile.** It is
   already computed for the canvas; writing it down is what makes the viewer's
   crop and the analysis filter the same decision rather than two that happen to
   agree.
3. **Say in the operator-facing documents that analysis results belong inside the
   position** — `labels` and `tables` — and that only our own two folders stay
   outside.
4. **Keep tests that judge our files by somebody else's rules.** Two of them, and
   they catch different things. Validate every kind of image we write against
   `ngff-zarr`'s bundled OME-Zarr schemas, which are the format's own words — that
   is what proved the current fault is a violation rather than a difference of
   opinion. And open every one of them with ngio, which is the check that a real
   analysis library will accept what we produce.
5. **Make 0.5 the default in every writer**, not only in `start_a_run`, and
   correct the documentation that still says 0.4.
6. **Run `viz_studio/measure_the_overlapping_run.py` on a machine with a real
   graphics card**, because nothing measured about drawing so far was measured on
   one.
7. **Finish the no-copy path for a drifting stage**, so that an ordinary run stops
   falling back to writing every voxel twice.
8. **Record the well and the field as columns of the run-level table**, so a
   screening run can be grouped by well without the plate layout. No instrument
   writes plate metadata.

---

## How to repeat the measurement

The probe scripts are not committed — they are a few dozen lines and quicker to
rewrite than to maintain. In outline: write a run with
`zmart_storage.positions.start_a_run`, then

```python
import ngio
container = ngio.open_ome_zarr_container(position_path)
image = container.get_image()
print(image.axes, image.shape, image.pixel_size.zyx, image.channel_labels)
```

against a position and against the view, on both OME-Zarr generations. A position
that opens and reports its real voxel size is the whole test.
