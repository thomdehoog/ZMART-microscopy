# Calibration Notebooks Plan

## Goal

Replace the current `calibrate_objectives.py` CLI orchestrator with two thin Jupyter notebooks, each calling a workflow script. The operator drives objective changes, focus, zoom, scan settings, and channels in LAS X; the notebook only commands stage motion, acquires images, analyzes them, and saves results.

The output model is deliberately simple:

- `calibration/sessions/<session_id>/` is staging and visual provenance.
- `calibration/current_config/` is the one live folder production reads from.
- Promotion from staging to live is explicit and audited.

## Design Ethos

- **Lean, simple, fundamentally sound.** If a field, file, or cell does not have a current consumer or prevent a clear failure mode, it does not ship.
- **Thin notebook, fat workflow.** The notebook is markdown plus one function call per code cell. All measurement, I/O, and visualization logic lives in `calibration/workflows/`.
- **Operator vs. notebook split, enforced by API.** Operator owns LAS X objective changes, focus, zoom, scan settings, and channels. Notebook only does stage XY get/move, `read_zwide_um`, z-wide move, acquisition, registration, analysis, save, and promotion.
- **Three concerns separated.** `image_to_stage`, `motor_shift`, and `correction` are independent failure modes. They are measured and reported separately. Production config stores only the final `translation`.
- **Staging vs. live, explicit promotion.** Session folders are staging. `calibration/current_config/` is live. Promotion is its own function call in its own optional cell. No save workflow promotes as a side effect.
- **Production-grade schemas, lean fields.** Config JSONs are versioned and human-readable, but only contain fields needed by production or validation.
- **Notebook = visual provenance; report = machine provenance.** Brenner curves, magenta/green overlays, and numerical summaries render inline. The saved notebook is the human-readable record. Report JSONs are tooling-readable diagnostics. Neither is consumed by production.
- **Trust the operator at the boundary; validate at the API.** The operator's reference focus is the focus anchor. The workflow validates image shape and pixel size before registration. Images must match exactly. v1 does not rescale or auto-compensate.
- **Calibration clarity beats switch minimization.** The 5-cell objective-pair notebook is intentional: parfocality reference, parfocality target, parcentricity reference, parcentricity target. The extra objective switches are acceptable because the measurement and visual output remain easy to understand.

## Conceptual Model

We work in absolute stage coordinates. The reference objective coordinate is the canonical source coordinate. To image a point identified under the reference objective at `P_ref` with a target objective:

```text
P_target = P_ref + translation
```

Calibration measures:

```text
translation = motor_shift + correction
```

- `motor_shift` is what LAS X firmware does automatically on objective switch. It is read from stage XY and z-wide before and after the operator switches objective.
- `correction` is what is still missing after the firmware switch. XY correction is measured by voting registration. The registration API returns image displacement in micrometers; `image_to_stage` maps that image displacement into stage micrometers. Z correction is measured from the Brenner focus peak in a z-wide stack.

Production reads only:

- `current_config/image_to_stage.json`
- `current_config/objective_<from>_to_<to>.json`

Reports keep `motor_shift_*`, `correction_*`, voting diagnostics, and Brenner diagnostics for troubleshooting.

## Z Model

This rig holds z-galvo at 0. All Z motion for this calibration lives on z-wide.

- Read Z with `drv.read_zwide_um(client, job)`.
- Move Z with the z-wide move primitive, for example `drv.move_z(client, target_um, z_mode="zwide")` or the driver equivalent.
- The operator focuses the reference objective via z-wide before the run starts.
- The operator does not manually adjust z-wide on the target side before measurement.
- `z_range_um` must be wide enough to cover the parfocal gap from the firmware's post-switch z-wide to the optical focus.

## Architecture

```text
Notebook
  calls
Workflow script: calibration/workflows/*.py
  uses
Library primitives: calibration/lib/phases.py, calibration/lib/lasx_state.py
  uses
Driver + algorithms: navigator_expert/driver/*, navigator_expert/algorithms/*
  talks to
LAS X
```

The notebook is not self-contained. It imports a workflow module and calls one function per cell.

Registration functions live in `navigator_expert/algorithms/`, where `VOTING_MIN_AGREE`, phase registration, and voting registration already live. Do not introduce a new `calibration/lib/registration.py`.

## File Layout

```text
controller/vendor/leica/navigator_expert/calibration/
  workflows/
    image_to_stage.py
    objective_pair.py
    promotion.py

  lib/
    phases.py
    lasx_state.py

  notebooks/
    calibrate_image_to_stage.ipynb
    calibrate_objective_pair.ipynb

  current_config/
    image_to_stage.json
    objective_10x_to_20x.json
    objective_10x_to_40x.json
    archive/
    .promotion.log

  sessions/
    2026-05-22_scope_calibration/
      configs/
        image_to_stage.json
        objective_10x_to_20x.json
        objective_10x_to_40x.json
      reports/
        image_to_stage_report.json
        objective_10x_to_20x_report.json
        objective_10x_to_40x_report.json
      notebooks/
        calibrate_image_to_stage.ipynb
        calibrate_objective_pair_10x_to_20x.ipynb
        calibrate_objective_pair_10x_to_40x.ipynb
      data/
        image_to_stage/
          home.tif
          plus_x.tif
          plus_y.tif
        objective_10x_to_20x/
          ref_xy.tif
          target_xy.tif
          target_z_stack/
        objective_10x_to_40x/
          ...

  scripts/
    calibrate_objectives.py
```

One session is one calibration campaign. A session can contain the image-to-stage calibration plus multiple reference-to-target objective calibrations from the same sitting.

Each calibration writes to exactly one subfolder pattern:

- Staging config: `sessions/<session_id>/configs/<kind>.json`
- Diagnostic report: `sessions/<session_id>/reports/<kind>_report.json`
- Raw data: `sessions/<session_id>/data/<kind>/`
- Saved notebook copy: `sessions/<session_id>/notebooks/<notebook_name>.ipynb`

Production never reads from `sessions/`. Production reads only from `calibration/current_config/`.

**Template-to-session step (operator, manual).** Before running a notebook, the operator copies the canonical template from `calibration/notebooks/<name>.ipynb` into `sessions/<session_id>/notebooks/`. Re-runs within the same campaign edit the session copy in place. Production never reads from `calibration/notebooks/` -- it is purely the operational starting point.

## API Connection

`start_session()` opens the LAS X Python client and reads hardware once per notebook run:

```python
import navigator_expert.driver as drv

client = drv.connect_python_client()
drv.apply_stage_limits_from_config(drv.load_stage_config())
hw = drv.get_hardware_info(client)
```

This follows the pattern in `calibrate_objectives.py:step_setup`. The notebook never touches the client directly. The client lives on the session object returned by the workflow.

Run environment: notebooks are launched from `C:\ProgramData\MinicondaZMB\home\t.de\` with the MinicondaZMB environment active. No environment variables and no CLI flags are required.

## Notebook 1: `calibrate_image_to_stage.ipynb`

Purpose: measure the pixel-to-stage mapping under the reference objective. This notebook is run rarely, usually before objective-pair calibration or after microscope/camera geometry changes.

### Cell 1: Config + Open Session

```python
from navigator_expert.calibration.workflows import image_to_stage as wf

session = wf.start_session(
    session_id="2026-05-22_scope_calibration",
    job_name="Overview",
    reference_objective="10x",
    stage_move_um=30.0,
)
print(session)
```

`start_session` opens the LAS X client, validates the job, creates:

- `sessions/<session_id>/configs/`
- `sessions/<session_id>/reports/`
- `sessions/<session_id>/notebooks/`
- `sessions/<session_id>/data/image_to_stage/`

It returns an `ImageToStageSession` dataclass.

### Markdown: Operator Instructions

> Select the reference objective in LAS X. Set the final scan format, scan speed, zoom, pixel size, image size, and channels you want for all three calibration images. Focus on a region with stable texture. Confirm `ImageTransformation = TOPLEFT` and no modal dialogs. The pixel size and image size must stay exactly the same for all images. Run the next cell.

### Cell 2: Measure

```python
session = wf.measure(session)
print(session)
```

`measure` does:

1. Acquire `home`.
2. Move stage `stage_move_um` in X.
3. Acquire `plus_x`.
4. Move back to home.
5. Move stage `stage_move_um` in Y.
6. Acquire `plus_y`.
7. Move back to home.

Images are saved to `sessions/<session_id>/data/image_to_stage/`.

The workflow validates that all three images have the same image size and pixel size. A mismatch raises an error. No rescaling is performed in v1.

The workflow runs voting registration for:

- `home` vs. `plus_x`
- `home` vs. `plus_y`

It fits a 2x2 image-to-stage matrix, snaps to the nearest D4 orientation, and stores `residual_from_d4` (Frobenius norm of the raw fitted stage-um-per-image-um matrix vs. the snapped D4 matrix) on the session. If `residual_from_d4` exceeds `D4_RESIDUAL_MAX` (existing constant in the algorithms module), the workflow raises -- the calibration is too far from a valid orientation to trust.

Voting agreement is recorded per registration in the report. If voting agreement falls below `VOTING_MIN_AGREE`, the workflow saves the report and visual output but does not write `configs/image_to_stage.json`. A promotable config is only written when the registration is trusted.

### Cell 3: Visualize + Save Staging

```python
summary = wf.save_and_visualize(session)
print(summary)
```

Renders magenta/green overlays inline for:

- `home` vs. `plus_x`
- `home` vs. `plus_y`

Saves diagnostic output:

- `sessions/<session_id>/reports/image_to_stage_report.json`

If the D4 residual is accepted and both voting registrations are trusted, also saves:

- `sessions/<session_id>/configs/image_to_stage.json`

Does not promote.

### Markdown: Review + Optional Promotion

> Review the overlays and residuals above. If accepted, run the next cell to promote this calibration to the live config. Otherwise stop here; the staging files remain in the session folder.

### Cell 4 Optional: Promote

```python
from pathlib import Path
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name="image_to_stage.json",
    live_path=Path("calibration/current_config/image_to_stage.json"),
)
```

Promotion copies the staging config into `current_config/`, archives any previous live file, and appends to `.promotion.log`.

## Notebook 2: `calibrate_objective_pair.ipynb`

Purpose: measure one reference-to-target objective translation. One notebook execution produces one objective-pair config, for example `objective_10x_to_20x.json`.

The notebook has five measurement-bearing cells:

1. Config
2. Parfocality reference
3. Parfocality target
4. Parcentricity reference
5. Parcentricity target + save

This phenomenon-grouped structure is intentional. The operator switches objective between 2a and 2b, between 2b and 3a, and between 3a and 3b. The extra switches are accepted because the notebook output remains easier to understand and rerun.

### Cell 1: Config + Open Session

```python
from navigator_expert.calibration.workflows import objective_pair as wf

session = wf.start_session(
    session_id="2026-05-22_scope_calibration",
    job_name="Overview",
    from_objective="10x",
    to_objective="20x",
    image_to_stage_path=None,  # default: calibration/current_config/image_to_stage.json
)
print(session)
```

`start_session` opens the LAS X client, loads `image_to_stage` from `calibration/current_config/image_to_stage.json` unless an explicit session path is supplied for testing, and creates:

- `sessions/<session_id>/configs/`
- `sessions/<session_id>/reports/`
- `sessions/<session_id>/notebooks/`
- `sessions/<session_id>/data/objective_10x_to_20x/`

The workflow validates that future registration images match the `image_size_px` and `pixel_size_um` stored in `image_to_stage.json`. If the resolved `image_to_stage` path does not exist (typically because Notebook 1 was never run on this rig), `start_session` raises with a clear message pointing the operator at Notebook 1.

### Markdown: Parfocality Reference

> Select the reference objective in LAS X. Set scan format, channels, zoom, pixel size, and image size. Focus the reference via z-wide. Pixel size and image size must match the image-to-stage calibration. Run the next cell.

### Cell 2a: Parfocality Reference

```python
session = wf.measure_parfocality_reference(session)
print(session)
```

Records:

- `home_xy` from stage XY readback
- `home_z` from `drv.read_zwide_um(client, job)`

No image is required in this cell.

### Markdown: Parfocality Target

> Switch to the target objective in LAS X. Set the target scan format, channels, zoom, pixel size, and image size. The pixel size and image size must match the reference acquisition and the image-to-stage calibration. Do not adjust z-wide before running the next cell; the z-stack measures the parfocal gap. If the parfocal gap is large, increase `z_range_um`.

### Cell 2b: Parfocality Target + Z Curve

```python
session = wf.measure_parfocality_target(
    session,
    z_range_um=30.0,
    z_step_um=1.0,
)
print(session)
```

The workflow:

1. Reads `z_post = drv.read_zwide_um(client, job)`.
2. Computes `motor_shift_z_um = z_post - home_z`.
3. Sweeps z-wide around `z_post` using `z_range_um` and `z_step_um`.
4. Acquires the z-stack into `sessions/<session_id>/data/objective_10x_to_20x/target_z_stack/`.
5. Computes the Brenner focus curve.
6. Finds `focus_z_target_um`.
7. Computes `correction_z_um = focus_z_target_um - z_post`.
8. Computes `translation_z_um = motor_shift_z_um + correction_z_um`, equivalent to `focus_z_target_um - home_z`.
9. Parks z-wide at `focus_z_target_um` for the target objective.
10. Renders the Brenner curve with the peak marker inline.

### Markdown: Parcentricity Reference

> Switch back to the reference objective in LAS X. Confirm the same image size and pixel size. Run the next cell.

### Cell 3a: Parcentricity Reference

```python
session = wf.measure_parcentricity_reference(session)
print(session)
```

The workflow:

1. Moves stage XY to `home_xy`.
2. Moves z-wide to `home_z`.
3. Acquires `ref_xy`.
4. Saves `sessions/<session_id>/data/objective_10x_to_20x/ref_xy.tif`.
5. Validates image size and pixel size against `image_to_stage.json`.

### Markdown: Parcentricity Target

> Switch to the target objective in LAS X. Image size and pixel size must match the reference acquisition and the image-to-stage calibration. Do not adjust z-wide. Run the next cell.

### Cell 3b: Parcentricity Target + XY Overlay + Save

```python
summary = wf.measure_parcentricity_target_and_save(session)
print(summary)
```

The workflow:

1. Reads `xy_post` from stage XY readback.
2. Computes `motor_shift_xy_um = xy_post - home_xy`.
3. Moves z-wide to `home_z + translation_z_um`, so the target objective is in focus.
4. Acquires `target_xy` at the post-switch XY position. It does not return to `home_xy`.
5. Saves `sessions/<session_id>/data/objective_10x_to_20x/target_xy.tif`.
6. Validates image size and pixel size against `ref_xy` and `image_to_stage.json`.
7. Runs voting registration for `ref_xy` vs. `target_xy`.
8. Converts the registered image shift in micrometers into stage micrometers with `image_to_stage`.
9. Computes `correction_xy_um`.
10. Computes `translation_xy_um = motor_shift_xy_um + correction_xy_um`.
11. Renders magenta/green overlay inline.
12. Saves `sessions/<session_id>/reports/objective_10x_to_20x_report.json`.
13. If voting is trusted, saves `sessions/<session_id>/configs/objective_10x_to_20x.json`.

The printed summary includes `motor_shift_xy_um`, `correction_xy_um`, `translation_xy_um`, and `voting_agreement`. If voting agreement falls below `VOTING_MIN_AGREE`, the workflow saves the report and visual output but does not write `configs/objective_10x_to_20x.json`. A promotable config is only written when the registration is trusted.

Does not promote.

### Markdown: Review + Optional Promotion

> Review the Brenner curve, XY overlay, and numerical summary above. If accepted, run the next cell to promote this objective-pair calibration to the live config.

### Cell 4 Optional: Promote

```python
from pathlib import Path
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name="objective_10x_to_20x.json",
    live_path=Path("calibration/current_config/objective_10x_to_20x.json"),
)
```

## Workflow API

### Shared Session Paths

Each workflow session should expose resolved output paths so implementation cannot accidentally write flat files into `sessions/<session_id>/`.

```python
@dataclass
class SessionPaths:
    session_dir: Path          # sessions/<session_id>/
    configs_dir: Path          # sessions/<session_id>/configs/
    reports_dir: Path          # sessions/<session_id>/reports/
    notebooks_dir: Path        # sessions/<session_id>/notebooks/
    data_dir: Path             # sessions/<session_id>/data/<kind>/
```

### `calibration/workflows/image_to_stage.py`

```python
@dataclass
class ImageToStageSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    reference_objective: str
    stage_move_um: float
    image_size_px: tuple[int, int] | None
    pixel_size_um: float | None
    home_xy: tuple[float, float] | None
    images: dict[str, np.ndarray]
    image_to_stage: np.ndarray | None
    residual_from_d4: float | None       # Frobenius norm vs snapped D4; raises above D4_RESIDUAL_MAX

def start_session(
    session_id: str,
    job_name: str,
    reference_objective: str,
    stage_move_um: float,
) -> ImageToStageSession: ...

def measure(session: ImageToStageSession) -> ImageToStageSession: ...
def save_and_visualize(session: ImageToStageSession) -> dict: ...
```

### `calibration/workflows/objective_pair.py`

```python
@dataclass
class ObjectivePairSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    from_objective: str
    to_objective: str
    objective_config_name: str                 # objective_10x_to_20x.json
    image_to_stage_path: Path
    image_to_stage: np.ndarray
    image_to_stage_image_size_px: tuple[int, int]
    image_to_stage_pixel_size_um: float
    home_xy: tuple[float, float] | None
    home_z: float | None
    ref_image: np.ndarray | None
    target_z_stack: list[np.ndarray] | None
    target_image: np.ndarray | None
    motor_shift_xy_um: tuple[float, float] | None
    motor_shift_z_um: float | None
    correction_xy_um: tuple[float, float] | None
    correction_z_um: float | None
    translation_xy_um: tuple[float, float] | None
    translation_z_um: float | None

def start_session(
    session_id: str,
    job_name: str,
    from_objective: str,
    to_objective: str,
    image_to_stage_path: Path | None = None,  # default = calibration/current_config/image_to_stage.json
) -> ObjectivePairSession: ...

def measure_parfocality_reference(session: ObjectivePairSession) -> ObjectivePairSession: ...
def measure_parfocality_target(
    session: ObjectivePairSession,
    z_range_um: float,
    z_step_um: float,
) -> ObjectivePairSession: ...
def measure_parcentricity_reference(session: ObjectivePairSession) -> ObjectivePairSession: ...
def measure_parcentricity_target_and_save(session: ObjectivePairSession) -> dict: ...
```

### `calibration/workflows/promotion.py`

```python
def promote_calibration(session, staging_name: str, live_path: Path) -> None:
    """Validate staging JSON, archive existing live file, copy staging to live,
    and append to current_config/.promotion.log."""
```

The promotion function reads from `session.paths.configs_dir / staging_name`. It never reads from `reports/` or `data/`.

## JSON Schemas

### `image_to_stage.json`

Same shape in staging and live:

```json
{
  "schema_version": 1,
  "kind": "image_to_stage",
  "created_at": "2026-05-22T14:30:00+02:00",
  "reference_objective": "10x",
  "image_size_px": [1024, 1024],
  "pixel_size_um": 1.234,
  "image_to_stage": [[0.0, -1.0], [1.0, 0.0]]
}
```

`image_to_stage` maps image displacement in micrometers to stage displacement in micrometers. `image_size_px` and `pixel_size_um` are validation metadata. Every workflow and production consumer that uses this config must verify exact match before using registration results. v1 does not rescale.

### `objective_<from>_to_<to>.json`

Same shape in staging and live:

```json
{
  "schema_version": 1,
  "kind": "objective_translation",
  "created_at": "2026-05-22T15:10:00+02:00",
  "from_objective": "10x",
  "to_objective": "20x",
  "translation_xy_um": [-6.46, 21.54],
  "translation_z_um": 2.40
}
```

This is the only per-objective file production needs. Runtime use:

```text
P_target = P_ref + translation
```

### `image_to_stage_report.json`

Diagnostic only:

Paths in reports are relative to the session root (`sessions/<session_id>/`).

```json
{
  "schema_version": 1,
  "kind": "image_to_stage_report",
  "created_at": "2026-05-22T14:30:00+02:00",
  "calibration_file": "image_to_stage.json",
  "stage_move_um": 30.0,
  "image_size_px": [1024, 1024],
  "pixel_size_um": 1.234,
  "images": {
    "home": "data/image_to_stage/home.tif",
    "plus_x": "data/image_to_stage/plus_x.tif",
    "plus_y": "data/image_to_stage/plus_y.tif"
  },
  "registrations": {
    "home_to_plus_x": {
      "image_shift_um": [24.3, -0.2],
      "voting_agreement": 4
    },
    "home_to_plus_y": {
      "image_shift_um": [0.1, 24.5],
      "voting_agreement": 4
    }
  },
  "residual_from_d4": 0.018
}
```

`residual_from_d4` is the Frobenius norm of the raw fitted image-to-stage matrix minus the snapped D4 matrix. The workflow raises if it exceeds `D4_RESIDUAL_MAX` because the calibration is too far from a valid orientation. Voting agreement is per-registration; below `VOTING_MIN_AGREE`, the workflow saves report/visual diagnostics but does not write a promotable config.

### `objective_<from>_to_<to>_report.json`

Diagnostic only:

Paths in reports are relative to the session root (`sessions/<session_id>/`).

```json
{
  "schema_version": 1,
  "kind": "objective_translation_report",
  "created_at": "2026-05-22T15:10:00+02:00",
  "calibration_file": "objective_10x_to_20x.json",
  "image_to_stage_file": "calibration/current_config/image_to_stage.json",
  "motor_shift_xy_um": [-7.02, 21.07],
  "motor_shift_z_um": -6.11,
  "correction_xy_um": [0.56, 0.47],
  "correction_z_um": 8.51,
  "translation_xy_um": [-6.46, 21.54],
  "translation_z_um": 2.40,
  "voting_agreement": 4,
  "brenner_peak_z_um": 12.40,
  "images": {
    "ref_xy": "data/objective_10x_to_20x/ref_xy.tif",
    "target_xy": "data/objective_10x_to_20x/target_xy.tif",
    "target_z_stack": "data/objective_10x_to_20x/target_z_stack/"
  }
}
```

## Promotion Semantics

`promote_calibration(session, staging_name, live_path)`:

- Source: `sessions/<session_id>/configs/<staging_name>`
- Target: `calibration/current_config/<staging_name>`

Steps:

1. Read staging JSON from `session.paths.configs_dir / staging_name`.
2. Validate against the schema implied by `kind`.
3. If `live_path` already exists, copy it to `calibration/current_config/archive/<timestamp>_<staging_name>`.
4. Copy staging JSON to `live_path`.
5. Append a line to `calibration/current_config/.promotion.log`.

Example log line:

```text
2026-05-22T13:10:04Z image_to_stage 2026-05-22_scope_calibration -> calibration/current_config/image_to_stage.json
```

Promotion is an explicit notebook cell. There is no default live path on save workflows, and saving staging files cannot activate a calibration.

## What Changes vs. `calibrate_objectives.py`

| Area | Old | New |
| --- | --- | --- |
| Orchestration | CLI script | Two notebooks plus workflow modules |
| Live config | One multi-slot `config.json` | One live folder: `calibration/current_config/` |
| Staging | Timestamped runs | One campaign session with `configs/`, `reports/`, `data/`, `notebooks/` |
| Production fields | Mixed measured/intermediate values | Production reads only `image_to_stage` and `translation_*` |
| Diagnostics | Mixed into config | Separate report JSONs |
| XY method | Previous script behavior | Stay at post-switch XY, register, then sum `motor_shift_xy + correction_xy` |
| Z method | Ref-Brenner subtraction | Operator ref focus is anchor; target Brenner peak gives translation |
| Pixel size | Read during acquisition; weak consumer validation | Stored in `image_to_stage.json`; exact validation before registration |
| Registration | Voting registration | Voting registration kept |
| Promotion | Writing config can make it live | Explicit promotion to `current_config/` |

## Open Questions for Reviewers

1. **Raw data format.** Save acquisitions as TIFF for inspectability, NumPy `.npy` for fast exact reload, or both?
2. **Z-stack memory.** A 60 um z-stack at 1 um steps is 61 images. Should acquisition stream-write during the stack instead of holding everything in memory?
3. **Promotion archive depth.** Keep all archived live files forever, or rotate after a fixed count?
4. **Image-to-stage robustness.** Voting registration uses the existing ensemble. For large known stage moves under the reference objective, is a simpler single registration method sufficient, or should voting remain mandatory?
5. **Cell 2a vs. Cell 3a redundancy.** Cell 2a records `home_xy` and `home_z`; Cell 3a moves back to them before acquiring the reference XY image. This is defensive against reverse-switch drift. Confirm that this explicit move is desired.
