# navigator_expert — Leica LAS X (STELLARIS) microscope driver

`navigator_expert` drives a **Leica STELLARIS** confocal from Python through the **LAS X Python
(CAM) API**. It is the Leica driver behind the ZMART controller, and every live command routes
through a two-layer dispatch backbone that handles idle-wait, transient-error retry, readback
confirmation, and structured timing/logging. The public API is **synchronous**, so operator
notebooks keep the thin 1–3-line invocation style used across the ZMART drivers.

- **Author:** Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com
- **License:** see the repository root [`LICENSE`](../../../../LICENSE).
- **Status:** **Production-tested** — validated on the LAS X simulator and a real STELLARIS.

## Contents

1. [About the LAS X CAM API](#1-about-the-las-x-cam-api)
2. [Requirements & installation](#2-requirements--installation)
3. [Configuration](#3-configuration)
4. [Quick start](#4-quick-start)
5. [Core concepts](#5-core-concepts)
6. [API reference](#6-api-reference)
7. [Architecture](#7-architecture)
8. [Configuration & tuning (profiles)](#8-configuration--tuning-profiles)
9. [Testing](#9-testing)
10. [Invariants & gotchas](#10-invariants--gotchas)
11. [Extending the driver](#11-extending-the-driver)
12. [References](#12-references)

---

## 1. About the LAS X CAM API

Leica LAS X exposes automation through a **Python (CAM) API** delivered as **.NET assemblies** that
this driver loads **in-process** via `pythonnet`. Commands are issued by writing an API model and
calling `UpdateAwaitReceipt`/`UpdateAsync`; an **echo model** (`PyApiCommandEcho`) reports errors.
State is read back through the CAM API and, as a hang-proof fallback, by tailing LAS X log files.

This is the **vendor-specific** layer: it knows LAS X enum names, log paths, the `.lrp`/`.rgn`/`.xml`
scan-field template formats, and OME exports. It runs **on the LAS X PC** (the API is in-process and
blocking — unlike the gRPC/socket ZMART drivers). Keep LAS X-specific assumptions inside this package.

## 2. Requirements & installation

Live control requires **LAS X installed** on the acquisition PC, with the Navigator Expert add-in
directory that contains the CAM assemblies. Offline work (parsing, template edits, tests) needs no
LAS X.

- **Python 3.10–3.12**, `pythonnet` (loads the .NET CAM assemblies). Offline dev/test deps:
  `pip install -r zmart_drivers/leica/stellaris5_y42h93/navigator_expert/requirements-dev.txt`.
- **Import the package** (put the machine dir on `sys.path`):
  ```python
  import sys
  from pathlib import Path
  sys.path.insert(0, str(Path("zmart_drivers/leica/stellaris5_y42h93").resolve()))

  import navigator_expert as lasx                       # namespace import
  from navigator_expert import connect_python_client, set_zoom, acquire, save
  ```
  The package self-bootstraps the repo root onto `sys.path` so `shared.output_layout` (used by
  `save()`) resolves.

### Machine paths this driver assumes

| Purpose | Path (default) |
|---|---|
| CAM API command log | `C:\ProgramData\Leica Microsystems\LAS X\lcsCommand.log` |
| LAS X dialog / MessageBox log | `C:\ProgramData\Leica Microsystems\LAS X\MatrixScreener.log` |
| CAM API assemblies (runtime) | `C:\Program Files\Leica Microsystems CMS GmbH\LAS X\AddIns\NavigatorExpert` |
| Scan-field templates | `%APPDATA%\Leica Microsystems\LAS X\MatrixScreener6\User_*\ScanningTemplates` |

Defaults live in `config/profiles.py` (`LogReaderProfile`, `LasxApiProfile`) and are discovered at
runtime where possible. Override via the profile, not at call sites.

## 3. Configuration

- **Connection** — `LasxApiProfile` (`config/profiles.py`): `runtime_root` (the add-in dir) and
  `delay_ms` (Leica's client-side pacing knob `DelayInMilliseconds`, default 250 ms).
- **Log reader** — `LogReaderProfile`: the `lcsCommand.log` / `MatrixScreener.log` paths + freshness windows.
- **Machine-local calibration & limits** — `config/machine.py` resolves the instrument's calibration
  (image↔stage matrix, per-objective translation), stage limits, orientation, and origin from a
  **machine-local ProgramData snapshot** (out of the repo). The repo ships defaults only. If
  ProgramData is empty, those defaults are copied into the first local snapshot so runtime reads still
  use ProgramData paths. Each snapshot holds `limits.json`, `calibration.json` or
  `calibrations/<name>/calibration.json`, and `orientation.json`. The **origin** is not snapshot
  state: it is ephemeral operator state, so it lives in its own `origin/` folder next to the
  snapshots and is **session-scoped** (see §5). The notebooks publish measured replacements by
  copying the latest snapshot forward and changing only their part. The single `limits.json` is
  function-keyed (`constraints` = the `stage.*` envelope + `functions` = the gate policy; no
  `backlash` block — backlash is a motion utility with baked-in defaults, §2b).
- **The driver loads the configs at connect** — `connect_microscope(...)` (`connection/session.py`)
  is the driver's own front door. It opens the CAM client and then loads this microscope's three
  machine-local configs — the **stage limits**, the **orientation**, and the **calibration** — so the
  whole session works from one consistent picture. The zmart adapter's `connect()` simply delegates to
  it. Each config can be skipped with `load_limits` / `load_orientation` / `load_calibration` (all
  default `True`; see §5 for what skipping one means). This is a deliberate ladder: the limits notebook
  is bounded only by the physical backstop, `set_orientation` is bounded by limits, and
  `calibrate_objective_pair` is bounded by limits and expects a measured orientation.
- **Limits handshake** — `connect_limits_handshake(client)` (run by `connect_microscope`;
  workflows/validators/notebooks call it directly). It resolves the ProgramData `limits.json` (seeding
  defaults there first when needed), validates it (schema, finite numbers only, min ≤ max, its
  `constraints`/`functions`, envelope **within the hardcoded physical backstop**
  `motion.limits.STAGE_BACKSTOP_UM`), applies the stage envelope, and installs the function-keyed gate
  for that client. **If the machine file is invalid (or loading is switched off), the session does not
  go dead — it falls back to the bundled default envelope** (loudly warned, marked a fallback). The
  defaults sit within the physical backstop, and the backstop bounds every move regardless, so an
  over-wide or corrupt file can never authorise a move the defaults forbid. The only fully fail-closed
  state is a client that never handshook at all (every mutating command then refuses, naming the
  notebook). Manual `set_stage_limits(...)` still adjusts the in-memory envelope, but it does not open
  the gate — only a successful handshake does.
- **Function-keyed limits (fail-closed gate, commands layer)** — `commands/gate.py`. Every mutating
  command wrapper (`set_*`, `move_*`, `acquire`, `select_job`, plus `save_experiment` /
  `load_experiment`) declares one key in `gate.MUTATING_COMMANDS` and checks it **before the native
  call fires** — nothing built on top (adapter, controller, workflows, notebooks) can bypass it.
  The machine-local `limits.json` (its `functions` block) must carry an entry for every key (`null` =
  reviewed-and-unlimited; an **absent** key makes the file invalid, which triggers the defaults
  fallback above rather than shipping a silently-ungated op). If a move/acquire is refusing, read the
  refusal message: it says exactly which envelope is in force and, when relevant, how to publish
  measured limits.

## 4. Quick start

```python
from navigator_expert import (
    connect_python_client, ping,
    connect_limits_handshake, select_job, set_zoom, set_scan_speed,
    move_xy, acquire, save,
)
from shared.output_layout import Naming, run_hash

# 1. Connect and validate the scope
client = connect_python_client()
assert ping(client)

# 2. Limits handshake (REQUIRED before any mutating command): resolves and
#    validates the ProgramData limits.json, seeding repo defaults there first
#    when needed, then installs the fail-closed gate for this client.
state = connect_limits_handshake(client)
assert state.ok, state.error   # points at limits/notebooks/set_stage_limits.ipynb

# 3. Select and configure a job (live commands return a result dict)
select_job(client, "MyExperiment")
r = set_zoom(client, "MyExperiment", 2.0)
assert r["success"] and r["confirmed"], r["message"]     # check BOTH — see §5
set_scan_speed(client, "MyExperiment", 600)

# 4. Move and acquire
move_xy(client, 65_000, 65_000, unit="um")
acq = acquire(client, "MyExperiment")                     # -> AcquisitionResult (RAISES on failure)

# 5. Persist to the lab-wide layout (a separate step from acquire)
naming = Naming(acquisition_type="overview", hash6=run_hash())
saved = save(client, acq, output_root="D:/runs/demo", naming=naming)
print(saved.image_paths)                                  # {PlaneIndex(t,z,c): Path, ...}
```

> `acquire()` returns an `AcquisitionResult` dataclass and **raises** on failure — it is *not* a
> `{"success": ...}` dict. Saving is a deliberate second step (see §6).

> The explicit `output_root` above is for the low-level driver API. Through
> `zmart_controller`, the Leica adapter discovers the run root from LAS X native
> AutoSave via `run_procedure({"name": "get_root"})`; operator workflows should
> use that discovered root instead of hard-coding a drive path.

> No machine config yet? The first connect seeds ProgramData from the repo defaults so CI and local
> mock runs work. On the rig, run `limits/notebooks/set_stage_limits.ipynb`,
> `orientation/notebooks/set_orientation.ipynb`, and the calibration notebook to replace those defaults
> with measured values. If a machine file is invalid, the session falls back to the bundled default
> envelope (loudly) rather than refusing — fix the file the warning names and reconnect.

## 5. Core concepts

**The client.** `connect_microscope(...)` is the normal entry point: it opens the CAM client and
loads this microscope's three machine-local configs (limits, orientation, calibration), so the whole
session works from one consistent picture; `connect_python_client()` is the lower-level primitive that
only opens and pings the client (the setup notebooks use it, since they load just the one config they
need). Every command/reader takes the returned `client` as its first argument. The CAM client has no
disconnect counterpart — it lives for the process; there is nothing to close when a session ends.

**Which configs to load.** `connect_microscope(load_limits=…, load_orientation=…, load_calibration=…)`
(all default `True`) chooses what a connection loads. Skipping one has a defined, safe meaning:
`load_limits=False` governs the session with the bundled **default** envelope (never ungated; the
physical backstop still holds); `load_orientation=False` saves images unrotated; `load_calibration=False`
refuses cross-objective moves rather than computing uncompensated ones.

**The origin is session-scoped.** `set_origin` makes the current position the frame zero — from then
until it is set again or the session ends. It is written to the machine-local `origin/` folder as a
record, but the driver does **not** restore it at connect: a fresh connection is an absolute frame
until `set_origin` runs. (An earlier version restored the last origin across sessions; it no longer
does.)

**Live vs. file.** `set_zoom(...)` talks to the running scope and confirms by reading hardware back;
`lrp_set_zoom(...)` edits a `.lrp` template *file* (nothing happens on the scope until LAS X reloads
it). There is a deliberate parallel API for each — don't mix them (see §6).

**Command vs. read.** Commands *change* state through the dispatch backbone; reads *observe* state
through `readers`. Reads that gate control flow or become persisted truth have a stricter rule (below).

**The result dictionary.** Every live command returns a stable envelope:

| Key | Meaning |
|---|---|
| `success` | Command accepted/applied (transport ok, no permanent API error). |
| `confirmed` | Readback matched the target (`True`/`False`); `None` if no confirmation ran. |
| `message` | Human-readable summary. |
| `timing` | `{pre_check_s, setup_s, fire_s, check_s, confirm_s, total_s, attempts, confirm_attempts, method}`. |
| `logs` | Ordered `{ts, level, msg}` trace. |
| *(command-specific)* | e.g. `position` (`move_xy`). |

**`success` vs. `confirmed` — read both.** `success=True, confirmed=False` means LAS X accepted the
command but readback didn't confirm the value within the windows (most `set_*` use
`success_on_unconfirmed=True` so a workflow can continue, with the mismatch in `logs`). **Don't treat
`success` alone as "applied"** for setting commands. `success=False` means it failed to fire (transport,
permanent error, failed pre-check) and `confirmed` is `None`.

**Error classification** (`commands/errors.py`): messages are matched **permanent-first**
(`out of range`, `is invalid`, `not implemented`, …) then **transient** (`being scanned`, `busy`,
`timeout`, …); unknown → permanent (conservative). Transient errors retry up to `max_retries`.

**Reading state — api / log / hybrid** (`readers/`, chosen per datum by `StateReaderProfile`;
default `hybrid` for all routed datums): `api` (one CAM read in a capped worker thread), `log`
(parse LAS X logs — never blocks the CAM API, can be stale), `hybrid` (race them, first
*admissible* evidence wins — the legs' staleness profiles are complementary, so one usually delivers). **Freshness rule:** a fresh-by-age
*log* value must never decide whether a command fires, how it is parameterized, whether it confirms,
or what metadata/calibration is persisted — those must use the API leg. The CAM API can hang; the log
mirror is the hang-proof fallback.

**Units.** Public API *inputs* are micrometers (`unit="um"`/`"mm"`/`"m"` where accepted). Returned
positions are mixed: `get_xy` and `move_xy`'s `position` carry raw meters under bare `x`/`y` —
use the `*_um` keys.

**Common per-call overrides** (`None` = use the profile): `max_retries` (transient-retry ceiling),
`pre_check_timeout` (idle-wait when the profile pre-checks), `tolerance` (readback tolerance, numeric
commands).

**Logging:** `logging.getLogger("navigator_expert").setLevel(logging.DEBUG)` — the same trace also
travels in each result's `logs`.

## 6. API reference

All setting commands take `(client, job_name, ...)` and return the result dict of §5.

### Connection
```python
connect_python_client(client_name="PythonClient", api_delay_ms=None) -> client
ping(client) -> bool
```

### State readers

The routed readers return a value or `None` (never raise) and accept `diagnostics=True` for a
source-tagged `Reading` (value + `source` + `observed_at`) plus `mode="api"|"log"|"hybrid"` to
override the profile backend. Exceptions: `ping` and `get_lasx_settings` take exactly the calls
shown; `read_zwide_um` takes only `(client, job_name, *, mode=None)` — no `diagnostics` — and
**can raise** (`RuntimeError`/`ValueError`) when job settings are readable but incomplete or
schema-mismatched (it returns `None` only when the settings cannot be read at all).

| Function | Call | Returns |
|---|---|---|
| `ping` | `(client)` | `bool` |
| `get_scan_status` | `(client, mode=None)` | status string (e.g. `"eIdle"`) |
| `get_xy` | `(client, mode=None)` | `{"x","y","x_um","y_um"}` |
| `read_zwide_um` | `(client, job_name, mode=None)` | `float` (µm); can raise — see above |
| `get_jobs` | `(client, ...)` | list of job dicts |
| `get_job_by_name` | `(client, job_name, ...)` | job dict |
| `get_selected_job` | `(client, ...)` | selected job dict |
| `get_job_settings` | `(client, job_name, ...)` | raw settings dict |
| `get_hardware_info` | `(client, ...)` | hardware dict |
| `get_fov` / `get_base_fov` | `(client, ...)` | field-of-view info |
| `get_lasx_settings` | `()` | LAS X advanced settings (orientation, …) |
| `get_pending_dialog` | `(*, diagnostics=False)` — no client; log-only | open LAS X dialog text, if any |

### Setting commands — reference

All take `(client, job_name, …)` and return the result dict of §5; `tolerance` overrides the default.
Per-setting commands (below the rule) also take a `setting_index` targeting a specific sequential setting.

| Function | Key parameters | Tolerance / notes |
|---|---|---|
| `set_zoom` | `value` | 0.1 (factor) |
| `set_scan_speed` | `value` | integer speed |
| `set_scan_resonant` | `enable` | `True`/`False` |
| `set_scan_mode` | `mode` | e.g. `"xyz"`, `"xzy"` |
| `set_sequential_mode` | `mode` | `"Line"`/`"Frame"`/`"Stack"` |
| `set_scan_field_rotation` | `angle` | 0.5° |
| `set_image_format` | `format_str` | `"512 x 512"` or `(512, 512)` |
| `set_objective` | `hw_info`, one of `slot_index=`/`name=`/`magnification=` | needs `get_hardware_info()` |
| `set_z_stack_definition` | `begin_um=`, `end_um=` (`old_begin_um=`, `old_end_um=`) | 1.0 µm |
| `set_z_stack_step_size` | `step_size_um` | 0.5 µm |
| `set_z_stack_size` | `size_um` | 1.5 µm |
| — *per-setting (take `setting_index`)* — | | |
| `set_frame_accumulation` | `setting_index, value` | exact match |
| `set_frame_average` | `setting_index, value` | exact match |
| `set_line_accumulation` | `setting_index, value` | exact match |
| `set_line_average` | `setting_index, value` | exact match |
| `set_pinhole_airy` | `setting_index, value` | 0.05 AU |
| `set_detector_gain` | `setting_index, beam_route, value` | 1.0 |
| `set_laser_intensity` | `setting_index, beam_route, line_index, value` | 0.005 (0–1) |
| `set_laser_shutter` | `setting_index, beam_route, activate` | `True` = open |
| `set_filter_wheel_slot` | `setting_index, beam_route, filter_wheel_type, slot_index` | exact match |
| `set_filter_wheel_spectrum` | `setting_index, beam_route, filter_wheel_type, position` | 1 nm |

### Settings model
`make_changeable_copy(get_job_settings(client, job))` (`commands/settings.py`) normalizes raw job
settings into the flat, stable dict the `_confirm_*` functions read back against: `zoom`, `scanSpeed`,
`scanMode`, `stack`, `zPosition`, and `activeSettings[...]` (with `activeDetectors`, `activeLaserLines`,
`filterWheels`). Underscore-prefixed keys (`_beamRoute`, `_lineIndex`, `_index`, `_name`) are
driver-added aliases for stable access.

### Stage & motion
```python
move_xy(client, x, y, unit="um", *, max_retries=None, pre_check_timeout=None, tolerance=None) -> dict  # tol 20 µm; result has "position"
move_z(client, job_name, z, unit="um", z_mode="galvo", ...) -> dict                                     # z_mode "galvo"|"zwide"; tol 1 µm
move_galvo_to_pixel(client, px, py, ...) -> dict                                                        # pan galvo to a pixel (no stage move)
set_stage_limits(*, x_min, x_max, y_min, y_max, z_galvo_min, z_galvo_max, z_wide_min, z_wide_max) -> None
get_stage_limits() -> dict ; apply_stage_limits_from_config(stage_cfg) -> None
```

### Acquisition & job selection
```python
select_job(client, job_name, poll_timeout=None, poll_interval=None) -> dict     # confirm defaults to hybrid
acquire(client, job, *, poll_interval=None, poll_timeout=None, heartbeat_interval=None,
        start_timeout=None, pre_check_timeout=None) -> AcquisitionResult          # RAISES on failure
save(client, acq, output_root, naming, *, lineage=None, fix_ome=True,
     cleanup_source=False) -> SavedAcquisition                                    # image_paths / xml_paths / naming
```
`save()` collects LAS X native AutoSave output into a neutral product,
and writes canonical single-plane OME-TIFFs into the `shared.output_layout` tree, with OME-XML embedded
in each image file.
**OME metadata:** `acquisition/ome.py` repairs known Leica OME violations (e.g. laser `Wavelength="0"`)
in place, preserving byte formatting; `acquisition/ome_canonical.py` writes clean canonical ZMART OME;
`save(..., fix_ome=True)` validates/repairs each written file.

**Acquiring empties the scanning template by default.** Through the zmart adapter, every `acquire()`
(and the autofocus procedure) applies the `strip_scan_fields` acquisition option: operator-drawn scan
fields, regions, and focus points vanish from LAS X. The strip is sidecar-backed — restore with
`restore_template` — but read stored positions through the zmart procedures (`get_positions`,
`get_focus_points`) *before* the first acquire, or pass `options={"strip_scan_fields": False}`.

**`Naming` constraints and slot overwrites.** Name parts (`acquisition_type` etc.) must be
kebab-case lowercase (`"overview"`, `"target-scan"`); `Naming` raises `ValueError` on `"Prescan"` or
`"target_scan"` — and on the adapter path that raise happens **after the scan has fired**, so the
capture is wasted. Validate names before acquiring. A numeric `position_label` claims that `p` slot
directly and **overwrites** any previous output saved at the same slot (upsert); non-numeric labels
take the next unused slot and appear only in the lineage record, never the filename.

### Templates / scan-fields (offline-capable)

**Parse saved templates** (read-only, stdlib ElementTree — no fragile regex; `scanfields/parsers.py`,
except `parse_lrp` in `scanfields/lrp.py`):
`parse_lrp` (full job-settings tree) · `parse_scan_positions` · `parse_acquisition_positions` ·
`parse_base_grid` · `parse_focus_points` · `parse_rgn_geometries` · `parse_rgn_tile_colors` ·
`parse_matrix_settings` · `plan_tiles_from_geometries` (planning).

**Active experiment:** `save_experiment` (fires save, confirms via file mtime + stable size) ·
`load_experiment` (receipt only — verify with a follow-up save) · `save_and_read_lrp` (save +
`parse_lrp` in one call) · `get_template_state` (`"fresh"`/`"unstripped"`/`"stripped"`/`"unreadable"`
— the adapter treats `"unreadable"` as a hard pre-acquire error) ·
`find_scanning_templates_dir` · `strip_template` / `restore_template` / `strip_template_in_place`
(remove/restore operator-drawn scan fields, regions, focus points around an automated run).

**Offline template edits** (`experimental/lrp_edits/`) — a **parallel, file-based** API mirroring the
live `set_*` commands (`lrp_set_zoom` vs `set_zoom`, …), since file editing has no readback. Route
every edit through `apply_lrp_change(...)` (**save → edit → reorder → load → save → verify**;
`reorder_jobs` keeps the active job selected). It also provides ROI authoring — `make_rectangle` /
`make_ellipse` / `make_polygon`, `lrp_add_roi`, `lrp_clear_rois` — and pixel↔stage↔pan/zoom coordinate
math — `mask_contour_to_roi`, `roi_translation_to_pan`, `galvo_pan_for_pixel` (see the
coordinate-frame docstring atop `experimental/lrp_edits/roi.py`). Despite the `experimental/` name this
code is **load-bearing** (used by `move_galvo_to_pixel`, `disable_roi_scan`, `reset_pan`) — read it as
"offline template editor", not "unstable".

## 7. Architecture

```
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/
├── connection/   lasx_runtime.py (load .NET CAM assemblies) · session.py (connect_python_client / connect_microscope) · session_state.py (per-connection orientation + calibration)
├── commands/     dispatch.py (the backbone) · errors.py · prechecks.py · confirmations.py ·
│                 settings.py · objectives.py · commands.py (set_*/move_*/acquire/select_job)
├── readers/      router.py (api/log/hybrid) · api_reader.py · log_reader.py · capabilities.py · derived.py
├── config/       profiles.py (CommandProfile + per-command instances, LasxApi/LogReader profiles) · machine.py
├── motion/       limits.py (µm safety envelope) · movement.py (backlash) · stage_config.py
├── acquisition/  product.py (neutral types) · capture.py (acquire) · save.py (persistence) · ome.py
├── scanfields/   .lrp/.rgn/.xml parsing + templates    experimental/lrp_edits/  offline template editors
├── calibration/  objective-pair calibration (data machine-local; defaults/ + notebooks/ inside)
├── limits/       stage/function limits defaults + setup notebook; runtime truth is ProgramData
├── orientation/  camera↔stage quarter-turn, applied at save; measured by set_orientation, stored in the machine snapshot next to calibration + limits
├── zmart_adapter/  ops table plugging this driver into zmart_controller (import to register)
├── tests/        unit/ (offline) + hardware/ (validate_*.py live scripts + mock-backed test_* gates)
└── run_ci.py · pytest.ini   (package root)
```

**Two-layer dispatch backbone** (`commands/dispatch.py` → `confirm_and_fire`):

```
confirm_and_fire (outer)
 ├─ _fire_block (inner, ≤ max_retries+1): pre_check → setup(model) → fire (UpdateAwaitReceipt/Async)
 │                                        → error_check (echo) → retry on transient
 └─ confirm_fn (readback) → on unconfirmed (≤ max_confirm_attempts): idle-correct + re-fire → re-confirm
```
The backbone is deliberately *dumb*: it owns pipeline order, retry ceilings, and timing, and knows
nothing about zoom/objectives/stages. Commands supply small zero-arg callables (extra params pre-bound
with `functools.partial`).

**Dependency direction:** `utils` (stdlib) → `commands.errors/settings/prechecks/confirmations` →
`commands.dispatch` → `config.profiles` → `commands.commands`; `readers.*`, `motion.*`, `scanfields.*`,
`acquisition.*` sit above the CAM readback. No circular imports.

## 8. Configuration & tuning (profiles)

Every command has a frozen `CommandProfile` in `config/profiles.py` — its complete recipe (pluggable
callables + retry/confirm tuning). Tuning a command = editing its profile; nothing else changes.

```python
@dataclass(frozen=True)
class CommandProfile:
    pre_check_fn=None ; error_check_fn=_default_error_check ; confirm_fn=None
    max_retries=3 ; max_confirm_attempts=3 ; refire_on_unconfirmed=True
    confirm_poll_s=CONFIRM_POLL_S ; confirm_tolerance=None
    success_on_unconfirmed=True                # exhausted readback -> unconfirmed, never hard-fail
    # + poll/heartbeat/backoff/receipt/async knobs
```

Posture is uniform: retry the fire, re-fire between confirm windows, return *unconfirmed* rather than
hard-failing. `ACQUIRE` is the sole deviation (`max_retries=0`, `refire_on_unconfirmed=False`) — it
must never re-send or it would start a duplicate acquisition.

**Default tolerances** (override per call via `tolerance=`):

| Command | Tol | Unit | | Command | Tol | Unit |
|---|---|---|---|---|---|---|
| `set_zoom` | 0.1 | factor | | `set_pinhole_airy` | 0.05 | AU |
| `set_scan_field_rotation` | 0.5 | deg | | `set_detector_gain` | 1.0 | gain |
| `set_z_stack_definition` | 1.0 | µm | | `set_laser_intensity` | 0.005 | frac |
| `set_z_stack_step_size` | 0.5 | µm | | `set_filter_wheel_spectrum` | 1 | nm |
| `set_z_stack_size` | 1.5 | µm | | `move_xy` | 20.0 | µm |
| | | | | `move_z` | 1.0 | µm |

## 9. Testing

```powershell
# Offline suite (no microscope, no LAS X)
python -m pip install -r zmart_drivers/leica/stellaris5_y42h93/navigator_expert/requirements-dev.txt
python -m pytest -q zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/unit
python -m pytest -q zmart_drivers/leica/stellaris5_y42h93/navigator_expert/calibration/tests

# Self-contained gates
python zmart_drivers/leica/stellaris5_y42h93/navigator_expert/run_ci.py             # mock/offline (default)
python zmart_drivers/leica/stellaris5_y42h93/navigator_expert/run_ci.py --mock      # explicit mock/offline
python zmart_drivers/leica/stellaris5_y42h93/navigator_expert/run_ci.py --hardware  # live LAS X validators + acquire smoke
```

`tests/unit/` is offline against committed synthetic fixtures (template parsing, strip/restore,
position parsers, stage/limits, log & state readers, acquisition, runtime loading). Follow the project
TDD practice: add a failing offline test first, and assert real values, not just shapes.

**Live hardware validation** (requires a live LAS X — simulator or scope) runs through the
`validate_*.py` *scripts* in `tests/hardware/`, invoked directly or via `run_ci.py --hardware` —
not through pytest. Everything pytest collects is mock-backed and offline, including the
`test_*.py` files in `tests/hardware/`, which drive the same validators against
`MockLasxClient`. (The `hardware`/`slow` markers registered in `pytest.ini` are used by zero
tests today; the mock/hardware split is file-based, not marker-based.) Direct hardware-moving
validator sections run only with their `--allow-*` flags:

```powershell
python -m pytest -q zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware   # offline mock gates
python zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware/validate_hardware.py --yes --allow-xy --allow-z --allow-objective --allow-acquire --state-reader-mode hybrid
```
Validator JSONL outputs are runtime artifacts, ignored by default. Every validator run also
writes a **Markdown run report** (`hardware_run_report_<timestamp>.md`, in `tests/_report/` when
launched via run_ci) listing every attempted instrument change — including failures and
restores — with confirmation status and timing. **Bench-run instructions** (prerequisites, what
`--hardware` changes on the scope, expected duration, report locations) live in
[`tests/hardware/README.md`](tests/hardware/README.md).

## 10. Invariants & gotchas

These **silently misbehave** instead of failing loudly — respect them or results are wrong without an error:

1. **Movement needs a limits handshake** — a client that never handshook refuses `move_xy`/`move_z`
   fail-closed. Through `connect_microscope` (and the adapter) the handshake always runs, falling back
   to the bundled default envelope if the machine file is invalid, so a connected session can always
   move within the defaults; the physical backstop bounds every move regardless.
2. **`acquire()` returns an `AcquisitionResult` and raises on failure** — not a dict; read timing via
   `acq.command_result["timing"]`. Persisting is a separate `save()` call.
3. **For setting commands, check `confirmed`, not just `success`** — most `set_*` return
   `success=True, confirmed=False` when readback never matched (mismatch is in `logs`).
4. **Reads that gate control flow or get persisted must use the API leg** — never let a fresh-by-age
   log value decide whether a command fires or what metadata/calibration is written.
5. **The CAM API can hang** — that's why `readers` has a log mirror and an in-flight API-read cap.
6. **`select_job` confirmation defaults to `hybrid`** — a stale API readback can report the wrong job
   after a switch; the hybrid race only accepts evidence of an actual transition.
7. **Objective changes are best-effort** — a manual turret may pop a "turn the turret manually" dialog
   (surfaced in `MatrixScreener.log` / `get_pending_dialog`); prefer binding the objective via the job.
8. **`PyApiAcquireJob` silently no-ops without `m.JobName`** — returns in ~0 s with no error; the driver
   sets it in the command's `setup_fn`. Check the setup callback before assuming a LAS X bug.
9. **Edit templates only through `apply_lrp_change`** — a raw `.lrp` edit won't take effect and can
   select the wrong job after reload.
10. **`load_experiment` confirms only the receipt, not on-disk state** — follow with `save_experiment`
    (or use `apply_lrp_change`, which does).
11. **Adapter mutating ops are gated by `limits.json` (its `functions` block)** — if the machine file
    fails to load/validate at connect, the session falls back to the bundled **default** envelope
    (loudly warned) rather than refusing everything; the connect-time warning names what happened
    (see §3). Out-of-envelope moves still refuse at the commands layer, below the adapter.
12. **The origin is session-scoped, not restored at connect** — after connecting, the frame is
    absolute stage coordinates until `set_origin` runs. It persists to the machine-local `origin/`
    folder only as a record (see §5).

## 11. Extending the driver

Adding a command touches four places, following the pattern every existing command uses:

1. **Confirm function** (`commands/confirmations.py`) — `_confirm_X(client, ...) -> {"success", "logs"}`
   (skip if no readback is possible).
2. **CommandProfile** (`config/profiles.py`) — `MY_PARAM = _leica_setting_profile(_confirm_my_param)`.
3. **Command wrapper** (`commands/commands.py`) — three phases (pre-checks → `_dispatch(...)` with the
   profile + a `setup_fn` and target-bound `confirm_fn` → post-process). `_dispatch` handles
   client-binding, profile defaults, and the `confirm_and_fire` call.
4. **Export** (`__init__.py`) — add to `__all__` and import it.

Copy the closest existing command of a similar shape.

## 12. References
- ZMART controller (the vendor-agnostic surface this driver registers with): [`zmart_controller/`](../../../../zmart_controller/README.md)
- Sibling drivers: [`zmart_drivers/zeiss/zenapi/`](../../../zeiss/zenapi/README.md) (gRPC), [`zmart_drivers/nikon/`](../../../nikon/README.md) (socket macro)
- Output layout used by `save()`: [`shared/output_layout/`](../../../../shared/output_layout/README.md)
