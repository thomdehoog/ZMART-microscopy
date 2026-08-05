# Runs whose tiles overlap: what was decided, what was measured, what to do next

Written 5 August 2026, for whoever picks this up — and particularly for whoever
first runs it on a machine with a graphics card, because that is the one thing this
session could not do.

**Read this one first.** Several documents were written while this was being worked
out and most of them argue for arrangements that were not built. This is the one
that describes what exists:

| | |
| --- | --- |
| `HANDOVER_overlapping_runs.md` | this file — what was built, and the numbers |
| `LINKING_INSTEAD_OF_COPYING.md` | showing a run without copying it — now built, and what it still needs |
| `PLAN_seam_ownership.md` | the next piece of work, written out step by step: making a linked view open a run off a real stage |
| `ARCHITECTURE.md` §7 | the three layers the whole tool is made of |
| `PLAN_keeping_the_overlap.md` | **superseded** — two arrangements that were weighed and not built |
| `TILES_IN_ONE_STORE.md` | the bench measurements behind all of it |

**Status.** The reasoning is settled, the code exists, and it has now been run. The
snapshot in `a9b7b5c` was taken mid-session with nothing yet proven; this document
has since been brought up to date. Every test in `zmart_storage/tests/test_cropped.py`
and `viz_studio/tests/test_the_cropped_canvas_draws.py` passes on this sandbox, and
the sweep in `measure_the_overlapping_run.py` has been taken from one tile to ten
thousand — the table is under "What the sweep found" below.

Since then a **second** arrangement has been written, which shows the same run
without copying it at all: `zmart_storage/linked.py` builds the view and
`viz_studio/backend/linking.py` answers for it. It passes its tests, and it works
only for runs whose tiles land on an exact grid — a real stage drifts by a voxel or
two and such a run is currently refused rather than shown. That is the next piece
of work and `LINKING_INSTEAD_OF_COPYING.md` sets out how to do it. The measurements
in this document are all from the copying arrangement; the two have not yet been
compared on the same run.

What that still does not tell you is anything about drawing on real hardware, for
the reason immediately below. Read the next section before treating any frame rate
here as a fact about the viewer.

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
chessboard of four images, no limit on how much tiles may overlap. All of those
existed only because two tiles claimed the same ground. (One thing on that list did
have to come back, in a much smaller form: the tiles at the edge of the pattern have
to be recognised, so that their outer edges are not cut. See "The rule is worked
out, not declared" below.)

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

Three conditions on it, all of which are now enforced rather than assumed:

- **The cropped tile must be a whole number of chunks.** A 2048 tile with 256 of
  overlap crops to 1792, which is seven chunks of 256. A round-sounding 10% crops
  to 1843.2, which is a whole number of nothing, and that is how misplacement
  arrives quietly. A run that breaks this is refused when it is declared, and the
  message names the overlaps that would work. The check is asked only where two
  tiles genuinely meet: an axis with no overlap, or one the pattern takes a single
  tile along, has no seam to line up.
- **The overlap must be an even number of voxels**, or half of it is not a whole
  voxel. Also refused when the run is declared, with a step named that would work.
- **Perimeter tiles keep their outer edges.** A tile with no neighbour on one side
  has nothing to replace what you would cut there, so trimming it loses a thin
  border around the whole run. This looks like a special case and is the common
  one.

That last one needed something the first draft of this document did not allow for,
and it is worth saying plainly because it is the one place the design gained a
moving part. To know that a tile is at the edge of the pattern you have to know
where the pattern ends, and a tile arriving cannot be asked about tiles that have
not arrived yet. So a raster states its shape once, as `tile_grid`, alongside the
step and the tile size it was already stating; a tile's own `tile_index` then says
which of its sides face another tile. A position the workflow chose for itself has
no place in a pattern, nothing is going to butt up against it, and it is kept whole.
A run that overlaps and does not state its pattern keeps its low edges, loses its
far ones, and is warned about it when it is declared, with the argument to pass.

One consequence of the first and third conditions together, which shows up if you
look at the canvas's declared corner: the untrimmed outer edges cannot sit at a
negative position, so the canvas begins a whole chunk before the stage's low corner
and leaves a blank margin around the run. That margin is what lets those edges have
their room while every cropped tile still lands exactly on a chunk boundary. It is
never written to, so it costs nothing on disk, and the canvas's declared position
accounts for it so the picture is still drawn in its true place.

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

### What the sweep found

`measure_the_overlapping_run.py` writes an overlapping run of a given size, reads
every tile back to count what was lost, and then opens the canvas in a real browser.
Taken on this sandbox — four processors, no graphics card, software rendering —
with tiles of 128 × 128 × 2 stepping 96, two colours and two moments:

| tiles | voxels lost | first pixel | requests | flat frames in 5 s | contrast | volume | on disk |
|---|---|---|---|---|---|---|---|
| 1 | 0 | 1.5 s | 22 | 121 | 1.3 ms | 3% | 0 MB |
| 4 | 0 | 1.9 s | 36 | 116 | 1.5 ms | 2% | 1 MB |
| 100 | 0 | 2.2 s | 146 | 127 | 2.3 ms | 2% | 13 MB |
| 484 | 0 | 2.6 s | 316 | 132 | 1.6 ms | 2% | 59 MB |
| 1 936 | 0 | 2.5 s | 272 | 136 | 1.9 ms | 3% | 229 MB |
| 10 000 | 0 | 3.5 s | 325 | 140 | 6.5 ms | 3% | 1 169 MB |

Three things in that table are worth reading carefully.

**Nothing was lost, at any size.** Every voxel handed to the writer was read back out
of the raw tiles and compared, one by one rather than sampled. That is the whole
promise of the arrangement, and it is the number to look at first if anything about
the writer is ever changed.

**Nothing grows with the run.** The frame rate is 121 at one tile and 140 at ten
thousand, which is noise rather than a trend, and the requests made while opening
stop climbing at a few hundred. The engine was handed one image per colour at every
size. Those are exactly the properties a canvas exists to buy, and they hold across
four orders of magnitude. What does move is small and comfortable: opening goes from
1.5 s to 3.5 s, and a nudge of the contrast slider from about 1.5 ms to 6.5 ms.

**The volume column is a share of the flat rate, not a frame count**, and it must be
read that way. Software rendering makes an absolute volume figure a fact about the
box rather than about the run. The share sits at two or three per cent throughout and
does not fall as the run grows, which is what the comparison was there to ask; what
it is *worth* on real hardware, this sandbox cannot say.

Writing is the other cost, and it is not free: ten thousand tiles took 223 seconds
to write both artefacts, about 22 ms a tile. That figure is the two writes together;
the split between the raw tile and the canvas was not measured, so "what the second
write costs during a fast acquisition" is still open.

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

- **The duplicate disk.** Writing raw tiles and a canvas costs roughly twice the
  space — measured at 1.17 GB for ten thousand small tiles, against about 640 MB for
  the tiles alone. The canvas is scaffolding and can be deleted once a run is
  stitched. What is still unmeasured is the *split*: both writes together cost about
  22 ms a tile here, and nobody has taken them apart to say what the second one
  costs during a fast acquisition.
- **The volume, everywhere.** No arrangement in this repository has a frame rate in
  three dimensions that means anything, because none could be taken honestly here.
  The volume is now at least *drawn* and photographed by a test — which nothing in
  this suite did before — but "it draws" and "it draws quickly enough" are different
  questions and only the first has been answered.
- **How a volume decides its brightness.** The window for a volume starts at the
  99th percentile so that background does not accumulate into fog along every ray.
  That is right, and it has a sharp edge: a specimen whose brightest voxels form a
  large flat plateau collapses the window to a single count and the volume opens
  completely empty, with the flat view looking perfectly normal beside it. This was
  met while writing the tests, with synthetic data rather than real, so it may never
  trouble an actual specimen — but a saturated camera would produce exactly that
  shape, and nothing at present would say why the volume had gone dark.
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
