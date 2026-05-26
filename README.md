# SMART

Microscope automation framework.

## Structure

- `shared/` - vendor-neutral utilities used by controllers and workflows.
- `controller/vendor/leica/navigator_expert/` - Leica Navigator Expert package.
  - `driver/` - LAS X driver, template handling, acquisition output, and motion helpers.
  - `calibration/` - calibration core code and operator notebooks.
  - `config/` - Leica machine, stage, API profile, and calibration config files.
  - `test/` - driver and calibration unit tests.
- `workflows/vendor/leica/navigator_expert/` - Leica workflow entry points.
  - `target_acquisition/` - target acquisition notebook, pipeline code, docs, and tests.
  - `examples/` - runnable Leica workflow cookbooks.
- `docs/cleanup/` - cleanup state and conventions.
