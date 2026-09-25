# nis-bridge

Control NIS-Elements from your own Python. NIS-Elements only accepts calls
from the Python that runs inside it, so this part is a small server (the
bridge) that runs there, plus a client for your own Python environment on the
same computer.

```
your Python                     NIS-Elements
NisClient ── socket ─────────── bridge.py ── g5_regprocs.dll
             127.0.0.1 only     (Python inside NIS, started by a macro)
```

This is part 1 of three; see the [overview](../README.md). It has no useq in
it, so it is useful on its own for any Python that needs to drive a Nikon
microscope.

Status: the NIS calls are the ones validated on NIS-Elements AR 6.10.02 with
the Ti2 simulator. Tested offline against a pretend NIS; the hardware tests
below are the first run on a real NIS.

## Install

In the Python environment you work from, on the microscope computer:

```
pip install -e .
```

## Start the bridge in NIS-Elements

1. Write the start macro for this computer (once; it contains this folder's path):

   ```
   python -m nis_bridge.install_macros
   ```

2. Start NIS-Elements (with the microscope or the simulator).
3. In NIS: *Macro > Run Macro From File...* and pick `nis_bridge/start_bridge.mac`.
   The macro keeps running while the bridge is up. That is intended: camera
   commands crash NIS unless they run on its main thread, and the macro loop
   is that thread. Press the macro **Stop** button to end it. Running the macro
   again later is safe; it closes whatever an earlier run left behind.

The bridge writes a log to `nis-bridge.log` in the Windows temp folder.

## Use it

```python
from nis_bridge.client import NisClient

with NisClient() as nis:                      # 127.0.0.1, port 54470
    print(nis.request("get_position"))        # {"x": ..., "y": ..., "z": ...} in um
    nis.request("move", x=1000, z=2500)       # absolute; axes left out stay
    nis.request("select_optical_configuration", name="DAPI")
    nis.request("snap", path=r"C:\temp\image.tif")
```

A request NIS refuses raises `RuntimeError` with NIS's message; a malformed
request raises `ValueError`. When the bridge does not answer, the client
raises `NisConnectionError` and says what to check.

## What the bridge answers

Only these requests exist; the bridge never runs macro text sent to it.

| Request | Arguments | Returns |
|---|---|---|
| `ping` | | bridge and protocol version |
| `get_position` | | `x`, `y`, `z` in um |
| `get_limits` | | the stage limits set in NIS, per axis `min` and `max` in um |
| `move` | any of `x`, `y`, `z` (um, absolute) | the position after the move |
| `get_optical_configurations` | | the configuration names |
| `select_optical_configuration` | `name` | the selected name |
| `set_exposure` | `exposure_ms` | the exposure NIS applied (it may round) |
| `get_objectives` | | the current nosepiece slot and the objective in each slot |
| `set_objective` | `position` (slot, from 1) | the current slot |
| `get_pfs` | | whether the Perfect Focus System is present, on, and in focus |
| `set_pfs` | `on`, optionally `timeout_s` | the PFS state after switching |
| `autofocus` | `range_um`, `speed` | the position after NIS's image-based focus sweep |
| `snap` | `path` | the path of the saved TIFF and the pixel size in um (None when not calibrated) |
| `shutdown` | | stops the bridge |

Every request carries how long the client will wait. A request NIS has not
started by then is dropped, so a late move never happens after the client
gave up (for example when the macro was stopped).

## Testing without a microscope

`nis_bridge.fake` is a pretend NIS-Elements whose limits, objectives and
optical configurations match the Ti2 simulator. `running_bridge` puts the real
bridge server in front of it, so code built on the client can be tested end
to end without NIS:

```python
from nis_bridge.client import NisClient
from nis_bridge.fake import FakeNisApi, running_bridge

with running_bridge(FakeNisApi()) as server:
    client = NisClient("127.0.0.1", server.server_address[1])
```

## Tests

```
pip install -e ".[test]"
pytest                    # offline, a few seconds
pytest -m hardware -s     # on NIS-Elements with the bridge running (step 1 in the overview)
```

## Files

| File | What it is |
|---|---|
| `nis_bridge/bridge.py` | The server inside NIS-Elements (standard library only). |
| `nis_bridge/client.py` | `NisClient`: the connection from your Python. |
| `nis_bridge/protocol.py` | The message format both sides share. |
| `nis_bridge/install_macros.py` | Writes `start_bridge.mac`. |
| `nis_bridge/fake.py` | A pretend NIS for tests. |

## Where the NIS function names come from

The macro reference installed with NIS-Elements
(`C:\Program Files\NIS-Elements\Docs\nis\eng_ar\`) lists every function and
its arguments. `g5_regprocs.dll` exports them, and the bridge calls them with
`ctypes`. `Camera_ExposureSet` is not exported; the bridge reaches it through
NIS's own `nis.call_proc`.

MIT license. Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich.
