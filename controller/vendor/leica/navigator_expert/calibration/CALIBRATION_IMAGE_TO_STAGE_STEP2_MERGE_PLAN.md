# Image-to-Stage Step 2 Merge Plan

## Status

Design plan. Not implemented yet.

This plan is PR 8. It cleans up the image-to-stage notebook flow after the
rotation-only D4 review work. The goal is to make the operator-facing output
lean: one diagnostic figure, one human-readable decision block, and one
optional promote step.

## Goal

Merge the old "summarize and save" cell into the measurement cell:

- Step 1: Configure.
- Step 2: Run measurement and save.
- Step 3: Optional promote.

Step 2 becomes the only operator review point before promotion. It displays
exactly one D4 candidate figure, writes the report and PNG diagnostics, writes
the staging config only on accepted measurements, prints a human-readable
summary, and returns the existing summary dict.

## Scope

Touch:

- `calibration/workflows/common.py`
  - `plot_d4_candidates` layout only.
- `calibration/workflows/image_to_stage.py`
  - merge display behavior into `save_and_visualize`
  - remove the no-longer-used `display_measurement_review` path if grep proves
    it has no non-test, non-notebook callers
  - rewrite the printed operator summary
- `calibration/notebooks/calibrate_image_to_stage.ipynb`
  - remove the separate save step
  - fold `save_and_visualize` into Step 2
  - rename optional promotion to Step 3
- `test/test_calibration_workflows.py`

Hands off:

- `calibration/workflows/objective_pair.py`
- `calibration/notebooks/calibrate_objective_pair.ipynb`
- `calibration/workflows/promotion.py`
- every shared helper in `common.py` except `plot_d4_candidates`

The user may be rig-testing the objective-pair notebook in parallel. This patch
must not perturb that workflow.

## Hard Rules

1. ASCII only.
2. No new public API.
3. `measure()` and `save_and_visualize()` are the only image-to-stage Step 2
   entry points the notebook needs.
4. Disk artifacts are unchanged:
   - same four PNG filenames in `reports/`
   - same `figures:` block keys
   - same report JSON schema
   - same returned summary dict shape
5. D4 math, D4 sign convention, reflection guard, residual gate, and voting
   thresholds are unchanged.
6. `save_and_visualize(session)` displays exactly one inline figure: the D4
   candidate grid.
7. Raw triplet and overlay figures are still written to disk for provenance but
   are never displayed inline.
8. Every existing objective-pair test must pass without modification.
9. Preserve whatever Step 1 runtime-root configuration exists on the current
   branch. This PR changes the image-to-stage Step 2/Step 3 flow, not runtime
   root APIs.

## Task 1: Fix `plot_d4_candidates` Layout

Only edit `plot_d4_candidates` and directly local helpers/constants needed by
that function. Do not change D4 residual computation or image-shift math.

Required layout:

- One figure with four rotation candidate tiles.
- Each candidate tile owns two stacked image axes:
  - top: corrected `+X` move
  - bottom: corrected `+Y` move
- Rotation candidates remain in this order:
  - `+X +Y`
  - `-Y +X`
  - `-X -Y`
  - `+Y -X`

### Winner Highlight

Replace subfigure patch styling with a figure-level rectangle:

```python
fig.add_artist(
    matplotlib.patches.Rectangle(
        (x, y),
        w,
        h,
        fill=False,
        edgecolor="lime",
        linewidth=4,
    )
)
```

The rectangle should use the winning tile's bounding box in figure coordinates.
The goal is backend-stable rendering in JupyterLab and PNG output. Do not use
`subfigure.patch.set_edgecolor("lime")` as the primary highlight mechanism.

Use this pattern:

```python
fig.canvas.draw()  # force layout before measuring the subfigure bbox
bbox = winner_sub.bbox.transformed(fig.transFigure.inverted())
rect = matplotlib.patches.Rectangle(
    (bbox.x0, bbox.y0),
    bbox.width,
    bbox.height,
    fill=False,
    edgecolor="lime",
    linewidth=4,
    transform=fig.transFigure,
)
fig.add_artist(rect)
```

If this pattern does not work in the current Matplotlib version, pause and
report. Do not replace it with a large gridspec-math workaround without review.

### Tile Text

Each tile uses its subfigure suptitle for the candidate label and residuals:

```python
sub.suptitle(f"{label}\n+X {rx:.1f} um  |  +Y {ry:.1f} um", fontsize=10)
```

Rules:

- The candidate label and residuals are not inner-axis titles.
- Inner axes have no titles.
- On the leftmost candidate only:
  - top inner axis gets `ax.set_ylabel("+X")`
  - bottom inner axis gets `ax.set_ylabel("+Y")`
- No other axis carries text labels.

### Global Title

The global suptitle is one line.

Success:

```text
Winner: -Y +X (rotation)
```

Failure examples:

```text
NO WINNER -- vote untrusted
NO WINNER -- D4 residual too high
REFLECTION REJECTED -- reflection-free workflow
SINGULAR FIT -- D4 not evaluated
```

Do not append residuals to the global title. Residuals live in each tile title.

### Figure Size

Use `figsize=(12, 8)`. Do not tune figure size further in this patch unless the
render is unreadable and you flag the proposed adjustment.

## Task 2: Merge Display Into `save_and_visualize`

`save_and_visualize(session)` becomes the sole Step 2 finalizer.

It must:

1. Render all four figures:
   - raw triplet
   - `home` vs `plus_x` overlay
   - `home` vs `plus_y` overlay
   - D4 candidate grid
2. Save all four PNGs to `reports/` with the existing filenames.
3. Add the same existing `figures:` keys to the report JSON.
4. Display exactly one inline figure: the D4 candidate grid.
5. Close each created figure with `plt.close(fig)`.
6. Write report JSON.
7. Write the staging config only when the existing acceptance gates pass.
8. Print the new human-readable summary.
9. Return the existing summary dict.

Do not call `plt.close("all")`; that can close unrelated operator figures in an
interactive kernel.

Remove `display_measurement_review` only after running:

```text
grep -rn "display_measurement_review" .
```

If there are non-test, non-notebook callers, pause and report. Do not leave a
dead public helper behind just to preserve stale API surface.

## Task 3: Human-Readable Operator Summary

Rewrite the existing module-level `_print_text_summary` helper in place to emit
the operator decision block below. It is an internal helper; do not rename it or
turn it into public API. The matrices stay in the report JSON and returned
summary dict; they are not printed by default.

### Success Template

```text
Image-to-stage calibration: OK

  Reference objective:  10x
  Stage move:           40.0 um
  Voting:               +X trusted (3/3),  +Y trusted (3/3)
  Orientation winner:   -Y +X  (90 deg CCW rotation)
  D4 residual:          0.04 um  (threshold 0.30 um)

  Staging config written:
    C:\...\sessions\<id>\configs\image_to_stage.json

  Run the promote cell below to copy this to the live config.
```

### Failure Template

Use one failure shape for reflection rejection, high D4 residual, weak vote, and
singular fit.

```text
Image-to-stage calibration: <STATUS HEADER>

  Reference objective:  <objective>
  Stage move:           <um> um
  Voting:               +X <trusted|untrusted> (N/3),  +Y <trusted|untrusted> (N/3)
  Orientation:          <best-fit label and geometry, or "not evaluated">
  D4 residual:          <value> um  (threshold 0.30 um)

  No staging config written.
  Reason: <session.failure_reason>
```

Omit the `D4 residual` line if no residual was evaluated.

`<STATUS HEADER>` should be derived from the existing status logic, for example:

- `REFLECTION REJECTED`
- `FAILED -- D4 residual too high`
- `FAILED -- voting registration not trusted`
- `FAILED -- singular fit`

### Formatting Rules

- Verify the maximum voting confidence by reading the current voting result
  shape. Use the actual maximum as the denominator. Do not hardcode `/3` if the
  implementation uses a different scale.
- Voting line uses the existing confidence integer:
  - `trusted (N/3)`
  - `untrusted (N/3)`
- Residual and threshold use two decimals.
- The config path is the absolute string already returned in
  `summary["config_path"]`.
- Geometry labels:
  - `+X +Y` -> `identity`
  - `-Y +X` -> `90 deg CCW rotation`
  - `-X -Y` -> `180 deg rotation`
  - `+Y -X` -> `90 deg CW rotation`
- Reflection labels -> `reflection`. Prefer the same determinant-based check
  used by the reflection guard (`det(matrix) < 0`) over enumerating reflection
  label strings.

## Task 4: Notebook Update

Update only `calibration/notebooks/calibrate_image_to_stage.ipynb`.

1. Delete the old Step 3 markdown and code cell.
2. Rename the old optional promote section to Step 3 in markdown.
3. Change Step 2 code to:

```python
session = wf.measure(session)
summary = wf.save_and_visualize(session)
```

4. Replace Step 2 markdown with:

```markdown
## Step 2: Run measurement and save

Acquire the home, +X, and +Y raw TIFFs, run voting registration, fit the 2x2
image-to-stage matrix against the 4 rotation candidates, and save the report
plus diagnostic PNGs. A staging config is written only if voting is trusted
and the D4 fit is accepted. The diagnostic figure below is the operator's
go/no-go view: each tile is one rotation candidate; the winner is highlighted
with a lime border and named in the figure title.

This notebook assumes the optical path is reflection-free. If a reflection
candidate fits best, the workflow rejects the measurement and asks you to
check camera/scan orientation rather than silently accepting a mirrored
calibration.
```

5. Verify Step 1 markdown still references Step 1 correctly.
6. Verify the new Step 3 promote cell uses the `summary` produced by Step 2 if
   it references the summary at all.
7. Preserve any current explicit runtime-root configuration in Step 1.

## Task 5: Tests

Delete tests that only protect the removed pure-display path:

- `test_display_measurement_review_is_pure`
- `test_display_measurement_review_displays_only_d4_grid`
- `test_display_measurement_review_weak_vote_text_has_no_nan`

Update tests:

- `test_plot_d4_candidates_highlights_expected_label`
  - find one figure-level `matplotlib.patches.Rectangle` with lime edge color
  - assert it corresponds to the winning tile
- `test_plot_d4_candidates_rotation_only_layout`
  - four rotation labels appear as subfigure suptitles
  - rotation labels do not appear as inner-axis titles
- `test_plot_d4_candidates_suptitle_names_rotation_winner`
  - global suptitle equals `Winner: -Y +X (rotation)` exactly
- `test_image_to_stage_save_and_visualize_writes_png_diagnostics`
  - monkeypatch `IPython.display.display`
  - assert exactly one inline display call

Add tests:

- `test_plot_d4_candidates_uses_rectangle_artist_for_winner`
  - no subfigure patch uses lime edge color as the winner highlight
  - the winner highlight comes from a figure-level `Rectangle`
- `test_plot_d4_candidates_no_redundant_axis_titles`
  - no inner axis title contains `stage +X correction` or
    `stage +Y correction`
- `test_image_to_stage_save_and_visualize_operator_summary_format`
  - use pytest's `capsys` fixture to capture stdout
  - success path stdout contains:
    - `Image-to-stage calibration: OK`
    - `Orientation winner:`
    - `D4 residual:`
    - `Staging config written:`
  - success path stdout does not contain the old dev-style keys:
    - `fitted_image_to_stage:`
    - `residual_from_d4:`
    - `d4_label:`
  - reflection-rejection path stdout contains:
    - `REFLECTION REJECTED`
    - `No staging config written.`

Expected count:

- If this patch starts from the current PR 7 baseline: `63 - 3 + 3 = 63`.
- If another PR landed first, expected count is "current baseline - 3 + 3".
- Any unexpected count change needs investigation before reporting done.

## Cross-Notebook Safety Check

Run the full calibration workflow test file, not only image-to-stage tests.

Command:

```text
cd Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\controller\vendor\leica\navigator_expert
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe" -m pytest test\test_calibration_workflows.py
```

Every existing objective-pair test must pass unchanged. If any objective-pair
test breaks, stop and report; the patch touched shared state beyond its scope.

Watch especially:

- `test_objective_pair_*`
- `test_acquire_failure_returns_stage_to_home`
- `test_collinear_votes_singular_matrix`

## Acceptance Criteria

1. Image-to-stage notebook has exactly three steps:
   - Step 1: Configure
   - Step 2: Run measurement and save
   - Step 3: Optional promote
2. Step 2 displays exactly one inline figure.
3. The inline figure is the rotation-only D4 grid.
4. The winner tile has one closed lime rectangle on all four sides in
   JupyterLab's default backend.
5. Tile labels and global title do not overlap.
6. The leftmost tile has `+X` and `+Y` y-axis labels; no other inner axis has a
   text label or title.
7. Step 2 prints the new human-readable operator block.
8. `reports/` contains all four existing PNG diagnostics after Step 2.
9. Report JSON schema and returned summary dict shape are unchanged.
10. Objective-pair workflow and notebook are untouched.
11. Full test file passes with 63 tests if starting from the PR 7 baseline.
12. Rig visual verification is required before merge. If the rig is unavailable,
    mark the PR as awaiting rig confirmation and do not declare the visual part
    done.

## Pause and Ask

Pause before implementing if:

- `display_measurement_review` has non-test, non-notebook callers.
- Computing the winner rectangle in figure coordinates becomes more than a
  small local block.
- Any required change touches a `common.py` symbol other than
  `plot_d4_candidates`.
- Any objective-pair test failure appears.

## Report Back

When done, report:

- files changed
- final pytest count
- confirmation that all objective-pair tests passed unchanged
- any deviations from this plan
- rig visual result:
  - closed lime border
  - no text collision
  - single inline figure
  - human-readable summary

If rig visual verification was not possible, report `awaiting rig confirmation`
explicitly.
