# Microscope-Agnostic Layer

One small, consistent interface for driving a microscope from a smart-microscopy
workflow. You discover what is there, connect, and issue plain commands. The same
workflow runs on any microscope that has a driver; your code never imports a
vendor's API.

The layer stays deliberately thin. It holds the session's context and forwards
your intent to the driver; the driver does the real work.

## Overview of functionalities

Everything you can call:

```python
from microscope_agnostic_layer import available_microscopes, connect_to_microscope

# Connect to the microscopes
available_microscopes()                       # {vendor: [(microscope, api), ...]}
mic = connect_to_microscope(vendor=String, microscope=String, api=String, client=String, password=String)

# Define the coordinate system
mic.get_coordinate_system()                   # available objectives and stage types
mic.set_coordinate_system(objective=String, stage_type=String)

# Capture and activate the instrument state and procedures
mic.get_state()
mic.set_state(Dict)
mic.get_procedure()
mic.set_procedure(Dict)

# Handle stage movements
mic.get_initial_positions()
mic.get_xyz()
mic.set_xyz(x, y, z, stage_types=Dict)

# Acquire
mic.get_acquisitions_options()
mic.acquire(options=Dict)

# Export the data
mic.get_export_data_options()
mic.export_data(options=Dict)

# Session
mic.disconnect()
```

The rest of this page explains each step.

## Connect

Two questions, answered at two different moments.

**What can I connect to?** `available_microscopes()` reads the registry and
returns the microscopes it knows about — no hardware touched:

```python
available_microscopes()
# {"leica": [("stellaris5-01", "navigator-expert")]}
```

**Then connect.** Pick a vendor, microscope, and api, and open the session:

```python
mic = connect_to_microscope(vendor="leica", microscope="stellaris5-01", api="navigator-expert")
```

`connect_to_microscope` selects the driver and opens the session — nothing more.
It does not yet know which objectives or stages this instrument has; only the
live connection can tell you that.

## Set the coordinate system

A position like `(10, 20, 5)` means nothing until you say *in what coordinate
system*. That depends on the objective you view through and the stage you move —
and you can only learn the available ones from the connected instrument. So you
discover them, then choose:

```python
mic.get_coordinate_system()
# {"objective":   {"options": ["10x", "20x", "40x"], "active": "10x"},
#  "stage_types": {"x": {"options": ["motoric", "galvo"], "active": "motoric"},
#                  "y": {"options": ["motoric", "galvo"], "active": "motoric"},
#                  "z": {"options": ["motoric", "piezo"], "active": "motoric"}}}

mic.set_coordinate_system(objective="10x", stage_type="motoric")
```

The stage names (`motoric`, `galvo`, `piezo`, …) are whatever the driver defines,
not a fixed set — you read the `options` and pass one back.

From here on, coordinates are unambiguous, because three things stay cleanly
separated:

- **What you speak in** — always the motoric stage's coordinate system, the one
  canonical space.
- **What moves you** — the stage type, chosen per axis. Using the piezo for fine
  Z does not change the coordinates you give; it just realizes them.
- **What you see through** — the objective. Switching it shifts the optics, not
  your coordinates; the driver applies the offset so a point keeps its address.

```python
mic.set_xyz(10, 20, 5, stage_types={"z": "piezo"})   # Z via the piezo, X and Y as they are
```

## Acquire and export

```python
mic.get_acquisitions_options()   # {"backlash_correction": {"options": [True, False], "active": True}}
mic.acquire(options={"backlash_correction": True})

mic.get_export_data_options()    # {"format": {...}, "procedure": {...}}
mic.export_data(options={"format": "ome-zarr", "procedure": "tiled", "name": "well_A1"})
```

`acquire` captures one dataset. `options` selects acquisition settings discovered
via `get_acquisitions_options` — e.g. `backlash_correction`, which settles the
stage before the shutter opens so the image lands at the true position.

`export_data` writes the result. `options` may set the discovered `format` /
`procedure` plus free `name` / `position` hints. Omit any option and the driver
fills it from its active default.

## States and procedures

Some things do not standardize across vendors — an instrument's full settings, a
named acquisition job. The layer passes these as opaque dictionaries: it carries
them, the driver understands them.

A **state** is a snapshot you can put back later:

```python
prescan = mic.get_state()                 # capture
prescan["mutable"]["laser_power"] = 2.0   # adjust the settable part
mic.set_state(prescan)                    # reactivate
```

A state has an `immutable` part (a fingerprint the driver checks, so you cannot
restore settings from a different instrument) and a `mutable` part (what actually
gets reapplied). The layer never looks inside — the driver owns the meaning.

Procedures work the same way through `get_procedure` / `set_procedure`, and
`get_initial_positions()` returns the positions captured at connect for your
workflow to visit.

## A full experiment

`example_experiment.ipynb` walks a complete prescan/target run end to end:
connect, set the coordinate system, capture both states, get the positions, then
move, acquire, and export across all of them. It uses the bundled mock driver, so
it runs with no hardware — open it and step through.

## Adding a microscope

A driver is a set of plain functions — one per operation — registered under a
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
