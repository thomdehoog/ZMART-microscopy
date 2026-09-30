# ZMART Controller

The ZMART Controller is the controller part of **ZMART**, ZMB's
Microscopy-Agnostic Research Toolkit for smart microscopy, developed at the
Center for Microscopy and Image Analysis (ZMB), University of Zurich. It is one
small, universal interface for driving a microscope from Python. You write your
experiment once, against a handful of plain commands, and it runs on any
microscope that has a driver.

## The Problem

Every microscope vendor ships its own programming interface. Each one names
things differently, counts positions from a different corner, uses different
units, and reports errors in its own way. A script written for one microscope
does not run on another.

For smart microscopy this is a real obstacle. A feedback experiment, where you
look at an overview, decide what is interesting, and go back to image it in
detail, has to be rewritten for every instrument, usually by someone who mostly
wanted to do biology. The knowledge of how to drive each microscope ends up
tangled into every experiment, and no two labs can share their workflows.

## The Solution

The controller separates the experiment from the microscope with three ideas:

1. **One universal interface.** A short list of plain commands: move here,
   capture an image, remember these settings, run the autofocus. They mean the
   same thing on every microscope, and your experiment speaks only this
   language.

2. **Drivers that plug in.** Each microscope gets a small driver that
   translates the commands into that microscope's own software. Everything
   specific to an instrument lives inside its driver: its configuration, its
   safety limits, its calibration, and every refusal.

3. **A schema, not a program.** The controller does no microscope work of its
   own. It hands each command to the driver and hands the answer back,
   unchanged. It is an agreement about what each command means and what it
   gives back, and that agreement is what lets workflows travel between
   microscopes and between labs.

### The vocabulary

Everything you can say to a microscope:

```python
import zmart_controller

# 1) See which microscopes are available, and connect to one
zmart_controller.get_instruments()
zmart_controller.set_instrument(instrument=Dict)

# 2) Learn about the connected setup
zmart_controller.get_info()

# 3) Discover the motors, then read or move the position (micrometers)
zmart_controller.get_actuators()
zmart_controller.get_xyz()
zmart_controller.set_xyz(x, y, z, with_actuators=Dict)

# 4) Capture the instrument settings, and apply them again later
zmart_controller.get_state()
zmart_controller.set_state(Dict)

# 5) Capture and save an image with the current settings and position
zmart_controller.get_acquisition_options()
zmart_controller.acquire(acquisition_type=String, position_label=String, options=Dict)

# 6) Run a routine the microscope offers (for example autofocus)
zmart_controller.get_procedures()
zmart_controller.run_procedure(Dict)

# 7) Close the connection
zmart_controller.disconnect()
```

The pattern is always **ask first, then act**. A `get_*` call shows what the
microscope can do, with the allowed values and the one currently in use. The
matching call then does it. Any option you leave out keeps its current value.

## How It Works

Your notebook talks only to the controller. The controller looks up the driver
of the microscope you picked and passes each command straight through. The
driver does the work and answers, and the controller passes the answer, or the
refusal, straight back to you.

```
  ┌──────────────────────────────────────────────────────────────┐
  │  your notebook, script or AI agent      (the experiment)     │
  └──────────────────────────────┬───────────────────────────────┘
                     commands    │    answers and refusals, unchanged
  ┌──────────────────────────────┴───────────────────────────────┐
  │  ZMART Controller                        (this package)      │
  │                                                              │
  │  get_xyz · set_xyz · acquire · get_state · set_state · ...   │
  │  registry: which drivers are plugged in                      │
  └───────┬──────────────────────┬──────────────────────┬────────┘
          │                      │                      │
  ┌───────┴───────┐      ┌───────┴───────┐      ┌───────┴───────┐
  │   driver A    │      │   driver B    │      │  your driver  │
  └───────┬───────┘      └───────┬───────┘      └───────┬───────┘
          │                      │                      │
  ┌───────┴───────┐      ┌───────┴───────┐      ┌───────┴───────┐
  │ microscope A  │      │ microscope B  │      │      ...      │
  │ own software  │      │ own software  │      │               │
  └───────────────┘      └───────────────┘      └───────────────┘
```

Every call is **synchronous**: the controller calls the driver, the driver
does the work on the microscope, and the command returns only when that work
is finished. Nothing keeps running in the background. A live view, where you
adjust settings while watching the image and then snap, needs a different kind
of command and is not part of the controller yet.

### Where positions are measured from

Every position you read or give is in micrometers from the microscope's
*origin*, its (0, 0, 0) point. You do not set the origin in an experiment. It
is part of the driver's configuration: you set it once, in a setup step with
the driver, the driver saves it to a file, and it loads it every time it
connects. Travel limits and calibration are handled the same way. The same list
of positions therefore means the same places on the sample every time you
connect.

### What is no longer your problem

Because the controller is this simple, a whole class of problems stops being
yours as soon as you write against it:

- **In an experiment**, you never touch vendor code, units, stage conventions
  or safety limits. If a move is unsafe, the driver refuses and you see why.
- **In a driver**, you never think about workflows, other microscopes or the
  controller's internals. You implement one function per command, and the
  controller checks only that every function is there.
- **In the controller**, there is nothing to maintain. It keeps no state,
  caches nothing and refuses nothing of its own, so it cannot drift out of step
  with a microscope.

## Quick Start

### Install

The controller needs Python 3.10 or newer and nothing else:

```bash
pip install "git+https://github.com/thomdehoog/ZMART-microscopy@release-candidate-zmart-controller"
```

### Try it without a microscope

The package ships with a **mock microscope**, a pretend instrument that lives
entirely in memory, so you can try every command with no hardware at all.

```python
import zmart_controller

# 0. Make the mock microscope available. With a real microscope you would
#    import its driver here instead, which registers it in the same way.
from zmart_controller import mock
mock.register()

# 1. See which microscopes are available, and connect to one.
instruments = zmart_controller.get_instruments()
zmart_controller.set_instrument(instruments[0])

# 2. Move 100 µm along x, and take a picture.
zmart_controller.set_xyz(100, 0, 0)
record = zmart_controller.acquire(acquisition_type="prescan", position_label="A1")

# 3. Close the connection when you are done.
zmart_controller.disconnect()
```

The notebook [`examples/example_experiment.ipynb`](examples/example_experiment.ipynb)
walks through a complete overview-then-detail experiment on the mock, cell by
cell.

The short style above drives one microscope at a time. To drive two side by
side, hold each connection yourself with
`from zmart_controller.layer import set_instrument` and call the commands on
the returned session objects.

### Writing a driver

A driver is one Python function per command, collected in a dictionary and
handed to the controller's registry. `connect` receives the connection
dictionary and returns a *handle*, any object that holds the live connection.
Every other function receives that handle as its first argument. The controller
never looks inside the handle or any answer.

```python
from zmart_controller.registry import register

def connect(connection):
    client = MyVendorClient(host=connection["host"])
    # The origin is this driver's configuration: saved once by its own setup
    # step, and loaded here every time the microscope connects.
    return {"client": client, "origin": load_saved_origin()}

def get_xyz(handle, *, with_actuators=None):
    raw = handle["client"].read_position()
    return {
        axis: {"value": raw[axis] - handle["origin"][axis], "actuator": "motoric", "unit": "um"}
        for axis in ("x", "y", "z")
    }

# ... one function for each command in the table below ...

register(
    {"vendor": "acme", "microscope": "acme-5000", "api": "acme-sdk", "host": "localhost"},
    ops={
        "connect": connect,
        "disconnect": disconnect,          # optional
        "get_info": get_info,
        "get_actuators": get_actuators,
        "get_xyz": get_xyz,
        "set_xyz": set_xyz,
        "get_state": get_state,
        "set_state": set_state,
        "get_acquisition_options": get_acquisition_options,
        "acquire": acquire,
        "get_procedures": get_procedures,
        "run_procedure": run_procedure,
    },
)
```

Importing your driver module runs `register(...)`, and from then on your
microscope appears in `get_instruments()`. The mock microscope in
[`zmart_controller/mock.py`](zmart_controller/mock.py) is a complete, readable
driver of about 300 lines; it is the best place to start.

### The contract

These are the parts every driver must provide, so that an experiment written
for one microscope keeps working on another. A driver may add extra keys to any
answer; it should not leave out the ones listed here.

| Function | Receives | Must return |
|---|---|---|
| `connect` | the connection dictionary | a handle (anything) |
| `disconnect` *(optional)* | handle | nothing; afterwards every other call raises `RuntimeError`, and a second `disconnect` is harmless |
| `get_info` | handle | a dictionary containing `output_root`, the folder where images are saved |
| `get_actuators` | handle | `{axis: [actuator names]}` for `x`, `y`, `z` |
| `get_xyz` | handle, `with_actuators=` | `{axis: {"value", "actuator", "unit"}}` for `x`, `y`, `z`, in micrometers from the origin |
| `set_xyz` | handle, `x`, `y`, `z`, `with_actuators=` | a dictionary containing `position` and `actuators`; raise if the move cannot be confirmed |
| `get_state` | handle | `{"changeable": {...}, "observed": {...}}` |
| `set_state` | handle, state | a dictionary reporting what was applied; act on `changeable` only |
| `get_acquisition_options` | handle | `{name: {"options": [...], "active": value}}` |
| `acquire` | handle, `acquisition_type=`, `position_label=`, `options=` | a record containing `acquisition_type`, `position_label` and the saved file paths |
| `get_procedures` | handle | `{name: {"description", ...}}` |
| `run_procedure` | handle, `{"name": ..., ...}` | a dictionary containing `ran`; raise `ValueError` for an unknown name |

A *state* has two parts. `"changeable"` holds the settings that `set_state`
applies. `"observed"` is a read-only report, such as which objective is in
place and the pixel size; it is useful to record alongside your data and is
never used as an instruction. When the allowed values of an option cannot be
listed, `"options"` may be a short description such as `"float > 0"`. Anything
in `get_info` beyond `output_root` is an extra of that driver, and an
experiment that depends on an extra will not run on other microscopes.

### Rules for drivers

- **Refuse by raising.** Use `ValueError` when the request itself is wrong (an
  unknown option, a position outside the limits) and `RuntimeError` when the
  microscope fails or refuses. Never return a normal-looking answer that
  quietly means "this did not work". The controller passes your error to the
  user unchanged.
- **Reject what you do not understand.** An unknown option name or procedure
  raises `ValueError`. A typo that is silently ignored can cost someone an
  entire experiment.
- **Keep secrets out of error messages.** The connection dictionary may hold
  passwords. Name the keys, never the values.
- **Keep safety in the driver.** Travel limits and anything else that protects
  the instrument or the sample belong in the driver, because only the driver
  knows the hardware.
- **Test against the mock's tests.** The tests in [`tests/`](tests/) show the
  behaviour a workflow relies on; running your driver through the same
  scenarios is the quickest way to find gaps.

## Project structure

```
zmart-controller/
    zmart_controller/
        __init__.py        # the short, module-level way of driving one microscope
        layer.py           # Session: one method per command, each calling the driver
        registry.py        # where drivers plug in
        mock.py            # the mock microscope: a complete example driver

    examples/
        example_experiment.ipynb   # an overview-then-detail experiment on the mock

    tests/                 # run offline against the mock microscope

    pyproject.toml
    LICENSE
```

## Testing

```bash
pip install ".[test]"
pytest
```

The tests run offline against the mock microscope and take well under a
second.

## Status

This is version 0.1. The commands are stable in spirit, and small changes may
happen before 1.0. One is already planned: every command will return the same
two things, whether it worked (`success`) and a free-form `report` from the
driver. Drivers will still raise an error whenever carrying on would be unsafe.
If you write a driver, please open an issue so we can keep the contract honest
together.

## Requirements

- Python 3.10+
- Nothing else. Drivers bring their own dependencies.

## Author

Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).

## License

MIT License. See LICENSE file for details.
