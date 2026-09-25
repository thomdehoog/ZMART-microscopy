# nis-assistant

A chat window where you ask for things at the Nikon microscope in your own
words. A language model (Claude `claude-opus-5-5` by default, through
Pydantic AI) does them with the microscope and explains what it did.

It is also a demonstration of the other two parts: it runs its acquisitions as
useq sequences on the nis-useq engine, explains them in useq terms (the
classic form and useq v2), runs sequences made in other useq tools, and can
read the source code of all three parts and of useq-schema to explain how
things work.

This is part 3 of three; see the [overview](../README.md).

## Install and start

On the microscope computer, parts 1 and 2 first, then this part:

```
pip install -e ../1_nis_bridge
pip install -e ../2_nis_useq
pip install -e .
```

Start the bridge in NIS-Elements as part 1's README describes, then:

```
set ANTHROPIC_API_KEY=...
nis-assistant --output D:\runs
```

(In PowerShell, set the key with `$env:ANTHROPIC_API_KEY="..."`.)

Another model works too, for example Gemini:

```
pip install -e ".[google]"
set GOOGLE_API_KEY=...
nis-assistant --output D:\runs --model google:gemini-3.5-flash-lite
```

Things to try: *Where is the stage?* · *What do you see?* · *Is it in focus?* ·
*Switch to FITC at 50 ms* · *Take a Z-stack of 10 um in 1 um steps in DAPI and FITC here* ·
*Image a 3 by 3 grid of tiles around here* · *Run the useq sequence in D:\sequences\cells.json* ·
*Show me the useq sequence for that plan* · *How does the engine move the stage? Show me the code* ·
*What is new in useq v2?*

## What it can do

As tools: read the microscope, move the stage, change the optical
configuration, exposure, objective and PFS, focus (PFS or the NIS image
sweep), and look at an image and describe it. Acquisitions go through useq:

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
- `search_source` and `read_source` search and read the source of the three
  parts and of useq-schema (read only, nothing else on the computer).

Plans run as a classic `useq.MDASequence`, because the pymmcore-plus file
writers (0.18) keep the channel and Z axes only for that form.

## How it stays safe

- **Stage limits you can see and narrow.** Below the chat, six fields (X-, X+,
  Y-, Y+, Z-, Z+) show the limits in force in um. Type a tighter value (for
  example 3000 in Z+) and press *Apply limits*; an empty field keeps NIS's own
  limit on that side, and *Use NIS limits* goes back to NIS's limits
  everywhere. The assistant is told the limits in force with every message.
- **Checks before acting.** Moves are checked against the stage limits, and
  settings against the NIS configuration lists. The image-based focus sweep is
  limited to 100 um and must stay inside the Z limits.
- **Refusals come with advice.** A refused or failed action comes back to the
  assistant with what was refused, why, and what to do next. After a limit
  breach it is told to stop and leave the next number to you, rather than try
  a nearby value. When a name is not known (an optical configuration, an empty
  nosepiece slot), the refusal lists the microscope's own names.
- **A red banner for refusals.** A limit breach or an invalid value is also
  shown in the window directly, whatever the assistant says.
- **Big steps are agreed in the chat first.** Starting an acquisition always
  waits for you: the assistant shows the plan and asks, and the run can start
  only after your reply. A stage move of more than 1 mm in XY or 100 um in Z
  works the same way ("Shall I move 19 mm to x = 20 mm?"). Moves are measured
  from where the stage was when you last wrote, so small steps that add up
  also ask. That the question comes first is in the code, not only in the
  model's instructions. Everything else runs at once.
- **One action at a time,** so each result is seen before the next action.
- **Looking stays out of the chat.** The image goes to the model in a separate
  request with a few measured numbers (brightness, saturation, sharpness).
- **Cancel prompt** stops the assistant: every further tool call in that turn
  does nothing. **Stop microscope** also ends a running acquisition after the
  image being taken. A single stage move that NIS has already started runs to
  its end; the joystick or NIS-Elements stops it sooner. The window does not
  close while the assistant is still working.
- **Clear context** forgets the conversation; **Show tool calls** lists each
  tool call in the chat as it happens.

To keep long conversations quick, the assistant forgets older messages now
and then: after 15 of your messages, the oldest are dropped so that the newest
10 remain. It does this between messages and only now and then, because Claude
checks that its earlier reasoning belongs to the conversation it is sent back
with, and frequent rewriting would spoil that check.

If the connection to the bridge times out (for example because the macro was
stopped), close and reopen the window after restarting the bridge.

## Tests and evaluation

```
pip install -e ".[test]"
pytest                    # offline, about 10 s: a scripted model over a fake NIS
pytest -m hardware -s     # on NIS-Elements with the bridge running (step 3 in the overview)
```

The tests check the code. Whether the assistant does what an operator expects
(acts when a request is clear, asks when it is not, stops at a limit, ignores
instructions hidden in the data) depends on the model, and is checked by the
evaluation. It runs every case in `tests/eval_cases.json` through the real
assistant, with a real model and the fake NIS, and scores the result. Each
run costs API calls.

```
python tests/evals.py --model anthropic:claude-opus-5-5        # needs ANTHROPIC_API_KEY
python tests/evals.py --model google:gemini-3.5-flash-lite     # needs GOOGLE_API_KEY and the [google] extra
python tests/evals.py --holdout --repeat 3                     # other wording; shows cases that pass only sometimes
python tests/evals.py --scoreboard evals-*.jsonl               # pass rates per model and per category
```

Change the instructions while looking at `eval_cases.json` only, then check
with `--holdout`: that shows whether a change made the assistant better, or
only fitted it to the cases.

## Files

| File | What it is |
|---|---|
| `nis_assistant/agent.py` | The assistant: its instructions, tools, plan format, go-ahead rule and memory. |
| `nis_assistant/window.py` | The chat window (`nis-assistant`). |
| `tests/evals.py` | The evaluation with a real model; `eval_cases.json` and `eval_cases_holdout.json`. |

MIT license. Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich.
