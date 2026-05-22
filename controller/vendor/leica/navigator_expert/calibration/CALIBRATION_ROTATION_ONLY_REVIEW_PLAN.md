# Calibration PR 7: Rotation-Only Image-to-Stage Review

## Status

Design locked. Awaits implementer handoff. Builds on PR 6 (D4 diagnostic grid + PNG outputs).

## Background

PR 6 added a D4 candidate grid that renders all 8 D4 elements (4 rotations + 4 reflections) as separate axes. On the first real rig run the operator
view felt cluttered: 16 panels for a decision that only needs to highlight one orientation. The right fix is not a layout tweak. The right fix is to
commit to the rig's actual optical assumption (reflection-free) and remove the reflection candidates from the operator view entirely, with an
explicit guard against silently accepting a reflected calibration.

The math, the registration, the promotion semantics, and the report schema do not change. Only:

1. Which D4 candidates the operator sees in the diagnostic.
2. How those candidates are visually grouped (one tile per candidate, not two separate axes).
3. What happens if the best-fitting candidate is a reflection (rejected with explicit reason, no silent coercion).

## Design

### Operator view (Step 2)

Step 2 displays exactly two things, in this order:

1. A 1x4 grouped D4 candidate grid showing only the 4 rotation candidates:

   - `+X +Y` (identity)
   - `-Y +X` (90 CCW)
   - `-X -Y` (180)
   - `+Y -X` (90 CW)

2. The existing text summary block (verdict + per-registration lines).

Each candidate tile is a single visual unit, not two separate axes:

- Tile title: the candidate label, e.g. `-Y +X`.
- Tile subtitle: residual line, e.g. `+X 0.7 um / +Y 1.2 um`.
- Top mini-panel inside the tile: corrected `+X` stage-move overlay.
- Bottom mini-panel inside the tile: corrected `+Y` stage-move overlay.
- Winner highlight: one lime border around the whole tile (not two borders around two axes).

Figure suptitle on the accepted-rotation-winner path:

    Winner: -Y +X (rotation)    +X residual = 0.7 um    +Y residual = 1.2 um

Figure suptitle on the rejected / no-winner paths:

    NO WINNER -- vote untrusted
    NO WINNER -- D4 residual too high
    SINGULAR FIT -- D4 not evaluated
    REFLECTION REJECTED -- reflection-free workflow

### Reflection rejection (the guard)

The math still evaluates the full D4 set internally (no change to the candidate enumeration in `compute_d4_candidate_residuals`). What changes is
acceptance: if the best-fitting D4 candidate has determinant -1, `measure()` must reject the measurement with a clear reason rather than silently
accepting a mirrored calibration.

Rejection happens in `measure()`, not in `save_and_visualize()`. The rejected state must be visible in the Step 2 review; Step 3 only inherits the
already-set rejected state and consequently skips the staging config write.

Behavior on reflection-best (set in `measure()`):

- `session.d4_label` records the reflection label that fit best (still informative for the operator).
- `session.d4_accepted = False`.
- `session.failure_reason` (or whichever existing field carries the reject reason in PR 6) is set to:
  `reflection candidate selected; this workflow assumes a reflection-free optical path`.
- Step 3 must not write a staging config (Section 15 invariant: staging only exists when registration is trustworthy).
- Report JSON carries the same reason/status as existing rejected paths.

This guard exists because the operator view no longer shows reflection candidates. Silently accepting a reflected-best result while only displaying
rotations would be the worst failure mode: the operator would never see the candidate that was actually chosen.

### Disk artifacts (Step 3)

Disk outputs are unchanged from PR 6. All four PNGs continue to be written to `reports/`:

- `image_to_stage_raw_triplet.png`
- `image_to_stage_overlay_home_plus_x.png`
- `image_to_stage_overlay_home_plus_y.png`
- `image_to_stage_d4_candidates.png`

The `figures:` block in `image_to_stage_report.json` is unchanged.

The raw triplet and the two measured overlays are rendered, saved, and closed without inline display. They remain available on disk for provenance
and post-hoc inspection.

## Scope

Touch only:

- `calibration/workflows/common.py`
- `calibration/workflows/image_to_stage.py`
- `calibration/notebooks/calibrate_image_to_stage.ipynb`
- `test/test_calibration_workflows.py`

Do not touch:

- `calibration/workflows/objective_pair.py`
- `calibration/notebooks/calibrate_objective_pair.ipynb`
- `calibration/workflows/promotion.py`
- `calibration/scripts/*`
- `calibration/lib/*`

## Hard rules

1. ASCII only in code, markdown, comments, JSON keys.
2. Step 2 stays display-only: no JSON writes, no PNG writes, no staging config writes.
3. Step 3 remains the only writer of report JSON, PNG diagnostics, and staging config.
4. Preserve PNG filenames and `figures:` block keys exactly: `raw_triplet`, `overlay_home_plus_x`, `overlay_home_plus_y`, `d4_candidates`.
5. Do not change the D4 sign convention:
   `pred_image_disp_um = -inv(candidate_image_to_stage) @ stage_disp_um`.
6. Do not change registration, voting, promotion, archive behavior, or stage movement.
7. The internal D4 evaluation set is unchanged (still all 8). Only the operator view and the acceptance gate change.

## Tests

Update the existing layout-sensitive tests and add the following:

1. `test_plot_d4_candidates_rotation_only_layout`
   - Render with accepted `-Y +X` data.
   - Assert only the 4 rotation labels appear as candidate tile titles.
   - Assert reflection labels (`+X -Y`, `-X +Y`, `+Y +X`, `-Y -X`) do not appear as candidate tile titles.
   - Assert no title contains `"nan"`.

2. `test_plot_d4_candidates_suptitle_names_rotation_winner`
   - Suptitle starts with `Winner: -Y +X`.
   - Contains the word `rotation`.
   - Contains `+X residual` and `+Y residual`.

3. `test_image_to_stage_rejects_reflection_candidate`
   - Provide trusted votes that make a determinant -1 D4 candidate the best fit.
   - Call `measure()`. Immediately after `measure()` returns, assert:
     - `session.d4_label` is the reflection label.
     - `session.d4_accepted is False`.
     - `session.failure_reason` contains `reflection-free`.
   - Then call `save_and_visualize()` and assert no staging config is written; report JSON carries the same reason.
   - The post-`measure()` assertions matter: rejection must be visible in the Step 2 review, not deferred until Step 3.

4. `test_display_measurement_review_displays_only_d4_grid`
   - Monkeypatch `IPython.display.display` to record calls.
   - Run on a measured trusted session.
   - Exactly one Figure is displayed.
   - Its suptitle starts with one of: `Winner:`, `NO WINNER`, `SINGULAR FIT`, `REFLECTION REJECTED`.

5. Existing affected tests:
   - Update `test_plot_d4_candidates_highlights_expected_label` for the grouped 1x4 layout.
   - Update `test_plot_d4_candidates_nan_measurement_titles_have_no_nan` if it walks `fig.axes`.
   - Existing PNG output and display-purity tests must still pass.

Expected count after: about 62 (current 59 + roughly 3 new, depending on in-place absorption).

## Out of scope (deferred)

- A second rig run of `image_to_stage` with this compact diagnostic.
- The first rig run of `objective_pair`.
- `objective_pair` PNG diagnostics patch.
- Optional debug toggle to re-enable the full 8-candidate D4 view.
- Optional debug toggle to re-enable the inline raw triplet and measured overlays.
