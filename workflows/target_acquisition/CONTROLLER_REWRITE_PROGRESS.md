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

## Remaining (the rewire phase)

1. Thin **v4 notebook** (`zmart_microscopy_v4.ipynb`) — markdown + 1–3 line invocations, one cell per step.
2. New `pipeline/__init__.py` exporting the new step functions.
3. **Adapt** `visualize.py` / `summary.py` (option a) to the new data (overview images + `discover_targets`
   output + `FocusSurface`), replacing `OverviewResult`/`Pick`/`scan_field` inputs.
4. **Delete** the driver-coupled control modules + their tests: `connect`, `context`, `preflight`,
   `focus`, `overview`, `target`, `selection`, `template`, `_job_state`, `_acquire`.
   **Keep:** `_hijack`, `_mock_provider`, `_geom`, `_figsave`, `_save_queue`, `_saved`, `_log_capture`
   (adapt as needed).
5. Full offline suite green (only the new tests remain).
6. **Sim fidelity end-to-end** run: real Leica adapter on the LAS X simulator + hijack →
   acquire → segment → discover → target, on the real code path.

## Controller surface (reference)

`get_instruments · set_instrument · disconnect · set_origin · get_xyz/set_xyz · get_actuators ·
get_state/set_state · get_procedures/run_procedure · get_acquisition_options · acquire · get_context`.
The Leica adapter (`zmart_adapter.py`) registers all of them and was live-validated on the sim.
