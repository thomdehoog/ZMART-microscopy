# Implementation plan: Step 8 down to four controls

Companion documents:

- findings — `docs/reviews/2026-09-04-target-scan-area-placement-review-findings.md`
- review prompt — `docs/reviews/2026-09-04-target-scan-area-placement-review-prompt.md`

Branch `claude/smart-operator-workflow-review-ehw3c5`, over the uncommitted
placement fix that the review cleared for coverage.

## What Step 8 becomes

Four controls, all in the main box. **More settings** goes away entirely.

| control | rule | today |
| --- | --- | --- |
| Max targets per overview tileset | systematic random sample of the gated targets, drawn per overview tileset | `objectsMax` — unchanged behaviour, clearer name |
| Max target tiles per overview tileset | ceiling on placed tiles, counted per overview tileset | `areasMax`, which is global today |
| Margin around a target (% of its size) | the ring each target must be imaged with | `margin` — unchanged |
| Tile overlap for big targets | the stitching overlap, used only where one target needs several tiles | `overlapMin` — unchanged behaviour, clearer name |

Deleted: **Max overlap**, **Min targets per tileset**, **Min scan areas**,
**Join into one scan**, **When both cannot hold**.

Two behaviours become fixed rules rather than levers:

1. **A stitched block is all or nothing.** If a big target's raster does not
   fit whole inside the tileset's remaining budget, no part of it is placed and
   the target is reported uncovered. A block clipped halfway would image a
   target with holes in it while looking acquired.
2. **When the budget runs out, coverage loses and says so.** Place the tiles
   that cover the most targets, then report how many targets went uncovered.
   This replaces the "When both cannot hold" choice.

## Why these five levers go

Each is a review finding, not a preference.

- **Max overlap** (F5) silently switches `planScanAreas()` off its exact
  minimum-tile search onto the order-dependent greedy path, with nothing in the
  summary saying the guarantee changed.
- **Join into one scan** (F3) is silently ignored whenever the stitching switch
  is off, because of `if (overlap.join && overlap.min != null)` at
  `scan-areas.js:150`.
- **Min targets per tileset** (F7) is note-only, and is compared against the
  whole sample rather than per tileset.
- **Min scan areas** is note-only.
- **When both cannot hold** exists only to qualify the tile ceiling.

Deleting Max overlap also deletes the only path that could return a non-minimal
tile count, so the minimum-tile guarantee becomes unconditional.

## Phases

Failing tests first in every phase; the suite runs green before the next one
starts.

### Phase 1 — Step 9 accounting (blocking, independent of the controls)

These two are release blockers on their own and do not depend on the control
rework. Land them first so the rest can be reviewed on a sound base.

**F1 — a tile is not a target.** Every tile of a stitched block currently
carries `id`/`targetId` = `covers[0].target.id`
(`scan-areas.js:506-513`), and `main.js:832-833`/`847-849` build
`acquiredLabels` with `Object.fromEntries`, so nine records collapse to one
reachable picture.

- give every tile a unique `key` at birth: `` `${targetId}#${tileIndex}` ``, in
  `stitchedBlocks()`, `joinedPlan()`'s replacement, and `candidateAreas()`
  (ordinary tiles get `#0`);
- key `state.acquired` and `state.acquiredLabels` by `key`, not by target id;
- the gallery derives target identity from `tile.covers` where it needs it.

Test: plan one target of reach 70 µm at margin 100 % in a 128 µm frame, assert
`new Set(placed.map((t) => t.key)).size === placed.length` (9 in, 9 out).

**F2 — acquired frames drawn at the wrong place.** The stage drives to tile
centres (`main.js:816-822`), but `acquire_targets/layers.js:47-50` outlines at
`c.x, c.y` and `main.js:1374-1377` hit-tests against `cell.x, cell.y`.

- carry the placed tile through acquisition as `state.acquiredTiles`;
- draw and hit-test from `tile.x`, `tile.y`, `tile.frameUm`.

Test: three targets at x = 0, 60, 120, reach 5 µm, margin off, planning one
shared tile at x = 30. A press at x = 30 selects that tile; a press at x = 0
does not select a frame that was never taken there.

### Phase 2 — delete the five levers

- `step.js`: remove the whole `configuration` fold (`More settings`, its title,
  fold button, body and `showConfiguration`), and the five controls inside it.
  **Tile overlap for big targets** moves up into the main box.
- `scan-areas.js`: delete `joinedPlan()` and the `overlap.join` branch at
  `:150`; delete the `overlap.max` parameter, `overlapsPastMaximum()`, the
  `refused` term in the greedy loop, and the `overlap.max == null` gate at
  `:194` so `minimumAreaCover()` always runs; delete the `areas.min` note at
  `:264` and the `prefer` parameter with every branch that reads it.
- `main.js`: drop `objectsMin`, `areasMin`, `overlapMax`, `join` and `prefer`
  from both `placing` literals (`:288`, `:417`) and from `placeTheScanAreas()`
  (`:1404-1409`); delete the `objectsMin` note at `:1410`.
- `scan-areas.test.js` and `operator-page.spec.js`: delete the cases that only
  exercise the removed levers; keep every coverage and minimum-count case.

Back-compat is not required — a saved run carrying the old keys simply ignores
them.

### Phase 3 — the tile ceiling becomes per overview tileset

`planScanAreas()` stays pure and tileset-unaware. The grouping belongs to the
page, which already owns it.

In `placeTheScanAreas()` (`main.js:1401`):

- group `state.restricted` by `tilesetOfField(cell.field)` — the same function
  the sampling ceiling already uses (`main.js:1275`);
- call `planScanAreas()` once per tileset with
  `areas: { max: p.tilesMax }`;
- concatenate `placed`, `uncovered` and `leftOut`; merge `notes`, collapsing
  identical sentences into one with a count.

Two consequences to state in the code, not discover later:

- targets in **different** tilesets that sit near a shared border no longer
  share a tile. That is the price of a per-tileset budget and it is the right
  one: a tileset's plan should not change because of what is next to it.
- planning per tileset also breaks the candidate graph into smaller components.
  This is the direct remedy for **F6** (200 targets, margin off, measured at
  3.3 s on the UI thread; 300 at 10.2 s; 400 at 55.7 s). Re-measure after this
  phase before deciding whether F6 needs anything further.

Then make the two fixed rules real, in `planScanAreas()`:

- **all-or-nothing blocks** — the existing `fitsMaximum(block.length)` check at
  `:172-176` already refuses a block that does not fit and reports its targets
  uncovered. Keep it, and make it unconditional now that `prefer` is gone.
- **budget exhaustion** — the greedy loop at `:203-231` already stops at the
  ceiling and reports the rest uncovered. With `prefer` gone this becomes the
  only behaviour. The exact search must still be capped by the remaining
  budget: keep the `slots` comparison at `:198-201` and drop its `prefer` term.

Note wording, one sentence: `stopped at N target tiles: M targets are not
covered`.

### Phase 4 — the summary and the step note

`step.js`'s summary rows stay as they are; the labels follow the new names.
`main.js:909` becomes per-tileset aware only in its wording — the count is
still the verified `plan.uncovered`, which the review confirmed is derived from
real geometry.

### Phase 5 — F4, minimum repeated ground (optional, do last)

`candidateAreas()` seats each candidate at the mean of the targets it holds
(`scan-areas.js:583-596`), so the minimum-overlap seat is never a candidate.
Measured: targets at x = 0, 60, 120 plan tiles at 30 and 120 with **4 864 µm²
imaged twice**, where tiles at −59 and 69 cover the same three with **zero**.

The fix is small and local: after the cover is fixed, slide each chosen tile
inside its own feasible rectangle to minimise `repeatedOverlap`. It changes no
coverage and no tile count, so it can land on its own.

Test: the three-in-a-row case, asserting `repeatedOverlap(placed) === 0`.

## Guard rails

The independent geometry oracle from the review is the acceptance gate for
every phase, not the planner's own bookkeeping. It must keep agreeing with
`plan.uncovered` across margin off / 100 % / 200 %, stitched blocks, negative
coordinates, overlapping large targets, stitching 0 / 20 / 90 %, duplicate
positions, missing ellipse data, and input-order permutations. Fold it into
`scan-areas.test.js` as a test-only helper so it stops being a scratch script.

## Validation

From `application`, in the `zmart-microscopy` environment:

```text
npx vitest run
npx playwright test framework/operator-page.spec.js -g "one walk of the whole run"
```

Baseline before this work: 411 passing, 15 skipped, and the nine-step walk
green. Targeted vitest runs per phase; the full suite and the browser walk once,
at the end.

Do not run `npx playwright install`. Do not edit page code while a walk is
running — Vite reload resets the run.
