# Examples

Three runnable cookbooks. Each one is a self-contained, top-to-bottom
read of a complete recipe — they are meant to be both useful tools
and a teaching reference for production scripts.

The scripts also double as on-scope health checks: if you bring the
controller to a new microscope, running these in order will exercise
the calibration, acquisition, segmentation, ROI-load, galvo-pan, and
objective-switch paths against the real instrument.

| Script | Purpose | Cellpose | Stage move | Galvo pan | Objective switch |
|---|---|---|---|---|---|
| `objective_switch_target.py` | Pick a cell at one objective, image it (centred + framed) at another. | yes | yes | no | yes |
| `galvo_zoom_in.py` | Pick a cell at zoom 1, galvo-pan + zoom-in on the **same** objective. | yes | no | yes | no |
| `segment_and_define_rois.py` | Acquire (or load) a frame, segment cells, load each as a polygon ROI. | yes | no | no | no |

All three scripts share the same code shape:

1. A long, educational module docstring covering *what*, *why*, and
   *the failure modes you should know about*.
2. A `Constants` section near the top — magic numbers documented and
   tunable in one place.
3. A CLI parser that mirrors the constants where applicable.
4. Frozen dataclasses for domain types (`FrameGeometry`, `SourcePick`,
   `LandingResult` — names vary per script but the pattern is the same).
5. Helper sections grouped by concern: LAS X interaction, image
   analysis, visualisation.
6. Pipeline `step_*` functions that read top-to-bottom in `main()`.
7. A `summary.json` written alongside the TIFFs, capturing every input
   parameter and every measured result so the run is reproducible
   from disk alone.

Operator preconditions (apply to all three)
------------------------------------------

- A job is currently selected in the LAS X UI.
- `ImageTransformation = TOPLEFT` in LAS X Advanced Settings.
- AFC / autofocus OFF; no LAS X modal dialogs.
- `calibration/config/config.json` (v9 schema) and `stage.json` exist.
  Run `calibration/scripts/calibrate_objectives.py` first.

Outputs
-------

Each script writes its outputs under `vendor/leica/config/<scope>/<timestamp>/`:

- `objective_switch_target.py` → `config/objective_target/<ts>/`
- `galvo_zoom_in.py` → `config/galvo_zoom/<ts>/`
- `segment_and_define_rois.py` → `config/segment_and_rois/<ts>/`

These directories are gitignored — outputs are disposable.
