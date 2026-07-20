# Refactor Opportunities — `zmart_controller/` + Leica Stellaris5 `navigator_expert/`

- **Scope:** `zmart_controller/` (all) and `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` (all, including tests). Rest of the repo read for context only (the mesoSPIM driver served as the "leaner driver" yardstick; no findings filed outside scope).
- **Date:** 2026-07-03
- **Reviewed commit:** `c7964dd` (working tree == origin/main)
- **Inputs:** the six prior reviews in `docs/reviews/` (LC/LS/LM/LA/LT/ZC series plus the driver-cleanup review). Every candidate area named there was re-verified against this tree before being designed here; several proposals are new (not in any prior review).
- **Filter applied:** a proposal appears only if it (a) deletes significant code, (b) collapses parallel implementations of one concern, (c) removes a whole class of bugs, or (d) makes a load-bearing module legible. Renames for taste, speculative extensibility, and pattern-for-pattern's-sake were excluded; the tempting ones are recorded under "Considered and rejected" so future reviewers don't re-propose them.

All driver paths below are relative to `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`.

---

## Executive summary

This codebase does not need an architectural rework. Its two central collapses — the `confirm_and_fire` dispatch backbone and the `CONFIRM_SPECS` table — are the right shape and already absorbed most of the boilerplate a driver like this generates. What remains falls into three buckets:

1. **Weight that is simply dead**: a reader-evidence subsystem with zero call sites (`readers/capabilities.py`), ~136 of 216 facade exports nothing consumes, a 360-line test class that tests its own mocks, four `calibration/core/model.py` functions with test-only or zero callers, and a parallel offline-edit API (`experimental/lrp_edits`) of which exactly three functions have production callers.
2. **One concern, 2–4 parallel implementations**: the flush-fire-poll skeleton copied four times in `api_reader.py` (with the stale-response guard on only one copy), four atomic-JSON writers with real NaN/fsync drift, three `.lrp` write strategies (one of which destroys the prolog another carefully preserves), ~25 hand-written lrp_edits set/verify pairs, and two tile-grid generators with different scan orders.
3. **Whole-class bug removers that cost almost nothing**: a typed calibration verdict to replace substring-matching English prose in four UI layers, and a controller-owned post-disconnect guard so drivers stop re-implementing (or forgetting) it.

On the test side, roughly 100 of the offline suite's ~124 wall-clock seconds are literal sleeping, removable with mechanical parameter/constant injection and one mock fix.

Total realistic deletion across all proposals: **~2,600–3,200 lines** (~12–15% of driver + tests), with no new abstraction that lacks a second consumer already in hand.

### Ranked by payoff / effort

| Rank | ID | Proposal | Effort | Deletes (est.) |
|---|---|---|---|---|
| 1 | RF-01 | Delete self-referential, fossil, and duplicated-bootstrap test weight | S | ~550 |
| 2 | RF-02 | Make the suite's sleeps injectable — ~124 s → ~25 s | S | ~0 (time, not lines) |
| 3 | RF-03 | Delete the dead reader-evidence subsystem; decide the hybrid race | S | ~90–170 |
| 4 | RF-04 | One flush-fire-poll primitive in `api_reader.py`, correlation everywhere | S/M | ~110 |
| 5 | RF-05 | Promote `experimental/lrp_edits` → `lrp_edits`; delete its dead surface | S/M | ~220 |
| 6 | RF-06 | Prune the 216-name facade to the real public surface | S/M | ~200 |
| 7 | RF-07 | Finish the CONFIRM_SPECS collapse: delete the `_confirm_*` wrapper layer | M | ~300 |
| 8 | RF-08 | One prolog-preserving LRP read/write pair (3 write strategies → 2) | S | ~20 + bug class |
| 9 | RF-09 | One atomic-JSON writer (4 → 1), `allow_nan=False` everywhere | S | ~25 + bug class |
| 10 | RF-10 | Typed calibration verdict instead of substring-matched prose | S | ~10 + bug class |
| 11 | RF-11 | `calibration/core` dedup + delete the dead `model.py` quartet | S | ~200 |
| 12 | RF-12 | Acquisition seams: shared candidate resolution; open the anchor TIFF once | S/M | ~50 + 4×→1× I/O |
| 13 | RF-13 | Shared test fixtures for profile/limits globals and acquisition fixtures | S | ~90 |
| 14 | RF-14 | Table-drive the surviving lrp_edits set/verify pairs | M | ~450 |
| 15 | RF-15 | Controller: own the post-disconnect guard; tighten three small seams | S | ~20 + bug class |
| 16 | RF-16 | One tile-grid generator for planned vs. materialized regions | M | ~80 + bug class |
| 17 | RF-17 | Package the repo (`[project]` table); retire the bootstrap constellation | M | ~80 across repo |

RF-01/02 and RF-03/04/05 are independent. RF-14 assumes RF-05 landed first. RF-07 subsumes LC-16 and LC-22. Everything is behavior-preserving except where a known reviewed bug is fixed in passing (each proposal says which).

---

## Proposals

### RF-01 — Delete self-referential, fossil, and duplicated-bootstrap test weight

**Current state.**
- `tests/unit/test_core_driver.py:2175–2535` (~360 lines incl. scaffolding): `TestAcquisitionProtocol` — `PROTOCOL_POSITIONS` (2175–2185), `_protocol_job_switches` (2188–2196), mock helpers (2199–2214), 14 test methods. Every test patches out `drv.select_job`, `drv.move_xy`, `drv.acquire`, **and** `commands.confirm_and_fire`; `_run_protocol` (2231–2262) is the test's own loop, and the assertions check the loop's own bookkeeping against the test's own table. Verified: no assertion reaches production logic (the `set_*` calls funnel straight into the patched `confirm_and_fire`; failure-path tests assert on `AssertionError`s raised inside `_run_protocol` itself). (LT-06)
- Fossil "removed-symbol" tests: `TestApiSetRemoved` (1155–1160), `TestModuleStructure` (2089–2168, 80 lines of `hasattr`/`callable` inventories plus a `__version__ == "6.0.0"` pin that forces a test edit per release), `TestReadbackCacheRemoved` (2721–2723), `test_acquisition.py:1163–1172` (9 `not hasattr` asserts). (LT-09)
- 13 redundant `sys.path.insert` lines across 12 unit-test files (e.g. `test_core_driver.py:30`, `test_zmart_adapter.py:16–17`) that duplicate `tests/conftest.py:11–28`; ~10 `if __name__ == "__main__"` tails in unit files — an invocation mode that bypasses the hermetic `SMART_MICROSCOPY_ROOT` fixture and can write into real machine snapshots (LA-25). `calibration/tests/unit/test_model.py:8–16`'s per-test `_load_calibration_module()` indirection duplicates its conftest. (LT-10, LM-26)

**Target design.** Pure deletion, plus one honest replacement:
- Delete `TestAcquisitionProtocol` and its module-level scaffolding. If an offline end-to-end sequencing test is wanted, it already exists in a real form: `tests/hardware/test_validate_hardware.py::test_validate_hardware_full_mock_run` drives the actual command layer against `MockLasxClient`.
- Delete the removed-API/hasattr/version tests. If the public-surface freeze matters, keep exactly one test: `assert set(drv.__all__) == EXPECTED_SURFACE` (which RF-06 will want anyway).
- Delete the per-file `sys.path.insert` lines and the unit-file `__main__` tails; `pytest` is the supported entry point. Keep `test_driver_bootstrap.py` untouched (its insert lives inside the subprocess script that *is* the test). In `test_model.py`, replace `_load_calibration_module()` with a module-level import.

**Deleted:** ~500–550 lines. **Risk:** near zero — the deleted tests pin no production behavior; the surviving suite (~640 tests) is the pin. One sanity gate: run the full offline suite before/after and diff coverage (it should not drop, since the protocol class exercised only mocks). **Effort:** S.

---

### RF-02 — Make the suite's sleeps injectable (~124 s → ~25 s)

**Current state.** Measured by the LT review and re-verified structurally here:
- `tests/unit/test_acquisition.py:577–592` `test_missing_xml_raises` deletes the companion XML and lets `_collect_positions` poll out the full `DEFAULT_EXPORT_COMPLETION_TIMEOUT_S = 60.0` (`acquisition/navigator_expert_export.py:37`) — measured 60.06 s, ~48% of the suite. Sibling tests already pass `export_completion_timeout=0.01` (e.g. 937–938, 976–977). (LT-02, LS-34)
- 9 negative confirm tests in `TestConfirmFunctions` omit `poll_window` and burn the full `CONFIRM_POLL_S = 3` window each (assertions at test_core_driver.py:1228, 1232, 1238, 1243, 1282, 1292, 1297, 1303, 1308). `CONFIRM_POLL_S` is defined in `utils.py:21` but bound **by value** into `confirmations.py:46` and `confirm_select_job.py:23`. (LT-03, LC-13)
- ~21 tests in `TestConfirmAndFire` (261–448) and `TestConfirmation` (880–1153) each pay ≥1 s because `dispatch._await_echo_result` (dispatch.py:128, `timeout=1.0`) is invoked from `_fire_block` (dispatch.py:309) with **no forwarded timeout**, and the shared `make_client()` mock echo never settles after the flush. `TestRetryBackoff` already shows both remedies (patching `_await_echo_result` at 497/527/556/590/619/647). (LC-13, LC-15, LC-18)

**Target design.** Three mechanical moves, no logic change:
1. `test_missing_xml_raises`: pass `export_completion_timeout=0.01, export_completion_poll_interval=0.001` like its siblings.
2. Add to `tests/conftest.py` an autouse fixture that shrinks the confirm window for unit tests:
   ```python
   @pytest.fixture(autouse=True)
   def fast_confirm_windows(monkeypatch):
       monkeypatch.setattr(confirmations, "CONFIRM_POLL_S", 0.05)
       monkeypatch.setattr(confirm_select_job, "CONFIRM_POLL_S", 0.05)
   ```
   (Patching `utils.CONFIRM_POLL_S` would *not* propagate — the consumers bind at import. This is also the LA-07 lesson: while here, fix the `utils.py:16–23` "import and override" docstring that documents a tuning mechanism that cannot work.)
3. Hoist the echo settle window to a module constant `dispatch.ECHO_SETTLE_TIMEOUT_S = 1.0` consumed at the dispatch.py:309 call site (this also discharges LC-18's "transport tuning hardcoded in a signature default"), and either monkeypatch it in the same autouse fixture or — better — fix the mock per LC-15 so `_EchoModel.clear()` sets `Result = 0` and handlers set `Result = 1` on completion, making the echo settle instantly and realistically. The LC-15 route is preferred because it *adds* coverage of the settle path instead of bypassing it.

**Deleted:** nothing meaningful; ~100 s per run, ×9 CI matrix jobs ≈ 15 CPU-minutes per push. **Risk:** low. The one thing to watch: a handful of tests assert on timing-dict *presence*, not durations; and any test that genuinely needs the 3 s window (none found) can pass an explicit `poll_window`. Pin with a CI wall-clock budget assertion in `run_ci.py` if desired. **Effort:** S.

---

### RF-03 — Delete the dead reader-evidence subsystem; make the hybrid race earn its keep or go

**Current state.**
- `readers/capabilities.py:59–64, 66–71, 112–164, 204–208, 227–229, 241–249`: `DatumSpec.evidence_log_fn/key_fn/target_fn/min_delta_attr/numeric`, `key_delta()`, `change_spec()`, and six `_selected_job_*`/`_xy_*` helpers have **zero call sites** (re-verified by grep on this tree); `StateReaderProfile.xy_min_delta_um` (`config/profiles.py:128`) exists only to feed them. The module docstring claims they power "the confirmation race"; the actual race (`confirmations.race_confirmations` + `confirm_select_job` + `log_wait`) never touches them, and `_selected_job_evidence` duplicates logic `log_wait._selected_job_reason` implements independently. (LC-01)
- `readers/router.py:266–343` `_log_rescue_concurrent` + `hybrid_log_grace_s`: the passive hybrid read race is unreachable at shipped defaults (every `*_mode` profile field defaults `"api"`, and all production `mode=` call sites pin `"api"`). ~80 lines maintained solely for unit tests. (LC-11)

**Target design.** Delete the evidence fields, the two module-level functions, the six helpers, the profile knob, and the docstring section; resurrect from git with a consumer in hand if a generic change-detection race is ever built. For the hybrid race, force the decision the LC review asked for: either flip one datum (`scan_status` or `xy`) to `"hybrid"` in the shipped profile — the design's stated point, claimed strictly more hang-resistant — or delete `_log_rescue_concurrent` + `hybrid_log_grace_s` and redefine `hybrid` as "api, with log fallback on error/timeout" (a ~15-line sequential branch). Keeping a dead race "for later" is the outcome to avoid.

**Deleted:** ~90 lines (evidence subsystem) + ~80 (race, if the delete branch is chosen) + their tests. **Risk:** near zero for the evidence subsystem (nothing calls it). For the race: the side-by-side hardware validators compare backends and would catch a behavior change; unit tests for hybrid degradation get deleted or simplified with it. **Effort:** S.

---

### RF-04 — One flush-fire-poll primitive in `api_reader.py`, correlation everywhere

**Current state.** `readers/api_reader.py` copies the retry/flush/fire/poll/timeout/log skeleton four times: `get_job_settings` (88–159), `get_hardware_info` (162–194), `get_xy` (197–237), `get_jobs` (240–272) — ~185 lines varying only in model object, sentinel, field, and validation. Protection has already drifted: only `get_job_settings` correlates the response with its query (`jobName` check, 122–135) and rejects blank-geometry transients (142–148). The other three accept the first non-sentinel value after the flush — a delayed response to a *previous* fire lands post-flush and is returned as fresh; for `get_xy` that can hand a confirm loop the pre-move position with a post-command `observed_at`, defeating the `_reading_value_after` gate on A→B→A move patterns. (LC-09)

**Target design.** One private primitive; each reader becomes a ~10-line adapter.

```python
_ACCEPT, _STALE, _RETRY = "accept", "stale", "retry"   # validator verdicts

def _flush_fire_poll(client, *, command, flush, read, validate=None, label=None,
                     timeout=1.0, poll_interval=0.01, max_retries=3):
    """Shared CAM read cycle: flush sentinel -> fire -> poll -> validate.

    validate(value) -> _ACCEPT (return it) | _STALE (keep polling: response
    belongs to an earlier fire) | _RETRY (restart the attempt: transient
    half-populated payload).
    """
    label = label or command
    for attempt in range(1, max_retries + 1):
        try:
            flush(client)
            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = command
            if not client.PyApiCommand.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
                log.warning("%s: attempt %d/%d receipt failed", label, attempt, max_retries)
                continue
            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                value = read(client)
                if value is not None:
                    verdict = _ACCEPT if validate is None else validate(value)
                    if verdict is _ACCEPT:
                        return value
                    if verdict is _RETRY:
                        break
                time.sleep(poll_interval)          # _STALE falls through here too
            log.warning("%s: attempt %d/%d timed out", label, attempt, max_retries)
        except Exception as e:
            log.error("%s attempt %d/%d failed: %s", label, attempt, max_retries, e)
    log.error("%s: all %d attempts failed", label, max_retries)
    return None
```

Before/after for one caller:

```python
# before: get_xy, 41 lines (197–237)
# after:
def get_xy(client, timeout=1.0, poll_interval=0.01, max_retries=3):
    def flush(c):
        c.PyApiGetXY.Model.XPosition = float("nan")
        c.PyApiGetXY.Model.YPosition = float("nan")
    def read(c):
        x, y = c.PyApiGetXY.Model.XPosition, c.PyApiGetXY.Model.YPosition
        if math.isnan(x) or math.isnan(y):
            return None
        return {"x": x, "y": y, "x_um": x * 1e6, "y_um": y * 1e6}
    return _flush_fire_poll(client, command="GetXY", flush=flush, read=read,
                            timeout=timeout, poll_interval=poll_interval,
                            max_retries=max_retries)
```

`get_job_settings` keeps its per-attempt `JobName` commit inside its `flush` and expresses its two guards as a `validate` returning `_STALE` (wrong `jobName`) / `_RETRY` (blank `imageSize`). Where the protocol offers no correlation field (`get_jobs`, `get_hardware_info`, `get_xy`), at minimum document the uncorrelated-response risk on the primitive and consider a double-read-agreement validator for `get_xy` (two consecutive identical reads) — that decision is now one place instead of four.

**Deleted:** ~185 lines → ~45 (primitive) + ~50 (four adapters); net ~90–110, and the stale-response guard becomes structurally impossible to drift. **Risk:** low-medium — this is the transport path, but it is pinned by `tests/unit/test_state_readers.py`, the mock's command-channel dispatch (`tests/helpers/mock_lasx_api.py:463–485` implements exactly this protocol), and the live `probe_four_readers.py` validator. Land as pure restructuring first (validators identical to today), add the `get_xy` agreement guard as a separate commit. **Effort:** S/M.

---

### RF-05 — Promote `experimental/lrp_edits` → `lrp_edits`; delete its dead surface

**Current state.** `experimental/lrp_edits/` is 2,192 lines. Verified consumer census on this tree:
- Production callers: exactly three functions — `galvo_pan_for_pixel`, `lrp_get_pan`, `lrp_set_pan`, imported function-locally by `commands/commands.py:1165–1166` inside `move_galvo_to_pixel` (the "primary galvo navigation primitive" per its own docstring). Nothing in `workflows/`, `shared/`, or the notebooks calls any other lrp_edits function.
- Dead with zero callers anywhere: `pixels_to_roi` + `center_vertices` (roi.py:432–507, ~70 lines; `mask_contour_to_roi` at roi.py:901 reimplements the same math), and the exported-but-uncalled `make_line` (412), `make_ellipse` (331), `make_polygon` (355 — a `list()` call whose docstring claims validation it doesn't do), `roi_to_pan_zoom` (868), `mask_contour_to_roi` (901), `disable_roi_scan` (169), `reset_pan` (scan.py:304). (LS-14, LS-15)
- The `experimental/` name misleads in both directions: it licenses dead code to accumulate, while `README.md:290` has to explain "despite the `experimental/` name this is load-bearing". (LS-13, LC-23)

**Target design.**
1. `git mv experimental/lrp_edits lrp_edits`; delete the now-empty `experimental/` package. Update the ~6 import sites (`commands/commands.py:1165–1166`, facade, tests) and the two comments that reference the old path (`connection/session.py:91`, `scanfields/parsers.py:56`). Delete the `parsers.py:56–58` re-export shim kept "so the (untouched) experimental package can keep importing" — the premise is stale (LS-12); `roi.py:101` imports from `scanfields.lrp` directly.
2. Delete `pixels_to_roi` + `center_vertices` outright.
3. For the seven uncalled-but-README-marketed helpers: the README sells lrp_edits as the offline mirror of the live `set_*` API for operator cookbooks, so wholesale deletion needs an owner call. The defensible split without one: delete `make_polygon` (adds nothing over `list`), `roi_to_pan_zoom`, and `mask_contour_to_roi` (duplicate coordinate math, no callers); keep `make_rectangle`/`make_ellipse`/`make_line`/`make_star` (cookbook shape authoring, coherent set), `disable_roi_scan`, `reset_pan` (documented cleanup steps) — and stop re-exporting all of them from the driver facade (RF-06), so the cookbook surface lives in `lrp_edits` itself.
4. `move_galvo_to_pixel`'s function-local imports become normal top-of-module imports — the layering inversion (production command depending on "experimental") disappears with the rename.

**Deleted:** ~220 lines (70 + ~110 of dead helpers + shim + empty package), more if the owner approves pruning the cookbook set. **Risk:** low — mechanical move pinned by the existing `test_lrp_edit_primitives.py` and the facade import test; grep for `experimental` afterwards. External notebooks that imported via `navigator_expert.experimental.lrp_edits` would break loudly at import — acceptable for a package whose name promised instability. **Effort:** S/M.

---

### RF-06 — Prune the 216-name facade to the real public surface

**Current state.** `__init__.py` is 532 lines: a 240-line `__all__` (216 names) plus ~250 lines of imports, needing file-wide `# ruff: noqa: E402,I001,F401` to exist. Verified against the LA review's repo-wide scan: 136 of 216 names are never consumed via the package root anywhere in the repo (the entire `lrp_*` block ~85 names, ROI authoring helpers, the OME check/fix septet, `LIMITS_SOURCE_MIGRATION`, ...); 14 exported names are underscore-private, including the *mutable process-global* `_stage_limits`; the grouping comments mislabel entries (`acquire` filed under `# commands` but bound from `acquisition.capture`, which the README calls out as gotcha #2); a `logging.Logger` (`log`) is exported. README §11 mandates double bookkeeping for every new symbol. (LA-05, LA-06, LA-18)

**Target design.** One decision, then mechanics:
- Public surface = what the README documents **and** something consumes via the root: connection/session, routed readers, command wrappers, motion (`set_stage_limits`, `apply_stage_limits_from_config`, `move_xy_with_backlash`, `correct_backlash`), acquisition (`acquire`, `save`, template state ops), config loaders. Roughly 80 names.
- Specialist surfaces (`lrp_edits.*`, ROI authoring, OME fix, log-reader internals) are imported from their submodules — which is what every in-repo consumer already does.
- Drop all underscore names from `__all__` (internal callers import from owning modules; `_readback`'s "genuinely public" comment gets resolved by renaming it in `confirmations` or keeping it internal); stop exporting `log`.
- Add the one honest freeze test from RF-01: `assert set(drv.__all__) == EXPECTED_SURFACE` with the literal list in the test.

Sketch of the resulting file: ~60-line `__all__`, grouped imports without the noqa blanket on F401 (re-exports keep a targeted noqa), the bootstrap block unchanged (or removed under RF-17).

**Deleted:** ~200 lines of `__init__.py`, plus the standing drift class of a facade that must be edited in two places per symbol. **Risk:** medium-low. The only real hazard is out-of-repo operator notebooks importing pruned names from the root; mitigate by staging — first drop the 14 underscore names + `log` + provably-dead constants (zero risk), then the `lrp_*`/ROI/OME blocks with a CHANGELOG note pointing at the submodule paths. **Effort:** S/M.

---

### RF-07 — Finish the CONFIRM_SPECS collapse: delete the `_confirm_*` wrapper layer

**Current state.** The table did its job — 16 confirmations are pure data (`commands/confirm_specs.py:149–186`) over one skeleton (`confirmations._confirm_readback`, 283–343). But the collapse stopped one layer short: `confirmations.py` still hand-writes 16 thin wrappers whose bodies are all `return _run_spec("<name>", ...)` — `_confirm_scan_field_rotation` (481–494), `_confirm_z_stack_step_size` (601–614), the tolerance quartet (681–764), the exact quartet (771–806), and six more (898–981) — ~230 lines of pure delegation. Because the wrappers are hand-written, `tests/unit/test_confirm_specs.py` (361 lines) exists largely to pin wrapper↔table equivalence "so the two cannot silently drift". Two more skeleton re-implementations sit alongside: `_confirm_image_format` (809–844) re-writes the whole poll loop because its target is the composed string `f"{w} x {h}"`, and `confirm_objective` (847–895) re-writes it for `ch["objective"]["slotIndex"]`. Related dead weight: `_readback`'s `observed_after` parameter has no caller (229–253, LC-16), and `commands.py` hand-builds seven identical Phase-A failure dicts (407–414, 422–430, 546–555, 565–574, 1063–1071, 1081–1089, 1274–1309) while `_fire_block` builds six identical timing dicts (dispatch.py:259–268 … 428–439) (LC-22).

**Target design.**
1. Replace the wrapper layer with one public binder in `confirmations.py`:
   ```python
   def confirm_spec(name, *, job_name, target, tolerance=None, **selectors):
       """Bind one CONFIRM_SPECS row to a zero-arg-able confirm callable."""
       return functools.partial(_run_spec, name, job_name=job_name,
                                target=target, tolerance=tolerance, **selectors)
   ```
   `commands.py` call sites change mechanically:
   ```python
   # before
   partial(_confirm_scan_speed, job_name=job_name, target=value)
   # after
   confirm_spec("scan_speed", job_name=job_name, target=value)
   ```
   Delete the 16 wrappers. The drift class the test file guards against no longer exists, so `test_confirm_specs.py` shrinks to what still carries information: table completeness vs. `BESPOKE_CONFIRMS`, per-row confirm/mismatch behavior of `_confirm_readback`, and tolerance defaults (now read from the table, the single source of truth, instead of byte-compared against wrapper signatures).
2. Fold the two skeleton re-implementations: `image_format` becomes a table row with extractor `ch["format"]` and the caller composing `target=f"{w} x {h}"` (its "special timeout text" is the label); `confirm_objective` calls `_confirm_readback` directly with `extract=lambda ch: ch["objective"]["slotIndex"]` and its mechanical-turret label, keeping its public name and longer default window. `BESPOKE_CONFIRMS` in the test shrinks accordingly.
3. Drive-by deletions in the same layer: `_readback`'s dead `observed_after` block; a `_phase_a_failure(message, **extra)` helper in `commands.py` and a single timing-dict constructor in `_fire_block` (the seven/six copies are already drifting — `move_xy`'s adds `"position"`).

**Deleted:** ~230 (wrappers) + ~60 (image_format/objective bodies) + ~60 (failure/timing dicts) + ~100 (test file shrink) ≈ 300+ net. **Risk:** low-medium. The confirm behavior itself is untouched (`_confirm_readback`/`_run_spec` unchanged); `TestSetFunctionWiring` and `TestConfirmFunctions` in `test_core_driver.py` pin every setter→confirm binding and every confirm outcome, and they run against the new binder unchanged except for patch targets (tests that patch `confirmations._confirm_scan_speed` must patch `_run_spec`/`confirm_spec` instead — grep says this affects a handful of wiring tests). **Effort:** M.

---

### RF-08 — One prolog-preserving LRP read/write pair (three write strategies → two)

**Current state.** The subsystem writes `.lrp` files three different ways:
1. Byte-preserving text splice — `lrp_edits/_primitives.py:27–87` (correct for attribute edits; keep).
2. Prolog-preserving ElementTree — `scanfields/transaction.py:44–89` (`reorder_jobs`): parses with `insert_comments=True`, re-splices the vendor prolog verbatim, forces UTF-8, with the rationale documented (83–89).
3. Naive ElementTree — `experimental/lrp_edits/roi.py:268/292` (`lrp_clear_rois`) and 553/625 (`lrp_add_roi`): `ET.parse(...)` + `tree.write(...)`, which drops every comment and the pre-root Leica header — the exact artifacts strategy 2 exists to preserve. Inside one `apply_lrp_change` the pipeline is therefore: ROI edit strips the prolog, then `reorder_jobs` carefully preserves what's left. Either the prolog matters (ROI edits corrupt every template they touch) or it doesn't (reorder's machinery is unjustified) — the code currently asserts both. (LS-16; C4 history shows this exact spot already produced a Critical once.)

**Target design.** Extract strategy 2 into two functions in `scanfields/lrp.py` (it already owns LRP parsing) and use them at all three ET sites:

```python
def read_lrp_tree(path) -> tuple[ET.Element, str]:
    """Parse an LRP preserving comments; return (root, verbatim prolog)."""
    raw = Path(path).read_text(encoding="utf-8")
    root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    start = raw.find(f"<{root.tag}")
    prolog = raw[:start] if start > 0 else '<?xml version="1.0"?>'
    return root, prolog

def write_lrp_tree(path, root, prolog) -> None:
    """Serialize root after the vendor prolog, always UTF-8 (see reorder_jobs
    rationale: LAS X writes declaration + header comments before the root,
    where ElementTree cannot represent them)."""
    Path(path).write_text(prolog + ET.tostring(root, encoding="unicode"), encoding="utf-8")
```

`reorder_jobs` becomes a caller (its body loses ~10 lines); `lrp_clear_rois`/`lrp_add_roi` switch from `ET.parse`/`tree.write` to the pair. The roi.py module docstring's "writing strategy" section then states one rule: text-splice for attribute edits, `read/write_lrp_tree` for structural edits.

**Deleted:** only ~20 lines net — the payoff is the bug class (silent prolog/comment destruction on every ROI edit) and the collapse of three serialization policies into two documented ones. **Risk:** low. Pin with a round-trip test: load a real fixture bundle from `tests/data/scanfield_parsing/`, `lrp_add_roi` + `lrp_clear_rois`, assert the prolog bytes and in-document comments survive (the `test_lrp_edit_primitives.py:117–131` prolog test for reorder shows the pattern). **Effort:** S.

---

### RF-09 — One atomic-JSON writer (4 → 1), `allow_nan=False` everywhere

**Current state.** Four writers, verified drift (LM-06):

| Writer | Lines | fsync | sort_keys | allow_nan | tmp+replace |
|---|---|---|---|---|---|
| `calibration/core/model.py:_atomic_write_json` | 45–54 | yes | True | **True** | yes |
| `motion/stage_config.py:_atomic_write_json` | 92–100 | yes | True | **True** | yes |
| `calibration/core/common.py:write_json_atomic` | 452–460 | no | False | False | yes |
| `config/machine.py:_write_json` | 89–93 | no | True | **True** | **no** (callers stage) |

The first two are byte-for-byte the same logic. The NaN drift is the substantive hazard: `validate_calibration` never checks finiteness, so a NaN introduced via `update_objective` serializes as a bare `NaN` token into the canonical `calibration.json` — exactly what the strict-JSON posture elsewhere (`common.py`, the strict-parsing tests) exists to prevent.

**Target design.** One function in `_file_utils.py` (the package's existing home for cross-cutting file helpers, imported by both `acquisition` and the root — no cycle):

```python
def write_json_atomic(path, payload, *, fsync=True, sort_keys=True, indent=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=indent, sort_keys=sort_keys, allow_nan=False)
        f.write("\n")
        if fsync:
            f.flush()
            os.fsync(f.fileno())
    os.replace(tmp, path)
```

`model.py` and `stage_config.py` delete their copies; `common.py` re-exports it (its callers pass `fsync=False, sort_keys=False` if the current behavior must be preserved — or just accept fsync, these are small files); `machine._write_json` becomes a call with `fsync=False` where the snapshot-staging rename already provides atomicity (`_seed_file`) and is deleted where it doesn't (`write_origin` keeps its own replace or switches wholesale). Add the missing finiteness check to `validate_calibration` in the same change.

**Deleted:** ~25 lines net; removes the NaN-in-canonical-calibration bug class and the "which writer has which guarantee" audit burden. **Risk:** low — behavior-visible changes are `allow_nan=False` (desired; a test writes a NaN through `update_objective` and asserts a loud failure) and fsync on paths that lacked it (safe). **Effort:** S.

---

### RF-10 — Typed calibration verdict instead of substring-matched prose

**Current state.** `image_to_stage.measure()` encodes its verdict in English (`failure_reason` set at image_to_stage.py:246, 263–265, 283–285, 288–291), and four consumers re-derive the verdict by matching that prose: `_operator_status_header` (`"reflection-free" in failure_reason` / `"singular" in ...`, image_to_stage.py:364/366), the `save_and_visualize` status ladder (594, then composing `f"{status} ({session.failure_reason})"` at 602–603), `common.plot_d4_candidates` (845–846), and `objective_pair._print_step5_summary`, which re-parses the *composed* string with `status.split(" (", 1)[0]` (objective_pair.py:287, composition at 850–851). Rewording any failure message — a natural doc-polish change — silently reroutes three UI layers to the generic branch, with no test failing at the source. (LM-04)

**Target design.** A five-value enum set once, read four times:

```python
# calibration/core/model.py (or common.py)
class Verdict(str, Enum):
    OK = "ok"
    WEAK_VOTE = "weak_vote"
    REFLECTION = "reflection"
    RESIDUAL = "residual"
    SINGULAR = "singular"
```

`ImageToStageSession` (image_to_stage.py:59–82) gains `verdict: Verdict | None = None` next to `failure_reason`; `measure()` sets both (prose stays, for humans). Consumers switch on the enum:

```python
# before (image_to_stage.py:364-366)
if failure_reason and "reflection-free" in failure_reason: ...
# after
if session.verdict is Verdict.REFLECTION: ...
```

`_print_step5_summary` reads `session.verdict` instead of un-parsing the composed status string. `ObjectivePairSession` (objective_pair.py:71–116) gets the same field if its status ladder wants it; otherwise leave it.

**Deleted:** ~10 lines, but removes the whole "reworded message silently breaks three UIs" class. **Risk:** near zero — the verdict is derived at the same points the prose already is; `test_workflows.py`'s status-ladder tests pin each branch, and one new test asserts prose can change without changing the verdict. **Effort:** S.

---

### RF-11 — `calibration/core` dedup + delete the dead `model.py` quartet

**Current state** (all verified on this tree):
- `model.py` public functions with no production caller: `save_calibration` (148–157, test-only), `set_reference` (296–309, test-only), `pixel_to_stage_xy_um` (384–401, test-only, and hardcodes a square image), and `reference_to_objective_command_xy` (368–381, **zero callers including tests** — fully dead). 56 lines + 27 lines of tests. (LM-09)
- `_f` duplicated byte-for-byte (`objective_pair.py:184–191` vs `image_to_stage.py:297–304`); `_registration_for_report` near-duplicated with drift already started (one handles `None`, one doesn't: objective_pair.py:194–202 vs image_to_stage.py:307–313). (LM-11)
- Inside `common.py`: three identical `_norm` closures (481–486, 647–652, 725–730) and two copies of the magenta/green overlay stacking (490–496, 732–739). (LM-15)
- IPython display / `plt.close` boilerplate repeated across both workflow modules (objective_pair.py:428–431, 471–478, 513–516, 556–563, 655–658, 742–749; image_to_stage.py:447–454, 543–549) — each occurrence carrying a bare `except Exception: pass`. (LM-16)
- Step 5 re-implements `_clear_parcentricity_target` inline (objective_pair.py:637–647 vs the helper at 332–343), already drifted by one field (`config_written`). (LM-10)

**Target design.** All destinations already exist in `common.py`:
- Delete the four `model.py` functions and their three tests (keep behavior coverage where it pins something else — none does).
- Move `_f` and the `None`-tolerant `_registration_for_report` to `common.py`; both workflow modules import them.
- Hoist `_normalize01(img)` and `_magenta_green(ref, tgt)` to module level in `common.py`; three call sites each.
- Add `common._display_and_close(fig)` (one try-import of IPython, one `plt.close`, one place for the swallowed exception with a debug log); ~8 call sites shrink to one line each.
- Replace the step-5 inline block with `_clear_parcentricity_target(session)` and fold `config_written = False` into the helper (its other callers pair it with `_invalidate_staging_config`, which already resets it — verify and note at the call sites).

**Deleted:** ~200 lines. **Risk:** low — pure consolidation of pure helpers; `test_workflows.py`'s 78 integration tests exercise every step and every rerun permutation, and its strict-JSON report parsing pins `_f`'s NaN→None behavior. **Effort:** S.

---

### RF-12 — Acquisition seams: shared candidate resolution; open the anchor TIFF once

**Current state** (verified in detail this review):
- The two collectors resolve `RelativePathName` differently: `navigator_expert_export.py:124` does `rel.lstrip("\\/").replace("\\", "/")` with a comment explaining the interior-backslash trap; `lasx_native_autosave.py:167` does `lstrip` only — the exact bug the nav comment documents, live in the sibling path. The native path additionally handles absolute paths and project-dir basenames (164–168), which the nav path lacks. (LS-24)
- The native path opens/reads the single anchor TIFF **four times** per acquisition: `TiffFile` at lasx_native_autosave.py:258 and again at 316, plus `extract_embedded_ome_xml` at 323 and again at 342 — and each `extract_embedded_ome_xml` call does a whole-file `read_bytes()` (`ome_canonical.py:204`) just to walk the first IFD. Native AutoSave stacks are the multi-GB case this exporter exists for. (LS-26)
- `save.py:309–313` `_append_summary_atomic` is dead in production (only caller: `test_acquisition.py:1092/1096`); `_persist_export` uses the three underlying helpers directly. (LS-28)
- Converters `_int_or_none`/`_float_or_none` exist in `ome_canonical.py:512–534`, `scanfields/_convert.py:8–24`, and `tests/hardware/compare_export_metadata.py:1047–1062`, with a semantic divergence (`_convert._to_int` parses `"3.0"`, `_int_or_none` rejects it); `ome_canonical.py:208` imports the private `_ome._read_tiff_tag_270`. (LS-32)

**Target design.**
- `acquisition/files.py` gains `candidate_paths(rel, base) -> list[Path]` encapsulating lstrip + interior-backslash normalization + absolute-path + basename fallbacks; both `_detect_from_relative_path` implementations call it. (Do **not** merge the two collectors — see Rejected R-03.)
- `collect_lasx_native_autosave` opens the anchor once (`with tifffile.TiffFile(anchor) as tif:`) and passes `tif` + the already-extracted OME bytes down to `_plane_sources_from_tiff`, `_metadata_from_native_tiff`, and `_vendor_metadata_sources`; `extract_embedded_ome_xml` grows a seek-based read in `_read_tiff_tag_270`'s caller instead of `read_bytes()` (it already has every offset it needs).
- Delete `_append_summary_atomic`; retarget its test at `_upsert_summary_record` + `_write_summary_atomic`.
- Rename `_read_tiff_tag_270` to a shared public name in `ome.py` (it is shared infrastructure and correctly *not* duplicated); pick `scanfields/_convert.py` as the one converter module and make `ome_canonical` use it (decide the `"3.0"` semantics once, with a test).

**Deleted:** ~50 lines; fixes one live path bug (interior backslash) and turns 2 whole-file reads + 2 TIFF parses into one open. **Risk:** low-medium — collector behavior is heavily pinned (`test_native_autosave.py`, `test_acquisition.py` fail-closed cases); the single-open restructure is mechanical plumbing of an already-open handle. **Effort:** S/M.

---

### RF-13 — Shared test fixtures for profile/limits globals and acquisition fixtures

**Current state.** Global-profile save/restore is hand-rolled in ≥8 places: `setUp`/`tearDown` pairs (`test_state_readers.py:23–26` and 336–339, `test_select_job_confirm.py:43–47`, `test_log_wait.py:45–48`, `test_validate_hardware_cli.py:24–28`) plus try/finally blocks (`test_core_driver.py:1246–1273`, 2551–2563; `test_log_reader.py:282–298`, 305–311, 321–326) — while three sites in the same file already use the clean idiom (`patch.object(profiles, "STATE_READERS", ...)`, test_core_driver.py:2939/2957/2991). `drv.set_stage_limits(...)` is called with no reset at test_core_driver.py:1956, 2219, 2608, 2657 — later tests pass only because every consumer re-sets limits first. The `naming`/`successful_acq` fixtures are declared twice (`test_acquisition.py:28–35, 113–120` vs `test_native_autosave.py:24–31, 34–41`, differing only in the job string). (LT-11, LT-17)

**Target design.** Three fixtures in `tests/conftest.py`:

```python
@pytest.fixture
def state_reader_profile(monkeypatch):
    def _set(**overrides):
        prof = dataclasses.replace(profiles.STATE_READERS, **overrides)
        monkeypatch.setattr(profiles, "STATE_READERS", prof)
        return prof
    return _set

@pytest.fixture
def log_reader_profile(monkeypatch): ...   # same shape, profiles.LOG_READER

@pytest.fixture
def stage_limits(monkeypatch):             # snapshot + restore _stage_limits
    saved = dict(limits._stage_limits)
    yield limits.set_stage_limits
    limits._stage_limits.clear(); limits._stage_limits.update(saved)
```

plus `naming` and a parameterizable `successful_acq(job="HiRes")` hoisted to conftest. unittest-style classes consume them via the documented `pytest` fixture-injection idioms or keep `patch.object` — the point is one blessed mechanism, not a rewrite.

**Deleted:** ~90 lines of per-file plumbing; removes the global-state-leak class (a forgotten `tearDown` poisoning later tests). **Risk:** near zero; mechanical, suite-pinned. **Effort:** S.

---

### RF-14 — Table-drive the surviving lrp_edits set/verify pairs *(after RF-05)*

**Current state.** `lrp_edits/{scan,z,general,focus}.py` (342 + 336 + 197 + 204 = 1,079 lines) hand-write ~25 set/verify pairs over the same four primitives (`_set_job_attr`, `_verify_job_attr`, `_verify_job_attr_float`, `_set_sequential_attr`). Each pair is the identical 10-line shape (coerce → `_set_job_attr`; mirror verify), e.g. `lrp_set_zoom`/`lrp_verify_zoom` (scan.py:30–46), `lrp_set_phase_x` (158–176), `lrp_set_sections` (z.py:75–101), the general.py sextet (29–150). Concrete drift already exists: tolerance defaults are scattered ad hoc (0.01 zoom, 0.1 phase, 0.001 pan, 0.5 µm z-position, 1.0 µm range, 0.1 pinhole) with no table to audit, and three paired name-attributes (`ScanDirectionXName`, `ZUseModeName`, `StackCalculationModeName`) are maintained by three hand-written enum dicts. This is exactly the shape `CONFIRM_SPECS` collapsed in the commands layer. (LS-17)

**Target design.** One descriptor table + two generators, preserving every public name:

```python
# lrp_edits/_specs.py
@dataclass(frozen=True)
class EditSpec:
    attrs: tuple[str, ...]                  # XML attribute(s) written
    coerce: Callable[[Any], str]            # python value -> attr string
    verify: str = "exact"                   # "exact" | "float"
    tolerance: float | None = None          # default for "float"
    name_attr: str | None = None            # paired *Name attribute
    enum: dict | None = None                # value -> (attr string, name string)

EDIT_SPECS = {
    "zoom":        EditSpec(("Zoom",), str, "float", 0.01),
    "scan_speed":  EditSpec(("ScanSpeed",), lambda v: str(int(v))),
    "image_format":EditSpec(("InDimension", "OutDimension"), _dim),
    "phase_x":     EditSpec(("PhaseX",), str, "float", 0.1),
    "scan_direction": EditSpec(("ScanDirectionX",), ..., name_attr="ScanDirectionXName",
                               enum={True: ("0", "UnknownDirection"), False: ("1", "Unidirectional")}),
    # ... one row per plain pair
}

# lrp_edits/generated.py — keeps the public API byte-compatible
for _name, _spec in EDIT_SPECS.items():
    globals()[f"lrp_set_{_name}"] = _make_setter(_name, _spec)
    globals()[f"lrp_verify_{_name}"] = _make_verifier(_name, _spec)
```

Genuinely bespoke editors stay as code: `lrp_set_z_stack_size` (computed begin/end around ZPosition), `lrp_set_stack_calculation_mode` (Master-element targeting), the ROI structural edits, `lrp_get_pan`. A drift test mirrors `test_confirm_specs`: every table row generates both functions; every bespoke function stays out of the table.

If the owner instead decides (under RF-05) that the cookbook mirror API can shrink to what cookbooks demonstrably use, prefer that — deletion beats generation. This proposal is the conservative path that keeps the README's documented surface.

**Deleted:** ~1,079 → ~350 (bespoke) + ~180 (table + generators + module docstrings): net ~450–550, and the tolerance/enum policy becomes one auditable page. **Risk:** medium — generated functions lose explicit signatures (acceptable: LA-05 verified nothing in-repo calls these; they are cookbook conveniences), and `test_lrp_edit_primitives.py` continues to pin the primitives underneath. Add one generated-vs-fixture round-trip test per verify kind against the real `.lrp` fixtures. **Effort:** M.

---

### RF-15 — Controller: own the post-disconnect guard; tighten three small seams

**Current state.** `zmart_controller` is small and healthy (385 production lines); these are the only refactor-grade items:
- `Session._closed` (layer.py:44) guards only double-disconnect; no op checks it. `test_ops_after_disconnect_raise` passes because the *mock* raises; the Leica adapter re-implements the guard in every op (`zmart_adapter.py:159–162`) and mesoSPIM has none — a controller op after `disconnect()` there hits a closed transport with an arbitrary error. Duplicated-or-forgotten safety logic in every driver is exactly what the thin controller exists to centralize. (ZC-03)
- `__init__.py:43` `set_instrument(*args, **kwargs)` erases the primary entry point's signature (ZC-04); `__init__.py:74–77` `__getattr__` delegates underscore attributes of the live session (`zmart_controller._handle` resolves — verified in the ZC review) (ZC-06); `registry.resolve()` returns its own argument in a tuple (registry.py:95–110, sole consumer unpacks and ignores it, ZC-11).

**Target design.**
```python
# layer.py — one helper, called first in each of the 12 forwarding methods
def _require_open(self):
    if self._closed:
        raise RuntimeError("session is disconnected; call set_instrument() again")
```
Then: `def set_instrument(instrument: dict[str, Any]) -> Session:` forwarding explicitly; `__getattr__` refuses `name.startswith("_")` before delegating; `resolve()` returns just the ops table. The Leica adapter's per-op `_require_open` becomes redundant defense-in-depth (keep or thin later); the existing `test_ops_after_disconnect_raise` becomes honest, plus one test against a scratch driver with no closed-state of its own.

**Deleted:** ~20 lines net (the adapter guard thinning is optional and larger). **Risk:** near zero; the controller suite runs in 0.05 s and covers each seam. **Effort:** S.

---

### RF-16 — One tile-grid generator for planned vs. materialized regions *(needs an owner decision)*

**Current state.** Two implementations of "geometry → tile grid" coexist with different contracts: `scanfields/parsers.py:345–441` (`_derive_positions_from_geometry_grid`, row-major, stamps the single global MatrixData count onto *every* Rectangle) and `scanfields/planning.py:152–283` (`_generate_from_geometries` + `_make_region`, column-major, flattens 2-D grids to `num_rows=1, col=i`). A consumer using `row`/`col`/`acquisition_order` for stitching gets a different contract depending on which template representation was on disk; the fixture-pair equivalence tests mask it by comparing *sorted* center sets (`test_scanfield_parsers.py:761–771`). (LS-02, LS-03; the driver-cleanup review noted the current behavior is "pinned by tests as intended; needs an owner decision".)

**Target design.** One generator in `planning.py` — `tiles_for_geometry(geom, tile_w, tile_h, overlap_pct) -> list[Tile(ix, iy, cx, cy)]` — emitting true `(row, col)` indices in row-major order; `parsers._derive_positions_from_geometry_grid` consumes it (keeping its XML-count validation and failing loudly for >1 Rectangle until the multi-geometry semantics are established with a fixture), and `_make_region` maps `Tile` to region fields instead of inventing `num_rows=1`. Tighten the fixture-pair test to compare ordered sequences. This is the only proposal that changes observable output (tile *ordering* for planned regions), which is why it is ranked despite collapsing a real parallel implementation: do not land without the owner confirming no downstream consumer depends on the current column-major planned order.

**Deleted:** ~80 lines; removes the three-contracts-for-one-concept class. **Risk:** medium (behavioral, owner-gated); the ground-truth fixture pairs in `tests/data/scanfield_parsing/` are the pin once tightened to ordered comparison. **Effort:** M.

---

### RF-17 — Package the repo; retire the bootstrap constellation

**Current state.** `pyproject.toml` has lint config only — no `[project]` table, so nothing is installable. The workarounds are everywhere: the driver `__init__.py:260–274` mutates `sys.path` at import; `tests/conftest.py` and `run_ci.py` re-do it per entry point; `zmart_controller/tests/conftest.py:13–17` and both example notebooks carry their own copies; `calibration/notebooks/_bootstrap.py` and `limits/notebooks/_bootstrap.py` are near-identical shims with fragile `parents[6]`/`parents[3]` indexing (LM-30); RF-01 deletes the 13 per-test-file copies but the root cause remains. (ZC-14, LA-19, LT-10)

**Target design.** Add a minimal `[project]` table + setuptools package discovery for `zmart_controller`, `zmart_drivers`, and `shared`; document `pip install -e .` in the two READMEs. Then, incrementally: controller conftest shrinks to `register_mock()`; notebooks lose their path cells; the two `_bootstrap.py` shims and the `workflows/target_acquisition` insert in `tests/conftest.py:26–28` (already dead — nothing imports `pipeline`, LT-18) are deleted. Keep the driver `__init__` bootstrap for one release (the scope PC runs from a checkout) with a comment naming packaging as its replacement, then remove.

**Deleted:** ~80 lines across the repo plus three classes of "works from this directory only" surprises. **Risk:** medium — the microscope-PC flow runs unpackaged from a checkout, and three bootstrap mechanisms are load-bearing today (one is subprocess-tested); hence the staged retirement rather than a big bang. **Effort:** M.

---

## Considered and rejected

Recorded so future reviewers don't re-litigate them.

- **R-01 — Typed result dataclass for command results.** The `{"success", "confirmed", "message", "timing", "logs"}` dict is a documented operator contract (README §5), crosses the controller seam (which speaks dicts by design), and is asserted by hundreds of tests. Converting deletes zero lines and churns ~40 call sites + every test; the observed drift (LC-22's hand-built dicts) is fixed by the two tiny constructors in RF-07 instead.
- **R-02 — Unify `ome.py` and `ome_canonical.py`.** Verified: not duplication. `ome.py` is byte-level vendor-fix surgery (regex + struct patching that must preserve exact bytes); `ome_canonical.py` is ElementTree generation of our own output. They share exactly one helper (`_read_tiff_tag_270`) and correctly share it rather than reimplement it. The real gaps are LS-21 (the fixer has no tests — a testing task, not a refactor) and the two small seams folded into RF-12.
- **R-03 — Fully unify the two export collectors.** The export shapes are genuinely different: many flat single-plane TIFFs + per-timepoint companion XML vs. one self-describing multipage TIFF + XLEF container; completeness semantics, ambiguity policy, and cleanup support differ intrinsically. Extract only the path/freshness primitives (RF-12); a merged collector would be a boolean-riddled superset.
- **R-04 — Generate the `set_*` command wrappers from a table.** Unlike the `_confirm_*` layer (RF-07), the setters carry real per-command content: Phase-A validation, enum resolution, unit conversion, and operator-facing signatures/docstrings that are the driver's primary API. `_dispatch_setting` already removed the mechanical part; what's left is information, not boilerplate.
- **R-05 — Routed readers always return `Reading` (kill the `diagnostics` boolean).** The boolean does switch return *types*, which is normally a smell — but the plain-value shape is the documented notebook/operator contract and the `Reading` shape is the internal confirm contract; both have real constituencies. The actual hazard (production accommodation of non-`Reading` shapes, LC-05/LA-02) is fixed by deleting the accommodation branches, already filed in those reviews.
- **R-06 — Extract the `run_ci.py` step-runner into `shared/`.** Three drivers × ~200 lines with deliberate divergence; the LT review's own advice stands: extract when a fourth driver appears, not before.
- **R-07 — Split `commands.py` (1,465) / `confirmations.py` (1,159) into more modules by size.** After RF-07 the files shrink and both have clear section structure and a single backbone each; splitting would churn imports and history for no deleted line. Size alone is not the problem here.
- **R-08 — `__getattr__`/ops-table magic for `Session` forwarding.** The twelve hand-written methods are a deliberate, documented trade (signatures, docstrings, IDE support for the notebook-first surface). Leave them.
- **R-09 — Micro-dedups below the threshold:** adapter `_select_job_or_raise` (4×3 lines, LA-14), `_leica_setting_profile` inlining (LM-18), `_load_image_to_stage` single-key dict (LM-21), `objective_config_name` bypass (LM-13). Fine as drive-bys inside neighboring work; none justifies a change on its own.
- **R-10 — Wholesale unittest → pytest conversion (LT-19).** Idiom churn across ~11 files with no behavior payoff; declare pytest-style for new tests and convert opportunistically.
- **R-11 — Log-reader incremental parsing / caching layer.** The stateless whole-file parse is a deliberate rotation-safety trade. The cheap `(st_size, st_mtime_ns)` short-circuit from LC-12 is a ~10-line perf fix already filed there — worth doing, but it is not a refactor and adding a stateful parse cache would be new complexity in a fail-closed path.
- **R-12 — Delete the lrp_edits cookbook mirror API outright.** Tempting (in-repo callers: three functions), but the README markets it as the offline mirror of the live `set_*` API for operator cookbooks that live outside this repo. That call belongs to the owner; RF-05 deletes the provably-dead subset and RF-14 collapses what remains either way.

---

## Summary table

| ID | Payoff | Effort | Deletes (est. lines) | Title |
|---|---|---|---|---|
| RF-01 | High | S | ~550 | Delete self-referential/fossil test weight + redundant bootstraps |
| RF-02 | High | S | ~0 (−100 s/run) | Injectable sleeps: confirm windows, echo settle, export timeout |
| RF-03 | High | S | ~90–170 | Delete dead reader-evidence subsystem; decide hybrid race |
| RF-04 | High | S/M | ~110 | One flush-fire-poll primitive with correlation in `api_reader.py` |
| RF-05 | High | S/M | ~220 | Promote `experimental/lrp_edits` → `lrp_edits`; delete dead surface |
| RF-06 | Med-High | S/M | ~200 | Prune the 216-name facade to the consumed, documented surface |
| RF-07 | Med-High | M | ~300 | Delete the `_confirm_*` wrapper layer; bind CONFIRM_SPECS directly |
| RF-08 | Medium | S | ~20 (+bug class) | One prolog-preserving LRP read/write pair |
| RF-09 | Medium | S | ~25 (+bug class) | One atomic-JSON writer, `allow_nan=False` everywhere |
| RF-10 | Medium | S | ~10 (+bug class) | Typed calibration verdict enum |
| RF-11 | Medium | S | ~200 | `calibration/core` dedup + dead `model.py` quartet |
| RF-12 | Medium | S/M | ~50 (+I/O 4×→1×) | Acquisition seams: shared candidate resolution, single anchor open |
| RF-13 | Medium | S | ~90 | Shared fixtures for profile/limits globals + acquisition fixtures |
| RF-14 | Medium | M | ~450 | Table-drive the surviving lrp_edits set/verify pairs |
| RF-15 | Medium | S | ~20 (+bug class) | Controller-owned post-disconnect guard + three seam fixes |
| RF-16 | Low-Med | M | ~80 (+bug class) | One tile-grid generator (owner-gated ordering change) |
| RF-17 | Low-Med | M | ~80 | Package the repo; staged retirement of bootstrap shims |

**Grand total (all proposals): ~2,600–3,200 deleted lines, ~100 s removed from every offline suite run, and five whole bug classes retired** (uncorrelated CAM responses, NaN in canonical calibration, prolog-destroying ROI edits, prose-matched verdicts, post-disconnect ops on real hardware).
