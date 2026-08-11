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
  shrinking does not average: `TileCanvases._write_smaller_copies` in `zmart_storage/canvas.py` is `image[:, ::factor, ::factor]`,
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

**Keep the index.** *Written, and the problem an earlier draft warned about here
has since been fixed and measured.* Which piece of the view is which piece of
which tile is written down listing each tile once — ten thousand tiles are ten
thousand lines, and the map travels inside the picture's own description. (It
sat in a loose file at first; the reader still understands the older
arrangements, so a run already on disk keeps working.)

An earlier `linking.py` spread that list out into one entry per *piece* on
opening, which at ten thousand tiles reaches tens of gigabytes of memory for a
file that was a megabyte on disk. It now keeps one note per tile per row of
pieces the tile crosses, and finds a piece by asking which tile in that row
covers it — a handful of comparisons, and memory in proportion to the tiles.
Measured over 9,231 positions (`measure_ten_thousand_linked.py`): the map is
1 MB on disk, parsing and indexing it costs 8 MB of memory and about half a
second once per change, one lookup takes about 30 microseconds, and every one
of 1,846 sampled pointers resolved to the right tile.

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

**Shrink the index in memory.** *Done, and measured at ten thousand positions —
see "Keep the index" above for the numbers.*

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

**Decide about sharding.** *Decided, built, and tested — for the full-size
picture.* A sharded tile's pieces live inside bundles, and the bundle is the
file, so the bundle is what is handed over: the view is declared bundled
exactly as its tiles are, the engine reads each bundle's own index and asks for
pieces by byte range, and the server answers single ranges. Growing views over
bundled tiles answer mid-run like any other. The rule to know is that **the
bundle becomes the placement unit** — tiles land on whole bundles, and a larger
bundle makes placement harder, not easier.

What stays open is pointing at a bundled tile's *deeper copies*: the unit the
picture is served in changes between levels (the bundle at full size, the bare
piece below), the map speaks one unit, so the depth is capped at full size and
the deeper zooms are written instead — pinned by
`test_bundled_tiles_point_one_level_and_the_next_zoom_is_written_right`. Going
deeper would mean the map carrying each level's own unit.

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

---

## How you actually build one

Four steps, and the third is one call.

**1. You already have the tiles.** Each position is an ordinary OME-Zarr that
says where it sits.

**2. Say where each one lands in the picture**, in voxels:

```python
from zmart_storage.linked import PlacedTile, link_the_tiles

tiles = [PlacedTile(store=folder / f"Tile{i}.ome.zarr", lands_at=(0, y, x))
         for i, (y, x) in enumerate(corners)]
```

`taken_from` and `size` are there too, for showing only part of a tile -- which
is how a run whose tiles overlap can skip the strip its neighbour is showing,
without a trimmed canvas existing anywhere.

**3. Build it:**

```python
view = link_the_tiles(folder, tiles=tiles, name="canvas", levels=3)
```

**4. What lands on disk** is a normal-looking OME-Zarr that holds no full-size
picture: the description, the smaller copies **as real pixels**, and the map of
pointers. `viz_studio/backend/linking.py` answers for it -- a piece is looked up
in the map and the tile's own file is handed over unchanged.

## Each pyramid level doubles the grid the tiles can be *pointed at* on

The condition above -- a piece of the view is a piece of a tile -- has a second
half that only appears when you ask for more than one level. The view points at
the tiles' *zoomed-out* copies as well as their full-size pictures, and pointing
`L` levels deep needs every tile to begin on a multiple of `chunk x 2**(L-1)`:
shrinking keeps every Nth voxel counted from the picture's own corner, so a tile
starting out of step keeps a different set of voxels from the ones the view
would have kept, and the specimen drawn when zoomed out is not the specimen.

**The builder no longer refuses a run over this, and no longer asks for smaller
pieces.** An earlier version demanded the full depth and refused anything less,
which forced the piece size down to whatever divided the step -- that is how the
16-position measurement below ended up at 32-voxel pieces and 925 requests. Now
the depth is worked out from the run: the view points as deep as the tiles
genuinely line up -- and as deep as the tiles' own pieces stay full-size, since
a copy smaller than one piece is stored as a smaller piece that a larger view
cannot hand over -- and **writes the copies below that depth** as an ordinary
canvas would. A run aligned all the way down writes nothing; one aligned only at
full size writes about a quarter of the picture; one level of pointing brings
that to ~7%, two to ~2%. The view records how deep its pointers go
(`pointed_levels`, both in the map and on `LinkedView`), and every zoom is right
either way -- `test_a_view_that_writes_nothing.py` follows both paths voxel for
voxel.

So the rule for acquisitions stays simple and is now about cost rather than
possibility: **step by a whole number of pieces to link at all, and by
`piece x 2**(L-1)` to also point `L` levels deep and write nothing.** Padding a
tile's low edge (as `PLAN_placement_by_transform.md` records) remains the trick
for bringing a run onto that coarser grid at write time.

## Measured, 2026-08-10

Building the view, over runs of 512-voxel tiles stepping 384, three levels:

| positions | linking | the view weighs | the run weighs |
| --- | --- | --- | --- |
| 1 | 0.02 s | ~0 MB | 4 MB |
| 16 | 0.03 s | ~0 MB | 67 MB |
| 128 (one level) | 0.12 s | 33 kB | 132 MB |

**Linking is free and stays free.** What is not yet understood is the cost of
*opening* one: a 16-position view took 925 requests and 2.5 s to settle, where
the same specimen written as one canvas takes 128-301 requests and under a
second. One source either way. The likeliest cause is that a pointer map hands
out pieces one at a time where a written pyramid gives the engine runs of
neighbouring chunks -- but that is a guess and it is the next thing to measure.

## Measured later the same day: ten thousand at random, and the 925 explained

The guess above did not survive its measurement. `measure_the_chunk_size.py`
showed the same picture written as an ordinary canvas costs 46 requests in
pieces of 256 and 1,925 in pieces of 32, no pointers anywhere -- so the 925 was
the piece size the old depth rule forced, not the pointing. With the depth now
worked out from the run (see "Each pyramid level..." above), the piece size
stays whatever the acquisition chose, and the linked view opens like a canvas.

Then the placement was made as hard as it gets, on this project's own piece
size: **10,000 positions of 512 voxels placed at random** over an 81,920-voxel
stage, 5,693 of them overlapping another tile, one linked source, measured
through the viewer's own server in a real browser
(`measure_a_random_scatter.py`, software renderer, so seconds are a floor):

| | |
| --- | --- |
| growing the view, positions written included | 44 ms a position |
| fully loaded from a cold page | **1.3 s, 71 pieces** |
| the whole 29 mm stage fitted and settled | 2.2 s from cold, 82 pieces |
| zoom ladder, full resolution to whole stage | every rung settled in ~0.3 s |
| pieces per rung, zooming out 4x at a time | 515, 367, 76, 8, 2 |
| pointers followed into the overlap and proven to cover their piece | 990 of 990 |

Random placement, holes and overlap change nothing about the opening cost,
because the browser is never told they exist: it sees one image and asks by
screen and piece size. The same ten thousand positions as separate sources
would be about 48,000 requests on the measured 5.2-per-tile curve.

## Measured on real hardware, 11 August 2026

Everything above was taken on a software renderer, and the handover said
plainly that a machine with a card would have to redo the frame numbers. That
machine turned up: an NVIDIA T400 4GB, drawing through ANGLE and Direct3D 11.
Two things had to be true before the card could be measured at all, and both
are now in the scripts rather than in anybody's memory: the SwiftShader pin had
to come out of the launcher (`measure_a_random_scatter.py` borrowed the sweep's,
which forces software on purpose), and the browser has to be **headed** —
a headless Chromium on this machine reports SwiftShader whatever arguments it
is given, so `--headed` is what reaches the card, and every run now announces
which renderer really drew.

The scatter, at 2,000 positions on the same seed, both renderers on the same
box (`measure_a_random_scatter.py 2000` and the same with `--headed`):

| | software (SwiftShader) | the card (T400) |
| --- | --- | --- |
| fully loaded from a cold page | 0.53 s, 71 pieces | 0.61 s, 71 pieces |
| the whole stage fitted and settled | 1.21 s, 82 pieces | 1.27 s, 82 pieces |
| zoom ladder, every rung | ~0.32 s | ~0.32 s |

**Opening did not notice the card, and the piece counts did not notice the
machine.** 71 pieces from a cold page is the same 71 the sandbox measured at
ten thousand positions — the browser asks by screen and piece size, so the
count belongs to the window, not to the run or the box. The seconds belong to
disk and requests, which never go near the card. Both of those were
predictions in `HANDOVER_overlapping_runs.md`; they are now measurements.

What the card does buy is frames
(`measure_the_frame_rate_of_a_linked_view.py --steps 100,400,1600`, and the
same with `--headed`; 1,600-tile rows, screen 0.9 lit):

| | fps | middle frame | worst |
| --- | --- | --- | --- |
| the sandbox that wrote this document (4 cores, software) | 25–28 | 33 ms | 100 ms |
| this machine, software | 89 | 8 ms | 19 ms |
| this machine, **the card** | **123** | **2 ms** | 19 ms |

The flatness claim survives on real hardware — 124 fps at 400 tiles, 123 at
1,600 — and the rate the sandbox could only call "more than half the frames
available" is 123 frames a second with a 2 ms middle frame on a modest card.

One operational finding from the same afternoon, recorded because it will bite
whoever runs this next: the 10,000-position build was **killed twice by this
machine's endpoint protection** — silently, exit code 5, no traceback, at a
different point each time. Writing tens of thousands of small files at full
speed is exactly the pattern a ransomware heuristic watches for. The 2,000
rows above exist because that is the size that got through; the counts lose
nothing (see the 71 above), but the 10,000-row seconds on this machine are
still owed, and want an antivirus exclusion before they are attempted.
