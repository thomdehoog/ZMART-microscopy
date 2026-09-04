# Operator session change ledger — 2026-09-04

This ledger records the implementation accumulated over the operator review
session above commit `44ffa257`.

## Detection and discovery

- Object detection reports field work, classical feature extraction, and the
  population UMAP as phases of one operation.
- UMAP is calculated in Python before object detection completes. Step 7 opens
  with its real `umap_1`/`umap_2` axes immediately; the delayed browser-side
  embedding request and its fallback behavior were removed.
- Step 7 wording is **Discovery method** / **Feature gating**.
- Candidate/selected/later-step populations no longer remain as competing
  blue, red, and green point clouds.

## Target-tile planning

- Step 8 exposes four operator controls: max targets per overview tileset, max
  target tiles per overview tileset, margin around a target, and overlap for
  big targets.
- Coverage uses each target's physical footprint plus its requested margin.
- Ordinary targets share tiles where that reduces tile count. Oversized targets
  use complete stitched rasters. A budget never clips a stitched raster.
- Small ambiguous budgets are searched exactly; dense fields take a bounded,
  deterministic best-coverage path and say so instead of blocking the UI.
  Both paths evaluate the physical union, including a target completed jointly
  by adjacent tiles, before minimizing tile count and repeated acquired ground.
- Each planned tile records which targets its acquisition prefix completes, so
  a jointly covered or stitched target is credited only after all required
  preceding frames have arrived.
- The summary reports planned tiles, gated targets, covered targets, and any
  important exclusions.

## Acquisition and inspection

- Overlapping target frames are presented to the Viewer as one resolved source
  per channel, preventing additive overlap from changing colour or brightness.
  Each raw frame remains separately retained for provenance and gallery use.
- Re-selecting a target rewrites only the chosen frame into the resolved mosaic.
  Automatic gallery following no longer performs redundant rewrites; explicit
  rewrites are serialized and retry only transient Windows sharing violations.
- Step 9 accounts for physical tile keys, so every tile of a stitched target is
  reachable in the gallery.
- Stage drives, hit testing, outline, overview crop, and high-resolution image
  all use the acquired tile centre and frame.
- Low- and high-resolution images are stacked vertically with the same physical
  crop and target display settings. The old RGB-composite fallback and target
  circle were removed.
- Approval/refusal controls and the instruction strip were removed.
- Completed target acquisition offers **Rerun current** below the selected pair
  and **Rerun all** beside it; rerunning one retains the other acquisitions.

## Canvas and operator layout

- See [the canvas stability review](2026-09-04-operator-interface-canvas-review.md)
  for the zoom/LOD root cause, rendering correction, no-bake decision, display
  settings move, sidebar behavior, target palette, Z scale, and evidence.

## Independent placement review

- The final independent review found no release blocker in the planner.
- Its augmented counterexample, joint-coverage case, and dense performance
  probes passed; the focused placement suite passed 75 of 75 tests.
- The dense-budget path is intentionally bounded and reports that fact instead
  of claiming exhaustive optimality.
