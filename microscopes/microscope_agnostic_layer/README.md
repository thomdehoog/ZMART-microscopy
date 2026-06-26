# Microscope-Agnostic Layer

A simplified, vendor-neutral surface that smart-microscopy workflows build on.
Its one aim is to give workflows a stable abstraction over microscope drivers,
with no unnecessary complication. It earns its keep by being boring: every call
forwards your intent and the session context to the driver and returns what the
driver gives back. The layer never moves a stage, computes an offset, or
interprets a payload — the driver does the work, the layer carries the context.

```
workflows / guards / limits      decide WHAT to do        (the smart part)
─────────────────────────────────────────────────────────────────────────
agnostic layer = CONTEXT          this package: one easy, discoverable surface
─────────────────────────────────────────────────────────────────────────
vendor drivers + calibration      do the work, USING the context
```

This package is two files plus a test integration:

| File | Role |
|------|------|
| `layer.py` | the workflow-facing surface: `connect()` + the `Session` methods |
| `registry.py` | points each operation at a driver's functions; `available()` |
| `tests/mock_driver.py` | a hardware-free reference driver used by the tests and the example |

See `DESIGN.md` for the full design rationale, boundaries, and acceptance bar.

> Status: the layer is implemented and exercised end to end against the bundled
> mock driver. No production vendor adapter is wired in yet — the Leica adapter
> registers here once it exists.

## Quick start

The flow has three phases: **discover what you can connect to**, **connect**, then
**discover what the instrument has and set the coordinate system**. After that you
drive it.

```python
from microscope_agnostic_layer import available, connect

available()                       # {vendor: [(microscope, api), ...]}  — no connection

mic = connect(vendor="leica", microscope="stellaris5-01", api="navigator-expert")

mic.capabilities                  # what objectives / stages / formats does it have?
mic.set_coordinate_system(objective="10x", stage_type="motoric")

mic.set_xyz(10.0, 20.0, 5.0)                      # absolute, motoric coordinate system
frame = mic.acquire(backlash_correction=True)
mic.save(format="ome-zarr", name="well_A1")

mic.disconnect()                  # optional teardown when finished
```

A runnable, explained version of a full prescan/target experiment is in
`example_experiment.ipynb` (it uses the bundled mock, so it runs with no
hardware).

## Concepts

### Discovery comes in two phases

The two kinds of "what's available" live in different places:

- **Pre-connect — what can I connect to?** `available()` reads the registry and
  returns `{vendor: [(microscope, api), ...]}`. No connection is made.
- **Post-connect — what does this instrument have?** Only after connecting does
  the driver report its objectives, stages, save formats, etc., as
  `session.capabilities`.

### Capabilities: options + active

`session.capabilities` is the menu the driver advertises. For each selectable
axis it gives the available `options` and the currently `active` one:

```python
session.capabilities == {
    "objective": {"options": ["10x", "20x", "40x"], "active": "10x"},
    "stages": {
        "x": {"options": ["motoric", "galvo"],  "active": "motoric"},
        "y": {"options": ["motoric", "galvo"],  "active": "motoric"},
        "z": {"options": ["motoric", "piezo"],  "active": "motoric"},
    },
    "save_format":    {"options": ["ome-tiff", "ome-zarr"], "active": "ome-tiff"},
    "save_procedure": {"options": ["direct", "tiled"],      "active": "direct"},
}
```

This is the single source of truth, and it drives the whole usage pattern:
**discover, then put it back.** You read an `option` here and pass the same value
straight back as an argument (a stage for `set_xyz`, a `format` for `save`, an
`objective` for `set_coordinate_system`). Omit the argument and the layer uses
`active`.

### The coordinate system

"Absolute" coordinates only mean something once a reference coordinate system is
fixed — which is why you set it *after* connecting, from the discovered options.
The layer keeps three normally-conflated things apart:

- **The coordinate system you speak in** — always the motoric-stage system, the
  single canonical absolute space.
- **The actuator that executes the move** — motoric, piezo, or galvo, chosen per
  axis with the `stages` argument. Choosing the galvo doesn't change the
  coordinates you give; it just realizes them within its range.
- **The objective you see through** — each carries a known offset; the reference
  objective is the baseline. A feature's absolute coordinate stays the same
  whichever actuator moves you there or whichever objective you're under.

The driver owns the calibration math (offsets, actuator transforms); the layer
only carries the intent.

### Two method styles

Every method is send/receive. They differ only in payload shape:

- **Standardized** — specific, typed parameters and structured results
  (`set_xyz`, `acquire`, `save`, …). The layer commits to the signature.
- **Flexible** — a single opaque **dict** in and out (`get_state`/`set_state`,
  `get_procedure`/`set_procedure`, `get_initial_positions`). The driver owns the
  shape; the layer interprets nothing.

## API reference

### Module functions

- `available() -> {vendor: [(microscope, api), ...]}`
  Pre-connect discovery of registered drivers. No connection.
- `connect(vendor, microscope=None, api=None, client=None, password=None) -> Session`
  Select the driver, open and authenticate the session, discover capabilities.
  `microscope`/`api` fall back to the vendor defaults. `password` has no default —
  pass it explicitly or resolve it from a secret upstream. Does **not** set the
  coordinate system.

### `Session` attributes

- `capabilities` — the options/active menu discovered at connect (refreshed when
  you call `set_coordinate_system`).
- `context` — how the driver was selected: `{vendor, microscope, api}`.

### `Session` methods

Coordinate system:

- `set_coordinate_system(objective=None, stage_type=None)`
  Fix the coordinate system from discovered options. Either may be omitted to
  keep the driver's active choice. The driver validates and the capabilities are
  refreshed.

Standardized (typed params, structured results):

- `get_xyz(stages=None) -> dict`
  Read position per axis as `{axis: {"value", "stage", "unit"}}`. `stages`
  optionally selects which actuator to read per axis.
- `set_xyz(x, y, z, stages=None)`
  Move to an absolute target in the motoric coordinate system. `stages` selects
  the actuator per axis (e.g. `{"z": "piezo"}`); unspecified axes use the active
  one.
- `acquire(backlash_correction=True) -> dict`
  Acquire one dataset. `backlash_correction` tells the driver to settle via the
  right approach before the capture (an acquisition concern, not a move concern).
- `save(format=None, procedure=None, name=None, position=None) -> dict`
  Persist the last acquisition. `format`/`procedure` default to the active
  discovered options; `name`/`position` are optional filename/metadata context.

Flexible (opaque dicts, send/receive only):

- `get_state() -> dict` / `set_state(state)`
  Capture and reactivate instrument state. The dict has an `immutable` part
  (a fingerprint the driver validates) and a `mutable` part (what gets reapplied).
  The driver owns the boundary.
- `get_procedure() -> dict` / `set_procedure(procedure)`
  Receive / send a vendor procedure dict. What it means (run, define, stage) is
  encoded in the dict and acted on by the driver.
- `get_initial_positions() -> list[dict]`
  The positions captured at connect, for the workflow to visit.

Lifecycle:

- `disconnect()` — close the session if the driver provides teardown.

## Adding a driver

A driver is a set of plain functions plus a registration. Each function takes the
driver's opaque handle as its first argument; `connect` returns that handle. The
ops table maps every operation in `registry.OPS` to one of these functions:

```python
from microscope_agnostic_layer.registry import register

register(
    "leica", "stellaris5-01", "navigator-expert",
    ops={
        "connect": ...,         # (*, microscope, api, client, password) -> handle
        "capabilities": ...,    # (handle) -> {axis: {"options", "active"}}
        "set_coordinate_system": ...,
        "get_xyz": ..., "set_xyz": ...,
        "acquire": ..., "save": ...,
        "get_state": ..., "set_state": ...,
        "get_procedure": ..., "set_procedure": ...,
        "get_initial_positions": ...,
        "disconnect": ...,      # optional
    },
    defaults={"microscope": "stellaris5-01", "api": "navigator-expert"},
)
```

Real vendor drivers register in `registry.py`. Test-only integrations register
from the test side (see `tests/conftest.py`), so no test code is imported into
production. `tests/mock_driver.py` is a complete, readable reference
implementation of the driver contract.

Per `DESIGN.md`, the driver tree will be organized as
`drivers/vendor/microscope/api`, with shared control code and thin per-instance
leaves; this registry will mirror it.

## Example

```bash
# from this folder, with the mock driver (no hardware):
jupyter notebook example_experiment.ipynb
```

The notebook walks the full flow — connect, set the coordinate system, select
prescan/target states, get positions, then run set_xyz/acquire/save over every
position — with markdown explaining each step.

## Tests

Offline, no hardware or LAS X install required:

```bash
python -m pytest microscopes/microscope_agnostic_layer/tests
```

Lint/format (matches the repo's ruff baseline):

```bash
ruff check microscopes/microscope_agnostic_layer
ruff format --check microscopes/microscope_agnostic_layer
```
