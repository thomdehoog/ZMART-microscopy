# Work order: what an acquisition must write for a run to be shown without copying it

Rewritten 5 August 2026. An earlier version of this document planned to fix drifted
runs inside the viewer, by moving the seam between overlapping tiles onto the
nearest piece boundary. That plan was tried against the real code before being
built, and it does not work. Why it does not work is written out below, because the
reasoning is the useful part and somebody will otherwise propose it again.

The question this document now answers is the one that actually matters for the
project: **what must an acquisition guarantee when it writes its tiles, so that a
run can be shown as one picture without a second copy of it — while the tiles stay
ordinary OME-Zarr that any other tool can read?**

---

## The problem in four sentences

A linked view hands the viewer a tile's own files untouched, which is only possible
when a piece of the view is exactly a piece of a tile, byte for byte. A microscope
stage asked to step 1792 voxels steps 1792 give or take a couple, so a real tile
begins a few voxels off the view's grid of pieces and no file of it holds the bytes
the view is asking for. `zmart_storage/linked.py` currently refuses such a run
rather than showing it wrongly, which is the right instinct and the wrong outcome.
The fix is not in the viewer at all — it is in **how the acquisition writes each
tile**, and it costs almost nothing once it is known.

---

## What was measured, before anything was planned

Two experiments were run against the code as it stands. Both wrote real tiles,
built a real view, and read it back through the viewer's own server over HTTP. The
tiles held **coordinate-coded** pixels — every voxel holds `1000 + the global x it
was acquired at` — so where a tile actually ended up on screen can be read straight
off the picture rather than inferred.

### The earlier plan, tried

Three tiles were placed at x = 0, 71 and 144, so that two of them began 7 and 16
voxels past a boundary of the 64-voxel pieces they were stored in.

- **"It must come out a whole number by construction" is not true.** The earlier
  plan's central step — take the first whole piece of the view the tile covers, and
  record which of the tile's own pieces that is — gives 0.891 of a piece for the
  tile at 71 and 0.750 for the tile at 144.
- **No other piece of the tile rescues it.** For the tile at 71 answering the
  view's piece at 128–192, its own pieces hold global voxels 71–135, 135–199 and
  199–263: off by −57, +7 and +71. There is no choice that is not wrong, because
  the pointer file records positions in whole pieces only and the drift is 7.
- **Serving it anyway moves the whole tile, not the seam.** With the refusal
  switched off, 128 of 208 columns of the picture held a value from somewhere else,
  displaced by exactly 7 and 16 voxels — the drift. 9216 of 13312 voxels differed
  from the canvas written from the same tiles.
- **The zoom levels then disagree with each other.** The smaller copies are written
  from the tiles' pixels at their true positions, so they came out exactly right —
  0 of 3328 voxels differing. The operator would see the specimen jump by several
  voxels on zooming in.
- **And under the earlier plan's own "covers completely" rule, the drifted tiles
  own nothing at all.** A tile is currently stored as one piece per plane (see
  below), so a tile that is out of step covers no whole piece of the view, and the
  view comes out empty.

That last point is worth sitting with. Implemented faithfully, the earlier plan
refuses exactly the runs the current code already refuses; implemented loosely, it
draws the specimen in the wrong place. There is no version of it that helps.

### The correction, tried

Three tiles 512 voxels across, stepping 384 (so neighbours overlap by 128), drifting
by 0, 7 and 16 voxels — but each one **written with its own grid of pieces aligned
to the run's grid**, by padding its low edge by however far the stage had drifted
past a piece boundary.

`zmart_storage/linked.py` was then asked to build a view over them **with no change
to it whatsoever**. It built the view without complaint, wrote nothing of the
full-size picture, and every one of the 163,840 voxels served read its own
coordinate. Nothing was displaced. The drift cost nothing.

---

## Why the earlier plan could not have worked

The reason is already written down in this repository, in two places, and both were
right.

`zmart_storage/linked.py` says it in its own opening docstring: *"zarr describes an
image as one regular grid, so a view can keep a tile's true position or hand over
its files untouched, but not both."*

`LINKING_INSTEAD_OF_COPYING.md` says it too, in "The condition, and what it costs
us": *"the choice is genuinely between the tile's true position and byte-for-byte
passthrough; a view cannot have both. That is not a limitation of this
implementation, it is a property of the format."*

The earlier plan then proposed an arrangement that claimed both — the tile still
supplies whole pieces of itself, *and* the picture is right to within the drift —
three paragraphs after the impossibility was stated. That is the flaw, and it is a
flaw of reasoning rather than of implementation. **Seam ownership decides which of
two overlapping tiles supplies a piece. It has no way to affect where that piece's
pixels land, because the pointer file counts in whole pieces and the drift is a few
voxels.** The two problems are independent, and only one of them was being solved.

The way out is to stop treating the tile's grid as fixed. It is not fixed; the
acquisition chooses it. Align it when the tile is written, and the impossibility
above simply does not arise — the tile's true position *is* a whole number of
pieces, so there is nothing to trade away.

### Two smaller things the earlier plan got wrong, for completeness

- Its final test rule said *"Every existing test in this file must still pass
  untouched. If any needed changing, the ownership rule ... is wrong."* But its
  task 2 deleted the refusal that
  `test_it_refuses_a_tile_that_would_not_land_on_whole_pieces`
  (`viz_studio/tests/test_the_linked_view_matches_the_canvas.py:359`) exists to
  check. By its own stated criterion, it was wrong.
- Its stated error bound — *"at most half a piece, which is 64 voxels with pieces
  of 128"* — describes pieces that tiles are not currently written in. A tile is
  stored as **one piece per plane** (`zmart_storage/cropped.py:949` sets
  `chunk = max(tile_shape[1], tile_shape[2])`), so a piece is the whole tile and
  half a piece is half a tile: 1024 voxels for a 2048-voxel tile, not 64.

---

## The three ways to show a run, and which to build

This is the decision the project actually faces, so it is set out plainly. All
three produce an OME-Zarr any other tool can open; they differ in what is written
and in what the acquisition has to promise.

**1. Write only the mosaic.** Put each tile straight into one big image at its true
place and keep no separate tile stores. Nothing has to line up, because there is
only one grid. This is the most interoperable thing that can be written and it has
no constraints at all — but it does not keep the untouched tiles a stitcher needs,
and a tile is altered on the way in wherever two of them overlap.

**2. Write the tiles, and point at them.** Keep every tile exactly as the camera
recorded it, and describe the mosaic as a list of pointers into those tiles. This
is what `zmart_storage/linked.py` does, and it is the only arrangement that keeps
both the raw tiles and a single picture without paying for the picture twice. It is
the one to build. Its price is the set of rules in the next section — which are
rules about *how* the tiles are written, not about what is in them.

**3. Assemble on the fly.** Let the viewer read whatever it is given, cutting and
recompressing pieces as requests arrive, with a cache. This asks nothing of the
acquisition, which is genuinely attractive. It is also much harder, it puts pixel
work in the path of every request, and the cache is a second copy by another name.
Worth revisiting only if the rules below turn out to be unacceptable at the
instrument.

The rest of this document builds option 2.

---

## The rules an acquisition must follow

These are the answer to "what should I be allowed to write". Each one says what it
buys, because a rule whose reason is not written down gets dropped the first time it
is inconvenient.

**1. Cut tiles into pieces much smaller than the tile.** A piece — a *chunk*, in
zarr's own word — is one file on disk. Use the same size in y and x for every tile
and for the view: **128 or 256 voxels** is the sensible range. This is the rule that
does not hold today, and everything else depends on it: a tile currently stored as
one piece per plane can only ever be placed as a single indivisible block.

**2. Begin every tile a whole number of pieces from the run's corner.** Where the
stage really went is not a whole number of pieces, so pad the tile's low edge by
however far it overshot — `pad = position mod piece` — and record the tile's corner
as the padded start. This is what makes the tile's pieces and the view's pieces the
same pieces. It is one subtraction at write time and it is the whole of the fix.

**3. Do not worry about where a tile ends.** Its last piece may run past the real
pixels; that piece is simply never handed to the view. Only the low edge has to be
aligned.

**4. Overlap neighbouring tiles by at least two pieces.** A tile can only supply
pieces it fills completely, so it loses up to one piece at each edge — the padded
one at the start, the ragged one at the end. Two pieces of overlap guarantees a
neighbour covers that loss whatever the drift. With pieces of 128 that is 256
voxels, about 12% of a 2048-voxel tile, which is an ordinary overlap for stitching
anyway.

**5. Do not shard the full-size tiles.** Sharding packs many pieces into one larger
file, so a piece stops being a file that can be handed over. Shard the smaller
zoomed-out copies if it helps; leave the full-size tiles unsharded.

**6. Write every tile the same way.** Same kind of number, same compression, same
fill value, same separator, same generation of OME-Zarr. `linked.py` already checks
this exactly and refuses a mismatch, because a difference here does not raise an
error — it draws noise.

**7. Keep one plane, one colour and one moment per piece.** Already true, and
already checked.

### What these rules cost, said honestly

The only real cost is rule 2. A padded tile holds up to `piece − 1` voxels of fill
value along its low edge — up to 127 voxels with pieces of 128, which is about 6% of
a 2048-voxel tile. Any other tool opening that tile sees those voxels as data. That
is a genuine interoperability cost and it should be handled by **recording the pad
in the tile's own attributes**, so that a stitcher, or anyone else who cares, can
crop it away. Extra attributes are ignored by readers that do not know them, so
this costs nothing in compatibility.

Everything else on the list is free. Smaller pieces mean more files, which is the
ordinary trade every zarr writer makes; 128 or 256 keeps a 2048-voxel tile at 256 or
64 files per plane, which is unremarkable. Nothing here makes a tile less readable
by napari, Fiji, `ngff-zarr` or `multiview-stitcher`; a padded, finely-chunked tile
is an ordinary OME-Zarr image in every respect.

---

## Tasks, in the order to do them

### 1. Let a tile be written in pieces, and align it

**Where:** `zmart_storage/cropped.py`, `_WholeTileImage.declare` (line 914), which
currently hard-codes `chunk = max(tile_shape[1], tile_shape[2])` at line 949.

Give it a piece size, and pad the tile's low edge so that its corner sits a whole
number of pieces from the run's own corner. The tile's recorded position must be the
padded corner, not the stage reading, or every other tool will draw it a few voxels
out. Record the pad alongside it so the padding can be told from specimen.

Default the piece size to 128. A caller that wants the old behaviour — one piece per
plane — can still ask for it, and should keep getting it, because a run that is
never going to be linked has no reason to pay for more files.

### 2. Say where the padding is

**Where:** the tile's own attributes, written by the same function.

Two numbers per axis: how much was padded, and where the real pixels begin. This is
what lets a stitcher use these tiles without measuring the padding as signal, and it
is what makes rule 2 above honest rather than a hidden alteration.

### 3. Give each piece of the view to exactly one tile

**Where:** `zmart_storage/linked.py`, around `PlacedTile` (line 142).

This is the part of the earlier plan that survives, and it is now solvable, because
the pieces genuinely line up. For each tile work out the pieces it can fill
completely — from `ceil(position / piece)` to `floor((position + size) / piece)` —
and where two tiles can both fill a piece, give it to whichever tile's centre is
nearer, breaking ties by position so the same run always builds the same view.

The seam then lands on a piece boundary rather than on the midline of the overlap,
which moves it by less than half a piece. **That is a seam moving, and this time the
word is accurate: no voxel is displaced, because every piece served still holds the
pixels the stage recorded at the position it recorded them.**

### 4. Keep the refusal, and make it say more

**Where:** `_refuse_a_placement_that_does_not_land_on_whole_pieces` (line 503).

Do not delete it. It is the check that catches exactly the failure measured above,
and the measurements are what earn it its place. What it should gain is a better
message: a tile that is not aligned was written by an acquisition that did not
follow rule 2, so the message should say that, and say which rule, rather than
suggesting the tiles be placed on a grid by hand.

Add one refusal beside it, for a run whose tiles overlap by less than two pieces —
that run will have holes in it, and a hole is better refused than drawn.

### 5. Tell a missing file apart from ground nobody imaged

Unchanged from the earlier plan, and still worth doing, though it is a separate
piece of work from everything above and can be done independently.

**Where:** `viz_studio/backend/linking.py`, and wherever the server answers.

Both currently answer 404. That is correct for ground nobody imaged and quietly
wrong for a tile file that has been deleted, moved, or half-written. **Keep the 404
on the wire** — Neuroglancer treats 403, 404 and a failed connection as "this piece
is absent" and fills from the fill value, whereas a politer 204 is read as a
successful empty reply and fails to decode. What to add is a note beside it: when
the pointer list says a tile should be there and the file is not, log it once per
tile rather than once per piece, and surface it in the viewer's status.

For a run still being acquired, "not written yet" and "written and then lost" are
different things and should be logged differently, or a run in progress will fill
the status with problems that are not problems.

---

## Tests

Add to `viz_studio/tests/test_a_drifted_run_is_placed_truthfully.py`, which this
work order comes with — it already holds the second experiment above as a test.

- **A drifted run opens, and every voxel is where the stage says.** Tiles nudged by
  one, two and seven voxels, written with aligned pieces, compared voxel for voxel
  against coordinate-coded truth. This is the test the whole arrangement stands on.
- **An unaligned tile is still refused**, with a message naming the rule it broke.
- **A run overlapping by less than two pieces is refused** before it can be drawn
  with holes.
- **Every piece has exactly one owner.** Walk the view's whole grid: no piece
  claimed twice, and every piece that some tile can completely fill has an owner.
  Include a four-tile junction, and a junction with one tile missing.
- **No padding is served.** Fill each tile's pad with a value that appears nowhere
  else and check it never appears in the view. This is the test that catches a tile
  owning a piece it cannot completely fill.
- **The zoom levels agree.** Compare the full-size picture against the smaller
  copies. The measurement above found them disagreeing, and that is the failure an
  operator notices first.
- **The same run always gives the same view.** Build it twice, compare the pointer
  files.
- **An undrifted run is unchanged.** Every existing test in
  `test_the_linked_view_matches_the_canvas.py` must still pass untouched — including
  the refusal test at line 359, which this plan keeps rather than deletes.

### What to run before saying it is done

```
python -m pytest zmart_storage/tests/ -q
python -m pytest viz_studio/tests/test_a_drifted_run_is_placed_truthfully.py -q
python -m pytest viz_studio/tests/test_the_linked_view_matches_the_canvas.py -q
python -m pytest viz_studio/tests/test_the_linked_view_draws.py -q
```

All of `zmart_storage/tests/` passes today (112 tests); it must still.

---

## What this work is not

- **Not stitching.** Nothing here measures where a tile really went. It shows the
  run at the accuracy the stage reports — but now genuinely at that accuracy, rather
  than at the stage's accuracy minus a quantisation nobody wrote down.
- **Not blending.** Each piece comes from one tile, whole.
- **Not the zoomed-out copies.** Those genuinely cannot be pointed at and are still
  written once, at about a quarter of the picture.

## Things not to do

- **Do not round a tile to the nearest whole piece.** It displaces every voxel of
  the tile by up to half a piece, and — as measured above — it is what the pointer
  file will silently do if handed a tile that is not aligned. This is the failure
  the refusal in task 4 exists to prevent.
- **Do not fall back to cutting and pasting pixels inside a request.** That is
  strategy 3 above, and if it is ever wanted it should be chosen deliberately rather
  than arrived at by accident.
- **Do not describe a quantisation as a moved seam.** A seam moves when ownership
  changes between two tiles that both hold the right pixels. Pixels appearing away
  from where they were acquired is a different thing, and calling it a seam hides
  it.
