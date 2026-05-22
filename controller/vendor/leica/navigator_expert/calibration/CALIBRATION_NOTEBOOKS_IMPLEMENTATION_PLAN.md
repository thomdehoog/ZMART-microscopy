# Calibration Notebooks: Implementation Plan

Canonical implementation plan for the smart-microscopy calibration notebooks. Self-contained; an implementer can build it without re-deriving any prior decisions.

This plan supersedes:

- `CALIBRATION_NOTEBOOKS_PLAN.md` (shared draft)
- `CALIBRATION_NOTEBOOKS_PLAN_claude.md` (claude draft)
- `CALIBRATION_NOTEBOOKS_PLAN_codex.md` (codex draft)

It was synthesized from the two comparison documents (`CALIBRATION_NOTEBOOKS_PLAN_compare.md` and `CALIBRATION_NOTEBOOKS_PLAN_comparison.md`), which stay as the decision record.

**Current amendment.** The objective-pair Z workflow is being updated to symmetric ref/target Brenner z-stacks. `CALIBRATION_REF_STACK_UPDATE_PLAN.md` is authoritative for that change. The operator configures z-stacks in LAS X; the notebook triggers the configured acquisition and analyzes the stack.

---

## 1. Scope and Non-Goals

**In scope (v1):**

- Two Jupyter notebooks driving stage motion, acquisition, registration, and analysis.
- Three workflow modules under `calibration/workflows/`.
- Schemas for two production configs and two diagnostic reports.
- Explicit promotion from session staging to `calibration/current_config/`.
- Validation of pixel size and image size at every consumer.

**Out of scope (v1):**

- Image rescaling / pixel-size compensation. Mismatch is a hard error.
- Multi-job `image_to_stage`. One global matrix per rig.
- Auto-promotion. Operator promotes; workflows never do.
- Hard active-objective validation. A lower-level `driver.confirmations.confirm_objective` helper exists, but there is no supported `navigator_expert.driver` API that exposes active-objective readback for notebook workflows. The operator instructions + visual outputs are the v1 boundary (see Key Risks).
- Replacing `calibrate_objectives.py`. It stays during the transition; retirement is a separate change.
- Non-square pixels. Raise in v1.

---

## 2. Design Ethos

1. **Lean and load-bearing.** A field, file, or cell that has no current consumer and prevents no clear failure mode does not ship.
2. **Thin notebook, fat workflow.** Each code cell is one workflow call. No analysis logic in the notebook.
3. **Operator vs. notebook split, enforced by API.** Operator owns LAS X (objective, focus, zoom, scan, channels). Notebook only does stage XY get/move, `read_zwide_um`, z-wide move, acquisition, registration, save, promotion.
4. **Three concerns separated.** `image_to_stage`, `motor_shift`, `correction` are independent failure modes. Production stores only `translation = motor_shift + correction`.
5. **Staging vs. live, explicit promotion.** `sessions/<id>/` is staging. `current_config/` is live. Promotion is a separate function call in its own optional cell.
6. **Production-grade schemas, lean fields.** Versioned and self-describing, with only fields production reads or validates.
7. **Notebook = visual provenance; report = machine provenance.** Inline visuals for humans; reports for tooling. Neither consumed by production.
8. **Trust the operator at the boundary; validate at the API.** Workflows validate image shape and pixel size and raise on mismatch. No rescaling.
9. **Calibration clarity beats switch minimization.** The 5-cell objective notebook is intentional; three operator switches is acceptable.
10. **Strict gating.** Weak voting writes the report and visuals but does NOT write a promotable staging config.

---

## 3. Conceptual Model

Absolute stage coordinates. The reference objective coordinate is the canonical source frame. For a target identified under the reference at `P_ref` and imaged under a target objective:

```
P_target = P_ref + translation
```

Calibration measures:

```
translation = motor_shift + correction
```

- `motor_shift`: stage XY and z-wide deltas the LAS X firmware applies on objective switch. Read by `drv.get_xy(client)` and `drv.read_zwide_um(client, job_name)` before and after the operator switches.
- `correction`: what is still missing after the firmware switch. XY: `register_voting` on the post-switch image vs. the reference image; the result is image-um, mapped to stage-um via `image_to_stage`. Z: target Brenner focus minus the post-switch z-wide readback.

Production reads only:

- `current_config/image_to_stage.json` (per rig)
- `current_config/objective_<from>_to_<to>.json` (per pair)

Reports keep `motor_shift_*`, `correction_*`, registration vote, and reference/target Brenner curves.

---

## 4. Z Model

This rig holds z-galvo at 0 throughout calibration. All Z motion is on z-wide.

- Read: `drv.read_zwide_um(client, job_name)`
- Move: `drv.move_z(client, job_name, z_um, unit="um", z_mode="zwide")`
- The operator configures reference and target z-stacks in LAS X.
- The notebook does **not** configure z-stack range, step size, slice count, direction, or enable/disable state through the API.
- The notebook triggers the already-configured stack acquisition and analyzes the returned/exported stack.
- The operator focuses approximately with the reference objective before the reference stack.
- The operator does **not** manually adjust z-wide on the target side before target measurement.

Parfocality is measured peak-to-peak:

```text
translation_z_um = focus_z_target_um - focus_z_ref_um
```

Both focus values come from Brenner peaks on acquired z-stacks. `home_z_um` remains a diagnostic value for the operator's approximate reference focus, not the final reference focus used in the Z translation.

If stack z positions cannot be read reliably from LAS X metadata, the workflow must fail clearly or accept explicit z-position overrides. It must not guess positions from slice count alone.

---

## 5. Units

Every named quantity, with its units. This is the canonical reference; the most common source of bugs.

| Quantity | Units | Source / Notes |
| --- | --- | --- |
| Stage XY position | um (absolute) | `drv.get_xy` |
| Stage z-wide position | um (absolute) | `drv.read_zwide_um` |
| Pixel size (`pixel_w_um`, `pixel_h_um`) | um per pixel | `drv.parse_tile_geometry`; v1 requires `pixel_w_um == pixel_h_um` |
| Image size in pixels | `[height, width]` (numpy order) | from `ndarray.shape[-2:]` or LAS X geometry |
| Voting registration output (`dx_um`, `dy_um`) | um (image-frame) | `register_voting(ref, tgt, pixel_um)` already multiplies by `pixel_um` internally |
| `image_to_stage` matrix | dimensionless (stage-um per image-um) | 2x2 rotation/reflection, elements in {-1, 0, +1} after D4 snap |
| `fitted_image_to_stage` (pre-snap) | dimensionless | raw measurement before D4 classification |
| `residual_from_d4` | dimensionless | Frobenius norm of (fitted - snapped) |
| `motor_shift_xy_um`, `correction_xy_um`, `translation_xy_um` | um (stage frame, 2-vector) | XY |
| `motor_shift_z_um`, `correction_z_um`, `translation_z_um` | um (z-wide, scalar) | Z |
| `focus_z_ref_um` | um (absolute z-wide) | Brenner peak from the reference z-stack |
| `focus_z_target_um` | um (absolute z-wide) | Brenner peak from the target z-stack |

XY conversion path:

```
[dx_um, dy_um] = register_voting(ref, tgt, pixel_um).{dx_um, dy_um}   # image-um, signed
correction_xy_um = image_to_stage @ [dx_um, dy_um]                     # stage-um
translation_xy_um = motor_shift_xy_um + correction_xy_um                # stage-um
```

Z computation:

```
motor_shift_z_um = z_post - focus_z_ref_um
correction_z_um  = focus_z_target_um - z_post
translation_z_um = motor_shift_z_um + correction_z_um
                 = focus_z_target_um - focus_z_ref_um
```

`image_to_stage` is pure orientation. Scaling lives in `pixel_size_um` (consumed by `register_voting`).

---

## 6. Existing APIs to Reuse

### Driver

```python
import navigator_expert.driver as drv

drv.connect_python_client()
drv.load_stage_config()
drv.apply_stage_limits_from_config(stage_cfg)
drv.get_hardware_info(client)
drv.get_job_settings(client, job_name)
drv.make_changeable_copy(settings)       # normalizes settings["stack"] to begin/end/stepSize/sections/zDrive
drv.parse_tile_geometry(settings)        # returns {pixel_w_um, pixel_h_um, pixels_x, pixels_y, ...}
drv.get_xy(client)                       # returns {x_um, y_um}
drv.move_xy_stage(client, x_um, y_um, unit="um", tolerance=...)
drv.read_zwide_um(client, job_name)
drv.move_z(client, job_name, z_um, unit="um", z_mode="zwide")
drv.move_z(client, job_name, 0.0, unit="um", z_mode="galvo")   # to enforce z-galvo = 0
drv.acquire_frame(client, job_name, backlash_params=...)       # returns (image, exported_path)
drv.acquire_stack(client, job_name, backlash_params=...)       # returns stack array only: (slices, H, W)
drv.check_idle(client, timeout=...)
```

`drv.acquire_single` is **not** a public API. Do not use it.

### Algorithms

```python
from navigator_expert.algorithms import (
    D4_RESIDUAL_MAX,
    VOTING_MIN_AGREE,
    brenner,              # scalar Brenner score for one frame
    brenner_focus,        # optional stack helper if the implementation keeps the full stack
    classify_d4,          # (matrix) -> (label, canonical, residual)
    register_voting,      # (ref, tgt, pixel_um) -> dict
)
```

`register_voting(ref, tgt, pixel_um)` returns:

```python
{
    "dx_um": float,         # image displacement, signed, micrometers
    "dy_um": float,
    "trusted": bool,        # True if confidence >= VOTING_MIN_AGREE
    "confidence": int,      # number of methods that agreed
    "agreeing": list[str],  # which methods agreed
    # additional diagnostic fields per method
}
```

Verified: `algorithms/registration.py:194` (call site) and `:246` (return), `:118` (px-to-um conversion inside individual methods).

### LAS X State Helpers

```python
from navigator_expert.calibration.lib.lasx_state import (
    reset_pan_roi_zstack,
    disable_z_stack,
    # configure_z_stack is intentionally not used in notebook workflows.
    # The operator configures z-stacks in LAS X; the workflow only triggers/acquires/analyzes.
)
```

---

## 7. Architecture

```
Notebook (1 function call per code cell)
  -> Workflow (calibration/workflows/*.py)
       -> Library + algorithms (calibration/lib/*.py, navigator_expert/algorithms/*)
            -> Driver (navigator_expert/driver/*)
                 -> LAS X Python client
```

The notebook imports a workflow module and calls one function per cell. The workflow owns the LAS X client (on the session object), all file I/O, all visualization, and all schema construction. Library + algorithms do the measurement math. Driver talks to LAS X.

No new `calibration/lib/registration.py`. Registration lives in `navigator_expert/algorithms/`.

---

## 8. File Layout

```
controller/vendor/leica/navigator_expert/calibration/

  workflows/                          # NEW
    __init__.py
    common.py                         # SessionPaths, ImageGeometry, helpers
    image_to_stage.py
    objective_pair.py
    promotion.py

  lib/                                # EXISTING -- unchanged
    phases.py
    lasx_state.py

  notebooks/                          # canonical templates (source-tree only)
    calibrate_image_to_stage.ipynb
    calibrate_objective_pair.ipynb
    _bootstrap.py                     # locates navigator_expert on sys.path

  scripts/
    calibrate_objectives.py           # DEPRECATED; retired separately
```

Runtime data does NOT live under the package tree. The operator declares
`SESSIONS_ROOT` and `LIVE_ROOT` at the top of each notebook's Step 1.
Layout under those operator-owned roots:

```text
<LIVE_ROOT>/                          # LIVE -- production reads from here only
  image_to_stage.json
  objective_<from>_to_<to>.json       # one per pair
  archive/<timestamp>_<name>.json
  .promotion.log

<SESSIONS_ROOT>/                      # STAGING -- one folder per campaign
  <session_id>/
    configs/<kind>.json               # written only when registration is trusted
    reports/<kind>_report.json        # always written
    notebooks/                        # session-local snapshots (optional)
    data/<kind>/...                   # raw TIFFs and z-stacks per calibration
```

**Kind labels** drive subfolders, filenames, and report fields:

- `image_to_stage`
- `objective_<slug(from)>_to_<slug(to)>` (e.g. `objective_10x_to_20x`)

The notebook is run from `calibration/notebooks/` directly. It does not
need to be copied into a session folder for the workflow to run. The
operator may save a copy under `<SESSIONS_ROOT>/<session_id>/notebooks/`
for provenance, but runtime output paths do not depend on notebook
location.

---

## 9. Constants

| Name | Location | Value | Notes |
| --- | --- | --- | --- |
| `VOTING_MIN_AGREE` | `navigator_expert.algorithms` | existing | trust threshold for voting registration |
| `D4_RESIDUAL_MAX` | `navigator_expert.algorithms` | existing | raise threshold for D4 fit |
| `SCHEMA_VERSION` | `common.py` | `1` | bumped on breaking schema changes |

Runtime roots are NOT module constants. Each notebook declares
`SESSIONS_ROOT` and `LIVE_ROOT` at the top of Step 1 and passes them
through to `start_session` and `promote_calibration`. There is no
default; the workflow refuses to start if either is omitted.

No new tunables. Z-stack range/step and stage-move sizes are notebook-cell arguments.

---

## 10. Common Module (`calibration/workflows/common.py`)

### Dataclasses

```python
@dataclass(frozen=True)
class SessionPaths:
    session_dir: Path        # sessions/<session_id>/
    configs_dir: Path        # sessions/<session_id>/configs/
    reports_dir: Path        # sessions/<session_id>/reports/
    notebooks_dir: Path      # sessions/<session_id>/notebooks/
    data_dir: Path           # sessions/<session_id>/data/<kind>/

@dataclass
class ImageGeometry:
    image_size_px: tuple[int, int]   # [height, width] from ndarray.shape[-2:]
    format_px: tuple[int, int]       # [pixels_y, pixels_x] from LAS X geometry
    pixel_size_um: float             # equals pixel_w_um when square
    pixel_w_um: float
    pixel_h_um: float
```

### Helpers

```python
def slug(value: str) -> str:
    """Filesystem-safe objective label. '10x' -> '10x', '100x oil' -> '100x_oil'."""
    return (
        value.strip()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(".", "p")
    )

def objective_config_name(from_objective: str, to_objective: str) -> str:
    return f"objective_{slug(from_objective)}_to_{slug(to_objective)}.json"

def make_session_paths(session_id: str, kind: str) -> SessionPaths:
    session_dir = SESSIONS_ROOT / session_id
    paths = SessionPaths(
        session_dir=session_dir,
        configs_dir=session_dir / "configs",
        reports_dir=session_dir / "reports",
        notebooks_dir=session_dir / "notebooks",
        data_dir=session_dir / "data" / kind,
    )
    for p in (paths.configs_dir, paths.reports_dir, paths.notebooks_dir, paths.data_dir):
        p.mkdir(parents=True, exist_ok=True)
    return paths

def read_job_geometry(client, job_name, image=None) -> ImageGeometry:
    settings = drv.get_job_settings(client, job_name) or {}
    geom = drv.parse_tile_geometry(settings)
    pixel_w = float(geom["pixel_w_um"])
    pixel_h = float(geom["pixel_h_um"])
    if not np.isclose(pixel_w, pixel_h, rtol=0, atol=1e-9):
        raise ValueError("non-square pixels are not supported in v1")
    format_px = (int(geom["pixels_y"]), int(geom["pixels_x"]))
    image_size_px = tuple(image.shape[-2:]) if image is not None else format_px
    return ImageGeometry(image_size_px, format_px, pixel_w, pixel_w, pixel_h)

def assert_geometry_matches(actual, expected_size_px, expected_pixel_size_um, *, context: str) -> None:
    if tuple(actual.image_size_px) != tuple(expected_size_px):
        raise ValueError(f"{context}: image size mismatch ({actual.image_size_px} vs {expected_size_px})")
    if not np.isclose(actual.pixel_size_um, expected_pixel_size_um, rtol=0, atol=1e-9):
        raise ValueError(f"{context}: pixel size mismatch ({actual.pixel_size_um} vs {expected_pixel_size_um})")

def move_xy_and_verify(client, x_um, y_um, *, settle_s=0.5, tolerance_um=0.5) -> None:
    result = drv.move_xy_stage(client, x_um, y_um, unit="um", tolerance=tolerance_um)
    if not result or not result.get("success"):
        raise RuntimeError(f"move_xy_stage failed: {result}")
    time.sleep(settle_s)
    xy = drv.get_xy(client)
    if abs(xy["x_um"] - x_um) > tolerance_um or abs(xy["y_um"] - y_um) > tolerance_um:
        raise RuntimeError(f"stage readback outside tolerance: requested ({x_um}, {y_um}), got ({xy['x_um']}, {xy['y_um']})")

def move_zwide_and_verify(client, job_name, z_um, *, tolerance_um=1.0) -> None:
    result = drv.move_z(client, job_name, z_um, unit="um", z_mode="zwide", tolerance=tolerance_um)
    if not result or not result.get("success"):
        raise RuntimeError(f"move_z zwide failed: {result}")
    actual = drv.read_zwide_um(client, job_name)
    if abs(actual - z_um) > tolerance_um:
        raise RuntimeError(f"z-wide readback outside tolerance: requested {z_um}, got {actual}")

def zero_z_galvo(client, job_name) -> None:
    result = drv.move_z(client, job_name, 0.0, unit="um", z_mode="galvo")
    if not result or not result.get("success"):
        raise RuntimeError(f"move_z galvo zero failed: {result}")

def acquire_frame_to(session, name: str) -> np.ndarray:
    img, exported_path = drv.acquire_frame(
        session.client, session.job_name,
        backlash_params=session.stage_cfg["backlash"],
    )
    out = session.paths.data_dir / f"{name}.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(out, img)
    rel = str(out.relative_to(session.paths.session_dir))
    session.raw_files[name] = rel
    session.exported_files[name] = str(exported_path)
    return img

def acquire_stack_to(session, dirname: str) -> np.ndarray:
    stack = drv.acquire_stack(
        session.client, session.job_name,
        backlash_params=session.stage_cfg["backlash"],
    )
    if stack.ndim != 3:
        raise RuntimeError(f"expected z-stack with shape (slices, H, W), got {stack.shape}")
    stack_dir = session.paths.data_dir / dirname
    stack_dir.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(stack):
        out = stack_dir / f"z_{i:03d}.tif"
        tifffile.imwrite(out, img)
        session.raw_files[f"{dirname}/z_{i:03d}"] = str(out.relative_to(session.paths.session_dir))
    return stack

def read_stack_z_positions(client, job_name: str, expected_slices: int,
                           *, override: list[float] | None = None) -> list[float]:
    if override is not None:
        if len(override) != expected_slices:
            raise ValueError("z_positions_um length must match acquired stack slices")
        return [float(v) for v in override]

    raw_settings = drv.get_job_settings(client, job_name) or {}
    normalized = drv.make_changeable_copy(raw_settings)
    stack = normalized.get("stack") or raw_settings.get("stack") or {}
    begin = stack.get("begin")
    end = stack.get("end")
    sections = stack.get("sections")
    step_size = stack.get("stepSize")
    z_drive = stack.get("zDrive", stack.get("mode"))

    # acquire_stack returns images only. Z positions must come from
    # explicit metadata or the operator-supplied override above.
    if begin is None or end is None or sections is None:
        raise RuntimeError("z-stack positions unavailable: missing begin/end/sections in job settings")
    if int(sections) != expected_slices:
        raise RuntimeError("z-stack sections do not match acquired stack slices")
    if z_drive is not None and "wide" not in str(z_drive).lower():
        raise RuntimeError(f"z-stack is not configured for z-wide: {z_drive}")

    positions = np.linspace(float(begin), float(end), int(sections)).tolist()
    if step_size is not None and len(positions) > 1:
        actual_step = abs(positions[1] - positions[0])
        if not np.isclose(actual_step, abs(float(step_size)), rtol=0, atol=1e-6):
            raise RuntimeError("z-stack stepSize does not match begin/end/sections")
    return [float(v) for v in positions]

def write_json_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
```

### Visualization Helpers

```python
def plot_overlay(ref: np.ndarray, tgt: np.ndarray, title: str,
                 *, shift_um=None, pixel_size_um=None) -> Figure: ...
def plot_brenner_curve(z_positions_um: list[float],
                       scores: list[float],
                       peak_z_um: float) -> Figure: ...
```

Magenta = reference, green = target. Return the `Figure`; the workflow should explicitly display figures with `IPython.display.display(fig)` when running in a notebook and include figure paths or handles in the returned summary. `print(summary)` is only for text and must not be relied on to display figures.

---

## 11. Workflow API

### 11.1 `image_to_stage.py`

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
    settle_s: float = 1.0
    image_size_px: tuple[int, int] | None = None
    pixel_size_um: float | None = None
    home_xy: tuple[float, float] | None = None
    images: dict[str, np.ndarray] = field(default_factory=dict)
    raw_files: dict[str, str] = field(default_factory=dict)
    exported_files: dict[str, str] = field(default_factory=dict)
    registrations: dict[str, dict] = field(default_factory=dict)
    fitted_image_to_stage: list[list[float]] | None = None
    image_to_stage: list[list[float]] | None = None
    d4_label: str | None = None              # "-Y +X" etc.
    residual_from_d4: float | None = None
    config_written: bool = False

def start_session(
    session_id: str,
    job_name: str,
    reference_objective: str,
    stage_move_um: float = 30.0,
    settle_s: float = 1.0,
) -> ImageToStageSession: ...

def measure(session: ImageToStageSession) -> ImageToStageSession: ...
def save_and_visualize(session: ImageToStageSession) -> dict: ...
```

### 11.2 `objective_pair.py`

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
    home_z: float | None = None                 # diagnostic operator focus
    focus_z_ref_um: float | None = None
    z_post: float | None = None
    focus_z_target_um: float | None = None
    xy_post: tuple[float, float] | None = None
    ref_image: np.ndarray | None = None
    target_image: np.ndarray | None = None
    ref_z_stack: list[np.ndarray] | None = None
    ref_z_positions_um: list[float] | None = None
    ref_z_brenner: list[float] | None = None
    target_z_stack: list[np.ndarray] | None = None
    target_z_positions_um: list[float] | None = None
    target_z_brenner: list[float] | None = None
    raw_files: dict[str, str] = field(default_factory=dict)
    exported_files: dict[str, str] = field(default_factory=dict)
    motor_shift_xy_um: tuple[float, float] | None = None
    motor_shift_z_um: float | None = None
    correction_xy_um: tuple[float, float] | None = None
    correction_z_um: float | None = None
    translation_xy_um: tuple[float, float] | None = None
    translation_z_um: float | None = None
    registration: dict | None = None
    config_written: bool = False

def start_session(
    session_id: str,
    job_name: str,
    from_objective: str,
    to_objective: str,
    image_to_stage_path: Path | None = None,    # default: current_config/image_to_stage.json
) -> ObjectivePairSession: ...

def measure_parfocality_reference(session, *, z_positions_um: list[float] | None = None) -> ObjectivePairSession: ...
def measure_parfocality_target(session, *, z_positions_um: list[float] | None = None) -> ObjectivePairSession: ...
def measure_parcentricity_reference(session) -> ObjectivePairSession: ...
def measure_parcentricity_target_and_save(session) -> dict: ...
```

### 11.3 `promotion.py`

```python
def promote_calibration(session, staging_name: str, live_path: Path) -> dict:
    """Validate, archive existing live, copy staging to live, log.
    Returns {source, live_path, archived_previous}.
    Raises FileNotFoundError if the staging file does not exist."""
```

---

## 12. Workflow Step-by-Step

### 12.1 `image_to_stage.start_session`

1. `client = drv.connect_python_client()`.
2. `stage_cfg = drv.load_stage_config()`; `drv.apply_stage_limits_from_config(stage_cfg)`.
3. `drv.get_hardware_info(client)` (fail-early if the scope is unreachable).
4. Validate `stage_move_um > 0`.
5. `paths = make_session_paths(session_id, "image_to_stage")`.
6. Return the session. **Do not** change objective, zoom, scan, focus, or channels.

### 12.2 `image_to_stage.measure`

1. `home_xy = drv.get_xy(client)`; store as `(x_um, y_um)`.
2. `img_home = acquire_frame_to(session, "home")`. Store in `session.images["home"]`.
3. Read geometry from `img_home` and the job: `geom = read_job_geometry(client, job_name, img_home)`. Store `pixel_size_um` and `image_size_px` on session.
4. `move_xy_and_verify(client, home_x + stage_move_um, home_y)`.
5. `img_plus_x = acquire_frame_to(session, "plus_x")`. Store.
6. Validate geometry of `img_plus_x` matches `img_home` (`assert_geometry_matches`).
7. `move_xy_and_verify(client, home_x, home_y)`.
8. `move_xy_and_verify(client, home_x, home_y + stage_move_um)`.
9. `img_plus_y = acquire_frame_to(session, "plus_y")`. Store.
10. Validate geometry of `img_plus_y` matches `img_home`.
11. `move_xy_and_verify(client, home_x, home_y)`.
12. Registrations:

    ```python
    vote_x = register_voting(img_home, img_plus_x, pixel_size_um)
    vote_y = register_voting(img_home, img_plus_y, pixel_size_um)
    session.registrations["home_to_plus_x"] = vote_x
    session.registrations["home_to_plus_y"] = vote_y
    ```

13. If `not vote_x["trusted"]` or `not vote_y["trusted"]`: skip the matrix fit; return session. `save_and_visualize` will write the report but no staging config.
14. Else fit the matrix:

    ```python
    M_stage_to_image = np.array([
        [vote_x["dx_um"] / stage_move_um, vote_y["dx_um"] / stage_move_um],
        [vote_x["dy_um"] / stage_move_um, vote_y["dy_um"] / stage_move_um],
    ])
    fitted = -np.linalg.inv(M_stage_to_image)
    label, canonical, residual = classify_d4(fitted)
    session.fitted_image_to_stage = fitted.tolist()
    session.image_to_stage = canonical.tolist()
    session.d4_label = label                        # e.g. "-Y +X"
    session.residual_from_d4 = float(residual)
    ```

    Sign convention matches the existing `phases.measure_sign_convention`.

15. If `residual > D4_RESIDUAL_MAX`: mark `session.d4_accepted = False`, store a clear failure reason ("drift, sparse texture, or too small a stage_move"), and return the session. Do not write a staging config. `save_and_visualize` still writes the diagnostic report and overlays. Otherwise set `session.d4_accepted = True`.
16. Return session.

### 12.3 `image_to_stage.save_and_visualize`

1. Render and display magenta/green overlays for `home`-vs-`plus_x` and `home`-vs-`plus_y`.
2. Build the report (Section 14.3) and write atomically to `paths.reports_dir / "image_to_stage_report.json"`. **Always.**
3. If both registrations are trusted **and** `session.d4_accepted is True`: build the calibration JSON (Section 14.1) and write atomically to `paths.configs_dir / "image_to_stage.json"`. Set `session.config_written = True`.
4. Otherwise leave `session.config_written = False` and write only the report. The summary's `status` string explains why.
5. Return a summary dict (Section 13).

### 12.4 `objective_pair.start_session`

1. Resolve `image_to_stage_path`. Default: `CURRENT_CONFIG_ROOT / "image_to_stage.json"`.
2. If not `image_to_stage_path.exists()`: raise `FileNotFoundError` with "Run calibrate_image_to_stage.ipynb first and promote, or pass an explicit session path."
3. Load and validate the JSON: `schema_version == 1`, `kind == "image_to_stage"`, required fields present, matrix is 2x2, `image_size_px` has length 2, `pixel_size_um > 0`.
4. Connect client; load stage config; apply stage limits; read hardware.
5. Compute `kind = f"objective_{slug(from_objective)}_to_{slug(to_objective)}"`. Set `objective_config_name = f"{kind}.json"`.
6. `paths = make_session_paths(session_id, kind)`.
7. Build and return the session.

Notes:

- No active-objective validation is performed in v1. A lower-level polling helper exists, but there is no supported workflow-level active-objective API yet. The operator is responsible for setting LAS X to the correct objective before each cell. See Key Risks #1.
- The session also reads job geometry on first acquire to enforce pixel-size match against `image_to_stage`.

### 12.5 `measure_parfocality_reference`

Operator: at reference objective, with the reference z-stack configured in LAS X and the image approximately focused via z-wide.

1. Clear reference parfocality outputs, all downstream outputs, and any stale staging config before driver calls.
2. Enforce z-galvo == 0 via `zero_z_galvo(client, job_name)` (existing convention; safe to repeat).
3. `home_xy = drv.get_xy(session.client)`; store as `(x_um, y_um)`.
4. `home_z = drv.read_zwide_um(session.client, session.job_name)`; store as diagnostic operator focus.
5. Trigger the currently configured LAS X z-stack via a stack acquisition helper. Do not configure stack range, step, slice count, or direction through the API.
6. Store stack TIFFs under `data/<kind>/ref_z_stack/z_<i>.tif`.
7. Read z positions with `read_stack_z_positions(...)`: use `drv.get_job_settings(...)`, `drv.make_changeable_copy(...)`, and the stack `begin` / `end` / `sections` metadata, or use explicit `z_positions_um` override. If positions cannot be derived reliably, raise a clear error.
8. Validate stack image size and pixel size against the loaded `image_to_stage` calibration.
9. Compute Brenner score per slice and find `focus_z_ref_um` using the same peak/refinement logic as the target side.
10. Park z-wide at `focus_z_ref_um`.
11. Render the reference Brenner curve inline.
12. Return session. No calibration config is written in this cell.

### 12.6 `measure_parfocality_target`

Operator: at target objective, with the target z-stack configured in LAS X; **must not** have manually adjusted z-wide after switching.

1. Require `focus_z_ref_um` to be set.
2. Clear target parfocality outputs, parcentricity target outputs, and any stale staging config before driver calls.
3. Enforce z-galvo == 0 via `zero_z_galvo(client, job_name)`.
4. `z_post = drv.read_zwide_um(client, job_name)`. Store `session.z_post`.
5. `motor_shift_z_um = z_post - focus_z_ref_um`. Store.
6. Trigger the currently configured LAS X z-stack via the stack acquisition helper. Do not configure stack range, step, slice count, or direction through the API.
7. Store stack TIFFs under `data/<kind>/target_z_stack/z_<i>.tif`.
8. Read z positions with `read_stack_z_positions(...)`: use `drv.get_job_settings(...)`, `drv.make_changeable_copy(...)`, and the stack `begin` / `end` / `sections` metadata, or use explicit `z_positions_um` override. If positions cannot be derived reliably, raise a clear error.
9. Validate stack image size and pixel size against the loaded `image_to_stage` calibration.
10. Compute Brenner score per slice and find `focus_z_target_um`.
11. Compute and store:

    ```python
    correction_z_um = focus_z_target_um - z_post
    translation_z_um = focus_z_target_um - focus_z_ref_um
    ```

    The identity `translation_z_um = motor_shift_z_um + correction_z_um` must hold.
12. Park z-wide at `focus_z_target_um`.
13. Render the target Brenner curve inline.
14. Return session. No calibration config is written in this cell.

### 12.7 `measure_parcentricity_reference`

Operator: switched back to reference objective. Pixel size and image size must match the z-stacks and the image-to-stage calibration.

1. Require `home_xy` and `focus_z_ref_um`.
2. `move_xy_and_verify(client, *session.home_xy)`.
3. `zero_z_galvo(client, job_name)`.
4. `move_zwide_and_verify(client, job_name, session.focus_z_ref_um)`.
5. `ref_image = acquire_frame_to(session, "ref_xy")`. Store.
6. `geom = read_job_geometry(client, job_name, ref_image)`. `assert_geometry_matches(geom, session.image_to_stage_image_size_px, session.image_to_stage_pixel_size_um, context="reference XY image")`.
7. Return session.

### 12.8 `measure_parcentricity_target_and_save`

Operator: switched to target; **must not** have manually adjusted z-wide after switching. Pixel size and image size must match the reference XY image, both z-stacks, and the image-to-stage calibration.

1. Require `focus_z_ref_um`, `focus_z_target_um`, `translation_z_um`, and `ref_image`.
2. `xy_post = drv.get_xy(client)`. Store as `(x_um, y_um)`.
3. `motor_shift_xy_um = (xy_post.x - home_xy[0], xy_post.y - home_xy[1])`. Store.
4. `zero_z_galvo(client, job_name)`.
5. Move z-wide to focus: `move_zwide_and_verify(client, job_name, focus_z_ref_um + translation_z_um)`. This is equivalent to `focus_z_target_um`.
6. `target_image = acquire_frame_to(session, "target_xy")` at the **post-switch XY** (no return to `home_xy`).
7. Validate geometry: `assert_geometry_matches(read_job_geometry(client, job_name, target_image), session.image_to_stage_image_size_px, session.image_to_stage_pixel_size_um, context="target XY image")` and confirm shape matches `ref_image.shape`.
8. Registration:

    ```python
    vote = register_voting(session.ref_image, target_image, session.image_to_stage_pixel_size_um)
    session.registration = vote
    ```

9. If `vote["trusted"]`:

    ```python
    image_shift = np.array([vote["dx_um"], vote["dy_um"]])
    correction_xy = np.asarray(session.image_to_stage) @ image_shift
    translation_xy = np.asarray(session.motor_shift_xy_um) + correction_xy
    session.correction_xy_um = (float(correction_xy[0]), float(correction_xy[1]))
    session.translation_xy_um = (float(translation_xy[0]), float(translation_xy[1]))
    ```

    Write the calibration JSON (Section 14.2) atomically to `paths.configs_dir / session.objective_config_name`. Set `session.config_written = True`.
10. If not trusted: leave `config_written = False`. `correction_xy_um` and `translation_xy_um` stay `None`; the report still includes the raw registration vote for debugging. Staging config is not written.
11. Render magenta/green overlay inline.
12. Write the report (Section 14.4) atomically to `paths.reports_dir / f"{kind}_report.json"`. **Always, after all available fields have been populated.**
13. Return summary dict (Section 13).

### 12.9 `promote_calibration`

Signature:

```python
def promote_calibration(session, staging_name: str, live_path: Path | None = None) -> dict: ...
```

1. `source = session.paths.configs_dir / staging_name`.
2. If not `source.exists()`: raise `FileNotFoundError("No staging config to promote. Review the report. The measurement may have failed validation or weak voting.")`.
3. Read JSON; validate `schema_version == 1` and `kind` matches one of `{"image_to_stage", "objective_translation"}`.
4. If `live_path is None`, set `live_path = CURRENT_CONFIG_ROOT / staging_name`.
5. If `live_path` is provided, first require `Path(live_path).is_absolute()`, then resolve it and require it to be inside `CURRENT_CONFIG_ROOT`. Reject relative paths so notebook cwd cannot redirect live writes.
6. `live_path.parent.mkdir(parents=True, exist_ok=True)`.
7. `archive_dir = live_path.parent / "archive"; archive_dir.mkdir(exist_ok=True)`.
8. `archived = None`. If `live_path.exists()`: read its `created_at`; sanitize to a filename-safe stamp; `archived = archive_dir / f"{stamp}_{staging_name}"`; `shutil.copy2(live_path, archived)`.
9. Copy `source` to `live_path` atomically (write `.tmp`, rename).
10. Append `f"{now_iso()} {data['kind']} {session.session_id} -> {live_path}\n"` to `CURRENT_CONFIG_ROOT / ".promotion.log"`.
11. Return `{"source": str(source), "live_path": str(live_path), "archived_previous": str(archived) if archived else None}`.

---

## 13. Returned Summary Dicts

`save_and_visualize` (Notebook 1, Cell 3):

```python
{
  "config_written": True,
  "config_path": "sessions/<id>/configs/image_to_stage.json",  # or None
  "report_path": "sessions/<id>/reports/image_to_stage_report.json",
  "d4_label": "-Y +X",
  "d4_accepted": True,
  "residual_from_d4": 0.018,
  "voting": {
    "home_to_plus_x": {"trusted": True, "confidence": 4},
    "home_to_plus_y": {"trusted": True, "confidence": 4},
  },
  "status": "OK -- staging config written",
}
```

`measure_parcentricity_target_and_save` (Notebook 2, Cell 3b):

```python
{
  "config_written": True,
  "config_path": "sessions/<id>/configs/objective_10x_to_20x.json",  # or None
  "report_path": "sessions/<id>/reports/objective_10x_to_20x_report.json",
  "from_objective": "10x",
  "to_objective": "20x",
  "motor_shift_xy_um": [-7.02, 21.07],
  "motor_shift_z_um": -7.71,
  "correction_xy_um": [0.56, 0.47],
  "correction_z_um": 10.11,
  "translation_xy_um": [-6.46, 21.54],
  "translation_z_um": 2.40,
  "focus_z_ref_um": 43.60,
  "focus_z_target_um": 46.00,
  "registration": {"trusted": True, "confidence": 4, "image_shift_um": [0.56, 0.47]},
  "status": "OK -- staging config written",
}
```

When `config_written` is False, `status` says so and the operator knows promotion will raise.

---

## 14. JSON Schemas

All payloads share `schema_version: 1`, `kind: <kind-string>`, `created_at: <iso-8601>`. All writes are atomic.

### 14.1 `image_to_stage.json` (staging + live)

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

- `image_size_px`: `[height, width]`, integers > 0.
- `pixel_size_um`: float > 0, square pixels.
- `image_to_stage`: 2x2 list of floats with elements in {-1, 0, +1} after D4 snap. Dimensionless (stage-um per image-um).

### 14.2 `objective_<from>_to_<to>.json` (staging + live)

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

Runtime use: `P_target = P_ref + translation`.

### 14.3 `image_to_stage_report.json`

All paths under `images` are relative to `sessions/<session_id>/`.

When D4 classification fails, `config_written` is `false` and `d4_accepted` is `false`; `fitted_image_to_stage`, snapped `image_to_stage`, `residual_from_d4`, registrations, and images are still written for debugging.

```json
{
  "schema_version": 1,
  "kind": "image_to_stage_report",
  "created_at": "2026-05-22T14:30:00+02:00",
  "calibration_file": "image_to_stage.json",
  "config_written": true,
  "d4_accepted": true,
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
      "trusted": true,
      "confidence": 4,
      "agreeing": ["pcc", "masked_pcc", "ncc", "orb"]
    },
    "home_to_plus_y": {
      "image_shift_um": [0.18, 29.91],
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

### 14.4 `objective_<from>_to_<to>_report.json`

All paths under `images` are relative to `sessions/<session_id>/`. `image_to_stage_file` is the path that was actually used (live config or session override).

When XY voting is untrusted, `config_written` is `false`; `correction_xy_um` and `translation_xy_um` are `null`, but the raw registration vote and all Z fields remain in the report.

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
  "focus_z_ref_um": 43.6,
  "xy_post_um": [992.98, 2021.07],
  "z_post_um": 35.89,
  "focus_z_target_um": 46.0,
  "motor_shift_xy_um": [-7.02, 21.07],
  "motor_shift_z_um": -7.71,
  "correction_xy_um": [0.56, 0.47],
  "correction_z_um": 10.11,
  "translation_xy_um": [-6.46, 21.54],
  "translation_z_um": 2.40,
  "registration": {
    "image_shift_um": [0.56, 0.47],
    "trusted": true,
    "confidence": 4,
    "agreeing": ["pcc", "masked_pcc", "ncc", "orb"]
  },
  "brenner_ref": {
    "peak_z_um": 43.6,
    "scores": [0.12, 0.28, 0.94, 0.35],
    "z_positions_um": [42.0, 43.0, 44.0, 45.0]
  },
  "brenner_target": {
    "peak_z_um": 46.0,
    "scores": [0.10, 0.21, 0.90, 0.32],
    "z_positions_um": [44.0, 45.0, 46.0, 47.0]
  },
  "images": {
    "ref_z_stack": "data/objective_10x_to_20x/ref_z_stack/",
    "ref_xy": "data/objective_10x_to_20x/ref_xy.tif",
    "target_xy": "data/objective_10x_to_20x/target_xy.tif",
    "target_z_stack": "data/objective_10x_to_20x/target_z_stack/"
  }
}
```

---

## 15. Validation Rules / Error and Trust Matrix

| Condition | Where | Effect |
| --- | --- | --- |
| `stage_move_um <= 0` | `start_session` | raise `ValueError` |
| LAS X unreachable | `start_session` (via `get_hardware_info`) | raise |
| `image_to_stage.json` missing | `objective_pair.start_session` | raise `FileNotFoundError` with hint to run Notebook 1 |
| Non-square pixels | `read_job_geometry` | raise `ValueError` |
| Image geometry mismatch (size or pixel size) | every acquire that gets registered | raise `ValueError` |
| Stage move readback outside tolerance | `move_xy_and_verify` / `move_zwide_and_verify` | raise `RuntimeError` |
| `residual_from_d4 > D4_RESIDUAL_MAX` | `image_to_stage.measure` / `save_and_visualize` | warn; `config_written = False`; report and visuals are written; staging config is NOT written |
| `vote["trusted"]` is `False` (image-to-stage) | `image_to_stage.measure` / `save_and_visualize` | warn; `config_written = False`; report is written; staging config is NOT written |
| `vote["trusted"]` is `False` (objective parcentricity) | `measure_parcentricity_target_and_save` | warn; `config_written = False`; report is written; staging config is NOT written |
| Promotion source missing | `promote_calibration` | raise `FileNotFoundError` |
| Wrong `kind` in source JSON | `promote_calibration` | raise `ValueError` |
| Operator did not switch objective | not hard-validated in v1 | silent wrong calibration; flagged in Key Risks |

The only way for a config file to exist in `sessions/<id>/configs/` is for the workflow to have judged the registration trustworthy.

---

## 16. Promotion Semantics

```
Source: sessions/<session_id>/configs/<staging_name>
Target: calibration/current_config/<staging_name>
```

`promote_calibration(session, staging_name)` uses `CURRENT_CONFIG_ROOT / staging_name` by default. Notebook cells should normally omit `live_path`. If an override is provided, it must resolve to an absolute path inside `CURRENT_CONFIG_ROOT`.

Steps in `promote_calibration` (already itemized in Section 12.9). Log line format:

```
2026-05-22T13:10:04+02:00 image_to_stage 2026-05-22_scope_calibration -> calibration/current_config/image_to_stage.json
```

Promotion is opt-in (separate notebook cell). No save workflow promotes as a side effect.

---

## 17. Notebook Contents

Both notebooks live as canonical templates in `calibration/notebooks/`
and are run from that location. Runtime output paths come from
operator-supplied `SESSIONS_ROOT` and `LIVE_ROOT` declared at the top of
Step 1; the notebook's location on disk does not affect where data is
written.

### 17.0 Layout Rules

- Every workflow code cell has a preceding markdown cell.
- Actual workflow cells are titled `## Step N: <name>`.
- Optional promotion is titled `## Optional: promote to live config`. It is NOT a numbered step.
- Each code cell calls one workflow function. No analysis logic in notebooks.
- ASCII only in markdown, comments, and code.
- The first code cell does `import _bootstrap` to make `navigator_expert` importable; the bootstrap only locates the package on `sys.path` and must never choose runtime write paths.
- Step 1 declares `SESSIONS_ROOT` and `LIVE_ROOT` as plain `Path` literals so the operator can edit them per rig or per user.

### 17.0.1 Notebook Copy Model (Optional, Operator)

The notebook may be saved as a snapshot under
`<SESSIONS_ROOT>/<session_id>/notebooks/` for provenance, but this is
optional and never required for the workflow to run. Runtime output
paths do not depend on notebook location.

### 17.1 `calibrate_image_to_stage.ipynb`

Logical structure: three numbered workflow steps plus optional promotion.

**Title:**

> # Calibrate image_to_stage
>
> Measure the rig's image-to-stage orientation matrix under the reference objective. Run this when microscope/camera geometry changes, or before a new objective-pair calibration campaign.

**Operator preflight:**

> Select the reference objective in LAS X. Set scan format, zoom, channels, pixel size, and image size. Keep these settings identical for all three acquisitions. Focus with z-wide and keep z-galvo at 0. Confirm `ImageTransformation = TOPLEFT` and that no modal dialogs are open in LAS X.

**Step 1: Configure**

> Set the session id, job name, reference objective label, and stage move distance. This opens the LAS X client, applies stage limits, and creates the session folder. No acquisition happens in this step.

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

Note: `stage_move_um=40.0` is convenient for the simulator (20 um grid). For real rig validation, choose the value appropriate for the rig.

**Step 2: Run measurement**

> Acquire and save the home, +X, and +Y raw TIFFs to `data/image_to_stage/`. The workflow runs voting registration, fits the 2x2 image-to-stage matrix, and snaps it to the nearest D4 orientation. No promotable calibration config is written in this step.

```python
session = wf.measure(session)
print(session)
```

**Step 3: Summarize and save**

> Render the magenta/green overlays, write the diagnostic report, and write a staging config only if both registrations are trusted and the D4 fit is accepted. Review the summary before promotion.

```python
summary = wf.save_and_visualize(session)
print(summary)
```

**Optional: promote to live config** (not a numbered step)

> Run this only if `summary["config_written"]` is True and the overlays look correct. Promotion copies the staging config into `current_config/`, archives any previous live file, and appends to the promotion log.

```python
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name="image_to_stage.json",
)
```

### 17.2 `calibrate_objective_pair.ipynb`

Logical structure: five numbered workflow steps plus optional promotion. The five-step structure maps directly to the operator-visible objective changes and keeps rerun/recovery semantics clear.

**Title:**

> # Calibrate objective pair
>
> Measure the absolute translation from one reference objective to one target objective. Production uses the final `translation_xy_um` and `translation_z_um`; the report keeps motor shift and correction values for debugging.

**Operator preflight:**

> A valid `image_to_stage.json` must already exist in `calibration/current_config/`. If it does not, run `calibrate_image_to_stage.ipynb` first and promote its output, or pass an override path via `image_to_stage_path=` in Step 1.
>
> Pixel size and image format must match across the reference z-stack, target z-stack, reference XY image, and target XY image. Since the objectives have different magnifications, matching pixel size usually means changing LAS X zoom between objectives. The lower-magnification objective generally needs proportionally higher zoom.
>
> The operator configures objectives, scan settings, channels, zoom, and z-stack settings in LAS X. The notebook triggers acquisitions, reads positions/images, validates geometry, and analyzes the result.

**Step 1: Configure**

> Set the session id, job name, reference objective, and target objective. This loads the image-to-stage calibration, opens the LAS X client, applies stage limits, and creates the session folder. No acquisition happens in this step.

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

**Step 2: Parfocality reference**

> With the reference objective active, configure the reference z-stack in LAS X. Use the same image size, pixel size, channels, and scan format that will be used for the target z-stack and both parcentricity images. Focus approximately with z-wide before running; the workflow acquires the configured stack and uses the Brenner peak as the reference focus.

```python
session = wf.measure_parfocality_reference(session)
print(session)
```

**Step 3: Parfocality target**

> Switch to the target objective in LAS X and configure the target z-stack. Match the image size, pixel size, channels, and scan format from Step 2; this usually requires a different zoom. Do not manually refocus with z-wide after the objective switch. The workflow acquires the configured stack, finds the target Brenner peak, and computes `translation_z_um` as target focus minus reference focus.

```python
session = wf.measure_parfocality_target(session)
print(session)
```

**Step 4: Parcentricity reference**

> Switch back to the reference objective. Match the same image size and pixel size used in the z-stacks. The workflow returns to `home_xy` and the reference Brenner focus, acquires the reference XY image, and validates geometry against the image-to-stage calibration.

```python
session = wf.measure_parcentricity_reference(session)
print(session)
```

**Step 5: Parcentricity target and save**

> Switch to the target objective. Match the same image size and pixel size used for the reference XY image and the z-stacks. Do not manually refocus with z-wide. The workflow acquires the target XY image at the post-switch XY position, registers it against the reference image, writes the report, and writes a staging config only if the vote is trusted.

```python
summary = wf.measure_parcentricity_target_and_save(session)
print(summary)
```

**Optional: promote to live config** (not a numbered step)

> Run this only if `summary["config_written"]` is True and the Brenner curve plus XY overlay look correct. Promotion copies the staging config into `current_config/`, archives any previous live file, and appends to the promotion log.

```python
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name=session.objective_config_name,
)
```

### 17.3 Bootstrap Helper

`calibration/notebooks/_bootstrap.py` makes `navigator_expert` importable from a notebook regardless of whether the file lives in the canonical templates folder or a `sessions/<session_id>/notebooks/` copy. The helper walks up from `Path(__file__).resolve().parent` and accepts both layouts (the candidate directory itself is `navigator_expert/`, or it contains `navigator_expert/` as a child). It raises a clearly-worded `RuntimeError` if neither layout is found.

Long term, the cleaner fix is packaging: make `navigator_expert` installable and use `pip install -e`. That is out of scope for the notebook layout update; the walk-up keeps the canonical template self-bootstrapping.

---

## 18. Tests

Under `test/test_calibration_workflows.py`. Use mocked driver calls; no LAS X required.

### Common

1. `make_session_paths` creates `configs/`, `reports/`, `notebooks/`, `data/<kind>/`.
2. `objective_config_name("10x", "20x") == "objective_10x_to_20x.json"`; `slug("100x oil") == "100x_oil"`.
3. `assert_geometry_matches` accepts exact match.
4. `assert_geometry_matches` rejects image-size mismatch.
5. `assert_geometry_matches` rejects pixel-size mismatch.
6. Non-square pixels are rejected.

### Image-to-Stage

1. Synthetic perfect orientation: mock `register_voting` for X and Y, verify fitted matrix, snapped matrix, D4 label, `residual_from_d4`, and `config_written == True`.
2. Weak vote: one registration has `trusted=False`. Verify report written, config NOT written.
3. D4 residual too high: synthetic shear shifts. Verify report written, `config_written == False`, and config NOT written.
4. Report image paths are session-root-relative.
5. Overlay smoke test (return figures, do not crash).

### Objective Pair

1. Z translation arithmetic:

    ```
    focus_z_ref = 100, z_post = 94, focus_z_target = 103
    -> motor_shift_z = -6, correction_z = 9, translation_z = 3
    ```

2. XY translation arithmetic with `image_to_stage = identity` and known image shift.
3. Weak XY vote: report written; staging config NOT written.
4. Missing `image_to_stage.json`: `start_session` raises with clear message.
5. Override `image_to_stage_path`: report records the exact resolved path.
6. Target acquire happens at post-switch XY (no return to `home_xy` before the acquire).
7. Reference parcentricity moves to `home_xy` and `focus_z_ref_um` before acquiring.
8. Reference parfocality acquires a z-stack and sets `focus_z_ref_um`.
9. Stack geometry mismatch raises before analysis.
10. Missing or ambiguous stack z positions raises unless explicit positions are supplied.

### Promotion

1. Promote with no existing live: copies to live, appends log.
2. Promote with existing live: archives to `archive/`, replaces live.
3. Missing staging: raises clearly.
4. Wrong `kind`: rejects.
5. Relative `live_path`: rejects clearly, so notebook cwd cannot redirect live writes.

---

## 19. Implementation Order

1. `calibration/workflows/common.py` + tests.
2. `calibration/workflows/promotion.py` + tests.
3. `calibration/workflows/image_to_stage.py` + tests (mocked driver and registration).
4. `calibration/workflows/objective_pair.py` + tests.
5. Notebook templates with markdown + workflow calls only.
6. Manual integration on the rig: image-to-stage first, then a known pair.
7. Run focused calibration tests.
8. Run broader navigator_expert tests if practical.
9. After tests pass, decide whether to deprecate or leave `scripts/calibrate_objectives.py`.

### Minimal First PR

To reduce microscope risk, the smallest useful PR contains:

1. `common.py`
2. `promotion.py`
3. `image_to_stage.py`
4. Notebook 1 template
5. Unit tests for paths, schemas, promotion, image_to_stage math, weak-vote behavior

Objective-pair workflow and Notebook 2 land in a second PR after the first is validated on the rig.

---

## 20. Migration Notes

The old `calibration/config/config.json` remains untouched during the first implementation.

The new workflows write only:

- `calibration/sessions/<session_id>/...`
- `calibration/current_config/...`

During transition:

- Do not delete old config files.
- Do not change runtime code until the new configs are validated on rig runs.
- If backwards compatibility is needed, add a small loader later that can read either the old `config.json` or the new split configs.

Production migration to read from `current_config/` is a separate change after the calibration notebooks are accepted on the rig.

---

## 21. Acceptance Criteria

Notebook 1 is acceptable when:

- It has a small number of cells (config / measure / save / optional promote).
- It acquires exactly three images: `home`, `plus_x`, `plus_y`.
- It validates same image size and same pixel size across the three.
- It uses voting registration via `register_voting(..., pixel_um)`.
- It writes `image_to_stage_report.json` always.
- It writes `image_to_stage.json` only when both registrations are trusted and the D4 fit is accepted.
- It shows magenta/green overlays for both registrations.
- Promotion is explicit.

Notebook 2 is acceptable when:

- It follows the 5-cell measurement structure (config / parfocality ref / parfocality target / parcentricity ref / parcentricity target + save).
- It records `motor_shift_*` and `correction_*` in the report, separately from `translation_*`.
- It stores only `translation_xy_um` and `translation_z_um` in the production config.
- It computes `translation = motor_shift + correction` correctly.
- It does **not** move target XY back to `home_xy` before the target XY acquire.
- Z motion is on z-wide; z-galvo stays at 0.
- It uses Brenner peaks from both reference and target z-stacks for Z.
- It does not configure z-stack settings through the API.
- It uses `register_voting` for XY.
- It blocks promotable config output on weak XY vote.
- It shows reference and target Brenner curves inline and a magenta/green XY overlay.

System is acceptable when:

- `sessions/<id>/configs/`, `reports/`, `data/<kind>/`, `notebooks/` are consistently used.
- `current_config/` is the only live folder.
- Report paths are session-root-relative.
- Unit names are unambiguous: registration shifts are in image micrometers.
- Tests cover math and path behavior without requiring LAS X.

---

## 22. Key Risks

1. **Operator forgets to switch objective.** A lower-level `driver.confirmations.confirm_objective` helper can poll active objective slot, but it is not currently exported as a supported `navigator_expert.driver` workflow API and the notebook config is objective-label based rather than slot based. v1 therefore does not hard-validate the active objective. Failure mode: the cell measures whatever is active, labels it wrong, and produces a silently wrong calibration. **Mitigation:** explicit operator markdown ("verify objective slot in LAS X status bar before running"); the report records `from_objective` and `to_objective` as supplied, plus all stage positions, so post-hoc detection is possible. Revisit in v2 by adding a public `drv.get_active_objective_slot(client, job_name)` or `drv.confirm_active_objective(...)` wrapper.
2. **Sign convention mismatch in XY registration.** Possible if conventions drift between `register_voting` and the D4 fit. **Mitigation:** preserve the existing `phases.measure_sign_convention` formula `image_to_stage_fitted = -inv(stage_to_image)`; unit-test synthetic shifts.
3. **Pixel-size factor applied twice.** Risk if a future change moves the multiplication out of `register_voting`. **Mitigation:** document and test that `register_voting` returns micrometers; this is the v1 contract.
4. **Z-stack physical order or metadata ambiguity.** The operator configures stacks in LAS X, so slice order and absolute z positions must come from reliable metadata or explicit override positions. **Mitigation:** do not guess z positions from slice count; raise clearly when metadata is missing or ambiguous.
5. **Operator changes image size or pixel size between cells.** **Mitigation:** geometry is validated for both z-stacks and both XY images; mismatch raises loudly.
6. **Weak voting still creates a config.** **Mitigation:** explicit `config_written` gate; tests pin the weak-vote path to "report only, no config".
7. **Promotion of stale config.** **Mitigation:** promotion reads only from `session.paths.configs_dir / staging_name`; if a valid config was not produced in this session, promotion raises.
8. **Session folder clutter.** **Mitigation:** one session per campaign; re-running overwrites the same campaign's configs/reports/data per `kind`.

---

## 23. Glossary

| Term | Meaning |
| --- | --- |
| home_xy, home_z | Stage XY and approximate z-wide values recorded under the reference objective before any switch; `home_z` is diagnostic once ref-stack Brenner is used |
| focus_z_ref_um, focus_z_target_um | Absolute z-wide Brenner focus peaks from the reference and target z-stacks |
| motor_shift_* | Stage delta after the firmware objective-switch motion, measured by readback; for Z this is `z_post - focus_z_ref_um` |
| correction_* | Residual error after the firmware switch, measured by image registration (XY) or target Brenner peak relative to `z_post` (Z) |
| translation_* | The full ref-to-target delta; `motor_shift + correction`; what production stores |
| image_to_stage | 2x2 dimensionless rotation/reflection matrix mapping image-um displacements to stage-um displacements |
| D4 | The dihedral group of order 8: the eight axis-aligned rotation/reflection matrices on the plane |
| residual_from_d4 | Frobenius norm of (fitted - snapped) image-to-stage matrix; dimensionless |
| trusted (registration) | `register_voting` returned `confidence >= VOTING_MIN_AGREE` |
| config_written | The workflow judged the calibration good enough and wrote a promotable staging config |
| promotion | The explicit operator action that copies a trusted staging config into `current_config/` |
| current_config | The one folder production reads from; the live calibration |
| sessions/<id> | One calibration campaign; staging for all calibrations from a single sitting |
| kind | A label that identifies a calibration's subfolder, filename, and report fields (`image_to_stage`, `objective_<from>_to_<to>`) |
| slug | A filesystem-safe rendering of an objective label (`"10x"` -> `"10x"`, `"100x oil"` -> `"100x_oil"`) |

---

## 24. Diff Against the Shared Plan

Substantive deltas from `CALIBRATION_NOTEBOOKS_PLAN.md`:

- Units of every named quantity are tabulated (Section 5). The registration API returns image-micrometers, not pixels.
- `image_to_stage` is dimensionless; scaling lives in `pixel_size_um` (which `register_voting` already consumes).
- `ImageGeometry` separates `pixel_w_um` and `pixel_h_um`; non-square pixels raise in v1.
- Move helpers verify readback within tolerance (`move_xy_and_verify`, `move_zwide_and_verify`).
- Acquisition helper owns session-relative paths and tracks both `raw_files` and `exported_files`.
- Parfocality uses reference and target Brenner z-stacks. The operator configures those stacks in LAS X; the workflow triggers/acquires/analyzes them and does not call `configure_z_stack`.
- Driver function names committed: `drv.acquire_frame` and `drv.acquire_stack` (not `acquire_single`); `drv.move_z(client, job_name, z_um, ...)` requires `job_name`.
- Reports use `config_written: bool` rather than `trusted: bool` and include richer registration entries (`{image_shift_um, trusted, confidence, agreeing}`).
- Objective report includes `home_xy_um`, `home_z_um`, `xy_post_um`, `z_post_um` so motor shifts are reproducible from the report.
- Objective report includes full reference and target Brenner curves (`peak_z_um`, `scores`, `z_positions_um`).
- D4 label is human-readable (`"-Y +X"`) rather than a group element code.
- Active-objective validation is deferred to v2 (no confirmed public API). Listed as Key Risk #1.
- Slug helper sanitizes objective filenames against spaces, slashes, dots.
- Migration notes, Acceptance Criteria, Key Risks, and Minimal First PR are added as dedicated sections.

---

## 25. Open Questions

These do not block implementation. They are honest residual uncertainties.

1. **Raw image format.** TIFF for inspectability (default) vs. NumPy `.npy` for fast reload. Recommendation: TIFF.
2. **Z-stack memory.** A 60-um stack at 1-um steps is 61 images per objective. The workflow may hold stacks in memory while also writing TIFFs; can switch to stream-to-disk if file sizes grow.
3. **Promotion archive depth.** Keep all archived live files vs. rotate. Recommend keep all in v1; revisit if size grows.
4. **Voting registration for large stage moves under reference.** Voting is conservative for the image-to-stage test where shifts are known and large. Possibly switch to single phase correlation in v2; keep voting for v1.
5. **Active-objective read API.** Add a `drv.get_active_objective_slot(client)` (or equivalent) and tighten Key Risk #1 in v2.
6. **Parabolic peak refinement at stack edges.** Currently falls back to the discrete index. Acceptable, or should the workflow widen the stack and retry?
