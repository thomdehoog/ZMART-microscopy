# nis-useq

Run [useq-schema](https://github.com/pymmcore-plus/useq-schema) acquisitions on
a Nikon microscope through NIS-Elements. `NisEngine` is an acquisition engine in
the form [pymmcore-plus](https://github.com/pymmcore-plus/pymmcore-plus) expects,
so its runner can execute a sequence on the Nikon and pass the images to its
file writers (OME-TIFF, OME-Zarr) and viewers. Both the classic
`useq.MDASequence` and the new `useq.v2.MDASequence` work.

Status: tested offline against the real bridge server with a simulated NIS
behind it. The NIS calls it uses are the ones validated on NIS-Elements AR
6.10.02 with the Ti2 simulator. Not yet run on a real microscope.

## How it fits together

```
your Python                         NIS-Elements
NisEngine ── NisClient ── socket ── bridge.py ── g5_regprocs.dll
(useq events)             127.0.0.1  (Python inside NIS, started by a macro)
```

NIS-Elements only accepts calls from the Python that runs inside it. The
bridge is a small server that runs there and answers a fixed list of requests
(move, snap, set the optical configuration, ...). Everything else runs in your
own Python environment on the same computer.

## Install

In the Python environment you acquire from, on the microscope computer:

```
pip install -e ".[pymmcore]"
```

## Start the bridge in NIS-Elements

1. Write the start macro for this computer (once; it contains this folder's path):

   ```
   python -m nis_useq.install_macros
   ```

2. Start NIS-Elements (with the microscope or the simulator).
3. In NIS: *Macro > Run Macro From File...* and pick `nis_useq/start_bridge.mac`.
   The macro keeps running while the bridge is up. That is intended: camera
   commands crash NIS unless they run on its main thread, and the macro loop
   is that thread. Press the macro **Stop** button to end it. Running the macro
   again later is safe; it closes whatever an earlier run left behind.

The bridge writes a log to `nis-useq-bridge.log` in the Windows temp folder.

## Run a sequence

```python
import useq.v2 as v2
from pymmcore_plus.mda import MDARunner
from nis_useq.engine import NisEngine

sequence = v2.MDASequence(
    stage_positions=[(1000, -500, 2500), (1200, -500, 2500)],  # x, y, z in um
    channels=[{"config": "DAPI", "exposure": 20}, "FITC"],
    z_plan={"range": 4, "step": 1},  # 5 planes around each position's z
)

runner = MDARunner()
runner.set_engine(NisEngine())
runner.run(sequence, output="run.ome.zarr")
```

Positions are NIS stage coordinates in micrometres, exactly as NIS shows them.
Before anything moves, the engine checks the whole plan and refuses it as a
whole if something is wrong:

- every position against the stage limits set in NIS;
- every channel name against the NIS optical configurations;
- every property and action, including their values;
- relative Z plans and grids, which need a stage position with x, y and z to be
  laid out around (otherwise useq produces offsets around 0 um, and the stage
  would be sent there);
- tiling grids, which need `fov_width` and `fov_height` in um (otherwise useq
  places the tiles 1 um apart). The error message states the camera field.

One check can only happen during the run: after a focus action, later Z moves
at that position include the focus correction, and a corrected move that would
leave the stage limits stops the run at that point.

## What each useq field does

| Field | On the Nikon |
|---|---|
| `x_pos`, `y_pos`, `z_pos` | Absolute stage position (um). Missing means "stay". |
| `channel.config` | Name of a NIS optical configuration. `group` is ignored. |
| `exposure` | Camera exposure (ms). |
| `properties` | `("Nosepiece", "Position", 2)` turns to slot 2. `("PFS", "State", "On")` or `"Off"` switches the Perfect Focus System. |
| `action` | `AcquireImage` snaps an image. `HardwareAutofocus` locks focus with the PFS, then switches it off. `CustomAction(name="autofocus", data={"range_um": 50, "speed": 30})` runs the NIS image-based focus sweep. |
| `min_start_time` | Handled by the runner (time-lapse). |

After a focus action, later events at the same position are shifted in Z by
the distance the focus moved. With the classic `MDASequence` an autofocus
plan focuses at the position's own z, so a Z-stack stays centred on the
focus. useq v2 (0.9.2) focuses at the first plane of the stack instead, so the
stack then starts at the focus.

useq v2 (0.9.2) also ignores a channel's `z_offset`, which the classic
`MDASequence` applies.

Not supported, and refused: camera ROI, SLM images, other custom actions.
`keep_shutter_open` is ignored because NIS handles the shutter.

## Good to know

- The engine and NIS must run on the same computer: each image is saved by
  NIS as a temporary TIFF and read back.
- Every run starts with one extra snap with the current settings, before the
  plan is checked, so file writers know the image size and pixel size.
- NIS cannot report the camera exposure. Frame metadata carries the exposure
  NIS applied when the sequence set one, or 0 when the sequence set none.
- When a run ends or fails, the PFS is switched back to how the run found it.
  Other settings (stage position, objective, optical configuration) stay as
  the run left them.
- Each request tells the bridge how long the engine will wait. A request NIS
  has not started by then is dropped, so a late move never happens after the
  engine gave up (for example when the macro was stopped).

## Files

| File | What it is |
|---|---|
| `nis_useq/engine.py` | `NisEngine`: turns useq events into bridge requests. |
| `nis_useq/client.py` | `NisClient`: the socket connection to the bridge. |
| `nis_useq/bridge.py` | The server inside NIS-Elements (standard library only). |
| `nis_useq/install_macros.py` | Writes `start_bridge.mac`. |
| `nis_useq/protocol.py` | The message format both sides share. |
| `tests/` | Offline tests over a fake NIS (`fake_nis.py`), and `test_simulator.py` for a live NIS. |

## Tests

```
pip install -e ".[test]"
pytest               # offline, about 5 s, no NIS needed
pytest -m hardware   # against NIS-Elements with the bridge running
```

## Where the NIS function names come from

The macro reference installed with NIS-Elements
(`C:\Program Files\NIS-Elements\Docs\nis\eng_ar\`) lists every function and
its arguments. `g5_regprocs.dll` exports them, and the bridge calls them with
`ctypes`. `Camera_ExposureSet` is not exported; the bridge reaches it through
NIS's own `nis.call_proc`.

MIT license. Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich.
