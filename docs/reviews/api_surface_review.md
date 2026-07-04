# API-Surface Consistency Review — the `zmart_controller` ↔ Leica `navigator_expert` seam

- **Scope:** (1) `zmart_controller/` — the contract it defines (ops table, `Session` surface, state-dict shapes, error surfacing, connection-dict schema); (2) `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` — its public surface (`zmart_adapter` ops, package `__init__.py` exports, `commands/*` public functions, `errors.py` taxonomy, return shapes, units and naming conventions). `zmart_drivers/mesospim/mesospim_zmart_adapter.py` and the mesoSPIM package were read as **context only** (the de-facto ecosystem yardstick); no findings target them.
- **Date:** 2026-07-03
- **Reviewed commit:** `c7964dd` (working tree == origin/main)
- **Inputs:** all prior reviews in `docs/reviews/` (ZC, LA, LC, LS, LM, LT, FD, RF, OP series). Findings below cross-reference rather than duplicate; the new material is the seam-wide consistency catalog (ops contract, return shapes, error taxonomy, units, naming) that no prior review assembled.

All driver paths are relative to `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` unless prefixed.

---

## Executive summary

The ops contract itself is in excellent shape: the Leica adapter implements **all 13 ops** (12 required + optional `disconnect`) with exactly matching names, arg names (`with_actuators`, keyword-only `acquire` args), handle-first calling convention, and µm units — verified op-by-op against `zmart_controller/registry.py:32-45` and `layer.py`, and pinned by a real-`Session` end-to-end test. There are **no YAGNI ops at the seam**: the adapter exposes nothing the controller never calls, and its package `__init__` re-exports exactly the ops table plus `CONNECTION`/`ZmartHandle`/`register`.

The problems live one level down, in the *semantics and shapes* that cross the seam:

1. **The `confirmed` bit is dropped at most of the seam's verification points** (AS-01, High). The driver's own contract (commands.py:25-28, README §5) says `success` = accepted, `confirmed` = verified — yet the adapter enforces `confirmed` only in `set_xyz`, while `set_state`, `acquire`'s job selection, both autofocus selections, and `capture.acquire` accept `success` alone. `set_state` then reports an unconfirmed job selection as "applied" — the wrong-job-acquisition failure the confirmation layer exists to prevent.
2. **The controller contract is silent about error behavior and several load-bearing dict shapes** (AS-02, AS-13, AS-21): both real adapters converged on raise-on-failure and on `{"name": ...}` procedure dicts, but nothing in `zmart_controller` says so — a third driver can legally diverge.
3. **One concept, several spellings**, catalogued in full below: frame positions appear as `{"value","unit"}` axis dicts *and* `_um`-suffixed keys inside the same adapter; the z drives have three names (`z-wide` / `zwide` / `z_wide_um`); `readers.get_xy` returns metres under bare `x`/`y` keys next to `x_um`; `get_state`'s observed report is half-translated (snake_case scalars next to raw PascalCase LAS X records).
4. **No typed error taxonomy crosses the seam** (AS-03): `commands/errors.py` is string classification only, and the adapter raises bare `RuntimeError`/`ValueError` for at least eight semantically distinct failure classes, so a generic caller must match prose — the same bug class RF-10 retires elsewhere.

One High, nine Medium, eleven Low findings. Facade pruning (LA-05/FD-05/RF-06) and `get_xyz` actuator semantics (LA-03) are cross-referenced with a seam-side sharpening, not re-litigated.

---

## 1. Ops-contract table

Controller contract: `zmart_controller/registry.py:32-45` (`OPS`, `disconnect` optional per :29-31), forwarding in `layer.py`. Leica implementation: `zmart_adapter/zmart_adapter.py` (registration at 1068-1093).

| Op | Controller expectation (layer.py) | Leica implementation (zmart_adapter.py) | Verdict |
|---|---|---|---|
| `connect` | receives connection dict untouched, returns opaque handle; raises when unreachable (layer.py:190-191) | `connect(connection) -> ZmartHandle` (253-280); propagates `connect_python_client` errors; degrades limits/calibration/origin loads with warnings | **Match.** Note: `output_root` (required by `acquire`) is not validated here — AS-19 |
| `disconnect` | optional; idempotence owned by `Session` (162-174) | `disconnect(handle)` marks closed (363-365); every op re-checks via `_require_open` (159-162) | **Match** (per-driver guard duplication is ZC-03/RF-15, controller-side) |
| `set_origin` | current position becomes (0,0,0); "returns whatever the driver reports" (50-58) | 444-489; captures XY + both z drives + objective, persists `origin.json` | **Match**, but the `"origin"` return key diverges semantically from the reference mock — AS-09 |
| `get_actuators` | per-axis option menu, e.g. `{"z": ["motoric","piezo"]}` (93-98) | 492-501: `{"x": ["motoric"], "y": ["motoric"], "z": ["z-wide","z-galvo"]}` | **Match** |
| `get_xyz` | per-axis position in frame µm; `with_actuators` "selects which actuator to read" (100-107) | 514-548: axis → `{"value","unit","actuator"}` + `objective_translation_um` + `hardware` | **Semantics gap:** `with_actuators` validate-and-echo only (LA-03 → AS-04); non-axis siblings pollute the axis namespace (AS-06) |
| `set_xyz` | absolute frame target, µm; `with_actuators` selects realizing actuator (109-118) | 551-615: frame→stage math, whole-move pre-flight, backlash transit; raises on failure/unconfirmed | **Match** — the seam's most rigorous op (both `success` and `confirmed` enforced, 603-604) |
| `get_acquisition_options` | options + active, forwarded live (122-130) | 623-647: `job` / `backlash_correction` / `strip_scan_fields` / `format` / `exporter` / `cleanup_source` | **Match** (menu keys are driver-owned by design) |
| `acquire` | keyword `acquisition_type` / `position_label` / `options`; label "names the position in the output filename" (132-151) | 705-782: validates options closed-world, strips scan fields, selects job, captures, saves | **Match** except: label→filename claim false for Leica (AS-10); job selection accepted-not-confirmed (AS-01) |
| `get_state` | opaque `{"changeable": ..., "observed": ...}` (62-70) | 790-833: `changeable={"job": name}`, rich observed report | **Match**; observed report is half-translated (AS-15); raises where `get_context` degrades (AS-17) |
| `set_state` | driver acts on `changeable` only; returns driver report (72-78) | 836-866: reapplies job selection with referent guard, returns `{"applied": ...}` | **Shape match**; unknown changeable keys silently ignored (AS-08); `confirmed` dropped (AS-01) |
| `get_procedures` | named procedures menu (80-82) | 869-883: `backlash_takeup`, `autofocus` (+`args`, `jobs`) | **Match**; descriptor schema unspecified controller-side (AS-21) |
| `set_procedure` | run a procedure dict (84-89) | 886-896 + `_run_autofocus` 899-945 | **Match**; result `"ran"` shape inconsistent (LA-10 → AS-12); `{"name": ...}` convention undocumented (AS-13) |
| `get_context` | read-only extras, opaque (155-160) | 1040-1065: `selected_job`, `scan_field`, `client`, `output_root`, `session_hash6` | **Match**; a `get_` op that writes files and can block ~60 s (LA-13 → AS-17) |

**Ops the adapter exposes that the controller never calls:** none. `zmart_adapter/__init__.py` exports exactly the 13 ops + `CONNECTION`, `ZmartHandle`, `register` — a coherent, minimal seam package. The [YAGNI] weight lives one level up, in the 216-name driver facade (AS-20, cross-ref LA-05/FD-05/RF-06).

---

## 2. Return-shape catalog

Every success/failure shape observable on the in-scope public surfaces.

| Surface | Function(s) | Success shape | Failure behavior |
|---|---|---|---|
| commands/* (setters, `move_xy`, `move_z`, `select_job`, `acquire`) | commands.py:120-1470 | `{"success", "confirmed", "message", "timing", "logs"}` (+`"position"` on `move_xy`) | same dict, `success=False` — **never raises** (contract at commands.py:25-28) |
| commands/* | `move_galvo_to_pixel` (commands.py:1142-1245) | `{"success", "pan", "delta_pan", "pan_scale_um", "message"}` | dict, `success=False` — **envelope break**, no `confirmed`/`timing`/`logs` (LC-23, cross-ref only) |
| commands/* | `prepare_select_job` no-op (confirm_select_job.py:340-357) | command-style dict without `timing` (stamped by caller) | `(None, context)` |
| commands/errors.py | `_default_error_check` (189-242) | `{"success", "error", "transient", "logs"}` | same dict shape |
| commands/errors.py | `_check_api_error` (111-181) | `None` on success | `{"error", "result", "result_code", "details"}` — **None-means-good** convention, inverse of everything above |
| readers (routed, plain) | `get_scan_status`, `get_jobs`, `get_selected_job`, ... (router.py) | plain value | `None` (fail-closed); router timeout loses diagnostics (LC-19) |
| readers (routed, `diagnostics=True`) | same | `Reading` dataclass (`value/source/observed_at/age_s/error`, router.py:28-35) | `Reading(value=None, error=...)` or bare `None` |
| readers | `get_xy` (api_reader.py:197-237) | `{"x", "y"}` **in metres** + `{"x_um", "y_um"}` | `None` |
| readers | `read_zwide_um` (router.py:435+) | float µm | **raises** `RuntimeError`/`ValueError` despite the no-raise docstring (LC-07) |
| scanfields | `save_experiment` | `bool` | `False` |
| scanfields | `strip_template`, `get_template_state` | dict / state token string (`"stripped"`, `"fresh"`, `"unreadable"`, ...) | `None` / token |
| acquisition | `capture.acquire` (capture.py:31-64) | `AcquisitionResult` dataclass | **raises** `RuntimeError` (checks `success` only — see AS-01) |
| acquisition | `save.save` (save.py:91-129) | `SavedAcquisition` (`image_paths`/`xml_paths` dicts) | **raises** |
| motion | `move_xy_with_backlash` (movement.py:40-107) | final `move_xy` result dict | **raises**, requires `success` **and** `confirmed` on both legs |
| motion | `correct_backlash` (movement.py:110-151) | **`None`** (implicit) | **raises**, requires `success` only — asymmetric with its sibling (AS-01, AS-18) |
| zmart_adapter | all 13 ops | op-specific dicts (see §1) | **raise** `RuntimeError`/`ValueError` — dict envelopes never cross the seam |

Three result idioms coexist on the driver's public surface — result-dict envelope (commands), `None`-fail-closed (readers), raise (motion/acquisition/adapter) — each internally justified, but the boundaries between them are documented nowhere and violated twice (`move_galvo_to_pixel`, `read_zwide_um`).

---

## 3. Naming and units catalog

### 3.1 Same concept, multiple names

| Concept | Spellings | Where |
|---|---|---|
| the z-wide drive | `"z-wide"` (actuator name) / `"zwide"` (`z_mode`) / `"z_wide_um"` (dict keys) / `"eUseZWide"` (LAS X enum, internal) | zmart_adapter.py:99,106,540-546; commands.py:1269 — AS-11 |
| position in frame µm | axis → `{"value": ..., "unit": "um"}` vs `{"x_um": ...}` vs flat `focus_um`/`frame_z_um` | zmart_adapter.py:535-538 vs 984-994 vs 939-945 — AS-05 |
| stage XY position | `x`/`y` **metres** and `x_um`/`y_um` in one dict | api_reader.py:224-229 — AS-07 |
| backlash-settle choice | option `backlash_correction` (bool) → record key `settle: "backlash-corrected"\|"direct"` | zmart_adapter.py:639,779; mock_driver.py:201,208 — AS-14 |
| "procedure" | named routine (`get_procedures`/`set_procedure`) vs saving-mode acquisition option (`"procedure": {"options": ["direct","tiled"]}`) | layer.py:80-89 vs layer.py:127, mock_driver.py:119, README.md:127,134 — AS-16 |
| saved output paths | Leica `images`/`xml` vs mock `filename` vs mesoSPIM `image_files`/`metadata_file` (context) | zmart_adapter.py:780-781; mock_driver.py:205 — no canonical shape; noted under AS-14 |
| job identity keys | adapter snake_case (`serial_number`) vs raw LAS X PascalCase (`Name`, `IsSelected`, `IsAutofocus`) in the same `observed` dict | zmart_adapter.py:812-824 — AS-15 |

### 3.2 Verb conventions

- Controller ops: strict `get_*`/`set_*` discover-then-apply (with the known `set_procedure`-runs / `set_instrument`-connects wrinkle, ZC-10).
- Routed readers: `get_*` ×12 + **`read_zwide_um`** + `ping` — one odd verb in an otherwise uniform family (readers/__init__.py:20-35) — AS-18.
- Commands: `set_*` ×21, `move_*` ×3, `acquire`, `select_job` — coherent.
- Symmetric pairs: `connect`/`disconnect` ✓, `save_experiment`/`load_experiment` ✓, `strip_template`/`restore_template` ✓, `lrp_set_*`/`lrp_verify_*` ✓. Asymmetries: `set_origin` has no `get_origin` (the reference is only visible in `set_origin`'s return and `get_state` is silent about it); `get_procedures` (plural) / `set_procedure` (singular); `move_xy_with_backlash` returns a result dict, `correct_backlash` returns `None`.
- Boolean option grammar mixes noun (`backlash_correction`), imperative (`strip_scan_fields`), and verb-noun (`cleanup_source`) in one menu (zmart_adapter.py:637-647) — AS-14.

### 3.3 Units

- Controller ⇄ adapter: µm everywhere, explicitly tagged (`"unit": "um"`) — consistent. Both frames documented in `_scan_field`'s `coordinate_spaces` block (zmart_adapter.py:1030-1034) — a good pattern worth copying.
- Driver internals: µm via `_um` suffix (dominant), **except** LAS X-native metres in `readers.get_xy["x"/"y"]` (AS-07) and the ROI/LRP layer (`um()` converter, `translation_x_m` — roi.py:111-112, 710-733, suffixed correctly there).
- `move_xy`/`move_z` accept `unit="um"|"mm"|"m"` (commands.py:1050, 1259-1269) — the only unit-parameterized functions; everything else is fixed-µm. The adapter always passes `unit="um"`.
- Time: `_ms` and `_s` suffixes used consistently (`api_delay_ms`, `settle_ms`, `poll_timeout` documented as seconds); `duration_s`, `total_s` suffixed. No findings.

---

## 4. Findings

Severity: **High** (wrong result reported across the seam), **Medium** (contract gap / consistency break with real misuse potential), **Low** (hygiene, doc drift).

### AS-01 — High — `confirmed` is enforced at only one of the seam's six verification points; `set_state` reports an unconfirmed job selection as applied

**File:** zmart_adapter.py:603-604 (enforced) vs 747-750, 862-864, 923-926, 933-936 (dropped); acquisition/capture.py:57-58; motion/movement.py:96-107 vs 146-151; contract at commands.py:25-28; profile default `success_on_unconfirmed: bool = True` at config/profiles.py:246 (SELECT_JOB at 449-458 inherits it).
**Problem:** The driver's own result contract is explicit: "``result['success']`` means the command was *accepted*, not that it took effect. A caller that needs proof the setting/move landed must check ``result['confirmed']``" (commands.py:25-28; README §5 makes the same warning). At the seam, only `set_xyz` honors this (`if not z_result.get("success") or not z_result.get("confirmed"): raise`, zmart_adapter.py:603-604), and `move_xy_with_backlash` (movement.py:96-107, with a comment explaining exactly why confirmed is required). Everywhere else the adapter tests `success` alone: `acquire`'s `select_job` (747-750), `set_state`'s `select_job` (862-864) — whose docstring promises "report what stuck" (837) — both autofocus selections (923-926, 933-936), and `capture.acquire` under the adapter (capture.py:57-58). Even within `motion/`, `correct_backlash` (146-151) checks `success` only while its sibling demands `confirmed` — yet an unconfirmed *return* leg leaves the stage displaced, the exact case the mesoSPIM `_settle` surfaces as an error (mesospim_zmart_adapter.py:564-566, context).
**Why it matters:** With `success_on_unconfirmed=True` (the shipped default for SELECT_JOB), a `select_job` that is accepted but never verified returns `success=True, confirmed=False`. The adapter then reports `{"applied": {"job": X}}` and `acquire` proceeds to capture — acquiring with the wrong job is the precise failure the driver's hybrid confirmation machinery (LC-02's subject) was built to prevent, silently re-opened at the seam by four `.get("success")` checks.
**Action:** Add one `_select_job_or_confirmed_raise(handle, job)` helper (also discharging LA-14's four-site duplication) that requires `success` **and** `confirmed`, and use it at all four selection sites; make `capture.acquire` and `correct_backlash` either check `confirmed` or carry a docstring sentence stating why acceptance suffices there (acquire has the export-completion wait as a backstop; say so). Add a unit test: `select_job` → `success=True, confirmed=False` must make `set_state` raise, not report applied.

### AS-02 — Medium — the controller contract never states how ops report failure; raise-on-failure is only a de-facto convention

**File:** zmart_controller/layer.py:73, 85-89, 112 ("return whatever the driver reports" — three times); registry.py:66-82 (`register` validates names only); README.md:175-196 ("Adding a microscope" — no error contract).
**Problem:** The controller documents the success path of every op but is silent on failure. Both real adapters and the mock independently converged on "ops raise; result-dict envelopes never cross the seam" (zmart_adapter raises `RuntimeError`/`ValueError` throughout; mock `_require_open` raises; mesoSPIM raises — context). Nothing prevents a third driver from returning `{"success": False}` dicts, which `Session` would forward as a perfectly truthy "report" and a workflow would treat as success.
**Why it matters:** This is the highest-leverage sentence the controller can add: the entire seam's error story currently rests on convention-by-imitation of `tests/mock_driver.py`. The mock is advertised as "a complete, readable reference implementation" (README.md:195-196) but its error behavior is nowhere stated to be normative.
**Action:** One paragraph in `registry.py`'s module docstring and README "Adding a microscope": *ops must raise on failure (any exception; `ValueError` for caller mistakes, `RuntimeError` for instrument/refusal failures) and must never encode failure in the returned dict.* Optionally assert it in the controller test suite against the mock.

### AS-03 — Medium — no typed error taxonomy crosses the seam; `errors.py` classifies strings, the adapter raises bare built-ins for eight distinct failure classes

**File:** commands/errors.py (whole file — zero exception classes; pattern lists at 31-51); zmart_adapter.py:162 (disconnected), 246-249 (limits unconfigured), 320-325 (cross-objective refusal), 478 (origin persist), 604 (unconfirmed move), 679-684 (template unreadable), 732-734 (missing output_root), 740 (no job), plus `ValueError`s at 509, 656-662, 854-861, 896, 916-919; the one typed exception is `shared/limits/spec.py:64` (`LimitViolation(RuntimeError)`).
**Problem:** The module named `errors.py` contains an error *taxonomy* only in the sense of transient-vs-permanent string patterns for LAS X messages; no exception types exist anywhere in the driver. Consequently every failure that crosses the seam is a bare `RuntimeError` (or `ValueError`), and semantically different situations — "refused fail-closed, fix config and retry" (246-249), "refused, re-set the origin" (320-325), "hardware move did not verify" (604), "unrecoverable mid-acquire" — are distinguishable only by parsing prose. That is the identical bug class RF-10 retires in the calibration UI (substring-matched English), now at the controller boundary. A workflow that wants "retry on transient, alert on refusal, abort on hardware failure" cannot be written robustly.
**Why it matters:** Errors are the part of the seam contract workflows automate against; string-matching `str(exc)` will silently reroute the first time a message is reworded (several already embed full result-dict reprs, e.g. 604, per LC-29's pattern).
**Action:** Introduce two or three adapter-level exception types (e.g. `DriverRefusal(RuntimeError)` for fail-closed/pre-flight refusals — limits, cross-objective, closed handle, missing output_root — vs plain `RuntimeError` for instrument failures), reusing `LimitViolation` where a limit is the cause; document them in the adapter module docstring. Controller-side, AS-02's paragraph should name the split so other drivers copy it.

### AS-04 — Medium **[YAGNI]** — `get_xyz(with_actuators=...)` has read semantics in the docs and in no driver, including the reference mock

**File:** zmart_controller/layer.py:100-107 ("selects which actuator to read per axis"); tests/mock_driver.py:161-169 (echo only — the mock stores one position; the chosen actuator never affects the value); zmart_adapter.py:514-548 (validate-and-echo, value is always the focus sum); consumers: only `zmart_controller/tests/test_layer.py:61` passes it on a read.
**Problem:** LA-03 filed the Leica-side mislabeling (the `actuator` tag misattributes the focus-sum reading). The seam-wide fact is stronger: *no* implementation in the ecosystem — not even the mock the docs call the reference — gives `with_actuators` any effect on a read, and no in-repo workflow passes it. The parameter is speculative API surface on `get_xyz` whose documented meaning has never been true anywhere.
**Why it matters:** The controller docstring promises per-actuator readings that a caller cannot obtain; each new driver must implement validate-and-echo boilerplate for a dead parameter, and the echoed `actuator` field actively misleads (LA-03).
**Action:** Controller-side (this is the clean fix LA-03 needs): drop `with_actuators` from `get_xyz` (keep it on `set_xyz`, where it is real), or redocument it as validation-only ("names must come from `get_actuators`; the reading itself is driver-defined"). Leica-side, on the first option the adapter deletes `_resolve_actuators` from the read path and reports a truthful per-axis source (e.g. `"actuator": "focus"` for z, per LA-03's recommendation).

### AS-05 — Medium — two-and-a-half encodings of "frame position in µm" inside one adapter surface

**File:** zmart_adapter.py:535-538 (`get_xyz`: axis → `{"value": ..., "unit": "um", ...}`) vs 984-994 (`_scan_field` entries: `frame: {"x_um", "y_um", "z_um"}`, `stage: {...}`) vs 939-945 (`_run_autofocus`: flat `focus_um` / `frame_z_um`) vs 486-489 (`set_origin`: `origin: {"x","y","z"}` unitless + `reference: {..._um}`).
**Problem:** The same quantity — a coordinate in the controller frame, micrometres — is spelled three ways by one module: structured axis dicts with a `unit` field (`get_xyz`), `_um`-suffixed flat keys (`scan_field`, autofocus, `hardware_targets`), and unsuffixed unitless keys (`set_origin`'s zero triple, `set_xyz`'s `position` echo). A caller consuming `get_context()["scan_field"]` positions to feed `set_xyz` must translate `frame["x_um"]` → `x`; a caller comparing `get_xyz()["z"]["value"]` with `_run_autofocus`'s `frame_z_um` must know they are the same convention under different shapes.
**Why it matters:** These values exist precisely to be piped into each other (`scan_field` docstring: "what set_xyz accepts", 1032). Every shape switch is a place for a silent 1e6 or key-name bug in workflow code.
**Action:** Pick one convention for controller-facing frame coordinates. Cheapest coherent rule: flat `_um` keys for everything except the `get_xyz`/`set_xyz` axis contract (which the mock fixes as `{"value","unit"}`), and state the rule once in the adapter module docstring. Renaming `set_origin`'s content-free zero triple away from `"origin"` also discharges AS-09.

### AS-06 — Medium — `get_xyz` mixes axis entries with non-axis metadata at the same dict level

**File:** zmart_adapter.py:539-547 (`result["objective_translation_um"] = ...; result["hardware"] = ...` as siblings of `"x"/"y"/"z"`); reference shapes: mock_driver.py:166-169 and mesospim_zmart_adapter.py:315-318 (axes only, context).
**Problem:** The de-facto `get_xyz` shape (mock, mesoSPIM) is "every key is an axis". Leica adds two sibling keys, so `for axis, entry in mic.get_xyz().items()` — the natural iteration the shape invites — crashes on `entry["value"]` for `objective_translation_um` (a list) and `hardware` (a dict). The controller docs ("Read the current position per axis", layer.py:101) give no warrant for non-axis keys.
**Why it matters:** This is the one op every workflow calls in a loop; the extras are valuable but placed where generic code trips over them.
**Action:** Nest the extras: move `objective_translation_um` inside `hardware` (it is hardware-frame bookkeeping), and either keep exactly one reserved non-axis key (`"hardware"`), documented in the controller docstring ("drivers may add a `hardware` sibling"), or nest both under it. `objective_translation_um` should also gain axis keys — it is currently a bare 3-list whose order the caller must guess (539).

### AS-07 — Medium — `readers.get_xy` returns metres under bare `x`/`y` keys next to `x_um`/`y_um`

**File:** readers/api_reader.py:224-229 (return dict), docstring at 204-205 ("dict with x/y in meters and microns").
**Problem:** On a public reader of a package whose every other coordinate is `_um`-suffixed µm, `get_xy(...)["x"]` is a plausible-looking micrometre read that is six orders of magnitude off. The only guard is one docstring line; the key itself carries no unit, violating the package's otherwise-strict suffix convention (`x_um`, `z_wide_um`, `tile_w_um`, ...). The bare keys are LAS X's native unit leaking through the reader unrenamed.
**Why it matters:** In-repo callers all use `x_um` (movement.py:142, zmart_adapter.py:401), so the metre keys are simultaneously a trap and nearly dead weight — the worst combination. `get_xy` is exported on the package root and documented public surface (README), so operator notebooks are the likely victims.
**Action:** Rename to `x_m`/`y_m` (mechanical; grep shows no in-repo consumer of the bare keys) or drop them and keep only `_um`. If the raw-metres reading must stay for LAS X parity, the suffix says so at every use site.

### AS-08 — Medium — `set_state` silently ignores unknown changeable keys while `acquire` validates its options closed-world

**File:** zmart_adapter.py:846-866 (`set_state`: only `"job"` is read; anything else in `changeable` is dropped without notice) vs 650-663 (`_with_defaults`: unknown option key or value → `ValueError`).
**Problem:** The adapter's two "apply a dict" ops have opposite strictness. `acquire(options={"jbo": ...})` fails loudly; `set_state({"changeable": {"jbo": ..., "laser_power": 2.0}})` returns `{"applied": {}}` with success. Because `get_state`/`set_state` is the round-trip pair workflows lean on (README.md:110-121 even shows editing a changeable key), a driver-version drift or a typo silently reapplies nothing — the state restore *appears* to succeed while restoring no setting. The mesoSPIM adapter filters silently too (context), so today's ecosystem convention is the unsafe one; the Leica adapter is the right place to set the better precedent since its changeable surface is a single known key.
**Why it matters:** A silent no-op on the op whose entire purpose is "reapply exactly what was captured" defeats discover-then-apply; the failure is invisible until an acquisition runs with the wrong setup.
**Action:** In `set_state`, reject unknown `changeable` keys with a `ValueError` naming the supported set (`{"job"}`), mirroring `_with_defaults`. Controller-side (optional): one sentence in `layer.py:72-78` that drivers should refuse changeable keys they cannot reapply.

### AS-09 — Medium — `set_origin`'s `"origin"` return key means "frame zeros" in Leica and "raw stage coordinates" in the reference mock

**File:** zmart_adapter.py:485-489 (`"origin": {"x": 0.0, "y": 0.0, "z": 0.0}` + `"reference"` + `"origin_file"`) vs zmart_controller/tests/mock_driver.py:95-101 (`"origin": {raw stage position}`); mesoSPIM returns raw too (mesospim_zmart_adapter.py:281, context).
**Problem:** The same key in the same op's return carries opposite meanings across the two in-scope implementations: the mock (advertised as the reference implementation, README.md:195-196) reports the captured raw position under `"origin"`, Leica reports the constant zero triple and puts the captured reference under `"reference"`. A workflow written against the mock that logs `result["origin"]` as "where the origin physically is" gets `(0,0,0)` from Leica, always.
**Why it matters:** `set_origin` is step 2 of the documented workflow; its return is the only place the frame reference is surfaced at all (there is no `get_origin`). The Leica zero triple carries no information — it is true by definition.
**Action:** Leica: drop the constant `"origin"` zeros (or rename to make the tautology visible) and report the captured reference under `"origin"` like the reference driver, keeping `"origin_file"`. Alternatively controller-side: document the expected `set_origin` return keys in `layer.py:50-58` and align the mock — either way, one meaning per key.

### AS-10 — Medium — controller docs promise `position_label` "names the output file"; the Leica filename carries a Naming `p` slot instead

**File:** zmart_controller/README.md:129 ("`position_label` names the output file"), layer.py:141-142 ("names the position in the output filename"); Leica: zmart_adapter.py:757-772 (`_assign_p_slot` → `Naming(..., p=p)`; the label travels only in the `lineage` record written to `summary.json`), documented at 718-723.
**Problem:** For the only real driver, a non-numeric label ("tumor-edge") appears in **no** filename; the file is named by an auto-assigned integer slot, and the label→slot mapping is recoverable only from `summary.json` (with the retry/burned-slot edges LA-17 catalogs). The controller-level promise is the shape workflows will code against ("find my file by label").
**Why it matters:** Contract drift at the acquire op — the seam's payload op — between what the two in-scope components say. The mock incidentally *does* put the label in `filename` (mock_driver.py:205), reinforcing the false expectation offline.
**Action:** Controller-side one-line fix: "names the position; how it appears in output naming is driver-defined — the driver's record links label to files." Or Leica-side: include a sanitized label in the Naming slots. The doc fix is cheaper and honest; pair it with LA-17's docstring additions.

### AS-11 — Low — the z drives have three public spellings: `z-wide`/`z-galvo`, `zwide`/`galvo`, `z_wide_um`/`z_galvo_um`

**File:** zmart_adapter.py:99 (actuator names), 106 (`_Z_MODES` translation table), 540-546 (`hardware` keys); commands.py:1269 (`z_mode` values `"galvo"`/`"zwide"`).
**Problem:** A single controller caller sees two of the spellings in one `get_xyz` result (`actuator: "z-wide"` next to `hardware["z_wide_um"]`); a caller dropping down to the driver API must learn the third (`move_z(..., z_mode="zwide")`). `_Z_MODES` exists purely to translate the adapter's own vocabulary into the driver's.
**Why it matters:** Small, but it is exactly the kind of token that gets typed into config/procedure dicts by hand; three near-identical spellings guarantee occasional `ValueError`s and grep misses.
**Action:** Pick the kebab actuator names as the public tokens (they are what `get_actuators` advertises) and accept them in `move_z`'s `z_mode` (alias, one release), or at minimum note the mapping in `get_actuators`'s docstring. The `_um` snake keys can stay (suffix convention governs them).

### AS-12 — Low — `set_procedure` result `"ran"` has three shapes across the ecosystem and two within Leica

**File:** zmart_adapter.py:893 (`{"ran": dict(procedure)}`) vs 939-945 (`{"ran": "autofocus", ...}`); zmart_controller/tests/mock_driver.py:255 (`{"ran": dict(procedure)}`); mesoSPIM `{"ran": name, ...}` (context). Extends LA-10.
**Problem:** LA-10 filed the intra-Leica split. The seam-wide addition: the controller's reference mock pins the *dict* shape while the other real adapter pins the *string* shape, so there is no canonical to converge on — each new driver flips a coin.
**Action:** Controller-side: bless `{"ran": <procedure name>, ...}` in `layer.py:84-89`'s docstring and update the mock; Leica unifies per LA-10. One sentence + two one-line changes.

### AS-13 — Low — the `{"name": ...}` procedure-dict convention is load-bearing in every driver and documented in none of the contract

**File:** zmart_controller/layer.py:84-89 ("Its meaning is encoded in the dict and run by the driver"); consumers: zmart_adapter.py:890 (`procedure.get("name")`), mock (implicitly any dict), mesoSPIM :412 (context); the convention appears only in a README example (README.md:146).
**Problem:** Both real adapters dispatch on `procedure["name"]` matched against `get_procedures()` keys, and raise `ValueError` otherwise — that *is* the seam contract, but the controller calls the dict opaque. A driver author reading only `layer.py` has no reason to use `"name"`, and a workflow author has no promise that `get_procedures()` keys are valid `"name"` values.
**Action:** Two sentences in `layer.py:84-89` / README §6: `set_procedure` takes `{"name": <key from get_procedures()>, **args}`; extra keys are procedure-specific per the descriptor's `args`.

### AS-14 — Low — the acquire record re-encodes one option under an invented name (`settle`) and echoes the rest partially

**File:** zmart_adapter.py:774-782 (echoes `format` and the derived `settle`, omits `exporter`/`cleanup_source`/`strip_scan_fields`); option grammar at 637-647 (`backlash_correction` noun / `strip_scan_fields` imperative / `cleanup_source` verb-noun); same `settle` re-encoding in the in-scope mock (mock_driver.py:201, 208).
**Problem:** A caller reconciling "what I asked for" with "what ran" must know that the boolean option `backlash_correction` comes back as the string `settle: "backlash-corrected"|"direct"`, that `format` echoes under its own name, and that the other three resolved options are not echoed at all. The record is the acquisition's provenance at the controller level; partial, renamed echo makes it unreliable for exactly that.
**Action:** Echo the full resolved options dict under one key (`"options": resolved`) and drop the `settle` translation (in the mock too — it is in scope); keep `format` top-level if existing consumers depend on it. Independently, when an option is next renamed, prefer one grammatical convention (noun phrases) for menu keys.

### AS-15 — Low — `get_state().observed` is half-translated: snake_case scalars beside raw PascalCase LAS X records and positional pairs

**File:** zmart_adapter.py:812-831 — `serial_number`/`system_type`/`stand` translated from `SerialNumber`/`SystemType`/`microscope.name`; `job`/`jobs`/`autofocus_jobs` passed through with LAS X keys (`Name`, `IsSelected`, `IsAutofocus`, `IsPattern`, `RotationAngle`); `objectives` as unlabeled 2-lists `[slotIndex, objectiveNumber]` (818-821).
**Problem:** `observed` is contractually opaque (layer.py:66-69), so nothing is *broken* — but the dict teaches two key conventions at once, and the `objectives` pairs force positional guessing where every neighbor uses names. Consumers (dashboards, state-diff tools) will inevitably read it; half-translation invites them to depend on both vocabularies, doubling the breakage surface when either side changes.
**Action:** Pick a rule and state it in the docstring: vendor records ride verbatim under clearly vendor-named keys (e.g. `lasx_job`, `lasx_jobs`) while everything the adapter authors is snake_case; give `objectives` entries keys (`{"slot": ..., "objective_number": ...}`).

### AS-16 — Low — "procedure" means two unrelated things on the controller surface

**File:** zmart_controller/layer.py:80-89 (`get_procedures`/`set_procedure`: named routines) vs layer.py:127 and tests/mock_driver.py:119, README.md:127,134 (acquisition *saving* option `"procedure": {"options": ["direct","tiled"]}`).
**Problem:** The mock's acquisition-options menu — the offline reference every new user runs — contains an option literally named `procedure`, in the same docs that define procedures as runnable routines. The Leica adapter had to avoid the collision (`exporter`, zmart_adapter.py:642-645).
**Action:** Rename the mock option (`save_procedure`, or align with Leica's `exporter`) and fix the example key in layer.py:127 and README.md:127/134. Pure controller-side doc/mock change.

### AS-17 — Low — read-op error postures are opposite and undocumented: `get_state` raises, `get_context` degrades — and `get_context` is a `get_` with a side effect

**File:** zmart_adapter.py:806-808 (`get_state` raises when the selected job is unreadable) vs 1040-1065 (`get_context` "degrades instead of raising"; uneven inner rules per LA-13); `_scan_field` saves the live experiment to disk (966-977, acknowledged at 1046-1047) and can block ~60 s (LA-13).
**Problem:** Two read-only reporting ops, opposite failure behavior, chosen sensibly (state must be truthful; context is informational) but recorded nowhere a controller caller looks. Separately, `get_context` performing a `save_experiment` breaks the `get_` = side-effect-free reading a discover-then-apply surface teaches — the docstring's "a save, not a state change" (1047) is honest but only visible driver-side.
**Action:** One sentence each in the two op docstrings *and* in the controller's `get_context` docstring (layer.py:155-160): context is best-effort and may be slow/entail a driver-side flush; state raises when it cannot be read truthfully. Unify `get_context`'s two inner degrade rules per LA-13.

### AS-18 — Low — verb and symmetry stragglers on the driver public surface

**File:** readers/__init__.py:20-35 (`read_zwide_um` among twelve `get_*` readers); motion/movement.py:107 vs 151 (`move_xy_with_backlash` returns the final result dict, `correct_backlash` returns `None`); commands.py:1411 (`select_job`, the one non-`set_/move_` mutator — acceptable, listed for completeness).
**Problem:** `read_zwide_um` is the sole `read_` verb in the routed-reader family (and the sole one that raises, LC-07 — the naming outlier and the contract outlier are the same function, which is at least consistent in its inconsistency). The backlash pair differ in return shape for no stated reason.
**Action:** When LC-07 is resolved, rename to `get_zwide_um` (alias one release) so verb == family; have `correct_backlash` return the final `move_xy` result like its sibling (callers ignore it today, so this is free).

### AS-19 — Low — connection-dict schema: `output_root` is a required-for-acquire key shipped as `None` and validated only mid-experiment

**File:** zmart_adapter.py:96 (`"output_root": None,  # required by acquire()`), 730-734 (validation at first `acquire`); controller docs on editing connection dicts at registry.py:85-92 / README.md:73-78; README drift already filed as ZC-05.
**Problem:** The schema encodes "required later" as a `None` placeholder plus a comment. A workflow that connects, sets origin, moves (all fine) then calls `acquire` fails only at that point — after hardware has moved. The failure message is good (732-734); its timing is the issue. Nothing on the controller side lets a driver declare "this key must be filled before connect for full function".
**Action:** Leica-side, cheap: `connect()` logs a warning when `output_root` is unset ("read-only session: acquire will refuse until connection['output_root'] is set"), preserving read-only use. Controller-side, optional: a `# required for acquire` comment convention in `get_instruments()` docs is enough — no schema machinery warranted.

### AS-20 — Low **[YAGNI]** — the seam needs zero package-root exports; the 216-name facade is entirely non-seam surface (endorse RF-06), and it exports a hazardous name (`um`)

**File:** `__init__.py:19-258` (`__all__`); the adapter imports every dependency from submodules, never the root (zmart_adapter.py:74-85); `um` exported at `__init__.py:176` ← experimental/lrp_edits/roi.py:111-112 (converts µm → **metres**).
**Problem:** LA-05/LA-06/FD-05 counted the dead exports and RF-06 designed the prune; this review adds the seam datum: the controller path consumes **no** root export — the facade is 100 % operator-notebook surface, so pruning it cannot affect the seam. One export deserves singling out beyond the prior counts: a function named `um` that *returns metres* sits on the package root, one `drv.um(50)` away from a 1e6 coordinate error in a notebook, compounding AS-07's bare-metre keys.
**Action:** Execute RF-06 (public surface = README-documented ∩ consumed, ~80 names; drop underscore names, `log`, and the `lrp_*`/ROI/OME blocks to their submodules). Whatever the final list, `um` should not survive on the root under that name — `to_metres`/`um_to_m` in `lrp_edits` is the honest spelling.

### AS-21 — Low — `get_procedures` descriptor schema is unspecified; `args` declarations already diverge

**File:** zmart_adapter.py:869-883 (`backlash_takeup`: description only; `autofocus`: `description` + `args: ["job"]` + `jobs: [...]`); mock_driver.py:243-249 (description only); mesoSPIM `args: ["value"]` (context); controller says only "The named procedures the driver offers" (layer.py:80-82).
**Problem:** The descriptor is the discover half of discover-then-apply for procedures, and nothing defines its keys: is `args` a list of accepted dict keys? Are extra menu keys (Leica's `jobs`) allowed? Can a caller programmatically build the `set_procedure` dict from the descriptor? Today the answer differs per driver, so generic procedure UIs cannot exist.
**Action:** Controller-side, minimal: document `{"<name>": {"description": str, "args": [accepted keys...], ...driver extras}}` in `layer.py:80-82`, with `args` optional-empty. Leica already fits; the mock gains nothing but conformity.

---

## 5. Summary table

| ID | Severity | Side | Title |
|-------|----------|------|-------|
| AS-01 | High | Leica | `confirmed` enforced at one of six seam verification points; `set_state`/`acquire` treat accepted-unconfirmed `select_job` as applied |
| AS-02 | Medium | Controller | Op failure behavior (raise vs error-dict) never stated; raise-on-failure is convention-by-imitation |
| AS-03 | Medium | Leica | No typed exceptions cross the seam; `errors.py` is string patterns; 8+ failure classes share bare `RuntimeError` |
| AS-04 | Medium | Controller | **[YAGNI]** `get_xyz(with_actuators=)` read semantics implemented by no driver, incl. the reference mock (completes LA-03) |
| AS-05 | Medium | Leica | Frame-µm coordinates spelled three ways inside one adapter (`{"value","unit"}` vs `_um` keys vs unitless) |
| AS-06 | Medium | Leica | `get_xyz` mixes axis entries with non-axis siblings (`hardware`, bare 3-list `objective_translation_um`) |
| AS-07 | Medium | Leica | `readers.get_xy` returns metres under bare `x`/`y` next to `x_um` — a 1e6 trap on the documented surface |
| AS-08 | Medium | Leica | `set_state` silently drops unknown changeable keys while `acquire` options are closed-world validated |
| AS-09 | Medium | Both | `set_origin`'s `"origin"` key: frame zeros (Leica) vs raw stage position (reference mock) — same key, opposite meanings |
| AS-10 | Medium | Controller | Docs promise `position_label` names the output file; Leica filenames carry the Naming `p` slot (label only in `summary.json`) |
| AS-11 | Low | Leica | z drives have three public spellings (`z-wide` / `zwide` / `z_wide_um`) |
| AS-12 | Low | Both | `set_procedure` `"ran"` shape: three variants across ecosystem, no canonical (extends LA-10) |
| AS-13 | Low | Controller | Load-bearing `{"name": ...}` procedure convention undocumented in the contract |
| AS-14 | Low | Both | Acquire record renames one option (`settle`) and echoes the rest partially; mixed option-name grammar |
| AS-15 | Low | Leica | `observed` state half-translated: snake_case scalars beside PascalCase LAS X records and unlabeled pairs |
| AS-16 | Low | Controller | "procedure" doubles as routine concept and mock saving-option name |
| AS-17 | Low | Leica | `get_state` raises / `get_context` degrades — undocumented split; `get_context` is a `get_` with a disk-write side effect |
| AS-18 | Low | Leica | Verb/symmetry stragglers: `read_zwide_um` among `get_*`; backlash pair return-shape asymmetry |
| AS-19 | Low | Both | `output_root` required-but-`None` connection key validated only at first `acquire` |
| AS-20 | Low | Leica | **[YAGNI]** Facade is 100 % non-seam surface — endorse RF-06; root-level `um` converts *to metres* |
| AS-21 | Low | Controller | `get_procedures` descriptor schema unspecified; `args` forms already diverge |
