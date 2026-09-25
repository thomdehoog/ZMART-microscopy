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

Status: the NIS functions it calls were validated on NIS-Elements AR 6.10.02
with the Ti2 simulator. The package itself is tested offline, against a fake
NIS behind the real bridge server; its hardware tests are for NIS-Elements.

## Install

In the Python environment you work from, on the microscope computer:

```
pip install -e .
```

Install it editable (`-e`), as shown: the start macro points NIS-Elements at
this folder, so the bridge must run from here, not from a copy in
site-packages.

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

NIS then shows "nis-bridge: running on port 54470". To check from your own
Python:

```
python -c "from nis_bridge.client import NisClient; print(NisClient().request('ping'))"
```

The bridge writes a log to `nis-bridge.log` in the Windows temp folder.

## Use it

```python
from pathlib import Path
from nis_bridge.client import NisClient

with NisClient() as nis:                                  # 127.0.0.1, port 54470
    here = nis.request("get_position")                    # {"x": ..., "y": ..., "z": ...} in um
    nis.request("move", x=here["x"] + 20)                 # absolute; axes left out stay
    names = nis.request("get_optical_configurations")
    nis.request("select_optical_configuration", name=names[0])
    reply = nis.request("snap", path=str(Path.home() / "snap.tif"))
    print(reply["path"], reply["pixel_size_um"])
    nis.request("move", **here)                           # back to where it was
```

`move` goes exactly where it is told: this part does not check the stage
limits itself, and only NIS may refuse. For moves checked against the limits
(and limits you can narrow), use `NisEngine` from part 2.

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

`nis_bridge.fake` is a fake NIS-Elements whose limits, objectives and
optical configurations match the Ti2 simulator. To try things by hand, serve
it on the bridge's usual port, in place of NIS (Ctrl+C stops it):

```
python -m nis_bridge.fake
```

In your own tests, `running_bridge` puts the real bridge server in front of it
on a free port, so code built on the client is tested end to end:

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
ruff check . && ruff format --check .   # lint and formatting, rules in pyproject.toml
```

## Files

| File | What it is |
|---|---|
| `nis_bridge/bridge.py` | The server inside NIS-Elements (standard library only). |
| `nis_bridge/client.py` | `NisClient`: the connection from your Python. |
| `nis_bridge/protocol.py` | The message format both sides share. |
| `nis_bridge/install_macros.py` | Writes `start_bridge.mac`. |
| `nis_bridge/fake.py` | A fake NIS for tests. |

## Where the NIS function names come from

The macro reference installed with NIS-Elements
(`C:\Program Files\NIS-Elements\Docs\nis\eng_ar\`) lists every function and
its arguments. `g5_regprocs.dll` exports them, and the bridge calls them with
`ctypes`. `Camera_ExposureSet` is not exported; the bridge reaches it through
NIS's own `nis.call_proc`.

MIT license. Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich.
