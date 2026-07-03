# Stage limits

The microscope's **physical stage envelope**: the hard XY / Z ranges the driver
refuses to move outside. These are hardware safety limits for the scope, not a
per-experiment area (that is the workflow's concern).

Operator-facing limit setting is notebook driven, mirroring calibration. The
notebook stays thin: one cell edits the envelope and calls
`navigator_expert.stage.config.write_limits`.

## Entry point

- `notebooks/set_stage_limits.ipynb` — enter each axis `[min, max]` in
  micrometers and publish the committed physical envelope.

## Files

- `defaults.json` — the committed physical envelope for this scope. The driver
  loader reads this by default. Written by the notebook above; commit it after
  running.
- `current.json` — the active working envelope, written at runtime by the
  target-acquisition workflow from boundary markers or scan-field geometry, and
  reloaded before limits are applied. Runtime artifact; gitignored.
