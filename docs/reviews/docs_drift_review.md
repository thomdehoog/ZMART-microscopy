# Docs & Drift Audit — ZMART Controller + Leica `navigator_expert` (rev 2)

- **Scope:** (1) `zmart_controller/` in full — `README.md`, all docstrings (`__init__.py`, `layer.py`, `registry.py`, `tests/mock_driver.py`), `example_experiment.ipynb`, `example_leica_experiment.ipynb`. (2) `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` — `README.md`, `calibration/README.md`, behavioral docstrings (`zmart_adapter/`, `utils.py`, `motion/*`, `connection/session.py`, `commands/*`, `readers/*`, `config/machine.py`, `scanfields/files.py`), `limits/notebooks/set_stage_limits.ipynb`, `requirements-dev.txt` claims, `pytest.ini` / `run_ci.py` comments. (3) Repo-root `README.md`, `getting_started/README.md`, and the `docs/` sections describing the controller or the Leica driver (`docs/ZMART.md`, `docs/design/objective-aware-frame.md`).
- **Date:** 2026-07-03 · **Commit:** `c7964dd` (working tree differs only by `docs/reviews/*.md`; every audited code and doc file is at this commit). **(rev 2 — independent rerun, then merged with rev 1.)**
- **Method:** every testable claim was extracted and checked against code. Runnable material was **executed against the mock driver / offline package — never hardware**: the controller README walkthrough end-to-end, both controller notebooks' registration/state flow, the driver README §4 quick-start imports and every §6 signature (via `inspect.signature`), `Naming`/`run_hash` (including the kebab-case rejection), the `set_stage_limits` notebook's `adopt_limits` path under a hermetic `SMART_MICROSCOPY_ROOT`, `pytest -m hardware --collect-only`, and all three documented test invocations (controller 35 passed; driver `tests/unit` 620 passed + 2 env-skips; `calibration/tests` 19 passed + 1 env-skip). Prior component reviews were used only as leads; every claim below was re-verified directly.

---

## 1. Executive summary

**Verdict: the reference material is trustworthy; the on-ramps are not.** The Leica driver README's API reference is remarkably accurate — every §6 signature (20+ `set_*`/`move_*`/`acquire`/`select_job` functions), every §8 tolerance (0.1 zoom … 20 µm `move_xy`; `ACQUIRE` the sole `max_retries=0` deviation), the §5 result envelope and timing keys (`utils._make_timing`), the error-classification story (`commands/errors.py`, permanent-first, unknown→permanent), `select_job`'s hybrid confirm default, the machine-path table, `run_ci.py`'s modes/flags/report paths, every `requirements-dev.txt` traced-dependency comment, and every referenced file/dir/notebook were verified correct at this commit. `config/machine.py`'s snapshot-resolution docstring and `calibration/README.md`'s snapshot/publish description match the code, and the bundled defaults are, as claimed, real values rather than identity placeholders.

The drift clusters exactly where a **new user starts**:

1. The controller's flagship notebook (`example_experiment.ipynb`) crashes at step 2 on a stale state vocabulary, while two READMEs advertise it as the runnable offline reference (DD-02, verified by execution).
2. The controller package docstring teaches a multi-microscope recipe that disconnects the first microscope (DD-01, verified by execution).
3. The driver README documents an orientation safety gate that **no code path calls** — including the controller notebook that moves and acquires — and that fails open on unreadable settings (DD-03).
4. `movement.py` docstrings promise calibrated backlash parameters the production caller never passes (DD-04).
5. Five pieces of genuinely load-bearing behavior — previous-session teardown, persisted-origin restore, the fail-closed function-limits gate, default scan-field stripping, `Naming` label/overwrite semantics — are documented thinly or not at all on the surfaces users actually read (DD-01, DD-08, DD-15, DD-16, DD-17; collected as the "top 5" list after the findings).

The controller README's step-by-step walkthrough is internally inconsistent: step 1 shows a (stale) *Leica* connection dict, while steps 3–7 demonstrate *mock-only* actuators, options, and context keys that raise on the Leica driver (DD-05, DD-09, DD-19). Cross-doc, the same contract is described three ways: the controller promises "origin = current position at connect" and "read-only context"; the adapter delivers persisted-origin restore and a context call that writes template files to disk (DD-08, DD-10, DD-11).

Everything in the testing story runs as documented **except** the hardware-marker fiction (DD-07) and the `pytest.ini` "self-contained" overstatement (DD-18).

---

## 2. Findings

Severity: **High** = the doc teaches something broken or dangerous; **Medium** = wrong but a user recovers; **Low** = cosmetic staleness. "(verified by execution)" marks findings reproduced by running code during this audit.

### High

#### DD-01 — High — Controller docstring's multi-microscope recipe disconnects the first microscope *(confirms ZC-01)* (verified by execution)
- **Doc:** `zmart_controller/__init__.py:16-20` — "or hold the session object explicitly (**needed for >1 microscope at once**): `from zmart_controller import set_instrument; mic = set_instrument(instrument)`".
- **Reality:** that import resolves to the module wrapper (`__init__.py:43-58`), which unconditionally disconnects the previous active session. Executed at this commit against the mock: after `mic1 = set_instrument(inst); mic2 = set_instrument(inst)`, `mic1.get_xyz()` raises `RuntimeError: session is disconnected`. The only working multi-session path is the un-advertised `zmart_controller.layer.set_instrument` (verified: two sessions stay live through it).
- **Also undocumented:** the teardown side effect itself — neither the controller README §1 nor the wrapper's own docstring (`__init__.py:44-49`) says selecting a new instrument disconnects the previous one.
- **Fix:** point the recipe at `zmart_controller.layer.set_instrument` (or stop tearing down in the wrapper), and state the disconnect-previous behavior in the wrapper docstring and README §1.

#### DD-02 — High — `example_experiment.ipynb` crashes at step 2 on stale state keys; two READMEs sell it as the runnable reference *(confirms ZC-02)* (verified by execution)
- **Doc:** `example_experiment.ipynb` cell 6 (markdown: "an `immutable` fingerprint plus a `mutable` part"), cells 7–8 (`prescan["mutable"]["laser_power"] = 2.0`), cell 11 (markdown: "Re-run with `zmart.set_state(target)`" — a name defined nowhere in the notebook).
- **Reality:** `get_state()` returns `{"changeable": ..., "observed": ...}` everywhere — mock (`tests/mock_driver.py:214-221`), controller (`layer.py:62-78`), Leica adapter (`zmart_adapter.py:810-833`), and the controller README §4 itself. Executed at this commit: cell 7 raises `KeyError: 'mutable'`. The rest of the notebook flow (cells 2–5, 10, 12–15) executes cleanly once the keys are fixed.
- **Compounding claims:** `zmart_controller/README.md:166-169` ("open it and step through the cells") and `:204` ("The test suite and the example notebook both run offline against the mock driver") — the notebook half of that sentence is false today.
- **Fix:** update cells 6–8 and 11 to `changeable`/`observed` and `zmart_controller.set_state`; add an nbclient/nbmake smoke test so the offline notebook cannot rot silently again.

#### DD-03 — High — The documented orientation safety gate is called by nothing, skipped by the controller path, and fails open *(confirms FD-03)*
- **Doc:** driver `README.md:85-87` ("**Canonical orientation** — call `require_canonical_scan_orientation()` at session start; it **fails fast** unless LAS X image export is `TOPLEFT`"), `:101` (quick start step 1), `:187` ("raises unless export is TOPLEFT"), `:392-393` (invariant 3).
- **Reality:** repo-wide, the only occurrences are the definition (`connection/session.py:87-119`) and facade re-exports. `zmart_adapter.connect()` (`zmart_adapter.py:253-280`) does not call it, and `example_leica_experiment.ipynb` — the controller on-ramp that moves the stage and acquires (cells 10–13) — never calls it either. The "fails fast" claim is also soft: `session.py:108-113` passes silently when `get_lasx_settings()` returns `None`/`{}` (missing or unparseable settings file, `readers/api_reader.py:395-407`) and only raises when `enable_transform` is truthy *and* the transform differs from `TOPLEFT`.
- **Fix:** call it from `zmart_adapter.connect()` (and/or `connect_python_client()`), treat unreadable settings as a failure, add a cell to the Leica notebook — or delete the function and the README text together. Today the safety net exists only as prose.

#### DD-04 — High — `movement.py` docstrings promise calibrated backlash parameters the production path never passes *(confirms LM-01/LM-02)*
- **Doc:** `motion/movement.py:23-25` ("Parameters for both come from `motion.stage_config.load`. **Production callers should pass `stage_cfg["backlash"]`** …; the function defaults below are last-resort fallbacks, not the source of truth"), repeated per-arg at `:69-71` and `:132-134`.
- **Reality:** the production caller — the ZMART adapter — calls `move_xy_with_backlash(handle.client, abs_x, abs_y)` and `correct_backlash(handle.client)` with **no** backlash arguments (`zmart_adapter.py:600, 753, 892`), despite loading `stage_cfg` at connect (`:275`). The calibrated `backlash` block that `stage_config.load()` validates on every connect (`stage_config.py:42-48, 158-168`) is consumed by nothing on this path; recalibrating backlash changes no behavior.
- **Related contract drift:** `correct_backlash` accepts `success` without `confirmed` on both legs (`movement.py:146-151`), contradicting its sibling's raise-contract ("either the stage is at (x, y) … or this function raises", `:78-84`) and README §10 invariant 4 ("check `confirmed`, not just `success`") — on the exact takeup that the adapter's default `backlash_correction=True` runs before every acquisition.
- **Fix:** wire `stage_cfg["backlash"]` through the adapter calls and require `confirmed` in `correct_backlash` — or rewrite the docstrings to say the hardcoded defaults are the operative values and drop the unread schema fields.

### Medium

#### DD-05 — Medium — Controller README connection-dict examples drifted from the real adapter *(confirms ZC-05)* (verified by execution)
- **Doc:** `zmart_controller/README.md:82-83` and `:185-186` — `{"vendor": "leica", "microscope": "stellaris5-01", "api": "navigator-expert", "client": "PythonClient", "api_delay_ms": 250}`.
- **Reality:** the registered dict — confirmed by executing `get_instruments()` after importing the adapter — is `{"vendor": "leica", "microscope": "stellaris5-y42h93", "api": "navigator-expert", "client": "PythonClient", "api_delay_ms": None, "output_root": None}` (`zmart_adapter.py:89-97`). Wrong microscope id, wrong delay value (`None` = "use profile default 250", `config/profiles.py:145`), and — critically — the README omits `output_root`, the one key `acquire()` **requires** (`zmart_adapter.py:730-734`) and the one edit §1 should be teaching (the Leica notebook cell 4 knows this; the README never mentions `output_root` at all).
- **Fix:** paste the real `CONNECTION` dict into both examples and explain `output_root` where §1 explains editing the dict before connecting.

#### DD-06 — Medium — `utils.py` documents a timeout-tuning override that cannot work *(confirms LA-07)*
- **Doc:** `utils.py:16-17` — "Configurable timeouts (seconds). **Import and override these to tune for your hardware.**"
- **Reality:** every consumer binds the values at import time (`from ..utils import RECEIPT_TIMEOUT` in `readers/api_reader.py:42`, `scanfields/files.py:19`, `commands/dispatch.py:51`; `CONFIRM_POLL_S` in `commands/confirmations.py:46`, `commands/confirm_select_job.py:23`; both in `config/profiles.py:59`, which additionally freezes them into `CommandProfile` dataclass defaults at class-definition time). Since importing `navigator_expert` imports all of these at once, rebinding `utils.RECEIPT_TIMEOUT` afterwards changes nothing.
- **Fix:** either say "edit-the-source constants" or make them real knobs (attribute access at call time, or route through the profiles that README §8 already documents as *the* tuning surface).

#### DD-07 — Medium — The `hardware`/`slow` marker story is fiction in three documents *(confirms LT-05)* (verified by execution)
- **Docs:** `pytest.ini:28-34` ("the offline/online split is explicit rather than relying on tests to self-skip"; "`hardware`: requires a live LAS X session … Excluded from the default offline run; select with `-m hardware`"; "`slow`: … flagged for --durations"), driver `README.md:308` (tree: "`tests/ unit/ (offline) + hardware/ (@pytest.mark.hardware)`"), `README.md:376-381` (§9 files `python -m pytest -q …/tests/hardware` under "**Live hardware validation** (gated, requires a live LAS X)").
- **Reality:** executed at this commit: `pytest -m hardware --collect-only` selects **0 of 643** tests; repo grep finds no `@pytest.mark.hardware` or `@pytest.mark.slow` anywhere. `pytest.ini`'s `addopts` contains no `-m` filter, so "excluded from the default run" has no mechanism even if tests were marked (the filter lives only in `run_ci.py:204-206`, where it deselects nothing). The `tests/hardware/test_*.py` files README §9 presents as live-gated are **mock-backed and run offline** (`test_validate_hardware.py:1-30` drives `MockLasxClient`; same for the adapter/stress gates). Live validation actually happens via the `validate_*.py` scripts (`run_ci.py online`), whose own comments are accurate.
- **Fix:** drop both marker registrations and the `-m` filter; fix README `:308` and §9 to describe the real split (pytest collects only mock-backed tests everywhere; live validation = the `run_ci.py online` scripts and the `--allow-*` CLI runs).

#### DD-08 — Medium — Controller docstring claims the origin "defaults to the current position at connect"; the real driver restores a persisted origin from a previous session
- **Doc:** `zmart_controller/layer.py:184-185` (`set_instrument`: "the frame is just micrometers from an origin you set with `Session.set_origin` (**the driver defaults it to the current position at connect**)").
- **Reality:** the Leica adapter's default origin is **all-zero** — the frame equals *absolute stage coordinates* (`zmart_adapter.py:137-146`); a first `get_xyz()` after connect reads e.g. `x ≈ 65 000`, not `0`. Worse: `connect` silently **restores a machine-persisted `origin.json` written by a previous session** (`zmart_adapter.py:279, 333-360`; `set_origin` docstring: "the origin stays the frame truth across sessions until set again"), so the frame a new user connects into may be a *previous operator's* zero point. Only the mock coincidentally satisfies the docstring (its raw position at connect happens to be zero).
- **Why it matters:** positions computed against the documented model land somewhere else on the real machine; with a stale persisted origin that is a physical move to another operator's reference.
- **Fix:** change `layer.py` to "origin policy is driver-defined; drivers may persist and restore it across sessions — call `set_origin()` at session start if you need a fresh frame", and say the same in controller README §2 and the Leica notebook's Move & acquire preamble.

#### DD-09 — Medium — Controller README's `get_context()["initial_positions"]` example raises `KeyError` on the Leica driver
- **Doc:** `zmart_controller/README.md:151-155` (§7 example `zmart_controller.get_context()["initial_positions"]`) and `:56-57`; echoed in `layer.py:155-156`; `example_experiment.ipynb` cell 10 builds its whole acquisition loop on this key.
- **Reality:** the Leica adapter's `get_context` returns `{"selected_job", "scan_field", "client", "output_root", "session_hash6"}` (`zmart_adapter.py:1059-1065`) — no `initial_positions`. The key exists in the mock (`mock_driver.py:262`) and, outside this audit's scope, in the mesoSPIM adapter (`zmart_drivers/mesospim/mesospim_zmart_adapter.py:589`) — so it is a plausible-looking convention that the flagship driver does not follow. *(Corrects rev 1, which claimed the key exists nowhere outside the mock.)*
- **Fix:** label the example driver-defined ("the Leica driver exposes stored positions under `scan_field` instead"), or align the drivers on one context key.

#### DD-10 — Medium — Controller docs call `get_context` "read-only"; the Leica implementation writes template files to disk and can stall ~60 s
- **Doc:** `zmart_controller/README.md:151-152` ("returns whatever extra **read-only** context the driver provides"), `layer.py:155-160` ("Additional **read-only** context").
- **Reality:** the adapter's `get_context` → `_scan_field` fires `save_experiment(..., timeout=60)` — flushing the live LAS X experiment to the on-disk scanning template — before parsing (`zmart_adapter.py:966-977`); the adapter's own docstring concedes "flushes the live experiment to disk … (a save, not a state change)" (`:1046-1047`). A "read-only" call that writes vendor files and can block a minute contradicts the controller-level contract.
- **Fix:** controller docs should say "read-only *with respect to instrument state*; drivers may persist working files and block briefly", or the adapter should move the flush behind an explicit option.

#### DD-11 — Medium — `get_xyz(with_actuators=...)` documented as selecting *which actuator to read*; no driver delivers that
- **Doc:** `zmart_controller/layer.py:100-107` ("`with_actuators` optionally selects which actuator **to read** per axis (e.g. `{"z": "piezo"}`); axes left unspecified use the reference one").
- **Reality:** the mock returns the same position regardless (`mock_driver.py:161-169`), and the Leica adapter *deliberately* makes frame `z` actuator-independent — always the focus sum — merely echoing the requested actuator name next to a value it did not influence (`zmart_adapter.py:514-548`: "reads the same regardless of which drive realized the move"). The controller promise and the adapter design directly contradict.
- **Fix:** reword `layer.py` to "annotates the reading with your actuator choice; whether the value differs per actuator is driver-defined" (the Leica per-drive readings already ride along under `"hardware"`).

#### DD-12 — Medium — `calibration/README.md` claims "nothing in this folder is a runtime dependency"; the adapter imports it at every connect
- **Doc:** `calibration/README.md:5-6` ("Workflows consume only the adopted calibration in the newest machine snapshot; **nothing in this folder is a runtime dependency**").
- **Reality:** `zmart_adapter.py:78` imports `..calibration.core.model` and calls `load_calibration`/`get_translation_um` on every `connect` (`:283-303`); `motion/stage_config.py:23` imports `calibration.core.model.SCHEMA_VERSION`; and `calibration/defaults/calibration.json` is the driver's bundled runtime fallback — which the **same README** acknowledges at `:45-46` ("Runtime code reads … or the bundled `calibration/defaults/` when none exists"). The file contradicts the code and itself.
- **Fix:** scope the claim: "the *notebooks and session artifacts* here are not runtime dependencies; `core/model.py` and `defaults/` are consumed by the driver at connect."

#### DD-13 — Medium — Driver README's state-reader contract is wrong on three points for `read_zwide_um`
- **Doc:** driver `README.md:191-192` ("All return a value or `None` (**never raise**). Pass **`diagnostics=True`** for a source-tagged `Reading` …") and the §6 table row `read_zwide_um | (client, ...) | float (µm)`.
- **Reality:** (a) `read_zwide_um` **can raise**: it guards only unreadable settings; readable-but-incomplete settings raise `RuntimeError` in `derived.zwide_um_from_settings` (`readers/derived.py:78-86`), and schema mismatch raises `ValueError` from `make_changeable_copy` (`commands/settings.py:44-50`) — despite `router.py:434-437`'s own "fails closed with None" docstring. (b) It accepts **no `diagnostics` parameter** — signature is `(client, job_name, *, mode=None)` (`router.py:434`; verified via `inspect.signature`), so following the README's "pass `diagnostics=True`" raises `TypeError`. (c) The table's `(client, ...)` hides that `job_name` is **required**. (`ping` and `get_lasx_settings` also lack `mode`/`diagnostics`, but the table shows their exact calls, so only `read_zwide_um` misleads.)
- **Fix:** align the router docstring and callers on one raise posture; show `job_name` in the table; scope the `diagnostics=True` sentence to the routed readers that accept it.

#### DD-14 — Medium — README quick start teaches a stage envelope looser than the machine's own limits, bypassing the config path §3 mandates
- **Doc:** driver `README.md:104-107` — `set_stage_limits(x_min=0, x_max=130_000, y_min=0, y_max=130_000, z_galvo_min=-200, z_galvo_max=200, z_wide_min=-5000, z_wide_max=5000)` under "**Configure safety limits (REQUIRED before movement)**".
- **Reality:** the machine's bundled/calibrated envelope (`limits/defaults/limits.json`; same values in `limits/notebooks/set_stage_limits.ipynb`) is `x [1000, 130000]`, `y [1000, 100000]`, `z_wide [0, 25000]`. The quick-start numbers admit `y` 30 mm past the machine limit, `x`/`y` down to 0, and **negative z-wide** (−5000) where the machine floor is 0. §3 (`README.md:83-84`) and the adapter (`zmart_adapter.py:170-197`) both say limits come from the machine config; the quick start silently replaces that source of truth with hand-typed constants that weaken the hard safety envelope on the exact machine this driver targets.
- **Fix:** make the quick start call `apply_stage_limits_from_config(stage_config.load())` (what `connect` does) and demote raw `set_stage_limits(...)` to a "no machine config yet" footnote using the bundled values.

#### DD-15 — Medium — `function_limits.json` — the fail-closed gate on *every* mutating controller op — is documented nowhere user-facing
- **Doc:** absent. Driver `README.md` §3 "Configuration" lists connection, log reader, calibration & limits, stage limits, orientation — never `function_limits.json` or `shared.limits`; §10's invariants don't mention it; the controller README and both notebooks are silent.
- **Reality:** `zmart_adapter.py:110-111, 200-250` — every op in `_MUTATING_OPS` (`set_origin`, `set_xyz`, `set_state`, `run_procedure`, `acquire`) is gated through `_check_limits`, **fail-closed**: if `function_limits.json` fails to resolve/validate at connect, *every mutating op refuses* ("function limits are not configured — connect() could not load function_limits.json (see the connect warning)"). The governing file surfaces only in `get_state()["observed"]["limits"]`. A user whose every move/acquire refuses finds zero documentation naming the mechanism, the file (`limits/defaults/function_limits.json` / newest snapshot), or the fix.
- **Fix:** add a §3 bullet ("Function-keyed limits — `function_limits.json`, resolved like calibration; fail-closed: mutating ops refuse without it") and a §10 invariant; mention it in the controller README's Leica notes.

#### DD-16 — Medium — Default `acquire()` silently empties the operator's scanning template; nothing user-facing says so
- **Doc:** absent from `zmart_controller/README.md` §5, `example_leica_experiment.ipynb` (cell 12 just acquires), and driver README §6's acquisition section. Documented only inside adapter docstrings (`get_acquisition_options`, `zmart_adapter.py:629-631`; `_ensure_scan_fields_stripped`, `:666-684`) and — for the "read them first" warning — a *private* helper (`_scan_field`, `:963-965`: "Read this BEFORE acquiring: the default `strip_scan_fields` acquisition option empties the template").
- **Reality:** every controller `acquire()` (and every `autofocus` procedure, `:921`) strips the scanning template by default (`strip_scan_fields` active=True). Sidecar-only and restorable via `restore_template`, but an operator's drawn scan fields, regions, and focus points vanish from LAS X with no notice, and the restore path is likewise undocumented at the controller surface.
- **Fix:** one paragraph in controller README §5 and a warning cell in the Leica notebook: "by default, acquiring empties the scanning template (restore with `restore_template`); read stored positions via `get_context()['scan_field']` *before* the first acquire, or pass `options={'strip_scan_fields': False}`."

#### DD-17 — Medium — `acquisition_type`/`position_label` constraints and overwrite semantics undocumented at the controller surface; violation wastes a captured acquisition
- **Doc:** `zmart_controller/README.md:127-135` ("`acquisition_type` is the kind of scan, `position_label` names the output file"), `layer.py:140-142` ("names the position in the output filename") — no constraints, no overwrite semantics.
- **Reality (Leica):** `acquisition_type` must be kebab-case lowercase — `Naming.__post_init__` raises `ValueError` on `"Prescan"` or `"target_scan"` (`shared/output_layout/naming.py:88-92`; rejection verified by execution) — and the raise happens **after** `_capture.acquire` has already run (`zmart_adapter.py:755-758`), so the scan fires and its data is never persisted. `position_label` does **not** name the output file: it maps onto a numeric Naming `p` slot — numeric labels claim their value directly and deliberately **overwrite** previous outputs at the same `p` ("upsert", `zmart_adapter.py:687-702`, `acquisition/save.py:_upsert_summary_record`); non-numeric labels take the next unused slot and appear only in the lineage record, never the filename. All of this lives only in adapter docstrings.
- **Fix:** document the kebab-case rule, the label→p mapping, and the numeric-label overwrite in controller README §5; ideally construct `Naming` *before* firing the capture.

#### DD-18 — Medium — `pytest.ini` header claims a self-contained suite; bare `pytest` silently skips the calibration tests CI treats as fatal
- **Doc:** `pytest.ini:3-5` ("This file makes the driver self-contained: `pytest` run from this folder discovers and runs **the driver's own offline suite**").
- **Reality:** `testpaths = tests` only; `run_ci.py:45` (`TEST_PATHS`) runs `tests` **and** `calibration/tests` as one fatal step. A green local `pytest` proves less than the doc implies (19 calibration tests uncollected).
- **Fix:** add `calibration/tests` to `testpaths`, or state the exclusion in the comment and README §9.

### Low

#### DD-19 — Low — Controller README presents mock-specific menus/keys as the generic contract
- **Doc:** `zmart_controller/README.md:106` (actuators `{"z": ["motoric", "galvo", "piezo"]}`), `:107` (`with_actuators={"z": "piezo"}`), `:125-135` (acquisition options "`backlash_correction` …, `format`, and `procedure`").
- **Reality:** the Leica menus are `z: ["z-wide", "z-galvo"]` (`zmart_adapter.py:99`) and `{job, backlash_correction, strip_scan_fields, format, exporter, cleanup_source}` (`:637-647`) — no `procedure`, no `piezo`; copy-pasting `{"z": "piezo"}` raises `ValueError`. Jarring because step 1 of the *same walkthrough* shows the Leica instrument dict (DD-05). Discover-then-apply mitigates, but nothing marks these values as mock examples.
- **Fix:** caption the examples "values from the bundled mock — always discover first", or show both drivers' menus.

#### DD-20 — Low — Adapter docstring: "`get_procedures` offers backlash takeup only" — it also offers autofocus
- **Doc:** `zmart_adapter/zmart_adapter.py:42` (module docstring, "Scope of v1" bullet).
- **Reality:** `get_procedures` returns `backlash_takeup` **and** `autofocus` (with job discovery), `zmart_adapter.py:869-883`; `run_procedure` runs both (`:886-896`). Stale scope bullet in an otherwise date-stamped, accurate docstring.
- **Fix:** update the bullet.

#### DD-21 — Low — `navigator_expert/__init__.py` package-layout docstring omits four load-bearing directories; facade groups `acquire` under "# commands"
- **Doc:** `__init__.py:4-15` lists `commands/ config/ connection/ readers/ scanfields/ acquisition/ motion/ experimental/` — no `calibration/`, `limits/`, `zmart_adapter/`, `tests/`, all of which README §7's tree documents as first-class. And `__all__`'s `"acquire"` sits under the `# commands` grouping comment (`:81-106`) while the exported symbol is `acquisition.capture.acquire` — the one command-like callable with a *different* contract (raises; returns `AcquisitionResult`; README gotcha #2).
- **Fix:** complete the layout list; move `acquire` under the acquisition grouping with a "raises, returns AcquisitionResult" note.

#### DD-22 — Low — README documents `get_template_state` as three-valued; the code (and the adapter's safety branch) has a fourth value
- **Doc:** driver `README.md:280` — "`get_template_state` (`"fresh"`/`"unstripped"`/`"stripped"`)".
- **Reality:** it also returns `"unreadable"` (`scanfields/files.py`, `get_template_state` docstring and body), the value the adapter treats as a hard pre-acquire error (`zmart_adapter.py:678-682`). A caller switching on the README's enum drops the safety-relevant case.
- **Fix:** add `"unreadable"` to the README line.

#### DD-23 — Low — "Public API is micrometers" vs. meters in returned positions
- **Doc:** driver `README.md:170` ("**Units.** Public API is micrometers"); §5 result table lists `position` (`move_xy`) with no unit.
- **Reality:** `get_xy` returns raw **meters** under `"x"`/`"y"` (µm only under `"x_um"`/`"y_um"`, `readers/api_reader.py:224-229`), and `move_xy`'s `result["position"]` carries the target in meters plus `*_um` keys (`commands/commands.py:1060-1061, 1135`). Inputs are µm as claimed; outputs are mixed.
- **Fix:** one sentence in §5: "returned `position`/`x`/`y` values are meters; use the `*_um` keys."

#### DD-24 — Low — `select_job` docstring denies the pre-check its profile ships
- **Doc:** `commands/commands.py:1414-1415` ("No pre_check_fn (job switching doesn't need scanner idle)").
- **Reality:** `SELECT_JOB = CommandProfile(pre_check_fn=partial(check_idle, timeout=None), ...)` (`config/profiles.py:449-450`).
- **Fix:** fix the docstring.

#### DD-25 — Low — `docs/ZMART.md` driver-status list omits mesoSPIM, contradicting the root README
- **Doc:** `docs/ZMART.md:67-69` ("Drivers today: Leica (production-tested), Zeiss (MVP, offline-green), Nikon + Evident (investigation / spike)").
- **Reality:** root `README.md:79` ranks mesoSPIM "**Demo-validated — near production**", ahead of Zeiss. Cross-doc staleness between the two files describing the same roster.
- **Fix:** add mesoSPIM to the ZMART.md status line.

#### DD-26 — Low — Design doc cites `rebase_galvo` as an existing operation; no such symbol exists
- **Doc:** `docs/design/objective-aware-frame.md:20` ("invariant under re-decomposition between the drives (including `rebase_galvo`)") — phrased as a present-tense property of the *built* §1 invariant (the doc's status header marks §1 BUILT).
- **Reality:** repo-wide grep: `rebase_galvo` appears only in this design doc (`:20`, `:282`). The adapter has no such operation.
- **Fix:** mark it future ("a future `rebase_galvo`") or name the actual mechanism (`with_actuators` re-decomposition inside `set_xyz`).

#### DD-27 — Low — Driver README files `parse_lrp` under `scanfields/parsers.py`; it lives in `scanfields/lrp.py`
- **Doc:** driver `README.md:273-275` — "Parse saved templates (read-only, stdlib ElementTree …; `scanfields/parsers.py`): `parse_lrp` (full job-settings tree) · `parse_scan_positions` · …".
- **Reality:** `parse_lrp` is defined in `scanfields/lrp.py` and imported from there by the facade (`__init__.py:386`); the other listed parsers are in `scanfields/parsers.py` as claimed.
- **Fix:** "(`scanfields/parsers.py`; `parse_lrp` in `scanfields/lrp.py`)".

### Undocumented load-bearing behavior — the top 5 a new user trips over

Each is a numbered finding above; collected here as the mandate's explicit deliverable:

1. **Selecting a new instrument via module-level `set_instrument` disconnects the previous one** — and the "hold two sessions" recipe in the package docstring hits exactly this (DD-01).
2. **The Leica frame is absolute stage coordinates until `set_origin`, and a previous session's persisted `origin.json` is silently restored at connect** — while the controller docstring promises "origin = current position at connect" (DD-08).
3. **Every mutating controller op is gated by `function_limits.json`, fail-closed; if it doesn't load, everything refuses with only a connect-time log warning as the clue** (DD-15).
4. **Default `acquire()` (and the autofocus procedure) empties the operator's LAS X scanning template**; read `get_context()["scan_field"]` first or pass `strip_scan_fields: False` (DD-16).
5. **`acquisition_type` must be kebab-case lowercase (checked *after* the scan fires, so the capture is wasted) and numeric `position_label`s overwrite previous outputs at the same slot** (DD-17). Runner-up: the Leica connection dict needs `output_root` set before `set_instrument()` or `acquire()` refuses (DD-05).

---

## 3. Summary table

| ID | Sev | Location | One-line claim → reality | Prior / verified |
|---|---|---|---|---|
| DD-01 | High | `zmart_controller/__init__.py:16-20` | Multi-microscope recipe → wrapper disconnects the first scope; teardown side effect undocumented | ZC-01 ✔ · executed |
| DD-02 | High | `example_experiment.ipynb` c6-8, c11; controller README:166-169, 204 | "Runnable reference" → `KeyError: 'mutable'` at step 2; `zmart.set_state` ghost name | ZC-02 ✔ · executed |
| DD-03 | High | driver README:85-87, 101, 187, 392; `session.py:87-119` | "Call the orientation gate; fails fast" → zero callers anywhere, notebook skips it, fails open on unreadable settings | FD-03 ✔ |
| DD-04 | High | `motion/movement.py:23-25, 69-71, 132-134` | "Production callers pass calibrated backlash" → adapter passes nothing; `correct_backlash` accepts unconfirmed legs | LM-01/LM-02 ✔ |
| DD-05 | Med | controller README:82-83, 185-186 | Connection dict → wrong microscope id, wrong delay, missing required `output_root` | ZC-05 ✔ · executed |
| DD-06 | Med | `utils.py:16-17` | "Import and override to tune" → import-time binding + frozen dataclass defaults; no effect | LA-07 ✔ |
| DD-07 | Med | `pytest.ini:28-34`; README:308, 376-381 | Marker split documented three ways → 0/643 tests marked; no `-m` filter exists in pytest.ini; `tests/hardware/test_*` are mock-backed | LT-05 ✔ · executed |
| DD-08 | Med | `layer.py:184-185` vs `zmart_adapter.py:137-146, 333-360` | "Origin defaults to current position at connect" → absolute frame, or a *previous session's* persisted origin | rev 1 ✔ |
| DD-09 | Med | controller README:151-155 | `get_context()["initial_positions"]` → `KeyError` on the Leica driver (mock/mesoSPIM-only key) | rev 1, corrected |
| DD-10 | Med | controller README:151-152 / `layer.py:155-160` vs `zmart_adapter.py:966-977` | "Read-only context" → Leica `get_context` writes template files to disk, can stall ~60 s | rev 1 ✔ |
| DD-11 | Med | `layer.py:100-107` | `with_actuators` "selects which actuator to read" → no driver reads differently; Leica z is actuator-invariant by design | rev 1 ✔ |
| DD-12 | Med | `calibration/README.md:5-6` | "Nothing here is a runtime dependency" → adapter imports `core/model.py` at every connect; `defaults/` is the runtime fallback (self-contradicted at :45-46) | rev 1 ✔ |
| DD-13 | Med | driver README:191-192 + §6 table | Readers "never raise / take `diagnostics=True`" → `read_zwide_um` raises, rejects `diagnostics`, hides required `job_name` | rev 1, extended |
| DD-14 | Med | driver README:104-107 | Quick-start limits → exceed machine envelope (y +30 mm, x/y floor 0, z-wide −5000 vs floor 0); bypass the §3-mandated config path | rev 1 ✔ |
| DD-15 | Med | absent (driver README §3/§10; controller README) | — → `function_limits.json` fail-closed gate on all mutating ops documented nowhere | rev 1 ✔ |
| DD-16 | Med | absent (controller README §5; Leica notebook) | — → default `acquire()` empties the operator's scanning template; warning lives in a private docstring | rev 1 ✔ |
| DD-17 | Med | controller README:127-135; `layer.py:140-142` | "`position_label` names the output file" → maps to numeric `p` slot; kebab-case checked *after* the scan fires; numeric labels overwrite | rev 1, extended · executed (Naming) |
| DD-18 | Med | `pytest.ini:3-5` | "Self-contained suite" → bare `pytest` skips `calibration/tests` that CI treats as fatal | rev 1 ✔ |
| DD-19 | Low | controller README:106-107, 125-135 | Mock menus (`piezo`, `procedure`) presented as generic; copy-paste fails on Leica | rev 1 ✔ |
| DD-20 | Low | `zmart_adapter.py:42` | "get_procedures offers backlash takeup only" → also offers autofocus | rev 1 ✔ |
| DD-21 | Low | `navigator_expert/__init__.py:4-15, 81-106` | Layout docstring omits `calibration/ limits/ zmart_adapter/ tests/`; `acquire` filed under "# commands" | rev 1 ✔ |
| DD-22 | Low | driver README:280 | `get_template_state` 3-valued → safety-relevant 4th value `"unreadable"` | rev 1 ✔ |
| DD-23 | Low | driver README:170 | "Public API is micrometers" → returned `x`/`y`/`position` are meters | rev 1 ✔ |
| DD-24 | Low | `commands/commands.py:1414-1415` | "No pre_check_fn" → `SELECT_JOB` ships `check_idle(timeout=None)` | rev 1 ✔ |
| DD-25 | Low | `docs/ZMART.md:67-69` | Driver roster omits mesoSPIM → root README ranks it near-production | rev 1 ✔ |
| DD-26 | Low | `docs/design/objective-aware-frame.md:20, 282` | `rebase_galvo` cited inside the *built* invariant → symbol exists nowhere | rev 1 ✔ |
| DD-27 | Low | driver README:273-275 | `parse_lrp` filed under `scanfields/parsers.py` → lives in `scanfields/lrp.py` | new (rev 2) |

**Totals:** 4 High · 14 Medium · 9 Low = **27 findings**. Six execution-verified; 7 confirm prior component-review findings (ZC-01, ZC-02, ZC-05, LA-07, LT-05, FD-03, LM-01/02 — all still present at `c7964dd`); 1 new in rev 2 (DD-27); 2 rev-1 findings corrected/extended (DD-09, DD-13).

**Verified-correct (no finding):** driver README §6 signatures for all commands/readers/stage/acquisition/template functions (checked via `inspect.signature`); §8 tolerance table exactly matches `config/profiles.py`; §5 result envelope and timing keys match `utils._make_timing`; error classification (permanent-first, unknown→permanent) matches `commands/errors.py`; `select_job` hybrid confirm default matches `StateReaderProfile`; §2 machine-path table matches code (runtime dir confirmed by the suite's own skip message); `run_ci.py` modes/report paths and the CI workflow claim in `requirements-dev.txt`; `config/machine.py` snapshot semantics and non-placeholder bundled defaults; `calibration/README.md` snapshot/notebook claims (except DD-12); `set_stage_limits.ipynb` executes end-to-end against `adopt_limits` (verified hermetically); quick-start imports incl. `Naming`/`run_hash`; both controller notebooks carry no stale committed outputs; all three documented pytest invocations pass offline; root README and `getting_started/README.md` file references (`build_env.py`, `environment.yml`, `requirements.txt`, architecture PNG, workflow notebook, README anchors) all resolve.
