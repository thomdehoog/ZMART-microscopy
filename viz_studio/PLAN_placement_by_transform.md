# Placement by transform, not by pixels

Each position carries its own offset in its own description, and the viewer draws
it where that says. Nothing is rewritten, nothing is padded, and an offset can be
revised later by editing a few bytes of JSON.

Measured today, on ten positions of the benchmark ladder: ten stores, each pulled
back 16.64 µm — **51.2 voxels, a fractional voxel** — placed correctly on screen
with no pixel altered. The pointer map cannot express that offset at all.

## What is already true, and needs no work

- OME-Zarr `scale` and `translation` are read per store; `identity` too. Anything
  else throws (`datasource/zarr/ome.js:155`), so **no rotation or shear** from
  metadata.
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

Deliverable: a table in the repo beside the other measurements, not a claim.

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
