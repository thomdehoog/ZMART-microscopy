# Placement by transform, not by pixels

Each position carries its own offset in its own description, and the viewer draws
it where that says. Nothing is rewritten, nothing is padded, and an offset can be
revised later by editing a few bytes of JSON.

Measured today, on ten positions of the benchmark ladder: ten stores, each pulled
back 16.64 µm — **51.2 voxels, a fractional voxel** — placed correctly on screen
with no pixel altered. The pointer map cannot express that offset at all.

## What is already true, and needs no work

- OME-Zarr `scale` and `translation` are read per store; `identity` too. The parser
  table is at `datasource/zarr/ome.js:155` and anything else throws at `:169`, so
  **no rotation or shear** from metadata.
- **A position records its stage position in the multiscale-level
  `coordinateTransformations`, and a correction written into the dataset transforms
  composes with it.** An earlier version of this document said the *engine* places
  sources a tile-width apart by index and that a translation adds on top of that.
  That was wrong: the placement was in the data all along, which is why offsets
  looked additive. Deleting or replacing that block strips every tile of where it
  belongs — see `PLAN_many_sources_with_transforms.md`.
- Translation is any finite float — fractional and negative both fine. Scale must
  be finite and **positive**, so no flips.
- One layer already holds many sources: `dataSources` is an array
  (`layer/index.d.ts:112`), and `scene.js:260` already sends the list.
- A group is *not* walked. The driver reads `multiscales` on the group's own
  attributes and resolves one volume per source URL
  (`datasource/zarr/frontend.js:491`). Ten stores means ten sources.

## Phase 0 — the measurement that decides the rest (gate)

**Nothing below is worth building until this number exists.** The linked picture
exists because neuroglancer builds a drawing layer per image. At ten sources the
cost was small; the ladder was built because *thousands* of positions were the
problem.

Run both arrangements over the same pixels at rungs 10, 50, 100, 200, 400:

- one picture, pointers — `held = 1`
- one layer, N sources with transforms — `held = N`

A script doing this at one rung was written while measuring and is **not in the
repository** — it lives in the session's scratchpad and should be brought in as
`viz_studio/measure_two_arrangements.py`. It needs the rung loop and, importantly,
**`lit` matched between the two**: today's run had 0.51 against 0.83, so part of
7.9 → 13.7 ms was simply more specimen on screen, not the arrangement. Zoom each
to the same lit fraction before timing.

**Decision rule, written before the numbers arrive:** if the drawing frame at 400
sources stays within ~20% of the picture's, adopt sources as the placement
mechanism and keep the picture only for runs above that. If it bends, keep the
picture as the default and treat transforms as an overlay for small runs — and
Phase 4 becomes the real answer.

### Result, measured 7 August 2026

Same pixels, same places, both arrangements, one browser. Positions served straight
out of the picture's own folder — nothing copied, nothing edited.

Drawing in software (headless), where `lit` did agree between the two and the rows
are therefore comparable:

```
positions   picture          sources         held
        5    8.7 ms          10.4 ms         1 / 5
       10    8.6 ms          12.7 ms         1 / 10
       50    8.9 ms          25.5 ms         1 / 50
      100    9.1 ms          41.4 ms         1 / 100
      200    9.4 ms          69.4 ms         1 / 200
      400   10.0 ms         121.1 ms         1 / 400
```

**The picture is flat and the sources are linear**: about `8.5 ms + 0.28 ms × N`,
fitted at 0.278 from 10→400 and 0.266 from 100→400. The gate says no: **placement
by transform cannot be the default mechanism.**

The decision is made on the *shape* — flat against linear — and not on the "within
twenty per cent" rule this document set out with. That rule is retired: it is a
threshold in milliseconds, and these milliseconds are software-drawn ones the same
document says overstate the cost about fiftyfold. A threshold cannot be applied to
numbers already declared untransportable. The shape argument needs no threshold and
is sufficient on its own.

Two cautions on the table above, both found by review after it was published.
`lit` agreed between the arrangements at every rung except 10, and that is why they
are quoted as comparable — but `lit` covers only the **centre half** of the canvas
and is blind to which pyramid level drew, so it is a weaker warrant than it looks.
And **the camera was not pinned**: the view is centred once from whichever source
resolves first, so two rows of a rung need not have been looking at quite the same
thing. The curve is very unlikely to change shape, but these rows should be
re-measured with `position` and `zoomFactor` set explicitly.

Two costs that hold whatever is drawn, and match on both machines:

```
opening     400 positions   0.25 s  ->  3.50 s      14x
requests    400 positions   67      ->  1744        4.3 per position
```

**The same ladder on the card (NVIDIA T400) does not settle the drawing frame, and
must not be quoted.** It reported 0.7 ms against 2.4 ms at four hundred — but `lit`
disagreed between the arrangements at nearly every rung and read **0.201** for 400
sources, so that row timed a mostly black panel. With 1744 requests and 3.5 s to
open, the fixed 2.5 s settle in `how_it_drew` is not enough for the stores to
arrive before sampling starts. What it does show is that software drawing overstated
the absolute cost by roughly fifty times: the *shape* transfers, the milliseconds
do not.

**Before this is re-run:** `how_it_drew` needs to settle until `lit` stops climbing
rather than waiting a fixed interval. Until then no threshold in positions can be
quoted for real hardware.

### What follows from it

- Transforms are an **overlay for small runs** — a detail scan of a dozen positions
  gets free, revisable, fractional-voxel placement at a cost nobody can feel.
- Surveys keep the linked picture, which is flat to four hundred positions and was
  built for exactly this.
- **Phase 4 is promoted** from optional to the only route that gets free placement
  *and* a flat curve.

## Phase 1 — placement written once, in the right slot

`parseOmeMultiscale` reads a `coordinateTransformations` at the **multiscale
level** and matrix-multiplies it with each dataset's. Tile placement belongs
there — one transform per image. Today's script wrote it into every resolution
level, which works and is the wrong slot.

- A writer in `zmart_storage` that records a placement on a store:
  `place(store, offset_um)`, writing the multiscale-level translation.
- It takes the offset a stitcher measured. It never touches pixels, and calling
  it twice replaces rather than accumulates.
- **The offset is a correction on top of nominal placement, not an absolute
  position** — measured today: a source lands a tile-width apart *plus* its own
  translation. Document that, because it is not what the name suggests.

Tests first, in the suite's style, driving the real page:

1. an offset written to a store reaches the engine and moves the picture;
2. a fractional offset survives — 51.2 voxels lands at 51.2, not 51;
3. offsets are independent — moving one position leaves the others where they were;
4. rewriting an offset replaces it, and no pixel changes (checksum the arrays).

## Phase 2 — the scale bar must notice sources that disagree

A per-tile **translation** is harmless. A per-tile **scale** is a claim about the
specimen: it says these voxels are a different size. Two sources at different
scales mean no single bar can describe the view — the fault fixed today, arriving
by a new route.

The guard added today (`LayerPanel.jsx`, `axesOnScreen` / `stretchedUnevenly`)
compares the *display stretch* only. It has no idea whether the sources disagree
with each other.

- Extend it to compare the scales the sources on screen declare.
- Same rule as today: warn when the axes on screen disagree, and stay quiet when
  they agree — an even difference is not a shear.
- Failing test first: two sources, different voxel size, warning appears; same
  voxel size, silent.

This phase is not optional if Phase 1 ships, and it should land in the same change.

## Phase 3 — affine, only if rotation is actually needed

OME-Zarr metadata cannot rotate. Neuroglancer's per-source
`LayerDataSource.transform` is a full matrix and can.

- `scene.js:260` would send `{url, transform}` instead of a bare URL string.
- Only worth doing if a real stitcher output carries rotation. Axis-aligned
  offsets cover drift, which is the case in hand.

Deferred until something asks for it.

## Phase 4 — upstream: a driver that walks a group

The one thing that would give both free placement **and** `held = 1`: a zarr
driver that, given a group, enumerates its child images and returns one multiscale
composed of them, each with its own `coordinateTransformations`.

Everything else exists — transforms are parsed, `dataSources` is an array,
`scene.js` sends a list. This is a well-scoped neuroglancer change, not a
redesign.

Only pursue if Phase 0 says `held = N` is unaffordable at the sizes that matter.

## What not to do

- **Do not rewrite pixels to place a tile.** The padding trick works and is what
  the pointer map requires, but it makes placement permanent and un-revisable.
  It is the fallback, not the design.
- **Do not remove the linked picture.** It is measured, it works, and above some
  number of positions it is likely still the right answer. Phase 0 decides where
  that line is.
- **Do not report a frame time without `lit` beside it.** Today's comparison shows
  why: the two arrangements drew different amounts of specimen and the raw ratio
  flattered nothing.

## Order

Phase 0 → decision → Phase 1 + 2 together → Phase 3/4 only on evidence.

Review before implementing: hand this to Codex first.
