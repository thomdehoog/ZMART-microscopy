# Findings: Step 8 target-tile placement

Working tree of `ZMART-microscopy_review`, branch
`claude/smart-operator-workflow-review-ehw3c5`, uncommitted change over
`44ffa257`. Findings only; no implementation was touched.

Evidence is an independent geometry oracle written for this review. It
represents every placed tile as its actual square frame rectangle, partitions
each target's requested footprint at every tile edge, and tests each resulting
cell. It never calls `coveredBy()` or `coveredByTiles()`, never reads
`tile.covers`, and never trusts `plan.uncovered`. A second oracle enumerates
minimum set covers exhaustively on an independently generated candidate grid.

## Verdict

**Correct for release on coverage, with declared optimisation limitations — but
the Step 9 accounting faults below must be fixed first.**

| Question | Answer |
| --- | --- |
| Can the planner claim coverage while leaving target ground outside the tile union? | **No.** 34 oracle cases agreed with `plan.uncovered` exactly. |
| Does enabling the margin change only the requested footprint? | **Yes** for geometry. It does change which path runs once a target passes one frame, but coverage holds on both sides of that threshold. |
| Is the tile count minimal? | **Yes** where the exact search runs. It is switched off entirely by **Max overlap** (F5) and bounded by a visit budget. |
| Is repeated acquisition minimised among minimum-count plans? | **No.** F4: a demonstrable 2-tile layout with zero overlap is unreachable. |
| Can Step 9 acquire every planned tile correctly? | **No.** F1 and F2. |

The regression in the three screenshots is fixed. The top-left-corner contract
is right at both call sites (`scan-areas.js:487-493`, `scan-areas.js:625-631`);
`bounds()` in `shared/scanfields.js:88` confirms a rectangle field is stored by
its top-left corner. Coverage was verified independently at margin off, 100 %
and 200 %, on stitched blocks, at negative coordinates, at stitching 0 / 20 /
90 %, under join, under every min/max lever and both conflict preferences, and
at 50 and 200 targets.

---

## F1 — One target spanning several tiles collapses to one acquired record (severity 1)

`scan-areas.js:506-513` gives every tile of a stitched block the same `id` and
`targetId`: `covers[0].target.id`.

`main.js:810-811` maps acquired tiles back to those ids, and `main.js:832-833`
and `847-849` build `acquiredLabels` with `Object.fromEntries`. Duplicate keys
collapse — only the last tile's `position_label` survives.

**Invariant violated:** 8 and 9 of the plan; "a target ID is not a unique tile
ID".

**Reproduction (measured):** one target at the origin, reach 70 um, margin
100 %, frame 128 um gives 9 tiles, all carrying `id` and `targetId` `"big"` —
9 tiles, 1 distinct id.

**Consequence:** the stage visits 9 positions and 9 pairs are recorded, but the
gallery can reach exactly one of them, `state.acquired` carries nine duplicate
entries, and `main.js:913` reports `9 pairs acquired` for one reachable pair.

**Why tests miss it:** the browser walk uses ordinary targets only, where each
tile happens to get a distinct `covers[0]`.

**Fix direction:** give every tile a unique key at birth
(`${targetId}#${tileIndex}`), key `acquiredLabels` and `state.acquired` by that
key, and derive target identity from `covers` where the gallery needs it.

**Regression test:** plan one oversized target and assert
`new Set(placed.map((t) => t.id)).size === placed.length`.

---

## F2 — Acquired frames are drawn and hit-tested at cell centres, not tile centres (severity 1)

The change correctly drives the stage to the tile (`main.js:816-822`), but two
consumers still resolve a position from the cell:

- `acquire_targets/layers.js:47-50` outlines the chosen and hovered frame at
  `c.x, c.y`.
- `main.js:1374-1377` (`targetAt`) hit-tests against `cell.x, cell.y`.

**Invariant violated:** 8 — planning, drawing and acquisition must describe the
same plan.

**Reproduction:** any shared tile. Three targets in a row at x = 0, 60, 120
(reach 5 um, margin off) plan a tile at x = 30 covering two of them. The stage
images at 30; the outline is drawn at 0 and at 60, and a press at 30 selects
nothing. It is worse for a stitched block, where all nine frames resolve to one
cell.

**Fix direction:** carry the tile through `state.acquired` (or a parallel
`acquiredTiles`) and use `tile.x`, `tile.y`, `tile.frameUm` in both places.

---

## F3 — "Join into one scan" is silently ignored when the stitching switch is off (severity 2)

`scan-areas.js:150`:

```js
if (overlap.join && overlap.min != null) return joinedPlan(...);
```

With **Join into one scan** ticked and **Stitching overlap** unticked,
`overlap.min` is `null`, the joined path never runs, and the operator gets a
scattered plan with no note saying why.

**Reproduction (measured):** four targets, margin 100 %, `join: true`. With
`overlap.min = 0.2` the plan is 16 contiguous tiles. With `overlap.min = null`
it is 3 scattered tiles and `notes` is empty.

**Invariant violated:** 6 of the control audit — each control has one traceable
effect, and no lever silently cancels another.

**Fix direction:** treat a missing stitching overlap as 0 % for the joined path,
or refuse and say so in `notes`. Better still, remove the lever (see the
recommendation below).

---

## F4 — Repeated ground is not minimised among equal-count plans (severity 3)

`candidateAreas()` seats each candidate at the **mean of the targets it holds**,
clamped to their common feasible rectangle (`scan-areas.js:583-596`). One seat
is generated per target subset. The equal-count tie-breaker in
`minimumComponentCover()` can therefore only choose the best *mean-seated*
plan; the minimum-overlap seat inside the feasible interval is never a
candidate.

**Counterexample (measured, exhaustive over 0.25 um seats):** targets at
x = 0, 60, 120, reach 5 um, margin off, frame 128 um.

- planner: tiles at x = 30 and x = 120, **4 864 um² acquired twice**
- true optimum at the same tile count: x = -59 and x = 69, **0 um² twice**

Both cover all three targets. The tile count is equal, so this is squarely the
secondary objective the prompt asks about.

**Why tests miss it:** the existing assertions check counts and coverage, never
union area.

**Fix direction:** once the cover is fixed, slide each tile inside its feasible
rectangle to minimise `repeatedOverlap` — a small local pass over an already
minimal cover, not a larger search.

**Regression test:** the three-in-a-row case above, asserting
`repeatedOverlap(placed) === 0`.

---

## F5 — "Max overlap" silently disables the minimum-tile search (severity 3)

`scan-areas.js:194-196`:

```js
const exact = overlap.max == null ? minimumAreaCover(...) : null;
```

Ticking **Max overlap** drops the whole plan to the order-dependent greedy
path. Nothing in the summary or `notes` says the guarantee changed; the step's
note still reads `N scan areas · M of M sampled covered`.

Related and smaller: `EXACT_COVER_VISITS = 250000` (`scan-areas.js:301`) can
return an unproven incumbent, and the `shallowest` memo does not prune
equal-depth revisits (`scan-areas.js:349-351`), so permutations of the same
selected set are re-expanded. Neither can lose coverage — the incumbent is
always a complete cover — but neither is surfaced.

**Fix direction:** drop the lever, or add a note when a bounded or greedy path
was used.

---

## F6 — Interactive stall at realistic target counts with the margin off (severity 3)

Measured on this machine, single-threaded, margin off, stitching 20 %:

| targets | tiles | planner time |
| --- | --- | --- |
| 100 | 88 | 16 ms |
| 200 | 105 | **3.3 s** |
| 300 | 139 | **10.2 s** |
| 400 | 146 | **55.7 s** |

With margin 100 % the same 200 targets plan in 22 ms — the larger footprints
break the candidate graph into small components. The blow-up is the exact
search on one large component, amplified by the equal-depth memo noted in F5.
It runs on the UI thread, so the page is frozen for the duration and the press
gives no progress.

**Fix direction:** cap component size and fall back to greedy above it, saying
so in `notes`; or fix the equal-depth memo and re-measure.

---

## F7 — "Min targets per tileset" is neither per tileset nor a planner rule (severity 4)

`main.js:1410` compares `p.objectsMin` against `state.restricted.size`, the
whole sample, and only appends a note. `planScanAreas()` never reads it.
**Min scan areas** (`scan-areas.js:264`) is likewise note-only.

---

## What passed

- **Coverage** — 34 independent oracle cases, all agreeing with
  `plan.uncovered`: margin off / 100 % / 200 %, exact one-frame fit and epsilon
  over it, 2 x 2 and 3 x 3 stitched blocks, two overlapping large targets,
  negative coordinates, duplicate positions, missing ellipse data, a zero-size
  target, stitching 0 / 20 / 90 %, join, and every min/max lever under both
  conflict preferences.
- **Invariant 4** — a chain of ordinary targets touching a large one through
  their margins does **not** stretch the stitched raster. Measured: a target at
  the origin with reach 140 um plus three small targets at x = 150, 220, 290
  gives the 3 x 3 block plus **one** extra tile at x = 255. The target at
  x = 150, incidentally inside the block, correctly receives no tile of its own.
- **Invariant 6 (minimum count)** — the planner matched the exhaustive oracle on
  every bounded case tried, including the greedy counterexample where four
  greedy tiles reduce to two.
- **Determinism** — four input-order permutations give one tile count; forward
  and reversed order give the same count at n = 50 and n = 200.
- **Empty-tile filtering** — dropping raster tiles that intersect no oversized
  footprint cannot open a hole, because the retained tiles still span every
  footprint. Confirmed by the oracle on all stitched cases.

## Recommendation on the controls

The review supports collapsing the box to four levers. Three of the seven
findings are levers that misbehave, and all three disappear on removal:

| keep | today |
| --- | --- |
| Max targets per tileset | `objectsMax` — the sampling ceiling; unchanged |
| Max tiles | `areasMax` — note that it is global today, not per tileset |
| Margin around a target (% of its size) | `margin` — unchanged |
| Tile overlap for big targets | `overlapMin` — the stitching overlap, which is already only used where one target needs several tiles |

| drop | why the review agrees |
| --- | --- |
| Max overlap | F5: it silently switches off the minimum-tile guarantee |
| Join into one scan | F3: silently ignored when the stitching switch is off |
| Min targets per tileset | F7: note-only, and not per tileset |
| Min scan areas | note-only, no planner effect |
| When both cannot hold | only exists to qualify Max tiles; covering every target and saying so is the sane single behaviour |

## Not covered by this review

The browser walk and the unit suite were not re-run: no code changed, and the
plan records them green at 411 passing and 15 skipped. Live Step 9 acquisition
was read, not executed — F1 and F2 are code-path findings, not bench
observations.
