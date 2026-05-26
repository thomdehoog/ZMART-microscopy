# Calibration Notebooks Implementation Plan - Codex

This is a self-contained implementation plan for the smart microscopy calibration notebooks.

It is intentionally close to code. It names the modules to add, the existing APIs to reuse, the data models, the notebook cell calls, the save paths, the JSON schemas, the validation rules, and the expected tests.

## 1. Scope

Build two Jupyter notebook workflows:

1. `calibrate_image_to_stage.ipynb`
   - Measures the mapping between image displacement and stage displacement under the reference objective.
   - Produces `image_to_stage.json`.

2. `calibrate_objective_pair.ipynb`
   - Measures one reference-to-target objective translation.
   - Produces `objective_<from>_to_<to>.json`.

The notebooks are thin. They contain markdown instructions plus one workflow function call per code cell. They do not contain measurement logic.

The workflow modules do the real work:

```text
calibration/workflows/common.py
calibration/workflows/image_to_stage.py
calibration/workflows/objective_pair.py
calibration/workflows/promotion.py
```

## 2. Non-goals

Do not implement objective switching in the notebook workflow API. The operator changes objectives in LAS X.

Do not let save functions silently activate calibration. Promotion to live config is always explicit.

Do not introduce an interactive sign picker. The magenta/green overlays are diagnostic confirmation.

Do not rescale images when image size or pixel size differs. Mismatch is a hard error.

Do not invent a new registration module. Reuse `navigator_expert.algorithms`.

Do not make production read from session folders. Production reads only from `calibration/current_config/`.

## 3. Coordinate Model

Smart microscopy works in absolute stage coordinates.

For a target found under the reference objective:

```text
P_target = P_ref + translation
```

Calibration measures:

```text
translation = motor_shift + correction
```

Definitions:

- `motor_shift`: what LAS X firmware/hardware/software does automatically when the operator switches objective.
- `correction`: what is still missing after that automatic switch.
- `translation`: the full absolute reference-to-target objective delta used by production.

Production config stores only:

```text
translation_xy_um
translation_z_um
```

Reports store the diagnostic pieces:

```text
motor_shift_xy_um
motor_shift_z_um
correction_xy_um
correction_z_um
```

## 4. Unit Convention

Use the current code convention in `navigator_expert.algorithms.registration.register_voting`.

`register_voting(ref, tgt, pixel_um)` returns:

```text
dx_um
dy_um
```

These are image displacements in micrometers, not pixels.

Therefore:

```text
correction_xy_um = image_to_stage @ [dx_um, dy_um]
```

The `image_to_stage` matrix maps:

```text
image displacement in um -> stage displacement in um
```

Do not name it `image_to_stage_um_per_px`. Do not store `pixel_shift` in reports unless a new explicit pixel-returning API is added later. Use `image_shift_um`.

## 5. Existing APIs To Reuse

### Driver

Import the public driver API:

```python
import navigator_expert.driver as drv
```

Use:

```python
drv.connect_python_client()
drv.load_stage_config()
drv.apply_stage_limits_from_config(...)
drv.get_hardware_info(client)
drv.get_job_settings(client, job_name)
drv.parse_tile_geometry(settings)
drv.get_xy(client)
drv.move_xy_stage(client, x_um, y_um, unit="um", tolerance=...)
drv.read_zwide_um(client, job_name)
drv.move_z(client, job_name, z_um, unit="um", z_mode="zwide")
drv.move_z(client, job_name, 0.0, unit="um", z_mode="galvo")
drv.acquire_frame(client, job_name, backlash_params=...)
drv.acquire_stack(client, job_name, backlash_params=...)
drv.check_idle(client, timeout=...)
```

### Algorithms

Use:

```python
from navigator_expert.algorithms import (
    D4_RESIDUAL_MAX,
    VOTING_MIN_AGREE,
    brenner_focus,
    classify_d4,
    register_voting,
)
```

### Calibration Helpers

Reuse where useful:

```python
from navigator_expert.calibration.lib.lasx_state import (
    configure_z_stack,
    disable_z_stack,
    reset_pan_roi_zstack,
)
```

The current `make_acquirer()` returns arrays but drops the exported file path for single frames. The workflows need session-owned raw data paths, so implement workflow-local acquisition wrappers that call `drv.acquire_frame()` / `drv.acquire_stack()` directly and copy or write arrays into `session.paths.data_dir`.

## 6. Directory Layout

Add:

```text
calibration/
  workflows/
    __init__.py
    common.py
    image_to_stage.py
    objective_pair.py
    promotion.py

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
    <session_id>/
      configs/
      reports/
      notebooks/
      data/
        image_to_stage/
        objective_10x_to_20x/
```

Rules:

- `sessions/<session_id>/configs/` contains staging config JSONs.
- `sessions/<session_id>/reports/` contains diagnostic report JSONs.
- `sessions/<session_id>/data/<kind>/` contains raw images/stacks.
- `sessions/<session_id>/notebooks/` contains executed notebook copies.
- `current_config/` is the only live config folder.

Production never reads from `sessions/`.

## 7. Common Workflow Module

File:

```text
calibration/workflows/common.py
```

### Constants

```python
CALIBRATION_ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROOT = CALIBRATION_ROOT / "sessions"
CURRENT_CONFIG_ROOT = CALIBRATION_ROOT / "current_config"
```

### Dataclasses

```python
@dataclass
class SessionPaths:
    session_dir: Path
    configs_dir: Path
    reports_dir: Path
    notebooks_dir: Path
    data_dir: Path
```

```python
@dataclass
class ImageGeometry:
    image_size_px: tuple[int, int]   # [height, width] from ndarray shape
    format_px: tuple[int, int]       # [pixels_y, pixels_x] from LAS X geometry
    pixel_size_um: float
    pixel_w_um: float
    pixel_h_um: float
```

Use a scalar `pixel_size_um` only if `pixel_w_um` and `pixel_h_um` match within tolerance. If they do not match, raise in v1.

### Path Helpers

```python
def objective_config_name(from_objective: str, to_objective: str) -> str:
    return f"objective_{slug(from_objective)}_to_{slug(to_objective)}.json"
```

`slug()` should keep objective names filesystem safe. Minimal v1:

```python
def slug(value: str) -> str:
    return (
        value.strip()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(".", "p")
    )
```

If objective names are already `10x`, `20x`, this produces the intended names.

```python
def make_session_paths(session_id: str, kind: str) -> SessionPaths:
    session_dir = SESSIONS_ROOT / session_id
    paths = SessionPaths(
        session_dir=session_dir,
        configs_dir=session_dir / "configs",
        reports_dir=session_dir / "reports",
        notebooks_dir=session_dir / "notebooks",
        data_dir=session_dir / "data" / kind,
    )
    for p in [paths.configs_dir, paths.reports_dir, paths.notebooks_dir, paths.data_dir]:
        p.mkdir(parents=True, exist_ok=True)
    return paths
```

### Geometry Helpers

```python
def read_job_geometry(client, job_name: str, image: np.ndarray | None = None) -> ImageGeometry:
    settings = drv.get_job_settings(client, job_name) or {}
    geom = drv.parse_tile_geometry(settings)
    pixel_w = float(geom["pixel_w_um"])
    pixel_h = float(geom["pixel_h_um"])
    if not np.isclose(pixel_w, pixel_h, rtol=0, atol=1e-9):
        raise ValueError("non-square pixels are not supported in v1")
    format_px = (int(geom["pixels_y"]), int(geom["pixels_x"]))
    image_size_px = tuple(image.shape[-2:]) if image is not None else format_px
    return ImageGeometry(
        image_size_px=image_size_px,
        format_px=format_px,
        pixel_size_um=pixel_w,
        pixel_w_um=pixel_w,
        pixel_h_um=pixel_h,
    )
```

Validation:

```python
def assert_geometry_matches(
    actual: ImageGeometry,
    expected_image_size_px: tuple[int, int],
    expected_pixel_size_um: float,
    *,
    context: str,
) -> None:
    if tuple(actual.image_size_px) != tuple(expected_image_size_px):
        raise ValueError(f"{context}: image size mismatch")
    if not np.isclose(actual.pixel_size_um, expected_pixel_size_um, rtol=0, atol=1e-9):
        raise ValueError(f"{context}: pixel size mismatch")
```

### Move Helpers

Use the same safety pattern as `calibration/lib/phases.py`.

```python
def move_xy_and_verify(client, x_um: float, y_um: float, *, settle_s: float, tolerance_um: float = 0.5) -> None:
    result = drv.move_xy_stage(client, x_um, y_um, unit="um", tolerance=tolerance_um)
    if not result or not result.get("success"):
        raise RuntimeError(f"move_xy_stage failed: {result}")
    time.sleep(settle_s)
    xy = drv.get_xy(client)
    if abs(xy["x_um"] - x_um) > tolerance_um or abs(xy["y_um"] - y_um) > tolerance_um:
        raise RuntimeError("stage readback outside tolerance")
```

```python
def move_zwide_and_verify(client, job_name: str, z_um: float, *, tolerance_um: float = 1.0) -> None:
    result = drv.move_z(client, job_name, z_um, unit="um", z_mode="zwide", tolerance=tolerance_um)
    if not result or not result.get("success"):
        raise RuntimeError(f"move_z zwide failed: {result}")
```

### Acquisition Helpers

The workflow owns the saved session data files. Do not rely on LAS X export names as final session filenames.

For frames:

```python
def acquire_frame_to(session, name: str) -> np.ndarray:
    img, exported_path = drv.acquire_frame(
        session.client,
        session.job_name,
        backlash_params=session.stage_cfg["backlash"],
    )
    out = session.paths.data_dir / f"{name}.tif"
    tifffile.imwrite(out, img)
    session.raw_files[name] = str(out.relative_to(session.paths.session_dir))
    session.exported_files[name] = str(exported_path)
    return img
```

For stacks:

```python
def acquire_stack_to(session, dirname: str) -> np.ndarray:
    stack = drv.acquire_stack(
        session.client,
        session.job_name,
        backlash_params=session.stage_cfg["backlash"],
    )
    out_dir = session.paths.data_dir / dirname
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(stack):
        tifffile.imwrite(out_dir / f"z_{i:03d}.tif", img)
    session.raw_files[dirname] = str(out_dir.relative_to(session.paths.session_dir))
    return stack
```

This creates stable, inspectable files in the session folder.

### JSON Helpers

Write JSON atomically:

```python
def write_json_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
```

### Plot Helpers

Notebook visuals should be generated by workflow functions, not notebook code.

Common functions:

```python
def plot_overlay(ref: np.ndarray, tgt: np.ndarray, title: str, *, shift_um=None, pixel_size_um=None):
    ...
```

Use magenta/green overlays:

- Reference image in magenta.
- Target/moved image in green.
- Optional shifted overlay after applying the measured displacement.

For focus:

```python
def plot_brenner_curve(z_positions_um: list[float], scores: list[float], peak_z_um: float):
    ...
```

The functions should call `matplotlib.pyplot` and return the figure object. In notebooks, returning or displaying the figure is enough.

## 8. Notebook 1 Workflow

File:

```text
calibration/workflows/image_to_stage.py
```

### Dataclass

```python
@dataclass
class ImageToStageSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    stage_cfg: dict
    reference_objective: str
    stage_move_um: float
    settle_s: float
    image_size_px: tuple[int, int] | None = None
    pixel_size_um: float | None = None
    home_xy: tuple[float, float] | None = None
    images: dict[str, np.ndarray] = field(default_factory=dict)
    raw_files: dict[str, str] = field(default_factory=dict)
    exported_files: dict[str, str] = field(default_factory=dict)
    registrations: dict[str, dict] = field(default_factory=dict)
    image_to_stage: list[list[float]] | None = None
    fitted_image_to_stage: list[list[float]] | None = None
    d4_label: str | None = None
    residual_from_d4: float | None = None
    config_written: bool = False
```

### Cell API

```python
def start_session(
    session_id: str,
    job_name: str,
    reference_objective: str,
    stage_move_um: float = 30.0,
    settle_s: float = 1.0,
) -> ImageToStageSession:
    ...
```

Implementation:

1. `client = drv.connect_python_client()`
2. `stage_cfg = drv.load_stage_config()`
3. `drv.apply_stage_limits_from_config(stage_cfg)`
4. `drv.get_hardware_info(client)` to fail early if the scope is not reachable.
5. `paths = make_session_paths(session_id, "image_to_stage")`
6. Validate `stage_move_um > 0`.
7. Return session.

Do not change objective, zoom, scan format, scan speed, channels, or focus.

```python
def measure(session: ImageToStageSession) -> ImageToStageSession:
    ...
```

Implementation:

1. Read `home_xy = drv.get_xy(session.client)`.
2. Acquire `home`.
3. Read and store geometry from `home`.
4. Move absolute XY to `home_x + stage_move_um, home_y`.
5. Acquire `plus_x`.
6. Validate `plus_x` geometry equals `home`.
7. Move back to `home_xy`.
8. Move absolute XY to `home_x, home_y + stage_move_um`.
9. Acquire `plus_y`.
10. Validate `plus_y` geometry equals `home`.
11. Move back to `home_xy`.
12. Run voting registration:

```python
vote_x = register_voting(home, plus_x, session.pixel_size_um)
vote_y = register_voting(home, plus_y, session.pixel_size_um)
```

13. Store the full vote dictionaries in `session.registrations`.
14. If either `vote["trusted"]` is false, do not compute a config; leave enough report data for inspection.
15. If both trusted, compute:

```python
stage_to_image = np.array([
    [vote_x["dx_um"] / stage_move_um, vote_y["dx_um"] / stage_move_um],
    [vote_x["dy_um"] / stage_move_um, vote_y["dy_um"] / stage_move_um],
])
image_to_stage_fitted = -np.linalg.inv(stage_to_image)
label, canonical, residual = classify_d4(image_to_stage_fitted)
```

16. If `residual > D4_RESIDUAL_MAX`, raise. This is not a weak diagnostic; the sign/matrix is not trustworthy.
17. Store:

```python
session.fitted_image_to_stage = image_to_stage_fitted.tolist()
session.image_to_stage = canonical.tolist()
session.d4_label = label
session.residual_from_d4 = residual
```

Note: this preserves the current sign convention used by `phases.measure_sign_convention`.

```python
def save_and_visualize(session: ImageToStageSession) -> dict:
    ...
```

Implementation:

1. Render magenta/green overlays for `home` vs `plus_x` and `home` vs `plus_y`.
2. Build and write report unconditionally:

```text
sessions/<id>/reports/image_to_stage_report.json
```

3. Write staging config only if:

```python
all(v["trusted"] for v in session.registrations.values())
and session.image_to_stage is not None
```

4. Return a summary dict:

```python
{
    "config_written": session.config_written,
    "config_path": ".../configs/image_to_stage.json" or None,
    "report_path": ".../reports/image_to_stage_report.json",
    "d4_label": session.d4_label,
    "residual_from_d4": session.residual_from_d4,
    "voting": {
        "home_to_plus_x": {"trusted": True, "confidence": 4},
        "home_to_plus_y": {"trusted": True, "confidence": 4},
    },
}
```

### Notebook 1 Cells

Cell 1:

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

Markdown before Cell 2:

```text
Select the reference objective in LAS X. Set final scan format, zoom, scan speed,
pixel size, image size, and channels. Focus on stable texture. Pixel size and
image size must stay exactly the same for all three images. Do not change settings
between acquisitions.
```

Cell 2:

```python
session = wf.measure(session)
print(session)
```

Cell 3:

```python
summary = wf.save_and_visualize(session)
print(summary)
```

Optional Cell 4:

```python
from pathlib import Path
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name="image_to_stage.json",
    live_path=Path("calibration/current_config/image_to_stage.json"),
)
```

## 9. Notebook 2 Workflow

File:

```text
calibration/workflows/objective_pair.py
```

### Dataclass

```python
@dataclass
class ObjectivePairSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    stage_cfg: dict
    from_objective: str
    to_objective: str
    objective_config_name: str
    image_to_stage_path: Path
    image_to_stage: np.ndarray
    image_to_stage_image_size_px: tuple[int, int]
    image_to_stage_pixel_size_um: float
    home_xy: tuple[float, float] | None = None
    home_z: float | None = None
    z_post: float | None = None
    focus_z_target_um: float | None = None
    xy_post: tuple[float, float] | None = None
    ref_image: np.ndarray | None = None
    target_image: np.ndarray | None = None
    target_z_stack: np.ndarray | None = None
    raw_files: dict[str, str] = field(default_factory=dict)
    exported_files: dict[str, str] = field(default_factory=dict)
    motor_shift_xy_um: tuple[float, float] | None = None
    motor_shift_z_um: float | None = None
    correction_xy_um: tuple[float, float] | None = None
    correction_z_um: float | None = None
    translation_xy_um: tuple[float, float] | None = None
    translation_z_um: float | None = None
    brenner: dict | None = None
    registration: dict | None = None
    config_written: bool = False
```

### Cell API

```python
def start_session(
    session_id: str,
    job_name: str,
    from_objective: str,
    to_objective: str,
    image_to_stage_path: Path | None = None,
) -> ObjectivePairSession:
    ...
```

Implementation:

1. Connect to client.
2. Load stage config and apply limits.
3. Resolve image-to-stage path:

```python
if image_to_stage_path is None:
    image_to_stage_path = CALIBRATION_ROOT / "current_config" / "image_to_stage.json"
```

4. If missing, raise with a message telling the operator to run Notebook 1 or pass a session config path.
5. Load JSON and validate:
   - `schema_version == 1`
   - `kind == "image_to_stage"`
   - has `image_to_stage`
   - has `image_size_px`
   - has `pixel_size_um`
6. Create session paths with kind `objective_<from>_to_<to>`.
7. Return session.

```python
def measure_parfocality_reference(session: ObjectivePairSession) -> ObjectivePairSession:
    ...
```

Operator is on reference objective and has focused manually.

Implementation:

1. `xy = drv.get_xy(session.client)`
2. `z = drv.read_zwide_um(session.client, session.job_name)`
3. Store:

```python
session.home_xy = (float(xy["x_um"]), float(xy["y_um"]))
session.home_z = float(z)
```

4. Optionally call `drv.move_z(... z_mode="galvo", z=0.0)` to enforce galvo zero, but do not move z-wide.

No image is required in this cell.

```python
def measure_parfocality_target(
    session: ObjectivePairSession,
    z_range_um: float = 30.0,
    z_step_um: float = 1.0,
) -> ObjectivePairSession:
    ...
```

Operator has switched to target objective and must not adjust z-wide.

Implementation:

1. Assert `home_z` is set.
2. Read:

```python
z_post = drv.read_zwide_um(client, job_name)
motor_shift_z_um = z_post - home_z
```

3. Configure z-wide stack:

```python
configure_z_stack(
    client,
    job_name,
    half_range_um=z_range_um,
    step_um=z_step_um,
    z_drive="z-wide",
    centre_um=z_post,
)
```

4. Acquire stack into:

```text
sessions/<id>/data/objective_<from>_to_<to>/target_z_stack/
```

5. Disable z-stack after acquisition.
6. Run:

```python
focus = brenner_focus(stack, z_step_um)
```

Current `lasx_state.configure_z_stack` uses high-Z-to-low-Z ordering:

```text
physical_z = z_post + z_range_um - peak_um
```

where `peak_um` is the focus result's stack-relative peak coordinate from `brenner_focus`.

Implementation should make this conversion explicit and test it:

```python
peak_offset_um = float(focus["peak_um"])
focus_z_target_um = z_post + z_range_um - peak_offset_um
```

7. Compute:

```python
correction_z_um = focus_z_target_um - z_post
translation_z_um = motor_shift_z_um + correction_z_um
# equivalent:
translation_z_um = focus_z_target_um - home_z
```

8. Move z-wide to `focus_z_target_um`:

```python
move_zwide_and_verify(client, job_name, focus_z_target_um)
```

9. Render Brenner curve.

```python
def measure_parcentricity_reference(session: ObjectivePairSession) -> ObjectivePairSession:
    ...
```

Operator has switched back to reference objective.

Implementation:

1. Assert `home_xy` and `home_z` are set.
2. Move XY to `home_xy`.
3. Move z-wide to `home_z`.
4. Acquire `ref_xy.tif`.
5. Read geometry from job settings and image.
6. Validate against `image_to_stage` config:

```python
assert_geometry_matches(
    actual_geometry,
    session.image_to_stage_image_size_px,
    session.image_to_stage_pixel_size_um,
    context="reference XY image",
)
```

Store `session.ref_image`.

```python
def measure_parcentricity_target_and_save(session: ObjectivePairSession) -> dict:
    ...
```

Operator has switched to target objective and must not adjust z-wide.

Implementation:

1. Read `xy_post = drv.get_xy(client)`.
2. Compute:

```python
motor_shift_xy_um = (xy_post_x - home_x, xy_post_y - home_y)
```

3. Move z-wide to target focus:

```python
target_z = home_z + translation_z_um
move_zwide_and_verify(client, job_name, target_z)
```

4. Acquire `target_xy.tif` at the post-switch XY position. Do not move back to `home_xy`.
5. Validate geometry against:
   - `ref_xy`
   - `image_to_stage_image_size_px`
   - `image_to_stage_pixel_size_um`
6. Run:

```python
vote = register_voting(session.ref_image, session.target_image, session.image_to_stage_pixel_size_um)
```

7. If `vote["trusted"]` is true:

```python
image_shift = np.array([vote["dx_um"], vote["dy_um"]])
correction_xy = np.asarray(session.image_to_stage) @ image_shift
translation_xy = np.asarray(session.motor_shift_xy_um) + correction_xy
```

8. If `vote["trusted"]` is false:
   - Save report and overlay.
   - Do not write `configs/objective_<from>_to_<to>.json`.
   - Return summary with `config_written=False`.

9. If trusted:
   - Save config.
   - Save report.
   - Return summary with `config_written=True`.

Important: weak XY voting is not promotable. This prevents a config file from existing when the measured XY translation should not be used.

### Notebook 2 Cells

Cell 1:

```python
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

Markdown before Cell 2a:

```text
Select the reference objective in LAS X. Set scan format, zoom, channels,
pixel size, and image size. Focus the reference via z-wide. Pixel size and
image size must match the image-to-stage calibration.
```

Cell 2a:

```python
session = wf.measure_parfocality_reference(session)
print(session)
```

Markdown before Cell 2b:

```text
Switch to the target objective in LAS X. Set target scan format, zoom,
channels, pixel size, and image size. Do not adjust z-wide. The z-stack
will measure the parfocal gap. Increase z_range_um if the focus peak is
near the edge of the curve.
```

Cell 2b:

```python
session = wf.measure_parfocality_target(
    session,
    z_range_um=30.0,
    z_step_um=1.0,
)
print(session)
```

Markdown before Cell 3a:

```text
Switch back to the reference objective in LAS X. Confirm the same image size
and pixel size. Run the next cell to acquire the reference XY image.
```

Cell 3a:

```python
session = wf.measure_parcentricity_reference(session)
print(session)
```

Markdown before Cell 3b:

```text
Switch to the target objective in LAS X. Do not adjust z-wide. Image size and
pixel size must match the reference acquisition and the image-to-stage
calibration. Run the next cell to acquire target XY, register, save the report,
and write the staging config if the vote is trusted.
```

Cell 3b:

```python
summary = wf.measure_parcentricity_target_and_save(session)
print(summary)
```

Optional promote:

```python
from pathlib import Path
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name=session.objective_config_name,
    live_path=Path("calibration/current_config") / session.objective_config_name,
)
```

## 10. Promotion Workflow

File:

```text
calibration/workflows/promotion.py
```

API:

```python
def promote_calibration(session, staging_name: str, live_path: Path) -> dict:
    ...
```

Implementation:

1. Source:

```python
source = session.paths.configs_dir / staging_name
```

2. If source missing, raise:

```text
No staging config exists. Review the report. The measurement may have failed validation or weak voting.
```

3. Read and validate source JSON by `kind`.
4. Create:

```text
calibration/current_config/
calibration/current_config/archive/
```

5. If `live_path` exists:

```text
archive/<timestamp>_<staging_name>
```

6. Copy source to live path atomically.
7. Append to:

```text
calibration/current_config/.promotion.log
```

Example line:

```text
2026-05-22T13:10:04Z image_to_stage 2026-05-22_scope_calibration -> calibration/current_config/image_to_stage.json
```

Return:

```python
{
    "source": str(source),
    "live_path": str(live_path),
    "archived_previous": str(archive_path) or None,
}
```

## 11. JSON Schemas

### `configs/image_to_stage.json`

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

Meaning:

- `image_to_stage` maps image-um displacement to stage-um displacement.
- `image_size_px` is `[height, width]`, matching numpy image shape.
- `pixel_size_um` is scalar and requires square pixels in v1.

### `configs/objective_10x_to_20x.json`

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

Runtime:

```text
P_target = P_ref + translation
```

### `reports/image_to_stage_report.json`

Report paths are relative to `sessions/<session_id>/`.

```json
{
  "schema_version": 1,
  "kind": "image_to_stage_report",
  "created_at": "2026-05-22T14:30:00+02:00",
  "calibration_file": "image_to_stage.json",
  "config_written": true,
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
      "trusted": true,
      "confidence": 4,
      "agreeing": ["pcc", "masked_pcc", "ncc", "orb"]
    },
    "home_to_plus_y": {
      "image_shift_um": [0.1, 24.5],
      "trusted": true,
      "confidence": 4,
      "agreeing": ["pcc", "masked_pcc", "ncc", "orb"]
    }
  },
  "d4_label": "-Y +X",
  "fitted_image_to_stage": [[0.02, -0.99], [1.01, 0.01]],
  "image_to_stage": [[0.0, -1.0], [1.0, 0.0]],
  "residual_from_d4": 0.018
}
```

If voting is weak:

- `config_written` is false.
- report still exists.
- `configs/image_to_stage.json` does not exist or is not overwritten.

### `reports/objective_10x_to_20x_report.json`

Report paths are relative to `sessions/<session_id>/`.

```json
{
  "schema_version": 1,
  "kind": "objective_translation_report",
  "created_at": "2026-05-22T15:10:00+02:00",
  "calibration_file": "objective_10x_to_20x.json",
  "config_written": true,
  "image_to_stage_file": "calibration/current_config/image_to_stage.json",
  "from_objective": "10x",
  "to_objective": "20x",
  "home_xy_um": [1000.0, 2000.0],
  "home_z_um": 42.0,
  "xy_post_um": [992.98, 2021.07],
  "z_post_um": 35.89,
  "motor_shift_xy_um": [-7.02, 21.07],
  "motor_shift_z_um": -6.11,
  "correction_xy_um": [0.56, 0.47],
  "correction_z_um": 8.51,
  "translation_xy_um": [-6.46, 21.54],
  "translation_z_um": 2.40,
  "registration": {
    "image_shift_um": [0.56, 0.47],
    "trusted": true,
    "confidence": 4,
    "agreeing": ["pcc", "masked_pcc", "ncc", "orb"]
  },
  "brenner": {
    "peak_z_um": 44.4,
    "scores": [0.1, 0.2, 0.9, 0.3],
    "z_positions_um": [43.0, 44.0, 45.0, 46.0]
  },
  "images": {
    "ref_xy": "data/objective_10x_to_20x/ref_xy.tif",
    "target_xy": "data/objective_10x_to_20x/target_xy.tif",
    "target_z_stack": "data/objective_10x_to_20x/target_z_stack/"
  }
}
```

If voting is weak:

- `config_written` is false.
- report still exists.
- objective config is not written.

## 12. Current Config Consumption

The eventual production reader should read:

```text
calibration/current_config/image_to_stage.json
calibration/current_config/objective_<from>_to_<to>.json
```

Minimal runtime helper:

```python
def target_position_from_reference(p_ref_xy, p_ref_z, from_objective, to_objective):
    cfg = load_objective_translation(from_objective, to_objective)
    return (
        p_ref_xy[0] + cfg["translation_xy_um"][0],
        p_ref_xy[1] + cfg["translation_xy_um"][1],
        p_ref_z + cfg["translation_z_um"],
    )
```

Do not add `motor_shift` at runtime. LAS X already does the firmware move during objective switching. The live config translation is the full absolute delta from reference coordinates to target coordinates.

## 13. Tests

Add tests under the existing test tree, likely:

```text
test/test_calibration_workflows.py
```

Use mocked driver calls. Do not require LAS X.

### Common Tests

1. `make_session_paths` creates:
   - `configs/`
   - `reports/`
   - `notebooks/`
   - `data/<kind>/`

2. `objective_config_name("10x", "20x") == "objective_10x_to_20x.json"`.

3. `assert_geometry_matches` accepts exact match.

4. `assert_geometry_matches` rejects image-size mismatch.

5. `assert_geometry_matches` rejects pixel-size mismatch.

6. non-square pixel sizes are rejected in v1.

### Image-To-Stage Tests

1. Synthetic perfect orientation:
   - Mock `register_voting` for X and Y moves.
   - Verify fitted matrix and snapped D4 matrix.
   - Verify config written.

2. Weak vote:
   - One registration has `trusted=False`.
   - Verify report is written.
   - Verify config is not written.

3. D4 residual too high:
   - Mock image shifts that produce sheared matrix.
   - Verify `RuntimeError`.

4. Save report paths:
   - Verify report image paths are session-root-relative.

5. Overlay generation:
   - Smoke test that `save_and_visualize` returns figures or does not crash on arrays.

### Objective Pair Tests

1. Z translation:

```text
home_z = 100
z_post = 94
focus_z_target = 103
motor_shift_z = -6
correction_z = 9
translation_z = 3
```

Verify all three values.

2. XY translation:

```text
home_xy = (1000, 2000)
xy_post = (993, 2021)
motor_shift_xy = (-7, 21)
registration image shift = (0.5, 0.25)
image_to_stage = identity
correction_xy = (0.5, 0.25)
translation_xy = (-6.5, 21.25)
```

Verify config values.

3. Weak XY vote:
   - Verify report written.
   - Verify objective config not written.

4. Missing image-to-stage config:
   - `start_session(... image_to_stage_path=None)` raises a clear message if current config missing.

5. Override image-to-stage path:
   - Pass a session config path.
   - Verify report records that exact resolved path.

6. Target acquisition happens at post-switch XY:
   - Mock `drv.get_xy` after switch.
   - Verify no move to `home_xy` occurs in target cell before acquisition.

7. Reference parcentricity cell moves to `home_xy` and `home_z`.

### Promotion Tests

1. Promote image-to-stage:
   - Source exists.
   - Live missing.
   - Copies to `current_config/image_to_stage.json`.
   - Appends log.

2. Promote with existing live:
   - Archives old live to `current_config/archive/`.
   - Replaces live.

3. Missing staging config:
   - Raises with clear message.

4. Wrong schema kind:
   - Rejects promotion.

## 14. Implementation Order

1. Add `calibration/workflows/common.py`.
2. Add JSON schema helpers and tests for common path/schema behavior.
3. Add `promotion.py` and promotion tests.
4. Add `image_to_stage.py` with mocked tests.
5. Add `objective_pair.py` with mocked tests.
6. Add notebook templates with only markdown and workflow calls.
7. Run focused calibration tests.
8. Run broader navigator_expert tests if practical.
9. Only after tests pass, decide whether to deprecate or leave `scripts/calibrate_objectives.py`.

## 15. Migration Notes

The old `calibration/config/config.json` remains untouched during the first implementation. The new notebook workflows write only:

```text
calibration/sessions/<session_id>/...
calibration/current_config/...
```

Existing production code can be migrated separately to read from `current_config/`.

During transition:

- Do not delete old config files.
- Do not change runtime code until the new configs are validated on microscope runs.
- Add a small loader later that can read either the old `config.json` or the new split config files if backwards compatibility is needed.

## 16. Acceptance Criteria

Notebook 1 is acceptable when:

- It has a small number of cells.
- It acquires exactly three images for image-to-stage: `home`, `plus_x`, `plus_y`.
- It validates same image size and same pixel size.
- It uses voting registration.
- It writes `image_to_stage_report.json` always.
- It writes `image_to_stage.json` only when registration and D4 checks are trusted.
- It shows magenta/green overlays.
- Promotion is explicit.

Notebook 2 is acceptable when:

- It follows the 5-cell measurement structure:
  - Config
  - Parfocality reference
  - Parfocality target
  - Parcentricity reference
  - Parcentricity target + save
- It records motor shift separately from correction in the report.
- It stores only translation in the production config.
- It computes `translation = motor_shift + correction`.
- It does not move target XY back to `home_xy` before target XY acquisition.
- It uses z-wide for Z and holds z-galvo at 0.
- It uses Brenner focus for Z.
- It uses voting registration for XY.
- It blocks promotable config output on weak XY vote.
- It shows Brenner curve and magenta/green overlay.

The whole system is acceptable when:

- `sessions/<id>/configs/`, `reports/`, `data/`, and `notebooks/` are consistently used.
- `current_config/` is the only live folder.
- Report paths are session-root-relative.
- Unit names are unambiguous: image shifts from registration are in image micrometers.
- Tests cover the math and path behavior without requiring LAS X.

## 17. Key Risks

1. Sign convention mismatch in XY registration.
   - Mitigation: keep the existing `phases.measure_shift_xy` convention and test synthetic shifts.

2. Pixel-size factor accidentally applied twice.
   - Mitigation: document and test that `register_voting` returns micrometers.

3. Weak voting still creates a config.
   - Mitigation: test that weak vote writes report only.

4. Z-stack physical order reversed.
   - Mitigation: test high-Z-to-low-Z conversion from `configure_z_stack`.

5. Operator changes image size or pixel size between cells.
   - Mitigation: validate geometry before every registration and fail loudly.

6. Promotion of stale config.
   - Mitigation: promotion only copies from `session.paths.configs_dir / staging_name`; if a valid config was not produced in this session, promotion fails.

7. Session folder clutter.
   - Mitigation: one session per calibration campaign; re-running overwrites that session's configs/reports/data for the same calibration kind.

## 18. Minimal First Pull Request

If this is implemented incrementally, the first useful PR should contain:

1. `calibration/workflows/common.py`
2. `calibration/workflows/promotion.py`
3. `calibration/workflows/image_to_stage.py`
4. Notebook 1 template
5. Unit tests for paths, schemas, promotion, image-to-stage math, weak-vote behavior

Then add objective-pair workflow and Notebook 2 in the second PR.

This reduces microscope risk because image-to-stage can be validated independently before the more complex objective-pair notebook is introduced.
