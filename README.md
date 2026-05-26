# SMART

Microscope automation framework.

## Structure

- `shared/` - vendor-neutral utilities used by controllers and workflows.
- `controller/vendor/leica/navigator_expert/` - Leica Navigator Expert package.
  - `driver/` - LAS X driver, template handling, acquisition save chain, and stage helpers.
  - `tests/` - offline driver unit tests and fixtures.
- `calibration/vendor/leica/navigator_expert/` - Leica calibration notebooks, code, tests, and promoted current state.
- `workflows/vendor/leica/navigator_expert/` - Leica workflow entry points.
  - `target_acquisition/` - target acquisition notebook, pipeline code, docs, and tests.
  - `examples/` - runnable Leica workflow cookbooks.
- `docs/cleanup/` - cleanup state and conventions.
