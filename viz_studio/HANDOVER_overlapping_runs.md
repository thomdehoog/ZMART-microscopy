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
| `PLAN_showing_many_stores_as_one.md` | the next piece of work, written out step by step: showing a folder of stores as one picture without rewriting any of them, so that a real transfer opens |
| `ARCHITECTURE.md` §7 | the three layers the whole tool is made of |
| `OPEN_a_run_that_changes_while_you_watch.md` | an open question — a new position works, but gaining a colour or a moment, or re-imaging a position, does not |
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

**Done, 11 August 2026, on an NVIDIA T400 4GB.** The flat view's real figures
are in `LINKING_INSTEAD_OF_COPYING.md` under "Measured on real hardware": 123
frames a second and a 2 ms middle frame at 1,600 tiles, against 25–28 and
33 ms in this document's tables — and opening, requests and piece counts did
not move at all, which is what "neither goes near the card" predicted below.
Two practical notes for whoever repeats it: the card is only reachable
**headed** (`--headed` on the measuring scripts; headless Chromium reports
SwiftShader whatever it is asked), and this section's own sweep still pins
software deliberately, because its columns are counts. The volume's frame rate
remains unmeasured.

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

### What the linked view drew

The table above is the arrangement that **copies**. This one is the arrangement that
**points**: the same tiles left where they are, shown as one picture through
`zmart_storage/linked.py`, with nothing of the full-size picture written down.
Measured with `measure_the_frame_rate_of_a_linked_view.py` on the same sandbox —
four processors, no graphics card, software rendering — with tiles of 64 × 64 laid
out as a mosaic:

| tiles | fps | middle frame | longest pause | opening | lit | building the view |
|---|---|---|---|---|---|---|
| 100 | 28.0 | 33 ms | 67 ms | 1 s | 0.91 | 0 s |
| 400 | 27.0 | 33 ms | 50 ms | 1 s | 0.91 | 1 s |
| 800 | 27.7 | 33 ms | 67 ms | 1 s | 0.91 | 3 s |
| 1 600 | 25.0 | 33 ms | 100 ms | 1 s | 0.91 | 6 s |
| 3 200 | 23.7 | 50 ms | 100 ms | 1 s | 0.90 | 12 s |
| 6 400 | 25.3 | 33 ms | 83 ms | 1 s | 0.90 | 24 s |

**The drawing does not notice the tile count.** The middle frame is 33 ms at every
size across a sixty-four-fold range, and opening stays at about a second throughout.
That is the whole claim of the arrangement, measured: the engine is handed one image
whatever is underneath it, so a picture made of six thousand four hundred tiles
behaves like a picture made of one hundred.

The 50 ms at 3 200 tiles is worth naming as a warning about reading these tables.
Taken on its own it looks like the beginning of a slope, and it was written up that
way before the next row was measured. The 6 400 row came back at 33 ms with a
*shorter* longest pause, so the 3 200 reading was the machine being busy and nothing
more. **One row is not a trend**, and this sandbox is contended enough that a single
figure should never be argued from.

**The `lit` column is a guard, not a result.** It says how much of the screen had
specimen on it. An empty panel redraws beautifully, so a frame rate measured on one
means nothing — and this was not a hypothetical: the first run of this climb painted
its test pattern between 400 and 800 out of a sixteen-bit range, which reaches the
screen at about one per cent brightness. The picture was there and drawing, the
brightest pixel on the panel was 3 out of 255, and every rate in the table was
correctly dismissed as measured on nothing. Any table without such a column should
be treated with suspicion, this project's own included.

**What building the view costs, and what that figure leaves out.** The last column
doubles cleanly with each doubling of tiles — 0, 1, 3, 6, 12, 24 seconds — so ten
thousand tiles projects to about forty. It is paid once, when the view is built, and
never again while drawing.

But it is measured with the smaller copies left out, because those are the part that
is genuinely written rather than pointed at and leaving them out is what made the
climb affordable. Measured separately at 400 tiles: 1.4 s and 0.07 MB for the
pointers alone, against 4.7 s and 1.04 MB with the copies included, over tiles
holding 3.78 MB. So **the real cost of opening a run is three to four times the last
column**, and the copies come to about a quarter of the data — which is the figure
`LINKING_INSTEAD_OF_COPYING.md` predicts, turning up in a measurement.

### Three things measured afterwards, because the table did not answer them

**How many requests does the browser make, and does it grow with the run?** It does
not, and this is the strongest single result here.

| tiles | requests | of them for pieces | bytes | opening | lit |
|---|---|---|---|---|---|
| 100 | 24 | 20 | 0.01 MB | 1.1 s | 0.17 |
| 400 | 54 | 50 | 0.08 MB | 0.6 s | 0.83 |
| 1 600 | 124 | 120 | 0.22 MB | 0.6 s | 0.90 |
| 6 400 | 124 | 120 | 0.11 MB | 0.6 s | 0.90 |

The count climbs while the picture is still smaller than the window, then stops
entirely: 1 600 tiles and 6 400 tiles ask for the same 124 things and open in the
same 0.6 seconds. The browser fetches what is on screen, and once the picture is
larger than the screen that stops depending on how large the run is. The `lit`
column explains the first row — at 100 tiles the picture does not fill the window,
so there is less to ask for.

**Is the frame rate hitting a ceiling, or is it real?** It is real. An empty page on
this sandbox, drawing nothing at all, manages **60.7 frames a second**, and the
linked view runs at 25 to 28. So the picture is consuming rather more than half the
frames available, which means the drawing is genuinely working and **a machine with
a graphics card has something to gain**. The middle frame sitting at 33 ms in row
after row looks like a fixed tick and is not one — that was checked because it
looked like one, and the ceiling turned out to be twice as high.

This matters for how the rest of the table is read: a card should move `fps`,
`middle frame` and `longest pause`, and should move nothing else. Building the view
is processor and disk, opening is disk and requests, and neither goes near the card.

**What does one more tile cost during a run?** A full rebuild, which is the honest
problem left in this arrangement.

| tiles | build from nothing | rebuild with one more tile |
|---|---|---|
| 800 | 0.25 s | 0.22 s |
| 3 200 | 0.92 s | 0.78 s |
| 6 400 | 1.72 s | 1.54 s |

Adding a tile costs the same as building the whole view, because that is literally
what happens. The figures above are after a thirteen-fold speedup — profiling showed
86% of the time was opening every tile to ask how many colours it held, which the
writer already knew, so 6 400 tiles went from 22.5 s to 1.7 s.

But a faster rebuild is not the answer. The cost is proportional to the run, so
across a whole acquisition it is the *square*: 6 400 tiles at around a second each
is hours of cumulative rebuilding for a run whose tiles arrive one at a time.

**So the view can now be held open instead.** `start_a_growing_view` in
`zmart_storage/linked.py` opens it once and adds tiles one at a time. Measured on a
view already holding 6 400 tiles:

| | one more tile | filesystem calls |
|---|---|---|
| arriving after a quiet moment | 88.9 ms | 9 — eight stat, one rename |
| arriving inside a burst | 0.53 ms | 8 stat |

**The first row is the one that matters for an acquisition**, because a microscope's
tiles arrive seconds apart and every one of them therefore lands after a quiet
moment. The second only applies to adding thousands in a loop, where the list of
pointers is written a few times a second rather than once per tile.

That distinction is worth stating plainly because it was got wrong once already: the
throttling was measured in a tight loop, reported as "0.32 ms and flat", and that
figure is real but describes the burst case rather than a run on an instrument.

The call counts say where the work is. **Eight stat calls is the whole of checking
the tile** — reading its description, confirming it is stored like the others, that
it lands on whole pieces, and that it agrees with the rest about where the picture's
corner is. That part costs nothing and does not grow. **The single rename is the
88 ms**: writing six thousand four hundred lines of JSON and swapping the file into
place.

So building the view of 6 400 takes 2.6 s, and one more tile after that takes 89 ms
rather than the 1 540 ms a rebuild took. Better by seventeen times, and 89 ms
between tiles that arrive seconds apart is not a bottleneck — but it still grew with
the run, because the list of pointers is one file and adding a line meant writing
all of it.

**Tiles are now added to the end of a companion file instead**, one line each, and
folded back into the list when the run finishes. Measured by growing a view a tile
at a time and then adding one more after a pause, so that the last tile really does
write:

| tiles | growing to that, a tile at a time | one more tile after it | a tile, median |
|---|---|---|---|
| 6 400 | 2.73 s | 0.87 ms | 0.378 ms |
| 12 800 | 4.33 s | 0.85 ms | 0.313 ms |

**Doubling the run does not change what a tile costs.** One more tile is 0.87 ms at
six thousand four hundred and 0.85 ms at twelve thousand eight hundred, and the
median tile is the same at both sizes. Growing the whole view roughly doubles with
the run, which is the right shape — it is the sum of a fixed cost per tile.

Against where this started: one more tile went from 1 540 ms rebuilding the view, to
89 ms rewriting the list, to 0.87 ms adding a line. The last of those is flat, and
the first two were not.

---

None of this is one-time during an acquisition. A tile arriving adds pointers, which
is cheap; keeping the smaller copies current as tiles land is recorded in
`ARCHITECTURE.md` §7 as unsolved.

---

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
