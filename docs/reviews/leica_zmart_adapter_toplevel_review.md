# Review 5 — Leica Stellaris5 driver: `zmart_adapter/` + package top-level files

- **Scope:** `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` — `zmart_adapter/` (both files), top-level `__init__.py`, `utils.py`, `_file_utils.py`, `run_ci.py`, `conftest.py`, `pytest.ini`, `.coveragerc`, `README.md`, `requirements-dev.txt`, plus the unit tests pinning these modules (`tests/unit/test_zmart_adapter.py`, `test_driver_bootstrap.py`, `test_validate_hardware_cli.py`). Controller context (`zmart_controller/layer.py`, `registry.py`, `__init__.py`) and the sibling `zmart_drivers/mesospim/mesospim_zmart_adapter.py` were read for seam judgment only; findings below are Leica-side.
- **Date:** 2026-07-03
- **Reviewed commit:** `c7964dd`

All paths below are relative to `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` unless prefixed with `zmart_controller/` or `shared/`.

---

## Executive summary

The adapter is the strongest seam file in the driver: it implements the controller's 13-op contract exactly (verified against `zmart_controller/registry.py:32-45` and `layer.py`), owns the frame math with dated design decisions written into docstrings, and has a genuinely well-thought-out safety posture — fail-closed function limits with a completeness guard, whole-move pre-flight before any motion, loud degradation on reads vs. hard refusal on moves. The test file backing it is one of the better ones in the repo (round-trip property test, end-to-end pass through a real controller `Session`).

The most important defect is that the adapter **ignores the machine's calibrated backlash parameters**: `move_xy_with_backlash` / `correct_backlash` are called bare (zmart_adapter.py:600, 753, 892) although `connect` loads the very `stage_cfg` that carries `backlash{overshoot_um, settle_ms, tolerance_um}`, and `motion/movement.py:24-26,131-135` explicitly says production paths must pass it. Today the bundled values coincide with the hard-coded defaults, so the bug is silent — exactly the failure mode the snapshot system exists to prevent.

Second theme: **dead-in-production defensive shape handling** in `_z_um_from_settings`, which the unit tests then "cover" only by patching out the real normalizer — the adapter's actual production interaction with `make_changeable_copy` is untested.

Third theme: the top-level `__init__.py` is a 533-line facade in which **136 of 216 `__all__` names are never consumed via the package root anywhere in the repo**, 14 of them underscore-private — a large drift surface for very little demonstrated value. `utils.py` documents a tuning mechanism ("import and override" `RECEIPT_TIMEOUT`/`CONFIRM_POLL_S`) that cannot work because every consumer binds the values at import time, and ships a galvo constant measured on a *different instrument*.

No Critical findings. One High, seven Medium, twenty Low.

---

## What works well

- **Exact, minimal controller seam.** `register()` (zmart_adapter.py:1068-1087) supplies every op in `zmart_controller/registry.py:32-45` plus optional `disconnect`; signatures line up with `layer.py`'s forwarding (keyword `with_actuators`, keyword-only `acquire` args). `tests/unit/test_zmart_adapter.py:109-117` pins the registration, and `test_full_controller_session_flow` (935-970) drives the adapter through a *real* `Session`, not a mock of the controller — the seam itself is under test.
- **The `_MUTATING_OPS` completeness contract.** zmart_adapter.py:108-111 declares the mutating ops; `shared/limits/spec.py:235-247` rejects a limits file that misses (or typos) one; `test_bundled_file_covers_every_mutating_op` (test_zmart_adapter.py:976-982) makes "new mutating op without a reviewed limit entry" a failing test. This is cheap, effective safety engineering.
- **Deliberate, documented degradation split.** Reads degrade loudly (`_delta_or_warn`, zmart_adapter.py:409-420: "a read cannot land the stage anywhere wrong"), moves refuse (`_objective_delta_um` raising, 306-327), and every connect-time loader states its posture in the docstring (`_configure_stage_limits` 170-197, `_load_function_limits` 200-235, `_restore_persisted_origin` 333-360). The broad `except Exception` blocks all carry `noqa: BLE001` with a reason and a warning log — this is the right way to do defensive catching.
- **Whole-move pre-flight.** `set_xyz` (zmart_adapter.py:582-597) checks XY *and* the decomposed z target against both limit layers before anything travels, so "a doomed z leg can never leave the stage at a new XY with the old focus", and the refusal message names the actionable alternative actuator. Pinned by tests at test_zmart_adapter.py:877-891 and 1002-1018 (including the hint text).
- **Race-preventing ordering with comments that say why.** Strip before select because stripping reloads the experiment (743-745); read the autofocus focus result *before* restoring the selection because restoring can reposition (929-931); `set_origin` persists loudly and explains why silent divergence is worse (474-478).
- **Frame design provenance.** The module docstring (zmart_adapter.py:1-59) records the z-focus model, the operator decisions with dates (2026-07-02), the unvalidated physical assumption (additivity), and the live validator that covers the arithmetic. `TestObjectiveCompensation.test_round_trip_property_across_objectives` (test_zmart_adapter.py:802-841) is a real property test of the frame math.
- **`run_ci.py` is a good CI definition, not a shell script in Python.** Structured per-step records, honest exit code, machine-readable `ci_summary.json`/`env.json`, graceful degradation when ruff/pytest-cov are missing (171-190, 219-222), and an explicit, correct reconciliation with `pytest.ini` (pytest.ini:17-20 explains why junit/coverage paths live in run_ci, not addopts). The online steps reference flags that actually exist in the hardware scripts (verified against `tests/hardware/validate_zmart_adapter.py:453-487`, `validate_hardware.py:1302`).
- **`conftest.py` (package root) is small and high-leverage:** one autouse fixture pointing `SMART_MICROSCOPY_ROOT` at an empty tmp dir keeps every test hermetic against `C:\ProgramData` (conftest.py:8-21), and it works because `MachineProfile.root()` reads the env var per call (config/machine.py:109-113).
- **`requirements-dev.txt` traces every heavy dependency** to the code that reaches it (requirements-dev.txt:8-12, 24-31) — the opposite of dependency rot.
- **`README.md` is exceptional driver documentation:** the result-envelope table (§5), the `success` vs `confirmed` warning, and the numbered "silently misbehave" invariants (§10) encode exactly the knowledge a new operator needs.

---

## Findings

### LA-01 — High — calibrated backlash parameters are silently ignored on the controller path
**File:** zmart_adapter.py:600, 753, 892 (with connect at 271-280).
**Problem:** `set_xyz` calls `_motion.move_xy_with_backlash(handle.client, abs_x, abs_y)` and `acquire`/`set_procedure` call `_motion.correct_backlash(handle.client)` with no backlash arguments, so the hard-coded fallbacks run (`overshoot_um=50, settle_ms=100`, profile tolerance). `motion/movement.py:24-26` and 131-135 state explicitly: "Production paths should pass calibrated values from `stage_cfg['backlash']` loaded via `motion.stage_config.load`". The adapter *has* that config in hand — `_configure_stage_limits()` returns the loaded `stage_cfg` (zmart_adapter.py:188-190) — and then uses it only for the limits overlay, dropping the `backlash` block that `stage_config.load()` validates and returns (motion/stage_config.py:129-142, 188-192).
**Why it matters:** Today the bundled calibration's backlash (`calibration/defaults/calibration.json`: 50/100/20) coincides with the fallbacks, so nothing visibly breaks — which is precisely the trap. The first machine snapshot that adopts a different measured backlash (larger overshoot, tighter tolerance) will be silently ignored by every controller-driven move and settle, defeating the point of the snapshot system and of the `tolerance_um` confirmation contract.
**Action:** Keep `stage_cfg` (or just its `backlash` block) on `ZmartHandle` at connect, and thread it through: `move_xy_with_backlash(..., overshoot_um=b["overshoot_um"], settle_ms=b["settle_ms"], tolerance_um=b["tolerance_um"])` and the same for both `correct_backlash` call sites. Add a unit test asserting the calibrated values reach the motion layer.

### LA-02 — Medium — `_z_um_from_settings` handles a settings shape that production never produces **[PATCHWORK]**
**File:** zmart_adapter.py:373-383 (the `isinstance(val, dict)` branch at 379-380).
**Problem:** The real `make_changeable_copy` normalizes `ch["zPosition"][key]` to a *float or None* (`commands/settings.py:139-145`: `_safe_float(entry.get("position"))`). The adapter nevertheless guards `if isinstance(val, dict): val = val.get("position")` — a branch that can only fire when `make_changeable_copy` is replaced by something returning the raw shape. That is exactly what the tests do (`_patch_position` patches it to identity, test_zmart_adapter.py:84-87), so the dead branch is "covered" while the production shape is not (see LA-24).
**Why it matters:** Dual-shape tolerance hides which contract the adapter actually depends on. If the normalizer's output changes, the adapter's behavior changes with no failing test; meanwhile the extra branch reads as if the raw shape were a supported input.
**Action:** Delete the `isinstance(val, dict)` branch and let the adapter consume only the normalized float/None contract; fix the tests to feed the real normalized shape (or call the real `make_changeable_copy`).

### LA-03 — Medium — `get_xyz`'s `with_actuators` selects nothing; the result's `actuator` tag misattributes the reading
**File:** zmart_adapter.py:514-548 (echo at 535-538); contract at `zmart_controller/layer.py:100-107`.
**Problem:** The controller documents `with_actuators` on `get_xyz` as "selects which actuator to read per axis". In this adapter the returned `z` value is always the focus sum of *both* drives (529-533) — by design — yet the result tags each axis with the chosen/default actuator (`{"value": ..., "actuator": "z-wide"}`), implying the value came from that single drive. The parameter's only effect is validation and echo.
**Why it matters:** A controller-side caller that reads `z-galvo` "per the menu" gets the same number as `z-wide` and a label claiming otherwise; the per-drive truth is only under `"hardware"`. That is a quiet contract mismatch at the exact seam this module exists to keep honest.
**Action:** Either report the z actuator as something truthful (e.g. `"focus"`/both drive names) with a docstring note that per-drive readings live under `hardware`, or make the chosen z actuator select which raw drive is reported alongside the frame value. At minimum, stop echoing an actuator that did not determine the value.

### LA-04 — Medium — restored origin is checked for key presence but not numeric type
**File:** zmart_adapter.py:333-360 (presence check 348, adoption 355); contrast mesospim_zmart_adapter.py:240-246.
**Problem:** `_restore_persisted_origin` verifies all `_ORIGIN_KEYS` exist, then adopts the dict verbatim. `origin.json` is hand-editable machine-local state; a value like `"x_um": "1000"` (string) passes the check and then every `get_xyz`/`set_xyz` dies with a bare `TypeError` in the frame arithmetic (531-533) instead of the documented "frame stays absolute" degrade. The sibling adapter coerces with `float(...)` and catches `(KeyError, TypeError, ValueError)`.
**Why it matters:** The function's whole purpose is "malformed origin must not poison the frame" (docstring 336-339, and test_zmart_adapter.py:197-206 pins the missing-key case) — the type-corruption case slips through the same guard.
**Action:** Coerce each `_ORIGIN_KEYS` value with `float(...)` inside the existing try/degrade, as mesospim does; keep `objective` as-is.

### LA-05 — Medium — 136 of 216 package-root exports are never consumed via the package root **[YAGNI]**
**File:** `__init__.py:19-258` (`__all__`), imports 277-527.
**Problem:** A repo-wide scan of `from navigator_expert import X` / `drv.X` usage (workflows, notebooks, tests, hardware scripts) shows 136 of the 216 `__all__` names are never accessed through the package root — including the entire `lrp_*` block (~85 names), all ROI authoring helpers (`make_star`, `COLOR_YELLOW`, `argb_color`, ...), the OME check/fix septet, and constants like `LIMITS_SOURCE_MIGRATION`. Consumers that use these do so via submodule imports, which keep working regardless of the facade.
**Why it matters:** This is the maintenance tax the maintainer asked to be allergic to: every new symbol must be added in two places (README §11 step 4 even mandates it), the file needs blanket `# ruff: noqa: E402,I001,F401` (line 1) to exist, and the facade silently drifts from reality (see LA-07 for the mislabeled groupings already present).
**Action:** Prune `__all__` to the surface that is documented in README *and* consumed (connection, readers, commands, motion, acquire/save, template state ops); let specialist surfaces (`lrp_*`, ROI, OME fix) be imported from their submodules, which the code already does everywhere. If the full facade is a deliberate operator-notebook contract, generate it from the submodules' own `__all__`s so it cannot drift.

### LA-06 — Medium — 14 underscore-private names exported in `__all__`
**File:** `__init__.py:32-48, 77-80` (`_safe_float`, `_hw_get`, `_make_timing`, `_make_log_entry`, `_is_transient_error`, `_check_api_error`, `_default_error_check`, `_PERMANENT_PATTERNS`, `_TRANSIENT_PATTERNS`, `_stage_limits`, `_check_xy_limits`, `_check_z_limits`, `_readback`, `_fire_with_receipt`).
**Problem:** A leading underscore says "not API"; `__all__` says "API". Exporting the *mutable module dict* `_stage_limits` is the worst of these — package consumers can rebind/clear the process-global safety envelope through the public surface.
**Why it matters:** The contradiction makes it impossible to know what is stable. Internal helpers (`_make_timing`) will be depended on; refactors then break "private" code.
**Action:** Drop the underscore names from `__all__` (internal callers already import from the owning modules). For anything genuinely public (`_readback`? the comment at `__init__.py:76` says it is), rename it without the underscore.

### LA-07 — Medium — `utils.py` documents a tuning mechanism that cannot work
**File:** utils.py:16-23; consumers `config/profiles.py:59,235,244`, `commands/dispatch.py:51,112`, `readers/api_reader.py:42`, `scanfields/files.py:19`, `commands/confirmations.py:46`.
**Problem:** "Import and override these to tune for your hardware" — but every consumer does `from ..utils import RECEIPT_TIMEOUT` (binding the int at import time), and `CommandProfile` freezes them into dataclass field defaults at class-definition time (profiles.py:235, 244). Rebinding `navigator_expert.utils.RECEIPT_TIMEOUT` after the package imports (which happens all at once via `__init__.py`) changes nothing.
**Why it matters:** An operator on slow hardware follows the documented instruction, observes no effect, and has no error telling them why. Broken tuning advice on a timeout is worse than none.
**Action:** Either fix the docs to say these are edit-the-source constants, or make them real knobs: have consumers read `utils.RECEIPT_TIMEOUT` at call time (module-attribute access) or route both values through a profile object that is already the documented tuning surface (README §8).

### LA-08 — Medium — galvo pan constants measured on a different instrument, hard-coded outside the machine-snapshot system
**File:** utils.py:65-71 (`PAN_LIMIT = 0.00775`, `GALVO_FIELD_FRACTION = 0.667`).
**Problem:** The comment itself warns: "the committed value was measured on the ZMB STELLARIS 8 while this driver targets the STELLARIS 5 (y42h93). Unlike image_to_stage and backlash it does not route through the machine calibration snapshots, so a per-scope error can only be corrected by editing this constant." So galvo-pan targeting (`move_galvo_to_pixel`, `galvo_pan_for_pixel`, ROI pan math) runs on another scope's calibration with no machine-local override path.
**Why it matters:** This is exactly the class of scope-specific truth the driver already solved with `config/machine.py` snapshots; leaving one calibrated quantity as a source-code constant guarantees the "silently misbehaves" failure README §10 warns about, on a targeting path.
**Action:** Move `GALVO_FIELD_FRACTION` into the calibration schema (per-scope, like backlash) with the current value as the bundled default, and have `pan_scale_um_from_base_fov` take it from the loaded calibration. Until then, at least log a warning when the pan path is used on this machine.

### LA-09 — Medium — tests patch away the very seam the adapter depends on
**File:** tests/unit/test_zmart_adapter.py:84-87 (`make_changeable_copy` → identity), used by every position-dependent test via `_patch_position`.
**Problem:** All frame/z tests feed raw `{"position": ...}` dicts through an identity-patched `make_changeable_copy`, so the adapter's production input shape (floats/None per `commands/settings.py:139-145`) is never exercised, and the schema-validation behavior of the real function (raises `ValueError` on missing required keys, settings.py:43-50) never meets the adapter's own "LAS X version mismatch?" error path (zmart_adapter.py:376-377), which is partially unreachable as written.
**Why it matters:** The suite pins the adapter against a fiction. A change to the normalizer's output contract passes the whole adapter suite and fails on hardware.
**Action:** Have `_patch_position` return raw-shaped settings and let the *real* `make_changeable_copy` run (it is pure), or patch it with a faithful fake producing floats/None. Add one test for the "zPosition missing" and "readback None" error branches (zmart_adapter.py:376-382).

### LA-10 — Low — `set_procedure` result shape is inconsistent across procedures
**File:** zmart_adapter.py:891-896 vs 939-945.
**Problem:** `backlash_takeup` returns `{"ran": dict(procedure)}` (a dict), `autofocus` returns `{"ran": "autofocus", ...}` (a string). The tests pin both shapes (test_zmart_adapter.py:553-555, 595), cementing the inconsistency. Mesospim returns `{"ran": name, ...}` uniformly (mesospim_zmart_adapter.py:426, 431).
**Why it matters:** A controller-side caller cannot handle procedure results generically.
**Action:** Return `{"ran": name, ...}` for both (echo the args separately if wanted); update the two assertions.

### LA-11 — Low — redundant double `or {}` in `_objective_delta_um`
**File:** zmart_adapter.py:314.
**Problem:** `((handle.origin.get("objective") or {}) or {})` — the second `or {}` is a no-op.
**Action:** `(handle.origin.get("objective") or {}).get("slotIndex")`.

### LA-12 — Low — `_hardware_snapshot` overclaims consistency and runs the normalizer twice
**File:** zmart_adapter.py:386-406, via `_z_um_from_settings` at 373-383.
**Problem:** The docstring says "One consistent read of everything the frame math needs", but it is three sequential CAM reads (XY, selected job, job settings) with no atomicity; the stage can move between them. Separately, `_z_um_from_settings` re-runs `make_changeable_copy(settings)` for each of the two z keys (called at 403-404), doing the full normalization twice on the same dict.
**Why it matters:** The doc claim invites callers to treat the snapshot as a transaction; the double normalization is small but pointless work on a hot read path (`get_xyz`, every `set_xyz` pre-flight).
**Action:** Reword to "one read pass"; normalize once in `_hardware_snapshot` and extract both z values from the single changeable copy.

### LA-13 — Low — `get_context` degrade rules are uneven, and it can block ~60 s
**File:** zmart_adapter.py:1040-1065; `_scan_field` save at 969-975.
**Problem:** The selected-job read degrades only on `RuntimeError` (1050-1053) while the scan-field path degrades on any `Exception` (1055-1058) — a reader `AttributeError` fails the whole "purely informational" call on one path and is swallowed (even for programming errors) on the other. Also, `_scan_field` fires `save_experiment(..., timeout=60)`, so a "read-only context" call can stall a minute; the docstring notes the save but not the stall.
**Why it matters:** Inconsistent degrade behavior at the one op documented as never-raising; and a 60 s worst case surprises controller callers that treat `get_context` as cheap.
**Action:** Use one degrade rule for both legs (catch `Exception`, log with `exc_info` so coding bugs stay diagnosable), and document the worst-case duration or lower the save timeout for this path.

### LA-14 — Low — `select_job` success-checking duplicated at four call sites
**File:** zmart_adapter.py:748-750, 862-864, 923-926, 933-936.
**Problem:** The pattern `result = _commands.select_job(...); if not result.get("success"): raise/log ...` appears four times with near-identical messages.
**Action:** Extract `_select_job_or_raise(handle, job)` (with a `log_only` flag for the restore path); one message format, one behavior.

### LA-15 — Low — adapter reaches into private motion internals for pre-flight
**File:** zmart_adapter.py:588, 591 (`_limits._check_xy_limits`, `_limits._check_z_limits`).
**Problem:** The pre-flight is well-motivated (check the z leg *before* the XY move fires), but it does so by calling underscore-private functions of `motion/limits.py` — which the top-level `__init__.py` then also exports (LA-06). The privacy marker is fiction.
**Action:** Give `motion.limits` a public `check_xy(x, y)` / `check_z(z, z_mode)` (thin renames) and use those; keep the underscore names as internal aliases or drop them.

### LA-16 — Low — `ZmartHandle` typing is loose where it is cheap to be precise
**File:** zmart_adapter.py:114-156.
**Problem:** `connection: dict`, `used_p: set`, `origin: dict`, `translations: dict | None` — no element types; `translations` and `function_limits` are documented as inline comments rather than in the class docstring's Attributes section (which documents the other five fields).
**Action:** `dict[str, Any]`, `set[int]`, `dict[int, tuple[float, float, float]] | None`; move the two comment blocks into the Attributes docstring for consistency.

### LA-17 — Low — `_assign_p_slot` semantics have undocumented edges
**File:** zmart_adapter.py:687-702, consumed at 757 before `save` (759-772).
**Problem:** (a) A p slot is consumed (`used_p.add`) even when the subsequent `save` raises, so a failed acquire burns the number and the retry of the same non-numeric label lands on a different `p`. (b) The same non-numeric label acquired twice intentionally gets *two different* slots (no label→slot memory), which is the documented "never collide" behavior but means a re-acquire of "tumor-edge" is a new position, unlike a numeric re-acquire which upserts. (c) `"-3"` / `"1.5"` fail `isdigit()` and silently become auto-assigned.
**Why it matters:** The lineage record is the only way to reconstruct which outputs share a position; the asymmetry between numeric and non-numeric labels deserves a sentence where callers will read it.
**Action:** Document (b)/(c) in the `acquire` docstring (it currently only covers the happy split), and either allocate the slot after a successful save or note that failed acquires burn slots.

### LA-18 — Low — `__all__` grouping comments mislabel entries; a logger is exported
**File:** `__init__.py:79-106` ("acquire" listed under `# commands` but bound from `acquisition.capture` at line 413 — the dict-returning `commands.commands.acquire` is *not* the exported one), 227-243 (`disable_roi_scan`, `LIMITS_SCHEMA_VERSION`, `load_stage_config` etc. filed under `# session helpers`), 22 (`log` — a `logging.Logger` in `__all__`).
**Problem:** The section comments are the only structure in a 240-name list and several are wrong; exporting `log` invites external code to log as the package.
**Why it matters:** The `acquire` mislabel is actively dangerous documentation: the commands-section reader expects the §5 result-dict contract, but the exported `acquire` raises and returns an `AcquisitionResult` (README calls this out as gotcha #2 precisely because it is confusable).
**Action:** Fix the group placements, add a comment at the `acquire` entry naming its origin, drop `log` from `__all__`.

### LA-19 — Low — import-time `sys.path` mutation is a global side effect (accepted, but keep it minimal)
**File:** `__init__.py:260-274`; duplicated per-entry-point by tests/conftest.py:10-28 and run_ci.py:74-86.
**Problem:** Importing the driver package inserts two directories at the *front* of `sys.path` for the whole process. It is documented, tested (`test_driver_bootstrap.py`), and each of the three mechanisms serves a different entry point — but front-insertion can shadow site-packages names for unrelated code in the host process, and three bootstrap sites is the current cost of not packaging.
**Why it matters:** Low today; becomes a real bug the day the repo gains a top-level module whose name collides with an installed package.
**Action:** No structural change demanded now; prefer `append` over `insert(0, ...)` for the repo root if shadowing is not required, and note in the comment that packaging (`pyproject.toml`) is the eventual replacement for all three bootstraps.

### LA-20 — Low — `utils.py` self-description contradicts its contents; duplicated format parsing **[PATCHWORK]**
**File:** utils.py:1-10 vs 25-88; 111-116 vs 147-162, 177-184; mojibake at 155.
**Problem:** (a) The module header claims "no domain knowledge … no knowledge of LAS X, microscopes" while hosting galvo-optics physics (`PAN_LIMIT`, `GALVO_FIELD_FRACTION`, `pan_scale_um_from_base_fov`). (b) `parse_format` (raises on bad input) is re-implemented inside `parse_tile_geometry` (silently yields `None` pixel counts, 177-184) — two parsers, two failure behaviors, one format. (c) `_parse_dim_um`'s regex `[Ânmuµμ]*m` silently handles the `Âµm` UTF-8-as-Latin-1 mojibake with no comment saying that is what `Â` is for.
**Action:** Move the galvo block next to its consumers (or to config, per LA-08); have `parse_tile_geometry` call `parse_format` for the pixel count; add one line naming the mojibake case.

### LA-21 — Low — `_hw_get` swallows every exception
**File:** utils.py:101-108.
**Problem:** `except Exception: return default` around a dict/attr get. The only realistic failures (`getattr` raising from a property) are exactly the ones worth seeing.
**Action:** Catch `(AttributeError, TypeError, KeyError)`; let the rest propagate.

### LA-22 — Low — `_is_file_locked` misclassifies read-only files as locked
**File:** _file_utils.py:14-27, consumed by `_wait_file_stable` 29-66.
**Problem:** Probing with `open(path, "r+b")` requires *write* access, so a file with the read-only attribute (or restrictive ACL) raises `PermissionError` and reports "locked by another process" forever; `_wait_file_stable` then times out on a file that is complete and readable. Also POSIX gives no `PermissionError` for advisory locks, so on non-Windows the probe is a no-op — the docstring says Windows, fine, but the read-only case is a Windows case too.
**Why it matters:** A stability timeout on an export path turns into a spurious acquisition failure with a misleading cause.
**Action:** Note the limitation, or distinguish sharing-violation from access-denied (`e.winerror == 32`) when on Windows.

### LA-23 — Low — `run_ci.py` end-of-run report list is incomplete; two stale strings
**File:** run_ci.py:294-303 (report list omits `zmart_adapter_validate.jsonl`, which the online step writes at 252-254), 316 (warn message hardcodes "(lint)" — true only while lint is the sole non-fatal step), 84-86 (a comment block explaining that nothing is being set).
**Action:** Add the missing report line, derive the warn label from the step names, delete the no-op comment.

### LA-24 — Low — `pytest.ini` and `run_ci.py` disagree on what "the suite" is
**File:** pytest.ini:8 (`testpaths = tests`) vs run_ci.py:45 (`TEST_PATHS = [tests, calibration/tests]`).
**Problem:** A bare `pytest` from the driver root — the exact invocation pytest.ini:3-5 advertises as "the driver's own offline suite" — silently skips the calibration suite that run_ci treats as fatal. README §9 papers over it by listing both commands.
**Action:** Add `calibration/tests` to `testpaths` (the hermetic conftest already covers it), or state in pytest.ini why it is excluded.

### LA-25 — Low — per-file `sys.path` hacks and `__main__` blocks bypass the hermetic fixture
**File:** tests/unit/test_zmart_adapter.py:16-17, 1076-1077; tests/unit/test_validate_hardware_cli.py:8, 51-52.
**Problem:** The path inserts duplicate tests/conftest.py:10-18; they exist to support `python test_zmart_adapter.py`, but that invocation runs *without* the autouse `SMART_MICROSCOPY_ROOT` fixture — so `TestFrame.test_set_origin_zeros_the_frame` executed directly on a machine with real snapshots would write `origin.json` into the newest production snapshot (zmart_adapter.py:472-473).
**Why it matters:** A test file that mutates machine-local calibration state when run the "obvious" way is a footgun on the one machine that matters.
**Action:** Drop the `__main__` blocks and path inserts (pytest is the supported entry point), or have the module set a tmp `SMART_MICROSCOPY_ROOT` when run as `__main__`.

### LA-26 — Low — adapter test-coverage gaps and one confusing assertion
**File:** tests/unit/test_zmart_adapter.py.
**Problem:** No test for: non-numeric `position_label` slot assignment (`_assign_p_slot`'s auto path, zmart_adapter.py:695-701); `get_xyz` rejecting an unknown actuator (only the `set_xyz` path is hit, and via the odd short-circuit `adapter.get_actuators(h) and adapter.set_xyz(...)` at 300-305, which reads as if it tested both but evaluates `get_actuators` for truthiness only); `get_context`'s selected-job degrade (`selected: None`); `_z_um_from_settings` error branches. Also `_wide_limits`/`_clear_limits` (91-106) mutate the process-global `_stage_limits` directly — correct but brittle; a fixture would guarantee restoration on error paths.
**Action:** Add the four small tests; split the `and`-chained assertion into two statements.

### LA-27 — Low — `test_validate_hardware_cli.py` pins one helper of a large CLI with a hand-rolled args contract
**File:** tests/unit/test_validate_hardware_cli.py:35-48.
**Problem:** The single test drives `_apply_log_select_confirmation` with a `SimpleNamespace` that re-declares seven argparse attributes by hand; if the CLI renames a flag, the namespace and the parser drift apart with no signal (the test keeps passing against attributes the real parser no longer produces). Coverage of `validate_hardware.py`'s CLI surface is otherwise zero at unit level (the hardware-side tests cover the rest, but they need a scope).
**Action:** Build the namespace via the module's own `parser.parse_args([...])` so flag renames break the test; consider one more case (the `--enable-log-select-confirm` path).

### LA-28 — Low — README quick-start example exceeds the reviewed stage envelope
**File:** README.md:104-107 vs `limits/defaults/limits.json` (y: 1000–100000).
**Problem:** The copy-pasteable `set_stage_limits(... y_max=130_000 ...)` grants a Y range 30 mm beyond the driver's own bundled last-known-good envelope for this machine. The section even says limits are "REQUIRED before movement" — the example then supplies unsafe numbers.
**Action:** Use the bundled values in the example, or better, show `apply_stage_limits_from_config(load_stage_config())` (the snapshot-driven path the adapter itself uses), demoting raw `set_stage_limits` to a footnote.

---

## Summary table

| ID | Severity | Title |
|-------|----------|-------|
| LA-01 | High | Calibrated backlash params from the machine snapshot silently ignored on all controller-path moves |
| LA-02 | Medium | `_z_um_from_settings` guards a settings shape production never produces **[PATCHWORK]** |
| LA-03 | Medium | `get_xyz` `with_actuators` selects nothing; result `actuator` tag misattributes the focus-sum reading |
| LA-04 | Medium | Restored `origin.json` values not type-coerced — corrupt file breaks frame math instead of degrading |
| LA-05 | Medium | 136/216 package-root exports never consumed via the root **[YAGNI]** |
| LA-06 | Medium | 14 underscore-private names (incl. mutable `_stage_limits`) exported in `__all__` |
| LA-07 | Medium | "Import and override" tuning for `RECEIPT_TIMEOUT`/`CONFIRM_POLL_S` cannot work (import-time value binding) |
| LA-08 | Medium | Galvo pan constants measured on STELLARIS 8, hard-coded outside the machine-snapshot system |
| LA-09 | Medium | Adapter tests patch `make_changeable_copy` to identity — production seam shape untested |
| LA-10 | Low | `set_procedure` result `"ran"` is a dict for one procedure, a string for the other |
| LA-11 | Low | Redundant double `or {}` in `_objective_delta_um` |
| LA-12 | Low | `_hardware_snapshot` overclaims atomicity; normalizer run twice per snapshot |
| LA-13 | Low | `get_context` degrade rules uneven; can block ~60 s on the scan-field save |
| LA-14 | Low | `select_job` success-check duplicated at four call sites |
| LA-15 | Low | Pre-flight reaches into private `motion.limits._check_*` functions |
| LA-16 | Low | `ZmartHandle` element types and attribute docs incomplete |
| LA-17 | Low | `_assign_p_slot` edge semantics (burned slots, label asymmetry, negative labels) undocumented |
| LA-18 | Low | `__all__` grouping comments mislabel entries (notably `acquire`); logger exported |
| LA-19 | Low | Import-time `sys.path` front-insertion; triplicated bootstrap across entry points |
| LA-20 | Low | `utils.py` header contradicts contents; duplicated format parsing; unexplained mojibake regex **[PATCHWORK]** |
| LA-21 | Low | `_hw_get` swallows every exception |
| LA-22 | Low | `_is_file_locked` misreports read-only files as locked |
| LA-23 | Low | `run_ci.py` report list omits an artifact; two stale strings |
| LA-24 | Low | `pytest.ini` `testpaths` excludes `calibration/tests` that run_ci treats as fatal |
| LA-25 | Low | Test-file `__main__` execution bypasses the hermetic machine root (can write real `origin.json`) |
| LA-26 | Low | Adapter test gaps (non-numeric p slots, `get_xyz` actuator rejection, context degrade) + one confusing assertion |
| LA-27 | Low | validate_hardware CLI test hand-rolls the argparse contract; drifts silently on flag renames |
| LA-28 | Low | README quick-start stage limits exceed the bundled envelope for this machine |
