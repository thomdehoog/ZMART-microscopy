# Keeping the overlap: two ways, and which one to build

Written 5 August 2026, rewritten the same day after two reviews took the first
version apart. **Nothing here is built.**

**The recommendation is to build the four-image arrangement and not the placing
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

**This is already measured**, in `DATA_LAYOUT.md` under Decision 1b:

| | one image | four images |
|---|---|---|
| acquired data overwritten | 21.0% | **0.0%** |
| draws per second, idle | 60 | **60** |
| draws per second, while tiles land | 60 | **60** |
| opening the run | 0.5 s | 0.6 s |
| description files read to open | 8 | 32 |
| writing one tile, median | 63.7 ms | 54.1 ms |

Four sources rather than one, and that costs nothing measurable: the frame-rate
cliff this project keeps meeting is at *thousands* of sources, not at four. The
count also does not grow — ten thousand tiles is still four images.

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
| frame rate | 60 a second, measured | one source; not yet measured in the viewer |
| what a colleague receives | four ordinary images | a grid of tiles, meaningless without our server |
| opens in napari, Fiji, a backup | yes | **no** |
| new code needed | none in the viewer | a placing layer, and everything in "what must be true" below |
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

**So build A.** Section B below stays because a run that must be a single file is a
real case, and because somebody will propose it again.

---

## What the four-image arrangement still needs

It is not free, and the work is honest rather than hidden.

**The writer has to deal tiles into four images.** Today `TileCanvases` refuses an
overlapping run outright — `_refuse_overlapping_tiles`, pinned by
`test_a_run_with_overlapping_tiles_is_refused`. That refusal is correct for one
image and has to become a choice between refusing and dealing, which is a change to
a recorded decision and should be written down as one.

**The seam has to be softened at the front.** Four overlapping images composited
with "later wins" give a visible join. The cure is in the shader and
`INTEROP.md` §3 has it: a cosine ramp from each image's own declared rectangle,
about fifteen lines, replacing the brightness test that "cannot tell 'never
imaged' from 'imaged and genuinely dark'". This is the same formula
`multiview-stitcher` uses; what is not portable is where they compute it, which is
Python once per chunk and is why theirs costs hundreds of milliseconds.

**The zoomed-out copies have to be made from all the tiles together.** Each of the
four images holds a quarter of the tiles with gaps between them, so shrinking each
one separately averages every tile edge against empty ground and leaves a faint
grid over the specimen at coarse zoom. One combined pyramid, written once, removes
it — and costs little, since the coarse copies are roughly a tenth of the data. At
coarse resolution nothing is lost by combining, because the overlap only matters at
full resolution, which is exactly where it is kept.

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
and it has been measured: zstd costs **1.4×** when slots line up with chunk
boundaries and **2.0×** when a tile straddles them. The first version's proposed
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
- **"The cost is flat with the size of the run."** Flat while tiles per unit of
  stage stay bounded. Both measurements held density constant, so the bound was
  arithmetic rather than a discovery.
- **"Measuring it in the viewer is the point of the exercise."** Largely
  pre-answered: `WHERE_THINGS_STAND.md` records no interface freeze even with the
  server delayed 200 ms per request, and placing costs about 4.5 ms. The volume
  remains genuinely unknown and is worth measuring.
