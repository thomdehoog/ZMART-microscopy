# nis-useq

Run [useq-schema](https://github.com/pymmcore-plus/useq-schema) acquisitions on
a Nikon microscope through NIS-Elements. `NisEngine` is an acquisition engine in
the form [pymmcore-plus](https://github.com/pymmcore-plus/pymmcore-plus) expects,
so its runner can execute a sequence on the Nikon and pass the images to its
file writers (OME-TIFF, OME-Zarr) and viewers. Both the classic
`useq.MDASequence` and the new `useq.v2.MDASequence` work.

```
your Python                                           NIS-Elements
MDARunner ──── NisEngine ──── NisClient ── socket ─── bridge
pymmcore-plus  this part      part 1 (nis-bridge)
```

This is part 2 of three; see the [overview](../README.md). It builds on part 1
and does nothing with coordinate systems: positions are NIS stage coordinates
in micrometres, exactly as NIS shows them.

## Install

On the microscope computer, part 1 first, then this part:

```
pip install -e ../1_nis_bridge
pip install -e .
```

Start the bridge in NIS-Elements as part 1's README describes.

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

Before anything moves, the engine checks the whole plan and refuses it as a
whole if something is wrong:

- every position against the stage limits;
- every channel name against the NIS optical configurations;
- every property and action, including their values;
- relative Z plans and grids, which need a stage position with x, y and z to be
  laid out around (otherwise useq produces offsets around 0 um, and the stage
  would be sent there);
- tiling grids, which need `fov_width` and `fov_height` in um (otherwise useq
  places the tiles 1 um apart). `engine.field_of_view()` measures the camera
  field with one image and NIS's pixel calibration.

`engine.check(sequence)` runs the same checks without moving or imaging and
returns the events, for looking at a plan before running it.

To stay inside a smaller area than NIS allows, for example for one sample
holder, narrow the limits for the session:

```python
engine = NisEngine()
engine.set_limits(x=(-5000, 5000), z=(None, 3000))  # um; None or a missing axis: NIS's own
```

These come on top of the NIS limits: an axis can get narrower, never wider.

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
stack then starts at the focus. useq v2 (0.9.2) also ignores a channel's
`z_offset`, which the classic `MDASequence` applies.

Not supported, and refused: camera ROI, SLM images, other custom actions.
`keep_shutter_open` is ignored because NIS handles the shutter.

## Good to know

- The engine and NIS must run on the same computer: each image is saved by
  NIS as a temporary TIFF and read back.
- Every run starts with one extra snap with the current settings, so file
  writers know the image size and pixel size.
- NIS cannot report the camera exposure. Frame metadata carries the exposure
  NIS applied when the sequence set one, or 0 when it set none.
- When a run ends or fails, the PFS is switched back to how the run found it.
  Other settings (stage position, objective, optical configuration) stay as
  the run left them.
- The pymmcore-plus OME-TIFF writer (0.18) keeps the channel and Z axes of a
  classic `MDASequence`, but saves a v2 sequence as one flat stack. With
  several positions it writes a folder with one file per position.

## Tests

```
pip install -e ".[test]"
pytest                    # offline, a few seconds, over nis-bridge's pretend NIS
pytest -m hardware -s     # on NIS-Elements with the bridge running (step 2 in the overview)
```

MIT license. Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich.
