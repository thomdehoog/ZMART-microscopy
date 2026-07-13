# Calibration

Measure the optical state of the microscope: the translation between each
objective pair the scope should support. Workflows consume only the adopted
calibration in the newest `calibration/<datetime>/` snapshot. The notebooks and session artifacts
in this folder are not runtime dependencies - but `core/model.py` and the
bundled `defaults/` are: the driver imports the model and loads the calibration
(newest calibration snapshot, seeded from `defaults/` if needed) at every
connect.

The rig's **image→stage orientation** is a separate concern owned by
`navigator_expert/orientation/` (measured by
`../orientation/notebooks/set_orientation.ipynb`, applied to exported planes at
save time), not part of this calibration. Because calibration frames are
already stage-aligned when saved, the objective-pair workflow registers image
shifts directly in the stage frame — no image-to-stage matrix lives here.

Operator-facing calibration is notebook driven. The notebooks stay thin:
each cell calls one procedure function, while reusable code lives in
`core/`.

## Entry Points

- `notebooks/calibrate_objective_pair.ipynb` measures the translation
  between one objective pair.

Set up a new rig in order: `../limits/notebooks/set_limits.ipynb` (physical
envelope), then `../orientation/notebooks/set_orientation.ipynb` (image→stage
rotation), then run the objective-pair notebook for each objective pair the
scope should support.

## Snapshots

When you adopt a calibration, the driver appends
`C:\ProgramData\zmart-microscopy\<vendor>\<microscope>\<api>\calibration\<datetime>\`.
It contains `calibration.json`, any named `calibrations/<name>/calibration.json`
sets carried forward from the preceding calibration snapshot, and the notebook
that produced the adoption. The driver reads the newest calibration timestamp.

Limits, orientation, and origin have parallel independent trees. Publishing
one subsystem never copies the others. ProgramData is the source of truth; an
empty limits, calibration, or orientation tree seeds from its own repo default.

The per-run *working* envelope (a boundary-marker sample area) is not machine
state - it belongs to the acquisition workflow, not here.

Notebook sessions write data, reports, and staging configs under an
operator-selected sessions root. Those session artifacts are runtime data;
they are not source files and should not be committed.

## Package Layout

- `core/` contains low-level calibration internals.
- `notebooks/` contains the operator UI.

Runtime code reads only ProgramData paths resolved by `../config/machine.py`.
