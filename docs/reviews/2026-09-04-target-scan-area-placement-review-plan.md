# Review plan: Step 8 target-tile placement

Companion prompt:
`docs/reviews/2026-09-04-target-scan-area-placement-review-prompt.md`

Review the current working tree in:

```text
C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_review
```

The review is findings-only. Do not modify the implementation while reviewing
it; proposed fixes and tests belong in the findings report.

## Outcome

Establish whether Step 8 reliably covers every selected target and requested
margin using the fewest practical fixed-size tiles, then minimizes pixels
acquired more than once. Confirm that stitching overlap is introduced only
where an individual target needs multiple tiles and that Step 9 acquires the
resulting tile plan faithfully.

The physical target-plus-margin footprint is a requirement, not an objective
to shrink.

## Invariants to audit

1. With sampling disabled, every gated/restricted target enters the planner.
2. A target that fits within one frame is contained whole, including margin,
   by at least one tile.
3. A target requiring multiple tiles is covered by their geometric union with
   no holes and the configured stitching overlap.
4. Ordinary targets do not enlarge a stitched raster merely because their
   margin footprints touch it.
5. A tile may cover several targets when their complete required footprints
   fit, avoiding redundant tiles.
6. The planner minimizes tile count before considering overlap.
7. Among equal-count plans, it minimizes actual multiply acquired ground, not
   a pairwise proxy that overcounts triple intersections.
8. Canvas geometry, summary counts, readiness state, and acquisition positions
   all describe the same plan.
9. `tile.covers` and target IDs are metadata, not proof of geometric coverage.
10. The output is deterministic for the same inputs and remains responsive at
    realistic target counts.

## Phase 1: establish the change and reproduce the evidence

1. Record `git status`, `git diff --stat`, and the diff from `44ffa257` for the
   relevant files.
2. Inspect the three original screenshots at full resolution:

   ```text
   C:\Users\t.de\Desktop\Screenshot 2026-09-04 154851.png
   C:\Users\t.de\Desktop\Screenshot 2026-09-04 154701.png
   C:\Users\t.de\Desktop\Screenshot 2026-09-04 154804.png
   ```

3. Reproduce the same Step 8 plan with margin disabled, 100%, and 200%, always
   pressing **Run again** after changing the setting.
4. Record for each run: selected target IDs and geometry, frame size, tile
   centres, tile count, configured overlap, reported uncovered IDs, summary
   text, and a canvas screenshot.
5. Confirm the development page is serving the current working tree before
   drawing conclusions from the visual result.

Exit criterion: the old failure is reproducible from evidence, or the current
fix visibly covers those same targets and the before/after difference is
captured.

## Phase 2: trace coordinate and unit contracts

Trace this path without skipping conversions:

```text
state.restricted
  -> object features and physical area
  -> objectReachUm / reachUm
  -> planScanAreas
  -> candidateAreas or stitchedBlocks
  -> shared scanfields.tiles
  -> state.targetTiles
  -> canvas frame rectangles
  -> Step 9 stage positions
```

Check:

- pixels versus micrometres;
- radius/reach versus diameter;
- fraction versus percentage;
- rectangle top-left versus rectangle centre;
- carrier coordinates versus stage coordinates;
- inclusive boundary and floating-point tolerances; and
- whether omitted, `null`, zero, and negative margin values have distinct and
  intended meanings.

Exit criterion: every coordinate and unit contract is stated explicitly, with
file and line references, and the corrected top-left call is verified at both
stitched call sites.

## Phase 3: use an independent geometry oracle

Build a small test-only oracle independent of planner metadata. Represent every
placed tile as its actual square frame rectangle. Partition each requested
target footprint at tile x/y edges and verify every resulting cell is covered
by at least one rectangle.

The oracle must not call `coveredBy()`, call `coveredByTiles()`, consume
`tile.covers`, or trust `plan.uncovered`.

Run it against:

- one ordinary target at margin off, 100%, and 200%;
- exact one-frame fit and epsilon over the threshold;
- a large target at the origin and at non-zero/negative coordinates;
- a target requiring a 2 x 2 block and one requiring more rows than columns;
- two overlapping large targets;
- a large target touching a chain of ordinary targets through margins;
- disconnected clusters plus isolated outliers matching the screenshots;
- different target pixel sizes and missing ellipse data; and
- overlap values 0%, 20%, and 90%.

Exit criterion: every target reported covered passes the independent oracle;
every intentionally limited target reported uncovered fails it.

## Phase 4: verify minimum tile count

For small inputs, enumerate all meaningful candidate tile centres independently
and solve the minimum set cover exhaustively. Compare that result with
`planScanAreas()`.

Include:

- the existing greedy counterexample where four greedy tiles can be replaced
  by three;
- several close ordinary targets that fit in one shared tile;
- a small target already covered by a large target's stitched block;
- overlapping large targets, comparing a shared lattice with separate
  per-target lattices;
- input-order permutations; and
- enabled maximum-area and maximum-overlap restrictions under both conflict
  preferences.

Audit the effect of `EXACT_COVER_VISITS`: determine when the search can return
an unproven incumbent and whether the product claims that result is minimal.

Exit criterion: either the planner matches the independent optimum for the
bounded suite, or every mismatch becomes a severity-ranked finding with a
minimal counterexample.

## Phase 5: verify the overlap objective

For all equal-minimum-count layouts in small cases, compute:

```text
sum(area of every tile) - area(union of all tiles)
```

Confirm the chosen plan has the smallest value. Include two-way and three-way
intersections so pairwise overlap cannot masquerade as the correct measure.

Separately verify stitching semantics:

- ordinary independent tiles are not moved merely to satisfy stitching
  overlap;
- tiles covering one oversized target use the configured pitch;
- ordinary margin-touching targets do not extend the stitched raster;
- sharing between oversized targets preserves complete stitchable coverage
  for each; and
- no tiles are added solely to bridge unrelated target ground unless **Join
  into one scan** is explicitly enabled.

Exit criterion: tile count is the primary objective, and actual repeated ground
is the demonstrated secondary objective.

## Phase 6: verify controls and conflict behavior

Exercise every switch independently and in relevant combinations:

- maximum targets per tileset;
- target margin;
- stitching overlap;
- maximum overlap;
- minimum targets per tileset;
- minimum and maximum scan areas;
- join into one scan; and
- conflict preference.

Confirm unchecked controls contribute `null`/disabled behavior, not their
visible resting values. Confirm collapsing **More settings** changes no rule.
After any change, ensure the old plan and summary disappear until **Run again**
is pressed.

Exit criterion: each control has one traceable planner effect and no hidden
default restriction.

## Phase 7: verify display and Step 9 acquisition

1. Compare the green rectangles drawn by the Target tiles layer with the exact
   `state.targetTiles` centres and frame sizes.
2. Confirm a red restricted target outside their union can never coexist with
   a full-coverage summary.
3. Confirm the summary recomputes covered count from verified geometry.
4. For Step 9, record every stage destination and prove it matches one planned
   tile centre exactly once.
5. Include one target requiring several tiles and one tile shared by several
   targets. Verify target IDs do not collapse distinct captures or duplicate
   gallery/accounting records incorrectly.
6. Interrupt and resume acquisition; ensure the acquired count and ground
   windows represent actual captured tiles.

Exit criterion: planning, drawing, summary, acquisition, and acquired-image
accounting agree tile for tile.

## Phase 8: performance and determinism

Measure planner time and output stability for representative sets of about 50
and 200 targets at margin off, 100%, and 200%. Repeat each input and permute its
order.

Record candidate count, exact-search visits or fallback use, tile count, and
elapsed time. Flag visible UI stalls, order-dependent counts, or a fallback
that silently weakens the minimum guarantee.

Exit criterion: practical latency is documented and repeated equivalent inputs
produce equivalent geometry and tile count.

## Validation commands

From `application`, with the configured `zmart-microscopy` environment:

```text
npx vitest run
npx playwright test framework/operator-page.spec.js -g "one walk of the whole run"
```

Do not run `npx playwright install`. Do not run the bridge-backed live spec
while the operator window's bridge is open. Do not edit page code while a
browser walk is running because Vite reload resets the run.

Current pre-review baseline: 411 unit tests pass, 15 are skipped, and the full
nine-step browser walk passes.

## Findings report

Write findings in severity order. Each finding must include:

- file and line;
- violated invariant;
- smallest concrete reproduction;
- observed and expected tile geometry/count;
- why existing tests miss it;
- smallest credible fix direction; and
- a focused regression test.

Finish with one of these verdicts:

- **Correct for release**;
- **Correct with bounded/declared optimization limitations**; or
- **Not correct for release**.

State separately whether coverage, minimum tile count, overlap minimization,
interactive efficiency, and Step 9 fidelity each passed.
