# Navigator Expert Driver v6.0.0

Python driver for the Leica STELLARIS confocal microscope via the LAS X Python
(CAM) API. Every live command routes through a two-layer dispatch backbone that
handles idle-wait, automatic retry on transient errors, readback confirmation,
and structured timing and logging.

This document is written so that a human **or a coding agent** can use the
driver correctly without reading the source first. If you only read one
section, read **[Orientation](#orientation-which-subsystem-do-i-use)** and
**[Invariants and gotchas](#invariants-and-gotchas)** — they prevent the
mistakes that silently misbehave instead of failing loudly.

## Where this driver sits

```
drivers/leica/stellaris5_y42h93/navigator_expert/   <-- THIS package (Leica/LAS X vendor driver)
  calibration/        adopted calibration + notebooks
  limits/             physical stage envelope (JSON)
shared/output_layout/   lab-wide file naming + layout (save() depends on this; at repo root)
```

`navigator_expert` is the **vendor-specific** layer: it speaks the Leica LAS X
CAM API and knows about LAS X file formats (`.lrp`/`.rgn`/`.xml` templates, OME
exports). It is one vendor implementation that the wider microscope-agnostic
layer builds on top of. Keep vendor-specific assumptions (LAS X enum names, log
paths, file layouts) inside this package.

---

## Orientation: which subsystem do I use?

The package has six subsystems. Pick by **what you are trying to do**, not by
file name:

| You want to...                                                      | Use                                            | Returns                          |
|---------------------------------------------------------------------|------------------------------------------------|----------------------------------|
| Change a **live** setting (zoom, speed, gain, laser, z-stack, ...)  | `commands/` `set_*`                            | result dict (`success`/`confirmed`) |
| Move the stage / focus on the **live** scope                        | `move_xy`, `move_z`, `move_galvo_to_pixel`     | result dict                      |
| Select a job, or trigger an acquisition                             | `select_job`, `acquire`                        | result dict / `AcquisitionResult` |
| **Read** current state (xy, status, settings, jobs, hardware)       | `readers/` `get_*`, `ping`               | value or `None`                  |
| **Persist** acquired image data to disk                             | `acquisition/` `save`                          | `SavedAcquisition`               |
| **Parse** a saved LAS X template (tile positions, ROIs, settings)   | `scanfields/` `parse_*`                        | dicts                            |
| Save / load the active experiment template, strip/restore objects   | `save_experiment`, `load_experiment`, `strip_template` | result dict / `None`     |
| Edit a job's parameters in the template **file** (no live scope)    | `experimental/lrp_edits/` `lrp_set_*` via `apply_lrp_change` | dict               |

Two mental distinctions matter most:

1. **Live vs. file.** `set_zoom(...)` talks to the running microscope and
   confirms by reading hardware back. `lrp_set_zoom(...)` edits a `.lrp`
   template file on disk; nothing happens on the scope until LAS X reloads
   that template. There is a deliberate parallel API for each — do not mix them
   up. See [Live commands vs. offline template edits](#live-commands-vs-offline-template-edits).
2. **Command vs. read.** Commands *change* state and go through the dispatch
   backbone. Reads *observe* state and go through `readers`. Reads that
   decide control flow or get persisted have a stricter rule — see
   [Reading state](#reading-state).

---

## Setup and environment

### Importing the package

```python
import sys
from pathlib import Path

# Put drivers/leica/stellaris5_y42h93 on sys.path so `navigator_expert`
# imports. The package also self-bootstraps the microscopes/ root onto
# sys.path so `shared.output_layout` (used by save()) resolves.
sys.path.insert(0, str(Path("drivers/leica/stellaris5_y42h93").resolve()))

import navigator_expert as lasx           # namespace import
from navigator_expert import set_zoom, acquire, save   # or selective import
```

All public functions are exported from the top-level `navigator_expert`
package; both import styles work.

### Connecting to LAS X

```python
from navigator_expert import connect_python_client, ping, require_canonical_scan_orientation

client = connect_python_client()         # opens the CAM client, applies API
                                         # pacing, and verifies ping
assert ping(client)
require_canonical_scan_orientation()      # fail fast if image export is not TOPLEFT
```

`connect_python_client()` loads the LAS X runtime, connects, sets Leica's
client-side pacing knob (`DelayInMilliseconds`, default 250 ms via the
`LASX_API` profile), and pings. It raises `ConnectionError`/`RuntimeError` with
a clear message on failure.

### Machine paths this driver assumes

| Purpose                       | Path                                                                                  |
|-------------------------------|---------------------------------------------------------------------------------------|
| CAM API command log           | `C:\ProgramData\Leica Microsystems\LAS X\lcsCommand.log`                               |
| LAS X dialog/MessageBox log   | `C:\ProgramData\Leica Microsystems\LAS X\MatrixScreener.log`                           |
| CAM API assemblies (runtime)  | `C:\Program Files\Leica Microsystems CMS GmbH\LAS X\AddIns\NavigatorExpert`            |
| Scan-field templates          | `%APPDATA%\Leica Microsystems\LAS X\MatrixScreener6\User_*\ScanningTemplates`          |

These defaults live in `runtime/profiles.py` (`LogReaderProfile`,
`LasxApiProfile`) and are discovered at runtime where possible
(`find_scanning_templates_dir()`). Override via the profile, not by editing
call sites.

### Logging

```python
import logging
logging.getLogger("navigator_expert").setLevel(logging.DEBUG)
```

Every command also returns a structured `logs[]` trace in its result dict (see
[The result dictionary](#the-result-dictionary)); the Python logger and the
result `logs` carry the same diagnostics.

---

## Quick start

```python
from navigator_expert import (
    connect_python_client, ping, require_canonical_scan_orientation,
    set_stage_limits, get_hardware_info, select_job, set_zoom, set_scan_speed,
    move_xy, get_xy, acquire, save,
)
from shared.output_layout import Naming, run_hash

# 1. Connect and validate the scope
client = connect_python_client()
assert ping(client)
require_canonical_scan_orientation()

# 2. Configure safety limits (REQUIRED before any movement), micrometers
set_stage_limits(
    x_min=0, x_max=130_000, y_min=0, y_max=130_000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=-5000, z_wide_max=5000,
)

# 3. Select a job and configure it (live commands return a result dict)
select_job(client, "MyExperiment")
r = set_zoom(client, "MyExperiment", 2.0)
assert r["success"] and r["confirmed"], r["message"]   # see success-vs-confirmed below
set_scan_speed(client, "MyExperiment", 600)

# 4. Move and acquire
move_xy(client, 65_000, 65_000, unit="um")
acq = acquire(client, "MyExperiment")            # -> AcquisitionResult (RAISES on failure)
print(f"Acquired in {acq.command_result['timing']['total_s']:.1f}s")

# 5. Persist the images to the lab-wide layout (separate step from acquire)
naming = Naming(acquisition_type="overview", hash6=run_hash())
saved = save(client, acq, output_root="D:/runs/demo", naming=naming)
print(saved.image_paths)                          # {PlaneIndex(t,z,c): Path, ...}
```

> Note: `acquire()` returns an `AcquisitionResult` dataclass and **raises** on
> failure — it does **not** return a `{"success": ...}` dict. Saving is a
> deliberate second step. See [Acquisition and saving](#acquisition-and-saving).

---

## The command model

All live commands (`set_*`, `move_*`, `acquire`, `select_job`) share one
backbone and one result shape.

### Two-layer dispatch backbone

All commands route through `confirm_and_fire` in `commands/dispatch.py`:

```
confirm_and_fire (outer wrapper)
|
+-- _fire_block (inner, up to max_retries + 1 attempts)
|     +-- 1. pre_check_fn()      wait for scanner idle
|     +-- 2. setup_fn(model)     write parameters to the API model
|     +-- 3. fire API command    UpdateAwaitReceipt (or UpdateAsync)
|     +-- 4. error_check_fn()    inspect PyApiCommandEcho
|     \-- retry on transient error
|
+-- confirm_fn()                 readback verification
|
\-- on confirm failure (up to max_confirm_attempts):
      +-- profile decides: readback-only retry, or idle/correction + re-fire
      \-- re-confirm
```

- **Inner (`_fire_block`)** executes the four-step delivery pipeline and retries
  on transient errors. Permanent errors fail immediately.
- **Outer (`confirm_and_fire`)** runs readback confirmation and, per profile
  policy, may re-fire or retry readback only. Acquisition profiles disable
  re-fire so an acquire is never sent twice.

The backbone is deliberately "dumb": it owns pipeline order, retry ceilings, and
timing, and knows nothing about zoom/objectives/stages. Each command supplies
small zero-argument callables; extra parameters are pre-bound with
`functools.partial`.

### CommandProfile (where tuning lives)

Every command has a `CommandProfile` in `runtime/profiles.py` holding its full
recipe — pluggable callables plus retry/confirm tuning:

```python
@dataclass(frozen=True)
class CommandProfile:
    pre_check_fn          = None                 # wait for idle (None to skip)
    error_check_fn        = _default_error_check  # post-fire error check
    confirm_fn            = None                 # readback confirmation (None to skip)
    correct_fn            = None                 # custom correction (None = idle wait)
    max_retries           = 3                    # transient error retries
    max_confirm_attempts  = 3                    # confirm-loop ceiling
    refire_on_unconfirmed = True                 # re-send after a failed readback
    confirm_timeout       = None
    confirm_tolerance     = None
    success_on_unconfirmed = False               # treat exhausted readback as non-fatal
    # ... plus poll/heartbeat/backoff/async knobs
```

Tolerances, polling intervals, confirmation windows, and the acquisition
fire-once policy live in the profile, **not** hardcoded in the wrapper. Most
setting commands are built from one factory, `_leica_setting_profile`, which
grants three 5 s readback windows and `success_on_unconfirmed=True`.

### The result dictionary

Every live command returns:

```python
{
    "success": True,              # did the command get accepted/applied?
    "confirmed": True,            # did readback match the target? (None if no confirmation)
    "message": "Zoom -> 2.0",
    "timing": {
        "pre_check_s": 0.05,      # waiting for scanner idle
        "setup_s": 0.001,         # writing parameters
        "fire_s": 0.018,          # UpdateAwaitReceipt transport
        "check_s": 0.002,         # API error check
        "confirm_s": 0.3,         # readback confirmation
        "total_s": 0.371,
        "attempts": 1,            # fire-block attempts (1 = no retries)
        "confirm_attempts": 1,
        "method": "async",
    },
    "logs": [ {"ts": ..., "level": "info", "msg": "..."}, ... ],
}
```

| Command   | Extra key   | Value                                              |
|-----------|-------------|----------------------------------------------------|
| `move_xy` | `"position"`| requested target `{"x","y","x_um","y_um"}`         |

#### `success` vs. `confirmed` — read both

This is the single most important contract for setting commands:

- `success=True, confirmed=True` — command accepted **and** readback matched.
- `success=True, confirmed=False` — command was accepted by LAS X, but the
  driver could not read back the requested value within the confirmation
  windows. Most `set_*` profiles set `success_on_unconfirmed=True` so a larger
  workflow can continue, with the mismatch recorded in `logs`. **Do not treat
  `success` alone as "the value was applied"** for setting commands — check
  `confirmed`.
- `success=False` — the command failed to fire (transport, permanent API error,
  failed pre-check). `confirmed` is `None`.

### Error classification (retry policy)

`runtime/errors.py` classifies LAS X API error messages:

- **Permanent** (fail immediately): `out of range`, `is invalid`,
  `invalid block identifier`, `invalid detector`, `invalid light source`,
  `not defined`, `not found`, `has been adjusted`, `not implemented`.
- **Transient** (retry up to `max_retries`): `being scanned`,
  `cannot be set while`, `block is being`, `busy`, `locked`, `timeout`,
  `timed out`.

Unknown errors are treated as **permanent** (conservative). Permanent patterns
take priority when a message matches both. A `HasError` echo whose message
contains `warning` is treated as success (LAS X uses it for non-fatal parameter
adjustments).

### Common per-call overrides

`None` means "use the command's profile."

| Parameter           | Default | Description                                            |
|---------------------|---------|--------------------------------------------------------|
| `max_retries`       | `None`  | Override transient-error retry ceiling                 |
| `pre_check_timeout` | `None`  | Override idle-wait timeout when the profile pre-checks |
| `tolerance`         | `None`  | Override readback tolerance (numeric commands)         |

---

## Command catalogue

All setting commands take `(client, job_name, ...)` and return the result dict
above. `setting_index` targets a specific sequential setting.

### Read-only functions (`readers`)

| Function            | Signature                                   | Returns                                   |
|---------------------|---------------------------------------------|-------------------------------------------|
| `ping`              | `(client, timeout=5)`                       | `bool`                                     |
| `get_scan_status`   | `(client)`                                  | status string (e.g. `"eIdle"`)            |
| `get_jobs`          | `(client, ...)`                             | list of job dicts or `None`               |
| `get_job_by_name`   | `(client, job_name, ...)`                   | job dict or `None`                        |
| `get_selected_job`  | `(client, ...)`                             | selected job dict or `None`               |
| `get_job_settings`  | `(client, job_name, ...)`                   | settings dict or `None`                   |
| `get_hardware_info` | `(client, ...)`                             | hardware dict or `None`                   |
| `get_xy`            | `(client, ...)`                             | `{"x","y","x_um","y_um"}` or `None`       |
| `read_zwide_um`     | `(client, ...)`                             | float or `None`                           |
| `get_fov` / `get_base_fov` | `(client, ...)`                      | field-of-view info                        |
| `get_lasx_settings` | `()`                                        | LAS X advanced settings (orientation, ...) |
| `get_pending_dialog`| `(client, ...)`                             | open LAS X dialog text, if any            |

### Job-level settings

| Function                 | Key parameters                                                                | Notes                          |
|--------------------------|-------------------------------------------------------------------------------|--------------------------------|
| `set_zoom`               | `client, job_name, value`                                                     | `tolerance=0.1`                |
| `set_scan_speed`         | `client, job_name, value`                                                     | integer speed                  |
| `set_scan_resonant`      | `client, job_name, enable`                                                     | `True`/`False`                 |
| `set_scan_mode`          | `client, job_name, mode`                                                       | e.g. `"xyz"`, `"xzy"`          |
| `set_sequential_mode`    | `client, job_name, mode`                                                       | `"Line"`/`"Frame"`/`"Stack"`   |
| `set_scan_field_rotation`| `client, job_name, angle`                                                      | `tolerance=0.5` deg            |
| `set_image_format`       | `client, job_name, format_str`                                                | `"512 x 512"` or `(512, 512)`  |
| `set_objective`          | `client, job_name, hw_info, slot_index=None, name=None, magnification=None`   | needs `get_hardware_info()`; specify exactly one of slot/name/magnification |

### Z-stack

| Function                 | Key parameters                                                                | Notes                |
|--------------------------|-------------------------------------------------------------------------------|----------------------|
| `set_z_stack_definition` | `client, job_name, begin_um=None, end_um=None, old_begin_um=None, old_end_um=None` | `tolerance=1.0` um |
| `set_z_stack_step_size`  | `client, job_name, step_size_um`                                              | `tolerance=0.5` um   |
| `set_z_stack_size`       | `client, job_name, size_um`                                                   | `tolerance=1.5` um   |

### Per-setting optical / detector / laser / filter wheel

| Function                    | Key parameters                                                                       | Notes                |
|-----------------------------|--------------------------------------------------------------------------------------|----------------------|
| `set_frame_accumulation`    | `client, job_name, setting_index, value`                                             | exact match          |
| `set_frame_average`         | `client, job_name, setting_index, value`                                             | exact match          |
| `set_line_accumulation`     | `client, job_name, setting_index, value`                                             | exact match          |
| `set_line_average`          | `client, job_name, setting_index, value`                                             | exact match          |
| `set_pinhole_airy`          | `client, job_name, setting_index, value`                                             | `tolerance=0.05` AU  |
| `set_detector_gain`         | `client, job_name, setting_index, beam_route, value`                                 | `tolerance=1.0`      |
| `set_laser_intensity`       | `client, job_name, setting_index, beam_route, line_index, value`                     | `tolerance=0.005`, 0-1 |
| `set_laser_shutter`         | `client, job_name, setting_index, beam_route, activate`                              | `True`=open          |
| `set_filter_wheel_slot`     | `client, job_name, setting_index, beam_route, filter_wheel_type, slot_index`         | exact match          |
| `set_filter_wheel_spectrum` | `client, job_name, setting_index, beam_route, filter_wheel_type, position`           | `tolerance=1` nm     |

### Stage, acquisition, job selection

- **`move_xy(client, x, y, unit="um", *, max_retries=None, pre_check_timeout=None, tolerance=None)`**
  Absolute XY move (`unit` = `"um"`/`"mm"`/`"m"`, default `tolerance=20.0` um).
  Result includes `"position"`. Fires async; confirms by reading the stage back;
  `success_on_unconfirmed=True`.
- **`move_z(client, job_name, z, unit="um", z_mode="galvo", ...)`**
  Z move (`z_mode` = `"galvo"`/`"zwide"`, default `tolerance=1.0` um).
- **`move_galvo_to_pixel(...)`** Pans the galvo so a given pixel reaches FOV
  centre (uses an LRP transaction internally; special-case command).
- **`select_job(client, job_name, poll_timeout=None, poll_interval=None)`**
  Selects a job by name; no-op if already selected. Confirmation legs are built
  per call (api/log/hybrid) from `StateReaderProfile.selected_job_confirm_source`
  (default **hybrid**).
- **`acquire(client, job, *, poll_interval=None, poll_timeout=None, heartbeat_interval=None, start_timeout=None, pre_check_timeout=None)`**
  Triggers one acquisition and blocks until the scan completes. Returns an
  **`AcquisitionResult`** (raises `RuntimeError` on failure). See below.

### Settings parsing helper

`make_changeable_copy(settings)` turns raw `get_job_settings(...)` JSON into a
flat, normalized dict (`zoom`, `scanSpeed`, `scanMode`, `activeSettings[...]`
with `activeDetectors`/`activeLaserLines`/`filterWheels`, `stack`, `zPosition`,
...). Fields prefixed `_` (`_beamRoute`, `_lineIndex`, `_index`, `_name`) are
driver-added aliases for stable access. This is the schema the `_confirm_*`
functions read back against.

---

## Reading state

`readers/` answers "what is the scope doing right now?" three ways, chosen
per datum by `StateReaderProfile` in `runtime/profiles.py`:

- **`api`** — a single CAM API read (run in a capped worker thread).
- **`log`** — parse the LAS X log files into a `Snapshot` (never blocks the CAM
  API; can be stale).
- **`hybrid`** — race API against the log; first *admissible* evidence wins.

Why three modes exist: **the CAM API can hang.** The log mirror is a hang-proof
fallback and the in-flight API read cap prevents overlapping CAM reads. Defaults
are `api` for almost everything; `selected_job` confirmation defaults to
`hybrid` because a stale API readback can report the wrong job after a switch.

### The freshness rule (important)

> A fresh-by-age **log** value must never decide whether a command fires, how it
> is parameterized, whether it confirms, or what metadata/calibration is
> persisted.

Reads that drive control flow (prechecks, early exits, command-parameterizing
reads, confirmations, post-write readbacks) or that become persisted truth
(calibration geometry, canonical OME physical metadata) **must** use the API leg
or the gated confirmation path. Cold status reads may use the log. This rule is
documented on `StateReaderProfile` and is enforced by choosing modes per datum.

### Change detection

`readers.change_wait` answers "did the state visibly change after my
command?" by alternating API and log reads until one source differs from **its
own** pre-command baseline:

```python
baseline = read_change_baseline(client, "xy")   # capture BEFORE firing
move_xy(client, x, y)
res = wait_for_change(client, "xy", baseline, target=(x, y))  # fail-closed unconfirmed on timeout
```

`datum` is `"selected_job"` or `"xy"`. Capture the baseline *before* firing.
Target tolerance is **reported, never enforced**. Tunables live in
`profiles.STATE_READERS` (`change_wait_*`).

### Diagnostics

Pass `diagnostics=True` to a routed reader to get a source-tagged `Reading`
(value + `source` + `observed_at` + `age_s`) instead of the bare value.

---

## Acquisition and saving

Acquisition and persistence are **two separate steps**. `acquire()` only drives
the microscope; `save()` collects whatever files LAS X produced and writes them
into the lab-wide layout.

```python
acq = acquire(client, "MyJob")          # AcquisitionResult; RAISES on failure
saved = save(client, acq, output_root, naming)   # SavedAcquisition
```

### `AcquisitionResult` (from `acquire`)

```python
@dataclass(frozen=True)
class AcquisitionResult:
    job: str
    started_at: float        # used by save() to identify the fresh files
    finished_at: float
    command_result: dict     # the dispatch result dict (timing, logs, ...)
```

`acquire()` records *when* the named job was acquired and returns that context.
It does **no** file detection, OME validation, or copying.

### `save()` and the output layout

```python
save(client, acq, output_root, naming, *,
     lineage=None, fix_ome=True, cleanup_source=False, exporter=None) -> SavedAcquisition
```

`save()` picks a **source exporter**, which collects LAS X's output into a
writer-agnostic product, then persists it as canonical single-plane OME-TIFFs
plus per-position OME-XML companions, updating `summary.json`. Two exporters
exist and are both production-active (selected by
`config.profiles.ACQUISITION.save_exporter`, default `lasx_native_autosave`):

| Exporter              | LAS X source                              | `cleanup_source` |
|-----------------------|-------------------------------------------|------------------|
| `navigator_expert`    | flat per-plane export tree + sidecar XML  | supported        |
| `lasx_native_autosave`| native AutoSave multipage OME-TIFF + project | not supported (it is a LAS X project container) |

The output layout and filenames come from `shared.output_layout`:

```
output_root/
  <acquisition_type>/
    data/
      <acquisition_type>_<hash6>_k.....m.....g.....p....._t....._v00_c00_z......ome.tiff
      metadata/
        <acquisition_type>_<hash6>_k.....m.....g.....p....._t....._v00.ome.xml   (companion, omits c/z)
        vendor/<exporter>/...                                                    (preserved provenance)
  summary.json                                                                   (per-plane lineage records)
```

Build a `Naming` with the 8 dimensional slots (`k,m,g,p,t,v,c,z`, all default 0)
and a `hash6` (base36 seconds-since-2026-01-01 UTC, sortable):

```python
from shared.output_layout import Naming, run_hash, build_layout
naming = Naming(acquisition_type="overview", hash6=run_hash())   # acquisition_type: kebab-case
# Or use build_layout(output_root, experiment) to create the run dir + plan.
```

`save()` returns a `SavedAcquisition(image_paths, xml_paths, naming)` mapping
`PlaneIndex(t,z,c)` -> `Path` and `PositionIndex(t,v)` -> `Path`.

### OME metadata

- `acquisition/ome.py` repairs known Leica OME schema violations (e.g. laser
  `Wavelength="0"`) in place, preserving byte formatting.
- `acquisition/ome_canonical.py` generates clean canonical SMART OME for the
  saved files from vendor metadata + job settings.
  `save(..., fix_ome=True)` validates/repairs each written file.

---

## Scan-field files and templates

LAS X stores experiment configuration as scan-field template files
(`.lrp` job settings, `.rgn` regions/shapes, `.xml` scan fields). `scanfields/`
reads and edits these.

### Parsing saved templates (read-only)

```python
from navigator_expert import parse_lrp, parse_scan_positions, get_rois, diff_lrp

settings = parse_lrp("path/to/template.lrp")     # full job settings tree
positions = parse_scan_positions(xml, rgn)        # tile/region geometry, focus points
```

Parsers (`scanfields/parsers.py`) use stdlib ElementTree with safe type
coercion — no fragile regex. Key entry points: `parse_lrp`, `diff_lrp`,
`parse_scan_positions`, `parse_acquisition_positions`, `parse_base_grid`,
`parse_focus_points`, `parse_rgn_geometries`, `parse_rgn_tile_colors`,
`parse_matrix_settings`, plus accessors `get_master_attrs`, `get_rois`, and
`plan_tiles_from_geometries` (planning).

### Saving / loading the active experiment

```python
from navigator_expert import save_experiment, load_experiment, save_and_read_lrp, get_template_state

save_experiment(client, "template.xml", templates_dir)  # fires save, confirms via file mtime+stable size
load_experiment(client, "template.xml")                  # receipt only; verify with a follow-up save
data = save_and_read_lrp(client)                         # save current experiment + parse_lrp in one call
state = get_template_state()                             # "fresh" | "unstripped" | "stripped"
```

`find_scanning_templates_dir()` locates the templates folder under
`%APPDATA%`. `strip_template`/`restore_template`/`strip_template_in_place`
remove and restore operator-drawn objects (scan fields, regions, focus points)
around an automated run.

---

## Live commands vs. offline template edits

`experimental/lrp_edits/` is a **parallel** API that edits job parameters in the
`.lrp` template file rather than on the live scope. Many functions mirror a live
command by name (`set_zoom` vs. `lrp_set_zoom`, `set_scan_speed` vs.
`lrp_set_scan_speed`, ...). This duplication is intentional: file editing has no
readback, so it cannot share the live confirmation backbone.

Despite the `experimental/` folder name, this code is **load-bearing** (fully
exported, used by `move_galvo_to_pixel`, `disable_roi_scan`, `reset_pan`). Treat
"experimental" as "offline template editor", not "unstable".

### Always edit through the transaction backbone

A raw file edit will not take effect in LAS X and can leave the wrong job
selected. Route every edit through `apply_lrp_change`, which performs
**save -> edit -> reorder -> load -> save -> verify** and preserves the active job:

```python
from navigator_expert import apply_lrp_change
from navigator_expert.experimental.lrp_edits.scan import lrp_set_zoom, lrp_verify_zoom

apply_lrp_change(
    client, "template.xml",
    lrp_set_zoom, "MyJob", 2.0,
    verify_fn=lambda p: lrp_verify_zoom(p, "MyJob", 2.0),
)
```

`reorder_jobs` (called inside the transaction) moves the active job to first
position so LAS X reselects it after the reload. The `lrp_edits` modules also
provide ROI authoring (`make_rectangle`/`make_ellipse`/`make_polygon`,
`lrp_add_roi`, `lrp_clear_rois`) and pixel<->stage<->pan/zoom coordinate math
(`roi_to_pan_zoom`, `mask_contour_to_roi`, `bbox_to_zoom`) — see the detailed
coordinate-frame docstring at the top of `experimental/lrp_edits/roi.py`.

---

## Invariants and gotchas

These are the things that **silently misbehave** instead of failing loudly.
Respect them or downstream results are wrong without an error.

1. **Configure stage limits before any movement.** `move_xy`/`move_z` return an
   immediate failure result if limits are unset. Call `set_stage_limits(...)`
   (or `apply_stage_limits_from_config()`) once per session.
2. **`acquire()` returns an `AcquisitionResult` and raises on failure** — it is
   not a `{"success": ...}` dict and is not subscriptable. Read timing via
   `acq.command_result["timing"]`. Persisting is a separate `save()` call.
3. **Image export must be TOPLEFT.** Call `require_canonical_scan_orientation()`
   at session start. Any other `ImageTransformation` rotates/flips the saved
   TIFF, and all pixel<->stage coordinate math silently misnavigates.
4. **For setting commands, check `confirmed`, not just `success`.** Most `set_*`
   profiles return `success=True, confirmed=False` when LAS X accepted the
   command but readback never matched (`success_on_unconfirmed=True`). The
   mismatch is in `logs`.
5. **Reads that gate control flow or get persisted must use the API leg.** Never
   let a fresh-by-age log value decide whether a command fires, how it is
   parameterized, whether it confirms, or what metadata/calibration is written.
6. **The CAM API can hang.** That is why `readers` has a log mirror and an
   in-flight API read cap. If you add a reader, do not block the API path
   uncancellably.
7. **`select_job` confirmation defaults to `hybrid`.** A stale API readback can
   report the wrong job after a switch; the hybrid race only accepts evidence of
   an actual transition.
8. **Objective changes are best-effort.** The `OBJECTIVE` profile fires once
   with a best-effort confirm (`success_on_unconfirmed=True`). On a manual
   objective turret LAS X may open a "turn the turret manually" dialog
   (surfaced in `MatrixScreener.log` / `get_pending_dialog`). Prefer binding the
   objective through the selected job over switching it live mid-run.
9. **Extending acquisition: `PyApiAcquireJob` silently no-ops without
   `m.JobName`.** It returns in ~0 s with no error if the job name is unset; the
   driver sets it in the command's `setup_fn`. Check the setup callback before
   assuming a LAS X bug.
10. **Edit templates only through `apply_lrp_change`.** A direct `.lrp` edit
    will not take effect and can select the wrong job after reload.
11. **`load_experiment` confirms only the receipt, not the on-disk state.**
    Follow it with `save_experiment` (or use `apply_lrp_change`, which does) to
    verify the load took effect.

---

## Testing

Tests live under `tests/`:

- `tests/unit/` — **offline** unit tests that run without a microscope, against
  committed synthetic fixtures in `tests/data/` (immutable). Cover template
  parsing, strip/restore, position parsers, stage backlash/config, log reader,
  log/state readers, acquisition, and runtime loading.
- `tests/hardware/` — **hardware-gated** probes and smokes that require a live
  LAS X session (export-layout probes, export-metadata comparison, stress and
  validation runs, two-tile save smoke). Do not run these without the scope.

Follow the project's TDD practice: add a failing offline test against synthetic
fixtures (and, where useful, an auto-skipping real-data test) before
implementing, and assert real values, not just shapes.

---

## Extending the driver

Adding a command touches four places, following the pattern every existing
command uses.

### 1. Write a confirm function (`commands/confirmations.py`)

```python
def _confirm_my_param(client, job_name, si, target, tolerance=0.1):
    """Confirm my_param readback is within tolerance."""
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False,
                "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["activeSettings"][si]["myParam"]
        return {"success": abs(actual - target) < tolerance, "logs": []}
    except (KeyError, TypeError, IndexError):
        return {"success": False,
                "logs": [_make_log_entry("debug", "myParam key missing from readback")]}
```

Contract: `_confirm_X(client, ...) -> {"success": bool, "logs": [...]}`. Skip
this step if no readback is possible.

### 2. Create a CommandProfile (`runtime/profiles.py`)

```python
from ..commands.confirmations import _confirm_my_param
MY_PARAM = _leica_setting_profile(_confirm_my_param)
```

### 3. Write the command wrapper (`commands/commands.py`)

```python
from ..config.profiles import MY_PARAM
from .confirmations import _confirm_my_param

def set_my_param(client, job_name, setting_index, value, *,
                 max_retries=None, tolerance=None):
    api_obj = client.PyApiSetMyParamByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.MyParam = value

    return _dispatch(
        client, api_obj, f"Setting[{setting_index}].MyParam -> {value}", MY_PARAM,
        setup_fn=setup,
        confirm_fn=partial(_confirm_my_param, job_name=job_name, si=setting_index,
                           target=value,
                           tolerance=_profile_value(MY_PARAM, "confirm_tolerance", tolerance)),
        max_retries=max_retries,
    )
```

`_dispatch` handles lambda-binding `client`, profile defaults, confirmation
racing, and the `confirm_and_fire` call. Omit `confirm_fn` if there is no
readback. Set `pre_check_fn=None` in the profile for commands that need no idle
wait (like `select_job`).

### 4. Export (`__init__.py`)

Add the name to `__all__` and import it from `.commands.commands`.

The pattern is identical for every command — copy the closest existing one of a
similar shape.

---

## Default tolerances

| Command                     | Default tolerance | Unit          |
|-----------------------------|-------------------|---------------|
| `set_zoom`                  | 0.1               | zoom factor   |
| `set_scan_field_rotation`   | 0.5               | degrees       |
| `set_z_stack_definition`    | 1.0               | um            |
| `set_z_stack_step_size`     | 0.5               | um            |
| `set_z_stack_size`          | 1.5               | um            |
| `set_pinhole_airy`          | 0.05              | Airy units    |
| `set_detector_gain`         | 1.0               | gain units    |
| `set_laser_intensity`       | 0.005             | fraction (0-1)|
| `set_filter_wheel_spectrum` | 1                 | nm            |
| `move_xy`                   | 20.0              | um            |
| `move_z`                    | 1.0               | um            |

All are overridable per call via the `tolerance` keyword.

---

## Dependency DAG (no circular imports)

```
utils          -> stdlib only
commands.errors         -> utils
commands.settings      -> utils
commands.prechecks     -> readers, utils
commands.confirmations -> readers, commands.settings, utils
commands.dispatch      -> commands.errors, utils, readers.log_reader
config.profiles       -> commands.prechecks, commands.confirmations, commands.errors
commands.commands      -> commands.dispatch, config.profiles, commands.confirmations,
                          readers, utils, motion.limits
readers.*        -> api/log/hybrid readers, capabilities, log waits
scanfields.*           -> scan-field file operations above API readback
acquisition.*          -> capture, exporters, OME, save (depends on shared.output_layout)
stage.*                -> stage safety and backlash-aware movement
```
