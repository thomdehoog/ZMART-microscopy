# A position has a place; a grid is one way of choosing places

Written 21 August 2026, at the end of the evening the load window was reworked,
as a plan. **Built the same night**, so what follows now describes the code
rather than proposing it -- except the last section, on counting, which is
still a decision waiting to be made.

## What was wrong, in one sentence

A run written through the live path was **a profile and a set of grid cells**, so
a position's place was worked out as `cell × step` rather than recorded — and a
dataset whose positions did not sit on a regular grid could not be written, or
replayed, at all. It can now: a position carries its place, and the grid is one
way of choosing one.

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

## The one hard part, found while starting the work

Placing a position anywhere is straightforward, and the picture then comes out
right. **Analysis ownership is not**, and the existing code says so in its own
refusal message:

> Treating those missing cells as outer boundaries would make diagonal
> neighbours own the same specimen twice. … this **box-shaped ownership format
> cannot represent it safely**.

That is the real limit, and it is worth stating precisely because it is easy to
mistake for a bug. `analysis_core_roi` is a **box**: a low and a high along each
axis. On a complete grid, a box can always express "my half of the strip I share
with each neighbour", because every neighbour is squarely along one axis. In an
arbitrary arrangement a position can share ground with another that is offset in
*both* axes at once, and the part it should own is then an L-shape or worse —
which no box can describe. Widening the box double-counts the corner; narrowing
it drops specimen nobody counts.

So the change splits cleanly in two, and only the first is needed for a replay
to work:

**The picture.** A position is placed where its own description says. This is
sound for any arrangement, needs no ownership question answered, and is what
makes an awkward run rehearse.

**The counting.** For a complete grid, exactly as today. For anything else, a
box cannot always be right, and there are three honest answers:

1. **Say the whole frame counts, and say so out loud** — every position owns
   everything it recorded, and analysis over an awkward run may count an object
   in an overlap twice. Simple, truthful, and wrong for anybody counting cells.
2. **Refuse the counting, not the run** — the run replays and draws, and asks
   for analysis boundaries answer that this arrangement has none. Nothing is
   quietly wrong; a caller that needs them finds out.
3. **Stop using a box** — ownership becomes a region that can describe an
   L-shape. Correct in general, and much the largest of the three: every reader
   of `analysis_core_roi` changes with it.

**This is the decision to make before building.** (2) is the smallest thing that
is not a lie, and it keeps (3) open. (1) should not be chosen by default,
because it is the one that produces wrong numbers with nothing on screen to say
so — which is the fault this whole repository is most careful about.

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
