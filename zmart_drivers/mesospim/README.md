# mesoSPIM integration — findings & architecture (ZMART driver)

> **Status:** **driver implemented** (offline, mock-server tested — 94 tests green) + a resident
> command-server script for bench/`-D`-demo validation. This documents how the open-source
> **mesoSPIM-control** light-sheet acquisition software works and how the `zmart_drivers/mesospim/`
> driver **plugs into ZMART** (the vendor-agnostic controller surface) beside the Leica/Zeiss/Nikon/
> Evident drivers.
>
> **What ships now:** an MIT socket client (`connection/`), a dispatch backbone + command wrappers
> (`commands/`), state readers (`readers/`), profiles + 5-axis limits (`config/`), capture + save
> (`acquisition/`), a ZMART controller adapter (`controller.py`), the GPL resident command-server
> script (`server/`), and an offline suite driving a mock command server (`tests/`). The one
> remaining bench step is validating `server/mesospim_command_server.py` against mesoSPIM `-D` demo
> mode (its Core-binding calls are quarantined in one class for exactly that).
>
> **Target:** [mesoSPIM-control](https://github.com/mesoSPIM/mesoSPIM-control) (v1.20.0), the
> Python/PyQt5 acquisition app for mesoSPIM light-sheet microscopes (Benchtop / v4 / v5 + custom).
> mesoSPIM originated at **UZH** (Fabian Voigt, Helmchen lab) — a local, community-run project.
>
> **License:** mesoSPIM-control is **GPL-3.0**; ZMART is **MIT**. That contrast drives the design
> (see [Licensing](#licensing--how-this-stays-mit)).

---

## TL;DR

- mesoSPIM-control is a **monolithic PyQt5 GUI app with NO external control API** — no socket, ZMQ,
  REST, or RPC. All control is in-process, inside the Qt event loop.
- **But** it exposes, in-process: a **Script Window** (`exec()`s a script with the full Core `self`
  in scope), an **embedded IPython console** (`-C`), **GUI-free `Acquisition`/`AcquisitionList`**
  data classes, and a process-wide **state singleton** — plus **complete demo backends + a `-D`
  demo mode** that run the whole app with zero hardware.
- **Recommended (MIT-preserving, no fork):** add a **resident Python "command-server" script** —
  loaded through mesoSPIM's own **Script Window** — that opens a localhost socket and **QTimer-polls**
  it, translating text commands into Core signals / state reads (the exact analog of the Nikon
  `NkSocketServerDemo.mac` `WM_TIMER` poll). ZMART's `zmart_drivers/mesospim/` is then a thin **MIT external
  client** speaking that socket — a sibling of the Leica CAM / Nikon NkSocket drivers.
- This keeps **ZMART MIT** (process boundary; GPL confined to the resident script), and it is
  **testable offline against the real software** via `-D` demo mode — unique among the ZMART drivers.

---

## What it is (hardware + stack)

Python 3.12, PyQt5, pyqtgraph. Config-driven hardware abstraction with swappable backends. Controls:

- **Cameras** (`src/devices/cameras/`): Hamamatsu Orca (DCAM), Photometrics (PVCAM/PyVCAM), PCO, `Demo_Camera`.
- **Stages** XYZ + rotation + focus (`src/mesoSPIM_Stages.py`, `src/devices/stages/`): Physik Instrumente (C-884), PI+Galil hybrid, ASI Tiger/MS-2000, `mesoSPIM_DemoStage`.
- **Lasers** (`src/devices/lasers/`): NI/cDAQ digital enable + analog modulation; `Demo_LaserEnabler`.
- **DAQ / galvos / ETL waveforms** (`src/mesoSPIM_WaveFormGenerator.py`): National Instruments generates galvo + tunable-lens + camera-trigger waveforms; `mesoSPIM_DemoWaveFormGenerator`.
- **Shutters** (`NI_Shutter`/`Demo_Shutter`), **filter wheels** (Ludl, Sutter Lambda 10, Dynamixel, ZWO; Demo), **zoom** (Dynamixel servo, Mitutoyo turret; Demo).

## Architecture

Monolithic Qt app (no formal QStateMachine; a shared state dict + string state field):

- **Entry** `mesoSPIM/mesoSPIM_Control.py` builds `QApplication` + `mesoSPIM_MainWindow` and calls
  `ex.show()` — **GUI is mandatory; no headless mode.**
- **`mesoSPIM_MainWindow`** moves the Core onto its own thread:
  `self.core = mesoSPIM_Core(cfg, self); self.core.moveToThread(self.core_thread)`.
- **`mesoSPIM_Core(QtCore.QObject)`** — "the pacemaker": everything is **signals/slots**
  (`sig_state_request`, `sig_move_relative`, `sig_prepare_image_series`, …). It spawns camera /
  image-writer / serial worker QThreads.
- **Device HAL is config-driven** (if/elif on config strings in the Core), e.g.
  `if cfg.waveformgeneration in ('NI','cDAQ'): … elif == 'DemoWaveFormGeneration': …`;
  stages dispatched by `stage_parameters['stage_type']`.
- **State:** `mesoSPIM_StateSingleton` — process-wide, mutex-guarded; `state['state']` cycles
  `init → idle → live/snap/running_script`.
- **Acquisition loop:** `start → prepare/run/close_acquisition_list → run_acquisition` iterates
  z-planes (`snap_image_in_series()` + `move_relative()`).

## Programmatic control surfaces (all in-process)

1. **Script Window** (`mesoSPIM_ScriptWindow.py` → Core slot): the Core literally
   `exec()`s the script with `self` in scope —
   ```python
   @QtCore.pyqtSlot(str)
   def execute_script(self, script):
       self.state['state'] = 'running_script'
       exec(script)   # full access to self (Core), self.state, devices
   ```
   Ships example scripts in `mesoSPIM/scripts/`.
2. **Embedded IPython console** (`-C/--console`): `IPython.start_ipython(..., user_ns={'mSpim': ex, 'app': app})` — `mSpim.core` reaches everything.
3. **`Acquisition` / `AcquisitionList`** (`utils/acquisitions.py`): GUI-free data classes
   (`x_pos, y_pos, z_start/end/step, planes, rot, laser, intensity, filter, zoom, etl_*`, …),
   constructible in pure Python; the app runs a list via *Run Acquisition List*. (On-disk save is an
   undocumented pickle `.bin`, so cross-process file exchange is fragile.)
4. **`mesoSPIM_StateSingleton`** — a co-resident object can read/write instrument state and enqueue
   actions via the Core's signals.

There is **no** way for a separate OS process to drive it out of the box.

## The recommended hook (no fork)

Use surface (1) to add the missing socket boundary **without forking mesoSPIM**:

- A **resident command-server script** (our file, loaded via the Script Window) opens a
  `127.0.0.1` TCP server and **QTimer-polls** it — non-blocking, so it never freezes the Qt event
  loop (directly analogous to the Nikon `NkSocketServerDemo.mac` `WM_TIMER` poll). Each received
  text line is dispatched to the Core: emit `sig_move_relative` / `sig_state_request`, snap, submit
  an `AcquisitionList`, or read `mesoSPIM_StateSingleton` for a reply.
- ZMART's **`zmart_drivers/mesospim/`** connects as an external **MIT** client and speaks that protocol —
  identical in shape to the Leica CAM / Nikon NkSocket drivers, so it reuses the existing driver
  skeleton (connection + commands + readers).
- **Better than a fork:** it's a script mesoSPIM *runs*, not a patch to maintain — and it's a good
  **upstream contribution** (Zurich-local, community project), which would make the hook first-class.

## Licensing — how this stays MIT

- mesoSPIM-control is **GPL-3.0**. Importing its modules into ZMART would make the combined work GPL.
- The **process boundary avoids that**: ZMART links only to our **MIT** external client, which
  *communicates with* a separate GPL program (mere aggregation, not a derivative work).
- The **GPL edge is the resident script only** (it uses the GPL Core API) — a small, standalone file,
  ideally contributed upstream. ZMART core + the `zmart_drivers/mesospim/` client stay MIT.
- GPL does **not** restrict *use* (incl. commercial) — only distribution of derivatives. So a
  commercial ZMART product driving mesoSPIM at arm's length is fine; folding modified mesoSPIM source
  into a closed product is the only thing that isn't. (Not legal advice — confirm with UZH tech-transfer.)

## Can do / can't do

### ✅ Can do
- Drive mesoSPIM **in-process** today via the Script Window / IPython console (move, snap, run lists).
- Add a clean **external socket** via a resident QTimer-polled script — no fork — then drive it from
  an MIT ZMART client (Leica/Nikon-symmetric).
- **Test the whole loop offline against the real software** using `-D` demo mode (all Demo backends).
- Reuse the vendor-neutral driver skeleton (connection + commands + readers + profiles).

### ❌ Can't do
- **No external API out of the box** — nothing for a separate process to connect to until we add the hook.
- **No headless mode** — the Qt GUI is mandatory; the Core isn't cleanly usable without `QApplication`.
- **In-process import into ZMART is off the table** — it would make ZMART GPL and fights the Qt coupling.
- The acquisition-list **`.bin`** format is undocumented pickle — don't rely on file interchange; submit lists in-process via the hook.

## Integration into ZMART

The `zmart_drivers/mesospim/` driver presents ZMART's neutral contract; internally it is a socket client:

```
zmart_drivers/mesospim/
  protocol.py     pure JSON-lines encode/parse (MIT)
  connection/     TCP client + session lifecycle to the resident command server
  commands/       dispatch backbone + verb wrappers (move_xy/z/focus/rotation, set_filter/zoom/laser/etl, ...)
  readers/        parse replies / state-singleton queries into ZMART state
  config/         profiles (host/port; per-command confirm/retry tuning), hardware model, 5-axis limits
  acquisition/    capture (snap / acquisition list) + save into the canonical layout
  controller.py   ZMART controller adapter (ops table + register)
  server/         the resident mesoSPIM command-server script (GPL edge) + PROTOCOL.md + upstream proposal
  tests/          offline: MIT client vs a mock server (94 tests); integration: vs mesoSPIM -D demo mode
```

### Two ways to drive it

Directly (thin, notebook-style):

```python
import mesospim as drv
client = drv.connect({"host": "127.0.0.1", "port": 42000})
# Required before any move: limits fail *closed*, so an unconfigured axis is
# rejected. (The zmart_controller path loads these automatically in connect.)
drv.apply_stage_limits_from_config(drv.load_stage_config())
drv.move_xy(client, 1000, 2000)          # micrometers
drv.set_filter(client, "515/30")
acq = drv.acquire(client, "prescan")     # capture with current settings
saved = drv.save(acq, run_dir, position_label="A1")
drv.close(client)
```

Through the vendor-neutral controller (`import zmart_controller`):

```python
import mesospim, zmart_controller
mesospim.register({"vendor": "mesospim", "microscope": "mesospim-01",
                   "api": "command-server", "host": "127.0.0.1", "port": 42000})
sess = zmart_controller.set_instrument(zmart_controller.get_instruments()[0])
sess.set_origin()
sess.set_xyz(10, 20, 5)                                   # um from origin
sess.acquire("prescan", "A1", options={"format": "ome-tiff"})
sess.disconnect()
```

The controller surface is x/y/z centric; focus and rotation are exposed as **procedures**
(`move_focus`, `move_rotation`), and laser/filter/zoom/intensity/shutter/ETL as the capturable
**mutable state** (`get_state` / `set_state`). The full driver API (`import mesospim`) covers the rest.

### Testing

```bash
python -m pytest zmart_drivers/mesospim/tests          # offline: MIT client vs mock command server
python -m pytest zmart_drivers/mesospim/tests -m integration   # vs mesoSPIM -D demo mode (see server/README.md)
```

## Next steps

1. ~~**Spike:** MIT external client + mock command server + offline tests.~~ **Done** — the client,
   dispatch/commands, readers, config/limits, acquisition, and the mock-server test suite are in
   place (94 tests green), and the protocol is specified in [`server/PROTOCOL.md`](server/PROTOCOL.md).
2. ~~**Resident command-server script:** the QTimer-polled socket server that dispatches to the Core.~~
   **Written** ([`server/mesospim_command_server.py`](server/mesospim_command_server.py)); its
   Core-binding calls are quarantined in `_CoreBridge`. **Still to do:** validate it against
   **mesoSPIM `-D` demo mode** (real software, no hardware) — see [`server/README.md`](server/README.md).
3. **Propose the hook upstream** to the mesoSPIM project (avoids a maintained fork; benefits the community).
4. ~~**Grow into `zmart_drivers/mesospim/`** and register it with the ZMART controller.~~ **Done** —
   [`controller.py`](controller.py) registers the driver's ops table with `zmart_controller`.

## References
- mesoSPIM-control: <https://github.com/mesoSPIM/mesoSPIM-control>
- mesoSPIM project: <https://mesospim.org>
- Sibling patterns: `zmart_drivers/nikon/` (resident socket macro + external client), `zmart_drivers/leica/.../navigator_expert/` (CAM external orchestrator).

<!-- Investigation date: 2026-07-01. Maintainer: Thom de Hoog (ZMB / University of Zurich),
     thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com. ZMART driver = MIT; mesoSPIM-control = GPL-3.0,
     kept behind a process boundary. Grounded in a source read of mesoSPIM-control v1.20.0. -->
