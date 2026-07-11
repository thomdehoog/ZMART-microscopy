# Target-acquisition workflow — deep simplification review

Scope: `workflows/target_acquisition/` on branch
`claude/review-workflows-controller-leica-yd625w`. No repo code was changed;
this document is the only file written. Adversarial probing was software-only
(offline, simulated stage). Line counts are from `wc -l`; the package holds
about 29,400 lines of Python across 103 files plus three notebooks.

---

## 1. Overview and overall health verdict

This package is in **good functional health and poor weight health**. The live
controller-only workflow — `steps.py`, `discovery.py`, `_capture_run.py`,
`_focus_*`, `_geom.py`, the four ipywidget review widgets, the React widget
stack, the stdlib webapp, and the simulation — is genuinely well-built. The
public surface is coherent, the wiring is real (I traced every seam, see §2),
the biologist-facing docstrings are among the best I have seen in this repo,
and 195 of the offline tests pass. Nothing in the *live* path is broken.

The problem is that the tree carries a **second, retired generation** in full:
the driver-coupled `workflow/retired/` flow (6,460 lines of code + 6,306 lines
of its own tests), the `zmart_microscopy_v3.2.ipynb` notebook that drives it,
the `pipeline/` compatibility shim that feeds it, three modules in the *live*
package (`_saved.py`, `_save_queue.py`, `_log_capture.py`) plus two live
functions (`_hijack.hijack_frame`, `_mock_provider.build_target_provider`) and
one geometry helper (`_geom.visible_target_fov_window`) that **nothing in the
live path imports** — they exist only to keep the retired flow and its tests
alive. Roughly **13,000–13,500 lines, about 45% of the package's Python, is the
retired generation and its life-support**, and it is invisible to the operator.

A second, smaller weight problem is stylistic: a handful of modules (`_hijack`,
`_geom`, `_mock_provider`) carry essay-length docstrings and comment blocks that
dwarf their code — the "AI slop" the maintainer asked me to name bluntly (§4,
§7).

Overall verdict: **healthy core, ship it — but the single highest-value action
in this package is deleting the retired generation wholesale, not refactoring
it.** Take the maintainer's principle literally here: the functionality the
operator uses survives completely if `retired/`, `v3.2`, `pipeline/`, and their
three orphaned support modules disappear.

---

## 2. Wiring verdict

**The live wiring is sound.** Traced end to end:

- **Notebook → steps → controller.** `zmart_microscopy_v4.ipynb` imports only
  `_bootstrap`, which puts driver + repo + package on `sys.path`, registers the
  Leica adapter, and exposes `workflow`. Every step the README lists resolves to
  a real function in `workflow/__init__.py`'s `__all__`, and each of those calls
  the `zmart_controller` `Session` ops (`set_state`, `set_xyz`, `acquire`,
  `run_procedure`, `get_info`, `get_state`, `set_origin`) — confirmed against
  `zmart_controller/layer.py`. No `navigator_expert` import leaks into the
  operator path; the driver is pulled in only by `_bootstrap` (to register) and
  lazily inside `_hijack` (the OME check).
- **Webapp → flow → same steps.** `workflow/webapp/_flow.py` `RunFlow` calls the
  *same* public functions (`connect`, `load_analysis_engine`, `run_overview`,
  `overview_inputs_from_records`, `discover_targets`, `write_run_report`) in the
  notebook's order, and builds the *same* React widgets via `workflow.react`.
  `_host.py`/`_server.py`/`_page.py` carry traits and messages over stdlib HTTP.
  Clean.
- **React widgets → protocol → notebook.** `workflow/react/_widgets.py` widgets
  subclass a common `_ZmartWidget`; `PROTOCOL.md` documents the traits/messages;
  `_flow`/`_host` speak that protocol. The image mathematics is genuinely shared
  with the matplotlib stack (`composite_channels`, `crop_for_target`,
  `pair_images`, `run_status_rows`, `_eta_text`, `record_channel_paths`,
  `read_overview_geometry`, `crop_overview_at_target_fov`).
- **No orphan modules in the live path**, and no calls to surfaces that do not
  exist (I grepped every helper module's importers across the whole repo).

**Two wiring caveats that matter:**

1. **Acquire-record key drift reaches into this workflow (real bug, §3.1).** The
   workflow reads driver acquire results three ways, and they disagree on how
   forgiving they are. `_records.record_channel_paths` correctly prefers the
   `planes` manifest and falls back to a single `images` path. But
   `_output.move_record_images` (called on every capture when an `output_root`
   is set) and `_hijack.hijack_records` read **only** `record["images"]`. The
   Leica adapter returns both `images` and `planes`, so the live Leica run is
   fine — but the mesospim adapter returns `image_files` + `planes` (no
   `images`), and the controller's own mock driver returns only `filename`.
   I confirmed by probe that `move_record_images` raises "acquire returned no
   image paths to organize" on a mesospim-shaped record even though a perfectly
   good `planes` manifest is present. The workflow is silently Leica-only at the
   capture/organize boundary while advertising driver-agnosticism.

2. **The tests that would prove notebook wiring are skipped in CI-like
   environments.** `test_notebooks_run_end_to_end.py`, `test_v4_notebook.py`,
   `test_v4_react_notebook.py`, `test_react_widgets.py`, `test_webapp.py`, and
   `test_webapp_browser.py` all `pytest.importorskip` on `nbformat`/`anywidget`,
   which are absent here — so 6 of the highest-value wiring tests, including the
   README's headline "runs BOTH notebooks end to end" safety net, and the entire
   2,244-line React widget module and the webapp, went **unexercised** in this
   run. 195 passed / 9 skipped, but the skips are exactly the integration seam.
   Not a code bug, but a coverage blind spot worth a CI note (§3.2).

---

## 3. Findings ordered by value

### 3.1 Delete the retired generation wholesale — ~13,000+ lines (JUDGMENT, product call)

This is the headline. The retired driver-coupled flow is fully superseded by the
live controller-only flow and is reachable only through the `v3.2` notebook.
Everything below is verified by repo-wide grep to have **no live importer**:

| What | Lines | Live importers (outside retired + `pipeline` shim) |
|---|---:|---|
| `workflow/retired/` code | 6,460 | none |
| `workflow/retired/tests/` | 6,306 | none |
| `workflow/_log_capture.py` | 261 | none (only `retired/*` + `tests/test_log_capture.py`) |
| `workflow/_save_queue.py` | 139 | none (only `retired/*` + `tests/test_save_queue.py`) |
| `workflow/_saved.py` | 20 | none (only `retired/target.py`, `retired/overview.py`) |
| `tests/test_log_capture.py` | 197 | tests a retired-only module |
| `tests/test_save_queue.py` | 142 | tests a retired-only module |
| `pipeline/__init__.py` shim | 29 | `v3.2` notebook + `retired/*` + 2 compat tests |
| `zmart_microscopy_v3.2.ipynb` | ~13 KB | drives `pipeline.*` (retired) |
| `CONTROLLER_REWRITE_PROGRESS.md` | 136 | referenced nowhere |

Plus three functions that live in *shared* modules but serve only retired code
and its tests, and could be dropped with it:

- `_hijack.hijack_frame` (+ most of `_hijack.py`'s 64-line module docstring and
  `_assert_simulator`, the `layout`-based path): the live flow uses
  `hijack_records`. `tests/test_hijack.py` (544 lines, a *live* test file) drives
  the retired `hijack_frame` entry point; the shared core
  `_overwrite_preserving_ome` would keep its coverage through
  `test_sim_hijack.py`.
- `_mock_provider.build_target_provider` (~127 lines): consumes a retired `Pick`
  / `layout` domain object; the live widgets call `crop_overview_at_target_fov`
  directly.
- `_geom.visible_target_fov_window` (~47 lines): only `retired/visualize.py`
  calls it.

**Why safe:** the operator uses `v4` / `v4_react` / the webapp. None of them
import `pipeline`, `retired`, `_saved`, `_save_queue`, `_log_capture`,
`hijack_frame`, `build_target_provider`, or `visible_target_fov_window`. The
`__init__` re-exports and `__all__` do not include any retired symbol. Deleting
the table above plus the three functions removes **≈13,500 lines (~45% of the
package's Python)** while every operator-visible capability survives untouched.

**Concrete change:** remove `workflow/retired/`, `zmart_microscopy_v3.2.ipynb`,
`pipeline/`, `CONTROLLER_REWRITE_PROGRESS.md`, `_saved.py`, `_save_queue.py`,
`_log_capture.py`, `tests/test_save_queue.py`, `tests/test_log_capture.py`,
`tests/test_pipeline_compat.py`; drop `hijack_frame`/`_assert_simulator`/
`build_target_provider`/`visible_target_fov_window` and reduce
`tests/test_hijack.py` to the `hijack_records`/`_overwrite_preserving_ome` cases
already covered by `test_sim_hijack.py`. Estimated lines saved: **~13,500**.

**Judgment flag:** this is a product decision (does anyone still need the v3.2
driver-coupled path?), not a mechanical cleanup. If the answer is "keep one
generation of history", the honest place for it is a git tag or an `archive/`
directory *outside* the shipped package, so its dead modules stop masquerading
as live `workflow/` code and its broken-here tests stop being collected.

### 3.2 Un-skip or gate the integration tests in CI (SAFE, process)

`test_notebooks_run_end_to_end.py` is the README's advertised proof that the
notebooks still run; it and five siblings silently skip without `nbformat` /
`anywidget`. **Concrete change:** add `nbformat` and `anywidget` to
`requirements-dev.txt` (both are already in `environment.yml`/`requirements.txt`
per the docstrings) and make CI fail if these skip, so the notebook↔steps and
webapp↔flow seams are actually guarded. Lines saved: 0, but this is what keeps
§2's wiring honest over six months.

### 3.3 `move_record_images` should read `planes`, not only `images` (JUDGMENT, see §4.1)

Covered as a real bug in §4.1; listed here because the fix also *simplifies* the
record contract to one source of truth (`record_channel_paths`) instead of three
readers that disagree.

### 3.4 Trim the essay docstrings in `_hijack`, `_geom`, `_mock_provider` (SAFE)

These three modules carry comment/docstring mass far out of proportion to their
code — the clearest "AI slop" in the package:

- `_hijack.py`: a 64-line module docstring (lines 1–64) that re-derives the same
  "positive allowlist / indivisible / fail-closed" argument three more times in
  `NonSimulatorFrameError`, `_assert_simulator`, and `_overwrite_preserving_ome`.
  Much of it disappears with §3.1 (the retired `hijack_frame` half); the rest can
  drop to a tight paragraph.
- `_geom.py`: `target_fov_window_in_overview` and `crop_overview_at_target_fov`
  have NumPy-style `Parameters`/`Returns` blocks longer than their bodies,
  repeating the "scalar pixel size, non-square images honoured" caveat four
  times across the file.
- `_mock_provider.py`: the `build_target_provider` docstring (lines 141–175) plus
  the ~40-line inline essay on `order=0` vs bilinear honesty (lines 226–258).
  Most of this leaves with §3.1.

**Why safe:** pure prose; no behaviour. **Concrete change:** one clear paragraph
per function stating in/out/raises, in the calm CLAUDE.md voice; move the
"why nearest-neighbour is the honest choice" rationale to a single sentence.
Estimated lines saved: **~150–200** (beyond what §3.1 already removes).

### 3.5 `_matching_target_indices` is over-engineered for its job (JUDGMENT)

`_discovery_widget._matching_target_indices` (lines 70–115) runs a two-pass
identity-then-equality reconciliation with a 9-line docstring to handle the case
where discovery yields duplicate-valued target dicts. It is correct and tested,
but it is a lot of subtle machinery guarding a corner the operator rarely hits.
**Judgment:** leave it unless it shows up in profiling or confusion; noting it so
a future maintainer knows it is intentional, not accidental. No change proposed.

---

## 4. Real bugs (flagged, not fixed)

### 4.1 Capture/organize path is silently Leica-only (drift bug)

`_output.move_record_images` (line 120) and `_hijack.hijack_records` (line 366)
read `record["images"]` and nothing else; `move_record_images` raises
`RuntimeError("acquire returned no image paths to organize")` when the key is
absent, **even though a valid `planes` manifest is present**. Confirmed by probe
against a mesospim-shaped record (`image_files` + `planes`) and the controller's
mock driver (`filename` only). `_records.record_channel_paths` already does the
right, driver-agnostic thing (prefer `planes`), so the workflow contradicts
itself: discovery is driver-agnostic, capture-organize is not.

Repro:
```python
from workflow._output import move_record_images
rec = {"image_files": [existing_tiff], "planes": [{"t":0,"z":0,"c":0,"path": existing_tiff}]}
move_record_images(rec, data_dir)   # RuntimeError, despite a good planes manifest
```
This is exactly the "images vs image_files vs filename" drift the maintainer
flagged elsewhere, now visible inside target-acquisition. **Fix direction (do
not apply):** have `move_record_images` derive its source paths from
`record_channel_paths(record, allow_empty=False)` (which already unifies
`planes`/`images`), and update `hijack_records` to iterate the same. This both
fixes the bug and collapses three record readers into one. Plausible-operator
severity: **low today** (only Leica runs this workflow), **latent-high** the
moment a second driver is pointed at it.

### 4.2 Integration-test skip is a silent coverage hole

See §3.2. Not a runtime bug, but the README claims a safety net that does not
run without extra packages; a broken notebook cell would pass CI here.

Note on the retired test suite: `workflow/retired/tests` shows 20 failures in
this environment, but they are all `ModuleNotFoundError: No module named
'IPython'` (and `nbformat`), i.e. **environmental, not code rot** — I could not
verify the retired code itself is broken, only that its tests cannot run here.
This is a further reason to move retired out of the collected tree (§3.1) rather
than leave failing collection.

---

## 5. Simplifying-refactor proposals (before/after sketches)

### 5.1 One record reader (ties off §4.1)

Before — three readers, two of them Leica-only:
```python
# _records.py         -> handles planes + images   (agnostic, good)
# _output.py:120      images = record.get("images"); if not list: raise
# _hijack.py:366      for image_path in record.get("images", []):
```
After — everyone funnels through the agnostic reader:
```python
# _output.move_record_images
paths = record_channel_paths(record, context="acquire record")  # planes|images
# _hijack.hijack_records
for image_path in record_channel_paths(record, context=..., allow_empty=True):
```
Net: fixes the drift bug and removes two ad-hoc parsers. ~15 lines lighter,
one contract instead of three.

### 5.2 Retire the retired flow to an archive (ties off §3.1)

Before: `workflow/retired/` (12.8k lines) shipped inside the importable package,
three orphan modules in `workflow/`, a `pipeline/` shim, and `v3.2.ipynb`, all
collected by pytest and re-exported nowhere.

After: none of it in the shipped tree. If history must be kept, a git tag
(`v3-driver-coupled`) or a top-level `archive/` folder excluded from
`pytest`/packaging. The live `workflow/` package then contains only what an
operator's run touches — the single biggest readability win available here.

### 5.3 The two widget stacks are duplication, but each has a distinct consumer

The matplotlib widgets (`_overview_widget`, `_discovery_widget`,
`_acquisition_widget`, `_focus_widget`; ~2,290 lines) and the React widgets
(`react/_widgets.py`; 2,244 lines) implement the same four review surfaces
twice. **But** the matplotlib stack is `v4.ipynb`'s UI and the React stack is
both `v4_react.ipynb` and the webapp — so this is two products, not accidental
duplication, and the pixel math is already shared. **Recommendation: keep both**
unless the maintainer decides to retire one notebook edition. If a stack is ever
dropped, React is the one the webapp depends on; the matplotlib stack is the
easier ~2,290-line deletion because it has no non-notebook consumer. Flagging the
choice, not making it.

---

## 6. Explicit keeps

- **The live simulation (`_simulation.py`), `_mock_provider._skimage_human_mitosis`,
  and the sim hijack (`hijack_records`, `_overwrite_preserving_ome`).** This is
  what lets biologists learn the flow at their desk and what the offline tests
  ride on. High value, well-scoped, keep.
- **`_calibration_check.py`.** Dense, but every line earns its place — the
  sub-pixel common-window resampling and the "featureless window → not trusted"
  guard are real correctness properties, and the docstrings explain them for the
  intended reader. Keep as-is.
- **`_geom.overview_pixel_to_frame`, `crop_overview_at_target_fov`,
  `target_fov_window_in_overview`.** Genuinely shared pure geometry; the
  single-source-of-truth argument in the module docstring is real (past drift
  between crop and visualization). Keep (trim prose per §3.4).
- **`_run_status.py`, `_canvas.py`, `_figsave.py`.** Small, single-purpose,
  used live, clearly written. Keep.
- **The webapp (`_flow`, `_host`, `_server`, `_page`, `__main__`).** Stdlib-only,
  one-worker-thread discipline, honest offline promise. Coherent and maintainable.
  Keep.
- **The biologist-facing docstrings on the four ipywidgets and the `Session`
  step functions.** These are the model for the rest of the repo — welcoming,
  contextual, complete sentences. Keep; do not "tighten" them into telegram style.

---

## 7. Per-module coverage checklist with verdicts

Read in full unless noted. "Skimmed" means I read the docstring, structure
(class/def outline), and the load-bearing sections but not every line.

**Package root**
- `__init__.py` — clean. Verdict: keep.
- `_bootstrap.py` — clean; note it imports `workflow.retired.context.Config` for
  the v3 notebook (line 33), a live→retired coupling that disappears with §3.1.
- `run_webapp.py` — clean, 23 lines. Keep.
- `README.md` — accurate to live behaviour, including the `images`/`planes`
  contract (lines 78–80). Minor drift: it does not mention that the record
  contract is Leica-specific in practice (§4.1). Verdict: keep, add one caveat.
- `CONTROLLER_REWRITE_PROGRESS.md` — referenced nowhere; migration scratch note.
  Verdict: **delete** (§3.1).

**`workflow/` — live core**
- `__init__.py` — public surface; `__all__` is all-live, no retired leak. Keep.
- `steps.py` — thin orchestration, correct wiring. Keep.
- `_capture_run.py` — clean; the `RunCancelled` "cancel reads as unfinished"
  contract is well-judged. Keep.
- `_records.py` — the *correct* agnostic reader; should become the only one
  (§5.1). Keep and promote.
- `_output.py` — solid, but `move_record_images` carries the drift bug (§4.1).
  Keep with fix.
- `_hijack.py` — live `hijack_records` core is good; `hijack_frame` half is
  retired-only (§3.1); module docstring is over-long (§3.4). Verdict: **shrink**.
- `_mock_provider.py` — `_skimage_human_mitosis` live; `build_target_provider`
  retired-only (§3.1); heavy prose (§3.4). Verdict: **shrink**.
- `_geom.py` — pure geometry, mostly live; `visible_target_fov_window`
  retired-only; docstrings over-long. Verdict: keep core, drop dead helper, trim.
- `discovery.py` — clean OME-geometry + engine-drain logic. Keep.
- `_focus_run.py` / `_focus_surface.py` — pure, well-modelled (geometry-based fit
  choice), good residual diagnostics. Keep.
- `viz.py` — driver-agnostic summary + lazy-matplotlib plots. Keep.
- `_run_status.py` / `_canvas.py` / `_figsave.py` — small, live, clear. Keep.
- `_simulation.py` — the simulated microscope/engine; high value. Keep.
- `_overview_widget.py` / `_discovery_widget.py` / `_acquisition_widget.py` /
  `_focus_widget.py` — read in full; high-quality, biologist-friendly, live-tested.
  Keep (one over-engineered helper noted, §3.5).
- `_saved.py` / `_save_queue.py` / `_log_capture.py` — **no live importer**;
  serve only retired. Verdict: **delete** (§3.1).

**`workflow/react/`**
- `__init__.py` — clean public mirror of the matplotlib API. Keep.
- `_support.py` — read in full; the vendored-React private-scope shim and the
  streaming-over-messages rationale are real and well-explained. Keep.
- `_widgets.py` (2,244 lines) — **skimmed** (full class/def outline + the
  `_ZmartWidget` base, message routing, and gating reimplementation; not every
  JS template line). Structurally sound, shares the Python image math, mirrors
  the matplotlib semantics. Untested in this environment (no `anywidget`, §3.2).
  Verdict: keep; ensure CI actually exercises it.
- `PROTOCOL.md` — **skimmed**; matches the traits/messages the widgets declare.
  Keep.
- `vendor/*.js` (142 KB) + `LICENSE` — official MIT React build, deliberately
  vendored for offline use. Legitimate artifact, not slop. Keep.

**`workflow/webapp/`**
- `_flow.py` — read in full; wires to the same public steps in notebook order,
  clean prerequisite gating. Keep.
- `_host.py` / `_server.py` / `_page.py` — **skimmed** (docstrings + structure +
  the concurrency/one-worker-thread and buffer-cap sections). Coherent stdlib
  design. Untested here (§3.2). Keep.
- `__main__.py` / `__init__.py` — clean entry points. Keep.
- `webapp/README.md` — **skimmed**; consistent with `_page`/`_server` behaviour.
  Keep.

**`pipeline/`**
- `__init__.py` — compatibility shim for the old package name; feeds `v3.2` +
  retired + 2 compat tests only. Verdict: **delete with §3.1**.

**`workflow/retired/` (12,766 lines incl. tests)** — **skimmed** at the
directory/importer level, not line-by-line: `_acquire`, `_job_state`, `connect`,
`context`, `focus`, `output_layout`, `overview`, `preflight`, `selection`,
`summary`, `target`, `template`, `visualize`, and `tests/`. No live importer;
superseded by the controller-only flow. Its tests cannot run here (missing
`IPython`/`nbformat`), so I verified their *deadness by import graph*, not by
execution. Verdict: **delete / archive out of the package** (§3.1).

**`tests/` (live)** — `test_steps`, `test_discovery`, `test_capture_run`,
`test_focus_*`, `test_overview_widget`, `test_acquisition_widget`,
`test_discovery_widget`, `test_calibration_check`, `test_output`, `test_viz`,
`test_pixel_to_frame`, `test_sim_hijack`, `test_figsave`,
`test_leica_procedures_guard` all pass and pin live behaviour. Keep.
`test_hijack.py` (544 lines) is a live file testing the **retired** `hijack_frame`
path — reduce to the shared-core cases (§3.1). `test_save_queue.py` /
`test_log_capture.py` test retired-only modules — **delete with them**.
`test_pipeline_compat.py` — delete with the shim. The six `nbformat`/`anywidget`
integration tests — keep, but make CI run them (§3.2).

**Notebooks**
- `zmart_microscopy_v4.ipynb` — the live operator entry; imports only
  `_bootstrap`. Keep.
- `zmart_microscopy_v4_react.ipynb` — the React edition; imports `_bootstrap`,
  `react`, `workflow`. Keep.
- `zmart_microscopy_v3.2.ipynb` — drives `pipeline.*` (retired). Verdict:
  **delete / archive** (§3.1).

---

### One-line bottom line

The live target-acquisition workflow is well-built and correctly wired; the
single highest-value change is to **delete the retired generation and its
life-support (~13,500 lines, ~45% of the package)**, then fix the Leica-only
record-reader drift and make the skipped notebook/webapp tests actually run.
