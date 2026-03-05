# LASX Driver v6.0.0

Python driver for the Leica STELLARIS confocal microscope via the LAS X Python API. Every command routes through a two-layer dispatch backbone that handles idle-wait, automatic retry on transient errors, readback confirmation, and structured timing and logging.

---

## Quick Start

```python
from lasx import (
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
print(f"Acquired in {result['elapsed']:.1f}s")
```

---

## Import Patterns

```python
# Selective imports (recommended)
from lasx import set_zoom, get_job_settings, acquire

# Namespace import
import lasx
lasx.set_zoom(client, "MyJob", 2.0)

# Legacy shim (backwards compatible)
import driver as drv
drv.set_zoom(client, "MyJob", 2.0)
```

The `driver.py` file at the project root is a thin shim (`from lasx import *`) for existing code.

---

## Configuration

### Stage Safety Limits

Movement commands (`move_xy`, `move_z`) require safety limits to be configured first. All values are in micrometers.

```python
from lasx import set_stage_limits, get_stage_limits

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

The driver uses Python's standard `logging` module under the logger name `"lasx"`.

```python
import logging
logging.getLogger("lasx").setLevel(logging.DEBUG)
```

---

## Basic Workflow

```python
from lasx import (
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
    print(f"Done in {result['elapsed']:.1f}s")
else:
    print(f"Failed: {result['message']}")
```

---

## API Reference

All command functions (`set_*`, `move_*`, `acquire`, `select_job`) accept these common optional parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_retries` | `3` | Transient error retry ceiling |
| `pre_check_timeout` | `None` | Override idle-wait timeout (seconds). `None` uses the profile default (30s for most commands, 60s for acquire) |

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
| `set_objective` | `client, job_name, hw_info, name=None, magnification=None` | Requires `hw_info` from `get_hardware_info()`. Specify either `name` or `magnification` |

### Z-Stack Settings

| Function | Key Parameters | Notes |
|----------|---------------|-------|
| `set_z_stack_definition` | `client, job_name, begin_um=None, end_um=None, old_begin_um=None, old_end_um=None` | `tolerance=1.0` um. Use `old_*` params to reset previous bounds |
| `set_z_stack_step_size` | `client, job_name, step_size_um` | `tolerance=0.5` um |
| `set_z_stack_size` | `client, job_name, size_um` | `tolerance=1.5` um |
| `set_time_definition` | `client, job_name, interval=1, cycles=1, minimize=False` | No readback confirmation |

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
| `set_detector_active` | `client, job_name, setting_index, beam_route, activate` | No readback confirmation |

### Laser

| Function | Key Parameters | Notes |
|----------|---------------|-------|
| `set_laser_intensity` | `client, job_name, setting_index, beam_route, line_index, value` | `tolerance=0.005`. Value range: 0.0 - 1.0 |
| `set_laser_shutter` | `client, job_name, setting_index, beam_route, activate` | `True` = open, `False` = closed |
| `add_or_remove_laser_line` | `client, job_name, setting_index, beam_route, line_index, wavelength, add=True` | No readback confirmation |

### Filter Wheel

| Function | Key Parameters | Notes |
|----------|---------------|-------|
| `set_filter_wheel_slot` | `client, job_name, setting_index, beam_route, filter_wheel_type, slot_index` | Exact match confirmation |
| `set_filter_wheel_spectrum` | `client, job_name, setting_index, beam_route, filter_wheel_type, position` | `tolerance=1` nm |

### Stage Movement

**`move_xy(client, x, y, unit="um", *, max_retries=3, pre_check_timeout=None, tolerance=20.0)`**

Moves the XY stage to an absolute position. The result dict includes a `"position"` key with the final readback.

- `unit`: `"um"` (micrometers), `"mm"` (millimeters), or `"m"` (meters)
- `tolerance`: position confirmation tolerance in micrometers (default 20.0)

```python
result = move_xy(client, 65_000, 50_000, unit="um")
if result["success"]:
    pos = result["position"]
    print(f"At ({pos['x_um']:.1f}, {pos['y_um']:.1f}) um")
```

**`move_z(client, job_name, z, relative=False, unit="um", z_mode="galvo", *, max_retries=3, pre_check_timeout=None, tolerance=1.0)`**

Moves the Z drive.

- `relative`: if `True`, moves by offset rather than to absolute position
- `z_mode`: `"galvo"`, `"zwide"`, `"both"`, `"finefocus"`, `"microtome"`, or `"none"`
- Readback confirmation only works for absolute `"galvo"` and `"zwide"` moves

### Acquisition & Job Selection

**`acquire(client, job_name, poll_interval=0.1, poll_timeout=None, heartbeat_interval=30.0, settle_time=0.5, start_timeout=15.0, pre_check_timeout=None)`**

Triggers acquisition and blocks until the scan completes. Returns a result dict with an `"elapsed"` key.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `poll_interval` | `0.1` | Seconds between scan status polls |
| `poll_timeout` | `None` | Hard ceiling for completion. `None` = wait indefinitely |
| `heartbeat_interval` | `30.0` | Log interval during long scans |
| `settle_time` | `0.5` | Minimum seconds after fire before accepting idle as completion |
| `start_timeout` | `15.0` | Seconds to wait for scan to start before logging a warning |

**`select_job(client, job_name, poll_timeout=30.0, poll_interval=0.3, settle_time=0.1)`**

Selects a job by name. Returns immediately if the job is already selected. Returns a result dict with an `"elapsed"` key.

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
| `move_xy` | `"position"` | `{"x", "y", "x_um", "y_um"}` — final XY readback |
| `acquire` | `"elapsed"` | `float` — same as `timing["total_s"]` |
| `select_job` | `"elapsed"` | `float` — same as `timing["total_s"]` |

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
2. **`max_confirm_attempts`** (default 3, set per profile) — readback confirmation attempts. On failure, the backbone waits for idle and re-fires the command.

---

## Architecture

### Package Layout

```
lasx/
├── __init__.py    ← public API exports
├── util.py        ← helpers: _make_log_entry, _make_timing, parse_format
├── errors.py      ← error classification + _default_error_check
├── limits.py      ← stage safety limits
├── readers.py     ← get_scan_status, ping, get_jobs, get_job_settings, ...
├── settings.py    ← make_changeable_copy
├── checks.py      ← check_idle
├── confirm.py     ← readback confirmation functions
├── core.py        ← _fire_with_receipt, _fire_block, confirm_and_fire
├── profiles.py    ← CommandProfile dataclass + per-command profiles
└── commands.py    ← set_*, move_*, acquire, select_job
```

### Dependency DAG

Strict hierarchy with no circular imports:

```
util                  ← stdlib only
errors                ← util
limits                ← stdlib only
readers               ← stdlib only
settings              ← util
checks                ← readers, util
confirm               ← readers, settings, util
core                  ← errors, util
profiles              ← checks, confirm, errors
commands              ← core, profiles, confirm, errors, limits, readers, util
```

### Two-Layer Backbone

All commands route through `confirm_and_fire` in `core.py`:

```
confirm_and_fire (outer wrapper)
│
├── _fire_block (inner, up to max_retries + 1 attempts)
│     ├── 1. pre_check_fn()       wait for scanner idle
│     ├── 2. setup_fn(model)      write parameters to API model
│     ├── 3. _fire_with_receipt   UpdateAwaitReceipt transport
│     ├── 4. error_check_fn()     inspect PyApiCommandEcho
│     └── retry on transient error
│
├── confirm_fn()                  readback verification
│
└── on confirm failure (up to max_confirm_attempts):
      ├── correct_fn() or idle wait
      ├── re-fire via _fire_block
      └── re-confirm
```

**Inner layer (`_fire_block`):** Executes the four-step delivery pipeline. Retries on transient errors (e.g. scanner busy). Permanent errors fail immediately.

**Outer layer (`confirm_and_fire`):** Calls the fire block, then runs readback confirmation. If confirmation fails, it waits for idle (or runs a custom correction function), re-fires, and re-confirms.

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
```

Profiles are defined in `profiles.py`. Most commands use `_idle_standard` (30s timeout) as their pre-check. `acquire` uses `_idle_long` (60s). `select_job` has no pre-check.

---

## Extending the Driver

Adding a new command requires changes to four files, following the same pattern as every existing command.

### Step 1: Write a Confirm Function

In `confirm.py`, add a readback function that checks whether the value was applied. If readback is not possible for the command, skip this step.

```python
# confirm.py

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

from .confirm import _confirm_my_param

MY_PARAM = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_my_param,
)
```

### Step 3: Write the Command Wrapper

In `commands.py`, write the public function using the three-phase pattern:

```python
# commands.py

from .profiles import MY_PARAM
from .confirm import _confirm_my_param

def set_my_param(client, job_name, setting_index, value, *,
                 max_retries=3, pre_check_timeout=None, tolerance=0.1):
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
                           tolerance=tolerance),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
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
- `_dispatch` handles all lambda binding, pre-check timeout overrides, and the `confirm_and_fire` call.
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

## Backwards Compatibility

The `driver.py` file at the project root re-exports everything from the `lasx` package:

```python
from lasx import *
```

Existing code using `import driver as drv` continues to work. New code should import from `lasx` directly.
