# Fossils & Dead Code Review — `zmart_controller/` + Leica `navigator_expert/`

- **Scope:** (1) `zmart_controller/` (all files, incl. tests and notebooks); (2) `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` (all subpackages, tests, hardware scripts, JSON configs, notebooks, CI files).
- **Out of scope for findings, in scope for call-site tracing:** the entire rest of the repo (mesospim, zeiss, nikon, evident, `shared/`, `workflows/`, `getting_started/`, `docs/`, all notebooks). Every "dead" claim below was verified by whole-repo reference search (`.py`, `.ipynb`, `.md`, `.json`, `.yml`, `.ini`, `.txt`, `.toml`) — a name is only called dead when *nothing anywhere in the repo* references it outside its own definition site.
- **Method:** AST enumeration of every module-level function/class/UPPER-constant and class method in scope (≈1,600 names), cross-referenced against a whole-repo text corpus with word-boundary matching; per-name classification into (a) truly dead, (b) exported/README-documented but zero in-repo consumers, (c) load-bearing-but-mislabeled. Followed by targeted greps for: profile/config-knob reads, JSON key reads, TODO/FIXME/XXX/HACK markers, commented-out code blocks, `legacy|deprecated|obsolete` markers, skipped tests, test-data references, `__all__` root-consumption, and orphan files. `ruff --select F401,F811,F841` run over both components (clean; the facade carries a blanket `noqa`).
- **Date:** 2026-07-03 · **Commit:** `c7964dd` (working tree == origin/main)
- **Prior reviews read and cross-referenced:** ZC-*, LC-*, LS-*, LM-*, LA-*, LT-* (docs/reviews/*.md). Where this sweep merely confirms a prior finding it says so in one line; new findings and deepened prior findings get full treatment.

**Public-API caveat honored throughout:** this is a driver package whose README-documented commands are legitimately consumed by end-user notebooks outside the repo. Such names are classified "no in-repo consumer — decide deliberately", never "dead". Internal helpers with zero references are dead.

---

## Executive summary

The two components are, by dead-code standards, in very different shape.

**`zmart_controller/` is essentially free of dead weight.** ~760 lines of production+test code, zero TODO markers, zero commented-out code, no dead helpers, all 4 `__all__` names consumed, all test fixtures and the mock driver load-bearing. The only fossils are documentation-level (stale notebook state keys, `import zmart` future tense — ZC-02/ZC-18, owned by the docs pass) and two micro-items already filed (ZC-04, ZC-11). Nothing new to delete.

**The Leica driver carries ≈3,900 lines of deletable dead weight plus ≈1,100 lines needing a deliberate keep/delete decision**, clustered in four places:

1. **`tests/hardware/` — 2,686 lines across six orphan one-shot scripts** referenced by nothing (no run_ci step, no test wrapper, no README) — FD-04.
2. **`experimental/lrp_edits/` (2,192 lines) — exactly three functions have a production consumer** (`galvo_pan_for_pixel`, `lrp_get_pan`, `lrp_set_pan`, all for `move_galvo_to_pixel`). Within it, a truly dead subset of ≈350 lines: **all 24 `lrp_verify_*` wrappers** (built to be `verify_fn` callbacks that nothing ever passes), the LS-14 pair, and six orphan coordinate/ROI helpers referenced only by each other's docstrings — FD-02.
3. **The confirmation/reader layer's speculative half**: the entire evidence-leg subsystem in `capabilities.py` (≈95 lines, confirms LC-01), the passive hybrid read race unreachable at shipped defaults (LC-11), a **safety validator (`require_canonical_scan_orientation`) that no code anywhere ever calls** — FD-03, new — and dead knobs/kwargs (`xy_min_delta_um`, `observed_after`, `timing["method"]`).
4. **Fossil tests**: ≈440 lines of removed-API tombstones, hasattr inventories, and a protocol suite that tests its own mocks (confirms LT-06/LT-09), plus a 216-name facade `__all__` of which **135 are never consumed via the package root** (re-measured; LA-05 said 136 — one name, `set_scan_speed` group membership, differs by counting method).

Notably clean: **zero TODO/FIXME/XXX/HACK comments in either component** (§4), essentially zero commented-out code, no forever-skipped tests, and every committed test-data bundle is load-bearing (including `_ScanningTemplate_Test1`, exercised via glob parametrization).

Findings: 4 High, 13 Medium, 8 Low.

---

## Findings

Severity: **High** = large dead chunks or actively misleading fossils; **Medium** = real dead weight / decisions owed; **Low** = hygiene.

---

### FD-01 — High — `readers/capabilities.py`: the change/target "evidence leg" subsystem is dead (≈95 lines + a dead profile knob) — *confirms LC-01, with full inventory*

- **Files:** `readers/capabilities.py:10-15` (docstring section), `:59-63` (`DatumSpec.evidence_log_fn/key_fn/target_fn/min_delta_attr/numeric`), `:66-71` (`key_delta`), `:112-163` (`_selected_job_key/_selected_job_target/_selected_job_evidence/_xy_key/_xy_target/_xy_evidence`), `:204-208` + `:227-229` (evidence kwargs in the `xy` and `selected_job` `DatumSpec` entries), `:241-249` (`change_spec`); `config/profiles.py:127-128` (`xy_min_delta_um`).
- **Evidence:** whole-repo scan: `key_delta` and `change_spec` have **zero references outside capabilities.py** (only hits: the prior review doc). The six `_selected_job_*`/`_xy_*` helpers are referenced only by the two `DatumSpec` entries whose evidence fields nothing reads (`_xy_target` additionally appears once in the orphan script `tests/hardware/smoke_two_tile_save.py` — itself unreferenced, FD-04). `xy_min_delta_um` has exactly one production reference: the string `min_delta_attr="xy_min_delta_um"` inside the dead spec entry. The functions that *are* alive in this module — `spec()`, `age_for_snapshot()`, `trust_present/trust_status`, `UnsupportedSource` — are all consumed by `router.py`.
- **Action:** **Delete** the five evidence fields, `key_delta`, `change_spec`, the six helpers, the evidence kwargs in `DATUMS`, the "evidence legs" docstring section, and `StateReaderProfile.xy_min_delta_um`. Resurrect from git if a change-detection race ever gets a consumer.

---

### FD-02 — High — `experimental/lrp_edits/` (2,192 lines): three production-consumed functions; 24 dead `lrp_verify_*` wrappers; six orphan coordinate helpers; ~60 facade exports with no in-repo consumer — *extends LS-13/14/15 with a complete reachability map*

Full-package reachability (whole-repo grep per name, docstring hits discounted):

**Production-consumed (keep, promote out of `experimental/` per LS-13):**
| Name | Consumer |
|---|---|
| `galvo_pan_for_pixel` (roi.py:737) | `commands/commands.py:1165,1202` (`move_galvo_to_pixel`) |
| `lrp_get_pan`, `lrp_set_pan` (scan.py) | `commands/commands.py:1166,1213,1221` |
| `roi_translation_to_pan` (roi.py:710) | called by `galvo_pan_for_pixel` |
| `_set_job_attr`/`_verify_job_attr`/`_verify_job_attr_float`/`_set_sequential_attr` (_primitives.py) | every `lrp_set_*`; pinned by `tests/unit/test_lrp_edit_primitives.py` |
| `lrp_set_stack_calculation_mode` (focus.py) | unit tests only (regression pin for the cross-job bug) |

**(a) Truly dead — delete (~350 lines):**

1. **All 24 `lrp_verify_*` wrappers** — `focus.py:120,162,201`; `general.py:45,69,90,111,136,182`; `scan.py:44,68,103,147,174,211,240,266`; `z.py:65,93,126,173,201,238,319`. Each is `in-file refs = 1` (its own `def`) and its only external reference is the facade re-export block (`__init__.py:430-525`). They exist to be passed as `verify_fn=` to `apply_lrp_change` — a whole-repo grep for `verify_fn` shows **only two call sites ever pass one** (`roi.py:188` → `lrp_verify_roi_scan`, `scan.py:321` → `lrp_verify_pan`), and both callers (`disable_roi_scan`, `reset_pan`) are themselves dead (below). No workflow, notebook, script, or test uses any of the 24. The verify half of the LS-17 set/verify boilerplate is 100 % unconsumed.
2. **`pixels_to_roi` (roi.py:459) + `center_vertices` (roi.py:~432)** — zero references anywhere, not exported, not in README (~70 lines). *Confirms LS-14.*
3. **`roi_to_absolute_um` (roi.py:761) and `absolute_um_to_roi_translation` (roi.py:778)** — *new*: zero code callers repo-wide; the only in-file "uses" are each other's docstrings (`"Inverse of roi_to_absolute_um"`) and a docstring at roi.py:61/542. Exported by the facade, in no README example (~40 lines).
4. **Transitively dead trio `roi_to_pan_zoom` (roi.py:868) → `roi_geometry` (roi.py:818) + `bbox_to_zoom` (roi.py:798)** — `roi_geometry` and `bbox_to_zoom`'s only code callers are `roi_to_pan_zoom`, which itself has zero callers (LS-15). Deleting the root deletes ~105 lines.
5. **`um()` (roi.py:111)** — a metres helper exported at the facade (`__init__.py:478`, `__all__:176`) that nothing outside roi.py calls.

**(b) No in-repo consumer, but README-documented offline-template-editing API — decide deliberately (~300 lines + ~85 facade export lines):**
`disable_roi_scan`, `reset_pan` (their docstrings promise verification they don't perform — driver-cleanup review §4), `make_rectangle`, `make_ellipse`, `make_polygon`, `make_line`, `make_star`, `mask_contour_to_roi`, `lrp_clear_rois`, `lrp_add_roi`, `lrp_enable_roi_scan`, `lrp_find_aotf_template`, `argb_color`, `COLOR_RED/GREEN/BLUE/YELLOW`, `ROI_RECTANGLE/ELLIPSE/LINE/POLYGON`, `STACK_MODES`, `SCAN_DIRECTIONS`, `SEQUENTIAL_MODES`, `Z_STACK_DIRECTIONS`, `Z_USE_MODES`, and all ~26 `lrp_set_*` — every one has zero consumers in the repo (facade + README only). The README's load-bearing justification (§ "offline template editor") cites `disable_roi_scan`/`reset_pan`, which are themselves the unconsumed names (LS-15's circularity, re-verified). If the interactive/cookbook use case is real, keep the `lrp_set_*` family and the `make_*` authoring helpers and say where they're used; either way the 24 verify fns and the group-(a) orphans go.

- **Action:** delete group (a) now; make a recorded decision on group (b); rename `experimental/` → `lrp_edits/` (LS-13) since the only genuinely experimental thing left after (a) is nothing.

---

### FD-03 — High — `connection/session.py:87-119`: `require_canonical_scan_orientation` is a safety validator that **no code anywhere ever calls** — *new (LC-10 reviewed its fail-open logic without noticing it has zero call sites)*

- **Evidence:** whole-repo grep: references are the facade re-export (`__init__.py`), the README, and prior review docs. `connect_python_client` does not call it; neither do the calibration workflows, the zmart adapter's `connect`, `workflows/target_acquisition` (which uses `connect_python_client` at `pipeline/connect.py`), nor any hardware validator or notebook.
- **Why it matters:** the docstring says a non-TOPLEFT export "silently misnavigates downstream coordinate math" — i.e. this check guards the exact silent-corruption class the driver is built to prevent — and it is *documented in the README as part of the session-setup surface*. A reader assumes the guarantee is enforced somewhere. It is enforced nowhere. This is the most misleading kind of fossil: a safety net that exists only as text. (It also fails open when settings are unreadable — LC-10.)
- **Action:** **Promote, don't delete**: call it from `connect_python_client()` (or from the adapter's `connect` and both calibration `start_session`s), fix the LC-10 fail-open at the same time, and add a test. If the team decides the check is obsolete, delete it *and* its README section together.

---

### FD-04 — High — `tests/hardware/`: six orphan one-shot scripts, 2,686 lines, referenced by nothing — *confirms LT-08 with exact sizes and zero-reference verification*

| Script | Lines | Self-description | Referenced by |
|---|---|---|---|
| `compare_export_metadata.py` | 1,164 | "**Offline** metadata verifier" — misfiled under `hardware/` | nothing |
| `smoke_two_tile_save.py` | 522 | two-tile acquire/save smoke | nothing |
| `compare_select_job_confirm_sources.py` | 452 | the measurement study behind the 2026-06-11 hybrid-confirm decision (decision already recorded in profiles.py:107-111 and test docstrings) | nothing |
| `verify_save_product.py` | 215 | "Run AFTER the driver fix lands" — it landed; `test_acquisition.py` pins the contract offline | nothing |
| `move_xy_pattern_api_vs_log.py` | 180 | visible-move reader comparison | nothing |
| `probe_export_layout.py` | 153 | "so we stop guessing … before restructuring the collector" — the collector was restructured | nothing |

- **Evidence:** grep for each module name across all `.py/.md/.yml/.ini` files: zero hits outside the file itself (and prior review docs). The five *maintained* scripts are, by contrast, all wired: `validate_hardware.py`, `validate_zmart_adapter.py`, `probe_four_readers.py`, `validate_readers_side_by_side.py` (run_ci.py:239-266) and `stress_hardware.py` (imported by `test_stress_hardware.py`).
- **Action:** delete `probe_export_layout.py`, `verify_save_product.py`, `compare_select_job_confirm_sources.py` (fossils of finished debugging campaigns — git history keeps them). Decide on `move_xy_pattern_api_vs_log.py` and `smoke_two_tile_save.py` (wire into `run_ci online` or delete). Move `compare_export_metadata.py` out of `hardware/` and wire it in, or delete it.

---

### FD-05 — Medium — Facade `__init__.py`: 135 of 216 `__all__` names never consumed via the package root — *verifies LA-05 (they counted 136), adds the exact list*

- **Evidence:** re-measured with an independent method (AST-extracted `__all__`; repo-wide match on `drv.NAME`, `navigator_expert.NAME`, `from navigator_expert import …NAME`, and the fully-qualified form): **216 names, 135 never consumed via the root**, including the entire `lrp_*` block (~85 names), the ROI authoring group, the OME check/fix septet (`check_ome_xml_bytes`, `fix_ome_xml_bytes`, `extract_wavelength_from_id` are additionally *internal-only* — their only non-facade consumers are inside `acquisition/`), scanfields parser internals (`parse_base_grid`, `parse_rgn_geometries`, `parse_rgn_tile_colors`, `plan_tiles_from_geometries`, …), tuning constants (`RECEIPT_TIMEOUT`, `CONFIRM_POLL_S` — whose "import and override" advice can't work, LA-07), `LIMITS_SOURCE_MIGRATION` (see FD-08), `um`, `Reading`, `require_canonical_scan_orientation` (FD-03), and 5 of the 14 underscore-private names (LA-06).
- **Action:** as LA-05: prune to the consumed+documented surface or generate the facade from submodule `__all__`s. This sweep's list (above + FD-02's table) is the deletion worksheet.

---

### FD-06 — Medium — `calibration/core/model.py`: four public functions with test-only or zero callers (~75 production lines + ~40 test lines) — *confirms LM-09 and sharpens it*

| Function | Lines | Callers (whole repo) |
|---|---|---|
| `reference_to_objective_command_xy` | 368-381 | **none at all — not even a test** (LM-09 implied test coverage; there is none) |
| `save_calibration` | 148-157 | `calibration/tests/unit/test_model.py:224,226` only |
| `set_reference` | 296-309 | `test_model.py` only |
| `pixel_to_stage_xy_um` | 384-401 | `test_model.py` only (and hardcodes a square image — LM-09) |

Correction recorded during verification: `translate_z_between_objectives` (model.py:329) initially looked test-only but **is alive** — called by `translate_xyz_between_objectives` (model.py:359), which workflows consume. Not dead.
- **Action:** delete the four functions and their tests; `reference_to_objective_command_xy` can go without any test churn.

---

### FD-07 — Medium — Config/JSON keys nothing reads: calibration `backlash.approach` + `backlash.tolerance_um`; `LIMITS_SOURCE_MIGRATION` — *confirms LM-01/LM-19, with one correction to LM-19*

- **Evidence:**
  - `"approach"` (`calibration/defaults/calibration.json`, value `"+X+Y"`): the only code touching it is validation/copy-through (`stage_config.py:43,138`; `model.py:100`). The take-up direction is hardcoded in `movement.py`. Pure schema ornament.
  - `"tolerance_um"`: validated and coerced (`stage_config.py:141`, `model.py:110`), mentioned in a `movement.py:71` docstring — **never passed to any function**. The adapter calls both backlash primitives bare (LA-01) and the workflow passes only `overshoot_um`/`settle_ms` (`workflows/.../focus.py:330-331`, `_acquire.py:45-46`).
  - `LIMITS_SOURCE_MIGRATION` (`motion/stage_config.py:30`): defined, added to `LIMITS_SOURCES`, exported in the facade — written and read by nothing.
  - **Correction to LM-19:** `LIMITS_SOURCE_CFG_FALLBACK` is *not* test-only — `workflows/target_acquisition/pipeline/template.py:142` selects it in production. Keep it.
  - All other JSON keys checked are read: `limits.json` (`schema_version`/`source`/`stage_um` → `stage_config._read_limits`), `function_limits.json` (→ `shared/limits/spec.py` + `_MUTATING_OPS` guard), calibration `session_id`/`last_updated`/`reference_objective_slot`/`image_to_stage(_hash)`/`objectives.*` all consumed. All `StateReaderProfile`/`LogReaderProfile`/`LasxApiProfile`/`AcquisitionProfile`/`CommandProfile` fields are consumed **except** `xy_min_delta_um` (FD-01); `hybrid_log_grace_s` is consumed only on the unreachable hybrid path (FD-11).
- **Action:** per LM-01, either wire `tolerance_um` through (with LA-01) and justify `approach`, or delete both from the schema, both validators, and the bundled JSON. Delete `LIMITS_SOURCE_MIGRATION`.

---

### FD-08 — Medium — `config/machine.py:118-151`: `legacy_snapshot_root` + `migrate_legacy_snapshots` have no production caller — one-time migration code fossilizing in place — *deepens LM-27*

- **Evidence:** whole-repo grep: callers are `test_machine_profile.py:133-150` and a log-message *hint* at machine.py:205 telling a human to run it manually. No notebook, workflow, or script invokes it.
- **Action:** as LM-27 — either call it opportunistically from `resolve()` (idempotent) or set a deletion date once the rig's tree is migrated; ~45 lines + 2 tests go with it.

---

### FD-09 — Medium — Dead-in-production code kept alive only by tests

1. **`acquisition/save.py:309-313` `_append_summary_atomic`** — sole caller is `test_acquisition.py:1090-1101`. *Confirms LS-28.* Delete + retarget test.
2. **`zmart_adapter/zmart_adapter.py:379-380`** `isinstance(val, dict)` branch reachable only when tests patch `make_changeable_copy` to identity. *Cross-ref LA-02/LA-09.*
3. **`readers/derived.py:81-83`** bare-float re-guard unreachable behind `make_changeable_copy` normalization. *Cross-ref LC-06.*
4. **`commands/confirmations.py:260-275`** `_reading_value_after` plain-value branch existing for old test patch shapes. *Cross-ref LC-05.*

---

### FD-10 — Medium — Dead parameters and vestigial fields in the command layer — *confirms LC-16/LC-17 by grep*

- **`commands/confirmations.py:229` `_readback(client, job_name, *, observed_after=None)`** — every call site repo-wide (via `_confirm_readback` and the bespoke confirms) calls it without `observed_after`; the freshness-gate block at :249-253 never executes. (`_reading_value_after` at :260 is the separately-consumed variant.) Delete the kwarg + gate (~10 lines) or wire it in with a test.
- **`utils.py:246,259,273` `timing["method"]`** — every producer passes the literal `"async"` (`dispatch.py:561,586,636,705,733`); the only readers are tests asserting it equals `"async"` (`test_core_driver.py:142,299,2641`). Fossil of the removed sync path (`TestApiSetRemoved` is its tombstone — FD-14). Drop the key.

---

### FD-11 — Medium — Passive `hybrid` read race is unreachable at shipped defaults — *confirms LC-11*

- **Evidence re-verified:** all six `*_mode` fields in `StateReaderProfile` default `"api"` (profiles.py:88-125); repo-wide grep for `mode="hybrid"`/`mode="log"` on routed reads finds only unit tests and the hardware validator CLI. `hybrid_log_grace_s` has exactly one production read (`router.py` grace window) — on that path. ~80 lines of maintained, tested, never-executed race.
- **Action:** as LC-11 — flip a datum to `hybrid` for real, or delete `_log_rescue_concurrent` + the knob. Decide; don't keep by default.

---

### FD-12 — Medium — `tests/hardware/validate_readers_side_by_side.py:315-316,401-402` references profile fields that do not exist — a maintained, run_ci-wired script that crashes on entry to its live-changes phase — *confirms LM-23, escalation note*

- **Evidence:** `profiles.LOG_READER.poll_timeout` / `.poll_interval` — `LogReaderProfile` (profiles.py:63-69) has neither field (the real names are `STATE_READERS.selected_job_log_poll_timeout_s/…interval_s`). `phase_changes()` dies with `AttributeError` on line 315. Unlike LM-23's framing, note this script is one of the four *maintained* validators wired into `run_ci.py online` (:243) — so the online CI leg has a guaranteed-broken step. The fossil evidence: the profile was slimmed without sweeping consumers.
- **Action:** fix the two references (or delete the phase); add the script to whatever lint/import smoke covers `tests/hardware/`.

---

### FD-13 — Medium — Compatibility shims and self-declared "legacy" code

1. **`scanfields/parsers.py:56-58`** — re-exports `parse_lrp`/`_get_job_names` from `lrp.py` "so the (untouched) experimental lrp_edits package can keep importing it" — the "(untouched)" premise is false (the package is maintained and tested), and the import is one line away. *Confirms LS-12.* Delete shim, fix `roi.py:101`.
2. **`motion/stage_config.py:11-12, 59-66, 196-214`** — `current_path()`/`write_limits()` self-declare as "legacy … until that lift into the workflow lands". They **are** consumed (workflows `template.py:731-733` via the facade aliases `write_stage_limits_config`/`current_stage_limits_path`), so not dead — but they are the repo's only self-labeled legacy surface, and the lift (with LM-07's tracked `limits/current.json` runtime artifact — 26 lines of per-run data in VCS) has no owner or date. Decide and schedule.

---

### FD-14 — Medium — Fossil tests: tombstones for long-removed APIs, hasattr inventories, self-testing protocol suite (~440 test lines) — *confirms LT-06/LT-09*

- `tests/unit/test_core_driver.py:1155-1160` `TestApiSetRemoved` and :2093-2094 `test_no_api_set` (duplicate tombstones for a sync API removed before v6), :2721-2723 `TestReadbackCacheRemoved`, :2089-2091 `test_version` pinning `__version__ == "6.0.0"`, :2105-2168 `TestModuleStructure` (hasattr lists of 23 private confirm fns + 20 set fns), `tests/unit/test_acquisition.py:1152-1161` (9 hasattr absence asserts); plus :2175-2535 `TestAcquisitionProtocol` (~360 lines testing its own table/loop/mocks — LT-06).
- **Action:** delete per LT-09/LT-06; keep one `__all__`-freeze test if the surface pin matters.

---

### FD-15 — Medium — `hardware`/`slow` pytest markers: registered, documented, filtered on — used by zero tests — *confirms LT-05*

- **Evidence re-verified:** `grep -rn "mark.hardware\|mark.slow"` over the driver returns nothing; `pytest.ini:29-32` registers both, `run_ci.py:205-206` filters `-m "not hardware"` (deselecting nothing), README §repo-map claims `hardware/ (@pytest.mark.hardware)`. The offline/online split actually works because live validators lack the `test_` prefix.
- **Action:** drop the markers + filter and document the real mechanism (LT-05 option (a)).

---

### FD-16 — Low — `tests/conftest.py:24-28`: dead `workflows/target_acquisition` sys.path insert — *confirms LT-18*

- **Evidence:** grep for `import pipeline`/`from pipeline` across `tests/` and `calibration/`: only the conftest comment itself. Delete the block.

---

### FD-17 — Low — Single-consumer log-side convenience readers — *confirms LC-30; keep-examined*

`readers/log_reader.py:569-623` (`get_job_by_name`, `get_pending_dialog`, `get_fov`, `get_base_fov`, `read_zwide_um`) and their `router.py` counterparts: production consumers are the hardware validators (`validate_readers_side_by_side.py` — currently broken, FD-12) and, for `router.get_base_fov`, `move_galvo_to_pixel`. `router.get_job_by_name` has no in-repo production caller (README-documented public API — category (b)). No action beyond LC-30's watch; if the side-by-side validator is retired, these go with it.

---

### FD-18 — Low — Calibration session dataclasses store `stage_cfg` nothing reads — *confirms LM-20 by grep*

`calibration/core/objective_pair.py:77,169`, `image_to_stage.py:65,113`: the loaded config is applied (`apply_stage_limits_from_config`) and then stashed on the session; zero subsequent reads repo-wide. Drop the field on both dataclasses (or use its `backlash` block — FD-07/LM-01).

---

### FD-19 — Low — Unreachable defensive branches — *confirms LM-14/LS-29(b) by reading*

- `calibration/core/common.py:606-619`: `np.linalg.inv` LinAlgError branch for D4 elements (all orthogonal, det ±1) — 14 unreachable lines re-verified in source.
- `acquisition/navigator_expert_export.py:87-88`: `if not detected.source_files` unreachable behind `_IncompleteExport` (LS-29(b)).

---

### FD-20 — Low — Underscore-private names exported in `__all__` — *confirms LA-06*

14 names (`_stage_limits`, `_readback`, `_make_timing`, `_fire_with_receipt`, `_PERMANENT_PATTERNS`, `_TRANSIENT_PATTERNS`, `_hw_get`, …) at `__init__.py:32-48,77-80`; 5 of them additionally never consumed via the root (FD-05 list). Drop from `__all__`.

---

### FD-21 — Low — Stale docs describing removed/renamed things (flag only; docs agent owns the deep pass)

- README §repo-map: `@pytest.mark.hardware` claim (FD-15).
- README §offline-template-editor justification cites its own unconsumed functions (FD-02b).
- `experimental/lrp_edits/z.py:9` (`templates.transaction…`), `roi.py:90` (`positions.parsers`) — two-renames-ago docstrings (LS-20).
- `tests/unit/test_core_driver.py:12-17` ("python test_unit.py"), `test_scanfield_parsers.py:4-5` (old filename + dead `zmart_drivers/vendor/leica/...` path) (LT-16).
- `zmart_controller`: notebook `mutable/immutable` keys (ZC-02), `import zmart` present tense (ZC-18).
- `run_ci.py:84-86`: a comment block explaining that nothing is being set (LA-23).

---

### FD-22 — Low — `zmart_controller/`: clean bill of health for dead code (result recorded so the next sweep can diff)

Verified: zero TODO markers; zero commented-out code; `__all__` = 4 names, all consumed (notebooks, workflows via adapters, tests); `tests/mock_driver.py` fully load-bearing (registered by conftest and the example notebook); `conftest._reset_active_session` is an autouse fixture; both example notebooks referenced by README. The only sweep-relevant items are the already-filed ZC-04 (`*args,**kwargs` signature erasure) and ZC-11 (`resolve()` returning its own argument — a vestigial tuple slot). Nothing new.

---

### FD-23 — Low — Test data and skipped tests: no fossils found (negative results, verified)

- All six template bundles under `tests/data/` are load-bearing: `scanfield_parsing/*` are consumed via `TEST_DATA.glob("*.xml")` parametrization (`test_scanfield_parsers.py:703` — including `_ScanningTemplate_Test1`, which no test names explicitly) and by the fixture-pair tests (:774-808); `general_workflow/*` via `tests/conftest.py:53` + `test_scanfield_strip_restore.py`.
- No `@pytest.mark.skip`-forever tests exist. The only skips are environment-conditional: `importorskip("cv2")` (calibration suite), `importorskip("ome_types")` (one test), LAS X-runtime-unavailable (`test_driver_bootstrap.py:80`), and data-dir `skipif`s. LT-13's silent-hollowing concern stands but there is no permanently-skipped fossil.
- `.coverage` and `.pytest_cache/` exist in the working tree but are untracked/ignored; the only questionable *tracked* artifact is `limits/current.json` (FD-13.2 / LM-07).

---

### FD-24 — Medium — Facade-only exports of internal OME helpers (subset of FD-05 worth its own line because the names look like API)

`acquisition/ome.py`: `check_ome_xml_bytes` (:142), `fix_ome_xml_bytes` (:241), `extract_wavelength_from_id` (:56) are consumed **only inside ome.py** (by `check_ome_tiff`/`fix_ome_tiff`/the file-level wrappers) yet are exported in the facade `__all__` (:66-73) alongside the genuinely-consumed `check_ome_tiff`/`check_ome_xml_file`/`fix_ome_tiff`/`fix_ome_xml_file` (used by `materialize.py:88-109` and `workflows/.../_hijack.py`). The byte-level entry points were exported wholesale with the file-level ones. Un-export the three; keep them as module internals.

---

### FD-25 — Medium — Commented-out code: one real instance (near-clean; negative result otherwise)

A block-comment scan (≥2 consecutive code-shaped comment lines) over both components found **no dead commented-out code** — the only hits are a two-line worked example in a comment at `utils.py:58-59` (legitimate documentation of the `pan_scale_um` formula) and prose that pattern-matches code. This is unusually clean and worth preserving as a norm.

---

## 4. TODO / FIXME / XXX / HACK inventory

Complete inventory, case-insensitive word-boundary grep over all `.py`, `.md`, `.ipynb`, `.json`, `.ini` files in both scoped components:

| # | File:line | Marker | Text | Verdict |
|---|---|---|---|---|
| — | *(none)* | — | — | — |

**Zero markers exist in either component.** (Case-insensitive `todo|fixme|xxx|hack` matches only ordinary words inside identifiers/prose, e.g. "skip", none of which are deferred-work markers.) The codebase's convention is evidently to encode deferred work as dated docstring notes (e.g. `stage_config.py:11-12` "remain only until that lift … lands"; `machine.py:205` migration hint; `session.py:102-104` "A future check could …"). Those live notes are covered as FD-08/FD-13; there is no rotting TODO backlog to clean.

---

## 5. Summary table

| ID | Sev | Title |
|---|---|---|
| FD-01 | High | `capabilities.py` evidence-leg subsystem dead (~95 lines + `xy_min_delta_um`) — confirms LC-01 |
| FD-02 | High | `lrp_edits`: 3 production-consumed functions in 2,192 lines; 24 dead `lrp_verify_*`; 6 orphan coordinate/ROI helpers; ~60 consumer-less exports |
| FD-03 | High | `require_canonical_scan_orientation`: safety validator with zero call sites — promote or delete (new) |
| FD-04 | High | Six orphan one-shot scripts in `tests/hardware/` (2,686 lines) — confirms LT-08 |
| FD-05 | Medium | 135/216 facade `__all__` names never consumed via root — verifies LA-05 |
| FD-06 | Medium | `model.py`: 4 test-only/zero-caller public functions; `reference_to_objective_command_xy` has no callers at all |
| FD-07 | Medium | Unread config keys: `backlash.approach`/`tolerance_um`, `LIMITS_SOURCE_MIGRATION` (LM-01/LM-19; corrects LM-19 on `CFG_FALLBACK`) |
| FD-08 | Medium | `migrate_legacy_snapshots`: manual-only one-time migration fossilizing (LM-27) |
| FD-09 | Medium | Dead-in-production code kept alive by tests (`_append_summary_atomic` + 3 cross-refs) |
| FD-10 | Medium | Dead `observed_after` kwarg; vestigial `timing["method"]` (LC-16/LC-17 verified) |
| FD-11 | Medium | Hybrid passive read race unreachable at shipped defaults (LC-11 verified) |
| FD-12 | Medium | run_ci-wired validator references nonexistent `LOG_READER.poll_timeout/.poll_interval` (LM-23, escalated context) |
| FD-13 | Medium | `parse_lrp` re-export shim (LS-12); self-declared legacy `current_path`/`write_limits` + tracked `limits/current.json` |
| FD-14 | Medium | Fossil tests: removed-API tombstones, hasattr inventories, self-testing protocol suite (~440 lines) (LT-06/LT-09) |
| FD-15 | Medium | `hardware`/`slow` markers used by zero tests (LT-05 verified) |
| FD-24 | Medium | Facade exports of internal-only OME byte-level helpers |
| FD-25 | Medium | Commented-out code: effectively none (negative result) |
| FD-16 | Low | Dead workflows sys.path insert in tests/conftest.py (LT-18 verified) |
| FD-17 | Low | Single-consumer log-side readers (LC-30 watch) |
| FD-18 | Low | Session `stage_cfg` field nothing reads (LM-20 verified) |
| FD-19 | Low | Unreachable defensive branches: D4 inversion, export emptiness check (LM-14/LS-29b) |
| FD-20 | Low | 14 underscore names in `__all__` (LA-06) |
| FD-21 | Low | Stale doc/docstring fossils (flags for docs pass) |
| FD-22 | Low | `zmart_controller/`: no dead code found (recorded negative) |
| FD-23 | Low | Test data + skips: no fossils (recorded negative) |

### Deletable-lines estimate

| Cluster | Lines (delete now) |
|---|---|
| FD-04 three finished one-shots (`probe_export_layout`, `verify_save_product`, `compare_select_job_confirm_sources`) | ~820 |
| FD-04 remaining three (pending decision; likely delete/move) | ~1,870 |
| FD-02(a) lrp_edits truly-dead subset (24 verify fns, LS-14 pair, orphan helpers) | ~350 |
| FD-01 capabilities evidence subsystem + knob | ~95 |
| FD-14 fossil tests | ~440 |
| FD-06 model.py functions + tests | ~115 |
| FD-05/FD-20/FD-24 facade `__all__`+import pruning | ~150 |
| FD-08 migration code (+2 tests) when scheduled | ~60 |
| FD-09/FD-10/FD-16/FD-18/FD-19 small items | ~70 |
| **Total deletable** | **≈3,900 (of which ≈2,100 need only a rubber-stamp; ≈1,870 one decision)** |
| FD-02(b) README-marketed lrp/ROI surface + FD-11 hybrid race + FD-03 validator | ≈1,100 more pending deliberate keep/promote/delete decisions |

Dead weight concentrates in `tests/hardware/` (orphan scripts), `experimental/lrp_edits/` (speculative API surface), and the facade `__all__`. The production command/reader/acquisition core and the whole of `zmart_controller/` are close to fossil-free.
