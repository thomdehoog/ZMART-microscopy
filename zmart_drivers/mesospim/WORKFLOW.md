# Driving mesoSPIM from Python — workflow manual

This is the end-to-end manual for controlling a **mesoSPIM** light-sheet microscope
from an external process (a script, a notebook, or a ZMART workflow), using
mesoSPIM's **Remote Control** server plus the ZMART mesoSPIM driver and controller
adapter.

You get two levels of API:

- **Neutral controller** (`zmart_controller`) — the vendor-agnostic surface a
  workflow uses (`get_xyz` / `set_xyz` / `get_state` / `acquire` …). **Use this by
  default** — the same code drives Leica/Zeiss/Nikon/mesoSPIM.
- **Flat driver** (`import mesospim`) — the mesoSPIM-specific API (every laser/ETL
  knob, `run_acquisition_list`, …) for anything the neutral surface doesn't cover.

```
  your workflow / notebook (MIT)
        │  import zmart_controller           ← neutral, vendor-agnostic
        ▼
  mesospim_zmart_adapter  ─ import mesospim  ← the mesoSPIM driver (MIT)
        │  named JSON calls over TCP (length-framed, password-gated)
        ▼
  mesoSPIM-control  ── Remote Control tab → TCP server (GPL; pull request #106)
        │  validates, admits one change at a time, calls the Core
        ▼
  the microscope (or the -D demo backends)
```

The socket is the license boundary: your client stays **MIT**, mesoSPIM stays
**GPL**, and the only vocabulary on the wire is a fixed list of named calls the
server validates itself.

---

## 1. Prepare mesoSPIM-control (one time)

Remote Control is part of mesoSPIM-control from
[pull request #106](https://github.com/mesoSPIM/mesoSPIM-control/pull/106). Until it
is merged, run its branch:

```bash
git clone https://github.com/thomdehoog/mesoSPIM-control
cd mesoSPIM-control
git checkout remote-control-py312
```

Once the pull request is merged, any mesoSPIM-control that carries the **Remote
Control** tab will do; nothing on the ZMART side changes.

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
import mesospim   # registers instrument (vendor=mesospim, api=remote-control)
```

## 3. Start the Remote Control server

**Off until you start it.** The server is **OFF** until an operator starts it, and it
always asks for a password.

### Operator (GUI)
In mesoSPIM: open the **Remote Control** tab. Choose **TCP**, keep host `127.0.0.1`
and port `42000`, set a password (the pre-filled `smart_mesospim` is public and is
only accepted on the local machine), and click **Start**. The tab shows the address
once the server is listening.

### Headless / CI / the `-D` demo
Use the bundled launcher, which boots the demo offscreen and starts the TCP
transport with a password you choose:

```powershell
$env:MESOSPIM_CONTROL_ROOT = "…/mesoSPIM-control"   # a checkout that carries Remote Control
$env:MESOSPIM_TOKEN        = "choose-a-password"
python zmart_drivers/mesospim/tests/hardware/launch_demo_server.py
# → prints:  LISTENING 127.0.0.1:42000 token=choose-a-password
```

## 4. Drive the microscope — neutral controller (recommended)

```python
import zmart_controller
import mesospim   # registers the instrument at import

sess = zmart_controller.set_instrument({
    "vendor": "mesospim", "microscope": "mesospim-01", "api": "remote-control",
    "host": "127.0.0.1", "port": 42000, "token": "choose-a-password",   # token None = the local default
})

sess.get_info()                # identity, initial positions, focus/rotation, limits, canvas, output_root
sess.get_actuators()           # {'x': ['motoric'], 'y': [...], 'z': [...]}
sess.get_xyz()                 # {'x': {'value','actuator','unit'}, ...} — µm from origin
sess.get_state()               # {'changeable': {laser,intensity,filter,zoom,shutter,etl_*}, 'observed': {...}}
sess.get_acquisition_options() # {format, planes, z_step, z_start, z_end, zoom, shutterconfig, backlash_correction}

# Frame origin: set the current stage position as (0,0,0), then move in µm from it.
sess.set_origin()              # persisted machine-locally; restored on reconnect
sess.set_xyz(50, 0, 10)        # move to x=50 µm, y=0, z=10 (relative to origin); returns once the stage is there

# Change light-path settings (the 'changeable' block); names must be the configured ones (see get_state()['observed']):
sess.set_state({"changeable": {"laser": "488 nm", "intensity": 20, "filter": "515/30", "zoom": "1x"}})

# Focus / rotation, mesoSPIM's own buttons, and stop are procedures:
sess.get_procedures()                       # move_focus, move_rotation, zero_stage, load_sample, unload_sample, center_sample, stop
sess.run_procedure({"name": "move_focus", "value": 5100.0})
sess.run_procedure({"name": "load_sample"})

# Acquire one frame at a labelled position; returns the written files and where each plane was taken.
r = sess.acquire("snap", "A1", options={"format": "ome-tiff"})
#   → {'images': [...data/snap_A1.tiff], 'planes': [{'z': 0, 'path': ..., 'x_um': ..., 'z_um': ...}],
#      'metadata': [...data/metadata/ZMART_state/snap_A1_ZMART_state.json, ...vendor/mesospim/snap_A1_meta.txt], ...}

sess.disconnect()
```

## 4b. Drive it — flat driver (mesoSPIM-specific)

```python
import mesospim as drv
c = drv.connect({"host": "127.0.0.1", "port": 42000, "token": "choose-a-password"})

drv.get_config(c)      # lasers / filters / zooms / camera / app / version
drv.get_limits(c)      # what the server lets a move reach
drv.get_positions(c)   # {x,y,z,f,theta}
drv.set_filter(c, "515/30"); drv.set_zoom(c, "1x"); drv.set_intensity(c, 20)

# Moves are FAIL-CLOSED on the flat API: configure the stage envelope first
# (the controller path in §4 does this for you at connect):
drv.set_stage_limits(x=(0, 25000), y=(0, 25000), z=(0, 25000), f=(0, 25000), theta=(-360, 360))
drv.move_absolute(c, {"x": 50.0, "z": 10.0})          # µm; returns once the stage is there

result = drv.acquire(c, "snap", options={"folder": r"D:\out", "filename": "snap.tiff", "planes": 1})
saved  = drv.save(result, r"D:\out\run", position_label="A1")   # relocate + print the state
drv.close(c)
```

## 5. Key behaviours & gotchas

- **Accepted is not finished.** A change is accepted first and finishes later. The
  driver polls the operation for you, so every call returns once mesoSPIM reports
  it done — a move once the stage reads back at the target.
- **One change at a time.** A second change while one runs is refused (`busy`);
  reads and `stop` still work. Work started in the GUI counts too.
- **Never re-send an accepted change.** If a wait runs out the driver raises and
  names the operation; check `get_progress` (`drv.get_progress(c)`) before deciding.
- **Names must be the configured ones.** Filter, zoom, laser and shutter names are
  validated by the server against the mesoSPIM configuration; read `get_config`
  (or `get_state()['observed']`) and pass those names back.
- **Limits, twice.** The driver refuses a move outside its envelope; the server
  refuses one outside mesoSPIM's own. Either refusal is `success=False` with the
  reason; nothing moves.
- **Password.** Plain TCP: it gates casual LAN access, it is **not** sniffer-proof.
  On untrusted networks, tunnel it (SSH/VPN). The default password only works on
  the local machine.
- **Backlash take-up** on `acquire` is best-effort: it is skipped (with a warning) if
  the take-up move would leave the stage envelope — e.g. exactly at the lower limit.

## 6. Test it

```powershell
# offline (no mesoSPIM, no hardware) — the mock server validates, gates and polls like the real one:
python zmart_drivers/mesospim/run_ci.py offline

# online (needs a live server from §3) — driver + adapter round-trip incl. acquire:
$env:MESOSPIM_TOKEN = "choose-a-password"; $env:MESOSPIM_ALLOW_ACQUIRE = "1"
python zmart_drivers/mesospim/run_ci.py online
```

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `the Remote Control password was refused` | Wrong/missing password. Use the one entered in mesoSPIM's Remote Control tab; unset means `smart_mesospim`, which only works on the local machine. |
| `cannot reach the mesoSPIM Remote Control server` / every integration test **skips** | Nothing is listening on `MESOSPIM_HOST:PORT` — start the TCP transport in the Remote Control tab (§3). |
| `move_*` returns `success=False`, "outside limits" | Flat API is fail-closed — call `set_stage_limits(...)` first (the controller does this automatically). |
| `success=False`, "server rejected: … outside the allowed range" | The server's own envelope (mesoSPIM's `stage_parameters`) is tighter than yours; `get_limits` shows it. |
| `success=False`, "busy: …" | Another change is still running (yours, or one started in the GUI). Wait for it, or `stop`. |
| `TimeoutError: … poll get_progress` | mesoSPIM never reported the change finished. Look at `get_progress` and at the mesoSPIM window (a warning dialog?) before sending it again. |
| `acquire(...): mesoSPIM reported the run finished but the stack is not complete on disk` | The writer wrote nowhere — check `folder`/`filename` and that the image writer plugin is enabled. |
| Headless launcher hangs "Installing torch …" | A newer mesoSPIM's ImageProcessor plugins pip-install torch at import; the bundled launcher already neutralises this — make sure you're running the committed `launch_demo_server.py`. |

---
Author: Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch ·
thomdehoog@gmail.com · MIT (client side).
