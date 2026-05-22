# Calibration Runtime Roots Plan

## Status

Design plan. Not implemented yet.

This plan replaces the previous "derive runtime output from package path"
approach with explicit operator-owned runtime roots.

## Problem

The calibration workflows currently derive runtime output paths from the
installed source tree:

```python
CALIBRATION_ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROOT = CALIBRATION_ROOT / "sessions"
CURRENT_CONFIG_ROOT = CALIBRATION_ROOT / "current_config"
```

On the rig, `Path(__file__).resolve()` turns a mapped `Z:` path into a UNC
path such as:

```text
\\zmbstaff.core.uzh.ch\zmbstaff\...
```

That made live microscope acquisition write raw TIFFs directly to a network
share. The latest notebook run failed in Step 2 while trying to write
`plus_y.tif`:

```text
FileNotFoundError: [WinError 53] The network path was not found:
'\\zmbstaff.core.uzh.ch\zmbstaff\'
```

This is not a D4-grid bug. The notebook never reached registration or plotting.
It is a path ownership bug.

## Design Principle

Runtime write paths must be explicit.

The source tree stores source code, notebook templates, and workflow logic. It
does not define where acquisition data, reports, staging configs, or live
configs are written.

The operator declares runtime roots visibly in the notebook. If the operator
does not provide them, the workflow refuses to start.

## Hard Rules

1. `sessions_root` is required for every `start_session` call.
2. `live_root` is required for promotion.
3. `image_to_stage_path` is required for `objective_pair.start_session`. No
   inference from a package `current_config` directory.
4. No environment-variable fallback.
5. No default session root.
6. No `Path.home()` fallback.
7. No probe-write helper.
8. No `Path.resolve()` on runtime write targets.
9. Use `Path(...).absolute()` only when normalization is needed.
10. No session output under the package tree unless the operator explicitly
    passes that path.
11. No live config output under the package tree unless the operator explicitly
    passes that path.
12. Missing or invalid roots fail before any stage move, acquisition, or driver
    connection.
13. ASCII only in markdown, comments, code snippets, and test names.

## Runtime Roots

The notebooks declare the roots at the top of Step 1:

```python
from pathlib import Path

SESSIONS_ROOT = Path(
    r"C:\ProgramData\MinicondaZMB\home\t.de\navigator_expert_calibration\sessions"
)
LIVE_ROOT = Path(
    r"C:\ProgramData\MinicondaZMB\home\t.de\navigator_expert_calibration\current_config"
)
```

These are visible, intentional, and operator-owned. If a different rig or user
needs a different location, they edit these two lines.

## Public API

### Image-to-stage

```python
session = wf.start_session(
    session_id="2026-05-22_scope_calibration",
    job_name="Overview",
    reference_objective="10x",
    stage_move_um=40.0,
    sessions_root=SESSIONS_ROOT,
)
```

### Objective pair

```python
session = wf.start_session(
    session_id="2026-05-22_scope_calibration",
    job_name="Overview",
    from_objective="10x",
    to_objective="20x",
    sessions_root=SESSIONS_ROOT,
    image_to_stage_path=LIVE_ROOT / "image_to_stage.json",
)
```

### Promotion

```python
promotion.promote_calibration(
    session,
    staging_name="image_to_stage.json",
    live_root=LIVE_ROOT,
)
```

## Scope

Touch:

- `calibration/workflows/common.py`
- `calibration/workflows/image_to_stage.py`
- `calibration/workflows/objective_pair.py`
- `calibration/workflows/promotion.py`
- `calibration/notebooks/calibrate_image_to_stage.ipynb`
- `calibration/notebooks/calibrate_objective_pair.ipynb`
- `test/test_calibration_workflows.py`
- relevant plan/notebook documentation that still says notebooks must be copied
  into session folders

Do not touch:

- registration math
- D4 sign convention
- D4 thresholds
- stage movement semantics
- objective-pair calibration math
- image processing algorithms

## Implementation Plan

### 1. `common.py`: remove runtime-root globals

Remove:

```python
SESSIONS_ROOT = CALIBRATION_ROOT / "sessions"
```

Do not add:

- `DEFAULT_SESSIONS_ROOT`
- `NAVIGATOR_EXPERT_SESSIONS_ROOT`
- `get_sessions_root`
- probe-write helpers

After this patch, run:

```text
grep -rn "CALIBRATION_ROOT" calibration/
```

If no call site references it, delete the constant from `common.py`. If any
remain for static packaged assets, keep it but add this comment:

```python
# static package assets only; never used for runtime write paths
```

It must not be used to choose runtime write locations.

### 2. `common.py`: make session path creation explicit

Change:

```python
def make_session_paths(session_id: str, kind: str) -> SessionPaths:
```

to:

```python
def make_session_paths(
    session_id: str,
    kind: str,
    sessions_root: str | Path,
) -> SessionPaths:
```

Behavior:

- `sessions_root` is required.
- Convert with `Path(sessions_root).absolute()`.
- Do not call `.resolve()`.
- Build:
  ```python
  session_dir = Path(sessions_root).absolute() / session_id
  ```
- Create:
  - `configs/`
  - `reports/`
  - `notebooks/`
  - `data/<kind>/`
- If directory creation fails, raise a clear `RuntimeError` that includes the
  path and original OS error.

Example:

```python
try:
    p.mkdir(parents=True, exist_ok=True)
except OSError as exc:
    raise RuntimeError(
        f"cannot create calibration session directory {p}: {exc}"
    ) from exc
```

No separate write/delete probe. Directory creation is the fail-fast validation.

#### Path conventions

The current `common.py` module docstring describes summary dicts as using
"calibration-root-relative" paths. That concept is meaningless once
`sessions_root` lives outside the package tree.

After this patch:

- Returned summary dict paths (for example `summary["staging_config_path"]` and
  `summary["report_path"]`) become absolute strings.
- Promotion return paths (for example `live_path`, `archive_path`, and
  `log_path`) become absolute strings.
- Report JSON `images:` paths remain session-root-relative, for example
  `"data/image_to_stage/home.tif"`.
- Report JSON `figures:` paths follow the same session-root-relative
  convention.

Update the module docstring in `common.py` to match. Do not leave the
"calibration-root-relative" wording in place.

### 3. `image_to_stage.py`: require `sessions_root`

Change `start_session` to keyword-only. Every argument crosses the `*` barrier;
no positional calls anywhere. This is a deliberate single-PR breaking change -
the API is small enough that a global update is cheaper than a compatibility
shim.

```python
def start_session(
    *,
    session_id: str,
    job_name: str,
    reference_objective: str,
    sessions_root: str | Path,
    stage_move_um: float = 30.0,
    settle_s: float = 1.0,
) -> ImageToStageSession:
```

Call `make_session_paths(session_id, KIND, sessions_root)` before
`drv.connect_python_client()`, `drv.load_stage_config()`, or any other driver
call. An invalid runtime output root must fail before the workflow touches
hardware or simulator state.

Do not change measurement math, D4 review behavior, PNG diagnostics, or
promotion behavior in this step.

### 4. `objective_pair.py`: require `sessions_root` and `image_to_stage_path`

Change `start_session` so both runtime inputs are required and keyword-only:

```python
def start_session(
    *,
    session_id: str,
    job_name: str,
    from_objective: str,
    to_objective: str,
    sessions_root: str | Path,
    image_to_stage_path: str | Path,
) -> ObjectivePairSession:
```

Do not infer `image_to_stage_path` from a package `current_config` directory.

The notebook passes:

```python
image_to_stage_path=LIVE_ROOT / "image_to_stage.json"
```

Use `Path(image_to_stage_path).absolute()` for this runtime path. Do not call
`.resolve()`.

Call `make_session_paths(..., sessions_root)` before
`drv.connect_python_client()`, `drv.load_stage_config()`, or any other driver
call. Prefer creating the session directory before loading
`image_to_stage_path` as well, so invalid runtime output roots fail first and
the operator gets one clear setup error.

### 5. `promotion.py`: require `live_root`

Remove implicit package-root promotion target behavior:

```python
CURRENT_CONFIG_ROOT = CALIBRATION_ROOT / "current_config"
```

Change promotion API to require `live_root`:

```python
def promote_calibration(
    session,
    staging_name: str,
    *,
    live_root: str | Path,
) -> dict:
```

Behavior:

- Source remains `session.paths.configs_dir / staging_name`.
- Destination is `Path(live_root).absolute() / staging_name`.
- Archive and promotion log live under `live_root`.
- Do not call `.resolve()` on `live_root`.
- Directory creation errors should raise clear `RuntimeError` messages.

This makes promotion explicit and prevents live config writes to the package
tree unless the operator intentionally passes that path.

#### Preserve existing archive and log behavior

The existing collision-counter archive behavior, for example
`image_to_stage_001.json` and `image_to_stage_002.json`, and `.promotion.log`
append behavior are unchanged. Only the root changes: `CURRENT_CONFIG_ROOT`
becomes the operator-supplied `live_root`. Do not re-derive the archive
algorithm.

#### Existing on-disk artifacts

`calibration/sessions/` and `calibration/current_config/` in the package tree
hold real artifacts from prior runs. Leave them in place as historical
artifacts. Do not delete in this patch. Do not migrate. A future cleanup PR can
remove them once nothing references them.

### 6. Notebooks: declare roots visibly

Update Step 1 code in both notebook templates.

Image-to-stage Step 1:

```python
import _bootstrap
from pathlib import Path
from navigator_expert.calibration.workflows import image_to_stage as wf

SESSIONS_ROOT = Path(
    r"C:\ProgramData\MinicondaZMB\home\t.de\navigator_expert_calibration\sessions"
)
LIVE_ROOT = Path(
    r"C:\ProgramData\MinicondaZMB\home\t.de\navigator_expert_calibration\current_config"
)

session = wf.start_session(
    session_id="2026-05-22_scope_calibration",
    job_name="Overview",
    reference_objective="10x",
    stage_move_um=40.0,
    sessions_root=SESSIONS_ROOT,
)
print(session)
```

Image-to-stage promotion cell:

```python
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name="image_to_stage.json",
    live_root=LIVE_ROOT,
)
```

Objective-pair Step 1:

```python
import _bootstrap
from pathlib import Path
from navigator_expert.calibration.workflows import objective_pair as wf

SESSIONS_ROOT = Path(
    r"C:\ProgramData\MinicondaZMB\home\t.de\navigator_expert_calibration\sessions"
)
LIVE_ROOT = Path(
    r"C:\ProgramData\MinicondaZMB\home\t.de\navigator_expert_calibration\current_config"
)

session = wf.start_session(
    session_id="2026-05-22_scope_calibration",
    job_name="Overview",
    from_objective="10x",
    to_objective="20x",
    sessions_root=SESSIONS_ROOT,
    image_to_stage_path=LIVE_ROOT / "image_to_stage.json",
)
print(session)
```

Objective-pair promotion cell:

```python
from navigator_expert.calibration.workflows import promotion

promotion.promote_calibration(
    session,
    staging_name=session.objective_config_name,
    live_root=LIVE_ROOT,
)
```

Notebook markdown should state plainly:

- `SESSIONS_ROOT` is where raw TIFFs, reports, notebook artifacts, and staging
  configs are written.
- `LIVE_ROOT` is where promoted live calibration configs are written.
- The source tree is not used as a runtime storage location unless these roots
  are intentionally pointed there.
- These two paths are the only place runtime data location is configured. Edit
  them per rig or per user.

### 7. Notebook copy model

Remove any instruction that copying notebooks into
`sessions/<session_id>/notebooks/` is required.

The operator may save a copy for provenance, but runtime output paths must not
depend on notebook location. Importability still depends on either
`_bootstrap.py` being usable from the notebook location or a future editable
package install.

The durable provenance is:

- raw TIFFs under `SESSIONS_ROOT`
- reports under `SESSIONS_ROOT`
- staging configs under `SESSIONS_ROOT`
- promotion log/archive under `LIVE_ROOT`

### 8. `_bootstrap.py`

`_bootstrap.py` keeps its current job: locate the `navigator_expert` package
and prepend its parent to `sys.path`. Nothing else.

Add a one-line docstring at the top of `_bootstrap.py`:

```python
"""Import bootstrap only. Must never choose runtime write paths."""
```

Do not add more tree walking. Do not use `_bootstrap.py` to infer
`sessions_root` or `live_root`. The walk-up algorithm itself is acceptable for
finding the package; its result must never feed runtime write roots.

Long-term, packaging with `pip install -e` should remove `_bootstrap.py`
entirely. That is out of scope for this patch.

## Tests

Run first:

```text
grep -n "start_session\|make_session_paths\|promote_calibration" test/
```

Every match must be updated to pass `sessions_root=tmp_path / "sessions"` and
`live_root=tmp_path / "live"` for promotion calls. Roughly 30 of the existing
63 tests instantiate sessions; do the updates in one pass before adding new
tests.

Use shared pytest fixtures if the test file does not already have them:

```python
@pytest.fixture
def sessions_root(tmp_path):
    return tmp_path / "sessions"


@pytest.fixture
def live_root(tmp_path):
    return tmp_path / "live"
```

Add or update tests:

1. `test_make_session_paths_uses_explicit_root`
   - Call `make_session_paths(..., sessions_root=tmp_path / "sessions")`.
   - Assert `session_dir` is under that root.

2. `test_make_session_paths_does_not_use_package_sessions_root`
   - Assert generated paths do not live under
     `navigator_expert/calibration/sessions` unless that exact root is passed.

3. `test_start_session_requires_sessions_root_image_to_stage`
   - Calling without `sessions_root` raises `TypeError`.

4. `test_start_session_requires_sessions_root_objective_pair`
   - Calling without `sessions_root` raises `TypeError`.

5. `test_objective_pair_requires_explicit_image_to_stage_path`
   - Calling without `image_to_stage_path` raises `TypeError`.

6. `test_promotion_requires_live_root`
   - Calling promotion without `live_root` raises `TypeError`.

7. `test_promotion_writes_to_explicit_live_root`
   - Staging config source is under `session.paths.configs_dir`.
   - Live config destination is under `live_root`.
   - Archive and log are under `live_root`.
   - Returned promotion paths are absolute strings.

8. `test_start_session_fails_fast_on_uncreatable_sessions_root`
   - Create a file at `tmp_path / "blocker"`, then pass
     `sessions_root=tmp_path / "blocker" / "sessions"`. `mkdir` raises
     `NotADirectoryError` deterministically on Windows and POSIX.
   - Assert failure happens in `start_session`, before any driver connection,
     stage movement, or acquisition call.
   - Assert the raised exception is a clear `RuntimeError` whose message
     contains the offending path.

9. `test_runtime_paths_preserve_drive_letter`
   - Call `make_session_paths(session_id="probe", kind="image_to_stage",
     sessions_root=tmp_path / "sessions")`.
   - Assert the constructed `session_dir` string starts with the same drive
     letter or prefix as `tmp_path` - no UNC conversion, no symlink
     dereferencing.
   - Skip platform-specific mapped-drive simulation. The contract being tested
     is "no `.resolve()` called on runtime roots," which is observable from the
     path string shape and from a source-level guard.
   - Add a companion source-level check: `grep -n "\.resolve()" calibration/
     workflows/` must not return any line that operates on a runtime write
     target. Either embed this as a subprocess-based test or document it as a
     manual check in the patch summary.

## Acceptance Criteria

1. Step 1 prints a local `session_dir`, not a UNC path.
2. Step 2 writes TIFFs to `SESSIONS_ROOT`.
3. Step 3 writes report JSON and PNGs to `SESSIONS_ROOT`.
4. Promotion writes live configs to `LIVE_ROOT`.
5. Missing `sessions_root` fails immediately in Step 1.
6. Missing `live_root` fails immediately at promotion.
7. Invalid `sessions_root` fails before any driver connection.
8. No raw acquisition write depends on `Z:` or `\\zmbstaff...`.
9. Existing calibration math and D4 diagnostics are unchanged.
10. Full calibration test file passes.

## Non-Goals

- No packaging changes in this patch.
- No changes to registration, voting, D4 math, or thresholds.
- No changes to objective-pair measurement math.
- No hidden environment-variable configuration.
- No fallback paths.
- No write probes.

## Implementation Order

1. Update `common.py` session path API.
2. Update image-to-stage workflow and tests.
3. Update objective-pair workflow and tests.
4. Update promotion API and tests.
5. Update notebooks.
6. Add the `_bootstrap.py` docstring.
7. Remove stale docs that require notebook copies under session folders.
8. Run the full test file. Expected count: 63 + roughly 9 new = about 72,
   allowing for in-place absorption. If the count differs by more than 2,
   investigate before declaring done.
9. Run a microscope smoke test:
   - Step 1 only: confirm local paths.
   - Step 2: confirm TIFFs go local.
   - Step 3: confirm reports and PNGs go local.
   - Promote only after review.
