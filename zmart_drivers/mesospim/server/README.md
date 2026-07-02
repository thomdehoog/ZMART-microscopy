# mesoSPIM resident command server (GPL edge)

`mesospim_command_server.py` is the small resident script that gives
mesoSPIM-control the external socket API it lacks, so the MIT ZMART driver can
drive it from another process. It is the **only GPL-3.0 file** in the mesoSPIM
driver: it uses the GPL mesoSPIM `Core` API and imports nothing from ZMART. The
ZMART client speaks to it over a localhost socket (see [`PROTOCOL.md`](PROTOCOL.md)),
so the process boundary keeps ZMART MIT (rationale in the driver
[`README.md`](../README.md) → Licensing).

## How it works

mesoSPIM-control has no headless mode and no RPC, but its Core menu has a
**Script Window** whose slot literally `exec()`s your script with `self` (the
`mesoSPIM_Core`) in scope. This server is **two files**:

- **`mesospim_command_server.py`** — a normal Python *module* with the logic: the
  `_CoreBridge` (the only Core-touching surface), the JSON dispatch, and the
  `QTcpServer` + `QTimer` socket loop. Call `start(core)` to run it.
- **`scriptwindow_loader.py`** — the tiny **flat** script you actually open in the
  Script Window. It imports the module and calls `start(self)`.

**Why two files?** The Script Window runs your script with `exec(script)` *inside*
`mesoSPIM_Core.execute_script` — a method, so `globals()` and `locals()` are
different dicts. A *module*-shaped script fails there: its top-level names
(constants, classes) land in locals but resolve as globals, raising `NameError`
(e.g. the `host=DEFAULT_HOST` default on `MesospimCommandServer.__init__`). A
**flat** script — only top-level statements using `self`, exactly like mesoSPIM's
own `mesoSPIM/scripts/` examples — survives that scope. So the loader stays flat
and the logic stays a module.

When the loader runs, the server:

1. opens a `QTcpServer` on `127.0.0.1:42000`, parented to the Core (so it
   outlives the loader's `exec()` frame);
2. **`QTimer`-poll**s the socket every ~20 ms — non-blocking, so the Qt event
   loop never freezes (the same pattern as the Nikon `NkSocketServerDemo.mac`
   `WM_TIMER` poll);
3. translates each JSON request line into a Core action (`move_absolute`,
   `sig_state_request`, run an `Acquisition`) or a state read, and writes back a
   JSON reply line.

The Core-touching calls are grouped in one class, `_CoreBridge`, so they are the
single surface to confirm against your mesoSPIM version.

## Loading it

1. Start mesoSPIM-control (real hardware, or **`-D` demo mode** for a
   hardware-free run: `python mesoSPIM_Control.py -D`).
2. Core menu → **Script Window** → open **`scriptwindow_loader.py`** → **Run**.
   Open the *loader*, **not** `mesospim_command_server.py` (see "How it works").
   If the ZMART driver isn't already importable in mesoSPIM's Python, set
   `SERVER_DIR` at the top of the loader to the folder holding
   `mesospim_command_server.py`.
3. You should see `[mesospim-cmd-server] listening on 127.0.0.1:42000` and
   `[mesospim] ZMART command server started via the Script-Window loader`.
4. From ZMART: `mesospim.connect({"host": "127.0.0.1", "port": 42000})`.

## Validating offline (recommended before any bench use)

mesoSPIM `-D` demo mode runs the whole app with Demo backends — no camera,
stages, lasers, or DAQ. Load the server there and run the ZMART round-trip:

```bash
python mesoSPIM_Control.py -D          # terminal 1: mesoSPIM in demo mode + Script Window → Run this file
# terminal 2: the packaged live round-trip (connect → get_config → get_state →
# move → get_position → acquire). Skips cleanly if nothing is listening; the
# capture step is opt-in so it never fires lasers by accident:
MESOSPIM_ALLOW_ACQUIRE=1 python -m pytest zmart_drivers/mesospim/tests -m integration
# Point it at another address with MESOSPIM_HOST / MESOSPIM_PORT.
```

mesoSPIM-control is effectively **Windows-only** (Python ≥3.12); `-D` demo mode
needs no hardware or drivers, so a Windows VM is sufficient for this step.

This is unique among the ZMART drivers: the whole control loop can be exercised
against the **real acquisition software** with no hardware.

### Headless validation of the Qt half (no mesoSPIM needed)

`validate_headless.py` runs this server's **entire Qt machinery** (`QTcpServer` +
`QTimer` poll + JSON dispatch + `_CoreBridge`) against a *fake* Core, driven by
the real `MesospimClient` over a localhost socket — proving everything except the
real Core executing the calls. It needs only PyQt5 and runs with no display:

```bash
QT_QPA_PLATFORM=offscreen python zmart_drivers/mesospim/server/validate_headless.py
# ... RESULT: PASS ✅
```

The fake Core's method/signal surface (`move_absolute(sdict, wait_until_done=…)`,
`move_relative`, `zero_axes(list)`, `sig_stop_movement`,
`sig_state_request_and_wait_until_done`, the `x_abs`/`x_rel` move keys, and the
`state['position']['x_pos']` layout) was checked against mesoSPIM-control
v1.20.0 source, so the only surface this does **not** cover is the live Core
actually moving hardware/demo backends — that is the `-D`-demo step above.

## Adapting to your instrument

All Core-touching names were **verified against mesoSPIM-control `1.20.0`**
source and corrected to match. Re-verify only if your installed version differs;
everything below is isolated in `_CoreBridge` (and the module-level `_written_files`
/ `_camera` helpers it calls):

- `core.move_absolute(sdict, wait_until_done=True)` / `core.move_relative(...)`
  and the `{axis}_abs` / `{axis}_rel` state keys. ✓ verified
- `core.sig_state_request_and_wait_until_done` for settings. ✓ verified
- Config attribute names in `config()` / `_camera()`: `laserdict`, `filterdict`,
  `zoomdict` + separate `pixelsize`, `shutteroptions`,
  `camera_parameters['x_pixels'/'y_pixels']`. ✓ verified
- **Validated live** (`-D` demo, v1.20.0): the `Acquisition` run path
  (`core.start(row=0)` + a Qt-event-loop wait for completion) and the image-writer
  output-path resolution in `_written_files` (default Tiff writer → one multi-page
  stack per acquisition). Still to confirm on a **real instrument** (demo mode
  simulates the devices) and for **non-Tiff writers**.

## Upstreaming

The cleanest long-term home for this file is the mesoSPIM project itself (a
first-class "command server" script, Zurich-local and community-run), so it is a
script mesoSPIM *ships and runs* rather than a patch anyone has to maintain.
