# How what we write differs from plain OME-Zarr 0.5

Written 5 August 2026. Short, because the honest answer is "hardly at all, in one
important way".

Every image this project writes is an ordinary OME-Zarr image. Open one in napari,
Fiji, `ngff-zarr` or anything else that reads the format and it opens, with the right
axes, the right voxel size and the right place on the stage. Nothing here is a
private format wearing OME-Zarr's clothes.

There is **one** real divergence, and four things that look like divergences and are
not. Knowing which is which matters, because the first one will surprise a colleague
and the others will not.

---

## The one that matters: a view is an image with its pixels somewhere else

A **view** — `overview.ome.zarr` in the layout below — is a complete and valid
OME-Zarr image. It declares its shape, its chunks, its number type, its compression,
its axes, its voxel size and where it sits on the stage. What it does not contain is
the chunk files.

Those live in the positions, and a small file beside the image says which chunk of
the picture is which chunk of which position. The viewer's server reads that and
hands over the position's own file, untouched.

**What another program sees.** Zarr is entitled to treat a missing chunk as unwritten
and fill it from the fill value, and that is exactly what it does. So opening a view
in napari gives you a correct-looking image that is **blank wherever the pixels are
pointed at** — which today is every level, because the positions carry their own
zoomed-out copies and all of them are pointed at.

**This is not a violation.** A zarr array with no chunks written is a legal zarr array
that has had nothing written to it, and every reader handles that gracefully. It is
simply not what a person expects when the folder is named after their experiment.

**So the rule to tell people is short: point other software at the positions, not at
the view.** The positions are ordinary images holding real pixels, each one openable
on its own, and they are where all the data is. The view exists for one purpose —
letting a drawing engine treat ten thousand positions as a single image — and outside
that purpose it has nothing to offer.

---

## The four that look like divergences and are not

**Our own files sit beside the images, never inside one.**

```
experiment/
  overview.ome.zarr/      a view — an ordinary OME-Zarr image, and nothing else
  positions/
    overview_pos00000.ome.zarr    ordinary OME-Zarr images holding the real data
    overview_pos00001.ome.zarr
  zmart-links/            ours — which piece of the picture is which position
  zmart-coverage/         ours — where the run has actually imaged so far
```

`zmart-links` and `zmart-coverage` are not part of OME-Zarr and are not pretending to
be. They are kept **outside** every `.ome.zarr` folder precisely so that the images
stay pure: put a file of your own inside one and zarr tells whoever opens it *"Object
at zmart-links.json is not recognized as a component of a Zarr hierarchy"*, and a
colleague meets a warning about a file they have never heard of. Reading the images
never requires reading ours.

**We write the position beside each resolution, and only there.** OME-Zarr allows
`coordinateTransformations` on the multiscales as a whole *or* on each dataset, and
the two **compose** — write both and the image is moved twice. We write the
per-dataset one, which the format's own examples use and which is the only one a
large part of the Python world reads. Writing it the other way makes `ngff-zarr` and
anything built on it, including `multiview-stitcher`, place the image at the origin
with nothing to say so.

**We shrink by taking every second voxel rather than averaging.** The format says
nothing about how the smaller copies are made, so this is within it. It is worth
stating because it is deliberate and load-bearing rather than lazy: because no voxels
are combined, a zoomed-out voxel comes from exactly one position, which is what lets
a view point at the positions' own zoomed-out copies instead of writing its own.
Averaging would look smoother and would quietly make that impossible.

**We use the `omero` block for channel names, colours and brightness.** That block is
a transitional part of the specification rather than a permanent one, and a future
version of OME-Zarr may put this somewhere else. It is what readers understand today.

---

## Version, and what we ask of a run

**We write OME-Zarr 0.4 by default and 0.5 on request.** 0.4 because almost
everything reads it today; 0.5 because it is where the format is going, and because
it allows several chunks to be bundled into one file, which matters when a run would
otherwise leave millions of small files behind. Both are fully readable here, and
nothing an operator sees changes between them.

**The constraints a run has to satisfy are ours, not the format's.** Positions must
begin on a multiple of the chunk size times the largest shrink, and must all be
written the same way — the same number type, compression, chunk size, axis order and
number of levels. None of that is required by OME-Zarr. It is required for a
position's own file to be handed over as a piece of the picture without touching a
single pixel, and a run that breaks it is refused when the view is built, with a
message saying what would work.

---

## In one paragraph

We write plain OME-Zarr. The positions are ordinary images and hold everything. The
view is also an ordinary image, correct in every respect except that its pixels are
somewhere else — so it draws perfectly in our viewer and comes out blank in anyone
else's. Point other software at the positions. Everything else we add sits beside the
images rather than inside them, so nothing we do makes an image harder for anybody
else to open.
