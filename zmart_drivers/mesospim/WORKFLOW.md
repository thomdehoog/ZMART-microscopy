# Driving mesoSPIM from Python — workflow manual

This is the end-to-end manual for controlling a **mesoSPIM** light-sheet microscope
from an external process (a script, a notebook, or a ZMART workflow), using the
**Remote Scripting** bridge plus the ZMART mesoSPIM driver and controller adapter.

You get two levels of API:

- **Neutral controller** (`zmart_controller`) — the vendor-agnostic surface a
  workflow uses (`get_xyz` / `set_xyz` / `get_state` / `acquire` …). **Use this by
  default** — the same code drives Leica/Zeiss/mesoSPIM.
- **Flat driver** (`import mesospim`) — the mesoSPIM-specific API (every laser/ETL
  knob, `run_acquisition_list`, …) for anything the neutral surface doesn't cover.

```
  your workflow / notebook (MIT)
        │  import zmart_controller           ← neutral, vendor-agnostic
        ▼
  mesospim_zmart_adapter  ─ import mesospim  ← the mesoSPIM driver (MIT)
        │  inject Python script over TCP (length-framed, token-gated)
        ▼
  mesoSPIM-control  ── Tools → Remote Scripting server (GPL, the pull_request/ PR)
        │  Core.execute_script(script)   (self == Core)
        ▼
  the microscope (or the -D demo backends)
```

The socket is the license boundary: your client stays **MIT**, mesoSPIM stays
**GPL**, and the only vocabulary on the wire is "here is some Python, here is its
console output."

---

## 1. Prepare mesoSPIM-control (one time) — apply the PR

The Remote Scripting server is a small upstream patch (see [`pull_request/`](pull_request/)).
Apply it to your mesoSPIM-control checkout:

```bash
# on the v1.20.0 release tag (the patch's base):
git checkout -b remote-scripting v1.20.0
git am pull_request/0001-Add-optional-remote-scripting-server-Tools-Remote-Sc.patch

# on a newer branch (e.g. release/candidate-py312) — 3-way, one trivial conflict:
git apply --3way pull_request/0001-Add-optional-remote-scripting-server-Tools-Remote-Sc.patch
#   → keep BOTH sides of the one MainWindow signal-connection conflict.
```

Validated end to end on **both** v1.20.0 and `release/candidate-py312`.

## 2. Point at the driver

The driver is pure standard-library on the client side (sockets + JSON); no heavy
deps. Put the drivers dir on `PYTHONPATH` (and the repo root for `zmart_controller`):

```python
import sys
sys.path.insert(0, r"…/ZMART-microscopy")                 # for zmart_controller
sys.path.insert(0, r"…/ZMART-microscopy/zmart_drivers")   # for `import mesospim`
```

Importing the driver self-registers it with the controller:

```python
import mesospim   # registers instrument (vendor=mesospim, api=remote-scripting)
```

## 3. Start the Remote Scripting server

**Secure by default.** The server is **OFF** until an operator starts it, and when
started it is **token-gated** — do not run it open on anything but localhost.

### Operator (GUI)
First **enable it**: set `enable_remote_scripting = True` in your mesoSPIM config (the
menu is hidden otherwise — an unmodified install can't start it). Then in mesoSPIM:
**Tools → Remote Scripting…**. The dialog pre-fills a fresh **token** (keep it — copy it
to your client) and binds `127.0.0.1:42000`. Click **Start**. (Binding to a
non-localhost host with no token is refused with a warning.)

### Headless / CI / the `-D` demo
Use the bundled launcher, which boots the demo offscreen and starts the server with
a token you choose:

```powershell
$env:MESOSPIM_CONTROL_ROOT = "…/mesoSPIM-control"   # a checkout with the PR applied
$env:MESOSPIM_TOKEN        = "choose-a-token"
python zmart_drivers/mesospim/tests/hardware/launch_demo_server.py
# → prints:  LISTENING 127.0.0.1:42000 token=choose-a-token
```

## 4. Drive the microscope — neutral controller (recommended)

```python
import zmart_controller
import mesospim   # registers the instrument at import

sess = zmart_controller.set_instrument({
    "vendor": "mesospim", "microscope": "mesospim-01", "api": "remote-scripting",
    "host": "127.0.0.1", "port": 42000, "token": "choose-a-token",   # omit if open
})

sess.get_context()             # identity, initial positions, focus/rotation, output_root
sess.get_actuators()           # {'x': ['motoric'], 'y': [...], 'z': [...]}
sess.get_xyz()                 # {'x': {'value','actuator','unit'}, ...} — µm from origin
sess.get_state()               # {'changeable': {laser,intensity,filter,zoom,shutter,etl_*}, 'observed': {...}}
sess.get_acquisition_options() # {format, planes, z_step, zoom, shutterconfig, backlash_correction}

# Frame origin: set the current stage position as (0,0,0), then move in µm from it.
sess.set_origin()              # persisted machine-locally; restored on reconnect
sess.set_xyz(50, 0, 10)        # move to x=50 µm, y=0, z=10 (relative to origin)

# Change light-path settings (the 'changeable' block):
sess.set_state({"laser": "488 nm", "intensity": 20, "filter": "Empty", "zoom": "1x"})

# Focus / rotation / autofocus etc. are exposed as procedures:
sess.get_procedures()                       # move_focus, move_rotation, zero_stage, ...
sess.set_procedure({"name": "move_focus", "value": 5100.0})

# Acquire one frame at a labelled position; returns the written files.
r = sess.acquire("snap", "A1", options={"format": "ome-tiff"})
#   → {'image_files': [...snap_A1.tiff], 'metadata_file': [...snap_A1.json], 'planes': 1, ...}

sess.disconnect()
```

## 4b. Drive it — flat driver (mesoSPIM-specific)

```python
import mesospim as drv
c = drv.connect({"host": "127.0.0.1", "port": 42000, "token": "choose-a-token"})

drv.get_config(c)      # lasers / filters / zooms / camera / app / version
drv.get_positions(c)   # {x,y,z,f,theta}
drv.set_filter(c, "Empty"); drv.set_zoom(c, "1x"); drv.set_intensity(c, 20)

# Moves are FAIL-CLOSED on the flat API: configure the stage envelope first
# (the controller path in §4 does this for you at connect):
drv.set_stage_limits(x=(0, 25000), y=(0, 25000), z=(0, 25000), f=(0, 25000), theta=(-360, 360))
drv.move_absolute(c, {"x": 50.0, "z": 10.0})          # µm

result = drv.acquire(c, "snap", options={"folder": r"D:\out", "filename": "snap.tiff", "planes": 1})
saved  = drv.save(result, r"D:\out\run", position_label="A1")   # relocate + JSON sidecar
drv.close(c)
```

## 5. Key behaviours & gotchas

- **Run-state is not observable.** Every read runs inside `Core.execute_script`,
  which reports `'running_script'` for the read's duration. So `get_state()['state']`
  and `get_progress()['state']` are `None` (unknown), and there is no `is_idle`.
  **Judge acquisition completion from the file on disk**, not from state — the driver
  already does this (it polls until the frame file's size stops growing).
- **Position/settings ARE truthful** — only the run-state string is masked.
- **One client at a time.** A new connection preempts a stale one. A dropped or
  crashed client can neither wedge nor crash mesoSPIM (teardown is guarded).
- **The GUI blocks while a script runs** (it runs on the Core thread). The driver
  keeps every injected script short and polls between them — don't inject a long
  `sleep`.
- **Token.** Plain TCP: the token gates casual LAN access, it is **not** sniffer-proof.
  On untrusted networks, tunnel it (SSH/VPN).
- **Backlash take-up** on `acquire` is best-effort: it is skipped (with a warning) if
  the take-up move would leave the stage envelope — e.g. exactly at the lower limit.

## 6. Test it

```powershell
# offline (no mesoSPIM, no hardware) — mock server exercises the real scripts:
python zmart_drivers/mesospim/run_ci.py offline          # 130 tests

# online (needs a live server from §3) — driver + adapter round-trip incl. acquire:
$env:MESOSPIM_TOKEN = "choose-a-token"; $env:MESOSPIM_ALLOW_ACQUIRE = "1"
python zmart_drivers/mesospim/run_ci.py online           # 11 tests
```

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `authentication failed (server said 'AUTH-FAILED')` | Wrong/missing token. Use the exact token the server printed / the dialog shows. |
| Every integration test **skips** | Nothing is listening on `MESOSPIM_HOST:PORT` — start the server (§3). |
| `move_*` returns `success=False`, "outside limits" | Flat API is fail-closed — call `set_stage_limits(...)` first (the controller does this automatically). |
| `acquire(...) did not produce a stable stack` | The run never wrote a file — check the `folder`/`filename` and that the writer is enabled; on real hardware confirm `start(row=…)` is the right entry point for your build. |
| Headless launcher hangs "Installing torch …" | A newer mesoSPIM's ImageProcessor plugins pip-install torch at import; the bundled launcher already neutralises this — make sure you're running the committed `launch_demo_server.py`. |

---
Author: Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch ·
thomdehoog@gmail.com · MIT (client side).
