# mesoSPIM driver — live bench validation against the real software

> **⚠ SUPERSEDED (transport changed).** This document records the bench validation of the earlier
> **bespoke command-server** transport (a ZMART-specific JSON command server loaded into the Core via a
> Script-Window loader). That transport has since been **retired**: the driver now rides mesoSPIM's generic
> **Remote Scripting** bridge (the upstream patch under `pull_request/`), injecting Python scripts and
> parsing a structured result. Kept as history — it is why the design moved to Remote Scripting (the loader's
> `exec()`-scope `NameError` and the two live-only bugs below are exactly the sharp edges the generic bridge
> avoids). The findings about the live Core API (config/state/move/`start(row=…)`/image-writer path) still
> hold and now live in `connection/scripts.py`; the live round-trip on the *new* transport is the open item
> in `TODO.md`.

**Date:** 2026-07-02
**Tester:** Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com
**Target:** mesoSPIM-control **v1.20.0** in `-D` demo mode (all Demo backends, no hardware)
**Driver under test:** branch `claude/mesospim-zmart-driver-brbeqv` @ `8f52101`, `zmart_drivers/mesospim/`

---

## Update — fix applied and re-validated (2026-07-02)

The loader bug below is **fixed and committed on this branch**, and the round-trip
was re-run through the **unmodified** mesoSPIM `Core.execute_script`, loading the
shipped `server/scriptwindow_loader.py` exactly as an operator would:

- `server/scriptwindow_loader.py` — new flat Script-Window loader.
- `server/mesospim_command_server.py` — the exec-only `if "self" in dir()` bootstrap
  replaced by a clean, importable `start(core)` (reload-safe). No logic changes.
- `tests/unit/test_scriptwindow_loader.py` — reproduces the exec scope and locks the fix in.

Result: **115 offline tests** pass (111 + 4 new) and **5/5 live integration tests**
pass through the real loader + live demo `Core`. Everything below is the original
diagnosis that led here.

## Verdict

> **As shipped, the driver does NOT interact with mesoSPIM-control — the documented way to load
> the command server fails immediately. But the driver's logic is correct: with a ~4-line loader
> fix (a flat shim), it drives the real app end-to-end, and all five packaged integration tests
> pass against the live demo `Core`, including a real acquisition.**

Two independent things were established:

1. **The integration *premise* is sound.** mesoSPIM's Script Window really does run a loaded
   script inside the live `mesoSPIM_Core` with `self == Core`, and every `_CoreBridge` binding
   (config attribute names, state keys, move API, `start(row=…)` acquisition, image-writer path)
   is correct against the real 1.20.0 Core.
2. **The *loader* is broken.** The command-server file cannot be loaded via the Script Window as
   the README instructs, because of a Python `exec()` scoping issue (details below). This is a
   ship-blocker: on the bench, step 2 of "Loading it" (`README` → open the file → Run) throws a
   `NameError` before the socket ever opens.

The branch's `TODO.md` claim — *"validated against a live `-D` demo Core, all 5 integration tests
pass"* — cannot have gone through the real Script-Window path (it would have hit the same
`NameError`). It was presumably `exec()`'d with a custom namespace that masks the bug. This run is
the first faithful one through the real path.

---

## The bug — command server cannot be loaded via the Script Window

### Symptom (reproduced)

Injecting `server/mesospim_command_server.py` through the real path
(`MainWindow.execute_script → sig_execute_script → Core.execute_script → exec(script)`) throws:

```
Traceback (most recent call last):
  File "…/mesoSPIM/src/mesoSPIM_Core.py", line 917, in execute_script
    exec(script)
  File "<string>", line 461, in <module>
  File "<string>", line 464, in MesospimCommandServer
NameError: name 'DEFAULT_HOST' is not defined
```

### Root cause

`mesoSPIM_Core.execute_script` runs the script like this:

```python
@QtCore.pyqtSlot(str)
def execute_script(self, script):
    self.state['state'] = 'running_script'
    try:
        exec(script)          # <-- exec INSIDE a method: globals() != locals()
    except:
        traceback.print_exc()
    ...
```

Because `exec(script)` is called inside a method, the script executes with
`globals()` = the `mesoSPIM_Core` **module** globals and `locals()` = the method's local dict —
**two different namespaces**. The server file is a full *module*: it defines module-level constants
(`DEFAULT_HOST`, `DEFAULT_PORT`, `PROTOCOL_VERSION`, `_MAX_LINE_BYTES`, `_ABS_KEY`, …), classes
(`_CoreBridge`, `MesospimCommandServer`), and functions that call each other (`handle_request` →
`_dispatch` → `_Nak` …).

Under `exec()` in a function scope:

- Top-level assignments/`def`s/`class`es land in **locals**.
- But a class body / a function-default expression / a call from one top-level function to another
  resolves names via **globals** (a function's `__globals__` is the globals passed to `exec`).

So `DEFAULT_HOST = "127.0.0.1"` is written to *locals*, but
`def __init__(self, core, host: str = DEFAULT_HOST, …)` evaluates its default via *globals* →
`NameError`. The same failure would hit `handle_request` calling `_dispatch`, etc. In short, a
module-shaped script is fundamentally incompatible with `exec(script)` in method scope.

### Why upstream's own example scripts don't hit this

The scripts in `mesoSPIM/scripts/` are **flat** — only top-level statements that use `self`
directly (`self.snap()`, `self.set_filter(...)`, `self.serial_worker.move_relative(...)`). Flat
scripts never cross the locals/globals boundary, so they work. The command server is the only
"script" here shaped like a module.

---

## The fix — a flat Script-Window shim

The Script-Window entry must be **flat** and delegate the real logic to an imported module (where
names resolve against a proper module `__dict__`). The proven-working shim:

```python
import sys
sys.path.insert(0, r"<dir containing the server module>")
import mesospim_command_server as _m
self._zmart_cmd_server = _m.MesospimCommandServer(self)
```

Every line is a top-level statement using names bound in the same scope, so it survives
`exec(script)`. Inside `MesospimCommandServer`, name resolution uses the imported module's real
globals, so `DEFAULT_HOST` et al. resolve normally.

**Recommended productionization** (either is clean):

- **Split:** keep `mesospim_command_server.py` as the module (the real logic), and make the
  *Script-Window file* a tiny separate shim that imports it; **or**
- **Package + install** the GPL edge as an importable module in the mesoSPIM env, so the shim is
  just `from zmart_mesospim_server import start; start(self)` with no hardcoded path.

The `_CoreBridge` internals need **no** changes — they are already verified correct (below).

---

## Evidence the rest is correct

Loaded via the flat shim (i.e. through the *unmodified* real `Core.execute_script` path), the
resident server came up cleanly:

```
[mesospim-cmd-server] listening on 127.0.0.1:42000
[shim] command server started via imported module
```

The packaged live round-trip (`tests/integration/test_live_roundtrip.py`) against it:

```
platform win32 -- Python 3.12.13, pytest-9.1.1
configfile: pytest.ini

tests/integration/test_live_roundtrip.py::test_handshake_reports_protocol_and_app     PASSED
tests/integration/test_live_roundtrip.py::test_get_config_has_lasers_and_camera        PASSED
tests/integration/test_live_roundtrip.py::test_get_state_has_position_and_settings     PASSED
tests/integration/test_live_roundtrip.py::test_move_absolute_confirms_without_moving   PASSED
tests/integration/test_live_roundtrip.py::test_acquire_writes_a_file                   PASSED

5 passed in 6.64s   (test_acquire_writes_a_file: 4.96s)
```

What each proves against the **real** 1.20.0 Core:

| Test | Confirms |
|---|---|
| handshake | `hello` reports `app="mesoSPIM-control"` and the expected protocol version |
| get_config | config attribute bindings `laserdict` / `filterdict` / `zoomdict` + separate `pixelsize`, and `camera_parameters['x_pixels'/'y_pixels']` are all correct |
| get_state | state singleton `position` + settings keys read correctly (raw `x_pos…` → `{x,y,z,f,theta}`) |
| move_absolute | `move_absolute(sdict, wait_until_done=True)` + readback/confirm plumbing |
| **acquire** | `core.start(row=0)` actually runs (mesoSPIM's own disk pre-check logged `Free disk C: space 224.2 GB`), the image writer writes a stack, and `_written_files` resolves the path the driver returns |

So the site-specific pieces that the offline mock could never prove — the `_CoreBridge` names and
the acquisition run + writer-path resolution — are confirmed against the live software.

---

## Reproduction

### Environment (one-time)

- **conda-forge env `mesospim-control`** (conda-forge only; app deps via pip = licensing-safe):
  ```
  conda create -n mesospim-control -c conda-forge --override-channels python=3.12 pip
  <env>\python -m pip install -r <mesoSPIM-control>\requirements-conda-mamba.txt
  <env>\python -m pip install pytest
  ```
  Notes: `nidaqmx` imports fine without the NI-DAQmx runtime (lazy DLL load); PyQt5 runs headless
  with `QT_QPA_PLATFORM=offscreen`.
- **mesoSPIM-control** clone: `Z:\…\repositories\mesoSPIM-control` (v1.20.0).
- **Driver worktree:** `C:\ProgramData\MinicondaZMB\home\t.de\mesospim-wt`
  (`git worktree add --detach … origin/claude/mesospim-zmart-driver-brbeqv`) — does not disturb the
  `driver-cleanup` checkout.

### Run

1. Launch the headless server (mirrors `mesoSPIM_Control.main()` offscreen and injects the shim):
   `python run_mesospim_server.py` → wait for `listening on 127.0.0.1:42000`.
2. In another process:
   ```
   set MESOSPIM_HOST=127.0.0.1
   set MESOSPIM_PORT=42000
   set MESOSPIM_ALLOW_ACQUIRE=1
   python -m pytest <worktree>\zmart_drivers\mesospim\tests\integration\test_live_roundtrip.py -m integration -v -s
   ```

### Gotchas discovered while making the real app run headless

These are harness concerns (for driving the GUI app with no display / no clicks), **not** driver
bugs — but they must be handled or the app won't construct/stay up:

1. **`PluginRegistry(cfg)` must run BEFORE importing `mesoSPIM_MainWindow`/`Core`.** `Acquisition`
   resolves an image-writer plugin at *class-definition* time; without the registry populated,
   importing the Core raises `TypeError: 'NoneType' object is not subscriptable`. (This is exactly
   what `main()` does.)
2. **CWD must be the `mesoSPIM` package dir.** The app resolves `gui/*.ui` and `./config` with
   relative paths.
3. **Stub `mesoSPIM.src.WebcamWindow`** (it needs `PyQt5.QtMultimedia`, a relative `.ui`, and a real
   camera) and no-op `MainWindow.open_webcam_window`.
4. **Suppress startup modals by patching the methods that create them**, not by dismissing them
   after the fact:
   - `MainWindow.__init__` calls `choose_etl_config()` (a `QFileDialog`) unconditionally →
     no-op it (the ETL config is still loaded by the waveformer from `cfg.ETL_cfg_file`).
   - The startup zoom state-request emits `sig_warning('Please wait until the zoom change is
     complete')`, which `MainWindow.display_warning` turns into a `QMessageBox.warning` on the GUI
     thread → **offscreen this segfaults** (`0xC0000005`). No-op `display_warning`.
   A generic "close the active modal via a timer" approach **races the modal teardown and
   segfaults** — patch the source methods instead.

---

## Files / artifacts

- **Fix (committed):** [`server/scriptwindow_loader.py`](server/scriptwindow_loader.py),
  the `start(core)` refactor in [`server/mesospim_command_server.py`](server/mesospim_command_server.py),
  and [`tests/unit/test_scriptwindow_loader.py`](tests/unit/test_scriptwindow_loader.py).
- **Headless launcher** used for the live run: a local dev script (mirrors
  `mesoSPIM_Control.main()` offscreen and injects the loader through the real path). It hardcodes
  machine paths, so it is **not committed**; the full method is the "Reproduction" section above.
- This report: `zmart_drivers/mesospim/LIVE_BENCH_VALIDATION.md`.
- Related driver docs: [`README.md`](README.md), [`TODO.md`](TODO.md),
  [`server/PROTOCOL.md`](server/PROTOCOL.md), [`server/README.md`](server/README.md).

## TODO updates (done in this change)

- [x] **Fix the loader** — flat `scriptwindow_loader.py` importing the server module; re-ran the
      round-trip through the *unmodified* real path (5/5 pass).
- [x] Correct `README.md` §2 "Loading it" and `server/README.md` to the loader procedure.
- [x] Correct `TODO.md` — the earlier "bench-validated" note did not exercise the real Script-Window
      load and hid this bug.

Remaining (needs the physical instrument): real-hardware validation; non-Tiff image writers.
