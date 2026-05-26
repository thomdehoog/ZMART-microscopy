# Calibration Notebook Plans: Codex vs Claude

This compares:

- `CALIBRATION_NOTEBOOKS_PLAN_codex.md`
- `CALIBRATION_NOTEBOOKS_PLAN_claude.md`

The goal is not to pick a winner wholesale. Both plans converge on the same architecture. The useful outcome is a final implementation direction that keeps the good parts and avoids API or unit mistakes.

## Executive Summary

Both plans agree on the core design:

- Two notebooks.
- Thin notebooks, fat workflow modules.
- One session folder per calibration campaign.
- `current_config/` as the only live production config folder.
- Explicit promotion.
- Five-cell objective-pair notebook.
- Exact image-size and pixel-size validation.
- Voting registration for XY.
- Brenner focus for Z.
- `translation = motor_shift + correction`.
- Production configs stay lean; reports keep diagnostics.

The best final implementation should mostly follow the shared architecture, but with these decisions:

1. Use the existing `register_voting(ref, tgt, pixel_um)` API directly. It returns image displacement in micrometers, not pixels.
2. Use manual z-wide stepping for parfocality in v1: move z-wide, acquire a frame, compute Brenner. This matches the "notebook only moves xyz and acquires" constraint better than configuring a LAS X z-stack.
3. Do not require active objective-slot validation unless a real read API is confirmed. `objective_by_slot()` only maps installed objectives; it does not read the currently active objective.
4. Use `drv.acquire_frame()` / `drv.acquire_stack()` or workflow-local wrappers. Do not use `drv.acquire_single`; that public driver function does not exist.
5. Use the real `drv.move_z(client, job_name, z, unit="um", z_mode="zwide")` signature.
6. Define image size unambiguously as array shape: `[height, width]`. If job format is also useful, put it in reports as separate metadata.
7. Gate staging configs strictly: weak voting writes report/visuals but not `configs/*.json`.

## Where The Plans Converge

### Workflow Shape

Both plans use two notebooks:

1. `calibrate_image_to_stage.ipynb`
2. `calibrate_objective_pair.ipynb`

Both plans keep the notebooks thin:

- Markdown instructions.
- One workflow function call per code cell.
- No measurement logic in notebook cells.

Recommended implementation:

Keep this exactly.

### Objective-Pair Notebook Cell Structure

Both plans keep the five-cell phenomenon-grouped structure:

1. Config / open session.
2. Parfocality reference.
3. Parfocality target.
4. Parcentricity reference.
5. Parcentricity target + save.

Extra objective switches are accepted because this makes the calibration easier to inspect and rerun.

Recommended implementation:

Keep this exactly.

### Session And Live Config Layout

Both plans use:

```text
calibration/
  current_config/
  sessions/
    <session_id>/
      configs/
      reports/
      notebooks/
      data/
```

Both agree that:

- `sessions/<session_id>/configs/` is staging.
- `sessions/<session_id>/reports/` is diagnostic.
- `sessions/<session_id>/data/` is raw acquisition data.
- `current_config/` is live.
- Production reads only from `current_config/`.

Recommended implementation:

Keep this exactly.

### Promotion

Both plans make promotion explicit:

```python
promotion.promote_calibration(...)
```

Both agree:

- Save workflows do not promote.
- Promotion validates staging JSON.
- Existing live config is archived.
- Promotion appends to `.promotion.log`.

Recommended implementation:

Keep this exactly.

### Calibration Math

Both plans agree:

```text
P_target = P_ref + translation
translation = motor_shift + correction
```

Reports keep:

```text
motor_shift_xy_um
motor_shift_z_um
correction_xy_um
correction_z_um
```

Production objective config stores only:

```text
translation_xy_um
translation_z_um
```

Recommended implementation:

Keep this exactly.

### Validation Policy

Both plans agree:

- Pixel size must match exactly.
- Image size must match exactly.
- v1 does not rescale.
- D4 residual above threshold is an error.
- Weak voting is not promotable.

Recommended implementation:

Keep this exactly.

## Major Divergences And Best Implementation

## 1. Registration Units

### Codex Plan

Uses the current API:

```python
vote = register_voting(ref, tgt, pixel_um)
dx_um = vote["dx_um"]
dy_um = vote["dy_um"]
```

The returned displacement is image displacement in micrometers.

### Claude Plan

Treats voting registration as pixel-returning:

```python
shift_x_px, vote_x = algos.register_voting(home, plus_x)
shift_x_um = shift_x_px * pixel_size_um
```

It also describes a thin wrapper that returns pixels.

### Existing Code

The existing implementation is:

```python
def register_voting(ref, tgt, pixel_um, ...):
    ...
    return {
        "dx_um": dx_um,
        "dy_um": dy_um,
        "quality": quality,
        "confidence": confidence,
        "trusted": confidence >= min_agree,
        ...
    }
```

The individual methods multiply pixel displacement by `pixel_um` before returning.

### Best Implementation

Use the Codex convention.

Do this:

```python
vote = register_voting(ref, tgt, pixel_um)
image_shift_um = np.array([vote["dx_um"], vote["dy_um"]])
correction_xy_um = image_to_stage @ image_shift_um
```

Do not do this:

```python
shift_px = register_voting(...)
shift_um = shift_px * pixel_size_um
```

That would either fail against the real API or double-apply pixel size if wrapped incorrectly.

### Final Rule

The final plan should say:

```text
register_voting returns image displacement in micrometers.
image_to_stage maps image-um displacement to stage-um displacement.
```

## 2. Meaning Of `image_to_stage`

### Codex Plan

Says `image_to_stage` maps image displacement in micrometers to stage displacement in micrometers.

### Claude Plan

Says `image_to_stage` is dimensionless, one of the eight D4 rotation/reflection matrices, with scaling in `pixel_size_um`.

### Existing Code

The current D4 snap returns canonical matrices with entries in:

```text
{-1, 0, +1}
```

So after snapping, the live matrix is dimensionless orientation/reflection, assuming image displacement is already in micrometers.

### Best Implementation

Use Claude's more precise wording, but Codex's API path.

Final wording:

```text
register_voting returns image displacement in micrometers.
image_to_stage is a dimensionless D4 orientation/reflection matrix.
correction_xy_um = image_to_stage @ image_shift_um
```

Do not name the field `image_to_stage_um_per_px`.

Keep the JSON field:

```json
"image_to_stage": [[0.0, -1.0], [1.0, 0.0]]
```

## 3. Z-Stack / Parfocality Acquisition

### Codex Plan

Uses the existing `configure_z_stack(...)` helper and `drv.acquire_stack(...)`.

### Claude Plan

Uses manual z-wide stepping:

1. Build `z_values`.
2. Move z-wide to each value.
3. Acquire one image per z.
4. Compute Brenner scores.
5. Fit/refine peak.

### Existing Code

Both are feasible. Existing helpers support z-stack acquisition:

```python
configure_z_stack(...)
drv.acquire_stack(...)
brenner_focus(stack, z_step)
```

But the user requirement for the notebook is that it should mostly:

```text
set/get xy and z, acquire, analyze
```

The operator should own microscope settings.

### Best Implementation

Use Claude's manual z-wide stepping in v1, with corrected driver calls and existing Brenner code.

Reason:

- It avoids changing LAS X z-stack settings inside the workflow.
- It makes every z-wide position explicit.
- It avoids ambiguity from high-Z-to-low-Z stack ordering.
- It matches the desired notebook boundary: move z, acquire, analyze.
- It is easier to debug from saved images.

Correct implementation:

```python
z_values = np.arange(
    z_post - z_range_um,
    z_post + z_range_um + z_step_um / 2,
    z_step_um,
)

images = []
for i, z_um in enumerate(z_values):
    drv.move_z(client, job_name, float(z_um), unit="um", z_mode="zwide")
    img, exported_path = drv.acquire_frame(client, job_name, backlash_params=...)
    save_image_tiff(img, data_dir / "target_z_stack" / f"z_{i:03d}.tif")
    images.append(img)

focus = brenner_focus(np.asarray(images), z_step_um)
focus_z_target_um = float(z_values[0] + focus["peak_um"])
```

Important correction to Claude's code:

Use:

```python
drv.move_z(client, job_name, z_um, unit="um", z_mode="zwide")
```

not:

```python
drv.move_z(client, z_um, z_mode="zwide")
```

## 4. Brenner Focus Implementation

### Codex Plan

Uses existing `brenner_focus(stack, z_step_um)`.

### Claude Plan

Re-describes Brenner scoring and parabolic interpolation manually.

### Existing Code

`navigator_expert.algorithms.focus` already has:

```python
def brenner(img) -> float
def subpixel_peak(scores, peak) -> float
def brenner_focus(stack, z_step) -> dict
```

`brenner_focus` already does parabolic sub-step refinement and handles edge peaks by falling back to the integer peak.

### Best Implementation

Use the existing `brenner_focus`.

If manual z-wide stepping is used, pass the acquired images as a stack in ascending z order:

```python
focus = brenner_focus(stack, z_step_um)
focus_z_target_um = z_values[0] + focus["peak_um"]
```

Do not duplicate the Brenner math unless the existing implementation proves insufficient.

## 5. Active Objective Validation

### Codex Plan

Does not require active objective validation.

### Claude Plan

Requires:

```python
assert_active_slot(client, expected_slot, expected_label)
```

at every measurement cell.

### Existing Code

There is:

```python
drv.objective_by_slot(hw_info)
drv.objective_summary(obj)
drv.validate_slots(...)
```

These inspect installed objectives from hardware info. They do not prove which objective is currently active.

No existing public driver API was found that reliably returns the active objective slot.

### Best Implementation

Do not make active objective validation a blocking v1 requirement.

Recommended v1:

- Resolve and record objective metadata from `get_hardware_info()` if useful.
- Print expected operator state in the returned session summary.
- Keep markdown instructions explicit.
- Let image registration, Brenner curves, and visual overlays catch wrong-switch cases.

Optional later:

- If a verified active-objective read API is found, add `assert_active_objective(...)`.
- Until then, do not invent `active_objective_slot()`.

## 6. Driver API Accuracy

### Claude Plan Issues

Claude names some APIs incorrectly:

```python
drv.move_z(client, target_um, z_mode="zwide")
drv.acquire_single
algos.register_voting(home, plus_x)
```

### Existing Code

The real signatures are:

```python
drv.move_z(client, job_name, z, unit="um", z_mode="zwide")
drv.acquire_frame(client, job_name, ...)
drv.acquire_stack(client, job_name, ...)
register_voting(ref, tgt, pixel_um)
```

### Best Implementation

Use Codex's API list, with the manual z-loop change from Claude.

The common acquisition wrapper should call:

```python
img, exported_path = drv.acquire_frame(client, job_name, backlash_params=...)
```

and then write a stable copy into:

```text
sessions/<session_id>/data/<kind>/
```

## 7. Common Module Name

### Codex Plan

Uses:

```text
calibration/workflows/common.py
```

### Claude Plan

Uses:

```text
calibration/workflows/_common.py
```

### Best Implementation

Use:

```text
calibration/workflows/_common.py
```

Reason:

- Notebooks should only import `image_to_stage`, `objective_pair`, and `promotion`.
- The helper module is internal to workflows.
- The underscore reduces the chance that notebook users treat it as public API.

This is a minor decision. Either name works if imports are consistent.

## 8. Image Size Convention

### Codex Plan

Uses image array shape:

```text
[height, width]
```

### Claude Plan

Uses job-format style:

```text
[W, H]
```

### Best Implementation

Use array-shape order:

```json
"image_size_px": [height, width]
```

Reason:

- Validation compares against `img.shape[-2:]`.
- Numpy and TIFF loading naturally produce `(height, width)`.
- It avoids axis reversal during implementation.

If job format is needed for human readability, put it in the report as:

```json
"job_format_px": [width, height]
```

Do not use `image_size_px` ambiguously.

## 9. Objective Names, Slots, And Filenames

### Codex Plan

Uses a slug helper and stores:

```python
session.objective_config_name
```

Promotion uses:

```python
staging_name=session.objective_config_name
```

### Claude Plan

Resolves slots from labels and constructs promotion filenames inline:

```python
f"objective_{session.from_objective}_to_{session.to_objective}.json"
```

### Best Implementation

Use Codex's filename approach:

```python
session.objective_config_name
```

Reason:

- One place owns filename construction.
- Objective names may contain spaces, slashes, dots, or long Leica names.
- Promotion should not duplicate slug logic in notebook cells.

Slot metadata can be added to reports if labels can be matched unambiguously, but filename generation should not depend on slot validation.

## 10. Trusted / Config-Written Report Fields

### Codex Plan

Uses `config_written` in report examples.

### Claude Plan

Uses `trusted`.

### Best Implementation

Use `trusted` in reports.

Use returned notebook summaries to show whether a config path was written.

Recommended report:

```json
{
  "trusted": true,
  "calibration_file": "objective_10x_to_20x.json"
}
```

Recommended summary:

```python
{
    "trusted": True,
    "config_path": ".../configs/objective_10x_to_20x.json",
    "report_path": ".../reports/objective_10x_to_20x_report.json",
}
```

Reason:

- `trusted` is the measurement verdict.
- `config_path` in the summary is enough for the operator.
- Promotion itself verifies file existence.

If implementation writes `config_written` too, it is not harmful, but it is redundant.

## 11. Test Strategy

### Codex Plan

Emphasizes many mocked unit tests, including mocking registration.

### Claude Plan

Emphasizes using real algorithm functions for registration/D4 math tests and a mock LAS X client for workflow integration.

### Best Implementation

Use both layers:

1. Pure unit tests with mocked driver calls for path/session/promotion behavior.
2. Synthetic algorithm tests using real `register_voting`, `classify_d4`, and `brenner_focus`.
3. Workflow tests where registration can be mocked to force weak/strong votes.
4. One manual microscope integration run for Notebook 1 before implementing Notebook 2 fully.

This gives isolation and still catches convention errors in the real algorithms.

## 12. Raw Data Handling

### Codex Plan

Writes stable session-owned TIFF copies after acquisition.

### Claude Plan

Also saves raw TIFFs, but is less explicit about preserving exported paths.

### Best Implementation

Use Codex's session-owned data model:

- Call `drv.acquire_frame(...)`.
- Receive `(image, exported_path)`.
- Write a stable copy into `sessions/<id>/data/<kind>/`.
- Store both session-relative data path and original LAS X export path in the report.

Recommended report fragment:

```json
"images": {
  "ref_xy": "data/objective_10x_to_20x/ref_xy.tif"
},
"exported_files": {
  "ref_xy": "Z:/.../original_lasx_export.tif"
}
```

If the exported path is too noisy, keep it report-only and never in production config.

## Final Recommended Implementation

Implement the combined plan below.

### Modules

```text
calibration/workflows/
  __init__.py
  _common.py
  image_to_stage.py
  objective_pair.py
  promotion.py
```

### Registration

Use existing API:

```python
vote = register_voting(ref, tgt, pixel_um)
image_shift_um = np.array([vote["dx_um"], vote["dy_um"]])
stage_shift_um = image_to_stage @ image_shift_um
```

No pixel-returning wrapper in v1.

### Image-To-Stage

Acquire:

```text
home
plus_x
plus_y
```

Use voting registration:

```python
vote_x = register_voting(home, plus_x, pixel_um)
vote_y = register_voting(home, plus_y, pixel_um)
```

Fit:

```python
stage_to_image = np.array([
    [vote_x["dx_um"] / stage_move_um, vote_y["dx_um"] / stage_move_um],
    [vote_x["dy_um"] / stage_move_um, vote_y["dy_um"] / stage_move_um],
])
image_to_stage_fitted = -np.linalg.inv(stage_to_image)
d4_label, image_to_stage, residual = classify_d4(image_to_stage_fitted)
```

Gate:

- Raise on D4 residual above threshold.
- Write report always.
- Write staging config only if both votes are trusted.

### Parfocality Z

Use manual z-wide stepping:

```python
z_values = np.arange(z_post - z_range_um, z_post + z_range_um + z_step_um / 2, z_step_um)
for z_um in z_values:
    drv.move_z(client, job_name, float(z_um), unit="um", z_mode="zwide")
    img, exported_path = drv.acquire_frame(client, job_name, backlash_params=...)
```

Then:

```python
focus = brenner_focus(stack, z_step_um)
focus_z_target_um = z_values[0] + focus["peak_um"]
motor_shift_z_um = z_post - home_z
correction_z_um = focus_z_target_um - z_post
translation_z_um = focus_z_target_um - home_z
```

### Parcentricity XY

After target switch:

```python
xy_post = drv.get_xy(client)
motor_shift_xy_um = xy_post - home_xy
```

Acquire target at post-switch XY:

```text
Do not move XY back to home.
```

Then:

```python
vote = register_voting(ref_xy, target_xy, pixel_um)
image_shift_um = np.array([vote["dx_um"], vote["dy_um"]])
correction_xy_um = image_to_stage @ image_shift_um
translation_xy_um = motor_shift_xy_um + correction_xy_um
```

Gate:

- Write report always.
- Write staging config only if vote is trusted.

### Objective Validation

Do not block v1 on active objective validation.

Use:

- clear notebook markdown,
- summary output showing expected objective,
- visual overlays,
- report diagnostics.

If a verified active-objective read API is found later, add it as a strict precondition.

### Image Size

Use:

```json
"image_size_px": [height, width]
```

and validate against:

```python
img.shape[-2:]
```

### Promotion

Promotion copies:

```text
sessions/<session_id>/configs/<name>.json
```

to:

```text
calibration/current_config/<name>.json
```

If the staging config is missing because the measurement was untrusted, promotion raises clearly.

## Practical Next Step

Before implementation, update whichever plan becomes source-of-truth with these corrections:

1. Remove the pixel-returning `register_voting` assumption.
2. Fix all `drv.move_z` signatures to include `job_name`.
3. Replace `drv.acquire_single` with `drv.acquire_frame`.
4. Decide `_common.py` vs `common.py`; recommended `_common.py`.
5. Define `image_size_px` as `[height, width]`.
6. Replace hard active-objective validation with optional/best-effort validation unless a real API is confirmed.
7. Use manual z-wide stepping for parfocality v1.

After that, implementation can proceed without re-litigating the design.
