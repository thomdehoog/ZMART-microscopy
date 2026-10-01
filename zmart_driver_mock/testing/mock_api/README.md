# The mock API: MockScope Control

This folder holds pretend vendor software, **MockScope Control**, with a
pretend microscope behind it. It plays the part that LAS X plays for a Leica
microscope, NIS-Elements for a Nikon, or ZEN for a ZEISS. It lets you build
and test every part of a driver on a laptop, without hardware.

In the driver anatomy (`docs/design/driver-anatomy.md` in the
ZMART-microscopy repository), this is the **mock API**: the stand-in at the
very bottom of a driver, below the vendor interface. The driver's vendor
interface talks to MockScope exactly the way a real driver talks to real
vendor software.

## Why it behaves like vendor software, not like ZMART

A stand-in is only useful if it confronts a driver with the same situations
a real microscope does. So MockScope deliberately does not speak ZMART:

| Real vendor software... | ...and so does MockScope |
|---|---|
| has its own command names | `MoveStage`, `SetSetting`, `StartAcquisition`, ... |
| reports raw stage positions, with no origin | x from 0 to 100,000 µm, y from 0 to 75,000 µm |
| often splits focus over two drives | a coarse `focus` drive and a fine `piezo` |
| answers with status codes and messages | `{"ok": False, "code": 201, "message": "Value out of range: ..."}` |
| accepts a command before it has finished | a move is accepted at once and finishes later |
| refuses commands while it is busy | moves and settings are refused with error 100 during an acquisition |
| writes its own file format | `.mraw` files, written in two steps |
| never overwrites a file | a second `cell` becomes `cell_001.mraw` |
| does not tell you how the camera sits, or how objectives are offset | these are hidden, and setup has to measure them |

The driver's vendor interface translates all of this into plain values in
micrometers, and its error handling sorts the codes into kinds.

## Getting started

```python
from zmart_driver_mock.testing.mock_api import MockScope

scope = MockScope(output_folder="images")        # the folder must exist
scope.send("Login", token="mock-token")
scope.send("MoveStage", x=51_000.0, y=37_000.0)  # {"ok": True, "result": {"accepted": "MoveStage"}}
scope.send("GetStagePosition")                   # may still be on its way
```

Every command goes through `scope.send(name, **arguments)` and returns a
reply. `"ok": True` means the software *accepted* the command, not that it
has finished. To know whether it really happened, read back. That is the job
of a driver's set dispatcher.

## Commands

| Command | Arguments | What it does |
|---|---|---|
| `GetVersion` | – | The software name and version. Works without logging in. |
| `Login` | `token` | Opens a session. Every other command needs one. The default token is `"mock-token"`. |
| `Logout` | – | Closes the session. |
| `GetHardware` | – | Serial number, travel ranges, objectives, camera size and the allowed range of each setting. |
| `GetStagePosition` | – | `{"x", "y"}` in raw micrometers. |
| `GetFocus` | – | `{"focus", "piezo"}` in raw micrometers. |
| `GetSettings` | – | The current settings and the objective slot. |
| `GetStatus` | – | `idle`, `moving`, `changing_objective` or `acquiring`, and the last acquisition with its file and state. |
| `GetOutputFolder` | – | Where acquisitions are written. |
| `MoveStage` | `x`, `y` (either or both) | Starts a stage move. |
| `MoveFocus` | `focus`, `piezo` (either or both) | Starts a focus move. |
| `SetSetting` | `name`, `value` | Changes `laser_power_percent` (0–100), `detector_gain` (0–1000) or `exposure_ms` (0.1–10,000). |
| `SetObjective` | `slot` | Changes the objective: 1 (10x), 2 (20x) or 3 (40x). This takes time. |
| `SetOutputFolder` | `folder` | Changes where acquisitions are written. |
| `StartAcquisition` | `name`, optionally `z_planes`, `z_step_um` | Starts an acquisition and replies with the file it will write. |
| `Abort` | – | Stops every movement and any running acquisition, where they are now. |

## Error codes

| Code | Message | What it means for a driver |
|---|---|---|
| 100 | System busy, try again later | Temporary: trying again may work. |
| 200 | Unknown command | A bug in the driver. |
| 201 | Value out of range | A bad request: outside the hardware's own end stops. |
| 202 | Unknown setting | A bad request. |
| 203 | Missing argument | A bad request. |
| 204 | Unknown argument | A bad request. |
| 205 | Invalid value | A bad request: not a number, or a forbidden file name. |
| 206 | Folder does not exist | A bad request. |
| 300 | Hardware fault: controller not responding | Permanent. |
| 401 | Access denied | The token is wrong. |
| 402 | Not logged in | Log in first. |
| 999 | Internal error 0x7F3A | Not recognisable. A driver should treat it as permanent. |

On top of these replies, `send` can raise `ConnectionError` when the
software is not running, and `TimeoutError` when a reply is lost.

## Time

The pretend microscope does not run in the background. Each command first
catches up with the time that has passed since the last one: moves that
should be finished are finished, and acquisitions that should be done are
written.

This has one consequence worth knowing: **a file is only completed when the
software is asked something.** To wait for an acquisition, ask `GetStatus`
until `last_acquisition.state` is `"done"`, then read the file. A real driver
should check the status this way anyway, rather than only watching the file.

For exact, fast tests, use a `FakeClock`, which only moves when you tell it
to:

```python
from zmart_driver_mock.testing.mock_api import FakeClock, MockScope

clock = FakeClock()
scope = MockScope(output_folder="images", clock=clock)
scope.send("Login", token="mock-token")
scope.send("MoveStage", x=60_000.0)
clock.advance(1.0)    # one second passes
```

When a test is not about timing at all, `MockScope.instant(output_folder=...)`
makes everything happen at once. Individual speeds and delays can be changed
with `timing={...}`; see `DEFAULT_TIMING` in `scope.py`.

## Making it fail on purpose

A driver has to handle failures calmly, and the only way to be sure is to
make them happen. `scope.faults.add(command, fault, times=1)` makes the next
call of `command` fail in a chosen way. Use `"*"` for any command, and
`times=None` for every time until `scope.faults.clear()`.

| Fault | What happens | The kind of error a driver should see |
|---|---|---|
| `busy` | Error 100. Nothing is applied. | Temporary |
| `out_of_range` | Error 201. Nothing is applied. | Bad request |
| `hardware_fault` | Error 300. Nothing is applied. | Permanent |
| `unknown_error` | Error 999. Nothing is applied. | Permanent (not recognisable) |
| `timeout` | The command **is** applied, but the reply is lost and `TimeoutError` is raised. | Temporary; only reading back tells whether it worked |
| `ignore` | The reply says OK, but nothing is applied. | Unconfirmed |
| `stale` | A get command repeats its previous answer. | Unknown reading |
| `disconnect` | The software closes. Every call raises `ConnectionError` until `scope.restart()`. | Connection lost |

Every command sent is recorded in `scope.history`, with its time, arguments,
reply code and any fault. The token is recorded as `"<hidden>"`, never its
value. Tests can use the history to check, for example, that nothing was sent
when the limits refused a move.

## The pretend sample and its hidden facts

The pretend microscope looks at a slide covered in small bright spots, like
fluorescent beads. The spots never move, so the same position always shows
the same picture. Spots blur as the focus moves away from the sharp height,
which makes autofocus possible.

Three facts are hidden, the way a real microscope hides them:

- **How the camera sits on the stage.** By default the picture is a mirror
  image: right in the picture is +y on the stage, and down is +x.
  Image-to-stage registration has to find this. Change it with
  `orientation=`.
- **How each objective is offset** from objective 1, in x, y and focus.
  Optical calibration has to find this. Change it with `objective_offsets=`.
- **The tilt of the slide**: the sharp focus height changes slightly across
  the slide. Change it with `tilt=`.

`scope.truth()` returns these answers, so a test can check what a setup
notebook measured. A real microscope has no such function.

Pass `noise=False` for clean pictures without camera noise, which makes
comparisons in tests exact. `seed=` chooses a different pattern of spots.

## The `.mraw` file format

`read_mraw(path)` returns `(description, planes)`. The description is a
dictionary with the image size, number of planes, pixel size, z step, the raw
stage and focus positions, the objective and the settings at the time of
capture. Each plane is an `array("H")` of 16-bit pixel values, row after row.

The software writes the description when an acquisition starts and the
pixels when it finishes. Reading the file in between raises `ValueError`
because it is incomplete. An acquisition that was aborted, or lost when the
software closed, stays incomplete.
