# Calibration

Operator-facing calibration is notebook driven. The notebooks stay thin:
each cell calls one procedure function, while reusable code lives in
`core/`.

## Entry Points

- `notebooks/calibrate_image_to_stage.ipynb` measures the image-to-stage
  orientation matrix for the reference objective.
- `notebooks/calibrate_objective_pair.ipynb` measures the translation
  between one objective pair.

Run image-to-stage first, promote the result, then run the objective-pair
notebook for each objective pair that the scope should support.

## Runtime Files

The live promoted configuration is outside this package:

- `../config/calibration.json` stores promoted optical calibration.
- `../config/stage.json` stores hand-edited stage limits and backlash.

Notebook sessions should write data, reports, and staging configs under an
operator-selected sessions root. Those session artifacts are runtime data;
they are not source files and should not be committed.

## Package Layout

- `core/` contains low-level calibration internals.
- `notebooks/` contains the operator UI.

The driver reads only the promoted files under `navigator_expert/config/`.
