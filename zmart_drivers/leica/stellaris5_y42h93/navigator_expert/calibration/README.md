# Calibration

Measure the optical state of the microscope: the translation between each
objective pair the scope should support. Workflows consume only the adopted
calibration in the newest machine snapshot. The notebooks and session artifacts
in this folder are not runtime dependencies - but `core/model.py` and the
bundled `defaults/` are: the driver imports the model and loads the calibration
(newest ProgramData snapshot, seeded from `defaults/` if needed) at every
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

When you adopt a calibration, the driver saves a dated **snapshot** folder on
the machine, under
`C:\ProgramData\zmart-microscopy\<vendor>\<microscope>\<api>\<datetime>\`. Each
snapshot keeps everything the microscope needs together: `calibration.json`
(the objective positions measured here), `limits.json` (how far the stage is
allowed to move), `orientation.json` (how the camera is turned relative to the
stage), and `origin.json` (the operator's zero point) — plus a copy of the
notebook that produced it, so you can always see how the numbers were made.
The driver simply reads the newest snapshot.

ProgramData is the source of truth. If no snapshot exists yet, the driver copies
the repo defaults for calibration, limits, and orientation into a local
ProgramData snapshot so CI and mock runs can connect. Each setup step stays in
its own lane after that: running the stage-limits notebook replaces
`limits.json`, setting orientation replaces `orientation.json`, and adopting a
calibration writes either `calibration.json` or a named
`calibrations/<name>/calibration.json` while carrying the rest forward.

The per-run *working* envelope (a boundary-marker sample area) is not machine
state - it belongs to the acquisition workflow, not here.

Notebook sessions write data, reports, and staging configs under an
operator-selected sessions root. Those session artifacts are runtime data;
they are not source files and should not be committed.

## Package Layout

- `core/` contains low-level calibration internals.
- `notebooks/` contains the operator UI.

Runtime code reads only ProgramData paths resolved by `../config/machine.py`.
