# ZMART Controller

[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-blue)](../../LICENSE)

The **ZMART Controller** is one small, consistent interface for driving a
microscope from a workflow — the vendor-agnostic surface the rest of ZMART is
built on. You
pick an instrument, set the frame, and issue plain commands. The same
workflow runs on any microscope that has a driver; your code never imports a
vendor's API, the driver talks to the microscope's own API, the controller stays
a thin, easy surface for humans and AI agents alike.

> **This is the `zmart` surface.** The controller is ZMART's vendor-agnostic API
> — the layer the outside world is meant to import (`import zmart`), with vendor
> drivers plugged in underneath. See [`docs/ZMART.md`](../docs/ZMART.md) for the
> identity and the "brand-surface" principle.

## Overview of functionalities

Everything you can call:

```python
import zmart

# 1) Get the available instruments and connect to one
zmart.get_instruments()
zmart.set_instrument(instrument=Dict)

# 2) Set the origin point of the frame (current position becomes 0, 0, 0)
zmart.set_origin()

# 3) Discover actuators, then read or move the position in the frame
zmart.get_actuators()
zmart.get_xyz()
zmart.set_xyz(x, y, z, with_actuators=Dict)

# 4) Capture and reapply instrument state
zmart.get_state()
zmart.set_state(Dict)

# 5) Acquire data (captures and saves) with the current state and position
zmart.get_acquisition_options()
zmart.acquire(acquisition_type=String, position_label=String, options=Dict)

# 6) Run a procedure specific to the microscope (e.g. hardware autofocus)
zmart.get_procedures()
zmart.set_procedure(Dict)

# 7) Get additional context the driver provides (e.g. initial positions)
zmart.get_context()

# 8) Close the session
zmart.disconnect()
```

Most steps follow the same pattern: **discover, then apply.** Call a `get_*`
function to see what the microscope supports, each option lists its allowed
values and the one currently active. It then pass your choice to the matching call.
Omit an option and the driver keeps its active default, so you only specify what
you want to change.

## The workflow, step by step

### 1. Get instruments and connect

`get_instruments()` lists what you can connect to, with no hardware touched. Each
entry is a `connection` dict -- the `vendor` / `microscope` / `api` identity the
registry keys on, plus any driver-specific params (client name, api delay, host,
...). You can edit it before connecting (e.g. drop in a credential); the
controller forwards it to the driver's `connect` untouched. `set_instrument()`
opens the session. After this, every `zmart` call goes to that microscope.

```python
instrument = zmart.get_instruments()[0]
# {"vendor": "leica", "microscope": "stellaris5-01", "api": "navigator-expert",
#  "client": "PythonClient", "api_delay_ms": 250}

zmart.set_instrument(instrument)
```

### 2. Set the origin of the frame

A position only means something against a frame. `set_origin()` tells the driver
the current position is, for our purposes: (0, 0, 0). From then on, every position
is micrometers in that frame, and in reference to that (0, 0, 0) point:

```python
zmart.set_origin()                    # (0, 0, 0) is here now
```

### 3. Move to a position in the frame

`get_actuators()` lists the actuator options each axis offers. `get_xyz()` and
`set_xyz()` read and set the position in micrometers, relative to the origin. The
optional `with_actuators` argument chooses which actuator moves each axis (for
example, the piezo for fine Z) without changing the coordinates you give.

```python
zmart.get_actuators()                 # {"x": ["motoric"], "y": ["motoric"], "z": ["motoric", "galvo", "piezo"]}
zmart.set_xyz(10, 20, 5, with_actuators={"x": ["motoric"], "y": ["motoric"], "z": "piezo"}) 
```

### 4. Capture and reapply state

A *state* is a snapshot of the instrument's settings you can capture now and
reapply later. It is an opaque dict the driver owns: an `immutable` fingerprint
(so you cannot restore settings from a different instrument) plus a `mutable` part
(what is actually reapplied).

```python
prescan = zmart.get_state()                 # {"immutable": {...}, "mutable": {...}}
prescan["mutable"]["laser_power"] = 2.0
zmart.set_state(prescan)                     # reapply it later
```

### 5. Acquire (captures and saves)

`get_acquisition_options()` lists the acquisition and saving settings the
instrument supports. For example: `backlash_correction` (settles the actuators
before the image is captured), `format`, and `procedure`. `acquire()` captures one
dataset and saves it in one call: `acquisition_type` is the kind of scan,
`position_label` names the output file, and `options` carries the settings. Omit a
setting and the driver uses its active default.

```python
zmart.get_acquisition_options()
# {"backlash_correction": {...}, "format": {...}, "procedure": {...}}
zmart.acquire(acquisition_type="prescan", position_label="A1", options={"format": "ome-tiff"})
```

### 6. Run a procedure

`get_procedures()` lists the named jobs the driver offers (e.g. hardware
autofocus); `set_procedure()` runs one. Procedures are opaque dicts the driver
interprets.

```python
zmart.get_procedures()                       # {"autofocus": {...}, ...}
zmart.set_procedure({"name": "autofocus"})
```

### 7. Get additional context

`get_context()` returns whatever extra read-only context the driver provides — for
example the initial positions captured at connect.

```python
zmart.get_context()["initial_positions"]     # [{"x": 0.0, "y": 0.0, "z": 0.0}, ...]
```

### 8. Close the session

```python
zmart.disconnect()
```

## A full experiment

`example_experiment.ipynb` runs a complete prescan/target experiment end to end:
connect, capture both states, get the positions, then move and acquire at each
one. It uses the bundled mock driver, so it runs without any hardware — open it
and step through the cells.

## Adding a microscope

A driver is a set of functions — one per operation — registered under a
`connection` dict (which carries the `vendor` / `microscope` / `api` identity plus
any connect params):

```python
from zmart.registry import register

register(
    {"vendor": "leica", "microscope": "stellaris5-01", "api": "navigator-expert",
     "client": "PythonClient", "api_delay_ms": 250},
    ops={"connect": ..., "acquisition_options": ..., "set_origin": ...,
         "get_actuators": ..., "get_xyz": ..., "set_xyz": ..., "acquire": ...,
         "get_state": ..., "set_state": ..., "get_procedures": ...,
         "set_procedure": ..., "get_context": ...},
)
```

`connect` receives the whole `connection` dict and returns the driver handle;
every other function takes that handle as its first argument. `tests/mock_driver.py`
is a complete, readable reference implementation.

## Tests

```bash
python -m pytest zmart/tests
```

The test suite and the example notebook both run offline against the mock driver.

## Author

Thom de Hoog — Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
