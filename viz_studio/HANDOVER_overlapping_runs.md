# Runs whose tiles overlap: what was decided, what was measured, what to do next

Written 5 August 2026, for whoever picks this up — and particularly for whoever
first runs it on a machine with a graphics card, because that is the one thing this
session could not do.

**Status.** The reasoning is settled and written down. The code exists and is
**unproven**: it was committed in `a9b7b5c` as a snapshot, at the operator's
request, so it could be pulled onto another machine. Nothing in it has been seen to
pass a test.

---

## Start here: the one thing to do first

Pull the branch onto a machine with a real graphics card and run:

```
python viz_studio/measure_the_overlapping_run.py
```

Everything measured in this repository about drawing was measured on a software
renderer, which has no graphics card at all. That makes every absolute frame rate
here meaningless, and it makes the **volume** measurements worse than meaningless,
because ray-marching through a specimen is exactly what a graphics card is for and
exactly what software rendering is worst at. A volume number from the sandbox reads
as "three dimensions are too slow" when it only means "this box has no card in it".

So the numbers that matter — frames a second in the volume, how a contrast drag
feels with ten thousand tiles open — can only come from your hardware. If your
figures disagree with any in this document, **yours are the real ones**.

`HANDOVER_3D.md` has the three commands for getting the volume view up.

---

## The problem, in one paragraph

Tiles are acquired overlapping, on purpose, because a stitcher compares the shared
strip to work out where the stage really went. But an image holds one value per
point, so writing overlapping tiles into a single image destroys that strip —
`DATA_LAYOUT.md` Decision 1b measures the loss at 21% of everything the camera
recorded. And the viewer wants a single image, because Neuroglancer builds drawing
layers per source and every one takes part in every frame: a thousand separate
positions draw at 24 frames in five seconds where one image manages 255.

So: keep the overlap, or draw quickly. That was the trade, and it looked
unavoidable.

---

## What was decided: show less, rather than blend

**Do not show the overlapping part.** Where two tiles share a strip, trim half of it
from each and let them meet at the midline. The left tile supplies the left half,
the right tile the right half.

Cropped tiles do not overlap, so they can go into one image and nothing is written
over. The raw tiles are kept separately, with their overlap intact, for the
stitcher.

Three things follow, and they are why this was chosen over everything else tried:

**Every hard question disappears.** No blending, no deciding which tile wins, no
chessboard of four images, no counting neighbours, no limit on how much tiles may
overlap. All of those existed only because two tiles claimed the same ground.

**It works for any arrangement.** A raster, scattered positions, a target scan
returning to the same field — a canvas does not care. This matters, because the
alternatives did care, and this project's runs are not rasters.

**The picture is often better.** The edge of a tile is where illumination falls off,
so trimming the edges throws away each tile's worst pixels and keeps its best.

The cost is accepted rather than solved: the view trusts the stage, so where the
stage was a few pixels out there is a small step at a join. That is what stitching
is for, and it happens afterwards, from tiles that still have their overlap.

### The rule is worked out, not declared

There is no flag. The crop on each axis is

```
crop = max(0, tile_shape - tile_step) / 2
```

so a run whose tiles already butt up is trimmed by nothing and behaves exactly as
before. A flag can be set wrongly and go unnoticed for a whole run; the tile size
and the stage's step are facts the acquisition already had to state.

Three conditions on it, all of which should be enforced rather than assumed:

- **The cropped tile must be a whole number of chunks.** A 2048 tile with 256 of
  overlap crops to 1792, which is seven chunks of 256. A round-sounding 10% crops
  to 1843.2, which is a whole number of nothing, and that is how misplacement
  arrives quietly.
- **The overlap must be an even number of voxels**, or half of it is not a whole
  voxel.
- **Perimeter tiles keep their outer edges.** A tile with no neighbour on one side
  has nothing to replace what you would cut there, so trimming it loses a thin
  border around the whole run. This looks like a special case and is the common
  one.

---

## What was measured, and where the scripts are

Everything below was taken on a machine with four processors and no graphics card.
None of it involves drawing, so it is trustworthy as far as it goes.

| what | number | script |
|---|---|---|
| stitching one piece of picture live | 647 ms, against 4.6 ms to read it | `measure_live_fusion_cost.py` |
| the same, several at once | 2.7× more pieces a second, and each piece slower | same |
| putting cropped tiles in place on read | about 6 ms a piece | `measure_tiles_in_one_store.py` |
| the same at ten thousand tiles | 13.4 ms on a raster, 6.9 ms scattered | `measure_ten_thousand_tiles.py` |
| the cost of compression | roughly 1.5× aligned, roughly 2× not | `measure_compression_cost.py` |

`INTEROP.md` §5 explains why live stitching is slow, and it is not what you would
guess: `multiview-stitcher` already detects when a tile's move is a plain
whole-voxel translation, stores the answer as `fix_dims`, and then never reads it —
so an ordinary mosaic is resampled through a general transformation when moving it
would have been a copy.

---

## What was rejected, so it is not proposed again

- **Stitching live, in front of the viewer.** Correct, and a hundred times too slow.
  Doing several at once raises the rate and lengthens the wait for any one piece,
  which is the wrong quantity: a viewer waiting to draw waits for one piece.
- **Dealing tiles across four images** so neighbours never share one. Already
  measured in `DATA_LAYOUT.md` at nothing lost and no loss of drawing rate — but
  only for a regular raster with overlap under half a tile, needing eight images if
  a run tiles in depth, and needing *N* images when *N* tiles revisit one field.
  That last case is this project's own workload.
- **Keeping tiles in slots and placing them as they are read.** Measured and quick,
  and it makes the store meaningless to any software but ours. `PLAN_keeping_the_overlap.md`
  weighs it properly. It stays on the table as an optimisation — the same view
  without the duplicate disk — but not as the first thing to build.
- **Blending in Python, per piece.** The formula is right and the place is wrong.
  Blending belongs in the shader if it is wanted at all, and with cropping it is not
  needed.

---

## What is still open

- **The code is unverified.** `a9b7b5c` is a snapshot taken mid-run. A verified
  commit with the sweep should sit above it; if it does not, treat `a9b7b5c` as
  scaffolding.
- **The duplicate disk.** Writing raw tiles and a canvas costs roughly twice the
  space. The canvas is scaffolding and can be deleted once a run is stitched, but
  nobody has measured what the second write costs during a fast acquisition.
- **The volume, everywhere.** No arrangement in this repository has a frame rate in
  three dimensions, because none could be taken honestly here.
- **Rotation in the volume does not work**, and its brightness is computed with the
  flat view's window. Both are broken independently of anything here, both are well
  described in `HANDOVER_3D.md`, and both are the smallest clearly specified work
  available.

---

## Three mistakes this session made, kept so they are not repeated

**A measurement flattered itself.** The by-level table in `TILES_IN_ONE_STORE.md`
sampled the first twelve pieces in reading order, which are all in the easiest row
of the picture, and reported six tiles touched where the honest answer is nine. Two
scripts in this repository disagreed — one said six, the other nine — and both were
published before anyone noticed. Cross-checking two measurements against each other
is nearly free.

**Numbers were quoted with no script behind them.** The compression figures sat in a
plan for several hours with nothing in the repository that could produce them.
`measure_compression_cost.py` exists now. A number without a script is an opinion.

**A design was proposed without reading what had already been decided.** The
four-image arrangement was measured and written down in `DATA_LAYOUT.md` long ago,
and a whole plan was built without mentioning it. In a repository that records its
rejections as carefully as this one does, that record is the first thing to read.
