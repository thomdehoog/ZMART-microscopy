# Review request: v4 calibration validation, review fixes, 3-pass backlash, live widgets, React edition

You are reviewing the commits on branch `claude/leica-config-loading-review-ammwaz`
in `thomdehoog/ZMART-microscopy` that follow the hardening commit `2230501`.
Review them against `2230501`, then sanity-check the whole branch against
`origin/main`. The prior review round is documented in
`docs/reviews/v4_notebook_hardware_proof_review.md` (findings 1–5 claim fixes in
these commits; verify each fix is faithful and introduces no new defect).

This is safety-adjacent code for a real Leica Stellaris 5. Do an adversarial code
review. Do not implement fixes. Prioritize wrong stage coordinates, unsafe or
surprising hardware actions, silent failures, and misleading operator-facing state
over style. Anything outside the listed scope that is worth mentioning: mention it.

## What the commit contains

### A. XY-calibration validation run (new feature — highest priority)

`workflows/target_acquisition/workflow/_calibration_check.py`, notebook section 5b
(two cells), tests in `tests/test_calibration_check.py`, exports in
`workflow/__init__.py`, README step 6.

Intent: visit N (default 12) sites on a ring of `radius_um` (default 1000) around
the frame origin; acquire each with the overview job (objective 1); re-visit every
site with the target job (objective 2 — the driver applies the calibrated
translation on each move); register each image pair; report the mean offset (the
systematic calibration error) separately from the rms scatter (per-move stage
error). Report + plot written into the run root.

Check specifically:

1. **Sign and axis convention.** The synthetic ground-truth test injects a
   (+3, −2) µm objective-2 positioning error and asserts the report's mean
   recovers it sign-correct. Trace the double negation
   (`register_voting` internals negate; `_pair_offset_um` negates again) and
   decide whether the docstring's operator-facing meaning ("where objective 2
   landed relative to objective 1") is right, and whether an operator applying
   the reported mean as a calibration correction would move things the right way.
2. **Cross-scale windowing.** `_pair_offset_um` crops both images to the shared
   physical window (min FOV per axis, centred) via `crop_overview_at_target_fov`
   and resamples the coarser onto the finer grid. Look for off-by-one/rounding
   drift between the two crops (`int()` truncation of `window_um / fine_ps`),
   anisotropic-shape handling, and whether median edge-padding can bias the
   registration when the two FOVs differ a lot.
3. **Trust plumbing.** Featureless windows are refused (std < 1e-6) — is that
   threshold meaningful for uint16 camera noise? Untrusted sites stay in
   `sites` but out of the statistics; fewer than 3 trusted sites raises. Can NaN
   leak into the JSON report or the plot?
4. **Hardware behaviour.** Both passes run through `capture_positions`
   (state applied once per pass, gated `set_xyz` per site, z from the focus
   surface). Sites at radius 1000 µm may sit outside a machine's measured
   envelope — the gate refuses mid-run; judge whether failing after the first
   few acquisitions is acceptable or whether the check should pre-validate all
   sites against the limits before moving at all.
5. **Notebook placement.** Section 5b sits between Focus and Overview and uses
   `overview_state`/`target_state` captured in step 3. Confirm the report
   (`calibration_check.json`/`.png`) cannot be mistaken for run output by later
   steps, and that skipping 5b entirely leaves the rest of the run intact.

### B. Fixes for the prior review's findings (verify each against
`docs/reviews/v4_notebook_hardware_proof_review.md`)

1. Notebook jobs cell now also requires `limits["source"] == "machine"`. Confirm
   `shared.limits` really reports `"machine"` for operator-adopted files on every
   path (named calibrations, explicit `stage_limits_path`, snapshot carried
   forward), i.e. the stricter check cannot brick a legitimately configured rig.
2. Queued-click debounce (2 s, monotonic) in `AcquisitionGallery._on_acquire_clicked`
   and `FocusPicker._on_measure_clicked`. Judge the window length, that the
   status/title message is visible, and that programmatic paths stay undebounced.
   Is there any path where the debounce eats a *legitimate* first click?
3. Setup-cell failure path shuts the engine down in a `finally` even when
   controller disconnect raises; re-run shutdown of the old engine is best-effort
   with a printed warning. Re-check every notebook lifecycle path for leaks.
4. Hardware validator: `get_focus_points` returning an empty list is now a SKIP,
   not a FAIL. Confirm the offline mock expectations still pin the mock path.

### C. 3-pass backlash takeup

`navigator_expert/motion/movement.py::correct_backlash` now loops
`passes` (default 3) overshoot-and-return round trips; `passes < 1` raises;
tests updated. Check every call site (adapter acquire path, `backlash_takeup`
procedure, retired flow) tolerates the tripled move count and duration, that the
per-pass sleep still applies, and that nothing pins the old two-move sequence.

### D. Live-updating widgets

`workflow/_capture_run.py` grew an ``on_record(index, position, record)``
callback (threaded through ``run_overview`` / ``acquire_targets``), and
``measure_focus`` an ``on_point``; ``workflow/_canvas.py::force_draw`` forces
synchronous repaints mid-loop. The matplotlib widgets now stream: the overview
viewer opens empty and grows via ``add_acquisition`` (plus ``reload()`` after
the simulation hijack), the gallery draws each pair as it is acquired
(``_begin_gallery``/``_draw_row``), and the focus picker refits and redraws the
heatmap after every measured point.

Check specifically:

1. A callback exception aborts the run mid-hardware — is every abort path
   still honest (records uncommitted, partial rows visible, no state that a
   later cell mistakes for success)?
2. ``force_draw`` calls ``canvas.draw()`` per tile/point/pair — estimate the
   render cost on a 25-tile scan and whether it can meaningfully slow
   acquisition; is drawing on the acquisition thread acceptable under ipympl?
3. The empty-start viewer initializes channel display ranges from the FIRST
   tile only (batch construction still uses all tiles). Can a dim first tile
   mis-scale the whole streamed session, and is that acceptable?
4. The v4 notebook's overview cell now creates the viewer before capturing and
   reloads after the hijack — confirm ordering is right in simulation mode and
   that `overview_inputs_from_records` still governs what analysis sees.

### E. The React edition (`workflow/react/`, `zmart_microscopy_v4_react.ipynb`)

Four anywidget/React apps mirror the matplotlib widgets, sharing their image
math (``composite_channels``, ``crop_for_target``, ``pair_images``). State
syncs via traits; buttons send messages to Python, which alone drives the
hardware. Check specifically:

1. **Trust boundary**: the browser can send arbitrary messages — confirm every
   ``handle_message`` validates its input (count parsing, index bounds on
   ``hover``: can an out-of-range index raise unhandled?) and that nothing the
   browser sends can bypass gating, debounce, or busy-guards.
2. **Parity**: gating semantics (thresholds AND lasso, axis-switch clears the
   gate), commit-only-on-success, queued-click debounce, and focus
   invalidation on point edits must match the matplotlib widgets exactly —
   diff the two implementations for behavioural drift.
3. **Trait-size hygiene**: tiles/rows travel as base64 PNGs inside traits.
   Estimate payload sizes for a 25-tile 2-channel scan (no downsample by
   default in the React viewer!) and flag anything that could stall the comm
   channel; should the React viewer share the matplotlib viewer's
   auto-downsample budget?
4. **CDN dependency**: React loads from esm.sh in the browser. The docs say
   so — is the failure mode when offline visible enough (blank cell vs
   message)?
5. The ESM strings cannot be executed by the offline suite — list what only a
   browser session can prove (pan/zoom math, lasso pixel→data conversion,
   pointer capture) as residual risks.
6. `test_v4_react_notebook.py` pins the notebook structurally; check the React
   notebook kept every hardware step and lifecycle guard of the v4 original
   (engine preflight before connect, limits `source == "machine"` check, jobs
   distinctness, cleanup cell).

### F. Cross-cutting

- The four widgets after this commit: layout at 1/5/10/25 gallery rows, the
  overview viewer's left-margin change, README/docstring drift.
- `workflow/__init__.py` exports and the notebook guard tests still agree with
  the notebook's `workflow.<name>` usage.
- Suites: ruff clean; `pytest zmart_controller/tests
  workflows/target_acquisition/tests navigator_expert/tests/unit` = 1121 passed
  in one process. Look for what those numbers still cannot prove (the
  smart-analysis v4 contract remains unverifiable offline — finding 6 of the
  prior review stands).

## Deliverable

Findings ordered blocker / major / minor / nit, each with exact `file:line`, a
concrete failing scenario, why existing tests miss it, and the smallest fix.
Then a short verified-correct section and a residual-risk list containing only
claims that require the real microscope.
