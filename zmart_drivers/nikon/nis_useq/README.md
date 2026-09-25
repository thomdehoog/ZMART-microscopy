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
pip install -e ".[pymmcore]"     # the engine
pip install -e ".[assistant]"    # the engine and the chat assistant
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

## The assistant

A chat window where you ask for things in your own words, and Claude (model
`claude-opus-5-5`, through Pydantic AI) does them with the microscope and
explains what it did.

```
set ANTHROPIC_API_KEY=...          (PowerShell: $env:ANTHROPIC_API_KEY="...")
nis-useq-assistant --output D:\runs
```

The assistant is also a demonstration of this package: it runs its
acquisitions as useq sequences, it can explain them in useq terms, and it can
run a sequence made in another useq tool.

Things to try: *Where is the stage?* · *What do you see?* · *Is it in focus?* ·
*Switch to FITC at 50 ms* · *Take a Z-stack of 10 um in 1 um steps in DAPI and FITC here* ·
*Image a 3 by 3 grid of tiles around here* · *Run the useq sequence in D:\sequences\cells.json* ·
*Show me the useq sequence for that plan*.

What it can do, as tools: read the microscope, move the stage, change the
optical configuration, exposure, objective and PFS, focus (PFS or the NIS
image sweep), and look at an image and describe it. Acquisitions go through
useq:

- `plan_acquisition` turns a plan into a `useq.MDASequence` and has the engine
  check every event without moving. A plan has positions, channels (each with
  its exposure, and optionally a single plane instead of the Z-stack, only
  every nth time point, or a focus offset), a Z-stack, a grid of tiles around
  each position, time points, and PFS focus locking. For tiles, the camera
  field is measured with one image, so the objective needs a pixel
  calibration in NIS.
- `plan_useq_sequence` loads a useq sequence made elsewhere (pymmcore-widgets,
  napari-micromanager, a script) from a `.json` or `.yaml` file, or as JSON,
  and checks it the same way.
- `run_acquisition` runs a checked sequence with the pymmcore-plus runner and
  saves it as OME-TIFF (a folder with one file per position when there are
  several), with the sequence itself next to it as `.useq.json`, which other
  useq tools can load again.

How it stays safe:

- **Stage limits you can see and narrow.** Below the chat, six fields (X-, X+,
  Y-, Y+, Z-, Z+) show the limits in force in um. Type a tighter value (for
  example 3000 in Z+) and press *Apply limits*; an empty field keeps NIS's own
  limit on that side, and *Use NIS limits* goes back to NIS's limits
  everywhere. A value beyond NIS's limit is cut back to NIS's, and the
  assistant is told the limits in force with every message.
- **Checks before acting.** Moves are checked against the stage limits, and
  settings against the NIS configuration lists. The image-based focus sweep is
  limited to 100 um and must stay inside the Z limits.
- **Refusals come with advice.** A refused or failed action comes back to the
  assistant as data: what was refused, why, and what to do next. After a limit
  breach, for example, it is told to stop and leave the next number to you,
  rather than try a nearby value. When a name is not known (an optical
  configuration, an empty nosepiece slot), the refusal lists the microscope's
  own names, so the assistant can propose the right one as a question.
- **A red banner for refusals.** A limit breach or an invalid value is also
  shown in the window directly, whatever the assistant says.
- **Big steps are agreed in the chat first.** Starting an acquisition always
  waits for you: the assistant shows the plan and asks, and the run can start
  only after your reply. A stage move of more than 1 mm in XY or 100 um in Z
  works the same way ("Shall I move 19 mm to x = 20 mm?"). Moves are measured
  from where the stage was when you last wrote, so small steps that add up
  also ask. That the question comes first is in the code, not only in the
  model's instructions. Everything else (small moves, settings, the
  objective, focus, looking, planning) runs at once.
- **One action at a time.** The assistant makes one tool call at a time, so
  each result is seen before the next action.
- **Plans are checked before they run.** An acquisition is planned first and
  checked against the microscope (stage limits, channels) without moving or
  imaging, and the run images exactly the positions that were planned.
- **Looking stays out of the chat.** The image goes to the model in a separate
  request with a few measured numbers (brightness, saturation, sharpness), so
  the conversation stays small.
- **Cancel prompt** stops the assistant: every further tool call in that turn
  does nothing. What already started runs on.
- **Stop microscope** does the same and also ends a running acquisition after
  the image being taken. A single stage move that NIS has already started runs
  to its end; the joystick or NIS-Elements stops it sooner. The window does not
  close while the assistant is still working.
- **Clear context** forgets the conversation, and *Show tool calls* lists each
  tool call in the chat as it happens.

A long conversation is made smaller now and then, between two messages: after
15 messages, the oldest are forgotten so that 10 remain, and all but the newest
three keep only a one-line reading of the microscope. Claude Opus 5.5 checks
that its earlier reasoning belongs to exactly the conversation it is sent back
with, so the history otherwise only grows, and at these points the old
reasoning is left out.

If the connection to the bridge times out (for example because the macro was
stopped), close and reopen the window after restarting the bridge.

The assistant runs its plans as classic `useq.MDASequence` objects: the
pymmcore-plus file writers (0.18) keep the channel and Z axes of a classic
sequence, but save a v2 sequence as one flat stack of images.

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
| `nis_useq/agent.py` | The assistant: its tools, the plan format, the go-ahead rule, and its memory. |
| `nis_useq/window.py` | The chat window (`nis-useq-assistant`). |
| `nis_useq/client.py` | `NisClient`: the socket connection to the bridge. |
| `nis_useq/bridge.py` | The server inside NIS-Elements (standard library only). |
| `nis_useq/install_macros.py` | Writes `start_bridge.mac`. |
| `nis_useq/protocol.py` | The message format both sides share. |
| `tests/` | Offline tests over a fake NIS (`fake_nis.py`); the assistant is tested with a scripted model in place of Claude. `test_simulator.py` needs a live NIS. |
| `tests/evals.py` | The behavioural evaluation with a real model: `eval_cases.json`, and `eval_cases_holdout.json` to check a change on cases it was not tuned on. |

## Tests

```
pip install -e ".[test]"
pytest               # offline, about 10 to 20 s: no NIS and no API key needed
pytest -m hardware   # against NIS-Elements with the bridge running
```

The unit tests check the code. Whether the assistant does what an operator
expects (acts when a request is clear, asks when it is not, stops at a limit,
ignores instructions hidden in the data) depends on the model, and is checked
by the evaluation. It runs every case in `tests/eval_cases.json` through the
real assistant, with a real model and the fake NIS, and scores the result.
Each run costs API calls.

```
python tests/evals.py --model anthropic:claude-opus-5-5        # needs ANTHROPIC_API_KEY
python tests/evals.py --model google:gemini-3.5-flash-lite     # needs GOOGLE_API_KEY and pydantic-ai-slim[google]
python tests/evals.py --holdout --repeat 3                     # other wording; shows cases that pass only sometimes
python tests/evals.py --scoreboard evals-*.jsonl               # pass rates per model and per category
```

## Where the NIS function names come from

The macro reference installed with NIS-Elements
(`C:\Program Files\NIS-Elements\Docs\nis\eng_ar\`) lists every function and
its arguments. `g5_regprocs.dll` exports them, and the bridge calls them with
`ctypes`. `Camera_ExposureSet` is not exported; the bridge reaches it through
NIS's own `nis.call_proc`.

MIT license. Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich.
