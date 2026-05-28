# Calibration

Measure the optical state of the microscope: the image-to-stage rotation
for the reference objective, then the translation between each objective
pair the scope should support. Workflows consume only the adopted JSON
under `current/`; nothing else here is a runtime dependency.

Operator-facing calibration is notebook driven. The notebooks stay thin:
each cell calls one procedure function, while reusable code lives in
`core/`.

## Entry Points

- `notebooks/calibrate_image_to_stage.ipynb` measures the image-to-stage
  orientation matrix for the reference objective.
- `notebooks/calibrate_objective_pair.ipynb` measures the translation
  between one objective pair.

Run image-to-stage first, adopt the result, then run the objective-pair
notebook for each objective pair that the scope should support.

## Current State

The adopted calibration state lives here:

- `current/calibration.json` stores adopted optical calibration and backlash.

Configured stage limits are not calibration measurements. They live in the
top-level `limits/vendor/leica/navigator_expert/` tree:

- `defaults.json` stores the configured physical microscope envelope.
- `current.json` stores the active working envelope used by the driver.

Target-acquisition boundary markers define a run-specific sample area inside
the physical envelope. The notebook writes that active working envelope to
`limits/vendor/leica/navigator_expert/current.json`.

Notebook sessions should write data, reports, and staging configs under an
operator-selected sessions root. Those session artifacts are runtime data;
they are not source files and should not be committed.

## Package Layout

- `core/` contains low-level calibration internals.
- `notebooks/` contains the operator UI.

Runtime code reads only the adopted files under
`calibration/vendor/leica/navigator_expert/current/`.
