# Operator interface and canvas stability review — 2026-09-04

## Outcome

The viewer remains a live, layered view. No overview mosaic is baked to hide
the problem.

Two independent causes made zooming look unstable:

1. Position pyramids were reduced with `[..., ::2, ::2]`. A coarser level kept
   one pixel out of every 2 × 2 block, so a level-of-detail change could remove
   a small feature or change the apparent channel balance.
2. The acquired picture followed the workflow canvas by reading the canvas view
   again from inside its view-change callback. That read could still be one
   frame behind. The engine image moved, while retained workflow layers were
   not repainted with the committed projection until an unrelated redraw.

Position stores are still completed at every level and atomically renamed into
the watched folder. That already prevents a reader from seeing a half-written
pyramid and remains the correct tile-loading boundary.

## Correction

- Every coarser position level now contains the mean of each adjacent 2 × 2
  block. The finest data is unchanged. Mean reduction preserves average signal
  and channel balance; it intentionally attenuates features smaller than a
  coarse pixel instead of selecting or discarding them arbitrarily.
- Resolved target acquisitions refresh affected coarse pixels from the prior
  resolved level on one global pixel lattice, including odd frame origins and
  overlaps.
- The acquired picture receives the committed view carried by the event.
- Retained canvas layers repaint after the viewer has committed the matching
  projection. Rapid wheel/drag events are coalesced into one repaint.
- Sidebar resize keeps the same carrier-local centre and zoom in both
  directions and then resynchronizes the picture beneath it.

Baking was rejected because it would duplicate live acquisitions, discard the
operator's independent acquisition/channel visibility, and require another
cache-invalidation path. The corrected multiscale position sources preserve
the original channels, finest pixels, acquisition identity, physical placement,
and live arrival behavior.

## Interface changes

- The canvas footer and permanent x/y readout are removed.
- Layer visibility, fade, and lock controls live in the **Canvas layers** white
  box under **Display settings**. **Fit** remains on the canvas.
- The sidebar handle has a 30 × 64 px hit area, visible focus/hover states,
  exact open/collapse labels, and `aria-expanded` state.
- The header is shorter, returning vertical space to the canvas.
- Step 7 uses the exact labels **Discovery method** and **Feature gating**.
- Workflow targets are green. Once a feature gate exists, contextual rejected
  targets disappear. Later steps show only the population still relevant to
  the workflow. Planned target tiles are blue; orange is reserved for genuinely
  uncovered targets.
- The predicted-Z legend is at the canvas top-right with larger text and numeric
  endpoints. Its physical colour domain is at least 100 µm and expands when the
  measured range is larger.

## Verification

- A real bridge/Smart Viewer evidence test crosses wide and close views three
  times, verifies acquisition visibility on every cycle, restores the exact
  centre and zoom, and requires fewer than 0.5% changed pixels in the returned
  composite.
- The complete real-bridge operator walk passed in 8.5 minutes with real object
  detection and Python UMAP, feature gating, target planning, live acquisition,
  explicit target selection, gallery comparison, and disconnect/reconnect.
- The full operator browser file passed all 35 scenarios (the first 34 together,
  followed by the corrected whole-run case), and the final whole-run evidence
  pass completed again with screenshot output enabled.
- The final unit runs passed 458 JavaScript tests (15 intentionally skipped)
  and 86 focused Python bridge, storage, and detection tests.
- Storage tests independently compare every coarse resolved pixel with the
  mean of the finest resolved image, including an odd-origin overlap.
- Sidebar tests begin at a non-default zoom and centre, then verify both
  collapse and reopen preserve them.
- Z-domain tests cover ranges below, exactly at, and above 100 µm, plus reversed
  endpoints.

## Screenshots

- [Before: footer present and target tiles green](evidence/2026-09-04-operator-interface/before-bottom-bar-green-target-tiles.png)
- [After: live canvas and compact interface](evidence/2026-09-04-operator-interface/after-live-canvas.png)
- [After: feature-gated targets and blue target tiles](evidence/2026-09-04-operator-interface/after-target-tiles.png)
