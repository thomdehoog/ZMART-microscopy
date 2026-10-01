# Plug in your own driver functions

A driver is one Python function per command, collected in a dictionary and
handed to the controller's registry. There is no base class to inherit from.
The mock microscope in [`zmart_controller/mock.py`](../zmart_controller/mock.py)
is a complete, readable driver of about 300 lines; read it alongside this
page.

## The shape

`connect` receives the connection dictionary and returns a *handle*: any object
you like that holds the live connection to your microscope. Every other
function receives that handle as its first argument. The controller never
looks inside the handle or any answer.

```
  connect(connection) --> handle --> get_xyz(handle, ...)
                                     set_xyz(handle, x, y, z, ...)
                                     acquire(handle, ...)
                                     ...
```

## A minimal driver

Two files in a folder called `zmart_plugin/`:

```
my_driver/
    zmart_plugin/
        zmart.json         # which instruments this driver serves
        __init__.py        # one function per command
    ...                    # the rest of the driver: vendor API, limits, calibration
```

`zmart.json` names the instruments. Three keys say which microscope;
anything else is handed to `connect` as it is:

```json
{
  "contract": 1,
  "instruments": [
    {"vendor": "acme", "microscope": "acme-5000", "api": "acme-sdk", "host": "localhost"}
  ]
}
```

`__init__.py` holds the functions, found by name:

```python
TRAVEL = {"x": (-5000.0, 5000.0), "y": (-5000.0, 5000.0), "z": (-500.0, 500.0)}

def connect(connection):
    client = MyVendorClient(host=connection["host"])
    # The origin is this driver's configuration: saved once by its own setup
    # step, and loaded here every time the microscope connects.
    return {"client": client, "origin": load_saved_origin()}

def get_xyz(handle, *, with_actuators=None):
    raw = handle["client"].read_position()
    position = {
        axis: {
            "value": raw[axis] - handle["origin"][axis],
            "actuator": "motoric",
            "unit": "um",
            "range": [lo - handle["origin"][axis], hi - handle["origin"][axis]],
        }
        for axis, (lo, hi) in TRAVEL.items()
    }
    return {"success": True, "report": position}

# ... and get_info, get_actuators, set_xyz, get_state, set_state,
#     get_acquisition_options, acquire, get_procedures, run_procedure.
#     disconnect is optional.
```

Plug it in once on the microscope computer with
`zmart_controller.register_driver("path/to/my_driver")`. The controller reads
`zmart.json`, picks the functions by name, registers each instrument, and
remembers the driver for later sessions. A missing function or a wrong file is
refused at once, by name.

## Does it fit?

Once the driver connects, let the controller check the answers:

```python
import zmart_controller

problems = zmart_controller.check_driver(instrument)
```

It calls every `get_*` function and compares each report with the contract
below. The answer is a list of problems in plain words; an empty list means
the driver fits. It moves nothing and acquires nothing.

## The contract

Every function except `connect` and `disconnect` returns
`{"success": bool, "report": ...}`. The table gives what the `report` must
contain, so that an experiment written for one microscope keeps working on
another. A driver may add extra keys to any report; it should not leave out the
ones listed here.

| Function | Receives | The `report` must contain |
|---|---|---|
| `connect` | the connection dictionary | *(returns a handle: anything)* |
| `disconnect` *(optional)* | handle | *(returns nothing; afterwards every other call raises `RuntimeError`, and a second `disconnect` is harmless)* |
| `get_info` | handle | `output_root`, the folder where images are saved |
| `get_actuators` | handle | `{axis: [actuator names]}` for `x`, `y`, `z` |
| `get_xyz` | handle, `with_actuators=` | `{axis: {"value", "actuator", "unit", "range"}}` for `x`, `y`, `z`; `value` and `range` (`[min, max]`, how far the axis can travel) in micrometers from the origin |
| `set_xyz` | handle, `x`, `y`, `z`, `with_actuators=` | `position` and `actuators`; raise if the move cannot be confirmed |
| `get_state` | handle | `{"changeable": {...}, "observed": {...}}` |
| `set_state` | handle, state | what was applied; act on `changeable` only |
| `get_acquisition_options` | handle | `{name: {"options": [...], "active": value}}` |
| `acquire` | handle, `acquisition_type=`, `position_label=`, `options=` | `acquisition_type`, `position_label` and the saved file paths |
| `get_procedures` | handle | `{name: {"description", ...}}` |
| `run_procedure` | handle, `{"name": ..., ...}` | `ran`, the name of the procedure; raise `ValueError` for an unknown name |

A *state* has two parts. `"changeable"` holds the settings that `set_state`
applies. `"observed"` is a read-only report, such as which objective is in
place and the pixel size; it is never used as an instruction. When the allowed
values of an option cannot be listed, `"options"` may be a short description
such as `"float > 0"`. Anything in `get_info` beyond `output_root` is an extra
of your driver; an experiment that depends on it will not run elsewhere.

## Rules

- **Refuse by raising; report soft outcomes.** When carrying on would be
  unsafe, raise: `ValueError` when the request itself is wrong (an unknown
  option, a position outside the limits), `RuntimeError` when the microscope
  fails or refuses. The controller passes your error to the user unchanged.
  Use `success: False` only for outcomes it is safe to carry on from, and say
  what happened in the `report`.
- **Reject what you do not understand.** An unknown option name or procedure
  raises `ValueError`. A typo that is silently ignored can cost someone an
  entire experiment.
- **Keep secrets out of error messages.** The connection dictionary may hold
  passwords. Name the keys, never the values.
- **Keep safety and configuration in the driver.** Travel limits, the origin,
  calibration: only the driver knows the hardware. Save them in the computer's
  configuration folder, never in a repository, and load them in `connect`.
- **Test against the mock's tests.** The tests in [`tests/`](../tests/) show the
  behaviour a workflow relies on; running your driver through the same
  scenarios is the quickest way to find gaps.

## Shipping it as a package

A driver that is its own package can be found without `register_driver`: one
line in its `pyproject.toml` names the function to call, and the controller
calls it the first time `get_instruments()` runs.

```toml
[project.entry-points."zmart_controller.drivers"]
acme = "zmart_drivers.acme:register"
```
