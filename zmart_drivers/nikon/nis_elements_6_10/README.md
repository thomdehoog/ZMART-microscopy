# Nikon NIS-Elements driver

> **Status:** simulator-validated (2026-09-18) on **NIS-Elements AR 6.10.02**
> with the Ti2 simulator. The full ZMART round trip runs — connect, set origin,
> move, **acquire** (snapshot and **Z-stack**), state (objective, optical
> configuration, exposure, PFS), procedures (autofocus, live/freeze, PFS).
> Offline suite: 52 tests, no NIS needed; hardware suite: 7 against the
> simulator. Not yet run on a real microscope. The folder name carries the NIS
> version the driver was built against; other versions may need small changes
> in `bridge/nis_bridge.py`.

This driver lets ZMART drive a Nikon microscope through NIS-Elements. It is a
sibling of the Leica, mesoSPIM and ZEISS drivers and speaks the same neutral
`zmart_controller` interface, so a workflow written for one of them runs here
unchanged.

## How it works (one picture)

```
  your Python (ZMART)                       NIS-Elements (nis_ar.exe)
  ┌──────────────────────┐   local TCP     ┌───────────────────────────────────┐
  │ nis_elements_6_10 package │ ─── JSON ─────▶ │ bridge/nis_bridge.py              │
  │  readers / commands  │ ◀── lines ───── │  (Python inside NIS, started by   │
  │  nis_zmart_adapter   │  127.0.0.1:54468│   start_bridge.mac)               │
  └──────────────────────┘                 │      │ ctypes                     │
                                           │      ▼                            │
                                           │ g5_regprocs.dll  StgMove, Capture │
                                           └───────────────────────────────────┘
```

NIS-Elements ships its own Python interpreter, and every macro command NIS
knows (`StgMoveXY`, `Capture`, `ImageSaveAs`, …) is also a plain function in
`g5_regprocs.dll`. So a small Python program **inside** NIS can call those
functions directly; that is what Nikon's own Python modules do. Our program is
the **bridge**: it listens on the local machine only and answers a fixed list
of requests (read position, move, capture, save, …) from the ZMART side.

Nothing needs to be installed into NIS-Elements, and no admin rights are
needed. The bridge is a file in this repository that NIS runs from a macro.

## Setting it up on the microscope PC

1. **Have this repository on the PC** (any folder) and write the two NIS
   macros for it — they need the folder's path, so they are generated once per
   computer (and ignored by git):

   ```
   cd <repo>\zmart_drivers\nikon
   python -m nis_elements_6_10.bridge.install
   ```

   This writes `bridge/start_bridge.mac` and `bridge/stop_bridge.mac` and
   prints where they are. Any Python 3.10+ will do; nothing is installed.
2. **Start NIS-Elements** (with the microscope, or the simulator).
3. **Start the bridge:** in NIS, *Macro ▸ Run Macro From File…* and pick
   `bridge/start_bridge.mac`. Two short texts appear ("starting", then
   "running on port 54468"). The macro then stays running — that is intended,
   see the note below. A log is written to `zmart-nikon-bridge.log` in the
   NIS user's temp folder.
4. **Use the driver from Python** (the normal ZMART environment, see
   `getting_started/`):

   ```python
   import sys

   sys.path.insert(0, r"...\ZMART-microscopy\zmart_drivers\nikon")
   import nis_elements_6_10  # registers the instrument with zmart_controller

   from zmart_controller.layer import set_instrument

   s = set_instrument({**nis_elements_6_10.CONNECTION, "output_root": r"D:\runs\today"})
   s.set_origin()  # here is (0, 0, 0) from now on
   s.set_xyz(100, -100, 5)  # micrometres from the origin
   s.acquire(acquisition_type="snap", position_label="tile_01")
   s.disconnect()
   ```

   Or without the controller, using the driver directly:

   ```python
   client = nis_elements_6_10.connect()
   nis_elements_6_10.get_position(client)  # {'x': ..., 'y': ..., 'z': ...}  µm
   nis_elements_6_10.move_xyz(client, 0, 0, 500)  # refused if outside the NIS stage limits
   nis_elements_6_10.capture(client)
   nis_elements_6_10.save_image(client, r"D:\runs\snap.tif")
   ```

5. **Stop the bridge** when you are done: press the macro **Stop** button in
   NIS. (NIS runs one macro at a time, so `stop_bridge.mac` cannot get a turn
   while the loop runs; from Python, `client.request("shutdown")` ends the
   loop too.) Re-running `start_bridge.mac` later is safe: it reloads the
   bridge code and closes any bridge left over from an earlier run.

   Known quirk: after the bridge has run, NIS-Elements can stay alive as a
   background process when its window is closed, and the next start then says
   "another instance is running". End `nis_ar.exe` in Task Manager (or
   `Stop-Process -Name nis_ar` in PowerShell) and start NIS again.

### Why the macro keeps running

NIS-Elements only tolerates camera and image-window commands (`Capture`,
`ImageSaveAs`) on its main thread; calling them from another thread crashes
the application — we found that out on the simulator. So the bridge's network
side only *queues* requests, and the small loop in `start_bridge.mac` runs them
on the main thread every 20 ms. While that loop runs, NIS shows a macro as
"running". Reading the position or moving the stage works either way; capture
needs the loop.

## What the driver offers today

| Neutral surface | Nikon meaning |
|---|---|
| `get_xyz` / `set_xyz` | XY stage and the main Z (focus) drive, µm, absolute. Every move is checked against the limits NIS-Elements reports (*Devices ▸ Stage limits*) before it is sent. When NIS reports a piezo Z insert, `with_actuators={"z": "piezo"}` drives it instead of the focus drive. |
| `set_origin` | Marks the current position as (0, 0, 0). Saved to `C:\ProgramData\zmart-microscopy\nikon\<microscope>\origin.json`, restored on the next connect. |
| `acquire` | A snapshot (`Capture()`), or a **Z-stack** through NIS's ND acquisition when the acquisition type contains "stack" (`z_start`, `z_end`, `z_step` in µm from the origin). Saved as TIFF, ND2 or OME-TIFF to `<output_root>/data/<type>_<label>.<ext>`, then the NIS window is closed. Options may also select an optical configuration and set the exposure first. |
| `get_state` / `set_state` | Changeable: `objective_position` (nosepiece slot, 1-based), `optical_configuration` (by name), `exposure_ms`, `pfs` (on/off, when a PFS is present). Observed: NIS version, objectives, optical configurations, Z drives, PFS status, limits. |
| `get_procedures` / `run_procedure` | `autofocus` (NIS's image-based focus sweep over `range_um`; reports `frame_z_um`), `live` / `freeze`, `pfs_on` / `pfs_off`. |
| `get_info` | Initial position, limits, objectives, pixel calibration of the current image, output root. |

Two honest limitations. The camera exposure cannot be read back from NIS
without a blocking dialog, so `exposure_ms` reports the value last set
through the bridge (None before that). And on the simulator, autofocus answers
"focus failed" because its flat image gives the focus criterion nothing to
work with; the call itself is exercised.

Not covered yet: multi-point ND experiments (ZMART does its own tiling),
multi-channel captures beyond what an optical configuration sets.

## Files

| Path | What it is |
|---|---|
| `bridge/nis_bridge.py` | The server that runs inside NIS. `NisApi` holds the ctypes wrappers (one per NIS function), `Operations` the allowed requests, `BridgeServer` the socket + queue. |
| `bridge/install.py` | Writes `start_bridge.mac` / `stop_bridge.mac` with this computer's repository path. |
| `protocol.py` | The message format both sides share (one JSON object per line). |
| `connection/` | `NisClient` (the socket client) and `connect`/`close`. |
| `readers/` | Read-only questions: position, limits, objectives, optical configurations, calibration, Z drives, PFS, exposure. |
| `commands/` | Moves (limit-checked, incl. piezo Z), objective / optical-configuration / exposure / PFS setting, autofocus, live/freeze, capture, Z-stack, save. |
| `calibration/machine.py` | Where the persisted origin lives. |
| `nis_zmart_adapter.py` | The `zmart_controller` ops table and registration. |
| `tests/` | `unit/` runs the real bridge server over a fake NIS API (`tests/helpers/fake_nis_api.py`); `hardware/` runs against a live NIS (`pytest -m hardware`). |

## Running the tests

From this folder, in an environment with `pytest` (for example the
`zmart-dev` conda env):

```
pytest              # offline: 52 tests, ~20 s, no NIS needed
pytest -m hardware  # against a running NIS with start_bridge.mac active
ruff check . && ruff format --check .
```

## Where the NIS function names come from

The signatures behind `NisApi` are taken from the macro reference installed
with NIS-Elements: `C:\Program Files\NIS-Elements\Docs\nis\eng_ar\`
(`FunctionList_6.10.02.html` lists every function; the `XY`, `XYZ`, `Z`,
`Nosepiece`, `OpticalConfiguration` and `ImageDocument` pages give the
arguments). Text arguments are wide strings (`c_wchar_p`); positions are
micrometres; device functions return `DR_OK (1)` on success and a negative
`DR_*` code on failure, which the bridge turns into a readable error.

A few functions (`Camera_ExposureSet`, `Live`, `Freeze`) are not exported by
the DLL at all; NIS registers them internally, and the bridge reaches them by
name through the built-in `nis.call_proc`, which answers with a list — the
return value first, then each argument as it is after the call.

## Security note

The bridge listens on `127.0.0.1` only and executes only the operations in
`nis_bridge.OPS`; it never runs macro text sent over the socket. Anyone who
can log in to the microscope PC could talk to it, which is the same trust
boundary as sitting at the keyboard.
