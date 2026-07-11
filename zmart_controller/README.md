# ZMART Controller

[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-blue)](../LICENSE)

The **ZMART Controller** is one small, consistent interface for driving a
microscope from a workflow — the vendor-agnostic surface the rest of ZMART is
built on. You
pick an instrument, set the frame, and issue plain commands. The same
workflow will run on any microscope that has a driver adapter; your code never
imports a vendor's API, the driver talks to the microscope's own API, the
controller stays a thin, easy surface for humans and AI agents alike.

> **Status:** the first real adapter is the Leica Stellaris 5 one — import
> `zmart_drivers.leica.stellaris5_y42h93.navigator_expert.zmart_adapter` to
> register it. The other vendor adapters are still under construction (see
> [`docs/ZMART.md`](../docs/ZMART.md)); the mock used by the tests and the
> example notebook registers from the test side.

> **This is the `zmart` surface.** The controller is ZMART's vendor-agnostic API
> — the layer the outside world will eventually import as `zmart` (today the
> package is `zmart_controller`; no `zmart` package exists yet), with vendor
> drivers plugged in underneath. See [`docs/ZMART.md`](../docs/ZMART.md) for the
> identity and the "brand-surface" principle.

## Overview of functionalities

Everything you can call:

```python
import zmart_controller

# 1) Get the available instruments and connect to one
zmart_controller.get_instruments()
zmart_controller.set_instrument(instrument=Dict)

# 2) Set the origin point of the frame (current position becomes 0, 0, 0)
zmart_controller.set_origin()

# 3) Discover actuators, then read or move the position in the frame
zmart_controller.get_actuators()
zmart_controller.get_xyz()
zmart_controller.set_xyz(x, y, z, with_actuators=Dict)

# 4) Capture and reapply instrument state
zmart_controller.get_state()
zmart_controller.set_state(Dict)

# 5) Acquire data (captures and saves) with the current state and position
zmart_controller.get_acquisition_options()
zmart_controller.acquire(acquisition_type=String, position_label=String, options=Dict)

# 6) Run a procedure specific to the microscope
zmart_controller.get_procedures()
zmart_controller.run_procedure(Dict)

# 7) Optionally inspect extra diagnostic information the driver provides
zmart_controller.get_info()

# 8) Close the session
zmart_controller.disconnect()
```

Most steps follow the same pattern: **discover, then apply.** Call a `get_*`
function to see what the microscope supports, each option lists its allowed
values and the one currently active. Then pass your choice to the matching call.
Omit an option and the driver keeps its active default, so you only specify what
you want to change. `set_*` applies a snapshot or value (`set_state`, `set_xyz`,
`set_instrument`); `run_procedure` runs a named procedure instead.

## The workflow, step by step

### 1. Get instruments and connect

`get_instruments()` lists what you can connect to, with no hardware touched. Each
entry is a `connection` dict -- the `vendor` / `microscope` / `api` identity the
registry keys on, plus any driver-specific params (client name, api delay, host,
...). You can edit it before connecting (e.g. drop in a credential); the
controller forwards it to the driver's `connect` untouched. `set_instrument()`
opens the session. After this, every `zmart` call goes to that microscope.

```python
instrument = zmart_controller.get_instruments()[0]
# {"vendor": "leica", "microscope": "stellaris5-y42h93", "api": "navigator-expert",
#  "client": "PythonClient", "api_delay_ms": None, "output_root": None}

zmart_controller.set_instrument(instrument)
```

Do not normally set `output_root` by hand. `get_info()["output_root"]` reports
the resolved root; Leica discovers its default from LAS X native AutoSave. The
connection field is an explicit workflow override and remains authoritative.

### 2. Set the origin of the frame

A position only means something against a frame. `set_origin()` tells the driver
the current position is, for our purposes: (0, 0, 0). From then on, every position
is micrometers in that frame, and in reference to that (0, 0, 0) point:

```python
zmart_controller.set_origin()                    # (0, 0, 0) is here now
```

### 3. Move to a position in the frame

`get_actuators()` lists the actuator options each axis offers. `get_xyz()` and
`set_xyz()` read and set the position in micrometers, relative to the origin. The
optional `with_actuators` argument chooses which actuator moves each axis (for
example, the piezo for fine Z) without changing the coordinates you give.

```python
zmart_controller.get_actuators()                 # {"x": ["motoric"], "y": ["motoric"], "z": ["motoric", "galvo", "piezo"]}
zmart_controller.set_xyz(10, 20, 5, with_actuators={"z": "piezo"})
```

The actuator names above are the bundled mock's — always discover first. The
Leica driver, for example, offers `{"z": ["z-wide", "z-galvo"]}`; copy-pasting
`{"z": "piezo"}` there raises `ValueError`.

### 4. Capture and reapply state

A *state* is a snapshot of the instrument you can capture now and reapply
later. It is an opaque dict the driver owns: a `changeable` part (what
`set_state` actually reapplies) plus an `observed` part (a read-only report of
instrument identity and condition — never an instruction).

```python
prescan = zmart_controller.get_state()                 # {"changeable": {...}, "observed": {...}}
prescan["changeable"]["laser_power"] = 2.0
zmart_controller.set_state(prescan)                     # reapply it later
```

### 5. Acquire (captures and saves)

`get_acquisition_options()` lists the acquisition and saving settings the
instrument supports. For example: `backlash_correction` (settles the actuators
before the image is captured), `format`, and `procedure`. `acquire()` captures one
dataset and saves it in one call: `acquisition_type` is the kind of scan,
`position_label` labels the position in the driver's output records (how it
appears — filename slot, lineage — is driver-defined), and `options` carries the
settings. Omit a setting and the driver uses its active default.

```python
zmart_controller.get_acquisition_options()
# {"backlash_correction": {...}, "format": {...}, "procedure": {...}}   <- mock's menu
zmart_controller.acquire(acquisition_type="prescan", position_label="A1", options={"format": "ome-tiff"})
```

The option menu shown is the bundled mock's; each driver owns its own menu
(the Leica driver's has `job`, `backlash_correction`, `strip_scan_fields`, `cleanup_source`
and no `procedure`) and its own naming rules — see the driver README for
constraints such as the Leica kebab-case `acquisition_type` rule and
numeric-label overwrites.

### 6. Run a procedure

`get_procedures()` lists named driver actions; `run_procedure()` runs one.
Procedures are opaque dicts the driver interprets. Read-only setup discovery
belongs to `get_info()`, not to procedures.

```python
zmart_controller.get_procedures()                       # {"autofocus": {...}, ...}
zmart_controller.run_procedure({"name": "autofocus"})
```

### 7. Get additional information

`get_info()` returns a fresh setup snapshot. For target-acquisition-capable
drivers, `tile_positions` are the vendor-authored acquisition tiles (including
physical `tile_size`), not the stage's current position; use `get_xyz()` for
that. `focus_positions` and the resolved `output_root` travel in the same
snapshot. Other keys remain driver-defined. The controller does not cache it.
The call is read-only with respect to microscope state, but a driver may persist
working files while gathering truthful information (Leica flushes the live
scanning template to disk, which may block up to a minute).

```python
info = zmart_controller.get_info()
root = info["output_root"]
tiles = info["tile_positions"]
focus_positions = info.get("focus_positions", [])
```

### 8. Close the session

```python
zmart_controller.disconnect()
```

## A full experiment

`example_experiment.ipynb` runs a complete prescan/target experiment end to end:
connect, capture both states, get the positions, then move and acquire at each
one. It uses the bundled mock driver, so it runs without any hardware — open it
and step through the cells.

`example_leica_experiment.ipynb` is the same surface against the **real Leica
driver** via its `zmart_adapter` (needs a live LAS X — simulator or scope):
register by import, connect, look around read-only, then origin/move/acquire.

## Adding a microscope

A driver is a set of functions — one per operation — registered under a
`connection` dict (which carries the `vendor` / `microscope` / `api` identity plus
any connect params):

```python
from zmart_controller.registry import register

register(
    {"vendor": "leica", "microscope": "stellaris5-y42h93", "api": "navigator-expert",
     "client": "PythonClient", "api_delay_ms": None, "output_root": None},
    ops={"connect": ..., "get_acquisition_options": ..., "set_origin": ...,
         "get_actuators": ..., "get_xyz": ..., "set_xyz": ..., "acquire": ...,
         "get_state": ..., "set_state": ..., "get_procedures": ...,
         "run_procedure": ..., "get_info": ...},
)
```

Connection dicts may include an explicit `output_root`; otherwise adapters
discover an instrument-derived default when they can and report the resolved
value through `get_info()`.

`connect` receives the whole `connection` dict and returns the driver handle;
every other function takes that handle as its first argument. `tests/mock_driver.py`
is a complete, readable reference implementation.

**How ops report failure: they raise.** Ops must raise an exception on failure
(`ValueError` for caller mistakes, `RuntimeError` for instrument failures or
driver refusals) and must never encode failure in the returned dict — the
controller inspects nothing and propagates driver exceptions to the caller
unchanged. Both real adapters and the mock follow this. Keep error text
credential-safe: connection dicts may carry credentials, so name keys, never
echo values (the registry's own errors follow this rule).

## Tests

```bash
python -m pytest zmart_controller/tests
```

The test suite and the example notebook both run offline against the mock driver.

## Author

Thom de Hoog — Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
