# SMART

Adaptive feedback microscopy: pick cells from a low-magnification overview, re-image each one at high magnification across an objective switch. Cellpose for segmentation, vendor-neutral coordinate transforms for the objective switch, and a confirm-and-retry driver wrapping the Leica LAS X Python API.

## Subsystems

- **`controller/`** — microscope drivers. Currently only `vendor/leica/navigator_expert/` (Leica STELLARIS via LAS X). Every command routes through a two-layer confirm-and-fire dispatcher with structured timing, retry policy, and readback verification. Full API reference: `controller/vendor/leica/navigator_expert/README.md`.
- **`calibration/`** — measure the optical state of a microscope: image-to-stage rotation for the reference objective, then translation between each objective pair. Operator-driven notebooks promote their results to `current/*.json`; workflows read only the promoted JSON.
- **`workflows/`** — operator-facing automation built on the driver and calibration. `target_acquisition/` is the flagship pipeline; `examples/` are short cookbook scripts that double as on-scope health checks (calibration, acquisition, segmentation, ROI load, galvo pan, objective switch).
- **`shared/`** — vendor-neutral primitives. `algorithms/` (focus scoring, registration); `output_layout/` (lab-wide canonical file naming and run-directory layout).
- **`docs/`** — design plans and cleanup history. `MIDLAYER_PLAN.md` is target-state for a future vendor-neutral waist; `cleanup/` is historical.

## Getting Started

1. Activate the conda env: `lasxapi_extended`.
2. From `calibration/vendor/leica/navigator_expert/notebooks/`, run the calibration notebooks: image-to-stage first, then objective-pair for each pair the scope should support. Promote each result to `current/`.
3. From a workflow (e.g. `workflows/vendor/leica/navigator_expert/target_acquisition/notebook.ipynb`), follow the config cell.

## Conventions

- Operator notebooks stay thin (markdown + 1-3 line invocations). Logic lives in the pipeline / cookbook code beside the notebook.
- Runtime artifacts (acquired TIFFs, run logs, calibration reports) write to operator-selected output roots under `media_path/smart/...`. They are not source files and must not be committed.
- See `CLAUDE.md` for repository-wide code style guidance.
