# zmart_drivers.setup: the door a microscope is configured through

Two things happen to a microscope in this repository, and they do not share a
door. **Driving** it, which means moving, imaging and reading its state, goes
through `zmart_controller`. **Setting it up**, which means publishing how far
the stage may travel, where the frame counts from, which way the picture is
turned and how the objectives line up, goes through this package. Nothing that
holds a controller session can reach it, and this package never imports the
controller.

That separation is a safety property. The driver refuses moves outside the
limits it stands on. That is only worth something while the thing being limited
cannot rewrite its own limits, so the controller carries no configuration op at
all. An agent driving a microscope through the controller can drive it and
nothing else.

The ZMART driver configuration workflow on the operator page is the one user
of this package. Its five steps talk only to the seam described here, so a new
microscope needs no change to the workflow, only a driver that plugs in.

## Overview

```python
import zmart_drivers.setup as zmart_drivers.setup

instrument = zmart_drivers.setup.get_instruments()[0]          # a connection dict
zmart_drivers.setup.get_configurations(instrument)             # the machine's configurations, newest first

setup = zmart_drivers.setup.open_setup({**instrument, "configuration": "configuration_2026-..."})
setup.describe()                       # what this driver can configure, and how
setup.where()                          # where the stage is, and every drive's reading
setup.move(x_um, y_um, z_um)           # move, and read back where it went
setup.acquire(into=..., name=...)      # one raw picture, or a stack
setup.read("limits")                   # the document as it stands, and its evidence
setup.publish("limits", document)      # a dated snapshot in the configuration
setup.close()
```

`zmart_drivers.setup.procedures` holds the measurements the workflow runs against a
setup: reading the corners, measuring the orientation, capturing a lens view,
measuring an objective pair, reading the origin. They are written against the
vocabulary below alone, so they work on any driver that supplies it. The image
analysis under them lives in `zmart_analysis/workflows/driver_configuration/`
and never learns which microscope took the pictures.

## Configurations

A machine keeps its setup as **configurations**: one folder per pass through
the workflow, named `configuration_<datetime>`, holding all four subsystems.
Each subsystem keeps a dated snapshot tree inside it, and each snapshot carries
the document plus its evidence, which is the figures, the measurement's
numbers, the raw frames and the analysis recipe:

```
<machine root>/
    configuration_<datetime>/
        limits/<datetime>/limits.json
        origin/<datetime>/origin.json
        orientation/<datetime>/orientation.json      (+ data/)
        calibration/<datetime>/calibration.json      (+ data/)
```

A new configuration starts as a full copy of the newest snapshot of each
subsystem, so it is complete before anything is adopted in it. The driver
stands on exactly one configuration, the one named at connect or else the
newest, and never looks across them. The controller always names one and
refuses one without limits.

## Adding a microscope

A driver's setup is a set of functions, one per operation, registered under a
connection dict that carries the `vendor`, `microscope` and `api` identity the
registry keys on, plus whatever the driver needs to open:

```python
from zmart_drivers.setup.registry import register

register(
    {"vendor": "leica", "microscope": "stellaris5-y42h93", "api": "navigator-expert",
     "client": "PythonClient", "api_delay_ms": None},
    ops={
        # required
        "open": open_setup, "close": close_setup, "describe": describe,
        "where": where, "move": move, "acquire": acquire,
        "read": read, "publish": publish,
        # optional
        "objective": objective, "objectives": objectives, "markers": markers,
        "configurations": configurations, "new_configuration": new_configuration,
        "use_configuration": use_configuration, "configuration": configuration,
    },
)
```

`open` receives the whole connection dict and returns the driver's handle.
Every other function takes that handle as its first argument, except
`configurations`, which takes the connection dict, because it is asked before
anything is opened. The registry refuses a table that is missing a required
op or names one it does not know, so a misspelt op fails at registration rather
than as a gap on the page. `zmart_drivers/mock/mock_setup.py` is a complete,
readable reference; the Leica's is `zmart_adapter/setup.py` beside its
operating adapter.

### The required ops

- **`open(connection)`** opens a driver-level connection that does not need a
  published envelope to succeed, since publishing one is what this is for.
  Moves are still fenced by the driver's physical backstop. When the
  connection names a `configuration`, the driver stands on that one.
- **`close(handle)`**.
- **`describe(handle)`** says what this driver can configure. It answers with a
  `label`, `checks` (a name to answer map, the way the controller's
  connection status reports them) and `subsystems`: for each of `limits`,
  `orientation`, `calibration` and `origin`, `{"supported": bool, ...}` with
  whatever the page needs to draw it. A subsystem left out is unsupported and
  the page says so. For limits, the page draws its rows from the `document`
  entry: the `axes` with a key, a label and a unit, which of them are
  `measured` by driving to the corners, which are `required`, the objective
  `slots` entry, and the names of the `settings` the driver can change.
- **`where(handle)`** answers `{"x_um", "y_um", "z_um", "actuators": {...}}` in
  absolute stage coordinates. Under `actuators` every drive the instrument has,
  each as `{"value", "unit"}`. The origin is a reading of all of them.
- **`move(handle, x_um, y_um, z_um)`** moves, then answers with where the stage
  was read back to be.
- **`acquire(handle, *, into, name, z_um=None)`** takes one raw picture, or a
  stack when `z_um` lists heights, written under `into`. It answers with
  `images` (paths in plane order), `pixel_um`, `frame_px` and `job`. Raw means
  before any orientation correction: measuring the orientation needs the
  pixels as the camera recorded them.
- **`read(handle, subsystem, *, fresh=False)`** answers with the `document` as
  it stands in the configuration, `source` saying `published` or `default`,
  its `path`, and `evidence`, a list of `{"name", "path"}` for the files kept
  beside it. With `fresh`, the driver's bundled default regardless.
- **`publish(handle, subsystem, document, evidence=())`** validates the way
  the driver validates, writes a dated snapshot into the configuration, and
  keeps each evidence file or folder beside the document. It answers with
  where it went.

### The optional ops

The page asks `describe()["can"]` before relying on any of these, and greys
out what depends on one the driver lacks.

- **`objective(handle)`** says which lens is in, `{"slot", "name"}`. Observed,
  never commanded: an operator changes lenses in the vendor's software.
- **`objectives(handle)`** lists every lens the turret holds, so a calibration
  names its reference and targets from the instrument's own list.
- **`markers(handle)`** answers `{"points": [{"x_um", "y_um"}, ...]}`, points
  the operator placed in the vendor's software to say where the safe corners
  are.
- **`configurations(connection)`** lists the machine's configurations newest
  first, each `{"id", "created_at", "has": {subsystem: bool}}`, without
  opening anything. **`new_configuration(handle)`** starts one as a full copy
  of the newest and stands on it. **`use_configuration(handle, id)`** stands
  on one by id. **`configuration(handle)`** says which one is stood on.

### How ops report failure

They raise. `ValueError` for a caller's mistake, `RuntimeError` for an
instrument's refusal or failure. Never encode failure in the returned dict:
the layer inspects nothing and passes the driver's exception to the caller
unchanged, and the page shows its sentence. Keep error text free of
credentials. Connection dicts may carry them, so name keys and never echo
values.

### What a driver does not do

It does not measure. Which way the picture is turned, where a second lens
looks, how sharp a plane is: all of that is computed in `zmart_analysis` from
the raw pictures the driver took. A driver that can move, take a picture and
read and write four documents is a complete setup driver. Keeping the
vocabulary this small is what makes a vendor's API safe to stand on, and what
keeps the workflow the same on every microscope.

## Tests

```bash
python -m pytest zmart_drivers/setup/tests
```

The tests run against the mock, which keeps its configurations under a
machine root named by `ZMART_MOCK_MACHINE`; the test setup points that at a
temporary folder, so nothing an operator published is read or touched.

## Author

Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
