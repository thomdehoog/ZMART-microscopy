# Calibration

Measure the optical state of the microscope: the image-to-stage rotation
for the reference objective, then the translation between each objective
pair the scope should support. Workflows consume only the adopted calibration
in the newest machine snapshot; nothing in this folder is a runtime dependency.

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

## Snapshots

Adopting a calibration publishes a dated, machine-local **snapshot** under
`C:\ProgramData\smart_microscopy\<vendor>\<microscope>\<datetime>\`, holding
`calibration.json` + the physical `limits.json` + the executed notebook. The
driver reads the newest snapshot (`config/machine.py`); with no snapshot it
falls back, loudly, to the driver-bundled `defaults/`. The physical stage
envelope has its own operator notebook, `set_stage_limits` under
`limits/notebooks/`.

The per-run *working* envelope (a boundary-marker sample area) is not machine
state - it belongs to the acquisition workflow, not here.

Notebook sessions write data, reports, and staging configs under an
operator-selected sessions root. Those session artifacts are runtime data;
they are not source files and should not be committed.

## Package Layout

- `core/` contains low-level calibration internals.
- `notebooks/` contains the operator UI.

Runtime code reads only the adopted calibration in the newest machine snapshot
(`config/machine.py`), or the bundled `defaults/` when none exists.
