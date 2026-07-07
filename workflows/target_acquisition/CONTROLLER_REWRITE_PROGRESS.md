# target_acquisition → controller-only rewrite — progress

**Branch:** `controller-workflow` (off `6f558ce`). **Status:** all 7 step-functions are
logic-complete and unit-tested (25 tests, all green); the notebook + module rewire
+ deletions are the remaining phase.

## Goal

Rewrite `workflows/target_acquisition` so the operator flow drives Leica through the
**`zmart_controller` surface only** — no `import navigator_expert` in the step logic.
Operator flow (thin notebook, ~1–3 lines/cell, one cell per collected state):

1. connect to Leica
2. collect states (one cell per state — a "state" = a selected LAS X job)
3. load positions (explicit list; no scan-field/limits derivation)
4. focus: place focus points ourselves, run them with the autofocus job via `run_procedure`
5. run the overview
6. target discovery (segment overviews via the analysis engine)
7. target acquisition

## Key decisions (locked)

- **No driver/adapter change.** RIGHTTOP orientation is dropped, so pixel→frame is just
  `frame_pos + (pixel − centre) × pixel_size` — pure workflow arithmetic over data the
  workflow already has (the frame position it moved to + the saved image's `pixel_size`).
- **Dropped for good:** calibration/objective-translation (the controller frame is already
  objective-compensated), scan-field templates, limits-derivation, raw job-settings editing,
  RIGHTTOP.
- **Reused (no reinvention):** the controller `mock_driver` (offline unit tests), `_geom`,
  the **cellpose analysis engine** (segmentation, via its `submit`/`status`/`results` contract),
  and `_hijack` + `_mock_provider` (test mode). Visualization: **option (a) — adapt the existing
  `visualize.py`/`summary.py`** to the new data (richer figures), not minimal inline plots.
- **Test mode = the real path + a pixel swap.** `acquire` writes a real `.ome.tiff` + companion
  XML on the simulator; `hijack_frame` overwrites *only the pixels* (OME/metadata byte-preserved),
  then everything downstream loads/analyses real-looking files. The SIMULATOR allowlist guarantees
  it can never touch a real-hardware frame. **The step functions never learn about simulation** —
  the sim caller applies the hijack over the file paths `acquire` returns.
- **`acquire` returns the printed file paths** — the Leica adapter already returns
  `{"images": [paths], "xml": [paths], …}`. No change needed.

## Done + committed (25 tests, no `navigator_expert` import)

| Module (new) | Step | Commit |
|---|---|---|
| `pipeline/_capture_run.py` — `capture_positions` (shared overview/target acquire loop) | 5, 7 | `af760bd` |
| `pipeline/_geom.py::overview_pixel_to_frame` (pixel→frame, no orientation) | 6 | `af760bd` |
| `pipeline/_focus_surface.py` — `fit_focus_surface` + `FocusSurface.z_at` (constant/plane/spline) | 4 | `af760bd` |
| `pipeline/_focus_run.py` — `measure_focus` (autofocus via `run_procedure`) | 4 | `af760bd` |
| `pipeline/steps.py` — `connect`, `load_positions`, `with_focus_z`, `run_overview`, `acquire_targets` | 1,3,5,7 | `424eb2f` |
| `pipeline/discovery.py` — `discover_targets` (reuses the analysis engine; centroids → frame) | 6 | `cf29192` |

Step 2 (collect states) needs **no module** — it's raw `mic.get_state()` / `mic.set_state(s)`.

Tests: `tests/test_capture_run.py`, `test_pixel_to_frame.py`, `test_focus_surface.py`,
`test_focus_run.py`, `test_steps.py`, `test_discovery.py`.

## Decided, NOT yet implemented (do this first on resume)

- **Simplify `hijack_frame`** to `hijack_frame(image_path, xml_path, provider, *, naming)` —
  drop the `kind`/`layout`/`result` derivation (it re-derives paths `acquire` already hands us);
  keep `naming` (the provider's one input, so `_mock_provider` stays untouched). It remains the
  single indivisible check-and-overwrite entry point (SIMULATOR gate unchanged).
- Update `tests/test_hijack.py` mechanically (it already builds the file pair + `naming`; pass the
  two paths instead of `result`/`layout`).
- Sim caller pattern (one cell, `run_overview` untouched):
  ```python
  records = run_overview(mic, positions, state=overview_state, focus=focus)
  if simulate:
      for i, rec in enumerate(records):
          hijack_frame(rec["images"][0], rec["xml"][0], provider, naming=Naming("overview", hash6, p=i))
  ```

## Rewire phase — status

**Decision (locked):** retire the driver-coupled modules, do **not** delete them. They move
under `pipeline/retired/` (preserved reference + safety-net tests), and the active
`pipeline` package exports the controller-only surface only.

Done:

1. ✅ **`pipeline/__init__.py` rewired** to the controller-only surface: `connect`,
   `load_positions`, `with_focus_z`, `measure_focus`, `fit_focus_surface`, `FocusSurface`,
   `run_overview`, `discover_targets`, `acquire_targets`, `capture_positions`,
   `overview_pixel_to_frame`. `import pipeline` pulls **no** driver code (verified);
   `zmart_controller` loads lazily inside `steps.connect()`.
2. ✅ **Retired** (moved to `pipeline/retired/`, not deleted): `connect`, `context`,
   `preflight`, `focus`, `overview`, `target`, `selection`, `template`, `_job_state`,
   `_acquire`, plus `visualize` / `summary` (welded to the retired data types).
   **Kept active:** `_hijack`, `_mock_provider`, `_geom`, `_figsave`, `_save_queue`,
   `_saved`, `_log_capture`, plus the new `steps`, `discovery`, `_capture_run`,
   `_focus_run`, `_focus_surface`. Retired modules import the kept helpers via `..`.
3. ✅ **Tests split.** Controller-only tests stay in `tests/`; the retired-coupled tests
   moved to `pipeline/retired/tests/` (own `conftest.py` + `support.py`). Both suites green
   (active 76 passed / 2 skipped; retired 183 passed / 11 skipped — same 259/13 as before).
4. ✅ **`_bootstrap.py`** (v3 notebook entry) repointed: `Config` now comes from
   `pipeline.retired.context`. The v3 notebook remains as the retired flow's reference.

Still open (not blocking "workflow uses the controller only"):

1. Thin **v4 notebook** (`zmart_microscopy_v4.ipynb`) — markdown + 1–3 line invocations,
   one cell per step, over the new `pipeline` surface.
2. **New `visualize` / `summary`** adapted to the new data (overview record dicts +
   `discover_targets` output + `FocusSurface`). The retired ones are welded to
   `OverviewResult` / `Pick` / `SelectionResult` / `scan_field`; new figures are a
   follow-up once the v4 record schema is exercised end-to-end.
3. **Sim caller wiring** for the new flow (apply `hijack_frame` over the paths the
   controller `acquire` returns; step functions stay simulation-unaware).
4. **Sim fidelity end-to-end** run: real Leica adapter on the LAS X simulator + hijack →
   acquire → segment → discover → target, on the real controller-only code path.

## Controller surface (reference)

`get_instruments · set_instrument · disconnect · set_origin · get_xyz/set_xyz · get_actuators ·
get_state/set_state · get_procedures/run_procedure · get_acquisition_options · acquire · get_context`.
The Leica adapter (`zmart_adapter.py`) registers all of them and was live-validated on the sim.
