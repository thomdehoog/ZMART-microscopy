# Calibration Notebook Layout Update Plan

## Purpose

Update the two calibration notebook templates so the operator sees a simple, numbered workflow:

- `calibrate_image_to_stage.ipynb`: three numbered steps plus optional promotion.
- `calibrate_objective_pair.ipynb`: five numbered steps plus optional promotion.

Promotion remains explicit, but it is not a numbered workflow step. It is an optional action after the operator reviews the visual output and summary.

This is a notebook-layout and documentation update only. Do not change workflow logic in `calibration/workflows/`.

## Global Layout Rules

- Every workflow code cell must have a preceding markdown cell.
- Actual workflow cells use `## Step N: <name>`.
- Optional promotion uses `## Optional: promote to live config`, not `Step N`.
- Each code cell calls one workflow function.
- Keep markdown short, practical, and operator-facing.
- Do not put calibration logic in notebook cells.
- Do not add hardcoded machine-specific paths to the notebook templates.

## Bootstrap Rule

Keep a small `_bootstrap.py` next to the canonical notebook templates:

```text
calibration/notebooks/_bootstrap.py
calibration/notebooks/calibrate_image_to_stage.ipynb
calibration/notebooks/calibrate_objective_pair.ipynb
```

The first code cell in each notebook should start with:

```python
import _bootstrap
```

Then it imports the workflow module.

The notebook does NOT need to be copied into a session folder to run.
Runtime output paths come from operator-supplied `SESSIONS_ROOT` and
`LIVE_ROOT` declared at the top of Step 1, not from the notebook's
location on disk. The operator may save a copy of the notebook for
provenance, but that is independent of where acquisition data lands.

`_bootstrap.py` only locates the `navigator_expert` package and prepends
its parent to `sys.path`. It must never choose runtime write paths.

Long term, the cleaner fix is packaging: make `navigator_expert`
installable and use `pip install -e`. That is out of scope for this
notebook layout update.

## Notebook 1: `calibrate_image_to_stage.ipynb`

Logical structure: three numbered steps plus optional promotion.

### Title

```markdown
# Calibrate image_to_stage

Measure the rig's image-to-stage orientation matrix under the reference objective. Run this when microscope/camera geometry changes, or before a new objective-pair calibration campaign.
```

### Operator Preflight

```markdown
## Operator preflight

Select the reference objective in LAS X. Set scan format, zoom, channels, pixel size, and image size. Keep these settings identical for all three acquisitions. Focus with z-wide and keep z-galvo at 0. Confirm `ImageTransformation = TOPLEFT` and that no modal dialogs are open in LAS X.
```

### Step 1: Configure

```markdown
## Step 1: Configure

Set the session id, job name, reference objective label, and stage move distance. This opens the LAS X client, applies stage limits, and creates the session folder. No acquisition happens in this step.
```

Code cell:

```python
import _bootstrap
from navigator_expert.calibration.workflows import image_to_stage as wf

session = wf.start_session(
    session_id="2026-05-22_scope_calibration",
    job_name="Overview",
    reference_objective="10x",
    stage_move_um=40.0,
)
print(session)
```

Note: `stage_move_um=40.0` is useful for the simulator because it moves on a 20 um grid. For real rig validation, choose the value appropriate for the rig.

### Step 2: Run Measurement

```markdown
## Step 2: Run measurement

Acquire and save the home, +X, and +Y raw TIFFs to data/image_to_stage/. The workflow runs voting registration, fits the 2x2 image-to-stage matrix, and snaps it to the nearest D4 orientation. No promotable calibration config is written in this step.
```

Code cell:

```python
session = wf.measure(session)
print(session)
```

### Step 3: Summarize And Save

```markdown
## Step 3: Summarize and save

Render the magenta/green overlays, write the diagnostic report, and write a staging config only if both registrations are trusted and the D4 fit is accepted. Review the summary before promotion.
```

Code cell:

```python
summary = wf.save_and_visualize(session)
print(summary)
```

### Optional Promotion

```markdown
## Optional: promote to live config

Run this only if `summary["config_written"]` is True and the overlays look correct. Promotion copies the staging config into `current_config/`, archives any previous live file, and appends to the promotion log.
```

Code cell:

```python
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name="image_to_stage.json",
)
```

## Notebook 2: `calibrate_objective_pair.ipynb`

Logical structure: five numbered steps plus optional promotion.

The five-step structure is intentional. It maps directly to the operator-visible objective changes and keeps rerun/recovery semantics clear.

### Title

```markdown
# Calibrate objective pair

Measure the absolute translation from one reference objective to one target objective. Production uses the final `translation_xy_um` and `translation_z_um`; the report keeps motor shift and correction values for debugging.
```

### Operator Preflight

```markdown
## Operator preflight

A valid `image_to_stage.json` must already exist in `calibration/current_config/`. If it does not, run `calibrate_image_to_stage.ipynb` first and promote its output, or pass an override path via `image_to_stage_path=` in Step 1. Use the same image size and pixel size as the image-to-stage calibration. The operator changes objectives and microscope settings; the notebook moves XY and z-wide, acquires images, and analyzes results.
```

### Step 1: Configure

```markdown
## Step 1: Configure

Set the session id, job name, reference objective, and target objective. This loads the image-to-stage calibration, opens the LAS X client, applies stage limits, and creates the session folder. No acquisition happens in this step.
```

Code cell:

```python
import _bootstrap
from navigator_expert.calibration.workflows import objective_pair as wf

session = wf.start_session(
    session_id="2026-05-22_scope_calibration",
    job_name="Overview",
    from_objective="10x",
    to_objective="20x",
    image_to_stage_path=None,
)
print(session)
```

### Step 2: Parfocality Reference

```markdown
## Step 2: Parfocality reference

With the reference objective active and focused, record the reference `home_xy` and `home_z`. This step does not acquire an image.
```

Code cell:

```python
session = wf.measure_parfocality_reference(session)
print(session)
```

### Step 3: Parfocality Target

```markdown
## Step 3: Parfocality target

Switch to the target objective in LAS X. Do not adjust z-wide. The workflow acquires a z-wide stack, finds the Brenner focus peak, computes the Z translation, and parks z-wide at the target focus.
```

Code cell:

```python
session = wf.measure_parfocality_target(
    session,
    z_range_um=30.0,
    z_step_um=1.0,
)
print(session)
```

### Step 4: Parcentricity Reference

```markdown
## Step 4: Parcentricity reference

Switch back to the reference objective. The workflow returns to reference `home_xy` and `home_z`, acquires the reference XY image, and validates image size and pixel size against the image-to-stage calibration.
```

Code cell:

```python
session = wf.measure_parcentricity_reference(session)
print(session)
```

### Step 5: Parcentricity Target And Save

```markdown
## Step 5: Parcentricity target and save

Switch to the target objective. Do not adjust z-wide. The workflow acquires the target XY image at the post-switch XY position, registers it against the reference image, writes the report, and writes a staging config only if the vote is trusted.
```

Code cell:

```python
summary = wf.measure_parcentricity_target_and_save(session)
print(summary)
```

### Optional Promotion

```markdown
## Optional: promote to live config

Run this only if `summary["config_written"]` is True and the Brenner curve plus XY overlay look correct. Promotion copies the staging config into `current_config/`, archives any previous live file, and appends to the promotion log.
```

Code cell:

```python
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name=session.objective_config_name,
)
```

## Plan Section 17 Update

Update `CALIBRATION_NOTEBOOKS_IMPLEMENTATION_PLAN.md` Section 17 to document:

- The numbered-step markdown structure.
- The optional promotion section is not a numbered step.
- Runtime output paths come from operator-supplied `SESSIONS_ROOT` and
  `LIVE_ROOT` declared at the top of Step 1. Notebooks do not need to
  be copied into session folders; the operator may save a copy for
  provenance only.

## Implementation Tasks

1. Rewrite `calibration/notebooks/calibrate_image_to_stage.ipynb` to the three-step layout above.
2. Rewrite `calibration/notebooks/calibrate_objective_pair.ipynb` to the five-step layout above.
3. Add `calibration/notebooks/_bootstrap.py`.
4. Update `CALIBRATION_NOTEBOOKS_IMPLEMENTATION_PLAN.md` Section 17.
5. Do not change workflow logic in `calibration/workflows/`.

## Acceptance Checks

- The image-to-stage notebook has exactly three numbered workflow steps.
- The objective-pair notebook has exactly five numbered workflow steps.
- Neither notebook labels promotion as a numbered step.
- Every code cell has a short preceding markdown explanation.
- The first code cell in each notebook imports `_bootstrap`.
- `_bootstrap.py` never chooses runtime write paths; it only locates the `navigator_expert` package on `sys.path`.
- `_bootstrap.py` raises a clearly-worded `RuntimeError` (not a silent failure) if it cannot locate `navigator_expert` by walking up from its own location.
- The workflow modules are untouched.
- A simulator smoke run of each rewritten notebook reaches the "WEAK VOTE / report only / no staging config" path without unhandled exceptions (the expected outcome until the rig pass produces real images).
