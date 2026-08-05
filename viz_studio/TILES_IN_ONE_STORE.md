# Keeping every tile whole in one image, and placing them when they are read

Written 5 August 2026, after measuring three ways of giving the viewer a single
source without throwing the overlap away. Everything here was measured on this
sandbox; the scripts are beside this file so the numbers can be re-taken rather
than believed.

---

## The problem this is trying to get around

Two things the project wants have so far been in direct conflict.

**The viewer needs one store.** `NEXT_STEPS.md` establishes this and
`measure_one_stitched_store.py` measures it: one image draws at 255 frames in five
seconds where the same specimen as 300 separate positions manages 62, because
Neuroglancer builds render layers per source and every one of them takes part in
every frame. At a thousand positions the viewer manages 24 frames in five seconds
and a contrast slider costs 191 milliseconds a step.

**Stitching needs the overlap.** Tiles are acquired overlapping on purpose, so a
stitcher can compare the two views of the shared strip and work out where the
stage really went. `DATA_LAYOUT.md` Decision 1b records the cost of writing tiles
into one image: an image holds one value per voxel, so the second tile written
replaces the first in the strip they share, and no later step can get it back.

So: one image is fast and loses the overlap; many images keep the overlap and are
slow. That is the trade this document is about.

---

## Three ways out, and what each measured

### 1. Stitch on the spot, every time a picture is asked for — **too slow**

Leave the tiles alone on disk and put a program in front of them that pretends to
be one stitched image, stitching each piece as it is requested. The viewer holds
one source; nothing is copied; the overlap survives. `multiview-stitcher` has this
built as `serve_virtual_ome_zarrs`, and it works correctly.

It is not quick enough. Measured by `measure_live_fusion_cost.py`, on sixteen
tiles:

| level | stitched on the spot | read from disk | ratio |
| --- | --- | --- | --- |
| 0 (finest) | 688 ms | 6.3 ms | 110× |
| 1 | 969 ms | 4.5 ms | 217× |
| 2 | 2 984 ms | 4.6 ms | 645× |
| 3 (coarsest) | 583 ms | 4.4 ms | 134× |

A single view needs tens of pieces, so this is seconds per view rather than frames
per second.

Worse, it goes the wrong way as a run grows. Timing the coarsest piece — the one a
zoomed-out view needs — against the number of tiles:

| tiles | planning the stitch | coarsest piece | finest piece |
| --- | --- | --- | --- |
| 4 | 0.29 s | 81 ms | 212 ms |
| 9 | 0.75 s | 232 ms | 179 ms |
| 16 | 1.46 s | 283 ms | 180 ms |
| 36 | 3.30 s | 1 248 ms | 168 ms |
| 64 | 6.82 s | 963 ms | 173 ms |

Two things to read out of that. The coarsest piece grows roughly in step with the
number of tiles, because a piece covering the whole specimen has every tile
overlapping it — so the zoomed-out view, which is the case that most needs help,
is the case this helps least. And planning alone costs about a tenth of a second
per tile, which is something like seventeen minutes at ten thousand tiles before
any picture appears.

**This is not a fault in the library.** Stitching properly means resampling every
tile through its own transformation and building smooth blending weights across
the seams — exactly right when tiles are rotated or shifted by fractions of a
voxel, and exactly why `multiview-stitcher` uses this to inspect a few dozen tiles
during registration rather than to browse thousands.

### 2. Write the stitch out once — **works, at the price of a copy**

Fuse the tiles and write the result to a real OME-Zarr. Pieces are then ordinary
file reads at 4–7 ms, the viewer holds one source, and the frame rate is the one
already measured for a single store.

The price is the copy: the data exists twice, and the raw tiles have to be kept
because the fused image no longer holds the overlap. `DATA_LAYOUT.md` Decision 1b
sets out why copying a finished run is not offered as a route.

### 3. Keep every tile whole in one image, and place them on the way out — **quick, and exact**

This is the one worth building.

Write **one** image in which each tile has a slot of its own, laid side by side.
No tile is cropped, no two tiles share any ground, and nothing is written twice.
What is on disk is a contact sheet rather than a specimen: a tile sits at
`k × 256` where it truly belongs at `k × 224`, so the picture is stretched by the
overlap at every seam.

Then place the tiles when the picture is **read**. Producing a piece of the true
picture means working out which tiles touch it and copying rectangles out of their
slots. Where two tiles genuinely cover the same ground the later one wins, which is
the rule the viewer already uses when two acquisitions are laid over one another.

Measured by `measure_tiles_in_one_store.py`:

| tiles | placing them on the way out | plain read | ratio | disagreement |
| --- | --- | --- | --- | --- |
| 16 | 5.45 ms | 1.42 ms | 3.8× | 0 grey levels |
| 64 | 6.36 ms | 1.65 ms | 3.8× | 0 grey levels |
| 256 | 5.87 ms | 1.39 ms | 4.2× | 0 grey levels |
| 576 | 6.06 ms | 1.42 ms | 4.3× | 0 grey levels |

**Flat.** Thirty-six times the tiles, the same cost per piece — because a piece is
touched by about four tiles whether the run holds sixteen of them or ten thousand.
That is the property the stitch-on-the-spot arrangement did not have, and it is the
one that decides whether something holds at the scale this project is aiming for.

It is also not an approximation: the picture produced is the same picture, voxel
for voxel, as the one written in true geometry.

Roughly a hundred and fifteen times quicker than stitching the same piece live,
and the reason is simply that it does less: whole-voxel moves and rectangle copies,
with no arithmetic on the pixels at all.

---

## What this arrangement buys, stated plainly

**On disk** there is one image. Every tile is whole, the overlap between
neighbours is intact and available to a stitcher, and no two tiles share a piece of
the file — which also dissolves the concurrent-write hazard measured in
`DATA_LAYOUT.md`, where tiles straddling a piece boundary lost up to 75% of their
voxels. Tiles here never share ground, so there is nothing to lose.

**On screen** the viewer sees a single source, so the frame rate stops depending
on how many tiles the run acquired.

**And the two become independent**, which is the part that matters most. Where a
tile lives in the file and where it belongs on the stage are now separate
questions, and the second is answered at read time. That means the arrangement can
be changed afterwards without rewriting anything: butted up, true stage geometry,
or a stitcher's corrected positions once registration has run.

---

## What it costs, and where it does not apply

**Hard seams, not blended ones.** Where two tiles meet, one of them simply wins.
`INTEROP.md` §3 describes the cure — a cosine ramp from each store's declared
rectangle, about fifteen lines of shader — and it applies here unchanged.

**Whole-voxel shifts only.** A tile shifted by a fraction of a voxel, or rotated,
needs resampling, and resampling is where the hundreds of milliseconds live. A run
that trusts its stage satisfies this; one that does not should keep its tiles
separate and stitch afterwards, which is Decision 1 and remains correct.

**A little wasted room.** The image is larger than the specimen by the overlap at
every seam — about 14% at a 32-voxel overlap on 256-voxel tiles. Nothing is written
into the gaps, so it costs description rather than disk.

**The coarse copies cost more, and the same script now measures how much.** A
piece of a smaller copy covers more of the specimen, so more tiles have to be
touched to produce it. The question was whether that number is set by *which copy*
— bounded, and so survivable — or by *how many tiles the run holds*, which would
have been the same wall stitching on the spot hit.

It is set by the copy. Measured at two run sizes:

| copy | 64 tiles | 576 tiles | most tiles touched |
| --- | --- | --- | --- |
| 0 (full resolution) | 5.96 ms | 6.11 ms | 4 → 6 |
| 1 | 12.88 ms | 14.06 ms | 9 → 12 |
| 2 | 27.86 ms | 41.51 ms | 25 → 36 |
| 3 | 97.80 ms | 80.92 ms | 64 → 100 |
| 4 | 95.39 ms | 145.14 ms | 64 → 361 |

Read the last column. Going from 64 tiles to 576 — nine times as many — the tiles
touched by one piece rise only from 25 to 36 at copy 2, and from 64 to 100 at copy
3. They are converging on a ceiling set by the copy rather than by the run: a piece
of copy *k* covers `256 × 2^k` voxels of specimen, which spans about
`(1.14 × 2^k + 1)²` tiles however many the run holds. That predicts 102 at copy 3
and 372 at copy 4, and the measurements land on 100 and 361.

So the ceiling is real, but it quadruples with every copy. By copy 3 a piece costs
around 90 ms, which is too slow to pan through.

**The arrangement that follows is a hybrid, and it is cheap.** Place tiles for the
sharp copies, and write the coarse ones out once:

- **Copies 0 and 1** — placed on the way out, 6 to 14 ms a piece, flat as the run
  grows. This is where nearly all the data is.
- **Copies 2 and beyond** — written out in true geometry, then read as ordinary
  pieces at a millisecond or two.

The coarse copies are a twelfth of the data — a quarter of the size each time, so
`1/16 + 1/64 + …` comes to about 8% of the full-resolution level. So roughly 8%
more disk buys a zoomed-out view that is as quick as any ordinary image, while the
92% that is the full-resolution picture is never duplicated at all, and the overlap
inside it stays intact.

**One rule to get right when acquiring**, and it is quiet rather than loud if
missed. Placing a tile by whole voxels only works while the stage's step divides
exactly by the shrinking factor. The step used in these measurements is 224
voxels, which is 32 × 7, so it divides cleanly down to the fifth copy and no
further. **Choose the overlap so that the step divides by two at least as many
times as there are copies** — otherwise the coarse copies place tiles half a voxel
out, which is exactly the kind of fault that looks like a slightly soft picture
rather than like a bug.

---

## Where the pieces are

| | |
| --- | --- |
| `measure_tiles_in_one_store.py` | the arrangement above, timed against a plain read |
| `measure_live_fusion_cost.py` | stitching on the spot, timed the same way |
| `measure_one_stitched_store.py` | one store against many, in the viewer itself |
| `DATA_LAYOUT.md` Decision 1b | why one image normally destroys the overlap |
| `INTEROP.md` §3 | the cosine ramp that would soften the seams |

None of this is built. What is here is a measured case for building it, and two
scripts that will say plainly if the case stops holding.

---

## What has not been measured, so that nobody reads more into this than is here

Everything above times the **server's** side of the work: producing a piece of
picture, on this sandbox, with no browser involved. That is deliberate, because it
is the part that decides the question and it needs no graphics card to measure
honestly.

What has *not* been done is to put this behind the viewer and watch it draw. So
these numbers say the arrangement can produce pieces quickly enough; they do not
yet say what frame rate an operator would see. The step after building it is to
run `check_scale.py` and `tests/test_the_drawing_keeps_up.py` against a server
serving a store this way, which is the same bar every other arrangement here was
judged against.

The tiles were also synthetic and small. Real tiles are larger, which should
favour this arrangement — the per-piece cost is dominated by working out which
tiles are involved rather than by moving the voxels — but that is a reasonable
expectation rather than a measurement.
