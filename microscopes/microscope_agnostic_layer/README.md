# Microscope-Agnostic Layer

[![tests](https://github.com/thomdehoog/smart-microscopy/actions/workflows/tests.yml/badge.svg?branch=microscope-agnostic-layer)](https://github.com/thomdehoog/smart-microscopy/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-blue)](../../LICENSE)
[![code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)](https://github.com/thomdehoog/smart-microscopy/actions/workflows/tests.yml)

One small, consistent interface for driving a microscope from a smart-microscopy
workflow. You discover what is there, connect, and issue plain commands. The same
workflow runs on any microscope that has a driver; your code never imports a
vendor's API.

The layer stays deliberately thin. It holds the session's context and forwards
your intent to the driver; the driver does the real work.

## Overview of functionalities

Everything you can call:

```python
import microscope_agnostic_layer as mic

# 1) Discover and connect
mic.available_microscopes()
mic.connect_to_microscope(vendor=String, microscope=String, api=String, client=String, password=String)

# 2) Define the coordinate system
mic.get_coordinate_system()
mic.set_coordinate_system(objective=String, stage_type=String)

# 3) Capture and activate the instrument state and procedures
mic.get_state()
mic.set_state(Dict)
mic.get_procedure()
mic.set_procedure(Dict)

# 4) Handle stage movements
mic.get_initial_positions()
mic.get_xyz()
mic.set_xyz(x, y, z, stage_types=Dict)

# 5) Acquire
mic.get_acquisitions_options()
mic.acquire(options=Dict)

# 6) Export the data
mic.get_export_data_options()
mic.export_data(options=Dict)

# 7) And session
mic.disconnect()
```

Most steps follow the same pattern: **discover, then apply.** Call a `get_*`
function to see what the microscope supports — each option lists its allowed
values and the one currently active — then pass your choice to the matching
call. Omit an option and the driver keeps its active default, so you only
specify what you want to change.

The steps below are listed in the order you call them.

## The workflow, step by step

### 1. Discover and connect

`available_microscopes()` reads the registry and returns the microscopes you can
connect to, as `{vendor: [(microscope, api), ...]}`. It opens nothing and touches
no hardware. `connect_to_microscope()` then selects the matching driver and opens
the session. After this, every `mic` call goes to that microscope. The driver
does not yet know which objectives or stages the instrument has — only the live
connection can report those, which is the next step.

```python
mic.available_microscopes()   # {"leica": [("stellaris5-01", "navigator-expert")]}
mic.connect_to_microscope(vendor="leica", microscope="stellaris5-01", api="navigator-expert")
```

### 2. Define the coordinate system

A position like `(10, 20, 5)` has no meaning until you fix the reference frame:
which objective you view through and which stage moves. Read the available choices
(each as `options` plus the `active` one), then set them. The stage names
(`motoric`, `galvo`, `piezo`, …) are defined by the driver, not a fixed list, so
read the options and pass one back.

```python
mic.get_coordinate_system()
# {"objective": {"options": ["10x", "20x", "40x"], "active": "10x"}, "stage_types": {...}}
mic.set_coordinate_system(objective="10x", stage_type="motoric")
```

From here on, three things stay separate, so a point keeps the same coordinates
no matter how you reach it:

- **Coordinate system** — you always give coordinates in the motoric stage's
  space. This is the single canonical frame.
- **Stage type** — chosen per axis. Using the piezo for fine Z does not change
  the coordinates you give; it only changes which actuator moves to them.
- **Objective** — switching it moves the optics, not your coordinates. The driver
  applies the offset so the coordinates stay the same.

### 3. Capture and reapply state and procedures

A *state* is a snapshot of the instrument's settings that you can capture now and
reapply later. A *procedure* is a named job the driver knows how to run. Both are
dictionaries that the layer passes along without reading; only the driver
interprets them. A state has two parts:

- an `immutable` part — a fingerprint the driver checks, so you cannot restore
  settings captured on a different instrument, and
- a `mutable` part — the settings that are actually reapplied.

The layer never looks inside either part.

```python
prescan = mic.get_state()                 # {"immutable": {...}, "mutable": {...}}
prescan["mutable"]["laser_power"] = 2.0
mic.set_state(prescan)                     # reapply it later
```

### 4. Move the stage

`get_initial_positions()` returns the positions to visit, captured when you
connected. `get_xyz()` and `set_xyz()` read and set the position in the canonical
(motoric) coordinate system. The optional `stage_types` argument chooses which
actuator moves each axis (for example, the piezo for fine Z) without changing the
coordinates you give.

```python
positions = mic.get_initial_positions()
mic.set_xyz(10, 20, 5, stage_types={"z": "piezo"})   # Z via the piezo
```

### 5. Acquire

`get_acquisitions_options()` lists the acquisition settings the instrument
supports — for example `backlash_correction`, which approaches each position from
a consistent direction so the stage settles at the intended spot before the image
is captured. `acquire(options=...)` captures one dataset with the settings you
choose; any setting you omit uses the active default.

```python
mic.get_acquisitions_options()   # {"backlash_correction": {"options": [True, False], "active": True}}
mic.acquire(options={"backlash_correction": True})
```

### 6. Export the data

`get_export_data_options()` lists the available output `format` and `procedure`.
`export_data(options=...)` writes the result. The options can also include `name`
and `position` values, used in the filename and embedded metadata. Omit `format`
or `procedure` and the driver uses its active default.

```python
mic.get_export_data_options()    # {"format": {...}, "procedure": {...}}
mic.export_data(options={"format": "ome-zarr", "name": "well_A1"})
```

### 7. Close the session

`disconnect()` closes the session when you are finished. It is optional — only
some drivers need an explicit teardown.

```python
mic.disconnect()
```

## A full experiment

`example_experiment.ipynb` runs a complete prescan/target experiment from start
to finish: connect, set the coordinate system, capture both states, get the
positions, then move, acquire, and export at each one. It uses the bundled mock
driver, so it runs without any hardware — open it and step through the cells.

## Adding a microscope

A driver is a set of functions — one per operation — registered under a
`(vendor, microscope, api)` name:

```python
from microscope_agnostic_layer.registry import register

register(
    "leica", "stellaris5-01", "navigator-expert",
    ops={"connect": ..., "capabilities": ..., "set_coordinate_system": ...,
         "get_xyz": ..., "set_xyz": ..., "acquire": ..., "export_data": ...,
         "get_state": ..., "set_state": ..., "get_procedure": ...,
         "set_procedure": ..., "get_initial_positions": ...},
    defaults={"microscope": "stellaris5-01", "api": "navigator-expert"},
)
```

Each function takes the driver's handle as its first argument.
`tests/mock_driver.py` is a complete, readable reference implementation, and
`DESIGN.md` covers the full contract and the planned
`drivers/vendor/microscope/api` layout.

## Tests

```bash
python -m pytest microscopes/microscope_agnostic_layer/tests
```

The test suite and the example notebook both run offline against the mock driver.
