# SMART

Adaptive feedback microscopy: pick cells from a low-magnification overview,
re-image each one at high magnification across an objective switch. Cellpose
handles segmentation, calibration handles objective-frame transforms, and the
Leica driver wraps LAS X calls with timing, retry policy, and readback
verification.

## Subsystems

- **`driver/`** - microscope drivers. Currently only
  `vendor/leica/navigator_expert/` (Leica STELLARIS via LAS X). Full API
  reference: `driver/vendor/leica/navigator_expert/README.md`.
- **`calibration/`** - measured optical state: image-to-stage rotation for the
  reference objective, objective translations, and backlash. Operator notebooks
  adopt their results to `current/calibration.json`.
- **`limits/`** - configured Leica stage envelopes. `defaults.json` is the
  physical microscope envelope and the driver's safe default; `current.json` is
  the last active working envelope written explicitly by target acquisition.
- **`workflows/`** - operator-facing automation built on the driver and
  calibration. `target_acquisition/` is the main pipeline; `examples/` are
  short cookbook scripts for on-scope checks.
- **`shared/`** - vendor-neutral primitives: `algorithms/` for focus scoring
  and registration, and `output_layout/` for canonical run-directory layout.
- **`docs/`** - design plans and cleanup history.

## Getting Started

1. Activate the conda env: `lasxapi_extended`.
2. Run the calibration notebooks in
   `calibration/vendor/leica/navigator_expert/notebooks/`: image-to-stage
   first, then objective-pair for each supported pair. Adopt each result to
   `current/calibration.json`.
3. Run the target-acquisition notebook:
   `workflows/vendor/leica/navigator_expert/target_acquisition/smart_microscopy_v3.2.ipynb`.

## Conventions

- Operator notebooks stay thin. Logic lives in the package beside the notebook.
- Runtime artifacts write to operator-selected output roots under
  `media_path/smart/...`. They are not source files and must not be committed.
- See `CLAUDE.md` for repository-wide code style guidance.
