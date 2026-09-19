# mesospim — mesoSPIM light-sheet microscope driver

> **New here? Start with the [workflow manual](WORKFLOW.md)** — start Remote Control in
> mesoSPIM and drive the scope from Python end to end. This README is the reference.

`mesospim` drives a **mesoSPIM** light-sheet microscope from an external Python process. Its target,
[**mesoSPIM-control**](https://github.com/mesoSPIM/mesoSPIM-control) (the GPL PyQt5 acquisition app),
has gained a **Remote Control** server in
[pull request #106](https://github.com/mesoSPIM/mesoSPIM-control/pull/106): a fixed list of named,
validated calls (`get_position`, `move_absolute`, `acquire_start`, …) served over a password-gated TCP
socket. This driver is a thin **MIT client** of that server. Nothing ZMART-specific runs inside mesoSPIM,
and that process boundary keeps ZMART MIT while mesoSPIM-control stays GPL (see
[§10](#10-licensing--how-this-stays-mit)).

It is a vendor sibling to the Leica `navigator_expert`, ZEISS `zenapi` and Nikon drivers and mirrors their
architecture — *connection + command vocabulary + state readers*, all tuning in profiles, every write
routed through a dispatch backbone with retry + readback confirmation. The public API is
**synchronous**, so operator notebooks keep the thin 1–3-line invocation style used across the ZMART
drivers.

- **Author:** Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com
- **License:** **MIT** (the whole driver). The Remote Control server itself is part of mesoSPIM-control
  (GPL-3.0) — see [§10](#10-licensing--how-this-stays-mit).
- **Status:** Written against the Remote Control server of mesoSPIM-control pull request #106
  (branch `remote-control-py312`, September 2026). The offline suite is green: a faithful mock of that
  server validates calls, admits one change at a time and hands every change back as an operation to
  poll, so framing, validation, polling and the acquisition flow are exercised for real. The live
  `-D` demo round trip and **real-hardware** validation are pending the pull request's merge (see
  [TODO.md](TODO.md)).

## How it controls the microscope — in plain terms

The driver does **not** talk to the camera, stage, or lasers itself, and it does
**not** re-implement any microscope logic. It asks the **real mesoSPIM-control
program** to do things — the same program a scientist normally clicks in — and
mesoSPIM does the actual work, with the same checks it applies to its own buttons.

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │  YOUR PYTHON  (your PC, or the microscope PC)                        │
  │                                                                     │
  │      drv.move_xy(client, 1000, 2000)                                │
  │              │                                                      │
  │              ▼                                                      │
  │  ZMART mesospim driver  (MIT)                                       │
  │      turns your call into one named request:                        │
  │      {"move_absolute": {"targets": {"x": 1000, "y": 2000}}}         │
  └──────────────┬──────────────────────────────────────────────────────┘
                 │
                 │   localhost network socket   127.0.0.1 : 42000
                 │   password first, then one JSON call per frame,
                 │   one reply per call  (the ONLY link, MIT ⇄ GPL)
                 ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │  THE REAL mesoSPIM-control PROGRAM                                   │
  │                                                                     │
  │  Remote Control server  (the Remote Control tab; PR #106)          │
  │      knows exactly 56 named calls and runs nothing else;           │
  │      checks every argument, option and stage limit first;          │
  │      admits ONE change at a time and reports it as an operation    │
  │      you poll until it is completed or failed                      │
  │              │                                                      │
  │              ▼                                                      │
  │  mesoSPIM_Core     ── the program's control brain ──               │
  │      core.move_absolute(...) · core.start(...) · core.state[...]   │
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
   `drv.move_xy(client, 1000, 2000)`. The driver turns it into one named call and
   sends it over the socket.
2. **A localhost network socket (`127.0.0.1:42000`).** The first thing sent is the
   Remote Control password; after that, one JSON call per frame and one reply per
   call. This socket is the *only* connection between the MIT driver and the GPL
   mesoSPIM program, which is also what keeps the licensing clean.
3. **The Remote Control server, running _inside_ mesoSPIM.** It understands a fixed
   list of calls and never runs code a client sends. Before anything moves it checks
   the call's name, the shape and type of every argument, that a filter or laser name
   is one the microscope is configured with, and that a target lies inside the stage
   limits of the loaded configuration. It admits **one change at a time**.
4. **`mesoSPIM_Core` — the program's control brain.** A call ends up in **the exact
   same `Core` methods that mesoSPIM's own buttons call**. A move sent by the driver
   runs the *identical code path* as a scientist clicking "move" in the GUI. **That is
   why this is real control, not a look-alike.**
5. **The devices.** `Core` drives the real camera, stage and lasers. In **demo mode
   (`-D`)** these are mesoSPIM's own *simulated* devices, so the whole program runs
   with no microscope attached.

**Accepted is not finished.** A change (a move, a setting, an acquisition) is
*accepted* first — validated, admitted, scheduled — and finishes later. The server
answers with an **operation** record (an id and a status), and the driver polls
`get_progress` until that operation is `completed` or `failed`, checking each time
that the id is still the one it was given. A stage move is completed only once
the stage reads back at the target. The driver never re-sends an accepted change
because polling was slow: if the wait runs out it raises and names the operation.

**The honest boundary.** Everything *except the bottom box* is the real
mesoSPIM-control program in every case. In `-D` demo mode the bottom box is
simulated; on the actual microscope PC the very same path drives the real devices.
That last step — real stage moves, real camera — is the remaining bench check (see
[TODO.md](TODO.md)); it needs the physical instrument.

## Contents

1. [About mesoSPIM-control & Remote Control](#1-about-mesospim-control--remote-control)
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

## 1. About mesoSPIM-control & Remote Control

mesoSPIM-control is a monolithic **Python 3.12 / PyQt5** GUI app. `mesoSPIM_Core` (a `QObject`
"pacemaker") runs on its own thread and drives everything through **signals/slots**; a process-wide
`mesoSPIM_StateSingleton` holds instrument state; device backends (cameras, PI/ASI stages, NI DAQ
galvo/ETL waveforms, lasers, filter wheels) are config-driven and **swappable for `Demo` backends**.

**Remote Control** (mesoSPIM-control pull request #106) adds the one thing it lacked: a way to drive it
from outside. It is a tab in the GUI (**Remote Control**) from which the operator starts one of two
transports — **TCP** (what this driver speaks) or **MCP** (an HTTP endpoint for AI-agent clients) — and
sets the password. Both expose the same **56 named calls**: reads (`get_state`, `get_position`,
`get_config`, `get_limits`, `get_progress`, …), moves (`move_absolute`, `move_relative`, `zero`,
`load_sample`, …), settings (`set_state`, `set_filter`, …), acquisitions (`acquire_start`,
`acquire_finish`, `set_acquisition_list`, `snap`, …) and emergency stops. The server validates every
argument and every stage target before it touches the Core, admits one change at a time, and reports
each change as an operation the client polls. It never executes text a client sends.

**The wire.** Length-framed UTF-8 (`<byte count>\n<payload>`), the password as the first frame (`OK` or
`AUTH-FAILED`), then one JSON object per frame — `{"<call>": {…arguments…}}`. A successful reply starts
with `__MESOSPIM_OK__` and a JSON object; a refused call is `error: [code] message` with the code
`validation`, `busy`, `unknown_command` or `execution`. The whole contract lives in
[`protocol.py`](protocol.py), and in the pull request's own manual
(`docs/source/remote_control/` in mesoSPIM-control).

**Why this is a good fit.** Because mesoSPIM ships a **`-D` demo mode** (all `Demo` backends, zero
hardware), the *entire* control loop — including a real acquisition through the real image writer — can
be exercised against the actual acquisition software with no microscope. Offline, the mock server in
`tests/helpers/` reproduces the server's validation, the one-change gate and the operation polling, so
the driver is exercised for real; only the live Core is absent.

> **Where the driver came from.** Two earlier transports preceded Remote Control: a bespoke command
> server loaded into the Core, and a generic "run this Python script" bridge. Both were validated on the
> `-D` demo and both were retired once mesoSPIM-control gained a proper, validated API; their history is
> in this folder's git log. Only the transport changed: the driver's command vocabulary, dispatch
> backbone, limits, readers and controller adapter kept their shape.

## 2. Requirements & installation

The **client** (this package) is pure standard-library sockets + JSON and is **cross-platform** with no
heavy dependencies. Only mesoSPIM-control itself needs Windows (Python ≥ 3.12;
`requirements-conda-mamba.txt` pins Windows-only packages). `-D` demo mode needs **no camera / stage /
DAQ hardware** — a bare Windows box or VM is enough.

**Install the driver (import the package):**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("zmart_drivers").resolve()))   # parent of the mesospim package

import mesospim as drv
```

Test/optional dependencies (the client itself needs none of these):

```bash
pip install -r requirements-dev.txt   # repo-root dev list (covers pytest, numpy, tifffile)
```

**Start Remote Control on the mesoSPIM PC:**

1. Run a mesoSPIM-control that carries Remote Control (pull request #106; until it is merged, its
   branch `remote-control-py312`) — real hardware, or **`-D` demo mode** for a hardware-free run:
   `python mesoSPIM_Control.py -D`.
2. Open the **Remote Control** tab, choose **TCP** (host `127.0.0.1`, port `42000`), set a password,
   and click **Start**. The tab shows the address once the server is listening. The default password
   `smart_mesospim` is public (it is in the mesoSPIM repository) and is only accepted on the local
   machine; to control mesoSPIM from another PC, set your own password and bind the PC's LAN address.
3. From the driver: `client = drv.connect({"host": "127.0.0.1", "port": 42000, "token": "<password>"})`.
   Omit `token` to use the default password on the local machine.

**Network use (control from another PC).** Plain TCP — the password gates casual access on a trusted
lab LAN; it is not sniffer-proof. Tunnel it (SSH/VPN) for untrusted networks. The server is off by
default and started by an operator, and it refuses to bind a non-local address with the default password.

## 3. Configuration

- **Connection** — `ConnectionProfile` (`config/profiles.py`, exported as `CONNECTION`): `host`
  (127.0.0.1), `port` (42000), `timeout_s` (10 s), `token` (the password; mesoSPIM's loopback default),
  and how the driver waits for an accepted change: `operation_poll_s` (50 ms between `get_progress`
  polls) and `operation_timeout_s` (120 s for an ordinary change; acquisitions have their own budget).
  `connect()` reads `host`/`port`/`timeout`/`token` from the connection dict the ZMART controller
  forwards, with explicit kwargs winning over the dict winning over the profile.
- **Stage limits (required before any move)** — limits fail **closed**: an axis with no configured limit
  is *rejected*, so a forgotten setup can never let an unbounded move reach a mounted sample. Configure
  once per session with `set_stage_limits(...)` or `apply_stage_limits_from_config(load_stage_config(...))`,
  in micrometers (degrees for `theta`). The check code is [`limits/checks.py`](limits/checks.py) and the
  bundled envelope is [`limits/defaults/stage_limits.json`](limits/defaults/stage_limits.json).
  **The `zmart_controller` path loads these automatically in `connect`.** The Remote Control server
  checks its own configured envelope (`stage_parameters` in the mesoSPIM config) on top, so every move
  is checked on both sides of the socket; `get_limits` reports the server's.
- **Machine-local config (ProgramData wins, bundled defaults fall back)** — the controller path resolves
  each config file machine copy first, then the bundled default under `limits/defaults/`
  ([`calibration/machine.py`](calibration/machine.py)):
  `<programdata_root>/mesospim/<microscope_id>/{stage_limits.json, function_limits.json, origin.json}`
  with `programdata_root` = `C:\ProgramData\zmart-microscopy` (override: `ZMART_MICROSCOPY_ROOT` env var,
  or `connection["machine_root"]`). So a machine-specific envelope never means editing the checkout.
  The **function-keyed limits** (`function_limits.json`) gate every mutating controller op, with the
  stage envelope overlaid onto their `stage.*` constraints and completeness enforced at load: every
  mutating op needs an entry (`null` = reviewed-and-unlimited), so a new op can't ship silently
  unlimited. Which file governed the session is reported under `get_state()["observed"]["limits"]`.
  The **frame origin** set by `set_origin` persists to `origin.json` and is restored at `connect`, so the
  zero point survives reconnects.
- **Hardware model / acquisition defaults** — `HARDWARE` (laser lines, filters, zoom→pixel-size table,
  camera size) and `ACQUISITION` (save format, defaults, `acquire_timeout_s`) in `config/profiles.py`.
  The live instrument's values are authoritative and read back via `get_config`; the profile is the
  offline default and validation reference.

## 4. Quick start

```python
import mesospim as drv

# 1. Connect to mesoSPIM's Remote Control server (password + greeting, ping-verified).
client = drv.connect({"host": "127.0.0.1", "port": 42000, "token": "<password>"})

# 2. Stage safety limits (REQUIRED before movement) — micrometers / degrees.
#    limits fail CLOSED, so an unconfigured axis is rejected.
drv.apply_stage_limits_from_config(drv.load_stage_config())     # bundled envelope

# 3. Drive the microscope — synchronous, micrometers. Each call returns once
#    mesoSPIM reports the change finished (a move: once the stage is there).
r = drv.move_xy(client, 1000, 2000)
assert r["success"], r["message"]                 # check `confirmed` too — see §5
drv.set_filter(client, "515/30")
drv.set_laser(client, "488 nm")
drv.set_intensity(client, 20)                      # percent

# 4. Read state.
print(drv.get_positions(client))                   # {'x':1000.0,'y':2000.0,'z':..,'f':..,'theta':..}
print(drv.get_config(client)["lasers"])            # [{'name':'488 nm','wavelength_nm':488}, ...]
print(drv.get_limits(client)["enforced"]["axes"])  # what the server lets a move reach

# 5. Capture and persist (two steps). The low-level acquire needs a folder/filename
#    so the mesoSPIM image writer has somewhere to write.
acq   = drv.acquire(client, "snap", options={"folder": "D:/runs/demo", "filename": "A1.tiff", "planes": 1})
saved = drv.save(acq, "D:/runs/demo", position_label="A1")     # relocates the stack + prints its state
print(saved.image_paths, saved.state_path)

drv.close(client)
```

Through the vendor-neutral controller instead (`import zmart_controller`):

```python
import zmart_controller
import mesospim  # importing the driver registers it (vendor=mesospim, api=remote-control)

sess = zmart_controller.set_instrument({"vendor": "mesospim", "microscope": "mesospim-01",
                                        "api": "remote-control", "host": "127.0.0.1", "port": 42000,
                                        "token": "<password>"})   # token None = the loopback default
sess.set_origin()
sess.set_xyz(10, 20, 5)                             # µm from origin
sess.acquire("prescan", "A1", options={"format": "ome-tiff"})
sess.disconnect()
```

The controller surface is x/y/z-centric: focus and rotation are exposed as **procedures**
(`move_focus`, `move_rotation`), together with mesoSPIM's own buttons (`zero_stage`, `load_sample`,
`unload_sample`, `center_sample`, `stop`); laser/filter/zoom/intensity/shutter/ETL are the capturable
**changeable state** (`get_state`/`set_state`). The full driver API (`import mesospim`) covers the rest.

## 5. Core concepts

**The client.** `connect(...)` opens the socket, sends the password, reads the `hello` greeting
(recording the server identity + protocol version), verifies the link with a `ping`, and returns a
`MesospimClient`. It refuses a server whose protocol version it does not know. Every command and reader
takes the client as its first argument. One request/reply at a time, guarded by a lock.

**Units.** Linear axes (x, y, z, focus) are **micrometers**; rotation (`theta`) is **degrees** — on
both the public API and the wire. Targets are in mesoSPIM's user-visible frame (the one its position
display shows); the server maps them onto its physical limits itself.

**Command vs. read.** Commands *change* state through the dispatch backbone and return a result
envelope; readers *observe* state and return a value (or `None`).

**Operations.** Every change is accepted first and finishes later. `client.perform(name, ...)` sends the
call and polls `get_progress` until the operation is `completed` or `failed`, checking each time that
the operation id is still ours. The command wrappers all go through it, so a move returns once the
stage is there, a setting once it is applied, an acquisition once mesoSPIM's own "finished" signal has
fired. An accepted change is never re-sent because polling was slow: on a timeout the driver raises and
names the operation, so you can look at `get_progress` before deciding what to do.

**The result envelope.** Every command returns a stable dict:

| Key | Meaning |
|---|---|
| `success` | The command achieved its effect (accepted, and its operation completed). |
| `confirmed` | A readback matched the target (`True`/`False`); `None` if no confirmation ran. |
| `message` | Human-readable summary. |
| `data` | Command-specific payload: the operation's result and record, the resulting position, … |
| `timing` | `{pre_check_s, fire_s, confirm_s, total_s, attempts, confirm_attempts}`. |
| `logs` | Ordered `{ts, level, msg}` trace. |

**`success` vs. `confirmed` — read both.** For moves and settings the profiles use
`success_on_unconfirmed=True`: `success=True, confirmed=False` means "mesoSPIM reported the change
done but the driver's own readback did not verify it" — the mismatch is in `logs`. `success=False` means
it did not happen: a validation or limit failure on either side (the message says which), a refusal
because another change was still running (`busy`), a failed operation, or a transport error.

**The freshness gate.** When a reader is asked for provenance (`diagnostics=True`) it returns a `Reading`
(`value` + `source` + `observed_at`). The confirm layer rejects any readback observed *before* the
command fired, so a stale pre-command read can never falsely confirm. Ordering uses
`time.perf_counter()` (monotonic, sub-microsecond) — wall-clock and `time.monotonic()` are both ~16 ms
coarse on Windows and would let a stale read share the fire's timestamp.

**Acquisition is two steps.** `acquire(...)` runs a capture and returns an `AcquisitionResult`
referencing the frame files the mesoSPIM image writer wrote (it **raises** if the server reports no
frames or the run fails). `save(...)` is a deliberate second step that relocates those frames into the
canonical layout and prints what the driver knows about the capture beside them.

**Errors.** A refused call raises `MesospimError` from `request()` (use `try_request()` when a refusal
is an expected, inspectable outcome); its `code` says why (`validation`, `busy`, `unknown_command`,
`execution`; a failed operation carries `operation`). Transport failures (dropped link, timeout)
invalidate the connection and are classified transient by the dispatch backbone (retried up to the
profile ceiling); there is no auto-reconnect.

**Logging.** `logging.getLogger("mesospim").setLevel(logging.DEBUG)` — the same trace also travels in
each result's `logs`.

## 6. API reference

All functions are synchronous; `client` is a `MesospimClient`. Commands return the result envelope of
§5; readers return a value or `None`.

### Connection
```python
connect(connection=None, *, host=None, port=None, timeout=None, token=None) -> MesospimClient   # password + greeting + ping
close(client) -> None                                                               # idempotent
ping(client) -> bool
client.request(name, **args) -> Reply            # one call; raises MesospimError on a refusal
client.try_request(name, **args) -> Reply        # one call; a refusal comes back as Reply(ok=False, code=...)
client.perform(name, *, timeout=None, poll_s=None, **args) -> Reply   # a change, waited on until its operation ends
```

### Movement (result envelope; µm / deg)
| Function | Signature | Notes |
|---|---|---|
| `move_absolute` | `(client, targets: dict, *, tolerance=None)` | `{axis: value}` over `x,y,z,f,theta`; limit-checked before firing; returns once the stage is there |
| `move_relative` | `(client, deltas: dict, *, tolerance=None)` | expected absolute (current + delta) is limit-checked & confirmed |
| `move_xy` | `(client, x, y, *, tolerance=None)` | convenience over `move_absolute` |
| `move_z` / `move_focus` | `(client, value, *, tolerance=None)` | sample Z / detection focus |
| `move_rotation` | `(client, theta, *, tolerance=None)` | degrees |
| `move_to_preset` | `(client, preset)` | `"load_sample"` / `"unload_sample"` / `"center_sample"`: the positions configured in mesoSPIM |
| `stop` | `(client)` | halt all motion (an emergency call: runs even while a change is busy) |
| `zero_axes` | `(client, axes=None)` | define current position as mesoSPIM's zero (`None` = all axes) |

### Instrument state (result envelope)
| Function | Signature | Notes |
|---|---|---|
| `set_state` | `(client, settings: dict)` | batch of mesoSPIM state keys; the server validates each against the configuration |
| `set_filter` / `set_zoom` / `set_laser` | `(client, name)` | select by name (`"515/30"`, `"1x"`, `"488 nm"`) |
| `set_intensity` | `(client, intensity)` | laser intensity, 0–100 % (range-checked) |
| `set_shutter` | `(client, shutterconfig)` | `"Left"` / `"Right"` / `"Both"` |
| `set_etl` | `(client, side, *, amplitude=None, offset=None)` | `side` = `"left"`/`"right"`; either/both params, within the server's ranges |

### State readers
All take `(client, ...)`; pass `diagnostics=True` for a source-tagged `Reading`.

| Function | Returns |
|---|---|
| `ping` | `bool` |
| `get_state` | `state` (mesoSPIM's run state: `idle`, `live`, a run state, …), `position` (`{x,y,z,f,theta}`), and the settings (`laser`,`intensity`,`filter`,`zoom`,`shutterconfig`,`etl_*`) |
| `get_positions` | `{x,y,z,f,theta}` (µm / deg) |
| `get_position` | single axis value |
| `get_xyz` | `{x,y,z}` |
| `get_config` / `get_hardware_info` | `lasers` (`[{name,wavelength_nm}]`), `filters`, `zooms` (`[{name,pixel_size_um}]`), `axes`, `shutter_configs`, `camera` (`{pixels_x,pixels_y}`), `app`, `version` |
| `get_lasers` / `get_filters` / `get_zooms` | the corresponding list from `get_config` |
| `get_limits` | the server's `stage`/`camera`/`startup` configuration and the `enforced` envelope (`axes`, `axis_offsets`, `parameters`) |
| `get_info` | the server's own information page: identity, `state`, `stage_type`, `save_path`, the latest `operation`, recent `warnings` |
| `get_progress` | `current_plane`, `total_planes`, `current_acquisition`, `total_acquisitions`, `state`, and the latest `operation` |

### Acquisition & save
```python
acquire(client, acquisition_type="snap", *, options=None, state=None) -> AcquisitionResult   # RAISES if no frames / run failed
snap(client, *, options=None) -> AcquisitionResult                                            # single frame (planes=1)
run_acquisition_list(client, acquisitions: list[dict]) -> dict                                # multi-tile/-channel
build_acquisition(state: dict, options=None) -> dict                                          # compose an Acquisition dict
save(acq, output_root, *, position_label, format="ome-tiff", state=None) -> SavedAcquisition   # relocate + print the state
canonical_stem(acquisition_type, position_label) -> str
data_dir / metadata_dir / state_dir / vendor_dir(output_root) -> Path                         # the layout, one function each
```
`options` may set `folder`/`filename` (where the image writer writes — the controller path fills these
in) and acquisition fields (`planes`, `z_step`, `z_start`, `z_end`, `laser`, `intensity`, `filter`,
`zoom`, `shutterconfig`, …). A capture is three calls — `acquire_start` (accepted at once), a poll of
its operation until mesoSPIM reports the run finished (up to `ACQUISITION.acquire_timeout_s`), a
`stat_files` check that the stack has stopped growing — and `acquire_finish`, which hands the operator's
own acquisition list back on every path. Result/product types: `AcquisitionResult`,
`AcquisitionMetadata`, `ChannelMetadata`, `SavedAcquisition` (`acquisition/product.py`).

`save()` takes **no client** — it relocates the files the writer already produced. What it leaves
behind is the layout every ZMART driver writes:

```
<output_root>/
    data/
        <type>_<label>.tiff                                 the pixels (one multi-page stack)
        metadata/
            ZMART_state/<type>_<label>_ZMART_state.json     ZMART's account: the acquisition row that
                                                            ran, the state it was captured under, the
                                                            files written
            vendor/mesospim/<type>_<label>_meta.txt         the mesoSPIM writer's own notes
```

It does not re-encode pixels (the OME rewrite is a documented seam; see [§12](#12-extending-the-driver)).

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
# protocol (advanced callers):
Reply, frame, encode_call, parse_reply, PROTOCOL_VERSION
```

## 7. Architecture

```
zmart_drivers/mesospim/
├── protocol.py     framing, {name: args} calls, __MESOSPIM_OK__ / error: [code] replies, operation records — pure, socket-free
├── connection/     client.py  blocking TCP client: password, greeting, request/try_request, perform (operation polling)
│                   session.py connect() / close()
├── commands/       dispatch.py  confirm_and_fire backbone (fire + transient retry → confirm + optional re-fire)
│                   movement.py  move_*/stop/zero_axes/move_to_preset (three-phase: validate+limits → backbone → envelope)
│                   commands.py  set_*/set_state wrappers (instrument-state settings)
│                   envelope.py  the shared result-envelope builders (leaf)
├── limits/         checks.py    fail-closed 5-axis µm/deg envelope check (enforced only in commands/)
│                   defaults/    bundled stage_limits.json + function_limits.json (ship with the driver)
├── calibration/    machine.py   ProgramData resolution of the stage envelope, function limits, persisted origin
├── readers/        readers.py   get_* reads + the Reading freshness gate
├── config/         profiles.py  CONNECTION/HARDWARE/ACQUISITION + CommandProfile instances (MOVE/MOVE_ROTATION/SET_STATE)
├── acquisition/    product.py   typed results     capture.py  build/acquire/snap/run_acquisition_list
│                   save.py      relocate the writer's stack into data/ and print the state under data/metadata
├── mesospim_zmart_adapter.py  ZMART controller adapter — ops table (connect, set_xyz, acquire, get/set_state, …); registers at import
└── tests/          unit/  offline vs the mock server     integration/  vs mesoSPIM -D demo     helpers/mock_mesospim_server.py
```

**Dispatch backbone** (`commands/dispatch.py` → `confirm_and_fire`) — two layers, deliberately *dumb* (it
owns order, retry ceilings, and timing; it knows nothing about axes, lasers, or acquisitions):

```
confirm_and_fire
 ├─ fire block   send the request and wait for its operation; retry only on transient transport errors
 │               (≤ max_retries). A refusal or a failed operation is permanent, not retried.
 └─ confirm wrap run confirm_fn (readback + freshness gate); optionally re-fire and re-confirm (≤ max_confirm_attempts).
```

Command wrappers supply small zero-arg/one-arg callables (targets pre-bound with `functools.partial`).
Because the server completes a move only once the stage reads back at the target, a single confirm read
normally sees the arrived state.

**GPL/MIT split.** The whole driver is MIT and imports nothing from mesoSPIM. The Remote Control server
is part of mesoSPIM-control (GPL); the driver reaches it over a socket, and nothing ZMART-specific runs
inside the mesoSPIM process (see [§10](#10-licensing--how-this-stays-mit)).

**Dependency direction:** `config.axes`/`commands.envelope` (stdlib leaves) → `protocol` →
`connection.client` → `commands.dispatch` → `config.profiles`/`limits.checks` →
`commands.movement`/`commands.commands`; `calibration` (machine config), `readers`, `acquisition`, and
the adapter sit above. No circular imports.

## 8. Configuration & tuning (profiles)

Per-command tuning lives in `config/profiles.py` as frozen `CommandProfile` instances; wrappers accept
explicit overrides (`tolerance=`) only for tests/unusual runs. Tuning a command = editing its profile.

```python
@dataclass(frozen=True)
class CommandProfile:
    max_retries=2 ; max_confirm_attempts=3 ; refire_on_unconfirmed=False
    confirm_tolerance=None ; success_on_unconfirmed=False
    # __post_init__ forbids the incoherent max_confirm_attempts==1 + refire_on_unconfirmed=True
```

| Profile | Posture |
|---|---|
| `MOVE` | confirm within `1.0 µm` (the server's own completion tolerance); unconfirmed ≠ failure. |
| `MOVE_ROTATION` | as `MOVE` but `0.1°` tolerance (chosen for `theta`-only moves). |
| `SET_STATE` | re-fire between confirm windows; unconfirmed ≠ failure. |

Other tuning surfaces: `CONNECTION` (host/port/password/timeout and the operation polling),
`ACQUISITION.acquire_timeout_s` (how long a run may take, 600 s) and `file_settle_timeout_s`, and
`HARDWARE` (the offline device model / validation reference).

## 9. Testing

One self-contained gate ([`run_ci.py`](run_ci.py) — env header + lint + tests + reports), three modes:

```bash
pip install -r requirements-dev.txt        # first run only; repo-root dev list (covers pytest, numpy, tifffile)

python zmart_drivers/mesospim/run_ci.py            # OFFLINE (default, portable): mock-server suite + coverage
python zmart_drivers/mesospim/run_ci.py online     # ONLINE:  live round-trip vs a running mesoSPIM -D demo
python zmart_drivers/mesospim/run_ci.py both       # BOTH:    the offline gate followed by the live round-trip
```

The two layers it runs, portable to most-faithful:

1. **Offline suite** — the MIT client vs a **mock Remote Control server** over a real socket; no mesoSPIM,
   no hardware. The mock is a *faithful* double: it demands the password, validates every call the way
   the real server does (unknown names, unknown arguments, options, ranges, stage limits), admits one
   change at a time, hands every change back as an operation the driver must poll, and writes a real
   TIFF stack with the writer's `_meta.txt` note beside it. `python -m pytest zmart_drivers/mesospim/tests`
   runs it directly (`-m "not integration"` is the default).
2. **Live round-trip** — the `-m integration` suite against a **running mesoSPIM `-D` demo** (real
   software, Demo backends, no hardware) on `MESOSPIM_HOST`/`MESOSPIM_PORT` (default `127.0.0.1:42000`)
   with the password in `MESOSPIM_TOKEN`. It skips cleanly if nothing is listening; capture is opt-in
   via `MESOSPIM_ALLOW_ACQUIRE=1` so it never fires lasers by accident. `run_ci.py` does not launch
   mesoSPIM — start the `-D` demo and its Remote Control TCP transport first (see
   [§2](#2-requirements--installation)), or use `tests/hardware/launch_demo_server.py` to boot the demo
   headless with the transport started.

Follow the project TDD practice: add a failing offline test first, and assert real values, not just
shapes.

## 10. Licensing — how this stays MIT

mesoSPIM-control is GPL-3.0. This driver is MIT. The two never share a process:

- The driver imports nothing from mesoSPIM. It sends named JSON calls over a TCP socket and reads the
  replies; the wire contract is a public, documented API of mesoSPIM-control (pull request #106).
- Nothing ZMART-specific runs inside mesoSPIM. The Remote Control server is a generic feature of
  mesoSPIM-control, usable by any client; the server never runs code a client sends.
- The mock server under `tests/helpers/` is an independent MIT re-implementation written from the
  protocol's public description, for tests only.

## 11. Invariants & gotchas

- **Limits fail closed, on both sides.** The driver rejects an axis with no configured limit; the server
  refuses a target outside the envelope of the loaded mesoSPIM configuration. A refusal on either side
  comes back as `success=False` with the reason in `message`; nothing moves.
- **One change at a time.** While a move, a setting or an acquisition is still running, another change
  is refused with `busy`. Reads, and the emergency `stop`, are answered meanwhile. Work started from the
  GUI counts too: during a GUI acquisition every remote change is refused.
- **Never re-send an accepted change.** If a reply is lost or a wait runs out, look at `get_progress`
  first: the operation may still be running or may have completed. The driver raises `TimeoutError`
  naming the operation rather than sending it again.
- **A capture holds the gate until mesoSPIM says it finished.** If a run never ends, `acquire_finish`
  (which restores the operator's own acquisition list) is refused as `busy` until the run is stopped in
  mesoSPIM (`stop_activity`); the driver warns and leaves it to be restored then.
- **Names must be the configured ones.** A filter, zoom, laser or shutter name is validated against the
  mesoSPIM configuration: read `get_config` first and pass its names back.
- **Password.** Plain TCP; the password gates casual LAN access, it is **not** sniffer-proof. On untrusted
  networks, tunnel it (SSH/VPN). The default password only works on the local machine.
- **Backlash take-up** on `acquire` is best-effort: it is skipped (with a warning) if the take-up move
  would leave the stage envelope — e.g. exactly at the lower limit.

## 12. Extending the driver

- **A new call.** Wrap it in `commands/` (a `fire_fn` that calls `client.perform(...)`, a `confirm_fn`
  that reads back) or `readers/` (one `client.request(...)`), then teach the mock server the same call
  so the offline suite covers it. The server's own call list is in mesoSPIM-control's
  `docs/source/remote_control/calls.md`; `get_manual` returns it from the running microscope.
- **Multi-channel captures** — loop lasers/filters into `run_acquisition_list` and expose a channel list
  through the controller `acquire` options.
- **Tiling helpers** — build an acquisition list over an XY grid (`set_acquisition_list` +
  `run_acquisition_list` on the server side).
- **OME-TIFF re-encode** in `acquisition/save.py` (today it copies the writer's stack verbatim; the
  pixel-pull → OME path is a documented seam).
- **The MCP transport** of the same server is not used by this driver; it exists for AI-agent clients
  and exposes the same 56 calls.

## 13. References

- mesoSPIM-control: <https://github.com/mesoSPIM/mesoSPIM-control> — Remote Control:
  [pull request #106](https://github.com/mesoSPIM/mesoSPIM-control/pull/106) (its
  `docs/source/remote_control/` holds the operator manual, the call list and the architecture).
- Sibling drivers (reference architecture): `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`,
  `zmart_drivers/zeiss/zenapi/`, `zmart_drivers/nikon/nis_elements_6_10/`.
