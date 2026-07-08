# Calibration

Measure the optical state of the microscope: the translation between each
objective pair the scope should support. Workflows consume only the adopted
calibration in the newest machine snapshot. The notebooks and session artifacts
in this folder are not runtime dependencies — but `core/model.py` and the
bundled `defaults/` are: the driver imports the model and loads the calibration
(newest snapshot, falling back to `defaults/`) at every connect.

The rig's **image→stage orientation** is a separate concern owned by
`navigator_expert/orientation/` (measured by
`orientation/notebooks/set_orientation.ipynb`, applied to exported planes at
save time), not part of this calibration. Because calibration frames are
already stage-aligned when saved, the objective-pair workflow registers image
shifts directly in the stage frame — no image-to-stage matrix lives here.

Operator-facing calibration is notebook driven. The notebooks stay thin:
each cell calls one procedure function, while reusable code lives in
`core/`.

## Entry Points

- `notebooks/calibrate_objective_pair.ipynb` measures the translation
  between one objective pair.

Set up a new rig in order: `limits/notebooks/set_stage_limits.ipynb` (physical
envelope), then `orientation/notebooks/set_orientation.ipynb` (image→stage
rotation), then run the objective-pair notebook for each objective pair the
scope should support.

## Snapshots

Adopting a calibration publishes a dated, machine-local **snapshot** under
`C:\ProgramData\zmart-microscopy\<vendor>\<microscope>\<api>\<datetime>\`. Each
snapshot dir holds exactly three files: `calibration.json` (optical
calibration), the physical `limits.json` (the single function-keyed limits
file: `constraints` + `functions`; no `backlash` block — backlash is a motion
utility with baked-in defaults, §2b), and the operator's `origin.json` (frame
zero point, carried forward) — plus the executed notebook.
The driver reads the newest snapshot (`config/machine.py`). `calibration.json`
keeps a loud bundled **read** fallback (`calibration/defaults/`) when no
snapshot exists; `limits.json` does **not** fall back for enforcement
(`limits/defaults/limits.json` is a template, refused). Note the split of
concerns: a **limits** adopt (the `set_stage_limits` notebook under
`limits/notebooks/`) writes only `limits.json` and never mints a
`calibration.json` from the template; a **calibration** adopt writes
`calibration.json` and carries the prior `limits.json` forward.

The per-run *working* envelope (a boundary-marker sample area) is not machine
state - it belongs to the acquisition workflow, not here.

Notebook sessions write data, reports, and staging configs under an
operator-selected sessions root. Those session artifacts are runtime data;
they are not source files and should not be committed.

## Package Layout

- `core/` contains low-level calibration internals.
- `notebooks/` contains the operator UI.

Runtime code reads only the adopted calibration in the newest machine snapshot
(`config/machine.py`), or the bundled `calibration/defaults/` when none exists.
