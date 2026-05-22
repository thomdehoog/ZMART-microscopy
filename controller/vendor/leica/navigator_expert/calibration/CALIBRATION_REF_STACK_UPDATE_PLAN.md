# Calibration Ref-Stack Update Plan

## Purpose

Update the objective-pair calibration so parfocality is measured peak-to-peak:

```text
translation_z_um = focus_z_target_um - focus_z_ref_um
```

Both `focus_z_ref_um` and `focus_z_target_um` must come from Brenner focus peaks on acquired z-stacks. The current workflow compares a target-side Brenner peak to the operator's approximate reference focus (`home_z`). That mixes two different focus definitions and can bake operator focus error into the Z translation.

This plan also updates the objective-pair notebook instructions to stress that pixel size and image format must match across all parfocality and parcentricity acquisitions.

## Key Design Decision

Do not configure z-stacks through the API.

The operator configures z-stack settings in LAS X. The notebook triggers the already-configured acquisition and analyzes the exported stack.

This avoids the buggy API path for setting z-stack range, step, slice count, or direction while keeping the measurement quantitative and repeatable.

## Operator / Notebook Boundary

Operator owns:

- Objective switching.
- LAS X job selection.
- Scan format, pixel size, zoom, channels, and z-stack setup.
- Approximate reference focus before the reference stack.
- Verifying that the correct objective and settings are active before each step.

Notebook owns:

- Reading XY and z-wide positions.
- Triggering acquisitions.
- Reading/validating images and stacks.
- Computing Brenner curves and focus peaks.
- Computing XY/Z translation.
- Writing reports and gated staging configs.

Notebook must not:

- Call API functions that configure z-stack range, step size, slice count, direction, or enable/disable state.
- Guess z positions silently when stack metadata is missing or inconsistent.
- Treat operator eyeball focus as the reference focus for the final Z translation.

## Pixel Size And Image Format Rule

The following acquisitions must use identical image size and pixel size:

- Reference z-stack.
- Target z-stack.
- Reference XY image.
- Target XY image.

Because objectives have different magnifications, matching pixel size usually means changing LAS X zoom between objectives. The lower-magnification objective generally needs proportionally higher zoom to match the physical pixel size.

The workflow must validate image size and pixel size before analysis. Any mismatch is a hard error.

## Z Model

Definitions:

- `home_xy_um`: XY position under the reference objective.
- `home_z_um`: operator's approximate reference z-wide before the reference stack. Diagnostic only.
- `focus_z_ref_um`: Brenner peak from the reference z-stack.
- `z_post_um`: z-wide readback immediately after switching to the target objective.
- `focus_z_target_um`: Brenner peak from the target z-stack.
- `motor_shift_z_um = z_post_um - focus_z_ref_um`
- `correction_z_um = focus_z_target_um - z_post_um`
- `translation_z_um = focus_z_target_um - focus_z_ref_um`

Identity:

```text
translation_z_um = motor_shift_z_um + correction_z_um
```

Parcentricity reference should acquire at `home_xy_um` and `focus_z_ref_um`.

Parcentricity target should acquire at the post-switch XY and `focus_z_target_um`. The existing expression `focus_z_ref_um + translation_z_um` is equivalent.

## Workflow Changes

### Common Helper: `acquire_stack_to`

Add a workflow-local helper, probably in `calibration/workflows/common.py`:

```python
def acquire_stack_to(session, dirname: str) -> np.ndarray:
    ...
```

Responsibilities:

1. Call `drv.acquire_stack(session.client, session.job_name, backlash_params=session.stage_cfg["backlash"])`.
2. Require the returned stack to have shape `(slices, height, width)`.
3. Write each slice to `session.paths.data_dir / dirname / f"z_{i:03d}.tif"`.
4. Populate `session.raw_files[f"{dirname}/z_{i:03d}"]` with session-root-relative paths.
5. Return the stack as a list or `np.ndarray`.

Do not configure the z-stack. Acquisition must use the currently configured LAS X job.

Exported source paths are currently not returned by `drv.acquire_stack`. Do not change the driver API unless needed. The report can rely on session-owned raw TIFFs under `data/<kind>/`.

### Common Helper: `read_stack_z_positions`

Add a helper to derive absolute z positions for the stack:

```python
def read_stack_z_positions(
    client,
    job_name: str,
    expected_slices: int,
    *,
    override: list[float] | None = None,
) -> list[float]:
    ...
```

Rules:

- If `override` is provided, validate `len(override) == expected_slices`, require `len(override) >= 3` for the parabolic peak to be meaningful, and return it.
- `drv.acquire_stack(...)` returns images only. It does not return z positions.
- Otherwise read LAS X job settings with `drv.get_job_settings(client, job_name)`.
- Normalize settings with `drv.make_changeable_copy(raw_settings)` and read `normalized["stack"]`; fall back to raw `raw_settings["stack"]` only if needed.
- Require at least `begin`, `end`, and `sections`.
- Require `int(sections) == expected_slices`.
- Require `int(sections) >= 3`. The parabolic peak refinement needs at least three samples; a one- or two-slice "stack" would pass `np.argmax` but produce a nonsense `focus_z_*_um`. Raise a clear error pointing the operator at the LAS X stack configuration.
- Compute positions with `np.linspace(begin, end, sections)`. This preserves LAS X order, including reversed stacks when `begin > end`.
- If `stepSize` is present, validate it against the absolute spacing between adjacent positions within a small tolerance.
- If `zDrive` or raw `mode` is present and is not z-wide, raise a clear error. Calibration Z is z-wide only.
- Return absolute z-wide positions in the same order as the stack slices.
- If positions cannot be derived reliably, raise a clear `RuntimeError`.
- Do not guess positions from slice count alone.

This helper is the main risk area. If metadata order is ambiguous on the simulator or rig, fail loudly and allow the operator to pass explicit positions rather than silently computing a wrong focus. Do not derive positions from `expected_slices` alone.

### `ObjectivePairSession` Fields

Add:

```python
ref_z_stack: list[np.ndarray] | np.ndarray | None = None
ref_z_positions_um: list[float] | None = None
ref_z_brenner: list[float] | None = None
focus_z_ref_um: float | None = None
```

Keep existing target fields:

```python
target_z_stack
target_z_positions_um
target_z_brenner
focus_z_target_um
```

Keep `home_z` in session and report as a diagnostic: it tells us how far the operator's approximate focus was from the Brenner focus peak.

### `_clear_parfocality_reference`

Add a new clear helper mirroring `_clear_parfocality_target`:

```python
def _clear_parfocality_reference(session, *, wipe_disk: bool) -> None:
    ...
```

It clears:

- `ref_z_stack`
- `ref_z_positions_um`
- `ref_z_brenner`
- `focus_z_ref_um`
- `raw_files` / `exported_files` entries starting with `ref_z_stack/`

If `wipe_disk=True`, remove:

```text
session.paths.data_dir / "ref_z_stack"
```

### `measure_parfocality_reference`

Change from "record home_z only" to "acquire and analyze reference stack".

Proposed signature:

```python
def measure_parfocality_reference(
    session: ObjectivePairSession,
    *,
    z_positions_um: list[float] | None = None,
) -> ObjectivePairSession:
    ...
```

Behavior:

1. Clear reference parfocality outputs and every downstream state, then invalidate the staging config, before any driver call. Compose the existing PR 2 polish helpers in this order:

   ```python
   _clear_parfocality_reference(session, wipe_disk=True)
   _clear_parfocality_target(session, wipe_disk=True)
   _clear_parcentricity_ref(session)
   _clear_parcentricity_target(session)
   _invalidate_staging_config(session)
   ```

   This mirrors the helper chain `measure_parfocality_target` already uses, but adds `_clear_parfocality_reference` because reference parfocality is now the upstream of the entire pipeline. Any rerun of this cell invalidates target parfocality, parcentricity reference, parcentricity target, and the staging config.
2. Record `home_xy_um` from `get_xy()`.
3. Record `home_z_um` from `read_zwide_um()`. Diagnostic only; not the focus anchor.
4. Trigger the currently configured LAS X z-stack via `acquire_stack_to(session, "ref_z_stack")`.
5. Read or validate z positions with `read_stack_z_positions(..., override=z_positions_um)`.
6. Validate stack image size and pixel size against the loaded `image_to_stage` calibration.
7. Compute Brenner score per slice.
8. Compute `focus_z_ref_um` using the existing parabolic peak helper.
9. Park z-wide at `focus_z_ref_um`.
10. Display the reference Brenner curve.

No calibration config is written in this step.

### `measure_parfocality_target`

Change from "manual z-wide stepping" to "trigger and analyze operator-configured target z-stack".

Proposed signature:

```python
def measure_parfocality_target(
    session: ObjectivePairSession,
    *,
    z_positions_um: list[float] | None = None,
) -> ObjectivePairSession:
    ...
```

Behavior:

1. Require `focus_z_ref_um` to be set.
2. Clear target parfocality outputs, parcentricity target outputs, and the staging config, before any driver call. Compose:

   ```python
   _clear_parfocality_target(session, wipe_disk=True)
   _clear_parcentricity_target(session)
   _invalidate_staging_config(session)
   ```

   This is the same composition the existing `measure_parfocality_target` already uses; do not also call `_clear_parcentricity_ref` because the ref XY image is anchored on `focus_z_ref_um`, which a 2b rerun does not change.
3. Record `z_post_um = read_zwide_um()` after the operator's objective switch.
4. Compute `motor_shift_z_um = z_post_um - focus_z_ref_um`.
5. Trigger the currently configured LAS X z-stack via `acquire_stack_to(session, "target_z_stack")`.
6. Read or validate z positions with `read_stack_z_positions(..., override=z_positions_um)`.
7. Validate stack image size and pixel size against the loaded `image_to_stage` calibration.
8. Compute Brenner score per slice.
9. Compute `focus_z_target_um`.
10. Compute:

```python
correction_z_um = focus_z_target_um - z_post_um
translation_z_um = focus_z_target_um - focus_z_ref_um
```

11. Park z-wide at `focus_z_target_um`.
12. Display the target Brenner curve.

No calibration config is written in this step.

### `measure_parcentricity_reference`

Change the z-wide target from `home_z` to `focus_z_ref_um`.

Prerequisites:

- `home_xy` is set.
- `focus_z_ref_um` is set.

Behavior:

```python
move_xy_and_verify(session.client, *session.home_xy)
zero_z_galvo(session.client, session.job_name)
move_zwide_and_verify(session.client, session.job_name, session.focus_z_ref_um)
```

Then acquire the reference XY image as today and validate geometry.

### `measure_parcentricity_target_and_save`

Keep the no-return-to-home XY behavior.

Use:

```python
move_zwide_and_verify(
    session.client,
    session.job_name,
    session.focus_z_ref_um + session.translation_z_um,
)
```

This equals `focus_z_target_um`.

Keep strict voting gate for writing the staging config.

## Report Schema Changes

Replace the single `brenner` block with two blocks:

```json
"brenner_ref": {
  "peak_z_um": 100.3,
  "scores": [1.0, 2.0, 3.0],
  "z_positions_um": [99.0, 100.0, 101.0]
},
"brenner_target": {
  "peak_z_um": 103.4,
  "scores": [1.0, 2.0, 3.0],
  "z_positions_um": [102.0, 103.0, 104.0]
}
```

Keep or add top-level diagnostic fields:

```json
"home_z_um": 99.8,
"focus_z_ref_um": 100.3,
"z_post_um": 94.0,
"focus_z_target_um": 103.4,
"motor_shift_z_um": -6.3,
"correction_z_um": 9.4,
"translation_z_um": 3.1
```

Images block should include:

```json
"images": {
  "ref_z_stack": "data/objective_10x_to_20x/ref_z_stack/",
  "target_z_stack": "data/objective_10x_to_20x/target_z_stack/",
  "ref_xy": "data/objective_10x_to_20x/ref_xy.tif",
  "target_xy": "data/objective_10x_to_20x/target_xy.tif"
}
```

Production config remains lean:

```json
{
  "schema_version": 1,
  "kind": "objective_translation",
  "created_at": "...",
  "from_objective": "10x",
  "to_objective": "20x",
  "translation_xy_um": [1.2, -3.4],
  "translation_z_um": 3.1
}
```

## Notebook Instruction Updates

The objective-pair notebook keeps the existing five-step structure. Only markdown and the parfocality code calls change.

### Operator Preflight

Replace with:

```markdown
## Operator preflight

A valid `image_to_stage.json` must already exist in `calibration/current_config/`. If it does not, run `calibrate_image_to_stage.ipynb` first and promote its output, or pass an override path via `image_to_stage_path=` in Step 1.

Pixel size and image format must match across the reference z-stack, target z-stack, reference XY image, and target XY image. Since the objectives have different magnifications, matching pixel size usually means changing LAS X zoom between objectives. The lower-magnification objective generally needs proportionally higher zoom.

The operator configures objectives, scan settings, channels, zoom, and z-stack settings in LAS X. The notebook triggers acquisitions, reads positions/images, validates geometry, and analyzes the result.
```

### Step 2: Parfocality Reference

Replace with:

```markdown
## Step 2: Parfocality reference

With the reference objective active, configure the reference z-stack in LAS X. Use the same image size, pixel size, channels, and scan format that will be used for the target z-stack and both parcentricity images. Focus approximately with z-wide before running; the workflow acquires the configured stack and uses the Brenner peak as the reference focus.
```

Code cell:

```python
session = wf.measure_parfocality_reference(session)
print(session)
```

If stack z positions cannot be read reliably from LAS X metadata, the implementation may expose:

```python
session = wf.measure_parfocality_reference(
    session,
    z_positions_um=[...],
)
```

That should be a fallback, not the default operator path.

### Step 3: Parfocality Target

Replace with:

```markdown
## Step 3: Parfocality target

Switch to the target objective in LAS X and configure the target z-stack. Match the image size, pixel size, channels, and scan format from Step 2; this usually requires a different zoom. Do not manually refocus with z-wide after the objective switch. The workflow acquires the configured stack, finds the target Brenner peak, and computes `translation_z_um` as target focus minus reference focus.
```

Code cell:

```python
session = wf.measure_parfocality_target(session)
print(session)
```

### Step 4: Parcentricity Reference

Replace with:

```markdown
## Step 4: Parcentricity reference

Switch back to the reference objective. Match the same image size and pixel size used in the z-stacks. The workflow returns to `home_xy` and the reference Brenner focus, acquires the reference XY image, and validates geometry against the image-to-stage calibration.
```

Code cell stays:

```python
session = wf.measure_parcentricity_reference(session)
print(session)
```

### Step 5: Parcentricity Target And Save

Replace with:

```markdown
## Step 5: Parcentricity target and save

Switch to the target objective. Match the same image size and pixel size used for the reference XY image and the z-stacks. Do not manually refocus with z-wide. The workflow acquires the target XY image at the post-switch XY position, registers it against the reference image, writes the report, and writes a staging config only if the vote is trusted.
```

Code cell stays:

```python
summary = wf.measure_parcentricity_target_and_save(session)
print(summary)
```

## Plan Document Updates

Update `CALIBRATION_NOTEBOOKS_IMPLEMENTATION_PLAN.md` after implementation:

- Section 1: remove any "ref-Brenner subtraction out of scope" language.
- Section 3 / conceptual model: define `focus_z_ref_um`, `focus_z_target_um`, and peak-to-peak `translation_z_um`.
- Section 4 / Z model: remove manual-stepping ownership as the planned approach; state that LAS X owns z-stack setup and notebook triggers/analyzes.
- Section 6 / APIs: `drv.acquire_stack` is now used.
- Section 11 / dataclass: add reference z-stack fields.
- Section 12.5 / `measure_parfocality_reference`: describe reference z-stack acquisition and Brenner peak.
- Section 12.6 / `measure_parfocality_target`: describe target z-stack acquisition and peak-to-peak arithmetic.
- Section 12.7 / `measure_parcentricity_reference`: move to `focus_z_ref_um`.
- Section 14.4 / objective report schema: replace `brenner` with `brenner_ref` and `brenner_target`, add `ref_z_stack`.
- Section 17.2 / notebook 2: update markdown as above.
- Section 22 / key risks: add operator-driven pixel/format matching and stack metadata reliability.

## Tests

Update `test/test_calibration_workflows.py`.

Required tests:

1. `test_objective_pair_parfocality_reference_acquires_z_stack`
   - Ref stack is acquired.
   - `focus_z_ref_um` is set.
   - `ref_z_brenner` and `ref_z_positions_um` are populated.
   - `ref_z_stack/` files exist.

2. `test_objective_pair_z_translation_arithmetic_peak_to_peak`
   - Synthetic ref peak at 100 um.
   - Synthetic target peak at 103 um.
   - Assert `translation_z_um == 3.0`.
   - Assert `motor_shift_z_um + correction_z_um == translation_z_um`.

3. `test_objective_pair_parcentricity_reference_uses_ref_focus_peak`
   - After ref stack, parcentricity reference moves z-wide to `focus_z_ref_um`, not `home_z`.

4. `test_objective_pair_stack_geometry_mismatch_raises`
   - Stack image size or pixel size mismatch raises before Brenner analysis.

5. `test_objective_pair_report_has_ref_and_target_brenner_blocks`
   - Report has `brenner_ref` and `brenner_target`.
   - Report images include both `ref_z_stack` and `target_z_stack`.

6. `test_objective_pair_rerun_2a_wipes_ref_z_stack_dir`
   - Successful run creates `ref_z_stack/`.
   - Rerun Step 2 clears downstream state and removes stale ref stack files.

7. `test_objective_pair_missing_stack_positions_raises`
   - If metadata and override positions are unavailable, workflow raises a clear error.

8. `test_objective_pair_z_stack_requires_at_least_three_slices`
   - Metadata-derived stacks with `sections < 3` raise with a message pointing to the LAS X stack configuration.
   - Explicit `z_positions_um` overrides with fewer than three positions raise before Brenner peak fitting.

Keep existing tests for:

- Weak XY vote blocks config.
- Stale config removal on reruns and exceptions.
- Promotion kind checks.
- Image-to-stage workflow.

Expected test count after implementation: current 40 plus roughly 6-8 new/updated objective-pair tests.

## Implementation Order

1. Add `acquire_stack_to` helper.
2. Add `read_stack_z_positions` helper.
3. Add ref z-stack fields to `ObjectivePairSession`.
4. Add `_clear_parfocality_reference`.
5. Rewrite `measure_parfocality_reference`.
6. Rewrite `measure_parfocality_target` to use `drv.acquire_stack` and peak-to-peak arithmetic.
7. Update `measure_parcentricity_reference` to use `focus_z_ref_um`.
8. Update objective report schema.
9. Update tests.
10. Update `calibrate_objective_pair.ipynb` markdown and parfocality code cells.
11. Update `CALIBRATION_NOTEBOOKS_IMPLEMENTATION_PLAN.md`.

## Acceptance Criteria

- Notebook does not configure z-stack settings through the API.
- Reference and target focus are both Brenner peaks from z-stacks.
- `translation_z_um = focus_z_target_um - focus_z_ref_um`.
- Pixel size and image size are validated for both z-stacks and both XY images.
- Objective report includes both reference and target Brenner curves.
- Production config remains lean and stores only final translation fields plus provenance.
- Existing staging-config safety invariants still hold.
- Unit tests pass.
- Simulator can still run the notebook to the expected report-only path, although synthetic images may not produce meaningful calibration values.
