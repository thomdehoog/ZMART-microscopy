# Microscope Agnostic Controller

[![Microscope Agnostic Controller](https://github.com/thomdehoog/smart-microscopy/actions/workflows/microscope-agnostic-controller.yml/badge.svg?branch=microscope-agnostic-layer)](https://github.com/thomdehoog/smart-microscopy/actions/workflows/microscope-agnostic-controller.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-blue)](../../LICENSE)
[![code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)](https://github.com/thomdehoog/smart-microscopy/actions/workflows/microscope-agnostic-controller.yml)

One small, consistent interface for driving a microscope from a workflow. You
pick an instrument, set a reference frame, and issue plain commands. The same
workflow runs on any microscope that has a driver; your code never imports a
vendor's API — the driver talks to the microscope's own API, the controller stays
a thin, easy surface for humans and AI agents alike.

## Overview of functionalities

Everything you can call:

```python
import microscope_agnostic_controller as mac

# 1) Get the available instruments and select one (with its reference frame)
mac.get_instruments()
mac.set_instrument(instrument=Dict, reference_actuators=Dict, reference_objective=String)

# 2) Capture and reapply instrument state
mac.get_state()
mac.set_state(Dict)

# 3) Get additional context the driver provides (e.g. initial positions)
mac.get_context()

# 4) Move the stage
mac.get_xyz()
mac.set_xyz(x, y, z, with_actuators=Dict)

# 5) Acquire data (captures and saves) with the current state and position
mac.get_acquisition_options()
mac.acquire(acquisition_type=String, position_label=String, options=Dict)

# 6) Run a procedure specific to the microscope (e.g. hardware autofocus)
mac.get_procedures()
mac.set_procedure(Dict)

# 7) Close the session
mac.disconnect()
```

Most steps follow the same pattern: **discover, then apply.** Call a `get_*`
function to see what the microscope supports — each option lists its allowed
values and the one currently active — then pass your choice to the matching call.
Omit an option and the driver keeps its active default, so you only specify what
you want to change.

## The workflow, step by step

### 1. Get instruments and connect

`get_instruments()` lists what you can connect to, with no hardware touched. Each
entry has exactly three keys -- a `connection` dict (forwarded untouched to the
driver at connect), the instrument's `objectives` list, and its `actuators`
(a per-axis dict of the actuator options each axis offers) -- so you can choose a
reference objective and per-axis reference actuators. `set_instrument()` then opens
the session and fixes that reference frame in one step. After this, every `mac`
call goes to that microscope.

```python
mac.get_instruments()
# [{"connection": {"vendor": "leica", "microscope": "stellaris5-01",
#                  "api": "navigator-expert", "client": "PythonClient", "api_delay_ms": 250},
#   "objectives": ["10x", "20x", "40x"],
#   "actuators": {"x": ["motoric"], "y": ["motoric"], "z": ["z-galvo", "z-wide"]}}]

instrument = mac.get_instruments()[0]
mac.set_instrument(
    instrument,
    reference_actuators={"x": "motoric", "y": "motoric", "z": "z-wide"},
    reference_objective="10x",
)
```

The `connection` dict carries the `vendor` / `microscope` / `api` identity the
registry keys on, plus any driver-specific connect params (client name, api
delay, host, ...). You can edit it before connecting (e.g. drop in a credential);
the controller forwards it to the driver's `connect` untouched.

The reference frame keeps three things separate, so a point keeps the same
coordinates no matter how you reach it:

- **Coordinate system** — you always give coordinates in the motoric stage's
  space, the single canonical frame.
- **Actuator** — chosen per axis; using the piezo for fine Z does not change the
  coordinates you give, only which actuator moves to them.
- **Objective** — switching it moves the optics, not your coordinates; the driver
  applies the offset.

### 2. Capture and reapply state

A *state* is a snapshot of the instrument's settings you can capture now and
reapply later. It is an opaque dict the driver owns: an `immutable` fingerprint
(so you cannot restore settings from a different instrument) plus a `mutable` part
(what is actually reapplied).

```python
prescan = mac.get_state()                 # {"immutable": {...}, "mutable": {...}}
prescan["mutable"]["laser_power"] = 2.0
mac.set_state(prescan)                     # reapply it later
```

### 3. Get additional context

`get_context()` returns whatever extra read-only context the driver provides — for
example the initial positions captured at connect.

```python
mac.get_context()["initial_positions"]     # [{"x": 0.0, "y": 0.0, "z": 0.0}, ...]
```

### 4. Move the stage

`get_xyz()` and `set_xyz()` read and set the position in the canonical (motoric)
coordinate system. The optional `with_actuators` argument chooses which actuator
moves each axis (for example, the piezo for fine Z) without changing the
coordinates you give.

```python
mac.set_xyz(10, 20, 5, with_actuators={"z": "piezo"})   # Z via the piezo
```

### 5. Acquire (captures and saves)

`get_acquisition_options()` lists the acquisition and saving settings the
instrument supports — for example `backlash_correction` (settles the stage before
the image is captured), `format`, and `procedure`. `acquire()` captures one
dataset and saves it in one call: `acquisition_type` is the kind of scan,
`position_label` names the output file, and `options` carries the settings. Omit a
setting and the driver uses its active default.

```python
mac.get_acquisition_options()
# {"backlash_correction": {...}, "format": {...}, "procedure": {...}}
mac.acquire(acquisition_type="prescan", position_label="A1", options={"format": "ome-zarr"})
```

### 6. Run a procedure

`get_procedures()` lists the named jobs the driver offers (e.g. hardware
autofocus); `set_procedure()` runs one. Procedures are opaque dicts the driver
interprets.

```python
mac.get_procedures()                       # {"autofocus": {...}, ...}
mac.set_procedure({"name": "autofocus"})
```

### 7. Close the session

```python
mac.disconnect()
```

## A full experiment

`example_experiment.ipynb` runs a complete prescan/target experiment end to end:
connect, capture both states, get the positions, then move and acquire at each
one. It uses the bundled mock driver, so it runs without any hardware — open it
and step through the cells.

## Adding a microscope

A driver is a set of functions — one per operation — registered under a
`connection` dict (which carries the `vendor` / `microscope` / `api` identity plus
any connect params), with the objective and stage options it offers:

```python
from microscope_agnostic_controller.registry import register

register(
    {"vendor": "leica", "microscope": "stellaris5-01", "api": "navigator-expert",
     "client": "PythonClient", "api_delay_ms": 250},
    ops={"connect": ..., "acquisition_options": ..., "set_coordinate_system": ...,
         "get_xyz": ..., "set_xyz": ..., "acquire": ...,
         "get_state": ..., "set_state": ..., "get_procedures": ...,
         "set_procedure": ..., "get_context": ...},
    objectives=["10x", "20x", "40x"],
    actuators={"x": ["motoric"], "y": ["motoric"], "z": ["z-galvo", "z-wide"]},
)
```

`connect` receives the whole `connection` dict and returns the driver handle;
every other function takes that handle as its first argument. `tests/mock_driver.py`
is a complete, readable reference implementation.

## Tests

```bash
python -m pytest microscopes/microscope_agnostic_controller/tests
```

The test suite and the example notebook both run offline against the mock driver.

## Author

Thom de Hoog — Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
