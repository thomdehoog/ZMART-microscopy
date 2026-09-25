# nis-engine

Run [useq-schema](https://github.com/pymmcore-plus/useq-schema) acquisitions on
a Nikon microscope through NIS-Elements. `NisEngine` is an acquisition engine in
the form [pymmcore-plus](https://github.com/pymmcore-plus/pymmcore-plus) expects:
the pymmcore-plus runner walks through a useq sequence one image at a time,
the engine carries out each step on the Nikon (move, set the channel, snap),
and the runner hands the images to its file writers and viewers.

```
your Python                                           NIS-Elements
MDARunner ──── NisEngine ──── NisClient ── socket ─── bridge
pymmcore-plus  this part      part 1 (nis-bridge)
```

This is part 2 of three; see the [overview](../README.md). Positions are NIS
stage coordinates in micrometres (um), exactly as NIS shows them.

## Install

On the microscope computer, part 1 first, then this part:

```
pip install -e ../1_nis_bridge
pip install -e .
```

Start the bridge in NIS-Elements as part 1's README describes (or, to try
things without a microscope, `python -m nis_bridge.fake`).

## Run a sequence

This takes a 5-plane Z-stack in two channels at the current position and at a
second one 50 um to the right, and saves it as OME-TIFF:

```python
import useq
from pymmcore_plus.mda import MDARunner
from nis_engine import NisEngine

engine = NisEngine()
here = engine.client.request("get_position")
channels = engine.client.request("get_optical_configurations")[:2]

sequence = useq.MDASequence(
    stage_positions=[
        {"x": here["x"], "y": here["y"], "z": here["z"], "name": "here"},
        {"x": here["x"] + 50, "y": here["y"], "z": here["z"], "name": "right"},
    ],
    channels=[{"config": name, "exposure": 20} for name in channels],
    z_plan={"range": 4, "step": 1},  # 5 planes, 1 um apart, around each position's z
)

runner = MDARunner()
runner.set_engine(engine)
runner.run(sequence, output="run.ome.tiff")
```

With two positions the writer makes a folder `run/` with one file per
position, each holding channels x planes x image. Open them in Fiji (drag the
file in; Bio-Formats reads OME-TIFF) or napari.

Before anything moves, the engine checks the whole plan and refuses it as a
whole if something is wrong:

- every position against the stage limits;
- every channel name against the NIS optical configurations;
- every property and action, including their values;
- relative Z plans and grids, which need a stage position with x, y and z to be
  laid out around (otherwise useq produces offsets around 0 um, and the stage
  would be sent there);
- tiling grids, which need the camera field in um (otherwise useq places the
  tiles 1 um apart).

`engine.check(sequence)` runs the same checks without moving or imaging, and
returns the steps it would take, so you can look at a plan first.

## Tiles

A grid needs the size of the camera field, which the engine measures with one
image and NIS's pixel calibration for the objective in use:

```python
width, height = engine.field_of_view()   # um
sequence = useq.MDASequence(
    stage_positions=[(here["x"], here["y"], here["z"])],
    channels=[channels[0]],
    grid_plan={"rows": 2, "columns": 2, "overlap": (10, 10),
               "fov_width": width, "fov_height": height},
)
```

## Narrower limits for a session

To stay inside a smaller area than NIS allows, for example for one sample
holder, narrow the limits for the session:

```python
engine.set_limits(x=(-5000, 5000), z=(None, 3000))  # um; None or a missing axis: NIS's own
```

These come on top of the NIS limits: an axis can get narrower, never wider.
One check can only happen during the run: after a focus action, later Z moves
at that position include the focus correction, and a corrected move that would
leave the limits stops the run at that point.

## useq v2

The new `useq.v2.MDASequence` runs the same way (`import useq.v2 as v2`, then
`v2.MDASequence(...)` with the same fields). Three cautions with useq-schema
0.9.2: the pymmcore-plus file writers (0.18) save a v2 sequence as one flat
stack of images, without its channel and Z axes, so use the classic
`useq.MDASequence` when the saved file matters; an autofocus plan focuses at
the first plane of a Z-stack, where the classic form focuses at the
position's own z; and a channel's `z_offset` is ignored.

## What each useq field does

| Field | On the Nikon |
|---|---|
| `x_pos`, `y_pos`, `z_pos` | Absolute stage position (um). Missing means "stay". |
| `channel.config` | Name of a NIS optical configuration. `group` is ignored. |
| `exposure` | Camera exposure (ms). |
| `properties` | `("Nosepiece", "Position", 2)` turns to slot 2. `("PFS", "State", "On")` or `"Off"` switches the Perfect Focus System (PFS). |
| `action` | `AcquireImage` snaps an image. `HardwareAutofocus` locks focus with the PFS, then switches it off. `CustomAction(name="autofocus", data={"range_um": 50, "speed": 30})` runs the NIS image-based focus sweep. |
| `min_start_time` | Handled by the runner (time-lapse). |

After a focus action, later steps at the same position are shifted in Z by
the distance the focus moved.

Not supported, and refused before the run: camera ROI, SLM images, other
custom actions, and colour cameras (set the camera to monochrome in NIS).
`keep_shutter_open` is ignored because NIS handles the shutter.

## Good to know

- The engine and NIS must run on the same computer: each image is saved by
  NIS as a temporary TIFF and read back.
- Every run starts with one extra snap with the current settings, so file
  writers know the image size and pixel size.
- NIS cannot report the camera exposure. Frame metadata carries the exposure
  NIS applied when the sequence set one, or 0 when it set none.
- When a run ends or fails, the PFS is switched back to how the run found it,
  if NIS still answers. Other settings (stage position, objective, optical
  configuration) stay as the run left them.
- If the connection to the bridge was lost, `engine.reconnect()` opens a new
  one once `start_bridge.mac` runs again.

## Files

| File | What it is |
|---|---|
| `nis_engine/engine.py` | `NisEngine`: checks a useq sequence, then turns each step into bridge requests. |

## Tests

```
pip install -e ".[test]"
pytest                    # offline, a few seconds, over nis-bridge's fake NIS
pytest -m hardware -s     # on NIS-Elements with the bridge running (step 2 in the overview)
```

MIT license. Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich.
