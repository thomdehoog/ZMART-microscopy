# Work order: a view that copies nothing, at any zoom

Written 5 August 2026. This corrects a claim made earlier the same day, in this
repository, which turned out to be wrong — and the correction removes the last
thing a view had to write.

---

## The claim that was wrong

`LINKING_INSTEAD_OF_COPYING.md` said, and `zmart_storage/linked.py` repeated, that
the zoomed-out copies of a picture cannot be pointed at:

> the zoomed-out copies, because shrinking averages across the join between tiles
> and no existing piece holds that answer

**It does not average.** `zmart_storage/canvas.py:1562` makes each smaller copy with

```python
smaller = image[:, ::factor, ::factor]
```

which takes every second voxel, or every fourth, and throws the rest away. Nothing
is combined. So a voxel of a zoomed-out copy comes from exactly **one**
full-resolution voxel, and therefore from exactly **one** tile. There is no join to
average across, because there is no averaging anywhere.

That was checked rather than reasoned about. Taking a whole picture, shrinking it,
and comparing each region against the same tile shrunk on its own gives an identical
answer at every level tried. A tile's own zoomed-out copy **is** the view's
zoomed-out copy in that tile's region.

## What follows from it

A view has been writing about a quarter of the picture — the zoomed-out copies — and
pointing at the rest. On a five-terabyte run that is more than a terabyte written to
look at data that already exists.

**It does not have to write anything at all.** If each tile carries its own
zoomed-out copies, the view can point at those exactly as it points at the
full-resolution pieces, and the view becomes pure description from top to bottom.

The zoomed-out numbers still have to exist somewhere — nothing can conjure a
shrunken picture out of nothing. What changes is *where* they live and whether they
are a **second copy**:

| | full resolution | zoomed out | second copy of anything? |
|---|---|---|---|
| write one canvas | written | written | yes, all of it |
| a view as built today | pointed at | written | yes, a quarter |
| a view over tiles that carry their own copies | pointed at | pointed at | **no** |

In the last row the zoomed-out numbers are inside the tiles, where they are useful
in their own right: a tile with its own copies opens on its own, in any viewer,
without reading the whole thing. They are part of the data being kept rather than a
duplicate of it.

---

## What the microscope has to write

This is the whole of it, and it belongs in the acquisition rather than anywhere
downstream. **One OME-Zarr store per position**, and nothing else — no canvas, no
second copy, no combining step.

Four rules about how each store is written. Three of them are ordinary good
practice; the fourth is the one that is easy to get wrong.

**1. Give each tile its own zoomed-out copies.** As many as the view will show.
This is what makes the row above possible, and a tile written this way is a proper,
independently viewable OME-Zarr rather than a fragment.

**2. Cut the tiles into pieces much smaller than the tile** — 128 or 256 voxels
across `y` and `x`. The writer in `zmart_storage/cropped.py` currently sets one
piece per plane (`canvas.py:949`), which makes a tile a single indivisible block and
nothing can be pointed at inside it.

**3. Overlap neighbours by at least two pieces.** A tile can only supply pieces it
fills completely, so it loses up to one at each edge; two pieces of overlap covers
that whatever the stage does. With pieces of 128 that is 256 voxels, around 12% of a
2048-voxel tile, which is an ordinary overlap for stitching anyway.

**4. Begin every tile a whole number of *coarse* pieces from the run's corner.**
This is the sharp one. For the full-resolution pieces to line up, a tile has to begin
on a multiple of the piece size. For the *zoomed-out* pieces to line up as well, it
has to begin on a multiple of the piece size **times the largest shrink factor** —
because a tile placed three voxels along picks different voxels than the view would,
which was measured and is not a rounding difference but a different picture.

With pieces of 128 and four copies kept, the largest shrink is eight, so positions
must be multiples of `8 × 128 = 1024` voxels.

The stage will not do that on its own, and it does not have to. **Pad each tile's
low edge** by however far the stage overshot the previous boundary, and record the
padded corner as the tile's position. The specimen does not move by a single voxel;
what moves is where the tile's own grid begins. This is the same fix
`PLAN_showing_many_stores_as_one.md` sets out, applied to a coarser grid, and it was
measured there to work with no change to `linked.py` at all.

---

## Tasks, in the order to do them

### 1. Stop refusing a tile that carries its own copies

**Where:** `zmart_storage/linked.py`, `_what_the_tiles_are` (around line 389), which
today raises:

> keeps 3 copies of its picture, and a view can only be built over tiles that keep
> one. A tile is a single field of view, so there is nothing to zoom out from

That reasoning is exactly backwards now. Those copies are the thing that lets a view
write nothing. Record how many copies each tile has, require every tile to have the
same number, and refuse only a tile that has **fewer** than the view means to show.

### 2. Point at them

**Where:** `_fill_in_the_zoomed_out_copies`, and the pointer file.

A tile's zoomed-out copies are laid out the same way as its full-resolution one,
with every number halved per level. So a tile that supplies pieces `at` in the view
at full resolution supplies the pieces at `at // 2` in the first smaller copy, and so
on. Given rule 4 above those divisions come out whole, and the writer should refuse
loudly when they do not rather than rounding.

Write the number of pointed-at levels into `zmart-links.json` and let the reader
halve, rather than writing a separate list per level. The note in
`viz_studio/backend/linking.py` about holding the list by tile explains why: a list
that grows per piece does not survive a real run, and the same applies per level.

### 3. Teach the reader

**Where:** `viz_studio/backend/linking.py`, which today answers only for level `0`
and leaves every other level to be found on disk.

It should answer for every pointed-at level, working out the tile's piece by halving
as above. Raise `LINKS_VERSION` to 4, so that a reader which does not know about
pointed-at copies refuses the view outright rather than showing a picture that is
sharp when zoomed in and blank when zoomed out.

### 4. Tests

- **A view over tiles with their own copies writes nothing.** Count the files in the
  view's folder: it should hold its description and the pointer list, and no picture
  at any level.
- **Every level matches a written canvas, voxel for voxel**, read through the
  viewer's own server. `test_the_linked_view_matches_the_canvas.py` already does this
  for the full-resolution picture and is the right place.
- **A tile that does not begin on a coarse boundary is refused**, with a message
  naming the position that would work.
- **A tile with fewer copies than the view shows is refused.**
- **A run still being acquired grows the same way**, since adding a tile now writes
  no pixels at all — it should be faster than the 0.87 ms already measured, not
  slower.

### 5. What to run before saying it is done

```
python -m pytest zmart_storage/tests/ -q
python -m pytest viz_studio/tests/test_the_linked_view_matches_the_canvas.py -q
python -m pytest viz_studio/tests/test_a_growing_view_is_read_as_it_grows.py -q
```

---

## What this does not change

- **The full-resolution alignment rule still applies**, and a drifted run is still
  refused. This work makes the zoomed-out copies free; it does not make a drifted
  run open. That is `PLAN_showing_many_stores_as_one.md`.
- **Decimation is not the only way to shrink a picture.** Averaging would give a
  smoother zoomed-out view, and it would make all of this impossible, because an
  averaged voxel near a join really does come from two tiles. If anyone ever changes
  `canvas.py:1562` to average, this whole arrangement goes with it — which is worth
  a comment at that line, and is task 1's real risk rather than anything in the
  linking.
