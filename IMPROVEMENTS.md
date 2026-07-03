# ZMART Microscopy — Exhaustive Improvement Plan

Scope: the Leica Navigator Expert driver
(`microscopes/drivers/vendor/leica/navigator_expert/`) and the
target-acquisition controller (`workflows/target_acquisition/`).

Guiding philosophy (per request + the
[ponytail](https://github.com/DietrichGebert/ponytail) lens): **the best code is
the code you never wrote — the diff's best outcome is getting shorter.** Every
item below is tagged and, where it removes code, carries an estimated line delta.
Everything here is achievable **without hardware testing** — each item lists how
it is verified offline (unit tests, `ruff`, import check, or pure text). A short
final section lists the changes that *do* need hardware and are therefore
explicitly out of scope.

### Tag legend

| Tag | Meaning |
|---|---|
| `fix` | Corrects a bug or a broken/blocking state |
| `delete` | Dead / unused / speculative code removed outright |
| `shrink` | Same behaviour, fewer lines (collapse duplication) |
| `yagni` | Abstraction/config/layer with a single user — inline it |
| `stdlib` | Hand-rolled logic the standard library already provides |
| `doc` | Documentation/comment brought back in sync with code |
| `org` | Organization/consistency/naming, behaviour unchanged |

### Estimated net effect

| Bucket | Approx. lines |
|---|---|
| Deletions (Part D) | **−4,500 to −5,200** |
| Simplifications (Part E) | **−700 to −1,000** |
| Fixes + docs + org (Parts A–C, F) | roughly net zero (small +/−) |
| **Total** | **≈ −5,000 to −6,000 lines** |

The driver + workflow are ~24.7k source lines today; this plan removes roughly a
fifth of that while making the rest run and read cleanly.

---

## Part A — Blockers: make the repo run on a fresh checkout

These come first: nothing else can be validated until the checkout works.

| # | Tag | Location | Change | Verify |
|---|---|---|---|---|
| A1 | `fix` | `workflows/target_acquisition/_bootstrap.py:18`, `workflows/target_acquisition/tests/conftest.py:9`, `microscopes/calibration/vendor/leica/navigator_expert/notebooks/_bootstrap.py:6`, `microscopes/calibration/vendor/leica/navigator_expert/tests/conftest.py:10` | `"driver"` → `"drivers"` in the sys.path join (half-applied rename from `95349dc`). | `pytest workflows/target_acquisition/tests` collects and passes (344 tests). |
| A2 | `fix` | `microscopes/drivers/.../tests/unit/test_stage_config.py:80` | Drop `assert current_limits.exists()` (it's a gitignored runtime artifact); keep the path-equality assertions. | Test passes on clean clone. |
| A3 | `fix` | `microscopes/drivers/.../tests/unit/test_acquisition.py:705` | Wrap the `ome_types` import in `pytest.importorskip("ome_types")` so the offline suite doesn't hard-fail when the optional validator isn't installed. | Test skips (or passes) instead of erroring. |
| A4 | `fix` | `pyproject.toml` | Add a real dependency list. Runtime: `numpy`. Optional groups: `viz` (`matplotlib`, `ipython`), `io` (`tifffile`, `ome-types`), `calibration` (`opencv-python-headless`, `scikit-image`, `scipy`, `pandas`), `test` (`pytest`). Today it declares **none**. | `pip install -e '.[test]'` then offline suites run. |
| A5 | `doc` | `workflows/target_acquisition/tests/conftest.py:7` | Comment says `smart-microscopy/`; repo is `ZMART-microscopy`. | Text. |

---

## Part B — Correctness fixes (unit-testable, no hardware)

| # | Tag | Location | Change | Verify |
|---|---|---|---|---|
| B1 | `fix` | `commands/confirmations.py:1390-1404` (`confirm_acquire`) | Do **not** let a `"Unknown"`/errored/stale scan-status read set `saw_scanning=True`. Treat `Unknown` as evidence of nothing (matches `check_idle`'s fail-closed doctrine), so a transient read right after firing can't produce a false `success=True`. | Add a unit test with a mock reader returning `None`/error then `Idle,Idle`; assert no false success. |
| B2 | `fix` | `runtime/session.py:108-113` (`require_canonical_scan_orientation`) | Raise (or hard-fail with a clear message) when `get_lasx_settings()` returned `None` or the `image_orientation` section is absent — currently it fails *open*, defeating the guard. | Unit test: patch `get_lasx_settings` → `None`; assert raises. |
| B3 | `fix` | `state_readers/derived.py:44-46` (`base_fov_from_settings`) | Remove the silent `if current_zoom < 1: current_zoom = 1` clamp (mis-scales galvo pan by up to ~33% at zoom 0.75, which the repo's own mock declares). If sub-1 zoom is truly impossible, `log.warning` instead of rewriting. | Unit test with `zoom.current=0.75`; assert FOV scales by 0.75. |
| B4 | `fix` | `pipeline/selection.py:203-207` (`load_overview_result`) | Read `n_tiles_acquired`/`n_tiles_hijacked`/`simulated` with `.get(...)` defaults (as adjacent keys already do) and/or add `KeyError` to the except tuple, so a pre-counter meta file warns instead of crashing — the exact reload-recovery path this function exists for. Honor `schema_version`. | Unit test: meta dict missing the three keys → returns `completed=False` with a warning. |
| B5 | `fix` | `commands/commands.py:1071-1072,1134-1135` (`move_xy`) | Return the confirmed readback (`last_position` from `confirm_move_xy`) as `"position"` when available; only fall back to the echoed target on the unconfirmed path, clearly labelled. Docstring currently promises a readback but returns the target. | Unit test asserting `position` matches the confirmed readback, not the requested target. |
| B6 | `fix` | `commands/dispatch.py` steps 1 & 4 + `commands/settings.py:44-50` | Wrap the pre-check and error-check steps in the same try/except the setup/fire steps use, so `set_scan_resonant`'s readback (added in `ff8ad93`) can't `raise ValueError` out of the backbone — every command must return a result dict. | Unit test: error-check raises → command returns `{"success": False, ...}`. |
| B7 | `fix` | `runtime/errors.py:129-159` (`_check_api_error`, `_read_echo_details`) | Guard `echo.HasError`/`echo.Error` reads (including inside the except branch that fired *because* the COM object was unreadable) the same way `int(echo.Result)` is guarded. | Unit test with a mock echo whose `HasError` raises. |
| B8 | `fix` | `pipeline/summary.py:75` | `"timestamp": ctx.out_dir.name` is a run-name string, not a timestamp. Either rename the field to `"run_name"` or store a real ISO timestamp captured at run start. | `test_summary_schema.py` assertion. |
| B9 | `fix` | `pipeline/target.py:245-273` | Set `stage="save"` before `drv.save(...)` so save failures aren't mislabelled `"acquire"`; drop the nonexistent `"zoom"` stage from the docstring. | Unit test forcing a save exception; assert `failure_stage=="save"`. |
| B10 | `fix` | `pipeline/_mock_provider.py:79-80` | When tile size ≥ the 512² source, offsets collapse to 0 and every tile is identical. Derive a per-tile offset that wraps (`(g*step) % max(1, sh)`), or tint per index, so simulated tiles differ. Simulation-only. | Add a 512² case to `test_hijack.py`; assert distinct tile content. |
| B11 | `fix` | `pipeline/overview.py:429-432` | Replace the bare `assert n_results + len(new_failures) == n_tiles_submitted` (vanishes under `python -O`, loses the session when it fires) with an explicit `raise RuntimeError(...)` after the meta is persisted. | Unit test that triggers the mismatch. |
| B12 | `fix` | `scanfields/files.py:254-281` (`save_and_read_lrp`) | Honor the docstring: return `None` when the save/confirm fails instead of parsing a possibly-stale LRP; confirm on the **LRP** path (like `apply_lrp_change`), not the XML. | Unit test with a save that never confirms → returns `None`. |
| B13 | `fix` | `pipeline/_log_capture.py:119,230-233` | Move the post-open `handle.write(_separator())`/`flush()` inside the guarded block (or wrap it) so a disk-full write can't escape the "must never block the pipeline" contract. | Unit test: patch `write` to raise; assert the wrapped step still runs. |
| B14 | `fix` | `pipeline/_save_queue.py:40-42,94-131` | `drain()` applies the shutdown timeout **per future** (16 × 30 s worst case). Track a single deadline across the loop so the promised total bound holds; fix the constant's misleading comment. | Unit test: many gated futures, assert total wait ≤ budget. |

---

## Part C — Documentation drift (pure text, no hardware)

| # | Tag | Location | Change |
|---|---|---|---|
| C1 | `doc` | Root `README.md` (Quick Start, Basic Workflow, "Result Dictionary") | The exported `acquire` returns a frozen `AcquisitionResult` and **raises** on failure. Rewrite examples to `result.timing.total_s` (attribute access) and `try/except RuntimeError`; delete the "every command returns a result dict" claim for the facade `acquire` (it describes the unexported `commands.acquire`). |
| C2 | `doc` | Root `README.md` read-only function table | Fix signatures: `ping(client)`; `get_jobs/...` defaults `timeout=1.0, poll_interval=0.01`; scan-status value `"eScanIdle"` (not `"eIdle"`). |
| C3 | `doc` | Root `README.md:476` dependency DAG | Remove imports `dispatch` doesn't have; add `runtime.session`, `runtime.lasx_runtime`. |
| C4 | `doc` | `overview.py`, `focus.py`, `preflight.py`, `pipeline/__init__.py:5-7`, `workflows/target_acquisition/README.md` | Unify step numbering across README, docstrings, and the `[step N]` console prints (three currently disagree; `__init__` says "six" then lists seven). Pick one scheme and make all three match. |
| C5 | `doc` | `runtime/utils.py:16-18` | Delete the "import and override these to tune" note — Python import semantics make it impossible; point to per-profile `receipt_timeout`/`confirm_timeout` instead. |
| C6 | `doc` | `commands/*` setting wrappers + `select_job` docstrings | Either wire `pre_check_timeout` to something (see E-block) or stop documenting it as functional; fix `select_job`'s docstring ("no pre_check_fn") to match reality (it blocks indefinitely on idle). |
| C7 | `doc` | `_file_utils.py:7`, `state_readers/api_reader.py:27-32`, `scanfields/roi.py:90`, `experimental/lrp_edits/z.py:9`, `scanfields/files.py:7-8`, `pipeline/_hijack.py:198-201`, `pipeline/_geom.py:8`, various `tests/*` docstrings | Fix stale "Imports/Imported by" notes naming renamed-away modules (`templates`→`scanfields`, `positions`→`scanfields.parsers`, a nonexistent `_save_atomic`), and `_geom.py`'s "two functions" (there are three). |
| C8 | `doc` | `acquisition/ome.py:143-146,243-245` | Remove the "(requirement N)" section headers referencing an external doc not in the tree. |
| C9 | `doc` | `scanfields/roi.py:526-527 vs :849`, `roi.py:351-362` | Resolve the degrees-vs-radians contradiction for `Rotation`; fix `make_polygon`'s "validates the input format" (body is `return list(vertices)`). |
| C10 | `doc` | `tests/unit/test_selection.py:108-110`, `test_summary_schema.py:28-46,238-239`, `test_scanfield_parsers.py:5` | Fix test comments contradicting fixtures, delete the dead `MagicMock` cfg setup, fix the stale filename. |

---

## Part D — Deletions (`delete:` — the biggest win)

Every item here has been grep-verified to have no production caller. Removing
each also removes its `__all__` re-export in
`navigator_expert/__init__.py` and any dedicated test.

| # | Tag | Target | Lines | Notes / verification |
|---|---|---|---|---|
| D1 | `delete` | `experimental/lrp_edits/general.py`, `focus.py`, `z.py`, `scan.py` (minus `reset_pan`), and all of `roi.py` **except** what `move_galvo_to_pixel` needs | ~**1,700** | Grep: only `lrp_set_pan`, `lrp_get_pan`, `galvo_pan_for_pixel` have callers (via `move_galvo_to_pixel`). Everything else (`lrp_set_zoom`, `lrp_add_roi`, `lrp_clear_rois`, `make_star/rectangle/ellipse/line/polygon`, `disable_roi_scan`, `reset_pan`, all of `z.py`/`focus.py`/`general.py`) has **zero** non-export references. Keep a slim `experimental/lrp_edits/pan.py` with the three used functions + their `_primitives` deps. Verify: `pytest` + import check. |
| D2 | `delete` | `experimental/lrp_edits/` test files for the removed modules | ~**300+** | Remove tests that only cover deleted code. |
| D3 | `delete` | `state_readers/change_wait.py` + `tests/unit/test_change_wait.py` + its `__init__` export + `change_wait_*` fields in `profiles.py` (127-136) | ~**1,100** | No production caller (router uses `capabilities`, not `change_wait`); only consumer is the hardware probe `probe_four_readers.py`. |
| D4 | `delete` | `state_readers/capabilities.py` evidence-leg half (`59-63,104-155,196-199,219-221,233-241`) | ~**120** | Keep `spec`/`age_for_snapshot`/`UnsupportedSource` (used by router); drop the evidence-leg machinery only the probe used. |
| D5 | `delete` | `acquisition/ome.py:470-635` (`update_ome_tiff_filename`, `update_ome_xml_filename`, `_update_filenames_in_xml`, `_replace_filename_in_path`, regexes `_RE_IMAGE_NAME`/`_RE_DESCRIPTION`) + their `__all__` entries | ~**170** | Zero callers; save path emits canonical OME from scratch. |
| D6 | `delete` | `state_readers/api_reader.py` unused readers `get_fov`, `get_base_fov`, `get_job_by_name`, `read_zwide_um` (router reimplements all four) | ~**80** | Grep shows production calls the routed versions; `read_zwide_um` currently exists in three drifting copies — keep only the router one. |
| D7 | `delete` | `runtime/profiles.py:435-461` `ACQUIRE_SINGLE_IMAGE` (field-for-field identical to `ACQUIRE`) | ~**15** | Replace references with `ACQUIRE` or an explicit alias. |
| D8 | `delete` | `correct_fn` plumbing: `CommandProfile.correct_fn` (`profiles.py:240`), the branch in `dispatch.py:459-460,619-633`, and the pass-through in `commands.py:221` | ~**40** | "Stubbed for future use"; no profile sets it. Classic `yagni`. |
| D9 | `delete` | `commands/confirmations.py:207,220-226` — `_readback`'s `observed_after` param + timestamp-gate branch | ~**10** | All 23 call sites pass two args; branch is dead. |
| D10 | `delete` | `scanfields` unused public API re-exported through both `__init__` layers: `save_and_read_lrp` (if B12 doesn't keep it), `get_master_attrs`, `get_rois`, `diff_lrp`, standalone `reorder_jobs` | ~**120** | Grep: zero callers. |
| D11 | `delete` | `pipeline/tests/test_hijack.py:51-66` `_OME_DESC_TMPL` (defined, never used); `plot_target_pairs` dead `enumerate` (`visualize.py:1676`); `_classify_cells_for_scatter`'s unused `crops_to_show` param (`visualize.py:859-887`) | ~**25** | Grep + tests. |
| D12 | `delete` | `navigator_expert_export.py:107` unused alias `_media_path`; `lasx_native_autosave.py` unused `store_separate_folders` field | ~**5** | Grep. |
| D13 | `delete` | `acquisition/materialize.py:126-127` `extract_embedded_ome_xml` one-line pass-through (only a test import path) | ~**5** | Point the test at `_canonical.extract_embedded_ome_xml`. |
| D14 | `delete` | `__init__.py` facade: names imported but absent from `__all__` (`correct_backlash`, `move_xy_with_backlash` — decide export vs. drop), the misfiled `disable_roi_scan` under "session helpers", duplicate consecutive imports from `scanfields.strip_restore` (387-388) | ~**5** | AST/import check. |

**Part D subtotal: roughly −3,700 to −4,000 lines of source + tests directly,
and by removing `experimental` as a public concern the `__init__.py` facade
(`541` lines, `223`-entry `__all__`) shrinks substantially.**

---

## Part E — Simplifications (`shrink:` / `yagni:`)

| # | Tag | Location | Change | Est. lines |
|---|---|---|---|---|
| E1 | `shrink` | `commands/confirmations.py` — 21 `_confirm_*` functions | Collapse the identical ~40-line poll skeleton into one `_poll_confirm(client, job, extract_fn, matches_fn, label, timeout=...)` helper; each command becomes a 2–4 line call. (Not a closure factory — the thing the module rightly avoids.) | **−600 to −800** |
| E2 | `shrink` | `scanfields/parsers.py:1185-1270` | `_parse_laser`/`_parse_shutter`/`_parse_multiband`/`_parse_lut` are four byte-identical "dict(attrib)+optional _BeamRoute" wrappers — fold into one. | −40 |
| E3 | `yagni` | `pipeline/visualize.py:142-161` | `_ScatterLayer` + `_LAYERS` registry sells extensibility for two entries while `test_polish.py` pins `len(_LAYERS)==2` and forbids a third. Inline the two scatter calls. | −40 |
| E4 | `yagni` | `pipeline/context.py:132-141,159-160` | `WorkflowRun` is a one-field wrapper around `LayoutPlan`, and `Context.out_dir` duplicates `run.layout.run_dir`. Replace both with a single `ctx.layout` field. | −20 |
| E5 | `shrink` | `pipeline/visualize.py:1261-1276 vs 1964-1974` | Deduplicate the cellpose-bbox fallback-window math (currently two copies that can drift — the exact class `_geom.py` was built to prevent). | −15 |
| E6 | `shrink` | `pipeline/visualize.py` live vs. batch target renderers (`display_target` / `plot_target_pairs`) | Extract the shared tif-read + 3-panel + suptitle + save into one helper; fixes the inconsistent font sizes and the missing `try/finally: plt.close` in `plot_overview_tiles` as a side effect. | −60 to −120 |
| E7 | `shrink` | `commands/commands.py:1140` + `runtime/utils.py:62` | Delete private `_PAN_LIMIT`; import the documented `utils.PAN_LIMIT`. | −3 |
| E8 | `shrink` | `scanfields/parsers.py:65` + `planning.py:17` | One `UNASSIGNED_JOB` constant, imported (parsers already imports from planning). | −2 |
| E9 | `yagni` | `commands/dispatch.py` `method="async"` | Field is always `"async"` (its default) and meaningless for sync commands — remove the param and the field, or set it correctly. | −10 |
| E10 | `shrink` | `pipeline/target.py:55-60` + `visualize._position_label` | Drop the "one-line twin"; import `visualize._position_label` at function scope (the pattern `display_target` already uses two functions down). | −6 |
| E11 | `shrink` | `pipeline/preflight.py:140-142,430-432` | `_put_analysis_repo_first` is called twice back-to-back — drop the inline call. | −2 |
| E12 | `shrink` | `state_readers/router.py:299-404` | Router re-declares the API tunables (`timeout=1.0, poll_interval=0.01, max_retries=3`) in every signature, shadowing `api_reader`'s identical defaults. Reference one source. | −20 |
| E13 | `stdlib` | `state_readers/log_reader.py:217-305` | `parse_log` does `f.readlines()` + full regex scan on every call (~10 Hz). Track a byte offset and read only the tail (stdlib `seek`/`tell`), or memoize by mtime+size. Fewer lines *and* far less work. | ~net 0, big perf win |

---

## Part F — Organization / consistency (behaviour unchanged)

| # | Tag | Location | Change |
|---|---|---|---|
| F1 | `org` | `pipeline/_acquire.py` | Rename `acquire()` → `position_stage()` (it explicitly does *not* acquire; it sits two lines from `drv.acquire()`). Removes the docstring whose whole job is to disclaim the name. |
| F2 | `org` | `acquisition/ome.py` | Rename → `ome_vendor_fix.py` (it *repairs vendor* OME; `ome_canonical.py` *emits canonical* OME) and bring it up to the package's typed/`from __future__ import annotations` style. Clarifies the confusing two-modules-named-"ome" split. |
| F3 | `org` | `stage/__init__.py` (empty 0-byte) and driver root reaching across the `_`-private boundary (`from .stage.limits import _check_xy_limits, ...`) | Give `stage/__init__.py` a docstring + explicit re-exports, and expose the limit checks under public names so the facade stops importing `_`-private symbols. |
| F4 | `org` | `pipeline/preflight.py:288-299` (`_ensure_cam_api_mode`) | Stop poking raw `.NET` attributes and overriding the API delay the driver just set — call the driver's `configure_lasx_api_delay` helper (single source of truth). *(Behaviour-preserving refactor; verify against the driver unit tests, not hardware.)* |
| F5 | `org` | `pipeline/_job_state.py:40-47` | Replace the substring match on the driver's human message + timing heuristic with a structured field from the driver result, so a wording change can't flip behaviour. Requires exposing a boolean on the driver's result. |
| F6 | `org` | `template.py`, `focus.py` vs `visualize.py` | Move the shared style tokens (focus-marker geometry, hex colors, font sizes) into one module the three renderers import, so the palette can't drift. |
| F7 | `org` | `stage/config.py` | Either read `backlash.approach`/`tolerance_um` in `movement.py` or drop them from `_REQUIRED_BACKLASH` (currently required-but-ignored); add a cross-reference between the two `SCHEMA_VERSION = 11` constants (`config.py`, `calibration/core/model.py`) or derive one from the other. |
| F8 | `org` | `state_readers/router.py:183-193` | Make the diagnostics contract symmetric: return a `Reading` carrying the error for API exceptions/untrusted values under `diagnostics=True` instead of bare `None`; document (or unify) the api-vs-log `trust` asymmetry. |
| F9 | `org` | `pipeline/__init__.py`, module naming | `_bootstrap.py` is the *most public* file (notebook entry point) yet underscore-named; consider `bootstrap.py`. `_saved.py` (one function) could fold into a neighbour. |
| F10 | `org` | `microscopes/drivers/.gitignore` vs root `.gitignore` | De-duplicate the two ignore files (near-identical); keep one. |

---

## Part G — Repo hygiene

| # | Tag | Change |
|---|---|---|
| G1 | `org` | Add a minimal CI (GitHub Actions) that installs `.[test]` and runs the four offline suites + `ruff check`. This is what would have caught A1–A4. |
| G2 | `doc` | Add a one-line "offline test" quickstart to the README that actually works post-A1 (currently the documented command fails). |
| G3 | `org` | `pyproject.toml`: add `[tool.pytest.ini_options]` with the `pythonpath`/`testpaths` so tests run with a bare `pytest` and the four `_bootstrap`/`conftest` path-hacks can eventually be deleted (`yagni` on the sys.path juggling). |
| G4 | `org` | Notebook `smart_microscopy_v3.2.ipynb`: strip committed cell outputs/execution counts (hygiene) and confirm it references current pipeline signatures. |

---

## Out of scope here — needs hardware / live LAS X

Listed for completeness; **not** part of this no-hardware pass:

- End-to-end validation of B1/B2/B5/B6/B12 against a real STELLARIS or the LAS X
  simulator (unit tests cover the logic; a live run confirms the hardware
  contract).
- Any change to the backlash motion sequence in `stage/movement.py` (F7's
  read-the-field option changes motion and must be validated on a stage).
- `probe_four_readers.py` / `validate_readers_side_by_side.py` and the other
  `tests/hardware/` scripts that drive the instrument.
- Re-tuning any timeout/interval constant based on observed hardware behaviour.

---

## Suggested execution order

1. **Part A** (unblock) → run offline suites, confirm green.
2. **Part C** (docs) — zero-risk, immediately improves trust.
3. **Part D** (delete) — biggest line win; grep-verified, tests pin behaviour.
4. **Part E** (shrink) — the `confirmations.py` collapse (E1) is the headline.
5. **Part B** (correctness) — add the small unit tests as you fix.
6. **Parts F, G** (organization + CI) — lock in the gains.

Each part is committed separately on `claude/zmart-microscopy-review-p3zkce`, so
any single step is easy to review or revert.
