# Showing the run without copying it

Written 5 August 2026, and revised since. **This is now built**, in two halves:
`zmart_storage/linked.py` writes a view, and `viz_studio/backend/linking.py`
answers for it while the viewer is open. The older arrangement that copies —
`zmart_storage/cropped.py`, measured in `HANDOVER_overlapping_runs.md` — still
exists and is still the one that has been measured end to end.

**Read the section "The condition, and what it costs us" before building on this.**
The linking works, and it works only for runs whose tiles sit on an exact grid.
Real acquisitions drift, and a drifted run is currently refused outright rather
than shown. That is the single thing standing between this and being usable, and
it is not a detail.

---

## Why this matters, and it is not tidiness

The arrangement that works today writes the run twice: the raw tiles, and a canvas
holding the same pixels trimmed and laid out as one picture. At the sizes measured
so far that costs about eighty per cent more disk, which is an easy price.

**At five terabytes it is not a price at all, it is a refusal.** A run that size
cannot be copied to be looked at. There is not the disk, and even where there is,
the copying itself takes long enough to change how the instrument is used. So for
the runs this project is heading towards, copying is not the expensive option — it
is the impossible one, and something else has to be true.

---

## The idea in one paragraph

A picture the viewer opens does not have to exist. It can be a **list of pointers**
into the tiles that already exist, and the pointers can be arranged to describe a
single, ordinary image.

Where two tiles overlap, the view simply **does not point at the shared parts**.
Those pieces stay on disk, in the tiles, untouched and unreferenced — available to
a stitcher, invisible to the viewer. Nothing is trimmed, nothing is rewritten, and
no pixel is ever at risk, because a view is only ever a list of pointers.

If the view is built wrongly, you rebuild the list. The data has no idea a view
exists.

---

## What makes it possible: a piece of the view is a piece of a tile

This is the whole mechanism, and it rests on arithmetic rather than cleverness.

An image is stored in pieces. If a piece of the *view* happens to be exactly a
piece of one *tile*, byte for byte, then answering a request for it is not
assembling anything — it is handing over a file that already exists. No arithmetic
on the pixels at all.

That happens when two conditions hold:

- **The trim is a whole number of pieces.** The trim is half the overlap, so a run
  overlapping by 256 voxels is trimmed by 128, and the pieces must be 128 or
  smaller.
- **The trimmed tile is a whole number of pieces**, so that each tile begins on a
  piece boundary in the view. This one is already checked by the writer that copies.

Worked through, with a tile 2048 voxels across overlapping by 256:

```
trim 128 from each side          = exactly 1 piece of 128
what is left is 1792 across      = exactly 14 pieces of 128

so piece j of tile k's part of the view is tile k's piece j+1
the first and last piece of every tile are simply never asked for
```

---

## The condition, and what it costs us

Everything above holds only while a tile lands on a piece boundary. This section is
about what happens when it does not, because that is the ordinary case and the
document did not previously admit it.

**What a microscope stage actually does.** Ask a stage to step 1792 voxels and it
steps 1792 voxels give or take a little. The error is small — a fraction of a
micrometre, a few voxels — and it does not matter for the science, because a
stitcher measures the real offset afterwards and that measurement is the whole
reason the tiles overlap. But "a few voxels" is exactly what breaks this
arrangement. A tile that begins 1794 voxels along, with pieces 128 across, begins
at 14.02 pieces — and 0.02 of a piece is as fatal as half of one. The bytes wanted
for a piece of the view are then spread across two files of the tile, and handing
over a file that already exists is no longer possible.

**Why no amount of cleverness in the description gets round it.** Zarr describes an
image as one regular grid. Inside that grid every piece is the same size and sits
at a multiple of that size. There is no way to write down "this tile is two voxels
further along than the grid says" and still have a reader find whole pieces. So the
choice is genuinely between the tile's *true* position and byte-for-byte
passthrough; a view cannot have both. That is not a limitation of this
implementation, it is a property of the format, and it is the one point on which
every review of this plan has agreed.

**What the code does today.** It refuses.
`_refuse_a_placement_that_does_not_land_on_whole_pieces` in `zmart_storage/linked.py`
raises rather than build the view, and the message says what to change. That was
the right first move — a refusal with a clear explanation is far better than a view
that silently draws a tile two voxels out of place — but it means **the tool does
not currently open a real acquisition.** It opens the synthetic runs in the tests,
where the grid is exact by construction. Nobody should read the measurements in
this document as evidence that a real plate will open.

**The way out, and two that were tried and rejected.**

The paragraph above is worth reading twice, because it rules out more than it first
appears to. If a view cannot have both a tile's true position and byte-for-byte
passthrough, then no rule applied *while building the view* can rescue a tile that
is already written out of step. The tile's grid has to be right before the view is
ever built.

**Which means this only ever works for tiles we wrote ourselves.** A transfer from
another microscope was arranged by nobody, and we cannot go back and change how it
was written. For those runs the picture has to be **assembled** — the few stored
pieces overlapping each piece of the view are decoded, cut and combined as requests
arrive, which touches nothing on disk and costs some processor time per piece
looked at. So pointing is the fast path and assembling is the path; the work order
in `PLAN_showing_many_stores_as_one.md` builds it that way round, and the options
below are about how often the fast path is available.

1. **Align the tile's own pieces when it is written.** Pad each tile's low edge by
   however far the stage overshot the previous piece boundary, so the tile's grid of
   pieces sits on the run's grid. Its true position is then a whole number of pieces
   by construction, and the choice above never has to be made: passthrough survives
   and no voxel moves. **This is the one to build.** It was measured before being
   planned — a run drifting by 7 and 16 voxels, built by `linked.py` with no change
   to it at all, served every one of 163,840 voxels exactly where the stage recorded
   them. The price is a set of rules the acquisition has to follow, listed in the
   work order, and up to one piece of padding along each tile's low edge.

2. **Round each tile to the nearest whole piece.** Rejected. It displaces every
   voxel of the tile by up to half a piece — far larger than the drift being
   corrected — so the picture ends up worse than if nothing had been done.

3. **Own whole pieces rather than trim fixed amounts.** Rejected *as a fix for
   drift*, though it survives as the rule for deciding which of two overlapping
   tiles supplies a piece. An earlier draft of this document proposed it as the
   answer and claimed the tile still supplies whole pieces of itself *and* the
   picture stays right to within the drift — which is exactly the "both" that the
   paragraph above says the format forbids. Tried against the real code, it does
   what that paragraph predicts: the ownership rule decides *which* tile supplies a
   piece and has no way to affect *where* that piece's pixels land, so a drifted
   tile is either drawn displaced by the drift or, under the rule's own
   "covers completely" test, supplies nothing at all and the view comes out empty.
   The measurements are in `PLAN_showing_many_stores_as_one.md`.

4. **Re-encode only the pieces that straddle.** Still open, but it is a larger job
   than it sounds. A tile out of step is out of step everywhere — *no* piece of it
   lines up, not merely a thin border — so this means rewriting the whole tile, not
   a few edges. It becomes worth doing for a run that has been stitched and needs to
   be shown at the stitcher's accuracy rather than the stage's, where the pixels
   genuinely have to move.

Until option 1 is built, the honest summary is: **linking is proven on grids and
refuses everything else.**

---

## The rule for what else this works on

**If the answer is exactly the bytes of a piece that already exists, it can be a
pointer. If producing the answer needs arithmetic on pixels, it cannot.**

That draws a clean line, and it is worth knowing which side things fall on.

Free, because they only rearrange:

- trimming, when the trim lands on piece boundaries;
- moving a tile, since that only changes which piece is asked for — including
  moving it again later, once a stitcher has found where the stage really went;
- taking a subset: one well of a plate, one colour, one moment, a range of planes;
- presenting the same tiles several ways at once — a whole-plate view, a per-well
  view and a single-colour view can all be lists of pointers into the same files,
  and cost nothing extra;
- joining along an axis, so moments or colours held in separate files appear as one.

Not free, because the pixels genuinely change:

- ~~**the zoomed-out copies**, because shrinking averages across the join between
  tiles and no existing piece holds that answer~~ — **this was wrong.** The
  shrinking does not average: `canvas.py:1562` is `image[:, ::factor, ::factor]`,
  which takes every second voxel and discards the rest, so a zoomed-out voxel comes
  from exactly one tile and there is no join to average across. A tile that carries
  its own zoomed-out copies can therefore be pointed at at every zoom, and a view
  need write nothing at all. `PLAN_nothing_copied_at_all.md` sets that out;
- blending overlap, for the same reason;
- anything rotated, or shifted by less than a piece, which needs resampling;
- changing the compression or the number type, since the bytes themselves change.

So the honest shape is: **full resolution is pointers, the zoomed-out copies are
written once.**

How much disk that costs is worth getting right, because an earlier draft of this
document said "about a tenth" and that was simply wrong. Each zoomed-out copy is
half the width and half the height of the one above it, so it holds a quarter as
many voxels. Adding up a quarter, plus a sixteenth, plus a sixty-fourth, and so on
comes to **a third** of the full-size picture. A real run stops making copies once
they are small enough to draw in one go, and its pieces are padded at the edges, so
the measured figure lands a little under that: **about 26%**.

So linking turns "eighty per cent more disk" into "about a quarter more". That is
still a large improvement and it is the right reason to do this — but at five
terabytes a quarter is well over a terabyte, and anyone planning disk should use
the real number rather than the comfortable one.

---

## What else has to be done

The pointing is the easy half. This is the list that decides whether it is a
week's work or a month's. Most of it is now written — each item below says which —
and the ones still open are gathered at the end.

**Describe the view.** *Written.* The viewer asks what the image is before it asks for any of
it — its axes, its size, where it sits on the stage, what copies it has. None of
that exists on disk, so the server has to say it. Note that the position must be
written beside each resolution, not once for the image; the reasoning is in
`INTEROP.md` §1 and the writer already does it this way.

**Keep the index.** *Written, and it has a problem worth fixing before this meets a
real run.* Which piece of the view is which piece of which tile is written to a
small file kept beside the images, in `zmart-links/` and named after the view it
describes, which lists each tile once — ten thousand tiles are ten thousand lines,
and that part is fine. (It sat *inside* the view's own folder at first; it was
moved out because anything inside an `.ome.zarr` makes zarr warn whoever opens it,
and because rewriting it there on every tile looked to the viewer like the
acquisition itself changing.)

The trouble is what the server does with it on opening. `linking.py` spreads that
list out into one entry per *piece*, so it can find a piece in a single step. A
tile 2048 voxels across in pieces of 128 is 16 by 16 pieces, times the planes and
the moments and the colours — and at ten thousand tiles that arithmetic reaches
tens of gigabytes of memory for a file that was a few megabytes on disk. It works
in the tests because the test tiles are small.

The fix is not difficult and does not change the file: keep the tile list as it is
written, sorted, and find a piece by asking which tile's rectangle contains it,
rather than by having written every piece down in advance. That is a handful of
comparisons instead of a lookup, which is more than fast enough, and it uses
memory proportional to the number of tiles rather than the number of pieces.

**Answer for ground no tile covers.** *Written.* Most of a scattered run's bounding box is
empty. The server already answers a plain "nothing here" — a 404 — and the pointing
path must do exactly the same.

It is worth knowing *why* that is right, because it looks like an error returned for
an ordinary case and a reviewer will suggest something politer. Neuroglancer's
`isNotFoundError` treats 403, 404 and a failed connection as "this piece is absent"
and nothing worse: the engine fills the region from the fill value and carries on.
There is no retrying and no error state. A 204, which reads as the more courteous
answer, is **not** in that list — it would be taken as a successful reply with an
empty body, and fail to decode. The polite answer is the broken one.

**Make the encodings agree, exactly.** *Written — all seven of the following are
compared before a view is built, and a disagreement refuses it.* Bytes are handed
over untouched, so
everything the view says about them has to match what the tiles really contain. A
mismatch fails silently — the picture is wrong and nothing reports it — which makes
this the longest list here and the one to check at the door rather than in the
field. Each of these has its own way of going wrong:

- **the number type, including which way round the bytes go.** A big-endian tile
  handed to a graphics card expecting little-endian draws as noise, with no error
  anywhere.
- **the compression, and its settings.**
- **the fill value**, since it decides what unwritten ground looks like.
- **how the pieces are named.** Zarr allows a dot or a nested folder, and serving
  one where the reader expects the other gives a black screen rather than a
  complaint. This writer chooses folders; a tile that chose dots cannot be served
  beside one that did not.
- **which way the numbers are laid out in memory**, row by row or column by column.
- **the order of the axes.** A tile declaring colour, depth, height, width cannot
  be served alongside one declaring depth, height, width — the same bytes would be
  read as a different picture, and the only sign would be a specimen that looks
  strange.
- **the generation of zarr.** `stores.zarr_scheme` decides which reader the engine
  is told to use by looking at the disk, so a view declaring one generation over
  tiles written in another does not open at all.

**And one that is not a mismatch, which is why it is easy to miss.** Zarr stores the
piece at the edge of an image at full size, padded out with the fill value. That is
right for the tile it belongs to. But hand that piece over at a place that is
*inside* the view rather than at its edge, and the padding is served as though it
were specimen — a band of blank ground in the middle of the picture, from a file
that is not corrupt and a server that did nothing wrong.

**And one that only shows up once a real acquisition drifts:** the seams. That is
the section above, and it is the largest piece of work left.

### Still open

**Handle a run that has drifted.** Build the ownership arrangement described above.
Everything else on this list is smaller than this one.

**Shrink the index in memory.** Rectangle arithmetic instead of an entry per piece,
as described under "Keep the index".

**Tell "nothing imaged here" apart from "something is wrong".** Right now both
answer 404, and that is correct for the first and quietly wrong for the second. If
a tile file has been deleted, moved, or half-written, the viewer shows blank ground
and says nothing — the same picture it shows for a part of the plate nobody imaged.
An operator cannot tell a sparse run from a broken one.

The server should keep the 404 for ground no tile covers, because that is what
Neuroglancer handles gracefully and any politer answer breaks it. But when the
index says a tile *should* be there and the file is not, that deserves a line in
the log and a note in the viewer's own status, even though the reply on the wire
stays the same. This came out of the third review and it is a real gap.

**Decide about sharding.** If tiles are written as sharded zarr, a piece lives
*inside* a file rather than being one, so handing it over means serving part of a
file rather than a file. Still possible, no longer simple.

**Keep it current during a run.** A tile arriving adds pointers, which is cheap.
Two things are not.

The zoomed-out copies are the first, and `ARCHITECTURE.md` §7 already records that
keeping them current as tiles land is unsolved.

The second is subtler and is worth writing down before it bites. A view is a file
that points at other files, so there is a moment while it is being rewritten when
it points at a run that has since changed — and a viewer that reads it in that
moment draws the wrong tile in the right place, with nothing on screen to say so.
The remedy is ordinary and cheap: write the new list under a temporary name and
rename it into place when it is complete, so a reader ever only sees a whole list
or the previous whole list. Renaming a file this way is a single step that either
happened or did not, on every system this runs on. The server already notices when
the file's timestamp changes and reads it afresh, so the rest follows.

**Prove it against the copy.** *Written, and passing.* The arrangement that copies
is measured and correct, which makes it the ideal control: the same run, the same
viewer, the same machine, and the only difference is whether the picture was
written down or pointed at. `viz_studio/tests/test_the_linked_view_matches_the_canvas.py`
writes both over the same tiles and compares every voxel, at every zoom, in every
moment and colour, reading the pointed-at view through the viewer's own server the
way the browser does. What it does not yet cover is a run that has drifted, because
such a run is refused before it can be compared.

---

## The one thing that could spoil it, and it is measurable now

The piece size is forced down — it has to divide half the overlap — and smaller
pieces mean the same picture arrives in more requests. The bytes are unchanged;
what grows is how many times the browser has to ask. `WHERE_THINGS_STAND.md`
already records that three requests in four are wasted on a sparse canvas, so this
is not a free direction.

**It is a lever you set when acquiring, not a limitation you discover afterwards**,
and the surprising part is which way it points:

| tile | overlap | trim | largest usable piece |
|---|---|---|---|
| 2048 | 256 (12.5%) | 128 | 128 |
| 2048 | 512 (25%) | 256 | 256, which is what is written today |
| 2048 | 1024 (50%) | 512 | 512 |

**More overlap makes linking easier**, because half of a larger overlap divides
more ways. A run that overlaps by a quarter can keep exactly the piece size this
project already uses, and nothing about the request count changes at all.

`measure_the_chunk_size.py` beside this file writes the same run at four piece
sizes and opens each one, so the only thing differing between the rows is how
finely the picture is divided. **It has not been run.** It needs no linking layer
and no new format, and it answers the question that decides whether any of this is
worth building.
