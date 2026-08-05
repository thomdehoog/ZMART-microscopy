# Serving a slot-per-tile store as though it were one ordinary image

A plan for building the thing `TILES_IN_ONE_STORE.md` measured, and for finding
out what it is worth in the viewer rather than on a bench.

Written 5 August 2026. Nothing here is built.

---

## What it changes

One new ability in the backend: a store may hold its tiles in **slots of its own
choosing**, and the server presents it to the viewer as an ordinary OME-Zarr whose
tiles are in their true places on the stage.

Nothing changes in the front end, and that is the point. Neuroglancer receives a
perfectly conventional multiscale OME-Zarr — one source, one pyramid — and never
learns that tiles exist.

---

## Why

The project has had to choose between two things it wants.

**One store is what makes the viewer quick.** `measure_one_stitched_store.py`:
one image draws at 255 frames in five seconds where the same specimen as 300
positions manages 62, because Neuroglancer builds render layers per source and all
of them take part in every frame.

**Overlap is what stitching needs**, and an image holds one value per voxel, so
writing overlapping tiles into one destroys the strip a stitcher compares.
`DATA_LAYOUT.md` Decision 1b records the trade as unavoidable.

It is avoidable. Give every tile a slot of its own in one image — nothing cropped,
no two tiles sharing ground — and work out where each belongs when the picture is
*read*. Measured in `measure_tiles_in_one_store.py` and
`measure_ten_thousand_tiles.py`:

| | |
| --- | --- |
| a piece of full-resolution picture | 6 ms, about 4× a plain read |
| the same at ten thousand tiles | 13.4 ms on a raster, 6.9 ms scattered |
| tiles touched by one piece | at most 9, whatever the run's size |
| agreement with the true picture | exact, 0 grey levels |

Flat with the size of the run, which is the property that matters and the one that
stitching on the spot did not have — `measure_live_fusion_cost.py` measured that at
110× to 645× a plain read, growing worse as the run grows.

**But every one of those numbers is from a bench, not from the viewer.** They say
pieces can be produced fast enough. They do not say what an operator would see.
That is what this plan is for.

---

## The design, concretely

### What the store looks like on disk

One OME-Zarr, written by `zmart_storage`, holding:

- **`0/`** — the full-resolution image, laid out in slots. A tile of 256 voxels
  occupies a slot 256 wide, so slot *k* begins at `k × 256`, regardless of where
  the tile truly sits.
- **`2/`, `3/`, …** — the coarse copies, written in **true geometry**, once. These
  are read and served unchanged.
- **`1/`** — undecided; see "What has to be decided".
- **`tiles.json`** — the manifest: for each tile, its slot and where it truly
  belongs, in voxels. This is the only new thing on disk and it is small — ten
  thousand tiles is a few hundred kilobytes.

### What the server does

`_serve_from_data` in `backend/server.py` currently resolves a path under `/data/`
to a file and sends it. The change is one branch: if the store carries a
`tiles.json`, answer from a placing reader instead of from disk.

That reader answers three kinds of question:

- **The description** (`.zattrs`, or `zarr.json` for 0.5) — synthesised to describe
  the *true* picture: its shape, its axes, its pyramid, and a translation beside
  each resolution. Not the slot layout, which the viewer must never see.
- **`.zarray` per level** — likewise the true shape.
- **A chunk** — assembled. Look up which tiles touch this piece, read the matching
  rectangle out of each tile's slot, copy them in acquisition order so the later
  tile wins.

For the coarse copies the reader steps aside and the existing file path serves
them, because they are already in true geometry.

### Why this is not the viewing window that was rejected

Worth stating plainly, because it looks similar and is not. The rejected proposal
had the *viewer* keep its own idea of what is on screen and hand the engine fewer
sources than it was given — wrong invisibly when it guessed wrong.

Here the engine is given **one** source and asks for whatever chunks it wants. It
does its own culling, which it is better at than we would be. The server answers
questions; it never decides what the operator may see.

---

## What has to be decided, and in this order

### 1. Compression, which is the largest risk to the whole idea

**Every measurement so far read uncompressed data.** Real stores are compressed —
the 75 GB acquisition uses zstd. Assembling one piece means reading up to nine
rectangles, each of which may live in a different compressed chunk, and each of
those has to be decompressed whole to get at the part wanted.

So the true cost could be several times the 6 ms measured, and it is the single
most likely thing to sink this. **Measure it before building anything else.** It is
a small change to `measure_tiles_in_one_store.py`: give the store a compressor and
re-run.

If it is bad, the fallback is a slot layout whose slots align with chunk
boundaries, so a rectangle read never straddles two compressed chunks — which a
tile of 256 in chunks of 256 already satisfies, and which is worth checking is
actually what happens.

### 2. Whether copy 1 is placed or written out

Measured at 12.9–14.1 ms a piece, against 6 ms for full resolution. Playable but
noticeably slower. Writing it out costs a further 25% of the data on top of the 8%
the coarser ones cost, which may be the better trade. **Decide by measuring both
through the viewer**, not by argument.

### 3. The chunk-key separator, which has bitten this project before

`LIVE_MODE_PLAN.md` §2 records that nested (`/`) and flat (`.`) chunk keys each
break a different mechanism, and that no choice gives both.

This design changes that calculus and the change should be checked rather than
assumed: the keys the *viewer* asks for are in true geometry and are synthesised,
so they need not match the layout on disk at all. The two can differ. Whether that
frees the decision or merely moves it is the thing to work out.

### 4. What the served chunks are encoded as

Simplest is to declare no compressor on the served arrays, since this is a browser
talking to a server on the same machine, and hand back raw bytes. That avoids
compressing something that was just decompressed. It should be stated in the
description rather than assumed to be the default.

---

## What is not in scope

- **Blending the seams.** Where two tiles meet, the later one wins, and the join
  will be visible. `INTEROP.md` §3 has the cure — a cosine ramp, about fifteen
  lines of shader — and it is a separate piece of work.
- **Sub-voxel or rotated placement.** This arrangement moves tiles by whole voxels.
  A run needing anything else needs real resampling, and that is the hundreds of
  milliseconds `measure_live_fusion_cost.py` measured. A run that trusts its stage
  is the case in scope.
- **Live updating.** The layout suits it — no two tiles share a chunk file, so the
  concurrent-write hazard cannot arise — but keeping the written-out coarse copies
  current as tiles land is design work of its own, and doing it here would make
  this plan two plans.
- **Changing the writer.** For measuring, a fixture that writes a slot-per-tile
  store is enough. `zmart_storage` learning to write one is the step after this.

---

## How it gets measured, which is the point of the exercise

Everything is a comparison against the same run written as an ordinary
true-geometry image, because absolute frame rates on a machine with no graphics
card mean very little and the sandbox has no graphics card.

| what | how | what would count as good |
| --- | --- | --- |
| first pixel | `tests/pixels.py` | within a second of the control |
| drawing rate | `tests/test_the_drawing_keeps_up.py`, pointed at both | keeps most of the control's rate |
| a contrast nudge | `check_scale.py` reports it | near the control's, not near the 191 ms of a thousand stores |
| scrolling in z | frames counted while stepping planes | no worse than the control |
| **the volume** | the same, in 3D | this is the one expected to hurt |
| requests | counted by the harness | comparable to the control |

**The volume is where I expect trouble and it should be measured first among the
drawing tests.** A ray marching through depth asks for far more pieces than a
slice does, and this project's chunks hold a single plane each — deliberately, so
that scrolling never fetches neighbours — which is close to the worst shape for
it. If the volume is bad, the question becomes whether a different chunk shape for
the served arrays fixes it, and that is a decision this plan should not pre-empt.

---

## How you would know it was finished

1. A store written in slots opens in the viewer and draws the same picture, voxel
   for voxel, as the same run written in true geometry. A test, not an eyeball.
2. The drawing-rate comparison above is recorded in `TILES_IN_ONE_STORE.md` with
   the same honesty as the bench numbers — including if it is bad.
3. The volume has a number, which it does not have today for any arrangement.
4. `check_scale.py` runs against a slot store and reports sensibly.
5. Whatever is decided about compression, copy 1 and the separator is written down
   with the measurement that decided it.

---

## What would falsify this, and what happens then

- **Compression multiplies the per-piece cost.** Most likely failure. Fall back to
  slot-and-chunk alignment; if that does not do it, the arrangement is for
  uncompressed stores only, which is a much narrower claim and should be said.
- **The volume is unusable.** Then this helps 2D and not 3D, which given how much
  3D matters would make it a partial answer rather than the answer.
- **Concurrency does not hold.** The 6 ms is one piece at a time in one thread. The
  viewer asks for many at once, and Python may not multiply the way the arithmetic
  suggests. If throughput per second is far below `1000 / 6 × threads`, that is the
  real ceiling and it should replace the per-piece number in the write-up.
- **It is fast and the picture is wrong.** The least likely and the worst. The
  voxel-for-voxel test above exists for this and should be written first.
