# A position has a place; a grid is one way of choosing places

Written 21 August 2026, at the end of the evening the load window was reworked.
This is a plan rather than a description: none of it is built yet.

## What is wrong today, in one sentence

A run written through the live path is **a profile and a set of grid cells**, so
a position's place is worked out as `cell × step` rather than recorded — and a
dataset whose positions do not sit on a regular grid cannot be written, or
replayed, at all.

## Why that matters more than it sounds

The replay door exists so that smart microscopy can be rehearsed without a
microscope in the room. Its whole value is that **nothing about the live path is
faked**: the positions go through the same writer, the same sealed profile, the
same manifest, one commit each, exactly as they would during an acquisition.

That is also what makes the limit so awkward. A replay that quietly took a
different road for awkward data would still show a picture, and would no longer
be a rehearsal of anything. So the fix cannot be a second path for difficult
runs; it has to be the one path, made able to say where a position is.

The operator put it plainly: the way it works while testing must not differ
much from the way it will work in a real experiment.

## What is already right, and is worth knowing before changing anything

Three things are already the way they need to be, which is what makes this a
contained change rather than a rewrite.

**A placement already carries an origin.** `PositionPlacement` has an `origin`
field placing the tile in the run's shared coordinates. Nothing needs to be
invented to hold a position's place; it is simply always filled in from a cell.

**The picture already has the right rule.** `PositionPlacement` says so
outright: *the picture itself records no region at all: a tile is drawn whole,
and where two tiles cover the same ground the one committed later lands on top.*
That is exactly the rule wanted for awkward runs — no blending, last one wins —
and it is already what both the composer and the viewer do.

**The seam rule does not touch the picture.** The regions worked out in
`plan_one_tile` are *analysis* boundaries: which tile's measurements count where
two overlap, so an object near a join is not counted twice. `plan_one_tile` says
this itself — *the picture shows the tile whole, there is no visual trimming to
record*. So arbitrary positions can be drawn correctly without settling any
question about counting, and the two can be changed one at a time.

## The change

**A position's place becomes something it carries rather than something derived
from its index.**

1. **Planning takes an origin.** The general act is placing a position at a
   known place. `plan_one_tile(profile, cell, ...)` keeps working and becomes a
   thin thing that computes `cell × step` and calls the general one. The regular
   grid is then a *way of generating places*, which is what it has always
   actually been, rather than the only way a place can exist.

2. **A run's identity becomes its placements.** `place_the_tiles(profile, cells)`
   and the coordinator's `self.cells` become a set of placed positions. A gridded
   acquisition builds that set from cells exactly as now, so nothing about a real
   ZMART run changes shape.

3. **`locations.json` records places.** It already exists to say where every
   position the run will ever image sits, fixed before the first pixel. It
   records what it says it records. This is the operator's own point: the
   positions of an experiment are known upfront, which is precisely why this is
   possible at all.

4. **Ownership follows real geometry.** Where a position has no neighbour
   sharing ground, it counts its whole frame. Where it does, the counting
   boundary sits in the middle of the ground actually shared, decided from the
   boxes rather than from `row ± 1`. Deterministic and independent of the order
   positions arrive in, which is the property the grid rule was protecting.

5. **The replay stops refusing.** `rehearsal.py` maps a dataset onto the live
   writer by reading its geometry; with places recorded rather than derived it
   plans each position at the place the dataset actually puts it. The
   `GRID_TOLERANCE_UM` refusal goes, along with the paragraph in its docstring
   promising it.

## What it touches

`zmart_live/ownership.py`, `zmart_live/model.py`, `zmart_live/coordinator.py`,
`zmart_live/profiles.py`, `viz_studio/backend/rehearsal.py`, and the gates that
speak in cells. `GridCell` is named in 37 files, but most of those are callers
handing a cell along; the placement rule itself is one function.

## How it is proved

The point of the change is that an awkward run rehearses like any other, so
that is what the gate says, using the fixtures already written for the open
door — three positions at fractional offsets, at three different sizes, with
unimaged ground between them, and a second pair that overlap:

- the awkward run replays through the experimental door and reaches the screen;
- every position lands where its own description says, to within a voxel;
- where two positions overlap, the shared ground is not brightened — the later
  one is on top, and nothing is added;
- a gridded run replays exactly as it does today, unchanged;
- and the whole of `test_a_dataset_is_relived_as_a_live_run.py` still passes,
  since a real acquisition's road through this must not move.

The existing refusal gate — the one that expects an alert saying "grid" — is
the one gate that must *change*, and it should be rewritten to say what is now
true rather than deleted, so the day the limit lifted is on the record.

## What this is not

It is not a change to how a ZMART microscope images. Acquisitions go on being
laid out on a grid, because that is what a stage doing a survey does. What
changes is that the live path stops *requiring* it, so that data from anywhere
can be rehearsed through the same road a real experiment takes.
