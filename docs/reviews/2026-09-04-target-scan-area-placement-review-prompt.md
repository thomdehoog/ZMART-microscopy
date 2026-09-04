# Opus 5 review prompt: Step 8 target-tile placement

Review the current **working tree**, not only `HEAD`, in:

```text
C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_review
```

The branch is `claude/smart-operator-workflow-review-ehw3c5`; its last committed
head before this work is `44ffa257`. The relevant implementation is currently
uncommitted. Do not change code during this review. Produce findings first.

## Review objective

Review the tile-placement algorithm used by Step 8, **Target scan area**, for:

1. correctness;
2. completeness and edge-case handling;
3. minimum number of tiles placed;
4. minimum overlap/reacquisition of the same pixels among plans using that
   minimum number of tiles; and
5. practical interactive efficiency.

Do not reward architectural novelty. Prefer the smallest correct design and
call out needless machinery. Conversely, do not accept a simple heuristic if
it can silently miss a target, violate its margin, or use avoidable tiles.

## Regression background: margin-enabled placement

The implementation under review is intended to fix a release-blocking defect.
Before the current fix, the control case worked when **Margin around a target
(% of its size)** was switched off, while enabling the margin visibly failed.

Inspect these screenshots at original resolution:

```text
C:\Users\t.de\Desktop\Screenshot 2026-09-04 154851.png
C:\Users\t.de\Desktop\Screenshot 2026-09-04 154701.png
C:\Users\t.de\Desktop\Screenshot 2026-09-04 154804.png
```

What they show:

- `154851` is the useful control: with margin disabled, the restricted target
  shapes lie within the green 128 x 128 um target tiles and placement looks
  plausible.
- With margin enabled (100%, and worse at 200%), restricted target shapes are
  still visibly red because they lie completely outside the green tile union.
  Shapes under a translucent green tile appear brown; therefore the isolated
  red shapes are not merely a colour-key misunderstanding.
- The dense central cluster receives many strongly overlapping tiles even
  while isolated restricted targets receive none.
- The UI has reported all gated targets covered in this state. Thus summary
  bookkeeping can disagree with the geometry drawn on the canvas.
- Increasing the margin can nearly double the tile count while still producing
  the uncovered red targets. More tiles are not buying correct coverage.

The root cause identified by the current change was a coordinate-contract
error: the shared Step 3 tiler represents rectangles by their top-left corner,
but Step 8 supplied the rectangle centre as `x` and `y`. The raster therefore
moved by half its width and height. Optimistic target IDs then hid that geometry
error from the summary.

The current working tree claims to fix this by:

- passing the expanded footprint's top-left corner to the shared tiler;
- allowing only targets that individually exceed one frame to enlarge a
  stitched raster, rather than pulling in a chain of ordinary margin-touching
  targets;
- verifying coverage from the union of the actual frame rectangles;
- retaining an exact minimum-cover search for ordinary targets, with a bounded
  fallback for large combinatorial components; and
- measuring actual multiply acquired ground when breaking ties between plans
  with the same tile count.

Review those claims; do not assume the diagnosis or fix is complete. The three
screenshots are regression evidence. The operator had explicitly pressed **Run
again**, so stale HMR state is not an adequate explanation.

## Required semantics

- The acquisition frame in this reproduction is 128 x 128 um.
- Every restricted target is an input unless the **Max targets per tileset**
  sampling switch is explicitly enabled.
- The target's base reach is half its fitted ellipse major axis, converted to
  micrometres using that target's pixel size. The implementation currently
  uses a conservative axis-aligned footprint from that reach.
- A 100% margin adds one base reach around the target; a 200% margin adds two.
- When the expanded target fits in one frame, one selected frame must contain
  the entire expanded footprint.
- When one target cannot fit in one frame, several frames may cover that one
  target. Their **union** must contain its entire expanded footprint without
  holes, and adjacent tiles in that target's tileset must use the configured
  stitching overlap.
- The configured stitching overlap is **not a global spacing rule**. It is
  introduced only because an individual target needs more than one tile.
  Ordinary targets must not extend a stitched raster merely because their
  expanded margins touch it.
- If two targets each individually require multiple tiles and their required
  footprints overlap, sharing a lattice or tiles is allowed only when each
  target independently retains complete, stitchable coverage and sharing
  reduces the final tile count. No overlap should be imposed over unrelated
  ground simply to connect separate targets.
- One tile may still serve several targets when it contains every one of their
  required footprints. That is ordinary tile sharing, not a stitched tileset.
- Coverage and per-target stitching are hard requirements. Subject to them,
  minimize the number of tiles globally. Only then minimize incidental overlap
  and repeatedly acquired pixels.
- **Do not minimize the physical target scan area.** The targets and their
  requested margins define the ground that must be acquired; none of that
  ground may be discarded or contracted to improve an optimization score.
  "Minimize" applies to the number of fixed-size tiles placed and, secondarily,
  to overlap between those tiles—not to the required target-plus-margin area.
- Collapsing **More settings** must not activate hidden restrictions.
- The scan-area summary must be derived from independently verified geometry,
  not from optimistic IDs attached while candidates are generated.

## Code that needs close inspection

Start with:

```text
application/workflows/target_acquisition/steps/target_scan_area/scan-areas.js
application/workflows/target_acquisition/steps/target_scan_area/scan-areas.test.js
application/workflows/target_acquisition/steps/target_scan_area/step.js
application/framework/window/main.js
application/workflows/target_acquisition/steps/acquire_targets/layers.js
application/workflows/target_acquisition/steps/discover_targets/layers.js
application/framework/operator-page.spec.js
```

Trace the full data path from `state.restricted`, target size and `p.margin`,
through `planScanAreas()`, into `state.targetTiles`, the canvas frames, and the
summary.

In particular, challenge these boundaries rather than trusting the passing
tests:

- Confirm the corrected `type: "rectangle"` fields really pass top-left `x/y`
  everywhere, including `stitchedBlocks()` and `joinedPlan()`. Look for another
  centre-versus-corner conversion in the full data path.
- `coveredBy()` requires containment in one tile for ordinary targets, while
  `coveredByTiles()` verifies union coverage for stitched targets. Verify both
  use exactly the same target reach and margin units.
- `stitchedBlocks()` now builds connectivity from oversized targets only.
  Confirm an ordinary target cannot enlarge that raster, while an ordinary
  target already covered by its tiles does not receive a redundant tile.
- Connected oversized targets may share a raster. Prove that this never uses
  more tiles than separate minimum per-target rasters, never leaves a footprint
  uncovered, and never creates stitching overlap solely to bridge unrelated
  target ground.
- A stitched tile's `covers` list uses an intersection predicate. The summary
  is now intended to use `coveredByTiles()` instead; verify no other readiness,
  acquisition, or UI path still mistakes `covers` metadata for proof.
- Empty raster tiles are filtered using intersection metadata. Verify removing
  them cannot create a hole in any expanded target footprint.
- The minimum-cover search applies only to the ordinary-target path. Verify
  that crossing the one-frame margin threshold does not cause an avoidable
  discontinuity or send a common real dataset into a non-minimal path.
- `EXACT_COVER_VISITS` can stop the claimed minimum-cover search and return its
  incumbent. Check whether the UI or tests incorrectly present that bounded
  result as a proven global minimum.
- The equal-count tie-breaker now computes total frame area minus rectangle
  union area. Verify that this is the intended amount of ground acquired more
  than once, including triple intersections, and that the branch ordering
  cannot prevent the best equal-count result from being considered.

The screenshots are authoritative evidence that the present assertions are
not sufficient. A test that merely checks `tile.covers`, `plan.uncovered`, or
the summary repeats the bookkeeping under review and cannot prove coverage.

## Required independent checks

Add proposed regression cases to the findings. At minimum, independently
calculate the union of the actual square frame rectangles and verify that it
contains each target's full expanded footprint. The oracle must not call the
planner's `coveredBy`, consume `tile.covers`, or trust `uncovered`.

Cover at least:

- the same target set at margin off, 100%, and 200%;
- a target that fits exactly in one frame and one just over the threshold;
- one very large target requiring a 2D stitched block;
- two overlapping large targets, comparing a shared raster with separate
  minimum per-target rasters and independently proving both coverages;
- a large target touching a chain of small targets only through their margins,
  proving that contact alone does not stretch the large target's stitched
  raster; also verify that small targets already covered incidentally do not
  receive redundant tiles;
- several close ordinary targets where one frame can contain all margins;
- disconnected clusters and isolated outliers like the screenshots;
- duplicate positions, boundary touching, negative coordinates, and input
  order permutations;
- missing ellipse size and differing per-target pixel sizes;
- stitching overlaps of 0%, a normal value such as 20%, and the safe upper
  bound;
- sampling disabled, ensuring every restricted/gated target is planned;
- every optional min/max area and overlap rule, under both conflict
  preferences;
- deterministic output and acceptable latency for roughly 50 and 200 targets.

For minimum tile count, use a small independent exhaustive oracle on bounded
synthetic cases and compare the planner against it. Include cases where greedy
set cover is suboptimal. For equal minimum-count solutions, compare the actual
area imaged more than once; do not treat a smaller required coverage region as
an acceptable way to reduce overlap. For stitched regions, state precisely
what lattice constraints make a claimed count minimal; do not equate "uses
Step 3's raster" with a proof of minimality.

Also verify that the actual acquisition visits the planned tile centres once
per tile, especially when one target spans several tiles. A target ID is not a
unique tile ID.

## Existing commands

From `application`, using the repository's configured environment:

```text
npx vitest run
npx playwright test framework/operator-page.spec.js -g "one walk of the whole run"
```

At the time this prompt was written, the current working tree passed 411 unit
tests (15 skipped) and the complete nine-step browser walk. Passing those tests
is context, not proof that the screenshot regression is fixed.

Do not run `npx playwright install`. Do not run the bridge-backed live spec
while the operator window's bridge is open.

## Deliverable

Return findings ordered by severity. For each finding provide:

- exact file and line references;
- the violated invariant;
- a concrete reproduction or counterexample;
- whether current tests would miss it and why;
- the smallest credible fix direction; and
- a focused regression test that would fail before that fix.

End with a short verdict answering these questions explicitly:

1. Can the current planner ever claim coverage while leaving expanded target
   ground outside the union of placed tiles?
2. Does enabling the margin change only the requested footprint, or does it
   accidentally change which optimization path and guarantees apply?
3. Is the returned tile count genuinely minimal under the enabled rules?
4. Is repeated pixel acquisition correctly minimized among minimum-count
   plans?
5. Can Step 9 acquire every planned tile correctly, including multiple tiles
   belonging to one target?
