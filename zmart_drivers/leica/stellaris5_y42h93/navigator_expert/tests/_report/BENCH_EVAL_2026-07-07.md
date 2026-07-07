# Bench evaluation — Leica Stellaris5 Navigator Expert driver

**Overall verdict: PASS-WITH-FINDINGS.** Every physical operation the driver
issued on the real instrument succeeded (limits handshake, XY/Z moves, all
reversible settings, job *selection*, backlash correction, capture + save).
The failures that appear in the CI exit codes are (a) two manifestations of the
**known** stale job-selection readback open item, (b) a **new** exporter/active-
config mismatch that made the `--exporter navigator_expert` acquire look
broken when it was not, and (c) one **new** offline test-hermeticity gap. None
of these are driver-breaking; the `backlash_correction` acquisition option is
**confirmed working end-to-end**.

## Run metadata

- **Machine**: `ZMB-Y42H93-STI8` (Windows-10-10.0.26100) — a *different* scope
  than the ZMB-LASX-PC the changes were first bench-verified on, so this run is
  the cross-machine confirmation the prompt asked for.
- **Backend**: live LAS X (real STELLARIS, operator-confirmed) — NavigatorExpert
  runtime `version=1.0.108.0`, `api_delay_ms=250`, `Microscope='DMI8'`,
  objective `HC PL APO CS2 10x/0.40 DRY`. Stage parked at `(63500, 41500) µm`,
  inside the envelope.
- **Repo**: branch `claude/smart-drivers-code-review-ky4phc` @ `aecf1a2`
  (descendant of `fa94125`; verified via `git merge-base --is-ancestor`).
- **Env / Python**: `sm-citest` conda env, **Python 3.11.15** (matches the
  prior bench run's interpreter), pytest 9.1.1, pytest-cov 7.1.0, ruff 0.15.20,
  pythonnet 3.1.0, driver `navigator_expert 6.0.0`.
- **Limits**: provisioned this session (machine had none). Adopted the notebook
  defaults via `stage_config.adopt_limits` → snapshot
  `C:\ProgramData\zmart-microscopy\leica\stellaris5_y42h93\navigator_expert\2026-07-07T07-22-31-729769Z\limits.json`.
  `functions` block carries the **new `run_procedure` key** (breaking-change
  gate satisfied); envelope `x[1000,130000] y[1000,100000] z_galvo[-200,200]
  z_wide[0,25000]` (X/Y mins are 1000, not 0). `limits: connect handshake` PASS
  on every live validator.

---

## Q1 — Overall CI result

**Offline suite:** `1009 passed / 1 failed` (1010 total), coverage **83.32%**
(gate 68%). Lint: `ruff check` clean; `ruff format --check` reports pre-existing
formatting debt (non-fatal by design).

- The single offline failure is
  `tests/hardware/test_validate_zmart_adapter.py::test_acquire_backlash_correction_through_the_controller_seam`
  — a **test-hermeticity gap**, see Finding 4. It is *not* a production defect;
  `fa94125` recorded this same suite as `1010 passed/0 failed` on ZMB-LASX-PC,
  and only a docs commit has landed since, so this is machine-state-specific.

**Live steps (7):** from `run_ci.py online --live-writes` unless noted.

| Step | Result | Evidence |
|---|---|---|
| limits: mock self-check | ✅ OK | 106 passed — fail-closed gate proven before hardware |
| passive readers (api/log/hybrid) | ✅ OK | 7/7 |
| reader parity + routed modes | ✅ OK | `SUMMARY: parity 43/43 skipped=9` (incl. reversible zoom/speed/format/pinhole) |
| zmart adapter round-trip | ❌ FAIL | 44 pass / 1 fail — `state: switched expected 'Overview' actual 'HiRes'` (stale readback, Finding 2) |
| end-to-end [api reader] | ❌ FAIL | job-select confirm reads stale `HiRes`; 50 s (2×15 s retries) |
| end-to-end [log reader] | ✅ OK | `pass=117 warn=2 fail=0` (log fails *closed* → WARN, not false FAIL) |
| end-to-end [hybrid reader] | ✅ OK | `pass=113 warn=2 fail=0` |

The read-only pass (`run_ci.py online`) was **6/7 on the first attempt** (the
parity step flaked once) and **7/7 (`RESULT: PASSED`) on immediate re-run** —
see Finding 3.

---

## Q2 — Backlash acquisition option, live: **CONFIRMED**

The `backlash_correction` option works end-to-end on real hardware. Getting a
*clean* record required the correct exporter (see Finding 1):

- The `select → backlash → capture` sequence is visible in the driver log on
  **every** attempt, e.g. `driver_log_20260707-093704.log`:
  - `SelectJob 'Overview' | OK` (job selection)
  - `MoveXY -> (63450.0, 41450.0)` then `MoveXY -> (63500.0, 41500.0)` — the
    overshoot-then-approach signature of `correct_backlash`, immediately before
    capture
  - `Acquire 'HiRes' | OK (6.797s)` — the capture itself
- The record confirms the settle field with `--exporter lasx_native_autosave`
  (`zmart_adapter_acquire_native.jsonl`, run `hardware_run_report_20260707-094731.md`):
  - `acquire: capture + save (7797ms)` **PASS**, `context: {"exporter":
    "lasx_native_autosave", "backlash_correction": true}`
  - `acquire: image files exist and are non-empty` **PASS**
  - `acquire: backlash_correction ran — expected='backlash-corrected'
    actual='backlash-corrected'` **PASS**
  - Output landed at `E:\Experiments\test\2026_07_07_09_37_09--Project\Overview001.ome.tif`
    (1 MB, 09:47:42), auto-discovered by the exporter.

The two earlier `--exporter navigator_expert` attempts failed at the export
step (`No Navigator Expert OME-TIFF files found ... scanned Z:\...\Data for
ELMI`) — that is Finding 1, **not** a backlash defect.

---

## Q3 — Reader-mode comparison (api / log / hybrid)

- **api** delivers every datum, fast: `xy 14ms`, `jobs 13ms`, `selected_job
  12ms`, `scan_status 1ms`, `hardware_info 13ms`, `job_settings 14–18ms`.
- **log** delivers `hardware_info` and `job_settings` (`source=log`, age
  ~1.0–1.6 s, ~135–155 ms) and agrees with api (`'DMI8' vs 'DMI8'`, `all
  contract fields agree`). For live `xy` / `selected_job` / `scan_status` the
  log stream is usually stale/absent and the **router fails closed** (`no
  trusted log value`) rather than returning a wrong value. It is *intermittently*
  fresh — one standalone parity run delivered the `xy` log leg (`parity 37/37
  skipped=7`) when the stream age dropped below threshold.
- **hybrid** routes per-datum correctly: log for `hardware_info`/`job_settings`,
  api for the live datums.
- **`jobs`** is **api-only by design** (`UnsupportedSource("datum 'jobs' has no
  log leg")`) — expected, not a finding.
- **Agreement:** wherever two legs both produce a value, they agree exactly
  (`agree[...] api vs hybrid` / `api vs log` all OK). There are **no value
  disagreements** — the only "differences" are the log leg being absent/stale
  and failing closed.
- **Winning leg:** api for live positional/status data; log for the
  log-derived `hardware_info`/`job_settings`; hybrid is the best default.

---

## Q4 — Confirmation health

- **Settings** confirm reliably on the api route, first try: `zoom`,
  `scan_speed`, `scan_resonant`, `sequential_mode`, `image_format`, `pinhole`
  all `att=1 conf=1`.
- **Job selection is the sole unconfirmed action, and it is systematic, not
  scattered:** on the **api** route, selecting any non-current job goes
  `UNCONFIRMED after 3 readback attempt(s)` (`~13–15 s` each) and reads back the
  *previously* selected job. Example (`driver_log_20260707-093937.log`):
  `SelectJob 'Overview' | UNCONFIRMED after 3 readback attempt(s); command was
  sent successfully, but LAS X state readback did not confirm the requested
  value (13.587s)`.
- Cluster: **one datum (job `IsSelected`), one route (api), systemic.** On the
  **log/hybrid** routes the same select degrades to a **WARN** (fails closed —
  "no trusted log value") instead of a hard FAIL, which is why those CI steps
  pass while the api-route step and the adapter round-trip fail.
- This is `reported-and-continue` by policy; it maps to the **known**
  stale-response open item (Finding 2).

---

## Q5 — Restore verification: **PASS**

Every `Mutates scope: YES` action has a matching restore, and final state
matched initial:

- Moves: `set_origin` → `set_xyz` XY/z-galvo/z-wide (frame math exact:
  `origin→0`, `xy→25`, `zgalvo→2`, `zwide` additive `→5`) → `move: restore XY +
  focus (frame 0,0,0)` PASS; live-writes 10-point XY sweep each `xy: restore →
  (63500,41500)` PASS; `z: restore → 0.0` PASS.
- Settings: every `write alternate` has a `restore` (`zoom→1`, `scan_speed→400`,
  `resonant→False`, `sequential→…`, etc.), all confirmed.
- Job: `set_state: restore` → `state: restored expected 'HiRes' actual 'HiRes'`
  PASS (and inversely `'Overview'=='Overview'` in the later run). The only
  action that does not confirm is the *mid-test switch* readback (the stale
  IsSelected), but the **restore itself confirms**, so the instrument is left as
  found.

---

## Q6 — Machine-specific observations

- **ImageTransformation = `TOPLEFT`, `enable_transform=False`** on this machine
  — *differs from ZMB-LASX-PC's `RIGHTTOP`*. This scope is canonical, so the
  pixel↔stage ROI math has no orientation surprise here.
- **Stage envelope** is sane for this stage (`x[1000,130000] y[1000,100000]`);
  the live position `(63500,41500)` sits comfortably inside and all moves stayed
  in-envelope.
- **Calibration** is the bundled default (no machine calibration adopted this
  session — only limits): `using bundled default calibration.json (calibration
  may be stale - re-calibrate)`. Expected; a calibration adopt is a separate,
  deliberate step.
- **Active save path is native AutoSave to `E:\Experiments\test`** (LCF
  `AutoSaveBaseFolder`, `DoUseAutoSave=True`); the Navigator Expert *export*
  (`media_path=Z:\...\Data for ELMI`, `auto_export=False`, all `export_formats`
  off) is disabled — see Finding 1.
- **vs ZMB-LASX-PC:** the stale job-readback (Finding 2) and the
  `--exporter navigator_expert` acquire failure both reproduce here (the
  2026-07-06 report shows the identical acquire error, scanning
  `Z:\...\Temporary_Data`), so neither is Y42H93-specific.

---

## Findings, ranked

1. **[HIGH · NEW] Exporter vs active-config mismatch — no fail-fast.**
   `acquire(--exporter navigator_expert)` scans the Navigator Expert export
   `media_path` even when `auto_export=False` (export disabled) and the scope is
   actually persisting via **native AutoSave** to a different volume
   (`E:\Experiments\test`). Result: a full ~27 s capture runs, then fails with a
   confusing `No Navigator Expert OME-TIFF files found`. The driver already
   *can* auto-discover the real location — `native_autosave_base_folder()`
   returns `E:\Experiments\test`, `native_autosave_enabled()` → True — and
   switching to `--exporter lasx_native_autosave` makes the same acquire pass.
   *Recommend:* (a) at acquire start, validate the chosen exporter against the
   live LAS X save config and **fail fast with guidance** ("navigator_expert
   export is disabled; did you mean lasx_native_autosave?"); and/or (b)
   auto-select the exporter from the active config; (c) update
   `BENCH_EVAL_PROMPT.md` Q2 to use the machine's active exporter rather than
   hardcoding `navigator_expert`.

2. **[MED · KNOWN] Stale CAM-API `IsSelected` job-selection readback.**
   Job-select confirmation is unreliable on the api route (reads the previous
   job, unconfirmed after 3 attempts / ~15 s), which fails two CI steps (zmart
   adapter round-trip, end-to-end [api]). The physical selection succeeds and
   restore confirms; only the readback lags. Maps to the known stale-response
   correlation for `get_jobs`/`get_selected_job`
   (`docs/reviews/PROGRESS_2026-07-05.md` §6;
   `project_validate_hardware_job_readback_stale`). *Recommend:* pursue the
   stale-response correlation fix; consider defaulting the select-confirmation
   route to log/hybrid (which degrade gracefully) rather than api.

3. **[LOW · KNOWN] Reader-parity startup flake.** The
   `validate_readers_side_by_side` step failed once inside `run_ci.py online`,
   then passed on immediate re-run and 4/4 standalone. Consistent with the
   transport-readiness / stale-response hazard on back-to-back connects.
   *Recommend:* a warmup ping or first-read retry at connect; track under the
   same stale-response item.

4. **[LOW · NEW] Offline test-hermeticity gap (ScanningTemplates).**
   `test_acquire_backlash_correction_through_the_controller_seam` calls
   `find_scanning_templates_dir()`, which reads the machine's **real**
   `%APPDATA%\...\MatrixScreener6\User_0\ScanningTemplates`. That dir is not
   redirected by the hermetic mock fixture (unlike `LOG_READER`/machine-config).
   With a populated template loaded, `_ensure_scan_fields_stripped` attempts a
   strip, which calls `client.PyApiSaveExperiment` — absent on the shared
   `MockLasxClient` — raising "could not strip the scanning template before
   acquiring". Same class as `fa94125` bug #3, not yet closed for the templates
   path. Test-only; production uses the real client. *Recommend:* redirect the
   templates dir to the throwaway root in `hermetic_mock_machine_root()`, or add
   a `PyApiSaveExperiment` stub to `MockLasxClient`, or have the test patch the
   strip / pass `strip_scan_fields=False`.

5. **[INFO]** `ruff format --check` debt (non-fatal); calibration not adopted
   (bundled default in use, by design).

## What was run

- `python run_ci.py` (offline) — 1009/1 fail, cov 83.32%.
- `python run_ci.py online` ×2 — 6/7 then 7/7 PASSED.
- `python run_ci.py online --live-writes` — reports `hardware_run_report_20260707-0933*.md`.
- `validate_zmart_adapter.py --allow-acquire --exporter navigator_expert` ×2 —
  export-step FAIL (Finding 1); driver logs `-093704`, `-093937`.
- `validate_zmart_adapter.py --allow-acquire --exporter lasx_native_autosave` —
  acquire PASS, `settle == 'backlash-corrected'`; report `-094731`.

_Safety: no limits edited; all moves ≤±25 µm XY / ±2/3 µm Z inside the
envelope and restored; nothing killed mid-capture; operator authorized the
stage motion and the real acquire in-session._
