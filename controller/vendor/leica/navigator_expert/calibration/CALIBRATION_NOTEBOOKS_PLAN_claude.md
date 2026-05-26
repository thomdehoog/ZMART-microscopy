# Calibration Notebooks: Implementation Plan (claude)

Self-contained, implementation-grade plan for the two calibration notebooks and the workflow scripts they call. Written so an implementer can build it without re-deriving any decisions made in earlier review rounds.

---

## 1. Scope and Non-Goals

**In scope (v1):**

- Two thin Jupyter notebooks driving stage motion + acquisition + analysis.
- Three new workflow modules under `calibration/workflows/`.
- Schemas for two production configs and two diagnostic reports.
- Explicit promotion from session staging to `calibration/current_config/`.
- Validation of pixel size and image size at every consumer.

**Out of scope (v1):**

- Image rescaling / pixel-size compensation. A mismatch is an error.
- Multi-job image-to-stage. One global matrix for the rig.
- Auto-promotion. The operator promotes; the workflows never do.
- Replacing the existing `calibrate_objectives.py`. It stays as a script during the transition and is retired in a separate change.

---

## 2. Design Ethos (Operative)

1. **Lean and load-bearing.** A field, file, or cell that has no current consumer and prevents no clear failure mode does not ship.
2. **Thin notebook, fat workflow.** Each notebook cell is markdown + one function call. No analysis logic in the notebook.
3. **Operator vs. notebook split, enforced.** Operator owns LAS X (objective, focus, zoom, scan, channels). The notebook only does stage XY get/move, `read_zwide_um`, z-wide move, acquisition, registration, save, and explicit promotion.
4. **Three concerns separated.** `image_to_stage`, `motor_shift`, `correction` are independent. Production stores only `translation = motor_shift + correction`.
5. **Staging vs. live, explicit promotion.** Session folders are staging. `calibration/current_config/` is live. Promotion is a separate function call in its own optional cell.
6. **Production-grade schemas, lean fields.** Config JSONs are versioned and self-describing, with only fields production reads or validates.
7. **Notebook = visual provenance; report = machine provenance.** Inline visuals are for humans. Reports are for tooling. Neither is consumed by production.
8. **Trust the operator at the boundary; validate at the API.** Operator focuses the reference. Workflows validate image shape and pixel size before registration and raise on mismatch. No rescaling.
9. **Calibration clarity beats switch minimization.** The 5-cell objective notebook is intentional. Three operator switches is acceptable.

---

## 3. Conceptual Model

We work in **absolute stage coordinates**. The reference objective coordinate is the canonical source frame. To image a point identified under the reference objective at `P_ref` with a target objective:

```
P_target = P_ref + translation
```

Calibration measures:

```
translation = motor_shift + correction
```

- `motor_shift` is what LAS X firmware applies automatically on objective switch. Measured by reading stage XY and z-wide before and after the operator switches objective.
- `correction` is what is still missing after the firmware switch. Measured at the post-switch stage position (no return to home). XY: voting registration of ref image vs. target image, converted from image-um to stage-um through `image_to_stage`. Z: Brenner peak of a z-wide stack relative to the post-switch z-wide.

Production reads only:

- `current_config/image_to_stage.json` (per rig)
- `current_config/objective_<from>_to_<to>.json` (per pair)

Reports keep `motor_shift_*`, `correction_*`, voting diagnostics, and Brenner diagnostics for troubleshooting.

---

## 4. Z Model

This rig holds z-galvo at 0 throughout calibration. All Z motion is on z-wide.

- Read: `drv.read_zwide_um(client, job_name)`
- Move: `drv.move_z(client, target_um, z_mode="zwide")`
- The operator focuses the reference objective via z-wide before the run starts.
- The operator does **not** manually adjust z-wide on the target side before measurement.
- `z_range_um` (per-call) must cover the parfocal gap from the firmware's post-switch z-wide to the optical focus.

---

## 5. Units

Make units explicit at every layer; this is the most common source of bugs.

| Quantity | Units | Notes |
| --- | --- | --- |
| Stage XY position | um (absolute) | from `drv.get_xy` |
| Stage Z (z-wide) position | um (absolute) | from `drv.read_zwide_um` |
| Pixel size | um per pixel | from job geometry |
| Image size | pixels (W, H) | from job geometry |
| Voting registration output | pixels (signed) | a thin workflow wrapper multiplies by `pixel_size_um` to produce image-um |
| Image displacement in image-frame | um | wrapper output |
| `image_to_stage` matrix | dimensionless (stage-um / image-um) | 2x2 rotation/reflection, elements in {-1, 0, +1} |
| `residual_from_d4` | dimensionless | Frobenius norm of (fitted - snapped) |
| `motor_shift_xy_um`, `correction_xy_um`, `translation_xy_um` | stage-um | 2-vector |
| `motor_shift_z_um`, `correction_z_um`, `translation_z_um` | um | scalar |
| `brenner_peak_z_um` | um (absolute z-wide) | scalar |

**Conversion path for XY correction:**

```
pixel_shift -> image_um_shift = pixel_shift * pixel_size_um
image_um_shift -> stage_um_shift = image_to_stage @ image_um_shift
```

`image_to_stage` is a pure rotation/reflection (one of the eight D4 elements). Its job is orientation, not scaling. Scaling lives in `pixel_size_um`.

---

## 6. Architecture

```
Notebook (1 function call per code cell)
  -> Workflow (calibration/workflows/*.py)
       -> Library primitives (calibration/lib/*.py, lightly modified)
            -> Driver + algorithms (navigator_expert/driver/*, navigator_expert/algorithms/*)
                 -> LAS X Python client
```

The notebook imports a workflow module and calls one function per cell. The workflow owns the LAS X client (on the session object), all file I/O, all visualization, and all schema construction. Library primitives do the measurement math. The driver talks to LAS X.

No new module is introduced under `calibration/lib/`. Registration lives in `navigator_expert/algorithms/`.

---

## 7. File Layout

```
controller/vendor/leica/navigator_expert/calibration/

  workflows/                              # NEW
    __init__.py
    image_to_stage.py                     # ImageToStageSession, start_session, measure, save_and_visualize
    objective_pair.py                     # ObjectivePairSession, start_session, measure_* (5), save inside last cell
    promotion.py                          # promote_calibration
    _common.py                            # SessionPaths, JSON helpers, validation helpers, viz helpers

  lib/                                    # EXISTING, minor edits
    phases.py                             # only shift_xy path needs the new "stay at post-switch" semantics if reused
    lasx_state.py                         # unchanged

  notebooks/                              # canonical templates
    calibrate_image_to_stage.ipynb
    calibrate_objective_pair.ipynb

  current_config/                         # LIVE -- production reads from here only
    image_to_stage.json
    objective_<from>_to_<to>.json (per pair)
    archive/<timestamp>_<name>.json
    .promotion.log

  sessions/                               # STAGING -- one folder per calibration campaign
    <session_id>/
      configs/<kind>.json                 # written only when registration is trusted
      reports/<kind>_report.json          # always written
      notebooks/<name>.ipynb              # operator-copied snapshot
      data/<kind>/...                     # raw TIFFs and z-stacks per calibration

  scripts/
    calibrate_objectives.py               # DEPRECATED -- removed in a separate change
```

**Kind labels** used to derive subfolders, filenames, and report fields:

- `image_to_stage`
- `objective_<from>_to_<to>`, e.g. `objective_10x_to_20x`

**Template-to-session step (manual).** The operator copies the canonical template from `calibration/notebooks/<name>.ipynb` into `sessions/<session_id>/notebooks/` before running. Production never reads from `calibration/notebooks/`.

---

## 8. Constants

Defined in `navigator_expert/algorithms/` (existing) or `calibration/workflows/_common.py` (new):

| Name | Value | Source |
| --- | --- | --- |
| `VOTING_MIN_AGREE` | from existing algorithms module | existing |
| `D4_RESIDUAL_MAX` | from existing algorithms module | existing |
| `CALIBRATION_ROOT_DEFAULT` | `Path(__file__).resolve().parents[1]` (the calibration/ folder) | new, in `_common.py` |
| `SCHEMA_VERSION` | `1` | new |

No new tunables are introduced. Z-stack and stage-move sizes are notebook-cell arguments.

---

## 9. Workflow API

### 9.1 `SessionPaths`

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SessionPaths:
    session_dir: Path     # sessions/<session_id>/
    configs_dir: Path     # sessions/<session_id>/configs/
    reports_dir: Path     # sessions/<session_id>/reports/
    notebooks_dir: Path   # sessions/<session_id>/notebooks/
    data_dir: Path        # sessions/<session_id>/data/<kind>/

    @classmethod
    def create(cls, calibration_root: Path, session_id: str, kind: str) -> "SessionPaths":
        session_dir = calibration_root / "sessions" / session_id
        paths = cls(
            session_dir=session_dir,
            configs_dir=session_dir / "configs",
            reports_dir=session_dir / "reports",
            notebooks_dir=session_dir / "notebooks",
            data_dir=session_dir / "data" / kind,
        )
        for p in (paths.configs_dir, paths.reports_dir,
                  paths.notebooks_dir, paths.data_dir):
            p.mkdir(parents=True, exist_ok=True)
        return paths
```

Idempotent. Multiple workflows in one campaign share the same `session_dir` and write to disjoint `data/<kind>/` subfolders.

### 9.2 `image_to_stage.py`

```python
@dataclass
class ImageToStageSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    hw: dict
    reference_objective: str          # operator-supplied label
    reference_objective_slot: int     # resolved from hw
    stage_move_um: float
    pixel_size_um: float              # from job geometry
    image_size_px: tuple[int, int]    # from job geometry, (W, H)
    home_xy: tuple[float, float] | None = None
    images: dict[str, np.ndarray] = field(default_factory=dict)
    registrations: dict[str, dict] = field(default_factory=dict)
    image_to_stage: np.ndarray | None = None       # 2x2 dimensionless
    matrix_label: str | None = None                # D4 element name
    residual_from_d4: float | None = None          # dimensionless, raises above D4_RESIDUAL_MAX
    trusted: bool = False

def start_session(
    session_id: str,
    job_name: str,
    reference_objective: str,
    stage_move_um: float,
    calibration_root: Path = CALIBRATION_ROOT_DEFAULT,
) -> ImageToStageSession: ...

def measure(session: ImageToStageSession) -> ImageToStageSession: ...

def save_and_visualize(session: ImageToStageSession) -> dict: ...
```

### 9.3 `objective_pair.py`

```python
@dataclass
class ObjectivePairSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    hw: dict
    from_objective: str
    to_objective: str
    from_objective_slot: int
    to_objective_slot: int
    kind: str                            # f"objective_{from}_to_{to}"
    objective_config_name: str           # f"{kind}.json"
    image_to_stage_path: Path
    image_to_stage: np.ndarray           # 2x2 dimensionless, loaded
    image_to_stage_image_size_px: tuple[int, int]
    image_to_stage_pixel_size_um: float
    home_xy: tuple[float, float] | None = None
    home_z: float | None = None
    ref_image: np.ndarray | None = None
    target_z_stack: list[np.ndarray] | None = None
    target_image: np.ndarray | None = None
    motor_shift_xy_um: tuple[float, float] | None = None
    motor_shift_z_um: float | None = None
    correction_xy_um: tuple[float, float] | None = None
    correction_z_um: float | None = None
    translation_xy_um: tuple[float, float] | None = None
    translation_z_um: float | None = None
    brenner_peak_z_um: float | None = None
    voting_agreement: int | None = None
    trusted: bool = False

def start_session(
    session_id: str,
    job_name: str,
    from_objective: str,
    to_objective: str,
    image_to_stage_path: Path | None = None,  # default: calibration/current_config/image_to_stage.json
    calibration_root: Path = CALIBRATION_ROOT_DEFAULT,
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

### 9.4 `promotion.py`

```python
def promote_calibration(session, staging_name: str, live_path: Path) -> None:
    """Validate staging JSON, archive any existing live file, copy staging to live,
    and append to current_config/.promotion.log. Raises FileNotFoundError if the
    staging file does not exist (e.g., voting was below threshold and the
    workflow did not write a promotable config)."""
```

### 9.5 `_common.py` helpers (sketch)

```python
def now_iso() -> str: ...
def read_json(path: Path) -> dict: ...
def write_json_atomic(data: dict, path: Path) -> None: ...
def save_image_tiff(arr: np.ndarray, path: Path) -> None: ...
def validate_image_geometry(
    images: dict[str, np.ndarray],
    expected_size_px: tuple[int, int],
    expected_pixel_size_um: float,
    measured_pixel_size_um: float,
) -> None: ...
def magenta_green_overlay(a: np.ndarray, b: np.ndarray) -> Figure: ...
def render_brenner_curve(z: np.ndarray, scores: np.ndarray, peak_z: float) -> Figure: ...
def slot_for_label(hw: dict, label: str) -> int: ...
def active_objective_slot(client) -> int: ...
def assert_active_slot(client, expected_slot: int, expected_label: str) -> None: ...
```

`write_json_atomic` writes to `path.tmp` then renames; no partial writes.

---

## 10. Workflow Step-by-Step

### 10.1 `image_to_stage.start_session`

1. Connect LAS X client: `client = drv.connect_python_client()`.
2. Apply stage limits: `drv.apply_stage_limits_from_config(drv.load_stage_config())`.
3. Read hardware: `hw = drv.get_hardware_info(client)`.
4. Validate the operator-supplied `reference_objective` matches the LAS X active slot:
   - `assert_active_slot(client, slot_for_label(hw, reference_objective), reference_objective)`
5. Read job geometry: `geo = drv.parse_tile_geometry(drv.get_job_settings(client, job_name))`.
6. Extract `pixel_size_um = float(geo["pixel_w_um"])` and `image_size_px = (W, H)` from the job.
7. Create paths: `paths = SessionPaths.create(calibration_root, session_id, "image_to_stage")`.
8. Build and return the session dataclass.

### 10.2 `image_to_stage.measure`

1. Read `home_xy = drv.get_xy(client)` (convert to `(x_um, y_um)` floats). Store on session.
2. Acquire `home` image. Save TIFF to `paths.data_dir / "home.tif"`. Store in `session.images`.
3. Move stage +X by `stage_move_um`: `drv.move_xy_stage(client, x + dx, y, unit="um")`.
4. Acquire `plus_x`. Save TIFF.
5. Move back to `home_xy`.
6. Move stage +Y by `stage_move_um`.
7. Acquire `plus_y`. Save TIFF.
8. Move back to `home_xy`.
9. Validate image geometry across the three images (same shape, same pixel size as session). Raise on mismatch.
10. Run voting registration:
    - `shift_x_px, vote_x = algos.register_voting(home, plus_x)`
    - `shift_y_px, vote_y = algos.register_voting(home, plus_y)`
11. Convert to image-um: `shift_x_um = shift_x_px * pixel_size_um`, same for y.
12. Store registrations dict: `{"home_to_plus_x": {"image_shift_um": [...], "voting_agreement": v}, "home_to_plus_y": {...}}`.
13. Fit the 2x2 image-to-stage matrix.

    Let `M_stage_to_image_um` be the matrix whose columns are the measured image-um shifts per unit stage-um move:

    ```
    M_stage_to_image_um = [[shift_x_um[0]/stage_move_um, shift_y_um[0]/stage_move_um],
                           [shift_x_um[1]/stage_move_um, shift_y_um[1]/stage_move_um]]
    ```

    Then the fitted image-to-stage (dimensionless) is:

    ```
    image_to_stage_fitted = -inv(M_stage_to_image_um)
    ```

    Sign convention: matches the existing `phases.py:measure_sign_convention`. Re-use that function if reasonable; if not, replicate the formula and add a unit test.

14. Snap to D4: `label, canonical, residual = algos.classify_d4(image_to_stage_fitted)`. Store all three on session.
15. If `residual > D4_RESIDUAL_MAX`, raise `RuntimeError` with a clear message (drift, sparse texture, or too small a move).
16. Set `session.trusted = (vote_x >= VOTING_MIN_AGREE and vote_y >= VOTING_MIN_AGREE)`.
17. Return the session.

### 10.3 `image_to_stage.save_and_visualize`

1. Render and `display(...)` two magenta/green overlays (`home`-vs-`plus_x`, `home`-vs-`plus_y`).
2. Build the report dict (see schema in section 11.3). Write to `paths.reports_dir / "image_to_stage_report.json"` atomically. Always written.
3. If `session.trusted`, build the calibration dict (see schema in 11.1) and write to `paths.configs_dir / "image_to_stage.json"` atomically.
4. If not trusted, do not write the staging config. The summary text makes the reason explicit.
5. Return a summary dict containing: `session_id`, `matrix_label`, `residual_from_d4`, `registrations`, `trusted`, `status` (human-readable), and `configs_dir`/`reports_dir` for the operator's convenience.

### 10.4 `objective_pair.start_session`

1. Resolve `image_to_stage_path`. Default: `calibration_root / "current_config" / "image_to_stage.json"`.
2. If the file does not exist: `raise FileNotFoundError(f"image_to_stage.json not found at {path}. Run calibrate_image_to_stage.ipynb first and promote its output.")`.
3. Read and parse `image_to_stage.json`. Extract `image_to_stage` matrix, `image_size_px`, `pixel_size_um`.
4. Connect client, apply stage limits, read hardware (same as 10.1).
5. Resolve `from_objective_slot` and `to_objective_slot` via `slot_for_label`.
6. Read job geometry. Compare `pixel_size_um` and `image_size_px` to the values from `image_to_stage.json`. Raise on mismatch (no rescaling in v1).
7. Compute `kind = f"objective_{from_objective}_to_{to_objective}"` and `objective_config_name = f"{kind}.json"`.
8. Create paths: `SessionPaths.create(calibration_root, session_id, kind)`.
9. Build and return the session dataclass.

### 10.5 `objective_pair.measure_parfocality_reference`

1. `assert_active_slot(client, session.from_objective_slot, session.from_objective)`.
2. Record `home_xy = drv.get_xy(client)`.
3. Record `home_z = drv.read_zwide_um(client, job_name)`.
4. Return session. No acquisition in this cell.

### 10.6 `objective_pair.measure_parfocality_target`

1. `assert_active_slot(client, session.to_objective_slot, session.to_objective)`.
2. Read `z_post = drv.read_zwide_um(client, job_name)`.
3. `motor_shift_z = z_post - home_z`. Store.
4. Build z-values: `z_values = np.arange(-z_range_um, z_range_um + z_step_um/2, z_step_um) + z_post`.
5. For each z in `z_values`: `drv.move_z(client, float(z), z_mode="zwide")`; acquire; save TIFF to `data_dir/target_z_stack/z_<signed_centi_um>.tif`; collect.
6. Compute Brenner score for each image (use existing `phases.py` Brenner function if present, or a small numpy implementation; sum of squared differences along one axis).
7. Find peak index, refine with a parabolic interpolation around the max (3-point):

    ```
    peak_um = z_values[i_peak] - 0.5 * (s[i_peak+1] - s[i_peak-1]) / (s[i_peak+1] - 2*s[i_peak] + s[i_peak-1]) * z_step_um
    ```

    Guard the parabolic refinement at the stack edges; fall back to `z_values[i_peak]` if `i_peak` is the first or last index.

8. `correction_z = peak_um - z_post`. `translation_z = motor_shift_z + correction_z`. (Equivalent to `peak_um - home_z`.)
9. Park z-wide at the peak for the next cell: `drv.move_z(client, float(peak_um), z_mode="zwide")`.
10. Render the Brenner curve inline with the peak marker.
11. Return session.

### 10.7 `objective_pair.measure_parcentricity_reference`

1. `assert_active_slot(client, session.from_objective_slot, session.from_objective)`.
2. `drv.move_xy_stage(client, *session.home_xy, unit="um")`.
3. `drv.move_z(client, session.home_z, z_mode="zwide")`.
4. Acquire `ref_xy`. Save TIFF to `data_dir/ref_xy.tif`. Store on session.
5. Validate `ref_xy` shape and pixel size against `image_to_stage_image_size_px` / `image_to_stage_pixel_size_um`. Raise on mismatch.
6. Return session.

### 10.8 `objective_pair.measure_parcentricity_target_and_save`

1. `assert_active_slot(client, session.to_objective_slot, session.to_objective)`.
2. Read `xy_post = drv.get_xy(client)`.
3. `motor_shift_xy = (xy_post.x - home_xy[0], xy_post.y - home_xy[1])`. Store.
4. Move z-wide to focus: `drv.move_z(client, home_z + translation_z, z_mode="zwide")`.
5. Acquire `target_xy` at the post-switch XY (no return to home). Save TIFF. Store.
6. Validate geometry against `ref_xy` and against `image_to_stage` metadata.
7. Voting registration: `shift_px, vote = algos.register_voting(ref_xy, target_xy)`.
8. Convert to image-um: `shift_image_um = shift_px * image_to_stage_pixel_size_um`.
9. Apply orientation: `correction_xy = session.image_to_stage @ shift_image_um`. Store as tuple of floats.
10. `translation_xy = motor_shift_xy + correction_xy`. Store.
11. Render magenta/green overlay inline.
12. Set `session.voting_agreement = int(vote)`, `session.trusted = vote >= VOTING_MIN_AGREE`.
13. Build and write the report (see 11.4). Always.
14. If `session.trusted`, build and write the staging calibration (see 11.2). Otherwise do not write a promotable config.
15. Return the summary dict (see section 12).

### 10.9 `promotion.promote_calibration`

1. `staging_path = session.paths.configs_dir / staging_name`.
2. If not `staging_path.exists()`: raise `FileNotFoundError` with a message that explains the common cause (voting below threshold, so the workflow did not save a promotable config).
3. Read JSON.
4. Validate against schema implied by `data["kind"]`. Implementation: a minimal jsonschema or hand-rolled check; reject missing required fields or wrong types.
5. If `live_path.exists()`:
    - Compute `existing_ts` from `read_json(live_path).get("created_at", now_iso())`, sanitized (`:` and `-` replaced for filenames).
    - `archive_dir = live_path.parent / "archive"`; `mkdir(exist_ok=True)`.
    - `shutil.copy2(live_path, archive_dir / f"{existing_ts}_{staging_name}")`.
6. `shutil.copy2(staging_path, live_path)`.
7. Append `f"{now_iso()} {data['kind']} {session.session_id} -> {live_path}\n"` to `live_path.parent / ".promotion.log"`.

---

## 11. JSON Schemas

All JSONs share top-level fields `schema_version: 1`, `kind: <kind-string>`, `created_at: <iso-8601>`. All writes are atomic (write to `.tmp`, rename).

### 11.1 `image_to_stage.json` (staging + live)

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

Field rules:

- `image_size_px`: 2-list `[W, H]`, integers > 0. Validation metadata.
- `pixel_size_um`: float > 0. Validation metadata.
- `image_to_stage`: 2x2 list of floats, elements in {-1, 0, +1} after D4 snap. Dimensionless.

Production consumers must reject mismatched `image_size_px` or `pixel_size_um` from their acquisition.

### 11.2 `objective_<from>_to_<to>.json` (staging + live)

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

Field rules:

- `from_objective`, `to_objective`: short labels matching the LAS X objective name. The filename encodes them too.
- `translation_xy_um`: 2-list of floats, stage-um.
- `translation_z_um`: float, um. Z-wide delta.

Production runtime use: `P_target = P_ref + translation`.

### 11.3 `image_to_stage_report.json`

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
      "image_shift_um": [29.96, -0.22],
      "voting_agreement": 4
    },
    "home_to_plus_y": {
      "image_shift_um": [0.18, 29.91],
      "voting_agreement": 4
    }
  },
  "matrix_label": "FX",
  "residual_from_d4": 0.018,
  "trusted": true
}
```

All paths under `images` are relative to `sessions/<session_id>/`.

`trusted` reflects the workflow's promotion gate. If `false`, no `configs/image_to_stage.json` was written.

### 11.4 `objective_<from>_to_<to>_report.json`

```json
{
  "schema_version": 1,
  "kind": "objective_translation_report",
  "created_at": "2026-05-22T15:10:00+02:00",
  "calibration_file": "objective_10x_to_20x.json",
  "image_to_stage_file": "calibration/current_config/image_to_stage.json",
  "from_objective": "10x",
  "to_objective": "20x",
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
  },
  "trusted": true
}
```

All `data/*` paths relative to the session root. The `image_to_stage_file` may be an absolute-ish path to live config or a session-relative one if an override was used.

---

## 12. Returned Summary Dicts (printed by the notebook)

Workflows return human-readable dicts the operator sees inline. Sketches:

`save_and_visualize` (Notebook 1, Cell 3):

```python
{
  "session_id": "...",
  "matrix_label": "FX",
  "residual_from_d4": 0.018,
  "registrations": {
    "home_to_plus_x": {"image_shift_um": [29.96, -0.22], "voting_agreement": 4},
    "home_to_plus_y": {"image_shift_um": [0.18, 29.91], "voting_agreement": 4},
  },
  "trusted": True,
  "status": "OK -- staging config written to sessions/<id>/configs/image_to_stage.json",
  "reports_dir": "...",
  "configs_dir": "...",
}
```

`measure_parcentricity_target_and_save` (Notebook 2, Cell 3b):

```python
{
  "session_id": "...",
  "from_objective": "10x",
  "to_objective": "20x",
  "motor_shift_xy_um": [-7.02, 21.07],
  "motor_shift_z_um": -6.11,
  "correction_xy_um": [0.56, 0.47],
  "correction_z_um": 8.51,
  "translation_xy_um": [-6.46, 21.54],
  "translation_z_um": 2.40,
  "voting_agreement": 4,
  "brenner_peak_z_um": 12.40,
  "trusted": True,
  "status": "OK -- staging config written",
}
```

When `trusted` is False, `status` says so and the operator knows promotion will fail (the staging file does not exist).

---

## 13. Notebook Contents

Both notebooks live as canonical templates in `calibration/notebooks/`. Operator copies into `sessions/<session_id>/notebooks/` before running.

### 13.1 `calibrate_image_to_stage.ipynb`

**Markdown 0 (title + purpose):**

> # Calibrate image_to_stage
>
> Measure the pixel-to-stage orientation matrix for this rig. Run rarely; usually after microscope/camera geometry changes or as the first step of an objective-pair calibration campaign.

**Markdown 1 (operator preflight):**

> Select the reference objective in LAS X. Set the final scan format, scan speed, zoom, pixel size, image size, and channels you want for **all three** calibration images. Focus on a region with stable texture. Confirm ImageTransformation = TOPLEFT and no modal dialogs. Pixel size and image size must stay exactly the same for all three images. Set `session_id`, `job_name`, `reference_objective`, and `stage_move_um` below, then run the next cell.

**Cell 1 (Config + Open Session):**

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

**Cell 2 (Measure):**

```python
session = wf.measure(session)
print(session)
```

**Cell 3 (Visualize + Save Staging):**

```python
summary = wf.save_and_visualize(session)
print(summary)
```

**Markdown 2 (review + optional promotion):**

> Review the overlays and `residual_from_d4` printed above. Voting agreement for both registrations must be at or above `VOTING_MIN_AGREE`. If `summary["trusted"]` is True, run the next cell to promote. Otherwise stop here and re-acquire.

**Cell 4 (Promote, optional):**

```python
from pathlib import Path
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name="image_to_stage.json",
    live_path=Path("calibration/current_config/image_to_stage.json"),
)
```

### 13.2 `calibrate_objective_pair.ipynb`

**Markdown 0 (title + purpose):**

> # Calibrate Objective Pair
>
> Measure the translation from a reference objective to a target objective. One run per pair. The notebook does not switch objectives; the operator does.

**Markdown 1 (operator preflight + Parfocality Reference instructions):**

> Set `session_id`, `job_name`, `from_objective`, `to_objective` below. Select the reference objective in LAS X. Set scan format, channels, zoom, pixel size, image size. Pixel size and image size must match the live `image_to_stage.json`. Focus the reference via z-wide. Run the next two cells.

**Cell 1 (Config + Open Session):**

```python
from navigator_expert.calibration.workflows import objective_pair as wf

session = wf.start_session(
    session_id="2026-05-22_scope_calibration",
    job_name="Overview",
    from_objective="10x",
    to_objective="20x",
    image_to_stage_path=None,  # default = calibration/current_config/image_to_stage.json
)
print(session)
```

**Cell 2a (Parfocality Reference):**

```python
session = wf.measure_parfocality_reference(session)
print(session)
```

**Markdown 2 (Parfocality Target instructions):**

> Switch to the target objective in LAS X. Set scan format, channels, zoom, pixel size, image size (must match the reference). Do **not** adjust z-wide before running the next cell. If the parfocal gap is large, increase `z_range_um`.

**Cell 2b (Parfocality Target + Z curve):**

```python
session = wf.measure_parfocality_target(
    session,
    z_range_um=30.0,
    z_step_um=1.0,
)
print(session)
```

**Markdown 3 (Parcentricity Reference instructions):**

> Switch back to the reference objective in LAS X. Confirm the same image size and pixel size. Run the next cell.

**Cell 3a (Parcentricity Reference):**

```python
session = wf.measure_parcentricity_reference(session)
print(session)
```

**Markdown 4 (Parcentricity Target instructions):**

> Switch to the target objective in LAS X. Image size and pixel size must match. Do not adjust z-wide. Run the next cell.

**Cell 3b (Parcentricity Target + XY overlay + save):**

```python
summary = wf.measure_parcentricity_target_and_save(session)
print(summary)
```

**Markdown 5 (review + optional promotion):**

> Review the Brenner curve, XY overlay, and numerical summary. If `summary["trusted"]` is True, run the next cell to promote.

**Cell 4 (Promote, optional):**

```python
from pathlib import Path
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name=f"objective_{session.from_objective}_to_{session.to_objective}.json",
    live_path=Path(f"calibration/current_config/objective_{session.from_objective}_to_{session.to_objective}.json"),
)
```

---

## 14. Validation Rules

Workflows raise on:

| Condition | Where | Message hint |
| --- | --- | --- |
| LAS X active objective slot != expected | every `measure_*` cell | "LAS X has slot X active, expected slot Y ('<label>'). Switch in LAS X and re-run cell." |
| `image_to_stage.json` missing at start of Notebook 2 | `objective_pair.start_session` | "Run calibrate_image_to_stage.ipynb first and promote its output." |
| Acquisition pixel size != `image_to_stage_pixel_size_um` | every acquisition that gets registered | "Acquisition pixel size 1.234 um does not match image_to_stage calibration 1.235 um. v1 does not rescale." |
| Image shape != `image_to_stage_image_size_px` | every acquisition that gets registered | same pattern |
| `residual_from_d4 > D4_RESIDUAL_MAX` | `image_to_stage.measure` | "sign-convention fit too far from D4 (Frobenius residual X.XX > Y.YY). Likely cause: drift, sparse texture, or too small a stage_move." |
| Staging file missing during promotion | `promote_calibration` | "Staging file not found ... If voting was below threshold, the workflow did not save a promotable config." |

Workflows warn (do not raise) on:

| Condition | Where | Effect |
| --- | --- | --- |
| `voting_agreement < VOTING_MIN_AGREE` | `image_to_stage.measure`, `measure_parcentricity_target_and_save` | `trusted = False`; report is written; staging calibration is NOT written; summary `status` explains. |

---

## 15. Error and Trust Policy

A summary of the failure modes and what each one does:

| Failure | Notebook behavior | Staging config written? | Promotion possible? |
| --- | --- | --- | --- |
| Wrong objective active | Workflow raises in the cell | No (cell errored) | No |
| Pixel/size mismatch | Workflow raises in the cell | No | No |
| `image_to_stage.json` missing | `start_session` raises | No | No |
| D4 residual above threshold | `measure` raises | No | No |
| Voting agreement below threshold | `save_and_visualize` / `..._target_and_save` saves report + visuals; sets `trusted = False`; no staging config | No | No (promotion raises FileNotFoundError) |
| Everything OK | Saves report + staging config | Yes | Yes |

This is the strict-gating model: the only way for a config file to exist in `sessions/<id>/configs/` is for the workflow to have judged the registration trustworthy.

---

## 16. Implementation Order

Recommended sequence for the implementer.

1. **`calibration/workflows/_common.py`**: `SessionPaths`, JSON helpers, atomic write, image save, geometry validation, slot helpers, visualization helpers. Unit tests for `SessionPaths.create`, the JSON helpers, and `validate_image_geometry`.
2. **`calibration/workflows/image_to_stage.py`**: dataclass, `start_session`, `measure`, `save_and_visualize`. Manual integration test: run the notebook against a real rig with the reference objective active, confirm the report and (if trusted) the staging config land in the right places.
3. **`calibration/workflows/objective_pair.py`**: dataclass and the four measure functions. Manual integration test: run the notebook against a real rig for one well-known pair (10x -> 20x).
4. **`calibration/workflows/promotion.py`**: validate-archive-copy-log. Unit tests with a tmp_path: existing live, no existing live, missing staging, malformed staging.
5. **`calibration/notebooks/calibrate_image_to_stage.ipynb` and `calibrate_objective_pair.ipynb`**: thin templates with the markdown and code cells listed in section 13.
6. **Tests**: a small mock LAS X client for `start_session` / object identification paths; trust integration tests for the registration math (do not mock the algorithms module).
7. **Documentation**: update `calibration/README.md` (or create one) with the campaign workflow: copy template, run, review, promote. Reference this plan.
8. **Retire `scripts/calibrate_objectives.py`**: separate change. Not in this implementation.

Total estimated effort: 2-3 days for code + 1 day for integration on the rig.

---

## 17. Test Plan

| Layer | What is tested | How |
| --- | --- | --- |
| `SessionPaths` | Idempotent directory creation, disjoint `data/<kind>/` subfolders | Unit, `tmp_path` |
| JSON helpers | Atomic write, round-trip, raises on missing | Unit |
| Geometry validation | Mismatch raises with a clear message | Unit |
| D4 fit math | Synthetic image shifts produce expected matrix labels and residuals | Unit (using existing `algos.classify_d4`) |
| Brenner peak refinement | Synthetic curve has peak refined to sub-step accuracy | Unit |
| `promote_calibration` | Live exists / does not exist; staging missing; malformed JSON | Unit, `tmp_path` |
| `image_to_stage.measure` | Wraps the registration + fit + D4-snap correctly | Integration (mock LAS X client returning fixed images) |
| `objective_pair` measure chain | Sessions threaded correctly; trust gate works | Integration (mock client; test both trusted and untrusted paths) |
| Notebook execution | End-to-end on the real rig | Manual, signed off by the operator |

A mock LAS X client lives under `calibration/tests/_mock_client.py` and returns deterministic XY/Z values plus a small library of synthetic 8-bit images.

---

## 18. Open Questions

1. **Raw image format.** TIFF for inspectability vs. NumPy `.npy` for exact reload. Recommend TIFF (Leica-compatible, opens in Fiji); keep `.npy` as an option if file size becomes an issue.
2. **Z-stack memory.** A 60-um stack at 1-um steps is 61 images. Stream-write during acquisition (recommended) or hold in memory (simpler but a few hundred MB)?
3. **Promotion archive depth.** Keep all archived live files vs. rotate. Recommend keep all in v1; revisit if the archive becomes large.
4. **Image-to-stage robustness.** Voting registration uses the existing 4-method ensemble. For large known stage moves this is arguably overkill; single phase correlation might be sufficient. Recommend keep voting until the v2 cleanup; it is the conservative default.
5. **Parabolic peak refinement edges.** Brenner peak at the stack boundary cannot be parabolically refined. Currently the plan falls back to the discrete index. Acceptable, or should the workflow widen the stack and retry?

---

## 19. Glossary

| Term | Meaning |
| --- | --- |
| home_xy, home_z | Stage XY and z-wide values recorded at the reference objective before any switch |
| motor_shift_* | Stage delta after firmware objective-switch motion, measured by readback (post_switch - home) |
| correction_* | Residual error after firmware switch, measured by image registration (XY) or Brenner peak (Z) |
| translation_* | The full ref-to-target delta; `motor_shift + correction`; what production stores |
| image_to_stage | 2x2 dimensionless rotation/reflection matrix mapping image-um displacements to stage-um displacements |
| D4 | The dihedral group of order 8: the eight axis-aligned rotation/reflection matrices on the plane |
| residual_from_d4 | Frobenius norm of (fitted - snapped) image-to-stage matrix; dimensionless |
| voting_agreement | Integer count of registration methods that agreed on the shift; threshold `VOTING_MIN_AGREE` |
| trusted | Workflow's verdict on whether the calibration is good enough to write a promotable staging config |
| promotion | Explicit operator action that copies a trusted staging config into `current_config/` |
| current_config | The one folder production reads from. Live calibration |
| sessions/<id> | One calibration campaign. Staging area for all calibrations from a single sitting |

---

## 20. Diff Against the Previous (Shared) Plan

This file is the implementation-grade version of `CALIBRATION_NOTEBOOKS_PLAN.md`. Substantive deltas:

- Units are stated explicitly per quantity in section 5, including the convention that the voting registration wrapper returns image-um (not pixels).
- `image_to_stage` is dimensionless (rotation/reflection only). The 2x2 matrix elements are integers in {-1, 0, +1} after the D4 snap. Scaling lives in `pixel_size_um`.
- `trusted: bool` is added to both reports, mirroring the workflow's promotion gate.
- The promotion gate (voting below `VOTING_MIN_AGREE` -> no staging config) is stated explicitly in section 15 and reflected in `save_and_visualize` and `measure_parcentricity_target_and_save`.
- Constants table (section 8) commits to the existing `VOTING_MIN_AGREE`, `D4_RESIDUAL_MAX`, and a new `CALIBRATION_ROOT_DEFAULT`. No new tunables.
- Implementation order (section 16) and a test plan (section 17) are added.
- Validation rules (section 14) and the error/trust matrix (section 15) are spelled out.
- Driver function names are committed to: `drv.get_xy`, `drv.move_xy_stage`, `drv.read_zwide_um`, `drv.move_z(..., z_mode="zwide")`, `drv.parse_tile_geometry`, `drv.get_job_settings`, `drv.acquire_single`, `drv.connect_python_client`, `drv.apply_stage_limits_from_config`, `drv.load_stage_config`, `drv.get_hardware_info`, `drv.objective_by_slot`. Implementer verifies each exists; if not, wraps the closest equivalent in `_common.py`.
