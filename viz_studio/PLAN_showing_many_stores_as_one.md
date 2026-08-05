# Work order: showing many stores as one picture, without rewriting any of them

Rewritten 5 August 2026, and renamed — it was `PLAN_seam_ownership.md`, which
described a fix that was tried and does not work. What replaces it is broader, and
it is worth stating the goal in one sentence before anything else:

> **Take the stores a microscope leaves on disk, whatever shape they are in, and
> present them to the viewer as a single image — without rewriting any of them.**

Everything below follows from that sentence, including the parts that turn out to
be impossible.

---

## Why this is needed at all

The viewer draws with [neuroglancer](https://github.com/google/neuroglancer), which
is very good at one enormous image and not good at many small ones. Every store
added is another description to fetch and another layer to manage, and a plate of
ten thousand positions handed over as ten thousand stores does not open in any
useful sense. The pictures are all there; the viewer simply cannot be asked to hold
them.

So the run has to *look like* one image. Not be copied into one — look like one.
That is the whole of this work.

## What arrives on disk, in practice

Three shapes, and the tool has to open all of them:

1. **One store holding the whole picture already.** A canvas written by
   `zmart_storage.canvas`. Nothing to do; it opens today.
2. **A folder of stores, one per position and colour.** This is what a mesoSPIM
   transfer looks like, and it is the ordinary case. Each store carries its own
   place on the stage.
3. **A handful of stores to be shown together** — five positions of an overview,
   say. The same problem as 2, smaller.

Cases 2 and 3 are the same job at different sizes, and they are what this document
is about.

---

## What was measured, before anything was planned

Three experiments were run against the code as it stands, each writing real stores,
building a real view, and reading the picture back through the viewer's own server
over HTTP. The tiles held **coordinate-coded** pixels — every voxel holds `1000 +`
the position it was acquired at — so where a tile really ended up can be read
straight off the picture rather than inferred from it.

**A drifted run, served by pointing at files.** Three tiles at x = 0, 71 and 144, so
two of them began 7 and 16 voxels past a piece boundary. 128 of 208 columns of the
picture held a value from somewhere else, displaced by exactly 7 and 16 voxels;
9216 of 13312 voxels differed from a canvas written from the same tiles. The
zoomed-out copies, which are written from the pixels rather than pointed at, came
out exactly right — so the specimen would jump on zooming in.

**The same run with the tiles' own pieces aligned to the run's grid**, by padding
each tile's low edge by however far the stage overshot. `zmart_storage/linked.py`,
with no change to it at all, built the view and served every one of 163,840 voxels
exactly where the stage recorded them.

**An earlier plan's rule, worked through.** It proposed giving each piece of the
view to the nearest tile that covers it completely, and claimed the first owned
piece "must come out a whole number by construction". It comes out at 0.891 and
0.750 of a piece for those two tiles, and no other piece of the tile is any better:
for the tile at 71 the available choices are off by −57, +7 and +71. Under the
rule's own "covers completely" test those tiles own **nothing at all**, and the view
comes out empty.

The second experiment is kept as a test in
`viz_studio/tests/test_a_drifted_run_is_placed_truthfully.py`.

---

## The one constraint everything bends around

A view that hands over a tile's own file untouched can only do so when the bytes
being asked for *are* that file. `zmart_storage/linked.py` says it in its opening
docstring and it is exactly right:

> "zarr describes an image as one regular grid, so a view can keep a tile's true
> position or hand over its files untouched, but not both."

A stage asked to step 1792 voxels steps 1792 give or take a couple, so a real tile
begins a few voxels off the grid and no file of it holds what is being asked for.
This is **phase**, and it is worth naming because it is constantly confused with
the seam between two overlapping tiles. They are different problems:

- **Seam** — where two tiles overlap, which one supplies this region? Answerable
  anywhere, cheaply, and it has to be answered however the bytes are served.
- **Phase** — does a tile's grid of pieces line up with the picture's? Answerable
  only by the writer, or by decoding and recombining pixels.

No scheme of pointers can fix phase, because a pointer means *these bytes,
verbatim*. That is true of our own list of pointers and equally true of the
standard tools for the same job — Kerchunk, VirtualiZarr, Icechunk. They reference
byte ranges; none of them can express "shift this piece seven voxels."

---

## The shape to build: one path, two speeds

Because phase cannot be assumed for data we did not write, **assembling has to be
the path, and pointing is an optimisation taken when it happens to be available.**
The earlier plan had this the other way round, which is why it refused the runs it
was written to open.

| When | How a piece is answered | What it costs |
|---|---|---|
| The piece is exactly a piece of one store | Hand over those bytes untouched | nothing |
| It is not | Decode the few pieces that overlap it, cut and combine them, hand that back, and remember it | some processor time, once per piece looked at |

Two things to be clear about, because they are what makes this acceptable:

- **Assembling rewrites nothing on disk.** The stores stay exactly as the
  microscope left them and the archive does not grow. The work happens as requests
  arrive, only for the pieces actually on screen, and a piece of the picture
  overlaps at most four pieces of the stores underneath it.
- **The viewer only ever asks for what is being looked at.** That is what makes a
  ten-thousand-position plate tractable: at any moment the browser wants a few
  dozen pieces, not the run.

---

## Tasks, in the order to do them

### 1. Find out what real transfers actually look like

**Where:** `viz_studio/measure_what_a_transfer_looks_like.py`, which is written and
needs running on the microscope computer against real data.

It reports how the stores are written, whether any are sharded, where they sit, and
what fraction of them begin on a piece boundary. That last number decides how much
of the run takes the fast path, and everything below is easier to size once it is
known. Nothing else in this document should be built before this is run, because it
is the difference between designing for the common case and guessing at it.

### 2. Build the assembling path

**Where:** `viz_studio/backend/linking.py`, beside the pointing path rather than
instead of it.

When no single stored piece answers a request, work out which stored pieces overlap
it, read them, cut the wanted part out of each, combine them into one piece of the
picture, and store the result so the next look does not repeat the work. Keep the
cache bounded and in memory unless measurement says otherwise; a cache that grows
without limit is a copy of the run by another name, which is the thing this
arrangement exists to avoid.

Answer "there is nothing here" — a 404 — for ground no store covers, exactly as the
pointing path does. Neuroglancer treats that as absent and fills it in; a politer
answer such as 204 is read as a successful empty reply and fails to decode.

### 3. Decide the seam once, and use it from both paths

**Where:** `zmart_storage/linked.py`, around `PlacedTile`.

Where two stores both cover a piece, one has to be chosen, and the choice must not
depend on which path serves it or the picture would change as the cache filled.

An earlier draft said "give the piece to whichever store's centre is nearest to the
piece's centre". That is the obvious rule and it should not be built, for reasons a
reviewer set out and which hold up. Nearest-centre ownership in two dimensions puts
the boundary between two stores on the line where the distances are equal, and that
line is only vertical or horizontal when the two centres happen to be level. In
general it is diagonal. So a store's owned region comes out stair-stepped rather
than rectangular; it can be split into disconnected parts; it can be interrupted by
a third store; and a store can end up owning a single isolated piece in a corner
where a neighbour was missing. Because it depends on distances, small changes in
where the stage went change the *shape* of the seams, so two runs of the same plate
do not have the same picture. The rule also cannot be worked out along `y` and `x`
separately, which is how it would naturally be written, and a version that does so
is quietly a different rule.

It is underspecified in another way too. "Nearest" needs units, and these voxels
are not cubes — about 0.35 µm across and 2 µm deep on this instrument. Nearest in
voxels and nearest in micrometres are different answers.

**Decide on the acquisition's own grid instead.** Every store carries a position;
sort those positions into rows and columns and give each store its row and column
number. Then, for two stores neighbouring in `x`, the shared pieces go to the left
one up to the piece boundary nearest the middle of their overlap and to the right
one after it. The same, separately, in `y`. A piece in a corner shared by four
stores is settled by `y` first and then `x` — stated as an order so it has one
answer rather than a nearly-tied one.

This gives every store a plain rectangle, puts the seams along the acquisition's own
rows and columns, and gives the same answer every time. The acquisition is a raster;
the ownership should be too. Where the stores are not a raster at all — a few
scattered overview positions — fall back to nearest centre, in micrometres, and say
in the log that it was used, because there the concerns above do not apply and
there is no grid to appeal to.

**Test the awkward geometries specifically**, because they are where a seam rule
goes wrong quietly: a four-store corner; the same with one store missing; a whole
row missing; two wells with a gap between them; and two stores level in one axis but
not the other.

This is the part of the earlier plan that survives. It is a real problem and it
needs a real answer — it simply never was an answer to phase.

**One thing the seam rule cannot fix, and should not be described as fixing.** Two
overlapping stores hold the same specimen photographed from two stage positions,
and until a stitcher has measured them they disagree slightly about where things
are. When ownership hands a piece from one store to the other, a structure can
appear to jump by that disagreement — which has nothing to do with where the seam
was put and is not bounded by anything in this document. It is what stitching
exists to remove. Report it separately from anything else the view is measured on,
so that one number does not hide the other.

### 4. Let the acquisition write tiles that need no assembling

**Where:** `zmart_storage/cropped.py`, `_WholeTileImage.declare` (line 914), which
currently sets `chunk = max(tile_shape[1], tile_shape[2])` at line 949 — one piece
per plane, so a tile can only ever be placed as a single indivisible block.

For runs this project writes itself, the fast path can be arranged rather than hoped
for, and it was measured to work. Two changes:

- **Cut tiles into pieces much smaller than the tile** — 128 or 256 voxels across
  y and x. Default to 128; a caller who will never link can still ask for one piece
  per plane and should still get it.
- **Begin every tile a whole number of pieces from the run's corner**, by padding
  its low edge by `position mod piece` and recording the padded corner as its
  position.

Record the padding in the tile's own attributes, so that a stitcher, or anyone else
reading the tile, can tell padding from specimen. Without that note this quietly
puts fill pixels into a raw tile, which is a real cost to everyone downstream and
not ours to impose silently.

Overlap neighbouring tiles by **at least two pieces**. A tile can only supply pieces
it fills completely, so it loses up to one at each edge; two pieces of overlap
covers that loss whatever the stage does. With pieces of 128 that is 256 voxels,
about 12% of a 2048-voxel tile, which is an ordinary overlap for stitching anyway.

### 5. Consider a standard reference file, behind the interface we have

The list of pointers this project writes is a **chunk manifest**: a small file
saying which piece of the picture is which piece of which store. That is the same
idea as Kerchunk and VirtualiZarr, which are the established tools for it, and the
backend is Python so it can read them through `fsspec` and still hand the referenced
bytes over without decoding.

Three reasons it is worth doing, and two cautions.

Worth doing because a reference of the form *(file, offset, length)* can point
**inside** a file, which our "hand over this file" cannot. It means stores that are
not zarr at all — TIFF, HDF5 — could be presented as one picture with nothing
converted, which is the real answer to "any format". And it means other Python
tools can read the same mosaic.

Note that **sharded stores no longer need this.** An earlier draft listed them as
the main reason to adopt it, on the assumption that a bundle's index would have to
be read here. It does not: what gets handed over is the whole bundle, and the
viewer's engine reads the index itself and asks for the piece it wants by byte
offset, which the server already answers. A sharded 0.5 run is pointed at today —
measured, and covered by
`viz_studio/tests/test_a_pointed_at_view_of_the_newer_format.py`. The one thing to
know is that the **bundle becomes the unit**: a tile has to begin on a whole bundle
boundary, and the smallest strip that can be trimmed where two tiles overlap is a
whole bundle. Larger bundles therefore make the placement rules in task 4 harder to
satisfy, not easier, so the bundle should be chosen as the smallest that keeps the
file count reasonable rather than as large as possible.

Caution one: use the **Parquet** form of references rather than JSON. References
are recorded per piece, and this project already learned what that costs — the note
in `viz_studio/backend/linking.py` works it through: ten thousand tiles of sixteen
by sixteen pieces, times their planes and colours and moments, turns a few megabytes
on disk into tens of gigabytes in memory. The Parquet form loads lazily and exists
for exactly this.

Caution two: the microscope computer is a constrained machine.
`TESTING_ON_REAL_HARDWARE.md` describes two conda environments that are not
interchangeable, everything confined under `C:\ProgramData\MinicondaZMB\`, and a
machine that refuses to run programs from folders a user can write to. It also
records how a missing dependency shows up there: every test timing out with nothing
said about the real cause. So keep this behind the interface that exists, so the
plain path still works if the dependency proves painful on the instrument.

### 6. Tell a missing file apart from ground nobody imaged

**Where:** `viz_studio/backend/linking.py`, and wherever the server answers.

Both currently answer 404, which is right for ground nobody imaged and quietly wrong
for a store that has been deleted, moved, or half-written: the operator sees blank
ground either way. Keep the 404 on the wire, for the reason in task 2, and add a
note beside it — log it once per store rather than once per piece, and surface it in
the viewer's status. For a run still being acquired, "not written yet" and "written
and then lost" are different things and should be logged differently, or a run in
progress fills the status with problems that are not problems.

---

## Tests

`viz_studio/tests/test_a_drifted_run_is_placed_truthfully.py` holds the
coordinate-coded approach and four tests already. Add to it:

- **A drifted run of stores we did not write opens, and every voxel is where the
  stage says.** This is the test the assembling path stands on, and it is the one
  that says whether a mesoSPIM transfer is really supported.
- **The two paths agree.** Serve the same run once where pieces line up and once
  where they do not, and compare voxel for voxel. A picture that changes depending
  on which path answered is the worst outcome available, because nothing on screen
  says which it was.
- **The cache changes nothing but speed.** Ask for the same pieces twice and compare.
- **Padding is never served**, and a store's edge padding never appears inside the
  picture.
- **The same run always gives the same view.** Build it twice, compare.
- **An undrifted run is unchanged.** Every existing test in
  `test_the_linked_view_matches_the_canvas.py` must still pass untouched, including
  the refusal at line 359 — which stays until the assembling path can answer for
  those runs, and only then becomes a fallback rather than a refusal.

### What to run before saying it is done

```
python -m pytest zmart_storage/tests/ -q
python -m pytest viz_studio/tests/test_a_drifted_run_is_placed_truthfully.py -q
python -m pytest viz_studio/tests/test_the_linked_view_matches_the_canvas.py -q
python -m pytest viz_studio/tests/test_the_linked_view_draws.py -q
```

All of `zmart_storage/tests/` passes today (112 tests); it must still.

---

## Things not to do

- **Do not round a store to the nearest whole piece and leave it there.** It
  displaces every voxel by up to half a piece, and — as measured above — it is what
  the list of pointers will silently do if handed a store that is not aligned.
- **Do not describe a quantisation as a moved seam.** A seam moves when ownership
  changes between two stores that both hold the right pixels. Pixels appearing away
  from where they were acquired is a different thing, and calling it a seam hides it.
- **Do not let the cache become the picture.** If it grows to the size of the run,
  the run has been copied and the arrangement has failed at the one thing it was
  for.
- **Do not assume a reference file makes the viewer able to read it.** Neuroglancer
  runs in a browser and reads pieces over HTTP; it cannot open a Kerchunk reference
  set itself. Whatever the manifest, the backend remains the thing that turns it
  into an answer.
