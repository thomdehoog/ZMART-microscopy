# Reading other people's OME-Zarr, and writing ours so others can read it

Written 3 August 2026, on the microscope computer, after opening a real mesoSPIM
transfer in the operator page for the first time and then reading how
[multiview-stitcher](https://github.com/multiview-stitcher/multiview-stitcher)
does the same job.

Nothing here is fixed. Two things found the same day **are** fixed and are in
`6c54c81`; they are described first only because the rest of this document does
not make sense without them.

---

## What was already put right

**An axis the store does not have.** `viv-under` asked Viv for `{t, c, z}` on
every read. Every acquisition our writer produces declares five axes whether or
not the run had a moment or a colour to put in them, so that constant is correct
on all eight fixtures and cannot be wrong on any of them. A light-sheet transfer
declares `z, y, x`; asking it for `t` is refused rather than ignored, so every
piece failed to load and the page reported itself perfectly content over an empty
window. It now names only the axes the store declares.

**A position stated where nothing looked.** OME-Zarr allows a transformation
beside each resolution *and* another beside the multiscale block that holds them,
the second applying to the result of the first. Our writer uses the outer place;
the transfers other instruments send carry the inner one and no outer block at
all. `originUm` read the outer place only, so every foreign image reported itself
as beginning at the stage's zero and a transfer of many tiles drew all of them on
top of one another. Both are now composed the way the format says.

That second one is the 898 micrometre fault of `options/contract.md` §1a
returning in the one form its fix did not cover: the readers had been taught this
project's convention rather than the format's.

---

## 1. Our files are mispositioned by a large part of the ecosystem — **fixed**

**This was the finding with the widest blast radius. It is now fixed, and the
description below is what it used to do.** `zmart_storage/canvas.py` writes the
translation beside each resolution, which is the place the format makes
compulsory, and no longer writes one beside the multiscale block. Images written
from now on open correctly in `ngff-zarr`, and so in `multiview-stitcher` and the
rest of the ecosystem built on it.

`zmart_storage/tests/test_other_tools_can_read_us.py` holds it there. It writes a
run at a known corner, reads it back with `ngff-zarr` rather than with our own
reader, and fails if the corner comes back as anything else. Confirmed to fail
against the old writer, reporting a corner of 0.0 where 10.0 was declared — which
is exactly the fault described below.

**One correction to the advice this section used to give**, because following it
would have caused a second fault rather than curing the first. It said that
"writing it in both places costs nothing and is understood by both conventions."
That is not so. A reader applies the multiscale-level transformation to the result
of the per-resolution one, so an image stating its position in both places is
placed **twice as far** from the stage's zero as it really is. Neuroglancer
composes them exactly this way — `datasource/zarr/ome.js`, where
`parseOmeMultiscale` multiplies the two together — so writing both would have
broken our own viewer as well as everyone else's. The position must be stated in
one place only, and the per-resolution one is the place to choose.

Removing the outer block is safe for the same reason, checked in the same file:
`parseOmeCoordinateTransforms` returns the identity when the block is absent.

Everything below is the original finding, kept because the mechanism is worth
understanding and because the same shape of fault can return.

multiview-stitcher does not parse NGFF itself. It calls
`ngff_zarr.from_ngff_zarr`, and in `ngff-zarr`'s
`py/ngff_zarr/v04/zarr_metadata.py::_from_zarr_attrs` the scale and translation
are read **only** from `datasets[i]["coordinateTransformations"]`. The
multiscales-level block is kept on the `Metadata` object for round-tripping and
validation and is never composed into the image's position — verified by reading
the tree; outside `structural_validation.py` and the `_to_v0X` converters nothing
consumes it.

So `ngff-zarr` has the exact mirror of the bug we just fixed. We read only the
outer block; it reads only the inner one. **Neither composes, and the two fail on
each other's files.**

`zmart_storage/canvas.py` writes `scale` per dataset (line 1746) and
`translation` at the multiscales level (line 1667). The consequence is concrete
and it is ours, not theirs:

> Every ZMART store, opened by multiview-stitcher — or by anything else built on
> `ngff-zarr`, which is a fair slice of the Python imaging ecosystem — has every
> one of its acquisitions placed at the origin, stacked on top of one another.

Today's fix made us read everyone else's files correctly. It did nothing to make
our files readable by anyone else.

**What was done about it.** The translation is written per dataset, and the
multiscales-level block is gone. It is written in one place only, for the reason
given at the top of this section: the two compose, so saying it twice would place
the image twice as far out. This relies on our own reader continuing to compose
both, which it does and should.

### 1a. And while that file is open: the half-voxel question

multiview-stitcher writes a **centre-of-pixel** translation per level —
`ngff_utils.calc_ngff_coordinate_transformations_and_axes` shifts each level by
`(factor - 1) * spacing / 2` so that pixel *centres* nest, and
`fusion/_core.py:1012` echoes the convention by name.

Our writer takes the other choice — one translation for every level, corner
convention — and `zmart_storage/canvas.py:1654-1666` argues for it well: the
copies nest perfectly, the format is genuinely ambiguous, and a file that shifts
itself to suit one reader is wrong for every other.

The argument is principled and the cost is already written down in our own code.
`options/neuroglancer-under/viewer.js:1060-1078` records that neuroglancer applies
its half-voxel assumption per level, that we can only correct the finest level
from JavaScript, and that a zoomed-out view is therefore up to half a screen pixel
out. That comment already prescribes the cure — "the writer should say which
convention it means, by giving each resolution a translation of half its own
voxel" — and multiview-stitcher is a second, independent implementation doing
exactly that.

Worth reopening. The ecosystem has picked a side.

---

## 2. Culling by declared geometry rather than by the coverage record

`options/RESULTS.md` measures that on a sparse canvas three requests in four are
for ground nobody has imaged — 250 requests to draw one view, 190 of them for
empty room. We answer that with `onlyWhereTheRunHasImaged`, which refuses a tile
whose rectangle misses every region in the `coverage` record.

multiview-stitcher answers it with declared geometry instead.
`fusion/_core.py::_build_spatial_fusion_plan` projects each tile's corners through
its transform, takes the world-space bounding box, pads it, and converts that
straight to a **range of chunk indices** by floor division — `O(N_tiles × ndim)`
rather than `O(N_tiles × N_chunks)` — building a map from output chunk to the
tiles that touch it. A chunk no tile touches then costs one `np.zeros` and no
read at all.

The difference that matters is not the arithmetic, it is what the bound is made
from:

| | ours | theirs |
| --- | --- | --- |
| source | `coverage`, a runtime record of what was written | origin, shape and voxel size, declared in the store |
| foreign stores | no record, so no bound | works unchanged |
| two voxel sizes at once | impossible — one record counts in one image's voxels | per tile, so the question does not arise |

That middle row is why this matters here: a foreign transfer keeps no coverage
record, so today it gets no bound at all. The bottom row is
`options/contract.md` §1a's own admitted gap — "coverage is **one** record for
the whole viewer … so it cannot describe two runs whose voxels are different
sizes", which is why measurement 8 is taken unbounded "for that reason rather
than by choice".

A per-store rectangle computed once at open, from numbers `originUm` and
`voxelSizeUm` already read, would compose with the existing coverage path rather
than replace it. It cannot reach zero waste — a declared canvas is larger than the
tiles inside it, which is the whole point of declaring it up front — but it
removes every request for ground *no store claims at all*.

---

## 3. Overlap: we are right for the nested case and wrong for siblings

Ours is two mechanisms, and only one of them has a counterpart there:

* `onlyWhereTheRunHasImaged` — geometric, from the coverage record.
* `LetTheUnimagedGroundShowThrough` — a shader that multiplies alpha by
  `smoothstep(0.0, 0.02, max(r, max(g, b)))`. **An intensity test.**

multiview-stitcher has one mechanism: every view is resampled with `cval=NaN`, and
`fuse_np` does `weights *= ~isnan(values)` then normalises. That is a *geometric*
validity mask — "is this output pixel inside this view's footprint" — so it is the
counterpart of our coverage bounding. **Our shader has no counterpart there at
all, because they never need one:** knowing each footprint exactly from geometry,
they never have to guess it from brightness.

Their blending is a cosine ramp: a tiny binary mask, distance-transformed once,
resampled through the tile's own transform, then `(cos((1-x)π)+1)/2`, over a
default `blending_widths` of 10 µm in x and y. Because it is a small array pushed
through the same transform as the image, it is nearly free and is automatically
right for rotated tiles and fractional offsets.

**Where we are right and should not change.** For a wide survey and a detail scan
of part of it — the arrangement `contract.md` §1a is built around — later-wins is
the correct semantics, not a compromise. Blending a 10× survey into a 63× detail
scan would be actively wrong.

**Where we are wrong.** For sibling tiles at the same magnification — precisely
the seven-store, three-tile, two-channel mesoSPIM transfer this was tested against
— later-wins gives a hard seam wherever two tiles overlap, discards the second
sample where averaging would have halved the noise, and the intensity threshold
cannot distinguish "never imaged" from "imaged and genuinely dark". The constant
is honestly named `AS_GOOD_AS_NOTHING` and its comment already admits it cannot
tell the two apart. On fluorescence, where most of a field is legitimately near
black, the acquisition underneath bleeds through *inside* imaged ground.

A cosine falloff over N micrometres from the store's own declared rectangle edge
is a shader change of about fifteen lines, needs no coverage record, and would
remove both the seam and the bleed-through in one go — while keeping later-wins
for the nested case, which is what it is for.

---

## 4. A coupling of our own, found while comparing

`options/viv-inside/viewer.js:548` sets `own.umPerVoxel = own.opened[0].umPerVoxel`
and `stretchOntoTheSameWorld` places every acquisition in **voxels of whichever
store the page listed first**. multiview-stitcher's world is abstract physical
space that no view's grid owns.

Ours is the simpler model and it is adequate — an axis-aligned mosaic needs a
diagonal scale plus a translation and nothing more. Two things follow from it
anyway:

* Viv chooses its pyramid level from the width of the model matrix, and rounds. So
  listing the survey first and listing the detail scan first can pick **different
  levels for the same store**. A latent surprise rather than a bug, and worth a
  sentence in `contract.md` §1a.
* A store carrying a rotation or a shear — which NGFF 0.4 cannot express but 0.5
  and neuroglancer both can — would be drawn axis-aligned, in the right *place*,
  silently. A guard that refuses or warns on a transform we cannot represent is
  cheap and would fail loudly instead.

---

## What is worth taking, and what is not

Portable into a browser viewer, in rough order of value:

1. The bounding-box → chunk-index-range arithmetic (§2). Integer arithmetic, no
   dependencies, about twenty lines.
2. The cosine edge ramp (§3), which is two lines of shader once the distance to a
   rectangle's edge is in hand — and for an axis-aligned rectangle that is
   analytic.
3. Multiplying the weight by a validity mask and then normalising, which is
   ordinary premultiplied-alpha blending in WebGL.
4. The centre-of-pixel per-level convention (§1a).
5. The shape of their neuroglancer JSON, including the correction that divides the
   translation column by the output spacing.

Not portable, and not worth trying: everything numeric — the distance transform,
arbitrary-order resampling, the half-space intersections, the DCT content weights,
the Bayesian deconvolution — along with the dask graph and the `VirtualOMEZarr`
server, which needs a live Python process holding the images and so is a server
technique rather than a client one.

---

## Provenance

Read from the `main` tarball of both repositories as of 3 August 2026, locally
rather than through rendered pages. Every claim above about their code was read in
source; the file and function names are given so they can be checked. Claims about
our own code cite the files in this repository at `6c54c81`.
