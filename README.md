# SMART

Microscope automation framework.

## Structure

- `controller/vendor/leica/navigator_expert/` — main Python package
  - `driver/` — Leica STELLARIS / LAS X confocal driver
  - `algorithms/` — image-analysis primitives (focus, registration)
  - `calibration/` — multi-objective calibration subsystem
  - `examples/` — three working end-to-end example scripts
  - `notebooks/` — workbooks
  - `test/` — pytest suite
- `docs/cleanup/` — cleanup state and conventions
