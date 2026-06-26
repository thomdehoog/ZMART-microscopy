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

Most steps follow the same rhythm: **discover, then apply.** You ask the
microscope what it offers with a `get_*` call — each option comes with its
allowed values and the one that is currently active — and then you pass your
choice back to the matching call. Leave an option out and the driver simply uses
its active default, so the short form always works.

1. **Discover and connect.** `available_microscopes()` reads the registry and
   returns what you can connect to as `{vendor: [(microscope, api), ...]}` —
   nothing is opened, no hardware is touched. `connect_to_microscope()` then
   selects that driver and opens the session. From this point on, `mic` *is* that
   microscope; it does not yet know which objectives or stages the instrument has
   — only the live connection can report those, which is the next step.

   ```python
   mic.available_microscopes()   # {"leica": [("stellaris5-01", "navigator-expert")]}
   mic.connect_to_microscope(vendor="leica", microscope="stellaris5-01", api="navigator-expert")
   ```

2. **Define the coordinate system.** A position like `(10, 20, 5)` is meaningless
   until you say *in what frame* — that depends on the objective you look through
   and the stage that moves. `get_coordinate_system()` shows the available
   objectives and stage types (each as `options` plus the `active` one), and
   `set_coordinate_system()` fixes the ones you want. From then on coordinates are
   unambiguous: the driver applies the objective offsets so a given point keeps
   the same address no matter which objective or actuator you use.

   ```python
   mic.get_coordinate_system()
   # {"objective": {"options": ["10x", "20x", "40x"], "active": "10x"}, "stage_types": {...}}
   mic.set_coordinate_system(objective="10x", stage_type="motoric")
   ```

3. **State and procedures.** A *state* is a snapshot of the instrument's settings
   that you can capture now and reactivate later; a *procedure* is a named job the
   driver knows how to run. Both are opaque dictionaries — the layer carries them,
   only the driver understands them. `get_state()` / `get_procedure()` read one,
   and `set_state()` / `set_procedure()` send it back.

   ```python
   prescan = mic.get_state()                 # {"immutable": {...}, "mutable": {...}}
   prescan["mutable"]["laser_power"] = 2.0
   mic.set_state(prescan)                     # reactivate it later
   ```

4. **Stage movements.** `get_initial_positions()` returns the list of positions to
   visit (captured at connect). `get_xyz()` and `set_xyz()` read and move in the
   canonical (motoric) coordinate system; the optional `stage_types` argument
   chooses which actuator realizes each axis (e.g. the piezo for fine Z), without
   changing the coordinates you give.

   ```python
   positions = mic.get_initial_positions()
   mic.set_xyz(10, 20, 5, stage_types={"z": "piezo"})   # Z via the piezo
   ```

5. **Acquire.** `get_acquisitions_options()` shows the acquisition settings the
   instrument supports — for example `backlash_correction`, which settles the
   stage the right way before the shutter opens so the image lands at the true
   position. `acquire(options=...)` captures one dataset with the settings you
   choose; anything you omit uses the active default.

   ```python
   mic.get_acquisitions_options()   # {"backlash_correction": {"options": [True, False], "active": True}}
   mic.acquire(options={"backlash_correction": True})
   ```

6. **Export the data.** `get_export_data_options()` shows the available output
   `format` and `procedure`; `export_data(options=...)` writes the result. The
   options may also carry free `name` / `position` context for the filename and
   embedded metadata. Omit `format` / `procedure` and the driver uses its active
   default.

   ```python
   mic.get_export_data_options()    # {"format": {...}, "procedure": {...}}
   mic.export_data(options={"format": "ome-zarr", "name": "well_A1"})
   ```

7. **Session.** `disconnect()` closes the session when you are finished. It is
   optional — only some drivers need an explicit teardown.

   ```python
   mic.disconnect()
   ```

The sections below walk each step in depth.

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
