# Where this got to, and what to pick up next

Written 5 August 2026, for the next session. Everything described here is committed
on `claude/frame-rate-stores-scaling-cngfct` and every test named passes on this
sandbox.

**Read this first, then `PLAN_showing_many_stores_as_one.md`.** That plan is the one
piece of work standing between all of this and a real plate opening.

---

## The shape it has arrived at

Store **one OME-Zarr per position**, exactly as the microscope naturally leaves
them, each with its own zoomed-out copies. Beside them, build a **view**: a small
file saying which piece of one big picture is which piece of which position. The
viewer opens the view and sees a single ordinary image.

```
run_folder/                 one folder holds the whole run
  overview_tiles/           one image per position, with its own 2–5 levels
    overview_pos00000.ome.zarr    this is where all the data lives
    overview_pos00001.ome.zarr
    ...
  linked.ome.zarr/          the view — an ordinary OME-Zarr image and nothing else
    zarr.json               says what the picture is
    0/ 1/ 2/ 3/             levels — descriptions only, no picture at all
  zmart-links/              ours, beside the images rather than inside one
    linked.ome.zarr.json    which piece is which piece of which tile
  zmart-coverage/           ours — where the run actually imaged
```

**Everything of ours sits beside the images, never inside one.** That is worth
stating because it was the other way round for a while and it is easy to drift
back. Anything added inside an `.ome.zarr` folder makes zarr complain to whoever
opens it — *"Object at zmart-links.json is not recognized as a component of a
Zarr hierarchy"* — so a colleague opening the run in napari or Fiji meets a
warning about a file of ours they have never heard of. Keeping every image folder
pure is what lets the positions and the view be ordinary images to everybody
else, which is the whole point of writing OME-Zarr rather than a format of our
own. It also keeps a live run quiet: the viewer notices change by when a folder
was last touched, so a list rewritten inside the image on every tile would look
like the acquisition itself changing, thousands of times over.

Two things make this worth having, and they are the whole point:

**The viewer stops caring how many positions there are.** Neuroglancer builds
drawing layers per store, so a few thousand separate positions do not open in any
useful sense. Handed one image, it does not matter what is underneath.

**Nothing is copied.** Not the full-resolution picture, and — since today — not the
zoomed-out copies either. A view holds a few kilobytes whatever the run's size.

---

## What was built, with the numbers

All measured on this sandbox, which has **no graphics card**. Absolute frame rates
mean nothing off this machine; the shapes do.

**Drawing does not notice how many positions there are.**

Measured with `viz_studio/measure_a_run_of_positions.py`, over runs written by
`zmart_storage.positions` — one zarr, the positions inside it with their own
zoomed-out copies. Positions of 512 voxels, pieces of 128, one colour.

| positions | lit | fps | middle frame | worst frame | opening | requests | the picture | the positions |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.850 | 35.7 | 33 ms | 50 ms | 0.8 s | 25 | 0.0 MB | 1 MB |
| 5 | 0.891 | 25.7 | 33 ms | 117 ms | 0.4 s | 65 | — | — |
| 10 | 0.513 | 27.3 | 33 ms | 133 ms | 0.4 s | 60 | 0.0 MB | 5 MB |
| 50 | 0.822 | 30.0 | 33 ms | 117 ms | 0.5 s | 60 | — | — |
| 100 | 0.771 | 32.0 | 33 ms | 100 ms | 0.6 s | 62 | 0.8 MB | 66 MB |
| 200 | 0.827 | 30.3 | 33 ms | 67 ms | 0.4 s | 70 | 1.6 MB | 132 MB |
| 400 | 0.924 | 28.0 | 33 ms | 83 ms | 0.4 s | 67 | 3.7 MB | 264 MB |
| 1 000 | 0.678 | 27.0 | 33 ms | 67 ms | 0.6 s | 70 | 8.8 MB | 540 MB |
| 2 000 | 0.970 | 26.0 | 33 ms | 117 ms | 0.6 s | 74 | 18.5 MB | 1 079 MB |

**The middle frame is 33 milliseconds at every one of those sizes**, across a two
thousand-fold range, and opening never passes 0.8 seconds. Requests climb only
while the picture is smaller than the window and then stop — the browser fetches
what is on screen, and that does not depend on how much run is underneath.

There is no cliff, and it is worth saying where one could have been. Two things
grow with the position count rather than with what is on screen: the map, which
the viewer's server spreads into a lookup when a run is first opened, and the
opening itself, which has to read that map before the first picture appears. Both
were watched at two thousand positions and neither moved. The map is the one to
keep an eye on at ten thousand, because it is held in memory — `linking.py`
records what an earlier version cost by holding it per *piece* rather than per
position.

**The picture stays about 1.7% of the run** and follows the number of positions
rather than the amount of specimen: 18.5 MB of description beside 1.08 GB of
picture. None of it is a copy — those are the levels zoomed out further than any
single position goes, which nothing can be pointed at for.

**Read `lit` before any of the rest.** It says how much of the screen actually had
specimen on it, and the first run of this table read 0.000 on every row while
reporting a healthy 35 frames a second — over a completely black screen. The
picture was being served correctly and drawn at about five per cent of its
brightness, because the display window was being worked out by reading a picture
that deliberately holds no pixels. Nothing else in the table so much as twitched.
See the commit *"Show a run at the brightness it asked for"*.

The older arrangement — a view built by hand over tiles written separately — was
measured the same way and is kept here as history rather than as current truth:
28.0 fps at 100 tiles, 25.0 at 1 600 and 25.3 at 6 400, with the middle frame 33 ms
throughout. The shape is the same one, which is the point.

**A tile arriving during a run went from 1 540 ms to 0.87 ms**, in three steps: not
rebuilding the view (`start_a_growing_view`), not reopening every tile to ask what
was already known, and not rewriting the whole pointer list for each tile. It is
flat — 0.87 ms at 6 400 tiles and 0.85 ms at 12 800.

**A view now writes no picture at all**, at any zoom, when the tiles carry their own
copies. Checked by rebuilding every level through the pointers and comparing against
the whole picture shrunk by the same amount — identical, every voxel.

**What that saves depends on whether your tiles already have pyramids**, and it is
worth being exact rather than encouraging. The zoomed-out copies are about 25% of a
picture: each is a quarter of the one above, so a quarter plus a sixteenth plus a
sixty-fourth, which comes to a third in theory and measures near 26% once a run
stops making them.

| | the tiles | the pyramid | in total |
|---|---|---|---|
| tiles with none, view writes one | 100% | 25%, in the view | 125% |
| tiles with their own, view writes one too | 125% | **25% again — the same numbers twice** | 150% |
| tiles with their own, view writes none | 125% | none | **125%** |

Tiles here are written with 2–5 levels of their own, so before today this was the
middle row: the view computed and wrote a second copy of zoomed-out data the
positions already held. **That duplication is what today's change removes** — a
quarter of the picture, and on a five-terabyte run more than a terabyte.

Had the tiles carried no pyramids, the change would move the bytes rather than
remove them: same total, better arrangement. It is worth knowing which of those you
are looking at before quoting a saving.

---

**What one more position costs a run already going.** Measured with
`viz_studio/measure_what_one_more_position_costs.py`, over positions of 256
voxels. Each arrival is timed *on its own*, with the run grown to the size in the
first column first — which is the question that matters, since a microscope hands
positions over one at a time rather than in a loop.

| run already holds | a new place | another colour | a later moment | a slab of z |
|---|---|---|---|---|
| 10 positions | 62.98 ms | 13.72 ms | 14.01 ms | 61.58 ms |
| 100 positions | 63.78 ms | 13.61 ms | 13.87 ms | 62.42 ms |
| 500 positions | 65.58 ms | 13.43 ms | 13.42 ms | 64.83 ms |
| 1 000 positions | 59.45 ms | 12.98 ms | 12.61 ms | 58.33 ms |
| 2 000 positions | 63.87 ms | 13.26 ms | 12.69 ms | 62.47 ms |

**Flat across a two hundred-fold range** — 63 ms at ten positions and 64 ms at two
thousand. Nothing is being paid per position already written, so an acquisition
does not slow down as it goes. Closing the run costs 63 ms once, when the
positions added a line at a time are folded into the picture's description.

Another colour or a later moment costs about a fifth of a new place, and the
reason is worth knowing: they go into the image that place already has, and the
map is not touched at all. The view is told about a *place* once rather than once
per picture.

Timing each arrival by itself rather than in a loop is deliberate, and the older
arrangement is why. It measured 0.32 ms a position when thousands were added in a
loop and **89 ms** for one arriving after a quiet moment, because every arrival
rewrote the whole map. The loop was paying that too; it was simply spread over
positions that were all already in it.

---

## Opening a run in napari or Fiji — read this before somebody is surprised

**Point other software at `positions`, never at the picture.**

Every position is an ordinary OME-Zarr image, with its own zoomed-out copies and
its own place on the stage written inside it. It opens anywhere, and nothing needs
to know this project exists to read one.

The picture does not travel. It holds no voxels — each piece of it is answered,
while the viewer is open, by the viewer's server handing over a position's file.

What makes this worth a section rather than a footnote is *how* it fails. It does
not refuse to open and it does not warn. It opens perfectly, with the right levels,
size, voxel size and channels, and every voxel in it is nought:

| opened with plain zarr | levels | shape | max | mean |
|---|---|---|---|---|
| the picture | 0, 1, 2 | 1024 × 1024 | **0** | **0** |
| one position | 0, 1, 2 | 512 × 512 | 3919 | 2500 |

So somebody opening a run the obvious way sees a black picture and reasonably
concludes the acquisition is empty. Nothing on screen tells them otherwise.

That is a real price rather than an oversight, and the alternative is the thing
this whole arrangement exists to avoid: writing the run a second time into one
image so any reader could open it. On a real acquisition that is a second copy of
many gigabytes. **There is no way to have one openable picture and no second copy
at the same time**, and it is better to know which of the two you are choosing.

If a colleague needs a single file they can open anywhere, give them the
positions, or write them a stitched image on purpose.

---

## The two things that block real data

### 1. A drifted run is refused

This is the big one. A view hands over a tile's own file untouched, which only works
when the tile begins exactly on a piece boundary. A stage asked to step 1792 voxels
steps 1792 give or take a couple, and two voxels out is as fatal as half a piece —
the bytes wanted are then spread across two of the tile's files.

**So the tool opens the tidy grids the tests build and not yet a plate off your
stage.** It refuses rather than drawing slightly wrong, which is the right instinct
and the wrong outcome.

The fix is in `PLAN_showing_many_stores_as_one.md` and it belongs in the
*acquisition*, not here: **pad each tile's low edge** by however far the stage
overshot the previous boundary, and record the padded corner as its position. The
specimen does not move by a voxel; what moves is where the tile's own grid begins.
It was measured before being planned — a run drifting by 7 and 16 voxels, built by
`linked.py` with no change to it at all, served every one of 163,840 voxels exactly
where the stage recorded them.

**The rule got stricter today.** Because the zoomed-out copies are pointed at too,
a tile must begin on a multiple of the piece size **times the largest shrink**, not
merely of the piece size. With pieces of 128 and five levels that is multiples of
2 048 voxels. The reason is that shrinking counts from each picture's own corner, so
a tile out of step keeps a different set of voxels from the ones the view would have
kept — a different picture, not a rounding difference.

### 2. Re-imaging a position is not noticed

When a position is imaged again and its tile written over in place, **nothing
changes that anything is watching**. The pointer is the same and the list is the same
length, and length is what the reader uses to notice a change. The operator keeps
seeing the old picture with nothing to say so.

`OPEN_a_run_that_changes_while_you_watch.md` sets out the question and recommends
letting a counter in the view be the truth and an announcement be the hurry-up, so a
lost message costs a moment's delay rather than a wrong picture.

---

## Smaller things left open

- **The view could be the plate folder itself**, rather than a subfolder beside the
  positions. Tested and it reads correctly; `link_the_tiles` needs an option for it.
  Weigh it against losing the safety of a view you can delete wholesale.
- **`cropped.py` writes one piece per plane** (`canvas.py:949`), which makes a tile
  a single indivisible block that nothing can be pointed at inside. It needs a piece
  size of 128 or 256.
- **The seam rule is written but not built.** `PLAN_showing_many_stores_as_one.md`
  task 3 decides which of two overlapping tiles supplies a shared piece, on the
  acquisition's own grid rather than on distances between tile centres.
- **Sharded tiles are pointed at**, and the bundle becomes the unit — a tile has to
  begin on a whole bundle boundary, so larger bundles make placement harder, not
  easier.
- **`measure_what_a_transfer_looks_like.py` has never been run.** It reports how
  your stores are really written and what fraction begin on a piece boundary, which
  is the number that decides how much of a real transfer can be pointed at. Run it
  on the microscope machine before building anything else.

---

## Things that were got wrong today, and corrected

Written down because each was believed for a while and each changed a decision.

**"Shrinking averages across the join between tiles."** It does not.
`canvas.py:1562` is `image[:, ::factor, ::factor]` — every second voxel kept, the
rest discarded. That mistake was the reason a view wrote a quarter of the picture.
There is now a comment at that line saying the arrangement depends on it: changing
it to average would give a smoother zoomed-out picture and quietly break all of
this.

**"Seam ownership fixes drift."** It does not. Deciding *which* tile supplies a
piece cannot change *where* that tile begins, and a tile out of phase is out of
phase for every one of its pieces. Tried against the real code, it produces an empty
view.

**A frame rate measured on a blank screen.** The test pattern was painted between
400 and 800 out of a sixteen-bit range and reached the screen at about one per cent
brightness — drawing perfectly, reported as nothing. Every table now carries a `lit`
column saying how much of the screen had specimen on it.

**"0.32 ms a tile, flat."** True for adding thousands in a loop, not for a
microscope. A tile arriving after a quiet moment cost 89 ms at the time, because it
wrote the whole pointer list. Fixed since, but the lesson stands: measure the case
the instrument actually produces.

---

## Where to look

| | |
| --- | --- |
| `zmart_storage/linked.py` | builds a view. `link_the_tiles` for a finished run, `start_a_growing_view` for one in progress |
| `viz_studio/backend/linking.py` | answers for a view while the viewer is open |
| `zmart_storage/canvas.py:1562` | the line everything depends on |
| `PLAN_showing_many_stores_as_one.md` | **the next piece of work** |
| `PLAN_nothing_copied_at_all.md` | why a view writes nothing, and what the acquisition must do |
| `OPEN_a_run_that_changes_while_you_watch.md` | the re-imaging question |
| `HANDOVER_overlapping_runs.md` | every measurement, including the older copying arrangement |

## What to run

```
python -m pytest zmart_storage/tests/ -q                                   # 124 tests
python -m pytest viz_studio/tests/test_the_linked_view_matches_the_canvas.py -q
python -m pytest viz_studio/tests/test_a_growing_view_is_read_as_it_grows.py -q
python -m pytest viz_studio/tests/test_the_linked_view_draws.py -q
```

And, on a machine with a graphics card:

```
python viz_studio/measure_the_frame_rate_of_a_linked_view.py --steps 100,1600,6400
```

Every drawing measurement in this repository came from a software renderer. **If
your figures disagree with any here, yours are the real ones.**
