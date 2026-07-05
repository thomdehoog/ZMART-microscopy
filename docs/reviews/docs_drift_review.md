# Docs & Drift Audit — ZMART Controller + Leica `navigator_expert`

- **Scope:** (1) `zmart_controller/` in full — `README.md`, all docstrings (`__init__.py`, `layer.py`, `registry.py`, `tests/mock_driver.py`), `example_experiment.ipynb`, `example_leica_experiment.ipynb`. (2) `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` — `README.md`, `calibration/README.md`, behavioral docstrings (`zmart_adapter/`, `utils.py`, `motion/*`, `connection/session.py`, `commands/`, `readers/`, `config/machine.py`, `scanfields/files.py`), `limits/notebooks/set_stage_limits.ipynb`, `requirements-dev.txt` claims, `pytest.ini` / `run_ci.py` comments. (3) Repo-root `README.md`, `getting_started/README.md`, and the `docs/` sections describing the controller or the Leica driver (`docs/ZMART.md`, `docs/design/objective-aware-frame.md`).
- **Date:** 2026-07-03 · **Commit:** `c7964dd` (verified: HEAD differs from `c7964dd` only by `docs/reviews/*.md` additions; every audited code and doc file is byte-identical at this commit).
- **Method:** every testable claim was extracted and checked against code; runnable snippets (controller README examples, both notebooks' registration/state flow, quick-start imports, `Naming`, registry round-trip, pytest invocations) were executed against the mock driver / offline package — never against hardware. Prior reviews in `docs/reviews/` were read first; confirmations are cross-referenced briefly, depth was spent on new drift.

---

## 1. Executive summary

**Verdict: the reference material is trustworthy; the on-ramps are not.** The Leica driver README's API reference is remarkably accurate — every signature in §6, every tolerance in §8, every `requirements-dev.txt` traced-dependency comment, every `run_ci.py` flag and report path, and every referenced file/dir was verified correct at this commit. The adapter's own docstrings are dated, honest, and match the code almost line-for-line.

The drift concentrates in exactly the places a **new user starts**:

1. The controller's flagship notebook (`example_experiment.ipynb`) still crashes at step 2 on a two-generations-stale state vocabulary, while two READMEs advertise it as the runnable reference (DD-02).
2. The controller package docstring still teaches a multi-microscope recipe that disconnects the first microscope (DD-01).
3. The driver README documents an orientation safety gate (`require_canonical_scan_orientation`) that **no code path calls** — including the controller notebook that moves and acquires — and that fails open when it can't read settings (DD-03).
4. `movement.py` docstrings promise calibrated backlash parameters that the primary production caller never passes (DD-04).
5. Five pieces of genuinely load-bearing behavior (previous-session teardown, persisted-origin restore, the fail-closed function-limits gate, default scan-field stripping, `Naming` label constraints) are documented thinly or not at all at the surface users actually read (DD-15…DD-17, DD-01, DD-08).

All six prior findings named in the mandate (ZC-01, ZC-02, ZC-05, LA-07, LT-05/FD-15, FD-03, plus LM-01) **still stand at this commit**, re-verified empirically where runnable. 19 further findings are new to this audit.

Verified-correct highlights (no finding): driver README §6 command table matches all 20+ `set_*`/`move_*`/`acquire`/`select_job` signatures; §8 tolerance table matches `config/profiles.py` exactly (0.1 zoom … 20.0 µm `move_xy`, `ACQUIRE` as the sole `max_retries=0` deviation); §5 result envelope matches `utils._make_timing`/`_make_log_entry`; quick-start imports all resolve offline (including `shared.output_layout.run_hash`); `machine.py`'s "schema v11" and "never an identity placeholder" claims hold; `.coveragerc`, `tests/_diagnostics.py`, both GitHub workflows, `build_env.py`/`environment.yml`/`requirements.txt`, and every root-README link exist; both controller notebooks carry no stale committed outputs; `python -m pytest zmart_controller/tests` passes 35/35 as the README instructs.

---

## 2. Findings

Severity: **High** = the doc teaches something broken or dangerous; **Medium** = wrong but a user recovers; **Low** = cosmetic staleness.

### High

#### DD-01 — High — Controller docstring's multi-microscope recipe disconnects the first microscope *(confirms ZC-01 — still present)*
- **Doc:** `zmart_controller/__init__.py:16-20` — "or hold the session object explicitly (needed for >1 microscope at once): `from zmart_controller import set_instrument; mic = set_instrument(instrument)`".
- **Reality:** that import resolves to the module wrapper at `__init__.py:43-58`, which unconditionally disconnects the previous active session. Re-verified at this commit against the mock: after `m1 = set_instrument(a); m2 = set_instrument(b)`, `m1.get_xyz()` raises `RuntimeError: session is disconnected`. The only working path is the un-advertised `zmart_controller.layer.set_instrument`.
- **Also undocumented:** the teardown side effect itself. Neither `README.md` §1 ("After this, every `zmart` call goes to that microscope") nor the `set_instrument` docstring (`__init__.py:44-49`) says that selecting a new instrument **disconnects the previous one**. Load-bearing behavior a user only discovers when their first session dies.
- **Fix:** point the recipe at `zmart_controller.layer.set_instrument` (or stop tearing down in the wrapper), and state the disconnect-previous behavior in both the wrapper docstring and README §1.

#### DD-02 — High — `example_experiment.ipynb` crashes at step 2 on stale state keys; two READMEs sell it as the runnable reference *(confirms ZC-02 — still present)*
- **Doc:** `example_experiment.ipynb` cell 6 (markdown: "an `immutable` fingerprint plus a `mutable` part"), cells 7-8 (`prescan["mutable"]["laser_power"] = 2.0`), cell 11 (markdown: "Re-run with `zmart.set_state(target)`" — a module name used nowhere else in the notebook).
- **Reality:** `get_state()` returns `{"changeable": ..., "observed": ...}` everywhere — mock (`tests/mock_driver.py:218-221`), controller (`layer.py:62-78`), Leica adapter (`zmart_adapter.py:810-833`), and the controller README itself (§4). Re-executed at this commit: cell 7 raises `KeyError: 'mutable'`.
- **Compounding claims:** `zmart_controller/README.md:166-169` ("open it and step through the cells") and `README.md:204` ("The test suite and the example notebook both run offline against the mock driver") — the second half of that sentence is false.
- **Fix:** update cells 6-8 and 11 to `changeable`/`observed` and `zmart_controller.set_state`; add an nbclient/nbmake smoke test so the offline notebook can't silently rot again.

#### DD-03 — High — The documented orientation safety gate is called by nothing, skipped by the controller path, and fails open *(confirms FD-03; extends it to the notebook path)*
- **Doc:** driver `README.md:85-87` ("**Canonical orientation** — call `require_canonical_scan_orientation()` at session start; it **fails fast** unless LAS X image export is `TOPLEFT`"), `README.md:101` (quick start step 1), `README.md:187` ("raises unless export is TOPLEFT"), `README.md:392-393` (invariant 3: "Image export **must** be `TOPLEFT`").
- **Reality:**
  - Whole-repo grep at this commit: the only occurrences are the definition (`connection/session.py:87-119`) and the facade re-export. `zmart_adapter.connect()` (`zmart_adapter.py:253-280`) does not call it, and `example_leica_experiment.ipynb` — the documented controller on-ramp, which moves the stage and acquires (cells 10-13) — never calls it either. The invariant README §10 says "silently misbehaves" about is enforced nowhere on the controller path.
  - The "fails fast"/"raises unless TOPLEFT" claim is also soft: `session.py:108-113` returns silently when `get_lasx_settings()` yields `None`/`{}` (unreadable settings ⇒ pass), and only raises when `enable_transform` is truthy *and* the transform differs.
- **Fix:** call it from `zmart_adapter.connect()` (and/or `connect_python_client()`), make unreadable settings a failure, add a cell to the Leica notebook — or delete the function and its README/§10 text together. The current state is a safety net that exists only as text.

#### DD-04 — High — `movement.py` docstrings promise calibrated backlash parameters the production path never passes *(confirms LM-01 — still present)*
- **Doc:** `motion/movement.py:23-25` ("Production callers should pass `stage_cfg["backlash"]` from that loader; the function defaults below are last-resort fallbacks, not the source of truth"), repeated at `movement.py:69-71` ("Pass the calibrated `backlash["tolerance_um"]` from the machine snapshot") and `movement.py:132-134`.
- **Reality:** the primary production caller — the ZMART adapter — calls `move_xy_with_backlash(handle.client, abs_x, abs_y)` and `correct_backlash(handle.client)` with **no** backlash arguments (`zmart_adapter.py:600, 753, 892`), despite loading `stage_cfg` at connect (`zmart_adapter.py:275`). The calibration schema's `tolerance_um`/`approach` (`motion/stage_config.py:42-48`) are consumed by nothing repo-wide. An operator who recalibrates backlash sees no behavior change on the adapter path.
- **Related contract drift (LM-02, re-verified):** `correct_backlash` accepts `success` without `confirmed` on both legs (`movement.py:146-151`), contradicting its sibling's documented raise-contract (`movement.py:87-96`) and README §10 invariant 4 ("check `confirmed`, not just `success`") — on the exact takeup the adapter's default `backlash_correction=True` runs before every acquisition.
- **Fix:** wire `stage_cfg["backlash"]` through the adapter calls (it already holds the config) and require `confirmed` in `correct_backlash` — or rewrite the docstrings to say the defaults are the operative values and delete the unread schema fields. The half-state actively misleads.

### Medium

#### DD-05 — Medium — Controller README connection-dict examples drifted from the real adapter *(confirms ZC-05 — still present)*
- **Doc:** `zmart_controller/README.md:82-83` and `:185-186` — `{"vendor": "leica", "microscope": "stellaris5-01", "api": "navigator-expert", "client": "PythonClient", "api_delay_ms": 250}`.
- **Reality:** the registered dict (`zmart_adapter.py:89-97`, confirmed via live `get_instruments()` at this commit) is `{"vendor": "leica", "microscope": "stellaris5-y42h93", "api": "navigator-expert", "client": "PythonClient", "api_delay_ms": None, "output_root": None}`. Wrong microscope id, wrong delay value (`None` = "use profile default 250", `config/profiles.py:145`), and — critically — the README omits `output_root`, the one key `acquire()` **requires** (`zmart_adapter.py:730-734`) and the one edit README §1 should be teaching (the Leica notebook cell 4 knows this; the README doesn't).
- **Fix:** paste the real `CONNECTION` dict into both examples and mention `output_root` where §1 explains editing the dict before connecting.

#### DD-06 — Medium — `utils.py` documents a timeout-tuning override that cannot work *(confirms LA-07 — still present)*
- **Doc:** `utils.py:16-17` — "Configurable timeouts (seconds). **Import and override these to tune for your hardware.**"
- **Reality:** every consumer binds the ints at import time (`from ..utils import RECEIPT_TIMEOUT` — `readers/api_reader.py:42`, `scanfields/files.py:19`, `commands/confirmations.py`, and `config/profiles.py:59`, which additionally freezes both values into `CommandProfile` dataclass field defaults at class-definition time, `profiles.py:235,244`). Rebinding `navigator_expert.utils.RECEIPT_TIMEOUT` after the package imports (which happens all at once via `__init__.py`) changes nothing. Verified by consumer-grep at this commit.
- **Fix:** either say "edit-the-source constants" or make them real knobs (module-attribute access at call time, or route through the profiles README §8 already documents as *the* tuning surface).

#### DD-07 — Medium — The `hardware`/`slow` marker story is fiction in three documents *(confirms LT-05 / FD-15 — still present, with one new detail)*
- **Docs:** `pytest.ini:28-32` ("the offline/online split is explicit rather than relying on tests to self-skip"; "`hardware`: … Excluded from the default offline run; select with `-m hardware`"), driver `README.md:308` (repo map: "`tests/ unit/ (offline) + hardware/ (@pytest.mark.hardware)`"), `README.md:376-381` (§9 presents `python -m pytest -q …/tests/hardware` under "**Live hardware validation** (gated, requires a live LAS X)"), `run_ci.py:197`.
- **Reality (re-verified empirically):** `pytest -m hardware` from the driver root selects **0 of 643** collected tests; grep for `mark.hardware|mark.slow` finds only the `run_ci.py` comment. **New detail:** `pytest.ini`'s own `addopts` contains no `-m` filter at all — the "excluded from the default offline run" claim in the marker text has no mechanism even if tests *were* marked (the filter lives only in `run_ci.py:204-206`, where it deselects nothing). Meanwhile the `tests/hardware/test_*.py` wrappers README §9 files under "requires a live LAS X" are mock-only and run in the default offline collection.
- **Fix:** LT-05 option (a): drop both marker registrations and the `-m` filter, fix README:308 and §9 to describe the real split (pytest collects only mock-backed tests; live validation is the `run_ci.py online` scripts).

#### DD-08 — Medium — Controller docstring claims the origin "defaults to the current position at connect"; the real driver restores a persisted origin from a previous session
- **Doc:** `zmart_controller/layer.py:184-185` (`set_instrument`: "the frame is just micrometers from an origin you set with `Session.set_origin` (**the driver defaults it to the current position at connect**)").
- **Reality:** the Leica adapter's default origin is **all-zero**, i.e. the frame equals *absolute stage coordinates* (`zmart_adapter.py:137-146`) — a first `get_xyz()` after connect reads e.g. `x ≈ 65 000`, not `0`. Worse for the claim: `connect` silently **restores a machine-persisted `origin.json` written by a previous session** (`zmart_adapter.py:279, 333-360`; `set_origin` docstring: "the origin stays the frame truth across sessions until set again"). So the frame a new user connects into may be a *previous operator's* zero point. Only the mock trivially satisfies the docstring (its raw position at connect happens to be zero).
- **Why it matters:** the two behaviors (documented vs. real) put the frame in different places; positions computed against the docstring's model land somewhere else. The adapter documents its behavior well *in its own module* — the controller-level promise is what's wrong.
- **Fix:** change `layer.py`'s claim to "origin policy is driver-defined; drivers may persist and restore it across sessions — call `set_origin()` at session start if you need a fresh frame", and say the same in controller README §2 and the Leica notebook's Move & acquire preamble.

#### DD-09 — Medium — Controller README's `get_context()["initial_positions"]` example raises `KeyError` on the only real driver
- **Doc:** `zmart_controller/README.md:151-155` (§7 code example `zmart_controller.get_context()["initial_positions"]`) and `:56-57`; echoed in `layer.py:155-156`.
- **Reality:** `initial_positions` exists only in the mock (`mock_driver.py:262`). The Leica adapter's `get_context` returns `{"selected_job", "scan_field", "client", "output_root", "session_hash6"}` (`zmart_adapter.py:1059-1065`) — whole-repo grep finds no `initial_positions` outside the mock/controller docs. `example_experiment.ipynb` cell 10 builds its entire acquisition loop on this key, reinforcing it as *the* pattern.
- **Fix:** label the example as mock-specific ("keys are driver-defined; the Leica driver exposes `scan_field` positions instead") or align the notebooks' position-source pattern with what real drivers provide.

#### DD-10 — Medium — Controller docs call `get_context` "read-only"; the Leica implementation writes template files to disk and can stall ~60 s
- **Doc:** `zmart_controller/README.md:151-152` ("returns whatever extra **read-only** context the driver provides"), `layer.py:155-160` ("Additional **read-only** context").
- **Reality:** the adapter's `get_context` → `_scan_field` fires `save_experiment(..., timeout=60)` — flushing the live LAS X experiment to the on-disk template — before parsing (`zmart_adapter.py:966-977`); the adapter docstring itself concedes "flushes the live experiment to disk … (a save, not a state change)" (`:1046-1047`). A "read-only" call that writes vendor files and can block a minute is a contract contradiction between the two layers (stall previously noted Leica-side as LA-12-adjacent; the cross-layer contradiction is the new finding).
- **Fix:** controller docs should say "read-only *with respect to instrument state*; drivers may persist working files and block briefly", or the adapter should move the flush behind an explicit option.

#### DD-11 — Medium — `get_xyz(with_actuators=...)` documented as selecting *which actuator to read*; no driver delivers that
- **Doc:** `zmart_controller/layer.py:100-107` ("`with_actuators` optionally selects which actuator **to read** per axis (e.g. `{"z": "piezo"}`); axes left unspecified use the reference one").
- **Reality:** the mock reads one position regardless (`mock_driver.py:161-169`); the Leica adapter *deliberately* makes the frame `z` actuator-independent — always the focus sum — and merely echoes the requested actuator name next to a value it did not determine (`zmart_adapter.py:514-548`; its docstring: "reads the same regardless of which drive realized the move"). The controller promise and the adapter design directly contradict.
- **Fix:** reword `layer.py` to "annotates the reading with your actuator choice; whether the value differs per actuator is driver-defined", or make the adapter report per-drive values for a per-drive request (the per-drive readings already ride along under `"hardware"`).

#### DD-12 — Medium — `calibration/README.md` claims "nothing in this folder is a runtime dependency"; the adapter imports it at every connect
- **Doc:** `calibration/README.md:5-6` ("Workflows consume only the adopted calibration in the newest machine snapshot; **nothing in this folder is a runtime dependency**").
- **Reality:** `zmart_adapter.py:78` imports `..calibration.core.model` and calls `load_calibration`/`get_translation_um` on every `connect` (`:283-303`); `motion/stage_config.py:23` imports `calibration.core.model.SCHEMA_VERSION`; and `calibration/defaults/calibration.json` is the driver's bundled runtime fallback — which the **same README** says at lines 45-46 ("Runtime code reads … or the bundled `calibration/defaults/` when none exists"). The file contradicts both the code and itself.
- **Fix:** scope the claim to what's meant: "the *notebooks and session artifacts* here are not runtime dependencies; `core/model.py` and `defaults/` are consumed by the driver at connect."

#### DD-13 — Medium — Driver README's "state readers … never raise" is false for `read_zwide_um` *(cross-ref LC-07 — the docstring side, still present)*
- **Doc:** driver `README.md:191` ("All return a value or `None` (**never raise**)"), and the §6 table row `read_zwide_um | (client, ...) | float (µm)`.
- **Reality:** `read_zwide_um` propagates `RuntimeError` when `zPosition`/z-wide is absent from readable settings and `ValueError` from `make_changeable_copy` on schema mismatch (`readers/derived.py:66-86`, `commands/settings.py:44-50`), despite `router.py:435-444`'s own no-raise docstring. Table nit: the elided signature hides that `job_name` is **required** (`(client, job_name, *, mode=None)`).
- **Fix:** per LC-07, pick a posture and align README §6, the router docstring, and the callers; show `job_name` in the table.

#### DD-14 — Medium — README quick start teaches a stage envelope looser than the machine's own limits, bypassing the config path §3 mandates *(extends LA-28: not just Y — X, and a Z-wide sign error too)*
- **Doc:** driver `README.md:104-107` — `set_stage_limits(x_min=0, x_max=130_000, y_min=0, y_max=130_000, z_galvo_min=-200, z_galvo_max=200, z_wide_min=-5000, z_wide_max=5000)` under "**Configure safety limits (REQUIRED before movement)**".
- **Reality:** the machine's bundled/calibrated envelope (`limits/defaults/limits.json`, same values in the operator notebook `limits/notebooks/set_stage_limits.ipynb`) is `x [1000, 130000]`, `y [1000, 100000]`, `z_wide [0, 25000]`. The quick-start numbers admit `y` up to 30 mm past the machine's limit, `x`/`y` down to 0, and **negative z-wide** (−5000) where the machine's floor is 0. §3 (`README.md:83-84`) and the adapter both say limits come from the machine config (`apply_stage_limits_from_config(stage_config.load())`); the quick start silently replaces that source of truth with hand-typed constants. A copy-paste weakens the hard safety envelope on the exact machine this driver targets.
- **Fix:** make the quick start load the machine config (`_limits.apply_stage_limits_from_config(stage_config.load())`, exactly what `connect` does) and demote raw `set_stage_limits(...)` to a "no machine config yet" footnote with the bundled values.

#### DD-15 — Medium — `function_limits.json` — the fail-closed gate on *every* mutating controller op — is documented nowhere *(undocumented load-bearing behavior #1)*
- **Doc:** absent. Driver `README.md` §3 "Configuration" lists connection, log reader, calibration & limits, stage limits, orientation — but never `function_limits.json` or `shared.limits`; §10's invariants don't mention it; the controller README and both notebooks are silent.
- **Reality:** `zmart_adapter.py:110-111, 200-250` — every op in `_MUTATING_OPS` (`set_origin`, `set_xyz`, `set_state`, `set_procedure`, `acquire`) is gated through `_check_limits`, **fail-closed**: if `function_limits.json` fails to resolve/validate at connect, *every mutating op refuses* with "function limits are not configured — connect() could not load function_limits.json (see the connect warning)". The governing file is surfaced only in `get_state()["observed"]["limits"]`. A user whose every move/acquire refuses will find zero documentation explaining the mechanism, the file, or the fix.
- **Fix:** add a §3 bullet ("Function-keyed limits — `function_limits.json`, resolved like calibration; fail-closed: mutating ops refuse without it") and a §10 invariant; mention it in the controller README's Leica notes.

#### DD-16 — Medium — Default `acquire()` silently empties the operator's scanning template; nothing user-facing says so *(undocumented load-bearing behavior #2)*
- **Doc:** absent from `zmart_controller/README.md` §5, `example_leica_experiment.ipynb` (cell 12 just acquires), and driver README §6's acquisition section. Documented only inside adapter docstrings (`get_acquisition_options`, `zmart_adapter.py:629-631`; `_ensure_scan_fields_stripped`, `:667-673`) and — for the "read them first" warning — a *private* helper (`_scan_field`, `:963-965`: "Read this BEFORE acquiring: the default `strip_scan_fields` acquisition option empties the template").
- **Reality:** every controller `acquire()` (and every `autofocus` procedure, `:921`) strips the scanning template by default (`strip_scan_fields` active=True). Sidecar-only and restorable via `restore_template`, but an operator's drawn scan fields, regions, and focus points vanish from LAS X with no notice, and the restore path is likewise undocumented at the controller surface.
- **Fix:** one paragraph in the controller README §5 and a warning cell in the Leica notebook: "by default, acquiring empties the scanning template (restore with `restore_template`); read stored positions via `get_context()['scan_field']` *before* the first acquire, or pass `options={'strip_scan_fields': False}`."

#### DD-17 — Medium — `acquisition_type`/`position_label` constraints undocumented at the controller surface; violation wastes a captured acquisition *(undocumented load-bearing behavior #3)*
- **Doc:** `zmart_controller/README.md:127-135` — "`acquisition_type` is the kind of scan, `position_label` names the output file" — no constraints; `layer.py:132-151` likewise.
- **Reality (Leica):** `acquisition_type` must be kebab-case lowercase — `Naming.__post_init__` raises `ValueError` on `"Prescan"` or `"target_scan"` (`shared/output_layout/naming.py:42-43, 88-92`) — and the raise happens **after** `_capture.acquire` has already run (`zmart_adapter.py:755-758`), so the scan fires and its data is never saved. Numeric `position_label`s claim their `p` slot directly and deliberately **overwrite** previous outputs at the same `p` ("upsert", `zmart_adapter.py:687-702`); non-numeric labels take the next unused slot. All of this lives only in adapter docstrings.
- **Fix:** document the kebab-case rule and the numeric-label overwrite semantics in controller README §5 (the driver README could carry it too); ideally validate `Naming` *before* firing the capture.

#### DD-18 — Medium — `pytest.ini` header claims a self-contained suite; bare `pytest` silently skips the calibration tests CI treats as fatal *(cross-ref LT-07/LA-26 — still present)*
- **Doc:** `pytest.ini:3-5` ("This file makes the driver self-contained: `pytest` run from this folder discovers and runs **the driver's own offline suite**").
- **Reality:** `testpaths = tests` only; `run_ci.py:45` runs `tests` **and** `calibration/tests` (fatal). A green local `pytest` proves less than the doc implies.
- **Fix:** add `calibration/tests` to `testpaths` (or state the exclusion in the comment and README §9).

### Low

#### DD-19 — Low — Controller README presents mock-specific menus/keys as the generic contract
- **Doc:** `zmart_controller/README.md:106` (actuators `{"z": ["motoric", "galvo", "piezo"]}`), `:107` (`with_actuators={"z": "piezo"}`), `:125-135` (acquisition options "`backlash_correction` …, `format`, and `procedure`"; example output `{"backlash_correction": ..., "format": ..., "procedure": ...}`).
- **Reality:** the real driver's menus are `z: ["z-wide", "z-galvo"]` (`zmart_adapter.py:99`) and `{job, backlash_correction, strip_scan_fields, format, exporter, cleanup_source}` (`:637-647`) — no `procedure` option, no `piezo`. Copy-pasting `{"z": "piezo"}` on the Leica raises `ValueError`. Discover-then-apply mitigates, but nothing marks these values as mock examples.
- **Fix:** caption the examples "values from the bundled mock — always discover first", or show both drivers' menus side by side.

#### DD-20 — Low — Adapter docstring: "``get_procedures`` offers backlash takeup only" — it also offers autofocus
- **Doc:** `zmart_adapter/zmart_adapter.py:42` (module docstring, "Scope of v1" bullet).
- **Reality:** `get_procedures` returns `backlash_takeup` **and** `autofocus` (with job discovery), `zmart_adapter.py:869-883`; `set_procedure` runs both (`:886-896`). Stale scope bullet in an otherwise date-stamped, accurate docstring.
- **Fix:** update the bullet.

#### DD-21 — Low — `navigator_expert/__init__.py` package-layout docstring omits four load-bearing directories; facade groups `acquire` under "# commands"
- **Doc:** `__init__.py:4-15` lists `commands/ config/ connection/ readers/ scanfields/ acquisition/ motion/ experimental/` — no `calibration/`, `limits/`, `zmart_adapter/`, `tests/`, all of which README §7's tree documents as first-class. And `__all__`'s `"acquire"` sits under the `# commands` grouping comment (`:82,106`) while the exported symbol is `acquisition.capture.acquire` — the one command-like callable with a *different* contract (raises; returns `AcquisitionResult`, README gotcha #2). *(Facade-drift risk previously flagged Leica-side; the layout omission is new.)*
- **Fix:** complete the layout list; move `acquire` under the acquisition grouping with a "raises, returns AcquisitionResult" note.

#### DD-22 — Low — README documents `get_template_state` as three-valued; the code (and the adapter's safety branch) has a fourth value
- **Doc:** driver `README.md:280` — "`get_template_state` (`"fresh"`/`"unstripped"`/`"stripped"`)".
- **Reality:** it also returns `"unreadable"` (`scanfields/files.py:89-91`), the value the adapter treats as a hard error before acquiring (`zmart_adapter.py:678-682`). A caller switching on the README's enum drops the safety-relevant case.
- **Fix:** add `"unreadable"` to the README line.

#### DD-23 — Low — "Public API is micrometers" vs. meters in returned positions
- **Doc:** driver `README.md:170` ("**Units.** Public API is micrometers"); §5 result table lists `position` (`move_xy`) with no unit.
- **Reality:** `get_xy` returns raw **meters** under `"x"`/`"y"` (µm only under `"x_um"`/`"y_um"`, `readers/api_reader.py:224-229`), and `move_xy`'s `result["position"]` is the target **in meters** (`commands/commands.py:1060-1061` documents it, the README doesn't). Inputs are µm as claimed; outputs are mixed.
- **Fix:** one sentence in §5: "returned `position`/`x`/`y` values are meters; use the `*_um` keys."

#### DD-24 — Low — `select_job` docstring denies the pre-check its profile ships *(cross-ref CF-12 — re-verified)*
- **Doc:** `commands/commands.py:1412-1415` ("No pre_check_fn (job switching doesn't need scanner idle)").
- **Reality:** `SELECT_JOB = CommandProfile(pre_check_fn=partial(check_idle, timeout=None), ...)` (`config/profiles.py:449-450`).
- **Fix:** fix the docstring (and see CF-02 about that `timeout=None`).

#### DD-25 — Low — `docs/ZMART.md` driver-status list omits mesoSPIM, contradicting the root README
- **Doc:** `docs/ZMART.md:67-69` ("Drivers today: Leica (production-tested), Zeiss (MVP, offline-green), Nikon + Evident (investigation / spike)").
- **Reality:** root `README.md:79` ranks mesoSPIM "**Demo-validated — near production**", ahead of Zeiss. Cross-doc staleness in the two files that describe the same driver roster.
- **Fix:** add mesoSPIM to the ZMART.md status line.

#### DD-26 — Low — Design doc cites `rebase_galvo` as an existing operation; no such symbol exists
- **Doc:** `docs/design/objective-aware-frame.md:20` ("invariant under re-decomposition between the drives (including `rebase_galvo`)") — phrased as a present-tense property of the built §1.
- **Reality:** whole-repo grep: `rebase_galvo` appears only in this doc. The doc is honestly marked "proposed / §1 built", but this reference sits inside the *built* invariant's description.
- **Fix:** mark it future ("a future `rebase_galvo`") or name the actual mechanism (`with_actuators` re-decomposition in `set_xyz`).

### Undocumented load-bearing behavior — the top 5 a new user trips over

Collected from the findings above (each is a numbered finding; listed here as the mandate's explicit deliverable):

1. **Selecting a new instrument disconnects the previous one** (module-level `set_instrument`) — DD-01.
2. **The Leica frame is absolute stage coordinates until `set_origin`, and a previous session's persisted origin is silently restored at connect** — DD-08.
3. **Every mutating controller op is gated by `function_limits.json`, fail-closed; if it doesn't load, everything refuses with only a connect-time log warning** — DD-15.
4. **Default `acquire()` (and autofocus) empties the operator's LAS X scanning template** — DD-16.
5. **`acquisition_type` must be kebab-case lowercase (checked *after* the scan fires) and numeric `position_label`s overwrite previous outputs at the same slot** — DD-17.

---

## 3. Summary table

| ID | Sev | Location | One-line claim → reality | Prior |
|---|---|---|---|---|
| DD-01 | High | `zmart_controller/__init__.py:16-20` | Multi-microscope recipe → wrapper disconnects the first scope; teardown side effect undocumented | ZC-01 ✔ |
| DD-02 | High | `example_experiment.ipynb` c6-8, c11; controller README:166-169, 204 | "Runnable reference" → `KeyError: 'mutable'` at step 2; `zmart.set_state` ghost module | ZC-02 ✔ |
| DD-03 | High | driver README:85-87, 101, 187, 392; `session.py:87-119` | "Call the orientation gate; fails fast" → zero callers anywhere, notebook skips it, fails open on unreadable settings | FD-03 ✔ |
| DD-04 | High | `motion/movement.py:23-25, 69-71, 132-134` | "Production callers pass calibrated backlash" → adapter passes nothing; `tolerance_um`/`approach` read by no one; `correct_backlash` accepts unconfirmed legs | LM-01/LM-02 ✔ |
| DD-05 | Med | controller README:82-83, 185-186 | Connection dict → wrong microscope id, wrong delay, missing required `output_root` | ZC-05 ✔ |
| DD-06 | Med | `utils.py:16-17` | "Import and override to tune" → import-time binding + frozen dataclass defaults; no effect | LA-07 ✔ |
| DD-07 | Med | `pytest.ini:28-32`; README:308, 376-381 | Marker split documented three ways → 0/643 tests marked; no `-m` filter even exists in pytest.ini | LT-05/FD-15 ✔ |
| DD-08 | Med | `layer.py:184-185` vs `zmart_adapter.py:137-146, 333-360` | "Origin defaults to current position at connect" → absolute frame, or a *previous session's* persisted origin | new |
| DD-09 | Med | controller README:151-155 | `get_context()["initial_positions"]` → `KeyError` on the only real driver (mock-only key) | new |
| DD-10 | Med | controller README:151-152 / `layer.py:155-160` vs `zmart_adapter.py:966-977` | "Read-only context" → Leica `get_context` writes template files to disk, can stall ~60 s | new |
| DD-11 | Med | `layer.py:100-107` | `with_actuators` "selects which actuator to read" → no driver reads differently; Leica z is actuator-invariant by design | new |
| DD-12 | Med | `calibration/README.md:5-6` | "Nothing here is a runtime dependency" → adapter imports `core/model.py` at every connect; `defaults/` is the runtime fallback (self-contradicted at :45-46) | new |
| DD-13 | Med | driver README:191 + §6 table | Readers "never raise" → `read_zwide_um` raises; required `job_name` hidden by `(client, ...)` | LC-07 ✔ (doc side) |
| DD-14 | Med | driver README:104-107 | Quick-start limits → exceed machine envelope (y +30 mm, x/y floor 0, z-wide −5000 vs floor 0); bypasses the §3-mandated config path | extends LA-28 |
| DD-15 | Med | absent (driver README §3/§10; controller README) | — → `function_limits.json` fail-closed gate on all mutating ops documented nowhere | new |
| DD-16 | Med | absent (controller README §5; Leica notebook) | — → default `acquire()` empties the operator's scanning template; warning lives in a private docstring | new |
| DD-17 | Med | controller README:127-135 | "`acquisition_type` is the kind of scan" → must be kebab-case; violation raises *after* the scan fires (data unsaved); numeric labels overwrite | new |
| DD-18 | Med | `pytest.ini:3-5` | "Self-contained suite" → bare `pytest` skips `calibration/tests` that CI treats as fatal | LT-07 ✔ |
| DD-19 | Low | controller README:106-107, 125-135 | Mock menus (`piezo`, `procedure`) presented as generic; copy-paste fails on Leica | new |
| DD-20 | Low | `zmart_adapter.py:42` | "get_procedures offers backlash takeup only" → also offers autofocus | new |
| DD-21 | Low | `navigator_expert/__init__.py:4-15, 82-106` | Layout docstring omits `calibration/ limits/ zmart_adapter/ tests/`; `acquire` filed under "# commands" | new |
| DD-22 | Low | driver README:280 | `get_template_state` 3-valued → code has safety-relevant 4th value `"unreadable"` | new |
| DD-23 | Low | driver README:170 | "Public API is micrometers" → returned `x`/`y`/`position` are meters | new |
| DD-24 | Low | `commands/commands.py:1412-1415` | "No pre_check_fn" → `SELECT_JOB` ships `check_idle(timeout=None)` | CF-12 ✔ |
| DD-25 | Low | `docs/ZMART.md:67-69` | Driver roster omits mesoSPIM → root README ranks it near-production | new |
| DD-26 | Low | `docs/design/objective-aware-frame.md:20` | `rebase_galvo` cited as existing → symbol exists nowhere | new |

**Totals:** 4 High · 14 Medium · 8 Low — 7 confirmations of prior findings (all still present at `c7964dd`), 19 new.
