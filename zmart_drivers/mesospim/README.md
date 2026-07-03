# mesospim — mesoSPIM light-sheet microscope driver

`mesospim` drives a **mesoSPIM** light-sheet microscope from an external Python process. Its target,
[**mesoSPIM-control**](https://github.com/mesoSPIM/mesoSPIM-control) (the GPL PyQt5 acquisition app),
has **no external control API** — all control is in-process, inside its Qt event loop. So the boundary is
added *in mesoSPIM* by a small, generic upstream feature — **Remote Scripting** (Tools → Remote Scripting…;
the patch under [`pull_request/`](pull_request/)) — that runs a received Python script in the live Core and
returns its console. This driver is a thin **MIT client** that injects scripts and parses a structured result
back; all command vocabulary stays client-side. That process boundary keeps ZMART MIT while mesoSPIM-control
stays GPL (see [§10](#10-licensing--how-this-stays-mit)).

It is a vendor sibling to the Leica `navigator_expert` and ZEISS `zenapi` drivers and mirrors their
architecture — *connection + command vocabulary + state readers*, all tuning in profiles, every write
routed through a dispatch backbone with retry + readback confirmation. The public API is
**synchronous**, so operator notebooks keep the thin 1–3-line invocation style used across the ZMART
drivers.

- **Author:** Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com
- **License:** **MIT** (the whole driver). The only GPL-3.0 code is the generic **Remote Scripting** feature
  *in mesoSPIM* (the upstream patch under [`pull_request/`](pull_request/)) — see [§10](#10-licensing--how-this-stays-mit).
- **Status:** The driver rides mesoSPIM's **Remote Scripting** bridge — a generic "run this Python, return the
  console" socket ([`pull_request/`](pull_request/), validated against real mesoSPIM `-D` demo, v1.20.0). The
  driver injects small scripts and parses a structured result back; all command vocabulary is client-side
  ([`connection/scripts.py`](connection/scripts.py)). **115 offline tests** green — the mock server `exec`s the
  real injected scripts against a Core-shaped fake, so framing/harness/vocabulary are exercised for real.
  Remaining: re-run the live round-trip on this transport and **real-hardware** validation (see [TODO.md](TODO.md)).

## How it controls the microscope — in plain terms

The driver does **not** talk to the camera, stage, or lasers itself, and it does
**not** re-implement any microscope logic. It tells the **real mesoSPIM-control
program** what to do — the same program a scientist normally clicks in — and
mesoSPIM does the actual work. We only add the one thing mesoSPIM lacks: a way to
send it commands from outside.

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │  YOUR PYTHON  (your PC, or the microscope PC)                        │
  │                                                                     │
  │      drv.move_xy(client, 1000, 2000)                                │
  │              │                                                      │
  │              ▼                                                      │
  │  ZMART mesospim driver  (MIT)                                       │
  │      turns your call into a small Python SCRIPT to run:            │
  │      self.move_absolute({'x_abs':1000,'y_abs':2000},...) ; print() │
  └──────────────┬──────────────────────────────────────────────────────┘
                 │
                 │   localhost network socket   127.0.0.1 : 42000
                 │   send script text  ──►  get its console output back
                 │   (the ONLY link between the MIT driver and GPL mesoSPIM)
                 ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │  THE REAL mesoSPIM-control PROGRAM                                   │
  │                                                                     │
  │  Remote Scripting server   (Tools → Remote Scripting… ; upstream)  │
  │      runs the received script via the SAME Core.execute_script     │
  │      the Script Window uses, so it calls the same methods          │
  │      mesoSPIM's own buttons call:                                  │
  │      core.move_absolute(...) · core.start(...) · core.state[...]   │
  │              │                                                      │
  │              ▼                                                      │
  │  mesoSPIM_Core     ── the program's control brain ──               │
  │              │                                                      │
  │  ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
  │              ▼                                                      │
  │  camera · stage · lasers · galvo / ETL                             │
  │  real devices on the microscope PC                                 │
  │  (or SIMULATED, when mesoSPIM runs in -D demo mode)                │
  └─────────────────────────────────────────────────────────────────────┘
```

**Reading it top to bottom:**

1. **Your code / the ZMART driver (MIT).** You call something plain like
   `drv.move_xy(client, 1000, 2000)`. The driver turns it into a tiny Python
   **script** (built in [`connection/scripts.py`](connection/scripts.py)) that
   calls the Core and prints its result.
2. **A localhost network socket (`127.0.0.1:42000`).** That script is sent over an
   ordinary TCP socket and the script's console output comes back. This socket is
   the *only* connection between the MIT driver and the GPL mesoSPIM program —
   which is also what keeps the licensing clean (see [§10](#10-licensing--how-this-stays-mit)).
3. **The Remote Scripting server, running _inside_ mesoSPIM.** mesoSPIM has a
   built-in "Script Window" that runs a Python snippet inside the live program. A
   small, generic upstream feature (**Tools → Remote Scripting…**; the patch under
   [`pull_request/`](pull_request/)) puts a socket in front of it — it runs the
   received script via the *existing* `Core.execute_script` and returns the console.
4. **`mesoSPIM_Core` — the program's control brain.** The injected script calls
   **the exact same `Core` methods that mesoSPIM's own buttons call**
   (`self.move_absolute(...)`, `self.start(...)` to run an acquisition, …). So a
   move sent by the driver runs the *identical code path* as a scientist clicking
   "move" in the GUI. **That is why this is real control, not a look-alike.**
5. **The devices.** `Core` drives the real camera, stage and lasers. In **demo
   mode (`-D`)** these are mesoSPIM's own *simulated* devices, so the whole program
   runs with no microscope attached.

**The honest boundary.** Everything *except the bottom box* is the real
mesoSPIM-control program in every case. In `-D` demo mode the bottom box is
simulated (no hardware present); on the actual microscope PC the very same path
drives the real devices. That last step — real stage moves, real camera — is the
one remaining bench check (see [TODO.md](TODO.md)); it needs the physical
instrument, which no amount of demo-mode testing can stand in for.

## Contents

1. [About mesoSPIM-control & Remote Scripting](#1-about-mesospim-control--remote-scripting)
2. [Requirements & installation](#2-requirements--installation)
3. [Configuration](#3-configuration)
4. [Quick start](#4-quick-start)
5. [Core concepts](#5-core-concepts)
6. [API reference](#6-api-reference)
7. [Architecture](#7-architecture)
8. [Configuration & tuning (profiles)](#8-configuration--tuning-profiles)
9. [Testing](#9-testing)
10. [Licensing — how this stays MIT](#10-licensing--how-this-stays-mit)
11. [Invariants & gotchas](#11-invariants--gotchas)
12. [Extending the driver](#12-extending-the-driver)
13. [References](#13-references)

---

## 1. About mesoSPIM-control & Remote Scripting

mesoSPIM-control is a monolithic **Python 3.12 / PyQt5** GUI app. `mesoSPIM_Core` (a `QObject` "pacemaker")
runs on its own thread and drives everything through **signals/slots**; a process-wide
`mesoSPIM_StateSingleton` holds instrument state; device backends (cameras, PI/ASI stages, NI DAQ galvo/ETL
waveforms, lasers, filter wheels) are config-driven and **swappable for `Demo` backends**. Crucially, it
exposes **no socket, ZMQ, REST, or RPC** — nothing a separate OS process can connect to out of the box.

**The hook (no fork, minimal upstream).** mesoSPIM's **Script Window** (Core menu) `exec()`s a Python
snippet with the live `Core` bound as `self`. A tiny, **generic** upstream contribution
([`pull_request/`](pull_request/)) — **Tools → Remote Scripting…** — puts a socket in front of that: it runs
a received Python script through the *existing* `Core.execute_script` and returns the console output. Text
in, console text out; **no command vocabulary, no data format in mesoSPIM**. The GPL edge is that one small,
reusable feature.

**All the vocabulary lives client-side (MIT).** A "command" here is a Python **script** the driver injects
([`connection/scripts.py`](connection/scripts.py)) — `move_absolute`, a state read, an `Acquisition` run.
Each is wrapped in a harness that prints its result as a **per-call-nonce + base64(JSON)** block, so the
driver extracts a clean structured `{ok, data, error}` from the console even though other threads may print
into it (exactly as the Script Window console does). The framing is length-prefixed (see
[`pull_request/PROTOCOL.md`](pull_request/PROTOCOL.md)). Nothing ZMART-specific runs inside mesoSPIM.

> **Why this shape.** Putting only a transport in mesoSPIM (and keeping the vocabulary in the MIT client)
> makes the upstream patch trivial to review and accept, keeps the GPL/MIT boundary clean, and means new
> capability is a new injected script — not a mesoSPIM change. The alternative (a bespoke ZMART command
> server loaded into the Core) was retired in favour of this after the PR proved out on the bench.

**Why this is a good fit.** Because mesoSPIM ships a **`-D` demo mode** (all `Demo` backends, zero hardware),
the *entire* control loop — including a real acquisition through the real image writer — can be exercised
against the actual acquisition software with no microscope. That is unique among the ZMART drivers (see
[§9](#9-testing)). Offline, the mock server **`exec`s the very same injected scripts** against a Core-shaped
fake, so the framing, harness, and vocabulary are all exercised for real; only the live hardware Core is
absent.

## 2. Requirements & installation

The **client** (this package) is pure standard-library sockets + JSON and is **cross-platform** with no heavy
dependencies. Only the resident server + live `Core` need mesoSPIM-control, which is effectively
**Windows-only** (Python ≥ 3.12; `requirements-conda-mamba.txt` pins Windows-only packages). `-D` demo mode
needs **no camera / stage / DAQ hardware** — a bare Windows box or VM is enough.

**Install the driver (import the package):**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("zmart_drivers").resolve()))   # parent of the mesospim package

import mesospim as drv
```

Test/optional dependencies (the client itself needs none of these):

```bash
pip install -r zmart_drivers/mesospim/requirements-dev.txt   # pytest, numpy, tifffile; PyQt5 optional (validator)
```

**Start Remote Scripting on the mesoSPIM PC:**

1. Apply the Remote Scripting patch ([`pull_request/`](pull_request/)) to mesoSPIM-control (until it is
   merged upstream), then launch — real hardware, or **`-D` demo mode** for a hardware-free run:
   `python mesoSPIM_Control.py -D`.
2. **Tools → Remote Scripting… → Start** (host `127.0.0.1`, port `42000`; set a token to expose it on the
   network). You should see `[mesospim-remote-scripting] listening on 127.0.0.1:42000`.
3. From the driver: `client = drv.connect({"host": "127.0.0.1", "port": 42000})`.

**Network use (control from another PC).** In the dialog, set the host to `0.0.0.0` (or the mesoSPIM PC's LAN
IP) **and** a token (the dialog warns and can generate one) — then pass it:
`drv.connect({"host": "<mesoSPIM-PC-IP>", "port": 42000, "token": "<token>"})`. The token gates access
(fail-closed) and is compared in constant time. Note it is **plain TCP** — a casual gate for a trusted lab
LAN, not sniffer-proof; tunnel it (SSH/VPN) for untrusted networks. Because a script is arbitrary Python on
the acquisition PC, the server is off by default and started by an operator. See
[`pull_request/README.md`](pull_request/README.md) and [`pull_request/PROTOCOL.md`](pull_request/PROTOCOL.md).

## 3. Configuration

- **Connection** — `ConnectionProfile` (`config/profiles.py`, exported as `CONNECTION`): `host` (127.0.0.1),
  `port` (42000), `timeout_s` (10 s). `connect()` reads `host`/`port`/`timeout` from the connection dict the
  ZMART controller forwards, with explicit kwargs winning over the dict winning over the profile.
- **Stage limits (required before any move)** — limits fail **closed**: an axis with no configured limit is
  *rejected*, so a forgotten setup can never let an unbounded move reach a mounted sample. Configure once per
  session with `set_stage_limits(...)` or `apply_stage_limits_from_config(load_stage_config(...))`, in
  micrometers (degrees for `theta`). The check code is [`motion/limits.py`](motion/limits.py) and the bundled
  envelope is [`limits/defaults/stage_limits.json`](limits/defaults/stage_limits.json) (schema-versioned).
  **The `zmart_controller` path loads these automatically in `connect`.**
- **Machine-local config (ProgramData wins, bundled defaults fall back)** — the controller path resolves each
  config file machine copy first, then the bundled default under `limits/defaults/` ([`calibration/machine.py`](calibration/machine.py)):
  `<programdata_root>/mesospim/<microscope_id>/{stage_limits.json, function_limits.json, origin.json}` with
  `programdata_root` = `C:\ProgramData\smart_microscopy` (override: `SMART_MICROSCOPY_ROOT` env var, or
  `connection["machine_root"]`). So a machine-specific envelope never means editing the checkout. The
  **function-keyed limits** (`function_limits.json`, the shared `shared/limits` schema — same as the Leica
  driver) gate every mutating controller op, with the stage envelope overlaid onto their `stage.*`
  constraints and completeness enforced at load: every mutating op needs an entry (`null` =
  reviewed-and-unlimited), so a new op can't ship silently unlimited. Which file governed the session is
  reported under `get_state()["observed"]["limits"]`. The **frame origin** set by `set_origin` persists to
  `origin.json` and is restored at `connect`, so the zero point survives reconnects.
- **Hardware model / acquisition defaults** — `HARDWARE` (laser lines, filters, zoom→pixel-size table, camera
  size) and `ACQUISITION` (save format, defaults, `acquire_timeout_s`) in `config/profiles.py`. The live
  instrument's values are authoritative and read back via `get_config`; the profile is the offline default and
  validation reference.

## 4. Quick start

```python
import mesospim as drv

# 1. Connect to mesoSPIM's Remote Scripting server (handshake + ping-verified).
client = drv.connect({"host": "127.0.0.1", "port": 42000})

# 2. Stage safety limits (REQUIRED before movement) — micrometers / degrees.
#    limits fail CLOSED, so an unconfigured axis is rejected.
drv.apply_stage_limits_from_config(drv.load_stage_config())     # bundled envelope

# 3. Drive the microscope — synchronous, micrometers.
r = drv.move_xy(client, 1000, 2000)
assert r["success"], r["message"]                 # check `confirmed` too — see §5
drv.set_filter(client, "515/30")
drv.set_laser(client, "488 nm")
drv.set_intensity(client, 20)                      # percent

# 4. Read state.
print(drv.get_positions(client))                   # {'x':1000.0,'y':2000.0,'z':..,'f':..,'theta':..}
print(drv.get_config(client)["lasers"])            # [{'name':'488 nm','wavelength_nm':488}, ...]

# 5. Capture and persist (two steps). The low-level acquire needs a folder/filename
#    so the mesoSPIM image writer has somewhere to write.
acq   = drv.acquire(client, "snap", options={"folder": "D:/runs/demo", "filename": "A1.tiff", "planes": 1})
saved = drv.save(acq, "D:/runs/demo", position_label="A1")     # relocates the frames + a JSON sidecar
print(saved.image_paths)

drv.close(client)
```

Through the vendor-neutral controller instead (`import zmart_controller`):

```python
import zmart_controller
import mesospim  # importing the driver registers it (vendor=mesospim, api=remote-scripting)

# Add "token": "…" if the server requires one; host/port default to 127.0.0.1:42000.
sess = zmart_controller.set_instrument({"vendor": "mesospim", "microscope": "mesospim-01",
                                        "api": "remote-scripting", "host": "127.0.0.1", "port": 42000})
sess.set_origin()
sess.set_xyz(10, 20, 5)                             # µm from origin
sess.acquire("prescan", "A1", options={"format": "ome-tiff"})
sess.disconnect()
```

The controller surface is x/y/z-centric: focus and rotation are exposed as **procedures**
(`move_focus`, `move_rotation`), and laser/filter/zoom/intensity/shutter/ETL as the capturable **mutable
state** (`get_state`/`set_state`). The full driver API (`import mesospim`) covers the rest.

## 5. Core concepts

**The client.** `connect(...)` opens the socket, performs the `hello` handshake (recording the server
identity + protocol version), verifies the link with a `ping`, and returns a `MesospimClient`. It refuses a
server whose protocol version it does not know. Every command and reader takes the client as its first
argument. One request/reply at a time, guarded by a lock — mesoSPIM's Remote Scripting server is single-client by
design (it lives in the Qt event loop).

**Units.** Linear axes (x, y, z, focus) are **micrometers**; rotation (`theta`) is **degrees** — on both the
public API and the wire. The server handles any conversion to mesoSPIM's internal units.

**Command vs. read.** Commands *change* state through the dispatch backbone and return a result envelope;
readers *observe* state and return a value (or `None`).

**The result envelope.** Every command returns a stable dict:

| Key | Meaning |
|---|---|
| `success` | The command achieved its effect (fired without a permanent/transport error). |
| `confirmed` | A readback matched the target (`True`/`False`); `None` if no confirmation ran. |
| `message` | Human-readable summary. |
| `data` | Command-specific payload (server reply data, resulting position, …). |
| `timing` | `{pre_check_s, fire_s, confirm_s, total_s, attempts, confirm_attempts}`. |
| `logs` | Ordered `{ts, level, msg}` trace. |

**`success` vs. `confirmed` — read both.** For moves and settings the profiles use
`success_on_unconfirmed=True`: `success=True, confirmed=False` means "the command fired but the readback did
not verify it" — the mismatch is in `logs`. Don't treat `success` alone as "the stage is there." (In
practice the server blocks on `wait_until_done`, so the reply only returns *after* the move completes and the
confirming readback normally sees the arrived position.) `success=False` means it never fired (a validation
or limit failure, a NAK, or a transport error), and `confirmed` is then `None`.

**The freshness gate.** When a reader is asked for provenance (`diagnostics=True`) it returns a `Reading`
(`value` + `source` + `observed_at`). The confirm layer rejects any readback observed *before* the command
fired, so a stale pre-command read can never falsely confirm. Ordering uses `time.perf_counter()` (monotonic,
sub-microsecond) — wall-clock and `time.monotonic()` are both ~16 ms coarse on Windows and would let a stale
read share the fire's timestamp.

**Acquisition is two steps.** `acquire(...)` runs a capture and returns an `AcquisitionResult` referencing the
frame files the mesoSPIM image writer wrote (it **raises** if the server reports no frames). `save(...)` is a
deliberate second step that relocates those frames into a canonical layout with a metadata sidecar.

**Errors.** A NAK (`ok=false`) raises `MesospimError` from `request()` (use `try_request()` when a NAK is an
expected, inspectable outcome). Transport failures (dropped link, timeout) invalidate the connection and are
classified transient by the dispatch backbone (retried up to the profile ceiling); there is no auto-reconnect.

**Logging.** `logging.getLogger("mesospim").setLevel(logging.DEBUG)` — the same trace also travels in each
result's `logs`.

## 6. API reference

All functions are synchronous; `client` is a `MesospimClient`. Commands return the result envelope of §5;
readers return a value or `None`.

### Connection
```python
connect(connection=None, *, host=None, port=None, timeout=None, token=None) -> MesospimClient   # handshake + ping-verified; token sent in hello if the server requires one
close(client) -> None                                                               # says "bye", idempotent
ping(client) -> bool
```

### Movement (result envelope; µm / deg)
| Function | Signature | Notes |
|---|---|---|
| `move_absolute` | `(client, targets: dict, *, tolerance=None)` | `{axis: value}` over `x,y,z,f,theta`; limit-checked before firing |
| `move_relative` | `(client, deltas: dict, *, tolerance=None)` | expected absolute (current + delta) is limit-checked & confirmed |
| `move_xy` | `(client, x, y, *, tolerance=None)` | convenience over `move_absolute` |
| `move_z` / `move_focus` | `(client, value, *, tolerance=None)` | sample Z / detection focus |
| `move_rotation` | `(client, theta, *, tolerance=None)` | degrees |
| `stop` | `(client)` | halt all motion (no confirmation) |
| `zero_axes` | `(client, axes=None)` | define current position as instrument zero (`None` = all axes) |

### Instrument state (result envelope)
| Function | Signature | Notes |
|---|---|---|
| `set_state` | `(client, settings: dict)` | batch of mesoSPIM state keys; applied via `sig_state_request_and_wait_until_done` |
| `set_filter` / `set_zoom` / `set_laser` | `(client, name)` | select by name (`"515/30"`, `"1x"`, `"488 nm"`) |
| `set_intensity` | `(client, intensity)` | laser intensity, 0–100 % (range-checked) |
| `set_shutter` | `(client, shutterconfig)` | `"Left"` / `"Right"` / `"Both"` |
| `set_etl` | `(client, side, *, amplitude=None, offset=None)` | `side` = `"left"`/`"right"`; either/both params |

### State readers
All take `(client, ...)`; pass `diagnostics=True` for a source-tagged `Reading`. They return a value (or `None`)
and never raise on a bad read.

> **Run-state is not observable over this transport.** Every read runs inside `Core.execute_script`, which sets
> `state['state']='running_script'` for the read's duration — so `get_state`/`get_progress` report `state` as `None`
> (unknown). Position, settings and progress counts are read truthfully; judge acquisition completion from the frame
> files on disk (see `acquisition.capture`), not from `state`.

| Function | Returns |
|---|---|
| `ping` | `bool` |
| `get_state` | full state dict — `position` (`{x,y,z,f,theta}`), settings (`laser`,`intensity`,`filter`,`zoom`,`shutterconfig`,`etl_*`), and `state` (always `None`; see above) |
| `get_positions` | `{x,y,z,f,theta}` (µm / deg) |
| `get_position` | single axis value |
| `get_xyz` | `{x,y,z}` |
| `get_config` / `get_hardware_info` | `lasers` (`[{name,wavelength_nm}]`), `filters`, `zooms` (`[{name,pixel_size_um}]`), `axes`, `shutter_configs`, `camera` (`{pixels_x,pixels_y}`), `app`, `version` |
| `get_lasers` / `get_filters` / `get_zooms` | the corresponding list from `get_config` |
| `get_progress` | `current_plane`, `total_planes`, `current_acquisition`, `total_acquisitions` (+ `state`, always `None`) |

### Acquisition & save
```python
acquire(client, acquisition_type="snap", *, options=None, state=None) -> AcquisitionResult   # RAISES if no frames
snap(client, *, options=None) -> AcquisitionResult                                            # single frame (planes=1)
run_acquisition_list(client, acquisitions: list[dict]) -> dict                                # multi-tile/-channel
build_acquisition(state: dict, options=None) -> dict                                          # compose an Acquisition dict
save(acq, output_root, *, position_label, format="ome-tiff") -> SavedAcquisition              # relocate frames + JSON sidecar
canonical_stem(acquisition_type, position_label) -> str
```
`options` may set `folder`/`filename` (where the image writer writes — the controller path fills these in) and
acquisition fields (`planes`, `z_step`, `z_start`, `z_end`, `laser`, `intensity`, `filter`, `zoom`,
`shutterconfig`, …). `acquire` uses `ACQUISITION.acquire_timeout_s` as its socket deadline (a capture reply
only arrives once the run finishes, far beyond the default per-request timeout). Result/product types:
`AcquisitionResult`, `AcquisitionMetadata`, `ChannelMetadata`, `SavedAcquisition` (`acquisition/product.py`).

> `save()` takes **no client** — it just relocates the files the writer already produced, into
> `<output_root>/data/` under a stable, collision-safe stem, with a JSON metadata sidecar. It does not
> re-encode pixels (the OME rewrite is a documented seam; see [§12](#12-extending-the-driver)).

### Config & limits
```python
set_stage_limits(**axis_limits) -> None            # e.g. x=(0, 20000), theta=(-360, 360); µm / deg
get_stage_limits() -> dict
apply_stage_limits_from_config(stage_cfg) -> None   # from load_stage_config(...)
load_stage_config(path=None) -> dict                # validates schema; defaults to the bundled envelope
check_move(targets) -> None                         # raises LimitError (fail-closed) — used by the command wrappers
```
Profiles `ACQUISITION`, `CONNECTION`, `HARDWARE` and the exception `LimitError` are also exported.

### Controller & protocol
```python
register(connection=None) -> None                   # register the ops table with zmart_controller (idempotent)
# protocol (advanced callers / server authors):
Request, Reply, encode_request, parse_request, parse_reply, PROTOCOL_VERSION
```

## 7. Architecture

```
zmart_drivers/mesospim/
├── protocol.py     JSON-lines encode/parse — pure, socket-free (MIT); the wire contract
├── connection/     client.py  blocking, line-oriented TCP client (lock-guarded, single in-flight)
│                   session.py connect() / close()
├── commands/       dispatch.py  confirm_and_fire backbone (fire + transient retry → confirm + optional re-fire)
│                   commands.py  set_*/set_state wrappers (instrument-state settings)
├── motion/         movement.py  move_*/stop/zero_axes wrappers (three-phase: validate+limits → backbone → envelope)
│                   limits.py    fail-closed 5-axis µm/deg envelope check
├── limits/         defaults/    bundled stage_limits.json + function_limits.json (ship with the driver)
├── calibration/    machine.py   ProgramData resolution of the stage envelope, function limits, persisted origin
├── readers/        readers.py   get_* reads + the Reading freshness gate
├── config/         profiles.py  CONNECTION/HARDWARE/ACQUISITION + CommandProfile instances (MOVE/MOVE_ROTATION/SET_STATE)
├── acquisition/    product.py   typed results     capture.py  build/acquire/snap/run_acquisition_list
│                   save.py      relocate the writer's frames into <output_root>/data/ + JSON sidecar
│                   connection/scripts.py  the injected-script templates (the mesoSPIM vocabulary, client-side)
├── mesospim_zmart_adapter.py  ZMART controller adapter — ops table (connect, set_xyz, acquire, get/set_state, …); registers at import
├── pull_request/   the upstream mesoSPIM Remote Scripting patch (GPL) + PROTOCOL.md + demo_client.py
└── tests/          unit/  offline vs a mock server     integration/  vs mesoSPIM -D demo     helpers/mock_mesospim_server.py
```

**Dispatch backbone** (`commands/dispatch.py` → `confirm_and_fire`) — two layers, deliberately *dumb* (it owns
order, retry ceilings, and timing; it knows nothing about axes, lasers, or acquisitions):

```
confirm_and_fire
 ├─ fire block   send the request; retry only on transient transport errors (≤ max_retries). A server NAK is
 │               a permanent rejection, not retried.
 └─ confirm wrap run confirm_fn (readback + freshness gate); optionally re-fire and re-confirm (≤ max_confirm_attempts).
```

Command wrappers supply small zero-arg/one-arg callables (targets pre-bound with `functools.partial`). Because
the *server* blocks on `wait_until_done`, the ACK returns only after the move completes, so a single confirm
read normally sees the arrived state.

**GPL/MIT split.** The whole driver is MIT and imports nothing from mesoSPIM. The only GPL code is the
generic **Remote Scripting** feature *in mesoSPIM* (the upstream patch under [`pull_request/`](pull_request/));
the driver reaches it over a socket. Nothing ZMART-specific runs inside the mesoSPIM process — the injected
scripts are just text the MIT client sends (see [§10](#10-licensing--how-this-stays-mit)).

**Dependency direction:** `utils` (stdlib) → `protocol` → `connection.scripts` → `connection.client` →
`commands.dispatch` → `config.profiles`/`motion.limits` → `motion.movement`/`commands.commands`; `calibration`
(machine config), `readers`, `acquisition`, and `controller` sit above. No circular imports.

## 8. Configuration & tuning (profiles)

Per-command tuning lives in `config/profiles.py` as frozen `CommandProfile` instances; wrappers accept explicit
overrides (`tolerance=`) only for tests/unusual runs. Tuning a command = editing its profile.

```python
@dataclass(frozen=True)
class CommandProfile:
    max_retries=2 ; max_confirm_attempts=3 ; refire_on_unconfirmed=False
    confirm_tolerance=None ; success_on_unconfirmed=False
    # __post_init__ forbids the incoherent max_confirm_attempts==1 + refire_on_unconfirmed=True
```

| Profile | Posture |
|---|---|
| `MOVE` | confirm within `1.0 µm`; unconfirmed ≠ failure (fire is reliable, reader may lag). |
| `MOVE_ROTATION` | as `MOVE` but `0.1°` tolerance (chosen for `theta`-only moves). |
| `SET_STATE` | re-fire between confirm windows; unconfirmed ≠ failure. |

Other tuning surfaces: `CONNECTION` (host/port/timeout), `ACQUISITION.acquire_timeout_s` (capture socket
deadline, 600 s), and `HARDWARE` (the offline device model / validation reference).

## 9. Testing

One self-contained gate ([`run_ci.py`](run_ci.py) — env header + lint + tests + reports), three modes:

```bash
pip install -r zmart_drivers/mesospim/requirements-dev.txt        # first run only (pytest, numpy, tifffile)

python zmart_drivers/mesospim/run_ci.py            # OFFLINE (default, portable): mock-server suite + coverage
python zmart_drivers/mesospim/run_ci.py online     # ONLINE:  live round-trip vs a running mesoSPIM -D demo
python zmart_drivers/mesospim/run_ci.py both       # BOTH:    the offline gate followed by the live round-trip
```

The two layers it runs, portable to most-faithful:

1. **Offline suite (115 tests)** — the MIT client vs a **mock Remote Scripting server** over a real socket;
   no mesoSPIM, no hardware. The mock is a *faithful* double: it `exec`s the very injected scripts the driver
   sends against a Core-shaped fake and returns the captured console, so the framing, harness, and command
   vocabulary are all exercised for real. `python -m pytest zmart_drivers/mesospim/tests` runs it directly
   (`-m "not integration"` is the default).
2. **Live round-trip** — the `-m integration` suite against a **running mesoSPIM `-D` demo** (real software,
   Demo backends, no hardware) on `MESOSPIM_HOST`/`MESOSPIM_PORT` (default `127.0.0.1:42000`). It skips
   cleanly if nothing is listening; capture is opt-in via `MESOSPIM_ALLOW_ACQUIRE=1` so it never fires
   lasers by accident. `run_ci.py` does not launch mesoSPIM — start the `-D` demo with **Tools → Remote
   Scripting** first (see [§2](#2-requirements--installation)), the same way the Leica/ZEISS `online` runs
   need their app live.

`online`/`both` therefore exercise the **real mesoSPIM-control software** — only the *hardware* is simulated
by the Demo backends. Reports (env.json, junit.xml, coverage, ci_summary.json) land in `tests/_report/`.

**Bench-validated.** The live round-trip has been run against a **`mesoSPIM_Core` (v1.20.0, all Demo
backends)** — all five tests pass, including `acquire`: it moves the demo stage, captures a frame, and the
driver resolves/relocates the Tiff stack the image writer wrote (plus the writer's `MAX_*` MIP and
`*_meta.txt` companions, which the driver correctly does *not* return as frame data). See [TODO.md](TODO.md)
for the method and the remaining bench items (non-Tiff writers; real-hardware moves).

Follow the project TDD practice: add a failing offline test first, and assert real values, not just shapes.

## 10. Licensing — how this stays MIT

- mesoSPIM-control is **GPL-3.0**; importing its modules into ZMART would make the combined work GPL.
- The **process boundary avoids that.** ZMART links only to the **MIT** external client, which *communicates
  with* a separate GPL program over a socket — mere aggregation, not a derivative work.
- The **GPL edge lives in mesoSPIM, not in ZMART:** the generic Remote Scripting feature (the patch under
  [`pull_request/`](pull_request/)). It uses the GPL `Core` API and imports **nothing** from ZMART; its home
  is an upstream contribution to the mesoSPIM project, so it is a feature mesoSPIM *ships and runs* rather
  than a patch anyone maintains. The ZMART client injects only *text* (scripts) across the socket.
- GPL does **not** restrict *use* (including commercial) — only distribution of derivatives. Driving mesoSPIM
  at arm's length from a commercial ZMART product is fine; folding modified mesoSPIM source into a closed
  product is not. *(Not legal advice — confirm with UZH tech-transfer.)*

## 11. Invariants & gotchas

These **silently misbehave** instead of failing loudly — respect them or results are wrong without an error:

1. **Configure stage limits before any movement.** Limits fail **closed**: an unconfigured axis is rejected,
   so every `move_*` returns `success=False` until `set_stage_limits`/`apply_stage_limits_from_config` runs.
   (The `zmart_controller` path does this automatically in `connect`.)
2. **For moves and settings, check `confirmed`, not just `success`.** The profiles accept unconfirmed as
   success (mismatch in `logs`); `success` alone is "fired," not "arrived."
3. **`acquire()` raises on no frames and needs a `folder`/`filename`** so the image writer has somewhere to
   write. Persisting is a separate `save()` call (which takes no client).
4. **Acquisitions are slow.** A capture is start + poll: `acquire` fires `acquire_start` (which returns
   immediately), then polls progress and file existence until the run is idle and the stack exists — up
   to `ACQUISITION.acquire_timeout_s` (600 s; a real stack can take minutes). On timeout it raises and
   still restores the operator's acquisition list; it never reports success without the file on disk.
5. **Single-client server.** The Remote Scripting server serves one client at a time; a new connection
   preempts the old one (it lives in mesoSPIM's Qt event loop). Don't open two concurrent clients.
6. **Process-global stage limits.** Limits live in a module-level dict, so this driver assumes one instrument
   per process; a second session in the same process would share (and overwrite) them.
7. **The injected scripts must match your mesoSPIM version.** The `Core`-binding names (state keys, move API,
   `cfg` attributes, `start(row=…)`, the image-writer path) are verified against v1.20.0 and all live in one
   place — `connection/scripts.py`; re-verify there if your installed version differs (run the live round-trip
   against `-D` demo mode first). `acquire` imports mesoSPIM's `Acquisition` from `mesoSPIM.src.utils.acquisitions`
   (with a bare-`utils` fallback).

## 12. Extending the driver

- **New command** — add an injected-script template in `connection/scripts.py` (a body that reads `_a` and
  sets `_result`), a wrapper in `motion/movement.py` (moves) or `commands/commands.py` (state) — three phases:
  validate + limit-check → `confirm_and_fire(...)` with the profile + a `fire_fn` and target-bound `confirm_fn`
  → return the envelope — a `CommandProfile` in `config/profiles.py` if the defaults don't fit, and the export
  in `__init__.py`. The
  mock covers it automatically (it `exec`s the template); extend `FakeCore` only if the template calls a new
  Core method.
- **Real procedures** — `autofocus` / `find_sample` currently NAK (the `procedure` template raises); implement
  them as their own injected scripts (e.g. an ETL/remote-focus sweep) or drop them from
  `config.profiles.ACQUISITION.procedures`.
- **Acquisition features** — multi-channel captures and XY-tiling by building an `AcquisitionList`; an OME-TIFF
  re-encode in `acquisition/save.py` (today it copies the writer's frames verbatim + a JSON sidecar — the
  pixel-pull → OME path is a documented seam).

## 13. References

- ZMART controller (the vendor-agnostic surface this driver registers with): [`zmart_controller/`](../../zmart_controller/README.md)
- Sibling drivers: [`zmart_drivers/zeiss/zenapi/`](../zeiss/zenapi/README.md) (gRPC), [`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`](../leica/stellaris5_y42h93/navigator_expert/README.md) (CAM API), [`zmart_drivers/nikon/`](../nikon/README.md) (socket macro)
- Remote Scripting bridge (the upstream mesoSPIM patch) & wire framing: [`pull_request/README.md`](pull_request/README.md) · [`pull_request/PROTOCOL.md`](pull_request/PROTOCOL.md)
- Remaining work & bench-validation notes: [`TODO.md`](TODO.md)
- mesoSPIM-control: <https://github.com/mesoSPIM/mesoSPIM-control> · mesoSPIM project: <https://mesospim.org>

<!-- Maintainer: Thom de Hoog (ZMB / University of Zurich), thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com.
     ZMART driver = MIT; mesoSPIM-control = GPL-3.0, kept behind a process boundary. Grounded in a source
     read of mesoSPIM-control v1.20.0 and a live -D demo-mode validation. -->
