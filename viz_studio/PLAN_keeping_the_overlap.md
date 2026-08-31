# Keeping the overlap: two ways, and which one to build

Written 5 August 2026, rewritten the same day after two reviews took the first
version apart. **Nothing here is built.**

> **Superseded. Do not act on the recommendation below.** This document weighs two
> ways of keeping the overlap and recommends one of them. Neither was built,
> because a third answer turned up afterwards that is simpler than both: do not
> show the overlapping part at all. Trim half of it from each tile, and the tiles
> no longer overlap — so there is nothing to blend, no chessboard of four images
> to arrange, and no limit on how much tiles may overlap.
>
> **Read `HANDOVER_overlapping_runs.md` instead.** It describes what was built and
> carries the measurements.
>
> This is kept because the comparison in it is sound and because both arrangements
> will be proposed again by somebody who has not seen the third.

**The recommendation was to build the four-image arrangement and not the placing
server.** The reasoning is below and the placing server is described honestly
rather than dismissed, because it may still be the right answer for a run that has
to be one file — and because the first version of this document proposed it without
comparing it to anything, which is the mistake this rewrite exists to correct.

---

## The question, stated once

An image holds a single value per point. So when tiles that overlap are written
into one image, the second tile written replaces the first wherever they meet, and
`DATA_LAYOUT.md` Decision 1b measures the loss at **21% of everything the camera
recorded** on a run overlapping by an eighth. No later step recovers it, because
the pixels are gone.

That matters because overlap is acquired on purpose. It is what a stitcher compares
to work out where the stage really went.

But the viewer wants one image, for reasons `NEXT_STEPS.md` establishes at length:
Neuroglancer builds drawing layers per source and all of them take part in every
frame, so a thousand separate positions draw at 24 frames in five seconds where one
image manages 255.

**So: how do you keep the overlap and still hand the viewer one picture?** There
are two answers and this document compares them.

---

## The two answers

### A. Deal the tiles across four images — **recommended**

Tiles that would overlap go into different images, the way squares of one colour on
a chessboard never touch. Four images are needed rather than two, because tiles
that meet only at a corner are diagonal neighbours and would otherwise land
together. Within any one image nothing overlaps, so nothing is written over.

**This was measured once**, and the measurement is smaller than it looks.
`DATA_LAYOUT.md` took it on a **9 × 9 raster — 81 tiles — overlapping by 12%, four
planes deep, one colour, written synthetically on this sandbox**. The plan's first
version copied the table without that sentence, which made it read as a result
about scale. It is not one.

| | one image | four images |
|---|---|---|
| acquired data overwritten | 21.0% | **0.0%** |
| draws per second, idle | 60 | **60** |
| draws per second, while tiles land | 60 | **60** |
| opening the run | 0.5 s | 0.6 s |
| description files read to open | 8 | 32 |
| writing one tile, median | 63.7 ms | 54.1 ms |

**Read the two "60" rows as a ceiling, not as headroom.** That harness counted the
browser's own redraw callbacks, which stop at sixty however much time is to spare.
Sixty against sixty says both arrangements sat on the ceiling with 81 tiles; it
cannot tell "costs nothing" from "costs a third of the time available". So it does
not support being set against the placing server as "measured" versus "not
measured", which is what the first version of this document did.

**And the script that produced it was deleted**, in `652327a`, because it crashed on
an argument that no longer exists. So the evidence for the recommended option
cannot currently be re-taken, while the evidence against the other one can. That is
the wrong way round and it should be repaired before this recommendation is acted
on.

What genuinely holds up is the arithmetic about sources: four sources is nowhere
near the cliff, which `NEXT_STEPS.md` puts between a hundred positions at 302
frames in five seconds and a thousand at 24. And the count does not grow — ten
thousand tiles is still four images. That is sound, and it is a claim about source
count rather than about anything else.

It was set aside for one reason, recorded at `DATA_LAYOUT.md`: it "leaves every
reader — analysis code included — joining four images up instead of reading one
picture."

### B. Give every tile a slot, and place them as they are read

Write one image in which each tile has a slot of its own, laid side by side so
nothing is cropped and no two tiles share ground. The picture on disk is then a
contact sheet rather than a specimen — a tile sits at `k × 256` where it belongs at
`k × 224` — and the server puts each tile where it truly goes when the viewer asks
for a piece.

Measured in `TILES_IN_ONE_STORE.md`: about 6 ms a piece, exact to the voxel, and
flat from sixteen tiles to ten thousand.

---

## Why A rather than B

Both keep every pixel and both draw fast. They differ in what is on the disk
afterwards, and that is the whole of the decision.

| | four images | slots and a placing server |
|---|---|---|
| overlap kept | yes | yes |
| frame rate | at the screen's ceiling on 81 tiles; unmeasured above that | one source; not yet measured in the viewer |
| what a colleague receives | four ordinary images | a grid of tiles, meaningless without our server |
| opens in napari, Fiji, a backup | yes | **no** |
| new code needed | a shader change and a pyramid decision — see below | a placing layer, and everything in "what must be true" below |
| already measured | yes | on a bench only |

**The objection that set A aside is smaller than the one B carries.** Opening four
images instead of one is an inconvenience. A store that is only a picture while our
software runs is a different kind of cost: it makes the archive depend on us, and
it is the sort of dependency that outlives the people who chose it.

`INTEROP.md` is this project's own record of what happens when files and readers
disagree, and it took a session on the microscope computer to find that ZMART's
stores were arriving at the origin in half the Python ecosystem. Choosing a layout
that *no* reader understands, deliberately, is a larger version of the same
problem.

### The condition on A, which has to be said before recommending it

Dealing tiles into four images works **for a run tiled on a regular raster, with a
fixed step, overlapping by no more than half a tile.** Four is the right number
because a tile has eight neighbours and only the diagonal ones force a third and
fourth image. Above half a tile of overlap a tile reaches its second neighbour and
four is not enough. If a run tiles in depth as well as across, the same argument
gives **eight**, not four, and this document does not otherwise mention it.

**The case that breaks it is the one this project is for.** A run that returns to
the same field — a timelapse, or a target scan gathering many tiles around one
object — puts N tiles on the same ground, and N tiles that all overlap each other
need N images. The source count then grows with the run, which is the entire
problem this document exists to remove. `TILES_IN_ONE_STORE.md` says plainly that
scattered positions are "the case this project actually produces".

That risk appears in the first version of this plan only as an argument *against*
the placing server, where it is a slowdown. For four images it is not a slowdown,
it is fatal. It belongs here.

**So: build A for raster mosaics, and treat revisited or clustered positions as
unsolved.** That is a narrower recommendation than the first version made, and it
is the honest one. Section B below stays because a run that must be a single file
is a real case, because it degrades rather than fails when tiles cluster, and
because somebody will propose it again.

---

## What the four-image arrangement still needs

It is not free, and the work is honest rather than hidden.

**The writer has to deal tiles into four images.** Today `TileCanvases` refuses an
overlapping run outright — `_refuse_overlapping_tiles`, pinned by
`test_a_run_with_overlapping_tiles_is_refused`. That refusal is correct for one
image and has to become a choice between refusing and dealing, which is a change to
a recorded decision and should be written down as one.

**The seam has to be softened at the front, and this is harder than it was said to
be.** Four overlapping images composited with "later wins" give a visible join, and
`INTEROP.md` §3 offers a cosine ramp from each image's declared edge as the cure,
"about fifteen lines". That estimate was made against a Viv prototype and **does
not carry to the engine we actually ship on.** `frontend/src/scene.js` records why,
and it is worth reading before anybody promises a small change:

- Transparency is already spent. `covered = "v > 0.0 ? 1.0 : 0.0"` uses it to say
  whether a spot was imaged at all, and a ramp needs it to say how much a tile
  should count. The two want the same channel.
- For the bottom-most picture the engine switches blending off and treats
  transparency as a yes-or-no test, so a fractional ramp does nothing there.
- Both obvious repairs are recorded as wrong in that same comment: multiplying the
  colour by the value darkens every picture above it twice over, because the
  engine's blending is straight rather than premultiplied; and additive blending
  makes overlapping tiles sum into bright seams.
- A proper weighted average has to divide by the total weight, and where four
  images meet at a corner no single image's shader knows what that total is.

The formula is still the right one — it is what `multiview-stitcher` uses, and
computing it at draw time rather than in Python is still the point. But "fifteen
lines" should be struck, and this wants designing rather than estimating.

**The zoomed-out copies are an open problem, not a solved one.** Each of the four
images holds a quarter of the tiles with gaps between them, so shrinking each one
separately averages every tile edge against empty ground and leaves a faint grid
over the specimen at coarse zoom. That much is certain.

The obvious answer — one combined pyramid, made from all the tiles together — was
offered here as though it were settled, and it is not. Four questions have no
answer yet:

- **Where does it live?** A pyramid belongs to one image, so a combined one is a
  fifth store. The server merges stores of matching voxel size into one row, and
  the engine picks a level per source and draws later over earlier — so a
  full-field coarse picture would smear over the four sharp ones at every zoom.
  Preventing that means choosing which source to show by zoom level, which is the
  engine's own job and the thing `NEXT_STEPS.md` §1 declines to take over.
- **Who writes it during a run?** `ARCHITECTURE.md` §7 already calls keeping these
  copies current as tiles land "design work rather than a detail, and it is not
  done".
- **It brings back the hazard four images removed.** A combined image is one image
  in which tiles do overlap and do share pieces of the file — the concurrent-write
  fault `DATA_LAYOUT.md` measures at up to three quarters of a tile lost, silently.
- **It is not as cheap as "a tenth of the data" suggests.** `DATA_LAYOUT.md` records
  that 44% of the time spent writing a tile already goes on its smaller copies. A
  fifth pyramid adds that work again, on the live path, for every tile.

**A dataset must be able to be four stores.** `ARCHITECTURE.md` §3 already says a
dataset is what one load produces, however many stores it spans, so this is a use
of the existing shape rather than a change to it.

---

## If B is built anyway: what must be true first

Every item here came out of review, and each is a thing the first version of this
plan got wrong or left out.

### Measure these on a bench before writing any server

1. **Serve chunks the size of the tile step.** The server invents the description,
   so the served chunk size is ours to choose. Set it to the step (224 rather than
   256) and every served chunk falls entirely inside one tile's slot: **one tile
   touched instead of nine, one decompression instead of up to thirty-six.** This
   was not tried and it could remove most of the cost. Measure it first.
2. **Many pieces at once.** Everything measured so far is one piece at a time in one
   thread. The viewer asks for many together, and Python may not multiply the way
   the arithmetic suggests. Pieces per second is the number that matters, not
   milliseconds per piece.
3. **Tiles piled in one place.** "Flat with the size of the run" is really flat
   *while the tiles per unit of stage stay bounded*. A timelapse returning to one
   field, or a target scan clustering around one object, puts every tile inside one
   piece and the cost climbs with the run again. Unmeasured.
4. **A cold store.** All numbers so far are warm — the store was written and read
   back immediately, so it was in memory. On a cold 75 GB store nine reads are nine
   seeks against the control's one.

**Compression is no longer on this list.** It was the first version's headline risk
and it has been measured — `measure_compression_cost.py`, added beside the other
scripts because the first version of this plan quoted these figures with nothing in
the repository behind them. Reading a compressed store costs roughly **one and a
half times** an uncompressed one when a tile's slot lines up with the pieces the
file is stored in, and roughly **twice** when it does not. Two runs gave 1.4× and
1.6× for the first and 2.0× and 2.3× for the second, so treat them as
approximate. The first version's proposed
mitigation was also wrong — lining slots up bounds you at one compressed chunk per
*tile touched*, not one per piece — but the measured cost is small either way, and
aligning is worth doing because `DATA_LAYOUT.md` already requires it of the writer
for a different reason.

### What the picture must get right

- **Edge pieces are padded, not truncated.** Zarr stores every chunk at full shape,
  edge chunks included. The measurement scripts return short arrays and would be
  copied; a server doing that hands back a buffer the reader cannot decode.
- **Time, channels and depth.** Absent from the first version and from every
  measurement. Placement composes only within one moment and one colour — otherwise
  the second channel obliterates the first — and the record must say which slot
  holds which.
- **Who wins is explicit.** "The later tile wins" currently means "the higher slot
  number wins", which is true only because the fixtures assign slots in acquisition
  order. A real writer assigns slots from a free list or after a crash. The record
  must carry an acquisition sequence and the reader must sort on it.
- **The placed and written-out copies must agree on who wins.** Full resolution is
  composed at read time and the coarse copies are written once. If the two order
  tiles differently, zooming in and out flips which tile you see in every overlap
  strip.
- **Ground no tile covers.** `_serve_from_data` answers 404 today and the comment
  there explains why it matters. For a scattered run most of the bounding box is
  empty, and neither measurement has a single empty region.

### What it costs in the server, which is more than one branch

The first version said the change was one branch in `_serve_from_data`. It is not.
Three things read stores straight off the disk and would see the slot layout rather
than the picture: `contrast.py` opens the group directly, `library` reads voxel
size and axes, and `stores.zarr_scheme` decides which reader the engine is told to
use by testing for `zarr.json` **on disk** — so a served description in a different
generation than the disk store fails to open at all. The description cache is keyed
on a file's modification time, and a synthesised description has no file to ask.

### Where the record goes

Not in a new file. `zmart_storage/coverage.py` already writes one line per tile
carrying its origin, shape, tile index, frame and channel. It needs a slot column,
not a rival record with its own consistency question.

---

## What is not in scope either way

- **Sub-voxel or rotated placement.** Both arrangements move tiles by whole voxels.
  Anything else needs real resampling, which `measure_live_fusion_cost.py` measures
  at 110× to 645× a plain read.
- **Stitching.** Keeping the overlap is what lets a stitcher run later. Running one
  is separate work.

---

## The tests, before the code

1. **The picture is the same.** A run written the new way draws the same picture,
   voxel for voxel, as the same run written in true geometry. Written first,
   because a fast wrong picture is the worst outcome available.
2. **The overlap survives.** Every voxel the camera recorded is readable afterwards.
   `DATA_LAYOUT.md`'s existing measurement of 0.0% overwritten is the model.
3. **The seam is soft.** A drawn frame across a join has no step in it.
4. **Coarse copies have no grid.** The failure this is guarding against is visible
   only when zoomed out, which is the state least often tested.
5. **Channels and moments do not collide.** Two channels of one field, and two
   moments of one field, both come back whole.
6. **The volume.** Nothing tests the volume today, for any arrangement.

---

## How you would know it was finished

An overlapping run is acquired, written, and opened; every voxel is still there;
the picture matches a true-geometry control; the join is invisible; and the numbers
— 2D, 3D, channels, timepoints — are written into `TILES_IN_ONE_STORE.md` with the
same honesty as the bench numbers, including if they are bad.

---

## What would falsify this

- **Four images turn out slow at scale.** The measurement behind them is on a small
  fixture. If four images at ten thousand tiles do not hold 60 frames a second, the
  comparison at the top of this document changes.
- **The seam cannot be hidden.** If the shader ramp leaves a visible join, four
  images are a worse picture than one, and the argument shifts back toward B.
- **Somebody needs one file.** A collaborator or an archive that cannot take four
  images makes B the answer despite everything above.

---

## Disproved by review, kept so it is not proposed again

- **"The placing server is the fix for the whole problem."** It is one of two, and
  the other was already measured in this repository and is more portable. The first
  version of this document never mentioned it.
- **"Compression is the largest risk."** Measured at 1.4× aligned. It was the right
  thing to worry about and the wrong thing to be frightened of.
- **"Lining slots up with chunks stops rectangles straddling compressed chunks."**
  It does not. It bounds the cost at one chunk per tile touched.
- **"Synthesising the served chunk keys frees the separator decision."** It does
  not. Both mechanisms in `LIVE_MODE_PLAN.md` §2 read the disk, never the served
  keys, so that trade-off is untouched.
- **"Four images need no new code in the viewer."** They need a shader change for
  the seam and a decision about the zoomed-out copies, both of which are open.
- **"The seam is about fifteen lines."** That estimate was made against a Viv
  prototype and does not survive `scene.js`, where transparency is already spent on
  coverage and the engine's blending is not the premultiplied kind.
- **"One combined coarse pyramid removes the grid."** Probably, but where it lives,
  who writes it during a run, and how the engine is stopped from drawing it over the
  sharp data are all unanswered.
- **"The cost is flat with the size of the run."** Flat while tiles per unit of
  stage stay bounded. Both measurements held density constant, so the bound was
  arithmetic rather than a discovery.
- **"Measuring it in the viewer is the point of the exercise."** Largely
  pre-answered: `WHERE_THINGS_STAND.md` records no interface freeze even with the
  server delayed 200 ms per request, and placing costs about 4.5 ms. The volume
  remains genuinely unknown and is worth measuring.
