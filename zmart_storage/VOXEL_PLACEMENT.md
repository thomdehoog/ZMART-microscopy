# Where a voxel sits: the corner or the middle?

Investigated on 2026-07-31. **Nothing was changed as a result.** This is a record
of what the standard says, what this writer means, and what two readers do with
it, so that the question does not have to be worked out again from scratch — and
so that nobody later "corrects" the writer to match whatever they happen to be
viewing it with.

## The question, in one sentence

An image has to say where in the specimen its first voxel sits. Saying that means
giving one number per axis — but a voxel is not a point, it is a small box, so the
number could mean either **the corner of that box** or **the middle of it**, and
the two differ by half a voxel.

## Why half a voxel is worth this much trouble

At the magnification a viewer normally chooses for itself, half a voxel is about
half a screen pixel, which nobody would ever notice. It stops being invisible when
you zoom in past the finest stored resolution: the half-voxel keeps its size in
the specimen while a screen pixel gets smaller, so the error grows on screen.
Measured in this project's own viewer at eight times full resolution, the edge of
the picture sat four screen pixels away from where the operator's drawing put it.

That is exactly the moment it matters. Zooming in that far is what an operator does
when they are asking whether a tile's picture really landed inside the square they
laid out — and four pixels is enough to make a correctly placed tile look wrong, or
a misplaced one look fine.

There is a second consequence, and it is arguably the more important of the two.
An image is stored several times over at halving resolutions, and the convention
decides whether those copies line up with one another. That is a property of the
data itself rather than of any particular viewer, so it would be worth getting
right even if nothing ever drew the image.

## 1. What the OME-Zarr specification says

**It does not say.** This was checked against the specification's own source text
for both generations this writer produces — version 0.4 and version 0.5 — and
neither contains the words "centre", "center" or "corner" anywhere in its
description of coordinates. The only appearance of "origin" in either document is
inside the sentence quoted below.

Here is the whole of what each version says about the numbers in question. The two
are word for word identical:

> Each dictionary in "datasets" MUST contain the field "coordinateTransformations",
> which contains a list of transformations that map the data coordinates to the
> physical coordinates (as specified by "axes") for this resolution level. […]
> They MUST contain exactly one `scale` transformation that specifies the pixel
> size in physical units or time duration. […] It MAY contain exactly one
> `translation` that specifies the offset from the origin in physical units. If
> `translation` is given it MUST be listed after `scale` to ensure that it is given
> in physical coordinates.

and, for the block that applies to every resolution at once:

> Each "multiscales" dictionary MAY contain the field "coordinateTransformations",
> describing transformations that are applied to all resolution levels in the same
> manner. The transformations MUST follow the same rules about allowed types,
> order, etc. as in "datasets:coordinateTransformations" and are applied after
> them.

So the specification is precise about *arithmetic* — a scale, then a translation,
in that order, then whatever the multiscale block adds — and silent about what the
resulting number is the position **of**. "The offset from the origin" leaves the
origin itself undefined.

This is not an oversight nobody has noticed. It is an open question in the
standard's own issue tracker: [ome/ngff issue #89, "Define the origin w.r.t. the
pixel corner or center"](https://github.com/ome/ngff/issues/89), opened in February
2022 and **still open** at the time of writing, more than four years later. The
issue records that the two communities really do differ — corners are the common
choice in two-dimensional image handling, middles in three-dimensional imaging and
in formats such as NIfTI and DICOM — and recommends the middle. That
recommendation has not been written into the specification.

The honest summary is therefore: **the standard does not settle this, and two
readers can disagree about the same file without either of them being wrong.**

## 2. What this writer currently means

The writer means the **corner**, and it says so in `canvas.py`, where the block
that places an image is introduced with "Every image in a run shares the same
corner". The coverage record in `coverage.py` counts the same way: a tile written
at origin `(0, 0, 0)` with a shape of `(2, 128, 128)` is recorded as covering
voxels 0 up to but not including 128, which is a statement about edges rather than
about middles.

It is applied consistently across resolutions, and in the simplest possible way:
**every resolution is given exactly the same translation**, namely the run's
`origin_um`, and the levels are told apart only by their `scale`. Read back off
disk from a run declared with 0.35 µm voxels starting at x = 900.25 µm, four
levels deep, both generations produce the same thing:

```
multiscale-level: translation [0.0, 0.0, 10.0, 250.5, 900.25]
level 0: scale [1.0, 1.0, 2.0, 0.35, 0.35]
level 1: scale [1.0, 1.0, 2.0, 0.7,  0.7 ]
level 2: scale [1.0, 1.0, 2.0, 1.4,  1.4 ]
level 3: scale [1.0, 1.0, 2.0, 2.8,  2.8 ]
```

No level carries a translation of its own. The way the smaller copies are *built*
agrees with the corner reading too: `_write_smaller_copies` takes every second
voxel starting from the tile's low edge, so a coarse voxel's value is the value of
the fine voxel at the low corner of the block it stands for, and the coarse voxel's
extent begins exactly where that fine voxel's extent begins.

## 3. Are the levels self-consistent? Worked out, and checked against disk

Take the x axis of the run above: voxels 0.35 µm across, the image beginning at
900.25 µm. The file maps index 0 of every level to 900.2500 µm. What that means for
where each level's first voxel actually lies depends entirely on the convention:

| level | voxel size | corner convention: first voxel covers | centre convention: first voxel covers |
|-------|-----------|----------------------------------------|----------------------------------------|
| 0 | 0.35 µm | [900.2500, 900.6000) | [900.0750, 900.4250) |
| 1 | 0.70 µm | [900.2500, 900.9500) | [899.9000, 900.6000) |
| 2 | 1.40 µm | [900.2500, 901.6500) | [899.5500, 900.9500) |
| 3 | 2.80 µm | [900.2500, 903.0500) | [898.8500, 901.6500) |

The answer is plain, and it is the useful result of this investigation.

**Under the corner convention our levels are exactly consistent.** Every level
begins at 900.2500 µm. Each coarse voxel covers precisely the fine voxels it was
built from — one voxel of level 3 spans exactly the eight voxels of level 0 that
were averaged down into it — so the copies are perfectly nested and the picture
does not move as a viewer switches between them while zooming.

**Under the centre convention they are not.** Each level begins half of its own
voxel earlier than the number given, so the coarser the level the further out it
starts: level 3 begins 1.4 µm before level 0, which is four voxels of the
full-resolution image. A reader following that convention will therefore draw the
zoomed-out view slightly displaced from the zoomed-in one, and the displacement
changes with the zoom.

Both facts follow from the same choice — giving every level the same translation —
so this is one decision with two consequences, not two separate problems.

It is worth noting what the alternative would have to be. To make the levels line
up *under the centre convention*, each level would need a translation of half of
its own voxel added on: `origin + scale/2`. That is not a fudge for any particular
viewer; it is simply how you write "the image begins here" when the number means a
middle rather than a corner. The two arrangements describe exactly the same picture
in the specimen. They differ only in which convention the reader is expected to
apply.

There is a further consideration that points the same way, and it concerns the
specification's own example rather than any reader. The example `multiscales`
block shipped with the standard gives three resolution levels with a `scale` each
and **no translation at all** — which is also what the reference implementations
ordinarily write. Under the corner reading, that plain pyramid is consistent: every
level starts at nought. Under the centre reading it is not: each level would start
at a different negative coordinate, so the standard's own example would describe a
pyramid whose levels do not line up. That does not make the corner reading
official, but it does mean the corner reading is the one under which the ordinary
output of the format makes sense.

## 4. What two readers actually do

Recorded so that whoever writes an adapter knows what to expect. Neither of these
is evidence about what is *correct*; common practice among readers is worth
knowing and is not the standard.

**Neuroglancer places a voxel by its middle.** In
`neuroglancer/lib/datasource/zarr/ome.js`, after assembling each level's transform,
it subtracts half a voxel of that level from the translation:

```js
for (const scale of scales) {
  const t = scale.transform;
  for (let i = 0; i < rank; ++i) {
    let offset = 0;
    for (let j = 0; j < rank; ++j) offset += t[j * (rank + 1) + i] * 0.5;
    t[rank * (rank + 1) + i] -= offset;
  }
  ...
}
```

In plain terms: it treats the number in the file as the position of the **middle**
of the first voxel, and works out the corner from it. It does this for every
resolution level separately, using that level's own voxel size — which is why, on
a file written the way ours is, a coarse level is placed further out than the fine
one, by exactly the amounts in the right-hand column of the table above.

This project's viewer already compensates for this, in
`viz_studio/options/neuroglancer-under/viewer.js`, by shifting the finest level
back by half a voxel. That compensation is correctly placed: it converts between
two stated conventions at the reader, which is where a disagreement about
convention belongs. It reaches only the finest level, because the coarser ones are
placed while the description is being read and cannot be adjusted afterwards.

**Viv does not read the placement at all.** Its OME-Zarr loader
(`@vivjs/loaders`) reads `multiscales` only for the dataset paths and the axis
names; the string `coordinateTransformations` does not appear anywhere in the
`@vivjs` or `@hms-dbmi` packages installed here. What it uses for voxel size comes
from OME-XML metadata (`meta.physicalSizes`) when there is any, and then only as a
ratio between the axes to correct for anisotropy. Resolution levels are placed by
scaling tile indices by `2 ** level` in the full-resolution pixel grid, which is
corner-aligned nesting by construction.

So Viv is consistent with the corner reading, and it never sees our translation at
all — an image drawn by Viv sits wherever its pixel grid puts it, not where the
stage said it was.

## 5. Recommendation

**Change nothing in the writer.** Keep giving every resolution the same
translation, meaning the corner of the first voxel, and leave the half-voxel
conversion in the viewer's adapter where it already lives.

The reasoning, in order:

The specification does not settle the question, so there is no standard to move
towards. Following one would be the first and last consideration if there were
one; there is not, and issue #89 has been open for four years, which is fair
warning that a decision is not imminent.

Given that freedom, the right test is internal consistency, and the corner
convention is the one our data is already consistent under. The levels nest
exactly, the smaller copies are built from the corners they claim, and the coverage
record counts edges the same way. The centre convention would make all three of
those things slightly wrong unless every level's translation were changed to
match — a change to what is on disk, made in order to arrive back at the same
picture.

Adjusting the file to suit a reader is the wrong instinct in any case. A file
should state what is true; a reader that assumes the other convention should
convert on the way in. If we shifted the translations to suit neuroglancer we would
then be half a voxel wrong for Viv, and for any reader that follows the corner
reading, and we would have no way to say which of them we meant.

What is worth doing instead is **saying so**. The whole difficulty is that our
writer means corners and never writes that down, so each reader is being reasonable
about a description that does not say. Recording it here, and in `canvas.py`
itself, costs nothing and is the part that stops the question being reopened.

## The cost of leaving it, stated plainly

A reader that assumes middles — neuroglancer, today — will draw a coarse
resolution level up to half of its own voxel before where we mean it, and our
viewer's compensation only reaches the finest level. In practice that means a view
zoomed a long way out can be up to half a screen pixel out of place, and a view
zoomed in is exact. That is the right way round: the zoomed-in view is the one
somebody is using to judge whether a tile landed where it should.

If that ever stops being good enough, the fix is to extend the compensation in the
viewer to the coarser levels, not to move the numbers in the file.
