# Microscope-Agnostic Layer

One small, consistent interface for driving a microscope from a smart-microscopy
workflow. You discover what's there, connect, and issue plain commands —
`set_xyz`, `acquire`, `save`. The same workflow runs on any microscope that has a
driver; your code never imports a vendor's API.

The layer stays deliberately thin. It holds the session's context and forwards
your intent to the driver; the driver does the real work. Nothing clever happens
in between — and that is the point.

## At a glance

```python
from microscope_agnostic_layer import available, connect

available()                       # what's out there?
mic = connect(vendor="leica", microscope="stellaris5-01", api="navigator-expert")

mic.set_coordinate_system(objective="10x", stage_type="motoric")

mic.set_xyz(10.0, 20.0, 5.0)
mic.acquire(backlash_correction=True)
mic.save(format="ome-zarr", name="well_A1")

mic.disconnect()
```

That is the whole shape of it. The rest of this page explains each step.

## Connecting

Two questions, answered at two different moments.

**What can I connect to?** Ask before you connect. `available()` reads the
registry and returns the microscopes it knows about — no hardware touched:

```python
available()
# {"leica": [("stellaris5-01", "navigator-expert")]}
```

**Then connect.** Pick a vendor, microscope, and api, and open the session:

```python
mic = connect(vendor="leica", microscope="stellaris5-01", api="navigator-expert")
```

`connect` selects the driver and opens the session — nothing more. It does not
yet know which objectives or stages this instrument has; only the live connection
can tell you that.

## The coordinate system

A position like `(10, 20, 5)` means nothing until you say *in what coordinate
system*. That depends on the objective you view through and the stage you move —
and you can only learn the available ones from the connected instrument. So you
set the coordinate system right after connecting:

```python
mic.set_coordinate_system(objective="10x", stage_type="motoric")
```

From here on, coordinates are unambiguous, because three things stay cleanly
separated:

- **What you speak in** — always the motoric stage's coordinate system, the one
  canonical space.
- **What moves you** — motoric, piezo, or galvo, chosen per axis. Using the piezo
  for fine Z does not change the coordinates you give; it just realizes them.
- **What you see through** — the objective. Switching it shifts the optics, not
  your coordinates; the driver applies the offset so a point keeps its address.

```python
mic.set_xyz(10, 20, 5, stages={"z": "piezo"})   # Z via the piezo, X and Y as they are
```

## Capabilities: the menu

Once connected, `mic.capabilities` is the instrument's menu. Each selectable
setting lists its `options` and the one that is `active`:

```python
mic.capabilities["objective"]
# {"options": ["10x", "20x", "40x"], "active": "10x"}
```

This is the single source of truth, and it sets the rhythm of the whole API:
**read an option, pass it back.** Anything you can choose — a stage, a save
format, the objective — you discover here and hand straight back as an argument.
Leave the argument out and the layer uses whatever is `active`.

## Acquiring and saving

```python
mic.acquire(backlash_correction=True)
mic.save(format="ome-zarr", procedure="tiled", name="well_A1")
```

`acquire` captures one dataset. `backlash_correction` (on by default) tells the
driver to settle the stage the right way *before* the shutter opens, so the image
lands at the true position — turn it off only when you want speed over certainty.

`save` writes the result. `format` and `procedure` are both drawn from
`capabilities`; omit them to use the active ones. `name` and `position` are
optional hints for the filename and embedded metadata.

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
move, acquire, and save across all of them. It uses the bundled mock driver, so
it runs with no hardware — open it and step through.

## Reference

**Module**

- `available()` — registered microscopes, as `{vendor: [(microscope, api), ...]}`.
  No connection made.
- `connect(vendor, microscope=None, api=None, client=None, password=None)` — open
  a session. `microscope` and `api` fall back to the vendor defaults; `password`
  is never stored.

**Session — attributes**

- `capabilities` — the options/active menu (refreshed by `set_coordinate_system`).
- `context` — `{vendor, microscope, api}`.

**Session — methods**

- `set_coordinate_system(objective=None, stage_type=None)`
- `get_xyz(stages=None)` · `set_xyz(x, y, z, stages=None)`
- `acquire(backlash_correction=True)`
- `save(format=None, procedure=None, name=None, position=None)`
- `get_state()` · `set_state(state)`
- `get_procedure()` · `set_procedure(procedure)`
- `get_initial_positions()`
- `disconnect()`

## Adding a microscope

A driver is a set of plain functions — one per operation — registered under a
`(vendor, microscope, api)` name:

```python
from microscope_agnostic_layer.registry import register

register(
    "leica", "stellaris5-01", "navigator-expert",
    ops={"connect": ..., "capabilities": ..., "set_coordinate_system": ...,
         "get_xyz": ..., "set_xyz": ..., "acquire": ..., "save": ...,
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
