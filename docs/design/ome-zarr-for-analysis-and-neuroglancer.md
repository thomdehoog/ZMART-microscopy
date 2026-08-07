# Is our OME-Zarr ready for analysis as well as for viewing?

Written 7 August 2026, by opening the files our writer produces with somebody
else's library rather than with our own reader.

The viewer work settled how an OME-Zarr should be arranged so that Neuroglancer
can draw a run of thousands of positions as one picture. That question is
answered. This document asks the other half of it: **can the same files be
analysed** — opened by an ordinary Python imaging library, segmented, and written
back to — without a biologist having to convert anything first.

The library used for the test is [ngio](https://github.com/BioVisionCenter/ngio)
(version 1.0.0) from the BioVision Center in Zurich. It reads and writes OME-Zarr,
it is what the Fractal analysis framework is built on, and it is strict: it checks
an image against the format's own rules and refuses to open one that breaks them.
That strictness is what makes it a good witness. Our own reader and our own writer
share whatever misunderstanding we happen to have, so they always agree with each
other; a stranger's library does not.

Everything below was measured on a small run written by `zmart_storage`, not
reasoned about. The branch under test is
`claude/frame-rate-stores-scaling-cngfct`, which is where the storage and viewer
work lives; `main` does not yet carry `zmart_storage` at all.

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

## The questions this raises, and what I would do

### Should the analysis output go inside the OME-Zarr or beside it?

**Inside, whenever the format has a place for it.** Segmentations belong in
`labels`, measurements belong in `tables`; both are part of OME-Zarr, both are
where ngio, Fractal, napari and Fiji look for them, and the measurement above
shows our own viewer already finds a label written there.

The rule we already follow is the right one and only needs stating more precisely:
**things the format has a place for go inside; things it has no place for go
beside.** `zmart-links` and `zmart-coverage` are ours and stay outside every
`.ome.zarr` folder, because putting an unrecognised file inside one makes zarr
warn whoever opens it. That is not a reason to keep *labels* outside — they are
not ours, they are the format's.

### Should we use the HCS plate layout?

We do not today. A run writes a plain group of position images:

```
overview.ome.zarr/
  0/ 1/ 2/            the view — descriptions only
  positions/
    overview_pos00000.ome.zarr
    overview_pos00001.ome.zarr
```

There is no `plate` or `well` metadata anywhere. (The commit that says "let one
folder hold a whole plate" is about putting the positions inside the view's
folder, not about the high-content-screening layout.)

**My recommendation: leave it as it is for now, and revisit it only for genuine
multiwell work.** The reasons are practical rather than principled:

- The plate layout addresses images by row and column — `B/3/0`. A smart
  experiment on a light-sheet or a confocal images wherever the specimen is, and
  forcing arbitrary stage positions into a grid of well names invents structure
  that the experiment does not have.
- It buys nothing for viewing. Neuroglancer does not read plate metadata; it reads
  one multiscale image. The view is what solves that, and it would still be
  needed.
- It buys real things for analysis — ngio and Fractal pipelines iterate over
  wells and fields natively — but only when the specimen genuinely sits in a
  plate.

Where it *would* pay off is exactly the case our position labels already
anticipate: `K` is a carrier and `M` is a compartment, so a real multiwell run has
a well to name. If plate-based analysis becomes something people want, the
honest move is to write plate metadata **as well**, over the same position images,
rather than to rearrange anything. It is metadata, not a different layout.

### Does this hold up for overlapping tiles and for mesoSPIM?

This is the strongest argument for making the correction rather than working
around it.

Tiles acquired with deliberate overlap cannot share one canvas, because one voxel
holds one value and the overlapping halves would write over each other. That is
why `zmart_storage/cropped.py` exists: it keeps every tile whole in an image of
its own and trims copies into the canvas for the viewer. Which means **the
per-tile images are the only complete record of an overlapping run** — the
stitcher has to read them, and it reads them through `ngff-zarr` or ngio.

An overlapping run whose tiles all claim to sit at the stage's zero is not
slightly wrong, it is unusable: every tile lands on top of every other and no
stitcher can recover the arrangement. The same is true of a mesoSPIM transfer,
where a specimen is many overlapping tiles by construction.

So the per-dataset position is not a tidiness point. It is what makes overlapping
acquisitions — the ones we most need other people's software for — analysable at
all.

### Which generation of OME-Zarr should a run be written in?

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
not measured here: a view hands a position's own chunk file to the browser
exactly as it is, and once chunks are bundled a chunk is no longer a file of its
own. The writer already bundles only the full-size copy and its comments say why,
so the thinking has been done — but it deserves a test against the viewer rather
than an assumption.

### Extending the analysis pipelines to OME-Zarr

`smart-analysis` runs each step as a plain `run(pipeline_data, **params)` function
in a named conda environment, passing either file paths or pickled objects between
steps. That design already suits OME-Zarr well, and the change is small:

- Add a step that takes a **store path and a position name** instead of an image
  array, and opens it with ngio. The engine's existing `data_transfer:
  "file_paths"` mode is exactly this, and it means large images stop being pickled
  between processes — a position is opened where it is used and read lazily.
- Have the segmentation step write its result with `derive_label(...)` and its
  measurements with `add_table(...)`, into the position it read. As measured
  above, the viewer then shows the segmentation with no further work.
- Put `ngio` in the analysis environment only. The acquisition side needs nothing
  new — `zmart_storage` writes with `zarr` and `numpy` and should stay that way.

None of this needs the pipeline engine itself to change.

---

## What I would change, in order

1. **Write each position's place on the stage beside each resolution, not once
   for the image as a whole.** The correction is already written on
   `claude/ngff-translation-per-dataset`; it needs merging into the storage
   branch, plus the small guard in `linked.py` so the view is not moved twice.
   Without this, no position we write can be opened by ngio, `ngff-zarr`,
   `multiview-stitcher`, or anything built on them.
2. **Say in the operator-facing docs that analysis results belong inside the
   position** — `labels` and `tables` — and that only our own two folders stay
   outside.
3. **Keep a test that opens our files with somebody else's library.** The one on
   the correction branch (`test_other_tools_can_read_us.py`) does this with
   `ngff-zarr`. An ngio equivalent would be worth having beside it, because ngio
   validates strictly and would have caught this the day it was introduced.
4. **Make 0.5 the default in every writer**, not only in `start_a_run`, and
   correct the documentation that still says 0.4.
5. **Leave the plate layout alone** until a genuine multiwell experiment asks for
   it, and then add plate metadata over the positions rather than moving them.

## How to repeat the measurement

The probe scripts are not committed — they are a few dozen lines and are quicker
to rewrite than to maintain. In outline: write a run with
`zmart_storage.positions.start_a_run`, then

```python
import ngio
container = ngio.open_ome_zarr_container(position_path)
image = container.get_image()
print(image.axes, image.shape, image.pixel_size.zyx, image.channel_labels)
```

against a position and against the view, on both OME-Zarr generations. A position
that opens and reports its real voxel size is the whole test.
