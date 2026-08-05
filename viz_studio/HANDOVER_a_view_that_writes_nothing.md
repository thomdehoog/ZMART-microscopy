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

**Drawing does not notice the tile count.**

| tiles | fps | middle frame | opening | requests |
|---|---|---|---|---|
| 100 | 28.0 | 33 ms | 1 s | 24 |
| 1 600 | 25.0 | 33 ms | 1 s | 124 |
| 6 400 | 25.3 | 33 ms | 1 s | 124 |

The middle frame is 33 ms at every size across a sixty-four-fold range. Requests
climb only while the picture is smaller than the window, then stop entirely — the
browser fetches what is on screen, and that does not depend on the run.

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
