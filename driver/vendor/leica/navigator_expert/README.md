# Navigator Expert Driver v6.0.0

Python driver for the Leica STELLARIS confocal microscope via the LAS X Python API. Every command routes through a two-layer dispatch backbone that handles idle-wait, automatic retry on transient errors, readback confirmation, and structured timing and logging.

---

## Quick Start

```python
# From a source checkout, make the vendor package importable first.
import sys
from pathlib import Path
sys.path.insert(0, str(Path("driver/vendor/leica").resolve()))

from navigator_expert import (
    set_stage_limits, ping, select_job,
    set_zoom, set_scan_speed, move_xy, acquire,
)

# 1. Configure safety limits (required before any movement)
set_stage_limits(
    x_min=0, x_max=130_000, y_min=0, y_max=130_000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=-5000, z_wide_max=5000,
)

# 2. Check connection (client comes from the LAS X Python API)
assert ping(client), "LAS X not responding"

# 3. Select a job and configure
select_job(client, "MyExperiment")
set_zoom(client, "MyExperiment", 2.0)
set_scan_speed(client, "MyExperiment", 600)

# 4. Move stage and acquire
move_xy(client, 65_000, 65_000)
result = acquire(client, "MyExperiment")
print(f"Acquired in {result['timing']['total_s']:.1f}s")
```

---

## Import Patterns

```python
# Selective imports (recommended)
from navigator_expert import set_zoom, get_job_settings, acquire

# Namespace import
import navigator_expert as lasx
lasx.set_zoom(client, "MyJob", 2.0)
```

---

## Configuration

### Stage Safety Limits

Movement commands (`move_xy`, `move_z`) require safety limits to be configured first. All values are in micrometers.

```python
from navigator_expert import set_stage_limits, get_stage_limits

set_stage_limits(
    x_min=0, x_max=130_000,
    y_min=0, y_max=130_000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=-5000, z_wide_max=5000,
)

print(get_stage_limits())  # Returns a copy of the limits dict
```

If limits are not configured, `move_xy` and `move_z` return an immediate failure result.

### Logging

The driver uses Python's standard `logging` module under the logger name `"navigator_expert"`.

```python
import logging
logging.getLogger("navigator_expert").setLevel(logging.DEBUG)
```

---

## Basic Workflow

```python
from navigator_expert import (
    ping, get_hardware_info, get_job_settings, make_changeable_copy,
    select_job, set_zoom, set_scan_speed, set_image_format,
    set_objective, set_pinhole_airy, set_detector_gain,
    set_laser_intensity, move_xy, move_z, acquire,
    set_stage_limits, get_xy,
)

# Safety limits (once per session)
set_stage_limits(
    x_min=0, x_max=130_000, y_min=0, y_max=130_000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=-5000, z_wide_max=5000,
)

# Connection check
assert ping(client)

# Discover hardware (needed for set_objective)
hw = get_hardware_info(client)

# Select and configure job
select_job(client, "Tiling_10x")
set_objective(client, "Tiling_10x", hw, magnification=10)
set_zoom(client, "Tiling_10x", 1.0)
set_scan_speed(client, "Tiling_10x", 600)
set_image_format(client, "Tiling_10x", "1024 x 1024")

# Per-setting configuration (setting_index=0)
set_pinhole_airy(client, "Tiling_10x", 0, 1.0)
set_detector_gain(client, "Tiling_10x", 0, "PMT1", 800)
set_laser_intensity(client, "Tiling_10x", 0, "Visible", 0, 0.05)

# Read current settings
settings = get_job_settings(client, "Tiling_10x")
ch = make_changeable_copy(settings)
print(f"Zoom: {ch['zoom']['current']}")
print(f"Speed: {ch['scanSpeed']['value']}")

# Stage movement
move_xy(client, 65_000, 65_000, unit="um")
pos = get_xy(client)
print(f"Stage at ({pos['x_um']:.1f}, {pos['y_um']:.1f}) um")

# Z movement
move_z(client, "Tiling_10x", 5.0, unit="um", z_mode="galvo")

# Acquire
result = acquire(client, "Tiling_10x", poll_timeout=300)
if result["success"]:
    print(f"Done in {result['timing']['total_s']:.1f}s")
else:
    print(f"Failed: {result['message']}")
```

---

## API Reference

Most command functions accept these optional overrides. `None` means use
the command profile in `driver/core/profiles.py`.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_retries` | `None` | Override transient error retry ceiling |
| `pre_check_timeout` | `None` | Override idle-wait timeout when the profile has a pre-check |

### Read-Only Functions

| Function | Signature | Returns |
|----------|-----------|---------|
| `ping` | `(client, timeout=5)` | `bool` |
| `get_scan_status` | `(client)` | Status string (e.g. `"eIdle"`, `"eScanRunning"`) |
| `get_jobs` | `(client, timeout=15, poll_interval=0.05, max_retries=3)` | List of job dicts or `None` |
| `get_job_by_name` | `(client, job_name, **kwargs)` | Job dict or `None` |
| `get_selected_job` | `(client, **kwargs)` | Selected job dict or `None` |
| `get_job_settings` | `(client, job_name, timeout=15, poll_interval=0.05, max_retries=3)` | Settings dict or `None` |
| `get_hardware_info` | `(client, timeout=15, poll_interval=0.05, max_retries=3)` | Hardware dict or `None` |
| `get_xy` | `(client, timeout=15, poll_interval=0.05, max_retries=3)` | `{"x", "y", "x_um", "y_um"}` or `None` |

`get_xy` returns positions in both meters (`x`, `y`) and micrometers (`x_um`, `y_um`).

Read-only functions route through `state_readers/` (API, log, or both -
profile-controlled, default API). Pass `diagnostics=True` for a
source-tagged `Reading` with timestamps.

### Change Detection

`state_readers.change_wait` answers "did the state visibly change after my
command?" by alternating API and log reads until one source differs from
its own pre-command baseline (fail-closed `unconfirmed` on timeout; target
tolerance is reported, never enforced). Tunables live in
`profiles.STATE_READERS` (`change_wait_*`).

| Function | Signature | Returns |
|----------|-----------|---------|
| `read_change_baseline` | `(client, datum)` | `ChangeBaseline` (per-source pre-command readings) |
| `wait_for_change` | `(client, datum, baseline, target=None, tolerance=None)` | `ChangeWaitResult` |

`datum` is `"selected_job"` or `"xy"`. Capture the baseline BEFORE firing
the command, after any previous API readback you rely on has converged; the
API leg has no independent event timestamp, while the log leg rejects lines
older than the baseline. See `tests/hardware/probe_change_wait.py` for live
usage and `docs/READER_VALIDATION_SIMULATOR_20260611.md` for measured
behavior.

### Job-Level Settings

| Function | Key Parameters | Notes |
|----------|---------------|-------|
| `set_zoom` | `client, job_name, value` | `tolerance=0.1` |
| `set_scan_speed` | `client, job_name, value` | Integer speed value |
| `set_scan_resonant` | `client, job_name, enable` | `enable`: `True`/`False` |
| `set_scan_mode` | `client, job_name, mode` | e.g. `"xyz"`, `"xzy"` |
| `set_sequential_mode` | `client, job_name, mode` | e.g. `"Line"`, `"Frame"`, `"Stack"` |
| `set_scan_field_rotation` | `client, job_name, angle` | `tolerance=0.5` (degrees) |
| `set_image_format` | `client, job_name, format_str` | Accepts `"512 x 512"` or `(512, 512)` |
| `set_objective` | `client, job_name, hw_info, slot_index=None, name=None, magnification=None` | Requires `hw_info` from `get_hardware_info()`. Specify exactly one of `slot_index`, `name`, or `magnification` |

### Z-Stack Settings

| Function | Key Parameters | Notes |
|----------|---------------|-------|
| `set_z_stack_definition` | `client, job_name, begin_um=None, end_um=None, old_begin_um=None, old_end_um=None` | `tolerance=1.0` um. Use `old_*` params to reset previous bounds |
| `set_z_stack_step_size` | `client, job_name, step_size_um` | `tolerance=0.5` um |
| `set_z_stack_size` | `client, job_name, size_um` | `tolerance=1.5` um |

### Per-Setting Optical

These commands require a `setting_index` to target a specific sequential setting.

| Function | Key Parameters | Notes |
|----------|---------------|-------|
| `set_frame_accumulation` | `client, job_name, setting_index, value` | Exact match confirmation |
| `set_frame_average` | `client, job_name, setting_index, value` | Exact match confirmation |
| `set_line_accumulation` | `client, job_name, setting_index, value` | Exact match confirmation |
| `set_line_average` | `client, job_name, setting_index, value` | Exact match confirmation |
| `set_pinhole_airy` | `client, job_name, setting_index, value` | `tolerance=0.05` (Airy units) |

### Detector

| Function | Key Parameters | Notes |
|----------|---------------|-------|
| `set_detector_gain` | `client, job_name, setting_index, beam_route, value` | `tolerance=1.0` |

### Laser

| Function | Key Parameters | Notes |
|----------|---------------|-------|
| `set_laser_intensity` | `client, job_name, setting_index, beam_route, line_index, value` | `tolerance=0.005`. Value range: 0.0 - 1.0 |
| `set_laser_shutter` | `client, job_name, setting_index, beam_route, activate` | `True` = open, `False` = closed |

### Filter Wheel

| Function | Key Parameters | Notes |
|----------|---------------|-------|
| `set_filter_wheel_slot` | `client, job_name, setting_index, beam_route, filter_wheel_type, slot_index` | Exact match confirmation |
| `set_filter_wheel_spectrum` | `client, job_name, setting_index, beam_route, filter_wheel_type, position` | `tolerance=1` nm |

### Stage Movement

**`move_xy(client, x, y, unit="um", *, max_retries=None, pre_check_timeout=None, tolerance=None)`**

Moves the XY stage to an absolute position. The result dict includes a `"position"` key with the requested target position; check `confirmed` and the logs for readback status.

- `unit`: `"um"` (micrometers), `"mm"` (millimeters), or `"m"` (meters)
- `tolerance`: position confirmation tolerance in micrometers (default 20.0)

```python
result = move_xy(client, 65_000, 50_000, unit="um")
if result["success"]:
    pos = result["position"]
    print(f"At ({pos['x_um']:.1f}, {pos['y_um']:.1f}) um")
```

**`move_z(client, job_name, z, unit="um", z_mode="galvo", *, max_retries=None, pre_check_timeout=None, tolerance=None)`**

Moves the Z drive.

- `z_mode`: `"galvo"` or `"zwide"`
- Readback confirmation checks the requested absolute Z position.

### Acquisition & Job Selection

**`acquire(client, job_name, poll_interval=None, poll_timeout=None, heartbeat_interval=None, start_timeout=None, pre_check_timeout=None)`**

Triggers acquisition once and blocks until the scan completes. Returns timing in `result["timing"]["total_s"]`.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `poll_interval` | profile | Seconds between scan status polls |
| `poll_timeout` | `None` | Hard ceiling for completion. `None` = wait indefinitely |
| `heartbeat_interval` | profile | Log interval during long scans |
| `start_timeout` | profile | Seconds to wait for scan to start before returning failure |

**`select_job(client, job_name, poll_timeout=None, poll_interval=None)`**

Selects a job by name. Returns immediately if the job is already selected. Returns timing in `result["timing"]["total_s"]`.

### Settings Parsing

**`make_changeable_copy(settings)`** transforms raw job settings JSON (from `get_job_settings`) into a flat, navigable dict with normalized field names.

```python
settings = get_job_settings(client, "MyJob")
ch = make_changeable_copy(settings)
```

Returned structure:

```python
{
    "zoom": {"current": float},
    "scanSpeed": {"value": int, "isResonant": bool},
    "scanMode": str,
    "sequentialMode": str,
    "scanFieldRotation": {"value": float},
    "format": str,                           # e.g. "512 x 512"
    "objective": {"name": str, "magnification": int},

    "activeSettings": [
        {
            "_index": int,
            "_name": str,
            "frameAccumulation": int,
            "frameAverage": int,
            "lineAccumulation": int,
            "lineAverage": int,
            "pinholeAiry": {"value": float},
            "activeDetectors": [
                {"_beamRoute": str, "gain": float, ...}
            ],
            "activeLaserLines": [
                {"_beamRoute": str, "_lineIndex": int, "intensity": float, ...}
            ],
            "filterWheels": [
                {"_beamRoute": str, ...}
            ],
        }
    ],

    # Present only if scan mode involves Z
    "stack": {
        "begin": float,      # um
        "end": float,        # um
        "stepSize": float,   # um
        "size": float,       # um
        "sections": int,
        "zDrive": str,       # e.g. "z-galvo"
    },

    # Z position readback (if available)
    "zPosition": {"galvo": float, "zwide": float},

    # Time series (if present)
    "time": {...},
}
```

Fields prefixed with `_` (`_beamRoute`, `_lineIndex`, `_index`, `_name`) are normalized aliases added by the driver for consistent access.

---

## Result Dictionary

Every command function returns a result dict with this shape:

```python
{
    "success": True,              # Did the command succeed?
    "confirmed": True,            # Readback matched target? (None if no confirmation)
    "message": "Zoom -> 2.0",     # Human-readable description
    "timing": {
        "pre_check_s": 0.05,      # Time waiting for scanner idle
        "setup_s": 0.001,         # Time writing parameters to API model
        "fire_s": 0.018,          # Time for UpdateAwaitReceipt transport
        "check_s": 0.002,         # Time for API error check
        "confirm_s": 0.3,         # Time for readback confirmation
        "total_s": 0.371,         # Wall-clock total
        "attempts": 1,            # Fire-block attempts (1 = no retries)
        "confirm_attempts": 1,    # Confirm-wrapper attempts
        "method": "async",        # Dispatch method
    },
    "logs": [                     # Timestamped diagnostic trace
        {"ts": 1709568000.0, "level": "info", "msg": "..."},
    ],
}
```

**Additional keys per command:**

| Command | Extra Key | Value |
|---------|-----------|-------|
| `move_xy` | `"position"` | Requested target position: `{"x", "y", "x_um", "y_um"}` |

---

## Error Handling

### Checking Results

```python
result = set_zoom(client, "MyJob", 2.0)

if not result["success"]:
    print(f"Failed: {result['message']}")
    for entry in result["logs"]:
        if entry["level"] in ("warning", "error"):
            print(f"  [{entry['level']}] {entry['msg']}")
```

### Error Classification

Errors from the LAS X API are classified as either **permanent** (fail immediately) or **transient** (retry up to `max_retries` times).

**Permanent errors** (no retry):
- `"out of range"`, `"is invalid"`, `"invalid block identifier"`
- `"invalid detector"`, `"invalid light source"`
- `"not defined"`, `"not found"`, `"has been adjusted"`, `"not implemented"`

**Transient errors** (retry):
- `"being scanned"`, `"cannot be set while"`, `"block is being"`
- `"busy"`, `"locked"`, `"timeout"`, `"timed out"`

Unknown errors are treated as permanent (conservative: fail immediately rather than retry indefinitely). Permanent patterns take priority when a message matches both categories.

### Retry Behavior

The backbone has two retry ceilings:

1. **`max_retries`** (default 3) — transient error retries inside the fire block. Total attempts = `max_retries + 1`.
2. **`max_confirm_attempts`** (default 3, set per profile) — readback confirmation attempts. Setting profiles may re-fire between failed readback windows and still return `success=True, confirmed=False` if LAS X never reports the requested state. Acquisition profiles fire once only.

---

## Architecture

### Package Layout

```
driver/vendor/leica/navigator_expert/
+-- README.md
+-- __init__.py          # public facade for LAS X driver commands
+-- core/                # commands, readers, confirmations, profiles
+-- templates/           # template file I/O, strip/restore, transactions
+-- positions/           # XML/RGN/LRP parsing and tile-position planning
+-- acquisition/         # capture, LAS X files, OME fixes, save chain
+-- stage/               # stage limits, movement, current-state loader
+-- experimental/        # LRP mutation helpers without live readback
+-- tests/               # offline driver tests and immutable test data

calibration/vendor/leica/navigator_expert/
+-- current/             # adopted measured state: calibration.json
+-- core/                # calibration model + notebook implementation
+-- notebooks/           # operator calibration notebooks
+-- tests/               # calibration unit/integration tests

limits/vendor/leica/navigator_expert/
+-- defaults.json        # configured physical microscope envelope
+-- current.json         # last active working envelope
```

### Dependency DAG

Strict hierarchy with no circular imports:

```
core.utils             -> stdlib only
core.errors            -> core.utils
stage.limits           -> stdlib only
state_readers.api_reader -> core.utils, stdlib
state_readers.log_reader -> state_readers.api_reader, core.settings,
                            core.utils, core.profiles, stdlib
state_readers.router     -> state_readers.api_reader,
                            state_readers.log_reader, core.profiles, stdlib
core.settings          -> core.utils
core.prechecks         -> state_readers, core.utils
core.confirmations     -> state_readers, core.settings, core.utils
core.dispatch          -> core.errors, core.utils
core.profiles          -> core.prechecks, core.confirmations, core.errors
core.commands          -> core.dispatch, core.profiles, core.confirmations,
                          state_readers, core.utils, stage.limits
templates/*            -> file/template operations above API readback
acquisition/*          -> capture, LAS X file arrival, and OME metadata fixes
stage/*                -> stage safety and backlash-aware movement
calibration/.../core.model -> adopted calibration state + coordinate transforms
```

### Two-Layer Backbone

All commands route through `confirm_and_fire` in `driver/core/dispatch.py`:

```
confirm_and_fire (outer wrapper)
│
├── _fire_block (inner, up to max_retries + 1 attempts)
│     ├── 1. pre_check_fn()       wait for scanner idle
│     ├── 2. setup_fn(model)      write parameters to API model
│     ├── 3. fire API command     UpdateAwaitReceipt or UpdateAsync
│     ├── 4. error_check_fn()     inspect PyApiCommandEcho
│     └── retry on transient error
│
├── confirm_fn()                  readback verification
│
└── on confirm failure (up to max_confirm_attempts):
      ├── profile decides readback-only retry or idle/correction + re-fire
      └── re-confirm
```

**Inner layer (`_fire_block`):** Executes the four-step delivery pipeline. Retries on transient errors (e.g. scanner busy). Permanent errors fail immediately.

**Outer layer (`confirm_and_fire`):** Calls the fire block, then runs readback confirmation. Profile policy decides whether a failed confirmation re-fires the command or retries readback only. Acquisition profiles disable re-fire so an acquisition command is never sent twice by the confirmation loop.

### Pluggable Function Contract

All pluggable functions follow the same signature: `callable(client) -> {"success": bool, "logs": [...]}`.

Extra parameters are pre-bound with `functools.partial` at profile or command level. The command function binds `client` via lambda. The backbone only sees zero-argument callables.

### CommandProfile

Every command has a `CommandProfile` that stores its complete backbone recipe:

```python
@dataclass
class CommandProfile:
    pre_check_fn: callable = None              # Wait for idle (None to skip)
    error_check_fn: callable = _default_error_check  # Post-fire error check
    confirm_fn: callable = None                # Readback confirmation (None to skip)
    correct_fn: callable = None                # Custom correction (None = idle wait)
    max_retries: int = 3                       # Transient error retries
    max_confirm_attempts: int = 3              # Confirm loop ceiling
    refire_on_unconfirmed: bool = True         # Re-send after failed readback
    success_on_unconfirmed: bool = False       # Non-fatal exhausted readback
```

Profiles are defined in `driver/core/profiles.py`. Tolerances, polling intervals, confirmation windows, and acquisition fire-once policy live there rather than being hardcoded in command wrappers.

---

## Extending the Driver

Adding a new command requires changes to four files, following the same pattern as every existing command.

### Step 1: Write a Confirm Function

In `driver/core/confirmations.py`, add a readback function that checks whether the value was applied. If readback is not possible for the command, skip this step.

```python
# confirmations.py

def _confirm_my_param(client, job_name, si, target, tolerance=0.1):
    """Confirm my_param readback is within tolerance."""
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False,
                "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["activeSettings"][si]["myParam"]
        ok = abs(actual - target) < tolerance
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError):
        return {"success": False,
                "logs": [_make_log_entry("debug", "myParam key missing from readback")]}
```

The contract: `_confirm_X(client, ...) -> {"success": bool, "logs": [...]}`.

### Step 2: Create a CommandProfile

In `profiles.py`, import the confirm function and create a profile:

```python
# profiles.py

from .confirmations import _confirm_my_param

MY_PARAM = _leica_setting_profile(_confirm_my_param)
```

### Step 3: Write the Command Wrapper

In `commands.py`, write the public function using the three-phase pattern:

```python
# commands.py

from .profiles import MY_PARAM
from .confirmations import _confirm_my_param

def set_my_param(client, job_name, setting_index, value, *,
                 max_retries=None, tolerance=None):
    """Set my_param for a specific setting index."""
    api_obj = client.PyApiSetMyParamByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.MyParam = value

    return _dispatch(
        client, api_obj,
        f"Setting[{setting_index}].MyParam -> {value}",
        MY_PARAM,
        setup_fn=setup,
        confirm_fn=partial(_confirm_my_param, job_name=job_name,
                           si=setting_index, target=value,
                           tolerance=_profile_value(
                               MY_PARAM, "confirm_tolerance", tolerance)),
        max_retries=max_retries,
    )
```

### Step 4: Export

In `__init__.py`, add to `__all__` and add the import:

```python
# __init__.py

# Add to __all__:
"set_my_param",

# Add import:
from .commands import set_my_param
```

### Notes

- The pattern is identical for every command. Copy an existing command of similar shape.
- `_dispatch` handles lambda binding, profile defaults, and the `confirm_and_fire` call.
- If no readback is possible, omit `confirm_fn` from the `_dispatch` call (the profile's `confirm_fn=None` is used).
- Commands that need no pre-check (like `select_job`) set `pre_check_fn=None` in the profile.

---

## Default Tolerances

| Command | Default Tolerance | Unit |
|---------|-------------------|------|
| `set_zoom` | 0.1 | zoom factor |
| `set_scan_field_rotation` | 0.5 | degrees |
| `set_z_stack_definition` | 1.0 | um |
| `set_z_stack_step_size` | 0.5 | um |
| `set_z_stack_size` | 1.5 | um |
| `set_pinhole_airy` | 0.05 | Airy units |
| `set_detector_gain` | 1.0 | gain units |
| `set_laser_intensity` | 0.005 | fraction (0-1) |
| `set_filter_wheel_spectrum` | 1 | nm |
| `move_xy` | 20.0 | um |
| `move_z` | 1.0 | um |

All tolerances can be overridden per call via the `tolerance` keyword argument.

---

## Import Style

All public functions are exported from the `navigator_expert` package. Use either selective or namespace imports:

```python
# Selective
from navigator_expert import set_zoom, acquire

# Namespace
import navigator_expert as lasx
lasx.set_zoom(client, "MyJob", 2.0)
```
