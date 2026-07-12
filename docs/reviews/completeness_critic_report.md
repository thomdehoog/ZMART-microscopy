# Completeness critic — what the three reviews and the applied fixes missed

Written 2026-07-12 on branch `claude/review-workflows-controller-leica-yd625w`, after
reading the three review reports, the full applied diff
(`origin/claude/forfable4-document-11mxsx..HEAD`), and re-running every offline suite.
Note on timing: while this audit ran, another session was actively removing the
retired-only Leica symbols (uncommitted edits to `model.py`, `gate.py`, `objectives.py`,
`stage_config.py`, `strip_restore.py`, `parsers.py` and their tests, −703 lines at last
look). All Leica statements below are a snapshot; where an item is being handled by that
in-flight work I say so.

## Verdict

The applied work is high quality and almost every SAFE finding landed cleanly: the tree
imports, both adapters register, ruff is clean, and every offline suite passes —
including the notebook/webapp integration tests that the workflows review flagged as a
blind spot (both v4 notebooks now execute end to end under pytest in this environment).
Two things were genuinely missed. First, **the acquire-record "fix" does not actually
work for the real mesoSPIM adapter** — both reviews misread the mesoSPIM record shape
(`planes` is an integer count there, not a manifest), so the applied fix, its new test,
and the new README contract all describe a driver that does not exist, and the real
record now fails with a worse error than before. Second, **`shared/` (813 lines that all
three reviewed areas depend on) was covered by no report**. Everything else found is
small: two doc drifts the fixes themselves introduced, a short list of SAFE items that
were not applied, and stale statements in the review reports and `docs/`.

## 1. Coverage gaps

**G1 — The mesoSPIM acquire record was never actually read, and the new cross-driver
contract contradicts it.** Both reports claim the mesoSPIM adapter returns
`image_files` plus a `planes` *manifest* (workflows review §2 caveat 1 and §4.1:
"a perfectly good `planes` manifest is present"; controller review F1). In reality
`zmart_drivers/mesospim/mesospim_zmart_adapter.py:544` sets `"planes": result.planes`
where `planes` is an **int** (`zmart_drivers/mesospim/acquisition/product.py:66` —
number of z planes), and there is no per-plane path manifest at all. Consequences are
listed under R1 below. Related inconsistency: the controller README's new convention
text (`zmart_controller/README.md:150-153`) says a driver that saves files *must*
provide `images` and *may* provide indexed `planes` entries with a `path` — the shipped
mesoSPIM adapter violates the first and collides with the second (same key, different
meaning). Aligning the mesoSPIM adapter (rename `image_files` → `images`, emit a real
manifest or a differently named count) is the one-decision fix; it was marked JUDGMENT
in the controller review and remains open.

**G2 — `shared/` was in the blast radius of all three reviews and none covered it.**
It is load-bearing for every reviewed area: the Leica gate imports `shared.limits`
(`commands/gate.py:84`), Leica calibration and orientation import `shared.algorithms`
(`calibration/core/objective_pair.py:51`, `orientation/measure.py:38`), the workflow's
calibration check imports `register_voting`
(`workflows/target_acquisition/workflow/_calibration_check.py:316`), and the mesoSPIM
adapter imports `shared.limits` too. That is 813 lines
(`shared/algorithms/registration.py` 440, `shared/limits/spec.py` 311,
`shared/algorithms/focus.py` 62) with no simplification/bug review this round. Its own
test suite passes (30 tests), so this is a coverage note, not an alarm.

**G3 — `docs/ZMART.md` is now flatly wrong about the workflow.** Line 64 area:
"Workflows do not yet run through it (they use the Leica driver directly)." The v4
workflow is controller-only, and the driver-coupled generation was just deleted from
the tree. One sentence to update. No report covered `docs/` outside `docs/reviews/`.

**G4 — The Zeiss zenapi driver is a fork of the pre-cleanup Leica commands
architecture.** It still carries the exact sediment just deleted from Leica —
`retry_backoff`/`retry_escalate` threaded through
`zmart_drivers/zeiss/zenapi/commands/dispatch.py:59-60`, `profiles.py:95-96`, and
`commands.py:92-93`. Zeiss was outside the stated scope, but sibling drift is now
guaranteed; worth a line in a future round.

**G5 — The controller's two example notebooks are executed by no test.** The workflows
suite executes both v4 notebooks, but nothing executes
`zmart_controller/example_experiment.ipynb` / `example_leica_experiment.ipynb`; the
controller review verified them by reading only. After the mock-record change (it now
returns `images`) their stored outputs are also slightly stale. Low priority.

**Checked and found adequately covered or clean** (details in §5): `getting_started/`,
`build_env.py`, the top-level `README.md`, the mesoSPIM adapter's own suite, and the
CI workflow files (which do install `nbformat`/`anywidget`/`nbclient` via the Leica
`requirements-dev.txt`, so the integration tests run in CI as intended — though nothing
*fails* CI if they ever skip again, and `playwright` is not installed there, so the
browser test always skips).

## 2. Regressions introduced by the fixes

**R1 — The record-drift fix claims to handle mesoSPIM records but crashes on the real
one, with a worse error than before.**
`workflows/target_acquisition/workflow/_output.py:119-120` (new docstring: "works for
any driver's record shape (a plain ``images`` list, a mesospim-style ``planes``
manifest, and so on)") and the new test
`workflows/target_acquisition/tests/test_output.py:54`
(`test_move_organizes_a_record_without_an_images_key`) both model a mesoSPIM record as
`{"image_files": [...], "planes": [{"t":0,"z":0,"c":0,"path":...}]}`. The real adapter
produces `{"image_files": [...], "planes": <int>}` (G1). Repro:

```python
from workflow._records import record_channel_paths
record_channel_paths({"planes": 1, "image_files": ["/tmp/a.tiff"]},
                     context="acquire record")
# TypeError: 'int' object is not iterable   (planes=1 is truthy, then iterated)
```

Since `move_record_images` now routes through `record_channel_paths`
(`_output.py:126-128`), a genuine mesoSPIM record fails with that opaque `TypeError`
where it previously failed with the clear `RuntimeError("acquire returned no image
paths to organize")`. The workflow is still Leica-only in practice, so nothing live
breaks today — but the fix's own claim ("no longer silently Leica-only") is false, and
the new test pins a fictional record shape. Fix direction: teach
`record_channel_paths` to treat a non-list `planes` as absent and to read
`image_files`, or (better, per G1) align the mesoSPIM adapter with the stated
convention — then correct the test and the two docstrings either way.

**R2 — `viz.py` docstring drifted when the mock was fixed.**
`workflows/target_acquisition/workflow/viz.py:6-7` still says "the mock returns
``{"filename": ..., "position": {...}}``", but the controller fix added an `images`
list to the mock record (`zmart_controller/tests/mock_driver.py:204-211`). One-line
doc fix.

**No other regressions found.** The dangling-reference sweep for every deleted name
came back clean (§5), the acquire-reordering in the Leica adapter (`Naming` built
before the scan fires, options validated before output-root discovery) is
behavior-improving and covered by the updated adapter tests, and the router's new
error-carrying timeout `Reading` is consistent with its documented contract.

## 3. SAFE-marked findings not applied

Controller review: **everything SAFE was applied** (mock `images`, key-order test,
misfiled tests, `resolve()` tuple, prose fossils, dead guard, conftest reset, README
drift items, both registry probe guards, the underscore delegation guard). Still open
as flagged-not-fixed decisions: the mock's `run_procedure` `"ran"` shape drift
(§4 bug 3; mock still returns a dict, `mock_driver.py:269-270`, mesoSPIM a string) and
the shallow-copy docstring caveat (§4 bug 4). F7/F8/F9 are JUDGMENT and untouched, as
expected.

Workflows review: §3.1, §3.4, §4.1, and the UI-constant consolidation all landed.
Partially applied: §3.2 — `anywidget` was added to the root `requirements-dev.txt` and
the tests run here and in CI, but there is no "fail CI if these skip" gate, and the
comment claiming `nbclient` executes the notebooks is slightly off (the end-to-end test
needs only `nbformat`; it passed here with `nbclient` absent). The §7 README caveat
about the record contract was not added and is now half-moot — except that R1 shows the
caveat is still true for mesoSPIM.

Leica review — not applied at snapshot time (and not part of the in-flight
retired-symbol work as of this writing):

- **Facade re-exports privates** (Wiring §3, SAFE ~15 lines):
  `navigator_expert/__init__.py:144,151,171,208` still export `_safe_float`,
  `_check_api_error`, `_readback`, `_stage_limits`; `tests/unit/test_core_driver.py`
  still calls `drv._check_api_error` (line 173).
- **`load_translations`** (§2 row 11, SAFE ~14 lines): still at
  `calibration/core/model.py:229` with zero callers (its `translate_*` siblings are
  being removed by the in-flight edits, so this may follow).
- **The phantom-defense comment** (Wiring §3 blemish, "fix the comment or drop the
  call"): `commands/commands.py:1335-1341` still claims "the machine file may
  constrain the absolute pan further", which the gate cannot do.
- **F6's two "free" register fixes**: the test-accommodation branch in production
  (`commands/confirmations.py:253`) and gate.py's fallback story told three times.
- **F1's side note**: `BENCH_EVAL_2026-07-07.md` was deleted with `tests/_report/`
  rather than moved to `docs/` — fine if intended (git remembers), noted so it is a
  decision rather than an accident.

Leica JUDGMENT items open by design (no action expected without the named decision):
`probe_four_readers` + its `run_ci.py:258` step, `experimental/lrp_edits` (maintainer
says untouched), F5 confirm-wrapper dedupe, F7 `objective_pair` ceremony, the F8
sidecar remainder (`ome.check_ome_xml_file`/`fix_ome_xml_file`, `PositionIndex`,
`xml_paths`), F9's `migrate_legacy_snapshots` (still present and still unwired — the
"a migration that never runs silently ignores real legacy snapshots" concern stands),
F10 reader housekeeping, F14 tunables (deferred to the profiles decision), and bugs
3, 4, 6, 7 (only bugs 1, 2, 5 were approved and fixed — verified in the diff).

## 4. Stale statements in the reports and docs after the deletions

- `docs/reviews/controller_simplification_review.md:15` still says
  `workflow/retired/` (~8,000 lines) is "still on the tree"; it is deleted. (Also its
  size figure disagreed with the workflows review's 12,766 — moot now.)
- The workflows review's mesoSPIM claims (§2 caveat 1, §4.1 including the "confirmed
  by probe" sentence) are factually wrong about the record shape (G1/R1); a correcting
  note in that report would stop the error propagating into a future round.
- The Leica review's §2 row 4 premise ("alive only because retired/ imports it") is
  now resolved by the retired deletion; the in-flight working-tree edits are executing
  exactly that row, correctly including call-site edits (for example
  `parse_rgn_tile_colors`' live call inside `parse_scan_positions`, which a bare
  symbol deletion would have broken).
- `docs/design/limits-enforcement-review.md:178` cites the deleted
  `workflows/target_acquisition/pipeline/preflight.py:124`; the file is a dated design
  review, so a one-line "historical; paths predate the 2026-07 deletion" header is
  enough.
- `docs/ZMART.md` — see G3.
- None of the three reports records what was applied; the commit messages do, but a
  short "applied on this branch / still open" annotation per report would save the
  next reviewer the reconciliation this report just did.

## 5. Checked and clean

- **Dangling references: none.** Repo-wide grep (py/md/ipynb/toml, excluding
  `docs/reviews/` history) for `hijack_frame`, `build_target_provider`,
  `visible_target_fov_window`, `_save_queue`, `_log_capture`, `_saved`, the
  `pipeline/` shim, `zmart_microscopy_v3.2`, `retired`, `pixels_dims`,
  `companion_xml` (the deleted `ome_canonical` pair; the surviving hits are the kept
  `ome.py` checker and its tests), `default_tolerance` (surviving hits read wrapper
  signature defaults, which is the new single source), `retry_backoff` (Leica-clean;
  Zeiss has its own copy, G4), tuple-unpacked `resolve()`, and
  `migrate_legacy_snapshots` (function + its test remain coherently paired) came back
  clean.
- **Both remaining operator notebooks execute.** `test_notebooks_run_end_to_end.py`
  and the v4/v4-react/webapp/react-widget suites ran here (116 passed), so the
  deletions did not strand the notebooks, and the review's headline coverage blind
  spot is closed in this environment and in CI.
- **Suites** (this container, offline): controller 37 passed; workflows 277 passed +
  4 environmental skips (playwright missing, skimage sample-data download blocked);
  Leica `tests/unit` + `calibration/tests` 1028 passed + 1 expected LAS X-runtime
  skip *with the in-flight retired-symbol edits in the tree* (an earlier run showed
  174 failures which disappeared on re-run — attributed to files being rewritten
  mid-collection by the concurrent session, not to code); mesoSPIM unit 130 passed;
  `shared/limits` 30 passed.
- **`ruff check`** clean over `zmart_controller`, `workflows/target_acquisition`,
  `zmart_drivers/leica`, `zmart_drivers/mesospim`, `shared` (including the in-flight
  edits).
- **Imports**: `zmart_controller`, `workflow`, `navigator_expert` (+ its
  `zmart_adapter`), `zmart_drivers.mesospim.mesospim_zmart_adapter`, and all three
  `shared` modules import; both real adapters register (`leica`, `mesospim`).
- **Docs verified accurate**: top-level `README.md` (layout, controller walkthrough,
  workflow pointer), `getting_started/README.md` (setup path, notebook paths,
  `run_ci.py` entry), `build_env.py` (its package manifest matches the current test
  deps), the controller README against the current code, and the applied
  `MAINTAINER_DECISIONS.md` §7b addendum against the shipped flat `limits.json`.
- **Fix-wave spot-checks that came back correct**: the registry's new
  string-identity and callable-ops guards, the module `__getattr__` underscore guard,
  the locale decimal-comma parser (both-marks and comma-only cases), the calibration
  NaN validation sweep, the router's error-carrying timeout `Reading`, the
  `_classified_error_result` dedupe, the `_phase_timing` helper, and the
  machine-config `resolve()` flattening including all call sites and tests.
