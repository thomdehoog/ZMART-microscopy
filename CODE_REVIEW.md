# ZMART Microscopy — Deep Code Review

**Scope:** the Leica Navigator Expert driver (`microscopes/drivers/vendor/leica/navigator_expert/`)
and the target-acquisition controller (`workflows/target_acquisition/`).
**Branch reviewed:** `main` (tip `ff8ad93`).
**Review priorities (as requested):** correctness bugs first, then drift
(docs/comments vs. code), consistency, simplicity over bloat, and production
readiness. The stated goal is code that is professional, consistent, intuitive,
and *a pleasure to read*.

---

## 1. Executive summary

The engineering underneath is genuinely strong. The dispatch → confirm → fire
backbone, the three-family state-reader trust model, the persistence and
failure-isolation contracts in the workflow, and the test suites are all
unusually careful for lab-automation code. Most subtle decisions are documented
and pinned by tests.

Three systemic problems stand between this and "production-ready and a pleasure
to read":

1. **`main` does not work on a fresh checkout.** The notebook entry point and
   the entire workflow test suite import nothing (a half-applied directory
   rename), and two "offline" driver tests fail (a gitignored artifact and an
   undeclared dependency). No CI appears to catch this.
2. **Documentation and comments are drifting faster than the code.** The
   README's headline `acquire` example *crashes*; step numbers disagree between
   docstrings and console output; many module docstrings still name modules that
   were renamed away. For a codebase that leans this hard on narrative prose,
   drift is corrosive — the comments can no longer be trusted.
3. **Substantial dead / speculative surface.** Most of `experimental/lrp_edits`,
   the whole `change_wait` subsystem, `correct_fn`, the OME filename-rewriters,
   and several unused `api_reader` helpers — exactly the bloat that works
   against the requested simplicity.

Nothing here is unrecoverable, and much of the fix is *subtraction*.

### Verification method

- Read every file in both areas in full (via eight parallel review passes).
- Ran the offline test suites directly after installing the (undeclared)
  scientific dependencies: `pytest numpy tifffile matplotlib scipy
  scikit-image pandas opencv-python-headless ipython ome_types`.
- `ruff check` over the whole repo: **passes clean** (the lint baseline is real).
- Independently re-verified every Blocker and every Correctness finding below by
  reading the exact lines and, where possible, executing.

### Test results observed

| Suite | Result |
|---|---|
| `drivers/.../tests/unit` + `tests/hardware` | 484 passed, 1 skipped, 62 subtests — **2 failed** (see B2) |
| `workflows/target_acquisition/tests` | fails to collect as shipped (B1); **344 passed, 2 skipped** once the import path is corrected |
| `calibration/.../tests` + `shared/output_layout/tests` | pass once path + deps are supplied |
| `ruff check .` | clean |

The 2 driver failures and the workflow-collection failure are environmental /
drift, not logic — the code itself passes once the checkout is made runnable.

---

## 2. Blockers — repo doesn't work as shipped

### B1 — `driver` → `drivers` rename half-applied (CRITICAL)

Commit `95349dc` ("Clean repository layout and lint baseline") renamed
`microscopes/driver/` → `microscopes/drivers/` but updated only the **comments**,
not the code, in four bootstrap/conftest files. Each computes the driver path as
`… / "driver" / "vendor" / "leica"` (singular), which no longer exists.

Affected:
- `workflows/target_acquisition/_bootstrap.py:18`
- `workflows/target_acquisition/tests/conftest.py:9`
- `microscopes/calibration/vendor/leica/navigator_expert/notebooks/_bootstrap.py:6`
- `microscopes/calibration/vendor/leica/navigator_expert/tests/conftest.py:10`

Consequences:
- `pytest workflows/target_acquisition/tests` fails at conftest collection with
  `ModuleNotFoundError: No module named 'navigator_expert'`.
- Notebook cell 1 (`from _bootstrap import Config, Path`) cannot run — the
  documented operator entry point is dead.
- The README instruction to run the workflow tests is false.

Confirmed: with the path corrected, all 344 workflow + calibration tests pass.
Note the same file (`tests/conftest.py:7`) still carries a `smart-microscopy/`
comment while the repo is `ZMART-microscopy`.

**Fix:** change `"driver"` → `"drivers"` in the four files. One word each.

### B2 — Two "offline" driver unit tests fail on a clean checkout (MAJOR)

The README promises the unit + hardware suites run with no microscope and no
LAS X. Two do not:

- `tests/unit/test_stage_config.py:80` —
  `assert current_limits.exists()` for
  `microscopes/limits/vendor/leica/navigator_expert/current.json`, but that file
  is a **runtime artifact** written by the workflow and is `.gitignore`d
  (line 19). Only `defaults.json` is committed, so the assertion can never hold
  on a fresh clone.
- `tests/unit/test_acquisition.py::TestSave::test_canonical_output_is_valid_under_ome_types`
  hard-imports `ome_types`, which is declared nowhere.

Also undeclared but needed by the suites: `tifffile`, `scipy`,
`scikit-image`, `opencv`, `IPython`, `pandas`, `numpy`, `matplotlib`.
`pyproject.toml` currently declares **no dependencies at all** (it only carries
`ruff` config).

**Fix:** make the path test tolerant of the ungenerated artifact (assert the
*computed path*, not existence), guard the `ome_types` test with
`pytest.importorskip`, and add a real dependency list (or a `[project.optional-
dependencies]` test extra) to `pyproject.toml`.

---

## 3. Correctness bugs

### C1 — `confirm_acquire`: a transient read failure is treated as "scan started" (MAJOR)

`commands/confirmations.py:1390-1404`.

```python
status = (
    _reading_value_after(_readers.get_scan_status(client, mode="api", ...), observed_after)
    or "Unknown"
)
...
if "Idle" not in status:
    saw_scanning = True
```

Any errored/stale/`None` scan-status read collapses to `"Unknown"`, and because
`"Idle" not in "Unknown"`, `saw_scanning` latches `True`. That permanently
disables the Phase-1 start-timeout and permanent-error checks; two later `Idle`
reads then satisfy `consecutive_idle >= 2 and saw_scanning` and the function
returns `{"success": True}` — reporting a completed acquisition that may never
have happened. This contradicts the fail-closed doctrine the sibling
`check_idle` documents ("Unknown is not idle", `prechecks.py:52-54`).

**Fix:** treat `Unknown` as evidence of nothing — do not let it set
`saw_scanning`.

### C2 — `require_canonical_scan_orientation` fails open (MAJOR)

`runtime/session.py:108-113`. The docstring promises it raises when export is
not `TOPLEFT`, and its purpose is to stop coordinate math that "silently
misnavigates."

```python
settings = _readers.get_lasx_settings() or {}
orient = settings.get("image_orientation", {}) or {}
if orient.get("enable_transform", False) and orient.get("transformation", "TOPLEFT") != "TOPLEFT":
    raise RuntimeError(...)
```

`get_lasx_settings()` returns `None` (only a `log.warning`) when the settings
file is missing/unreadable (`state_readers/api_reader.py:404-407`). Then
`settings = {}`, `enable_transform` defaults to `False`, and the check passes.
A wrong APPDATA path or a LAS X version change turns the safety gate into a
silent no-op — the opposite of what the docstring guarantees.

**Fix:** raise (or hard-fail) when the settings/orientation section could not be
read at all, distinct from "read and confirmed TOPLEFT".

### C3 — `base_fov_from_settings` silently clamps zoom < 1 to 1 (MAJOR)

`state_readers/derived.py:44-46`.

```python
current_zoom = float(zoom_info.get("current", 1) or 1)
if current_zoom < 1:
    current_zoom = 1
```

On hardware whose zoom range starts below 1 — the repo's own mock declares
`"zoom": (0.75, 48.0)` (`tests/helpers/mock_lasx_api.py:139`) — the zoom-1 FOV is
overstated by up to ~33 %. This value feeds `pan_scale_um_from_base_fov` in
`commands/commands.py` (`move_galvo_to_pixel`), so galvo pan targeting is
mis-scaled at zoom 0.75, with no comment explaining the clamp and no warning.

**Fix:** remove the clamp, or document precisely why sub-1 zoom is impossible on
supported hardware and warn instead of silently rewriting the value.

### C4 — LRP attribute editing can corrupt a neighbouring attribute (MAJOR, latent)

`experimental/lrp_edits/_primitives.py:54-73` (`_set_job_attr`; same pattern in
`_set_sequential_attr`, 154-160).

```python
pattern = re.compile(rf'{attr_name}="([^"]*)"')      # unanchored
...
element_text.replace(m.group(0), replacement)         # unbounded
```

The regex is unanchored, so `Zoom` also matches inside `BaseZoom`; and
`str.replace` rewrites *every* occurrence. In the shipped fixture LRP
(`tests/data/general_workflow/{ScanningTemplate}test_hardware_workflow.lrp`) the
same tag carries both `Zoom="1"` and `BaseZoom="0.75"`. If those two ever share a
value, editing `Zoom` silently rewrites `BaseZoom` too; if a suffixed attribute
precedes the plain one, the wrong attribute is edited outright. This writes
machine-control files. Latent only because these helpers are almost entirely
unused (see §5), but a real hazard the moment they are.

**Fix:** anchor with a boundary (e.g. `(?<![\w])`) and splice by match position
instead of `str.replace`.

### C5 — `load_overview_result` crashes on the recovery path it exists for (MAJOR)

`pipeline/selection.py:203-207`.

```python
n_tiles_acquired = int(meta["n_tiles_acquired"])
n_tiles_hijacked = int(meta["n_tiles_hijacked"])
simulated = bool(meta["simulated"])
except (json.JSONDecodeError, OSError) as exc:
```

Three strict `meta[...]` reads, but only `JSONDecodeError`/`OSError` are caught.
A meta file from a run that predates these counters raises `KeyError` — exactly
the kernel-restart / reload recovery scenario this function exists for — and the
docstring promises "missing/corrupt meta is tolerated with a warning and
completed=False." The writer even stamps `schema_version` (`overview.py`) but the
loader never checks it.

**Fix:** use `.get(...)` with defaults (as the adjacent keys already do) and/or
add `KeyError` to the except tuple; honor `schema_version`.

### C6 — `move_xy` returns the target as `"position"`, not a readback (MAJOR)

`commands/commands.py:1071-1072` (docstring) vs. `1134-1135` (code). The
docstring says the result's `"position"` is the "final XY readback"; the code
stores the echoed **target** (`# Target position (not a readback ...)`). With
`MOVE_XY.success_on_unconfirmed=True` (`profiles.py:420`), a caller can get
`success=True` plus a `position` the stage never reached. The genuine readback
(`last_position` from `confirm_move_xy`) is discarded on success.

**Fix:** return the confirmed readback when available; only fall back to the
target (clearly labelled) on the unconfirmed path.

### Lower-severity correctness items

- `pipeline/summary.py:75` — `"timestamp": ctx.out_dir.name` writes a run-name
  string (`<experiment>_<hash6>`), not a timestamp; any consumer parsing it as
  time gets garbage.
- `pipeline/target.py:245-273` — `failure_stage` telemetry labels `drv.save`
  failures as `"acquire"`; the `"save"` stage is unreachable as a failure; the
  docstring names a nonexistent `"zoom"` stage.
- `pipeline/_mock_provider.py:79-80` — when tile size ≥ the 512×512 source
  (common LAS X formats), every overview tile gets identical mock content,
  contradicting "each tile gets distinct content." Simulation-only; unpinned
  because tests use 128×128.
- `commands/dispatch.py` + `settings.py` (commit `ff8ad93` area) — the
  error-check step now runs a full readback that can `raise ValueError` on a
  schema mismatch, but steps 1 (pre-check) and 4 (error-check) are unguarded, so
  `set_scan_resonant` can raise instead of returning the result dict every other
  command guarantees.
- `runtime/errors.py:129-159` — `echo.HasError`/`echo.Error` are read unguarded,
  including *inside* the except branch that exists because the COM object was
  unreadable; one flaky interop read propagates through the backbone.
- Runtime invariants guarded by bare `assert` (`pipeline/overview.py:429`) vanish
  under `python -O` and, when they fire, lose an otherwise-persisted session with
  a non-diagnosable error.

---

## 4. Drift — docs / comments vs. code (the dominant readability tax)

### D1 — README's headline `acquire` examples crash (MAJOR)

The exported `navigator_expert.acquire` is `acquisition.capture.acquire`
(`__init__.py:422`), which returns a **frozen `AcquisitionResult` dataclass** and
**raises** `RuntimeError` on failure (`capture.py:57-58`). But the root README
shows:

- Quick Start: `result['timing']['total_s']` → `TypeError: 'AcquisitionResult'
  object is not subscriptable`.
- Basic Workflow: `if result["success"]: ... else: print(result['message'])` —
  not subscriptable, and the failure branch is unreachable because failure
  raises.
- The "Result Dictionary — every command returns a result dict" section is
  untrue for the exported `acquire`; it describes `commands.acquire`, which is
  not exported.

### D2 — README read-only function table is stale across the board (MINOR)

- `ping` documented as `(client, timeout=5)`; actual `(client)`
  (`router.py:295`).
- `get_jobs`/`get_job_settings`/`get_hardware_info`/`get_xy` documented
  `timeout=15, poll_interval=0.05`; actual defaults `timeout=1.0,
  poll_interval=0.01`.
- `get_scan_status` example value `"eIdle"` does not exist; the codebase uses
  `"eScanIdle"` everywhere.
- The dependency DAG (README:476) lists imports `dispatch` doesn't have and omits
  `runtime.session` / `runtime.lasx_runtime`.

### D3 — Step numbering is inconsistent three ways (MAJOR)

The workflow README, the docstrings, and the operator-visible `[step N]` console
prints disagree.

- `overview.py` docstring "Step 4" vs. every print `[step 3]`.
- `focus.py` docstring "Step 3" vs. prints `[step 2c]`.
- `preflight.py` docstrings "Step 0: prepare the world" vs. print `[step 1]`.
- `pipeline/__init__.py:5-7` says "the six numbered step functions" then lists
  seven.

A reader cross-referencing console output against the code gets two different
maps of the workflow.

### D4 — `RECEIPT_TIMEOUT` "tuning knob" cannot work as documented (MAJOR)

`runtime/utils.py:16-18` says "Import and override these to tune for your
hardware." But every consumer binds the value at import via
`from ..runtime.utils import RECEIPT_TIMEOUT`, and importing any part of the
package runs those imports immediately. Rebinding `utils.RECEIPT_TIMEOUT`
afterward affects nothing. The real mechanism is per-profile
`receipt_timeout` / `confirm_timeout`.

### D5 — `pre_check_timeout` is a silent no-op on ~19 setting wrappers (MAJOR)

`commands/dispatch.py:191` applies the override only when
`profile.pre_check_fn is not None`, but `_leica_setting_profile`
(`profiles.py:262-277`) never sets a pre-check. So `set_zoom(...,
pre_check_timeout=30)` does nothing, contradicting every setting wrapper's
docstring ("Idle-wait timeout … None = profile default").

Compounding, in the same family:
- `select_job` docstring says "No pre_check_fn (job switching doesn't need
  scanner idle)"; reality is `SELECT_JOB = CommandProfile(pre_check_fn=
  partial(check_idle, timeout=None), ...)` — it blocks **indefinitely** for
  idle, and `test_idle_prechecks.py` enforces exactly that.
- `select_job` is the one idle-guarded command that does **not** expose
  `pre_check_timeout`, so its unbounded wait cannot be bounded.

### D6 — Module docstrings name modules that were renamed away (MINOR, pervasive)

From the `templates`→`scanfields`, `positions`→`scanfields.parsers`,
`driver`→`drivers` eras:

- `_file_utils.py:7` — "Imported by: templates and acquisition.files"
  (`templates` gone).
- `state_readers/api_reader.py:27-32` — claims `prechecks`/`confirmations`/
  `commands`/`__init__` import it directly; they import the routed package.
- `scanfields/roi.py:90` — "Imports: positions.parsers".
- `experimental/lrp_edits/z.py:9` — "templates.transaction.apply_lrp_change".
- `scanfields/files.py:7-8` — claims it imports `_file_utils`; it doesn't.
- `pipeline/_hijack.py:198-201` — cites `driver/acquisition/save.py`'s
  `_save_atomic(image, xml)`, which does not exist (logic lives in
  `materialize.py`).
- `pipeline/_geom.py:8` — "Two functions live here"; there are three
  (`visible_target_fov_window` was added without updating the header).
- Several test-file docstrings name their own pre-rename filenames
  (`test_scanfield_parsers.py:5` → `test_position_parsers.py`).

Individually trivial; collectively they mean the prose can no longer be trusted.

### Other drift

- `select_job` annotation is a hand-rolled `{"level", "msg"}` dict missing the
  `"ts"` field every other log entry carries via `_make_log_entry`.
- Every dispatch result stamps `method="async"`, including synchronous
  `UpdateAwaitReceipt` commands — stale and meaningless.
- `save_and_read_lrp` (`scanfields/files.py:254-281`) docstring says it returns
  `None` on failure; it logs a warning and returns the possibly-stale parse
  anyway, and confirms on the XML while reading the LRP (a known stale-read
  race the sibling `apply_lrp_change` deliberately avoids).
- `roi.py` documents the same `Rotation` attribute as degrees in one place and
  radians in another; `make_polygon` claims to "validate the input format" but
  its body is `return list(vertices)`.

---

## 5. Overengineering / dead code (subtraction opportunities)

- **`experimental/lrp_edits/` is ~95 % unused.** ~1900 lines are re-exported
  through the public driver facade (`__init__.py:438-535`), but only
  `lrp_set_pan`, `lrp_get_pan`, and `galvo_pan_for_pixel` have any consumer
  (`move_galvo_to_pixel` + its test). All of `general.py`, `focus.py`, `z.py`,
  and nearly all of `roi.py` are uncalled. `roi.py` additionally ships **two
  contradictory implementations** of the same pixel→ROI conversion (one negates
  X, one doesn't — `pixels_to_roi` vs. `mask_contour_to_roi`), a 92-line
  docstring, and comments citing an "issue 1…10" list and a `feedback_*.md` file
  that are not in the repo. And the package is labelled `experimental` while a
  production command depends on it.

- **`state_readers/change_wait.py` (380 lines) + the evidence-leg half of
  `capabilities.py` have no production caller** — only the hardware probe
  `tests/hardware/probe_four_readers.py`. `capabilities.py:11-13` claims the
  evidence legs serve "the confirmation race," but the real confirmation race
  (`commands/confirmations.py`) never imports either module. ~1100 lines
  (module + its test) carried for a diagnostic tool; the docstring claim is
  false.

- **`confirmations.py` is ~900 lines of copy-pasted poll loops.** The 23
  `_confirm_*` functions repeat an identical ~40-line skeleton (default timeout,
  `logs=[]`, deadline, `while`, `_readback`, try/except extraction, compare,
  sleep, timeout warning) differing only in one extraction expression and one
  label — e.g. `_confirm_frame_accumulation` / `_confirm_frame_average` /
  `_confirm_line_accumulation` / `_confirm_line_average` differ in one dict key.
  A single parametrized `_poll_confirm(client, job, extract_fn, matches_fn,
  label, ...)` (not a closure factory — the thing the module rightly avoids)
  would cut the file to roughly a third and make each command's intent legible.
  This is the largest single readability tax in the driver.

- **`acquisition/ome.py:470-635`** — ~165 lines of filename-rewrite code
  (`update_ome_tiff_filename`, `update_ome_xml_filename`, helpers, two regexes),
  still in `__all__`, with zero callers; the save path generates canonical OME
  from scratch. `ome.py` is also the one untyped, banner-commented module bolted
  onto an otherwise fully-typed package; renaming it (e.g. `ome_vendor_fix.py`)
  would also clarify the confusing two-modules-named-"ome" split
  (`ome.py` fixes vendor output; `ome_canonical.py` emits canonical output).

- **Smaller speculative hooks / duplication:**
  - `correct_fn` — plumbed through `CommandProfile`, `_dispatch`, and
    `confirm_and_fire` (with its own try/except and timing), "stubbed for future
    use," set by no profile.
  - `_readback`'s `observed_after` parameter and its timestamp-gate branch are
    dead (all 23 call sites pass two args).
  - `ACQUIRE` and `ACQUIRE_SINGLE_IMAGE` are field-for-field identical profiles.
  - `PAN_LIMIT = 0.00775` (documented single source in `utils.py`) is duplicated
    as a private `_PAN_LIMIT` in `commands.py`.
  - `read_zwide_um` exists in three drifting copies (`api_reader`, `log_reader`,
    `router`); the `api_reader` convenience readers `get_fov`, `get_base_fov`,
    `get_job_by_name` have no callers.
  - `UNASSIGNED_JOB = "(unassigned)"` defined twice (`parsers.py:65`,
    `planning.py:17`).
  - `pipeline/visualize.py` — a `_ScatterLayer` + `_LAYERS` registry sells
    extensibility for two entries, while `test_polish.py` pins `len(_LAYERS)==2`
    and forbids adding a third; the cellpose-bbox fallback-window math is
    duplicated within the file (reintroducing the exact drift class `_geom.py`
    was created to kill); live vs. batch target renderers are near-duplicates
    with inconsistent font sizes.

---

## 6. Consistency / professionalism (smaller)

- `stage/__init__.py` is an empty 0-byte file while `state_readers/__init__.py`
  documents and re-exports; the driver root reaches across the `_`-private
  boundary (`__init__.py`: `from .stage.limits import _check_xy_limits, ...`),
  undercutting its own convention.
- `pipeline/_acquire.py`'s `acquire()` **does not acquire** ("Does not trigger a
  frame") yet sits two lines from `drv.acquire()` which does; the docstring's
  first job is to disclaim its own name. `position_stage` would erase the
  confusion.
- `WorkflowRun` is a one-field frozen wrapper around `LayoutPlan`, and
  `Context.out_dir` duplicates `run.layout.run_dir` — two redundant layers over
  one object.
- `state_readers/log_reader.parse_log` re-reads and regex-scans the **entire**
  growing log file on every call (`f.readlines()`), at ~10 Hz during waits — no
  tailing/offset; a missing/unreadable log is swallowed with no message, so a
  misconfigured path makes log/hybrid modes silently empty.
- `pipeline/preflight.py:288-299` reaches into raw LAS X .NET attributes
  (`client.PyApiClient.DelayInMilliseconds`) and overrides the API delay the
  driver's `connect_python_client` just set — two competing sources of truth,
  the workflow's hardcoded `300` always winning, bypassing the driver's
  `configure_lasx_api_delay` helper.
- `pipeline/_job_state.py:40-47` detects "readback unconfirmed" by substring-
  matching the driver's human-readable message plus a timing heuristic; a wording
  change in `dispatch.py:705` silently flips behaviour.
- Font sizes, focus-marker geometry, and hex colors are hand-duplicated across
  `template.py`, `focus.py`, and `visualize.py`, bypassing the "single source of
  truth" style tokens that only `visualize.py` enforces.
- `stage/config.py`: the calibration schema **requires** a `backlash.approach`
  field that no code reads (`movement.py` hardcodes the −X−Y / +X+Y sequence);
  `move_xy_with_backlash` has no `tolerance_um` parameter, so the calibrated
  `tolerance_um` is unusable on the one primitive production calls;
  `CALIBRATION_SCHEMA_VERSION = 11` duplicates `SCHEMA_VERSION = 11` in
  `calibration/core/model.py` with no cross-reference (must be bumped in
  lockstep by hand).

---

## 7. What the code gets right (so it isn't lost in fixes)

- The **three reader families** (`api` / `log` / `hybrid`, hybrid default,
  first-admissible-evidence for command confirmation) match the code exactly.
  Caveat: *passive* hybrid reads are **not** first-wins (there's a ~0.25 s
  log-rescue grace, `router._log_rescue_concurrent`), so keep that qualifier out
  of any broadened claim.
- The **dispatch backbone** (`dispatch.py`) and the profile/wrapper/confirmation
  layering are clean; the confirmation-race and select-job admissibility logic
  are unusually well reasoned and precisely tested (`test_select_job_confirm.py`,
  `test_confirmation_race.py` match the code exactly). The race/hybrid complexity
  is *earned* — it encodes measured hardware pathologies with dated evidence.
- The **scanfields** package (files/parsers/planning/strip_restore/transaction)
  is well-partitioned, honestly documented, and backed by real-fixture
  round-trip tests; `parsers.py`'s 1582 lines are mostly earned (three file
  formats + a careful fallback-derivation chain).
- The workflow's **persistence and failure-isolation** contracts (overview
  same-kernel invariant, per-pick failure isolation, the `_hijack` simulator
  allowlist with a dedicated exception type and byte-equality assertions, the
  `_geom` no-drift design) are model-quality and test-pinned.
- The **physics documentation** in `runtime/utils.py` is exemplary.
- `ome.py` and `ome_canonical.py` do **not** duplicate each other — clean
  one-directional dependency (canonical reuses vendor's raw tag reader); both are
  needed. The only weakness is the shared "ome" name.

---

## 8. Recommended order of work

1. **Make the checkout runnable (B1, B2).** Fix the four `driver`→`drivers`
   paths; make `test_stage_config` assert the computed path rather than
   existence; guard the `ome_types` test with `importorskip`; add a dependency
   list to `pyproject.toml`. Low-risk, mechanical, unblocks everything.
2. **Fix the fail-open / false-success bugs:** `confirm_acquire` Unknown handling
   (C1), `require_canonical_scan_orientation` (C2), the `base_fov` zoom clamp
   (C3). These are the items that can silently mislead a real experiment.
3. **Reconcile the docs with the code:** the README `acquire` examples and
   read-only signature table (D1, D2), and unify step numbering across README /
   docstrings / console prints (D3).
4. **Subtract:** remove or demote the dead `experimental/lrp_edits` surface (and
   harden `_set_job_attr`, C4, for the three helpers you keep); drop the
   `change_wait` / `capabilities` evidence legs; delete the `ome.py`
   filename-rewriters and `correct_fn`; collapse the 23 `_confirm_*` clones into
   one helper.
5. **Polish:** rename `_acquire.acquire` → `position_stage`; flatten
   `WorkflowRun`/`out_dir`; add log-file tailing; fix the remaining
   lower-severity correctness items (§3 tail).

Steps 1–2 are the difference between "impressive but broken on arrival" and
"trustworthy in production." Steps 3–5 are what turn it into a pleasure to read.

---

*Prepared as a read-only review; no source files were modified.*
