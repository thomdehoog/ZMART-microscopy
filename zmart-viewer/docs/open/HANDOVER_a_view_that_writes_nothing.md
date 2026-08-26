# Where this got to, and what to pick up next

Written 5 August 2026, for the next session. Everything described here is committed
on `claude/frame-rate-stores-scaling-cngfct` and every test named passes on this
sandbox.

**Read this first, then `docs/history/PLAN_showing_many_stores_as_one.md`.** That plan is the one
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

Measured with `zmart-viewer/measure_a_run_of_positions.py`, over runs written by
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
| 5 000 | 0.732 | 23.7 | **50 ms** | 83 ms | 0.9 s | 79 | 46.7 MB | 2 699 MB |
| 10 000 | 0.714 | 25.0 | **50 ms** | 83 ms | 0.8 s | 71 | 93.4 MB | 5 399 MB |

**No cliff out to ten thousand positions, but not perfectly flat either, and the
difference is worth stating rather than rounding away.**

The middle frame is 33 milliseconds from one position to two thousand, and **50
milliseconds at five thousand and ten thousand**. That is one step rather than a
slope: it does not move again between five and ten thousand, and it is exactly the
size of step this measurement can resolve — frames land on the screen's own
rhythm, so 33 ms is two of those intervals and 50 ms is three. Whether it is real
or an artefact of drawing in software is not answerable on a machine with no
graphics card, and it should be looked at again on one that has.

What did **not** move is the part that would have said the arrangement itself was
failing. Requests stay at seventy-odd — the browser fetches what is on screen, and
that does not depend on how much run is underneath. Opening stays under a second
at ten thousand positions, having been 0.6 at two thousand. And the picture is
93 MB against 5.4 GB of specimen, still about 1.7%, still description rather than
copy.

Those two were the places a cliff could have been, and they were named before the
measurement rather than after: the map, which the viewer's server spreads into a
lookup when a run is first opened, and the opening itself, which has to read that
map before the first picture appears. Both grow with the position count rather
than with what is on screen. `linking.py` records what an earlier version cost by
holding that lookup per *piece* instead of per position — megabytes on disk
becoming tens of gigabytes in memory. Neither showed at ten thousand.

Writing the runs took 462 seconds for five thousand positions and 907 for ten
thousand, which is the flat per-position cost below seen from the other end.

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
`zmart-viewer/measure_what_one_more_position_costs.py`, over positions of 256
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

The fix is in `docs/history/PLAN_showing_many_stores_as_one.md` and it belongs in the
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

`docs/open/OPEN_a_run_that_changes_while_you_watch.md` sets out the question and recommends
letting a counter in the view be the truth and an announcement be the hurry-up, so a
lost message costs a moment's delay rather than a wrong picture.

---

## Smaller things left open

- ~~**The view could be the plate folder itself.**~~ **Done, and further than that.**
  The whole run is now one zarr: the picture is the folder you open, and the
  positions live in a zarr *group* inside it. See "The shape it has arrived at".
- ~~**`cropped.py` writes one piece per plane.**~~ **Gone around rather than fixed.**
  `zmart_storage/positions.py` writes its own position images, with pieces of 128
  and their own zoomed-out copies, so the limitation no longer stands in the way.
  `cropped.py` itself is untouched and now unused by this path — see the note on
  simplifying below.
- **The seam rule is written but not built.** `docs/history/PLAN_showing_many_stores_as_one.md`
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

## What to do next

Two things, and they pull in the same direction: less of our own machinery, and
more that other people's tools can read.

### 1. Simplify further

The arrangement got much smaller today and there is more to take out. These are
listed with what each would actually remove, because "simplify" on its own is not
a task anybody can pick up.

- **`zmart_storage/cropped.py` is 965 lines and nothing on this path uses it.**
  It writes the acquisition *twice* — every position, and a trimmed copy of the
  whole run into one image — and roughly half of it is the trimming arithmetic
  that exists only to make tiles butt up inside that copy. The picture replaced
  the job the copy was doing. Outside its own tests it is imported by
  `zmart_storage/__init__.py` and two measurement scripts. **Decide whether it is
  the older arrangement kept deliberately, or dead.** If deliberately kept, say so
  at the top of the file; a reader today cannot tell.

- **The map can be found in three places and only one is written.** The reader
  looks in the picture's description, then in a `zmart-links` folder beside the
  images, then inside the image itself. The last two are runs written earlier
  today. Once nothing on disk needs them, this is one lookup instead of three.
  The same goes for `LINKS_VERSIONS_UNDERSTOOD`, which is `(1, 2, 3)`.

- **`start_a_run` has knobs that could be answers.** `piece`, `levels` and `dtype`
  are all asked for and all have one sensible answer. `levels` is already worked
  out from the room when left out; the other two could be.

- **`zmart-viewer` holds about thirty markdown files** and several describe
  arrangements that no longer exist. A reader cannot tell which is current truth
  without reading most of them. Merging or plainly marking the superseded ones is
  worth more than any of the code above.

### 2. Make a run readable by napari and Fiji

Today the picture opens **silently black** in anything but our own viewer, which
is set out in its own section above. That is the single worst property of the
arrangement, because it does not announce itself. Options, cheapest first, with
what each actually buys:

- **Write the coarse levels for real.** Point at the positions for full
  resolution as now, but let the picture *store* its smallest two or three
  levels as ordinary pixels. They are tiny — a few megabytes against a run of
  many gigabytes — and a reader opening the picture anywhere would then see a
  real, low-resolution image of the whole specimen instead of nothing. This does
  not make full resolution portable, but it turns a silent failure into an
  obviously-low-resolution picture, which is a completely different experience
  for somebody who does not know how any of this works. **Probably the best
  value of anything on this list.**

- **Put a plain note in the run folder.** A short `README.txt` beside the
  positions saying which folder to open and why the other one looks empty. No
  code, no cost, and it removes the silence even if it does not remove the
  limitation.

- **A reader for Python.** Something like `zmart_storage.open_run(folder)` handing
  back an array-like that resolves the map itself. napari opens array-likes
  happily, so that would make napari work at full resolution. It does nothing for
  Fiji, which is Java.

- **A standard reference file beside the run** — Kerchunk or VirtualiZarr. Then
  anything built on `fsspec` can read the mosaic natively, at full resolution and
  with no copy. Also nothing for Fiji. `docs/history/PLAN_showing_many_stores_as_one.md` task 5
  works through this, including why the Parquet form matters at this scale.

- **Export a stitched image when somebody asks for one.** Honest, portable, and a
  full second copy — which is fine as a deliberate act and not as a default.

Worth being clear that **none of these makes Fiji read a mosaic at full
resolution without a copy**, and that is not something this project can fix from
its side.

### 3. Overlap, which is harder than it looks and is really three questions

Today a later position simply wins for any piece two of them share. That is the
simplest rule there is, it is honest while a run is arriving, and it is not good
enough for a finished picture. Before anyone designs the replacement, the three
questions underneath need separating, because they are constantly confused and
only one of them is cheap.

**The seam.** Where two positions cover the same ground, which one supplies this
piece? Answerable anywhere, cheaply, and it has to be answered however the bytes
are served. The obvious rule — give the piece to whichever position's centre is
nearest — should *not* be built, and `docs/history/PLAN_showing_many_stores_as_one.md` task 3
sets out why at length: in two dimensions the boundary between two centres is
diagonal unless they happen to be level, so a position's owned region comes out
stair-stepped rather than rectangular, can be split into disconnected parts, and
changes *shape* when the stage moves slightly — so two runs of the same plate do
not produce the same picture. It also needs units, and these voxels are not cubes.
The plan proposes deciding on the acquisition's own grid of rows and columns
instead, which gives every position a plain rectangle and the same answer every
time.

**The phase.** Does a position's grid of pieces line up with the picture's? This
is the one that stops real data today, and **the seam rule cannot touch it** —
that was tried and produces an empty view. Deciding *which* position supplies a
piece cannot change *where* that position begins, and a position out of phase is
out of phase for every one of its pieces. No scheme of pointers can fix it,
because a pointer means *these bytes, verbatim*; that is equally true of Kerchunk
and VirtualiZarr. It is fixed in the acquisition or by decoding and recombining
pixels.

**The disagreement.** Two overlapping positions photograph the same specimen from
two stage positions, and until a stitcher has measured them they disagree slightly
about where things are. So when ownership hands a piece from one to the other, a
structure can appear to jump by that disagreement. **This is not bounded by
anything in the seam rule and is not improved by choosing a better seam.** It is
what stitching exists to remove, and it should be reported separately from
anything else the picture is measured on, so that one number does not hide the
other.

There is also a constraint the pointing arrangement adds. A position can only
supply pieces it fills *completely*, so it loses up to one piece at each edge and
an overlap cannot be trimmed to anything finer than a piece boundary without
decoding. Task 4 of the same plan suggests overlapping neighbours by at least two
pieces for that reason — with pieces of 128 that is 256 voxels, about 12% of a
2048-voxel tile, which is an ordinary overlap for stitching anyway.

**What we actually want is for the overlap not to be shown at all**, and that is
worth stating as the goal rather than leaving it implied. Crop each position back
so the overlapping strip is gone, and place what is left so the cropped positions
sit next to one another. There is still a disagreement where they meet, because
two positions photographed from two stage positions do not quite agree; if you do
not want that, the answer is to stitch. Nothing short of stitching removes it.

Two things make this much cheaper than it sounds, and both are already here.

**The interface already says it.** `PlacedTile` takes `taken_from` — where the
shown part begins inside the position — and `size`, how much of it to show. Its
own docstring says this is for "a run whose tiles overlap … to skip the strip its
neighbour is showing". Nothing needs inventing; `positions.py` simply does not use
those two fields yet, because it does not handle overlap.

**And cropping costs nothing at all.** This is the part worth understanding.
Cropping by pointing does not cut a single pixel: the view just points at *fewer
pieces* of each position. The bytes handed over are the same whole files they
always were, and the strip that is cropped away is simply never asked for. It
stays on disk inside the position, untouched, which is exactly what a stitcher
will want later.

The one rule is that the crop and the placement have to land on whole pieces —
`_refuse_a_placement_that_does_not_land_on_whole_pieces` checks `lands_at`,
`taken_from` and `size` all three. So the way to arrange it is from the piece
outwards rather than from the overlap inwards: **have the acquisition step by a
whole number of pieces, and show exactly that many pieces of each position.** The
cropped positions then tile the picture exactly, with no gap and no overlap, and
the leftover strip on each position is whatever the stage happened to give you.
With pieces of 128 and a 2048-voxel tile, stepping 1792 shows 14 pieces of 16 and
keeps an overlap of 256 voxels — about 12%, an ordinary overlap for stitching.

**Where would the cropping live?** Outside the zarr entirely, which is the part
worth being clear about. A position's entry in the map is counted in pieces:

    {"store": "positions/experiment_pos00042.ome.zarr",
     "at":   [0, 5, 3],      where its pieces begin in the picture
     "size": [1, 16, 16],    how many of them it supplies
     "from": [0, 0, 0]}      which of its own pieces the first one is

Cropping the overlap away is a change to two of those numbers — `"size"` becomes
`[1, 14, 14]` and `"from"` becomes `[0, 1, 1]`. **The position on disk is
byte-identical**, same file and same checksum; the trimmed strip is still inside
it and is simply never asked for, which is what a stitcher will want later. No
pixel is read, cut or rewritten anywhere.

**The coordinate system is the part to be careful about, and it has two halves —
one of them already safe and one of them not.**

A cropped position has to *move* with its crop. If a piece is taken off its low
edge, the part now being shown begins one piece further along the stage than the
position's own first voxel did, so it must be placed there. Leave it where the
stage was and the specimen is drawn a piece away from where it was acquired.

**That half is enforced.** `_where_the_view_begins` works the picture's corner out
as `tile_origin + (taken_from - lands_at) x voxel size`, so the crop is in the
arithmetic, and every position has to agree about the answer. Tried both ways on a
tile of 512 voxels stepped 384:

| | |
|---|---|
| cropped a piece off, **and moved it** by that piece | accepted, pieces `(0,4)` and `(4,7)`, butting up exactly |
| cropped a piece off, **left it at the stage position** | **refused** — "does not agree about where the view's low corner is" |

So positions ending up further apart than they were acquired cannot happen
quietly. Forgetting to move a cropped position is a refusal rather than a wrong
picture.

**The other half is not checked at all, and it is silent.** Nothing verifies that
the cropped positions actually *meet*. The corner check asks each position whether
it agrees with the others about where the picture begins; it says nothing about
whether the shown parts cover the ground between them. A first attempt at writing
this cropped a piece off each interior position but extended each by only the
step, which left every fourth piece uncovered — and it was accepted without
complaint. Ground no position covers is answered "there is nothing here" and drawn
as background, so **a cropping mistake one piece out appears as a thin blank
stripe between every pair of positions**, with nothing in the writer objecting.

Whoever builds this should add that check: for a raster, the shown parts must
tile the declared room with no gap. It is cheap — the map is already counted in
pieces — and it is the difference between a bug that shows itself and one that
looks like the specimen simply having nothing there.

And to be clear about what happens today: `positions.py` passes neither
`taken_from` nor `size`, so positions are shown whole. Hand it true overlapping
stage positions and both strips go into the map, and the later position wins for
the pieces they share. **So yes, there is overlap in the viewer today.** That is
honest while a run is arriving and wrong for a finished picture, which is the
whole reason this is the next piece of work.

There are two OME-Zarrs in play and it is worth keeping them apart. The
**positions** stay exactly as they were, down to the checksum — not even a
description is rewritten. The **picture's** own description is where the crop is
recorded, because that is where the whole map already lives::

    experiment.ome.zarr/zarr.json
      attributes:
        ome:    { multiscales, omero, ... }      the standard's
        zmart:  { tiles: [{store, at, size, from}, ...] }   ours, crop included

So the crop travels with the picture rather than in a file loose beside it, which
is the property this arrangement went to some trouble for. It sits under a key of
ours because the standard has no way to say "this image is assembled from these
sub-regions of those images" — which is the gap the map exists to fill in the
first place. Another tool reading the picture sees a well-formed attribute block
it does not understand, and ignores it. That is the same interoperability boundary
as everything else here rather than a new one.

Who decides is a separate question, and it has to be the **acquisition** rather
than the view builder. In a live run a position is handed over the moment it
lands, and its neighbour does not exist yet — so "half the shared strip" cannot be
worked out by looking at the positions, because the other half of the pair has not
been imaged. The acquisition is the only thing that knows the step before the run
happens. For a finished transfer somebody else wrote there is no acquisition to
ask, so there the view builder would have to infer the overlaps from the positions:
two callers, one piece of arithmetic between them.

The **server does nothing at all** here, and should not. It resolves what the map
says. The choice must not depend on which path served a piece, or the picture
would change as a cache filled.

The one thing `start_a_run` would need is the **step**. It knows `tile_shape`
today, and positions butt up only because the caller happens to pass `at` a whole
tile apart; it would have to be told `tile_step` up front, exactly as `cropped.py`
takes it.

Note this is the same idea `cropped.py` already implements for the *copying*
arrangement — trim half the shared strip off each tile so neighbours butt up — but
done by pointing instead of by writing a second copy. That is strictly better, and
it is a reason to read `cropped.py`'s `Trimming` before writing the arithmetic
again: it has already worked out how to halve an overlap, which edges of the scan
pattern must not be trimmed, and why.

The honest summary is that the seam is a day's work, the phase belongs in the
acquisition, and the disagreement is a stitching problem this project has
deliberately not taken on. Deciding which of the three is actually being asked
for is the first move.

### 4. Then take it to real data on a real machine

This is the one that matters, and everything above is tidying by comparison.
Nothing here has met a microscope. Every measurement in this file was made on
stores written for the purpose, on a sandbox with no graphics card, by a program
that also wrote the thing it was measuring.

**Expect drift to stop it at the first attempt, and that is the useful outcome.**
A stage asked to step 1792 voxels steps 1792 give or take two, and a position that
does not begin on a whole piece boundary is refused outright rather than drawn
slightly wrong. So the first real plate will very likely not open at all. That is
the refusal doing its job, not a surprise, and the fix is set out under "A drifted
run is refused" above — it belongs in the acquisition rather than here.

Run **`zmart-viewer/measure_what_a_transfer_looks_like.py` on the microscope
computer before building anything else.** It reports how your stores are really
written, whether any are sharded, and what fraction of them begin on a piece
boundary. That last number decides how much of a real transfer can be pointed at,
and everything else is guesswork until it is known. It has still never been run.

Three other things only real hardware can answer:

- **What a camera tile really costs.** Positions here were 256 to 512 voxels
  across; a real tile is 2048, which is sixteen to sixty-four times the area. The
  63 milliseconds a new position costs is mostly compressing pixels, so expect it
  to follow the area. Whether the writer keeps up with the camera is a question
  only the camera can answer.
- **What a graphics card does to the drawing.** Every frame rate here came from a
  software renderer, and two rows of an older comparison in
  `docs/open/HANDOVER_overlapping_runs.md` were noise for exactly that reason.
- **Windows, and the microscope PC's own constraints.** See
  `TESTING_ON_REAL_HARDWARE.md`: two conda environments that are not
  interchangeable, everything confined under `C:\ProgramData\MinicondaZMB\`, and a
  machine that refuses to run programs from folders a user can write to. It also
  records how a missing dependency shows up there — every test timing out with
  nothing said about the real cause.

---

## Things that were got wrong today, and corrected

Written down because each was believed for a while and each changed a decision.

**"Shrinking averages across the join between tiles."** It does not.
`TileCanvases._write_smaller_copies` in `zmart_storage/canvas.py` is `image[:, ::factor, ::factor]` — every second voxel kept, the
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
| `zmart-viewer/app/server/linking.py` | answers for a view while the viewer is open |
| `TileCanvases._write_smaller_copies` in `zmart_storage/canvas.py` | the line everything depends on |
| `docs/history/PLAN_showing_many_stores_as_one.md` | **the next piece of work** |
| `docs/history/PLAN_nothing_copied_at_all.md` | why a view writes nothing, and what the acquisition must do |
| `docs/open/OPEN_a_run_that_changes_while_you_watch.md` | the re-imaging question |
| `docs/open/HANDOVER_overlapping_runs.md` | every measurement, including the older copying arrangement |

## What to run

```
python -m pytest zmart_storage/tests/ -q                                   # 124 tests
python -m pytest zmart-viewer/tests/test_the_linked_view_matches_the_canvas.py -q
python -m pytest zmart-viewer/tests/test_a_growing_view_is_read_as_it_grows.py -q
python -m pytest zmart-viewer/tests/test_the_linked_view_draws.py -q
```

And, on a machine with a graphics card:

```
python zmart-viewer/measure_the_frame_rate_of_a_linked_view.py --steps 100,1600,6400
```

Every drawing measurement in this repository came from a software renderer. **If
your figures disagree with any here, yours are the real ones.**
