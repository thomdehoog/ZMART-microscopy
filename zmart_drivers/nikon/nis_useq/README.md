# nis-useq: useq-schema on a Nikon microscope

Run [useq-schema](https://github.com/pymmcore-plus/useq-schema) acquisitions on
a Nikon microscope through NIS-Elements, and talk to the microscope through a
chat assistant that uses them. It comes in three parts, each its own Python
package with its own README and tests, so you can adopt just the part you
need:

| Part | Package | What it does | Builds on |
|---|---|---|---|
| [1_nis_bridge](1_nis_bridge/README.md) | `nis-bridge` | Controls NIS-Elements from your own Python: a small server inside NIS and a client. No useq. | NIS-Elements |
| [2_nis_useq](2_nis_useq/README.md) | `nis-useq` | `NisEngine`, a useq engine for the pymmcore-plus runner: runs classic and v2 useq sequences. | part 1 |
| [3_nis_assistant](3_nis_assistant/README.md) | `nis-assistant` | A chat window whose assistant drives the microscope through useq and explains it. | parts 1 and 2 |

```
nis-assistant ──> nis-useq (NisEngine) ──> nis-bridge (client ── bridge in NIS) ──> microscope
```

None of the three shares code with ZMART. Positions are NIS stage coordinates
in micrometres; nothing here converts coordinate systems.

## Install

On the microscope computer, install the parts you need, in order:

```
pip install -e "./1_nis_bridge[test]"
pip install -e "./2_nis_useq[test]"
pip install -e "./3_nis_assistant[test]"
```

(`[test]` adds pytest, for the tests below; leave it out if you only use the parts.)

Then start the bridge in NIS-Elements (part 1's README, once per session).

## Testing on NIS-Elements

With NIS-Elements running (the simulator or the microscope) and
`start_bridge.mac` started, test the parts in order, and stop at the first
step that fails, since each builds on the one before. Everything stays within
100 um of where the stage is, and the stage is moved back afterwards; still,
keep the objective clear of the sample for the first run.

```
pytest -m hardware -s 1_nis_bridge      # 1. read, move a little, configuration and exposure, snap
pytest -m hardware -s 2_nis_useq        # 2. camera field, limit check, useq v2 and classic, tiles, channel options, a sequence file
pytest -m hardware -s 3_nis_assistant   # 3. the assistant's tools, with a scripted model (no API calls)
```

Run them from this folder.

`-s` prints what NIS reported. Tests that need a pixel calibration for the
objective in use (the camera field, tiles) are skipped without one, and say so.

Then try the assistant with the real model (`nis-assistant --output D:\runs`)
in this order, and check each answer against NIS:

1. *Where is the stage, and which objective is in use?* (reads only)
2. *Move x by 20 um.* (moves at once) and *Move x by 5 mm.* (asks first; answer *no*)
3. *Move z to 20000 um.* (refused: red banner, nothing moves)
4. *Switch to* a configuration NIS has, *at 50 ms.*
5. *What do you see?* (the image appears on the right)
6. *Take a Z-stack of 4 um in 2 um steps here in* a configuration. (shows the
   plan and asks; answer *yes*; the files appear in the output folder)
7. *Image a 2 by 2 grid of tiles around here.* (needs a pixel calibration)
8. *Show me the useq sequence for that plan*, *What is new in useq v2?*, and
   *How does the engine move the stage? Show me the code.*

To let Claude Code on the microscope computer do all of this, give it this prompt:

```
In zmart_drivers/nikon/nis_useq, test the three parts on this NIS-Elements
computer. NIS-Elements is running and start_bridge.mac has been started (ask
me if the bridge does not answer). Work in three steps and stop at the first
failure, showing me the output and what you think went wrong; do not change
code without asking.
1. Run `pytest -m hardware -s 1_nis_bridge`.
2. Run `pytest -m hardware -s 2_nis_useq`, then open the OME-TIFFs it saved
   in the pytest temp folder and tell me their shapes.
3. Run `pytest -m hardware -s 3_nis_assistant`. Then start the window with
   `nis-assistant --output D:\runs` and tell me, one at a time, the prompts
   from the checklist under "Testing on NIS-Elements" in README.md, and what
   to look for after each.
Finish with a short report: what passed, what was skipped and why, and
anything that looked wrong.
```

MIT license. Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich.
