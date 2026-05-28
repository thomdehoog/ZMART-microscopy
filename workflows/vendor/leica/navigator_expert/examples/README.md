# Leica Workflow Cookbooks

Three runnable Leica Navigator Expert cookbooks. Each script is a self-contained, top-to-bottom recipe meant to be both a useful tool and a teaching reference for production workflow code.

The scripts also double as on-scope health checks: if you bring the controller to a new microscope, running these in order will exercise the calibration, acquisition, segmentation, ROI-load, galvo-pan, and objective-switch paths against the real instrument.

| Script | Purpose | Cellpose | Stage move | Galvo pan | Objective switch |
|---|---|---|---|---|---|
| `objective_switch_target.py` | Pick a cell at one objective, image it centered and framed at another. | yes | yes | no | yes |
| `galvo_zoom_in.py` | Pick a cell at zoom 1, galvo-pan and zoom in on the same objective. | yes | no | yes | no |
| `segment_and_define_rois.py` | Acquire or load a frame, segment cells, load each as a polygon ROI. | yes | no | no | no |

All three scripts share the same code shape:

1. A module docstring covering what the script does, why it exists, and relevant failure modes.
2. A `Constants` section near the top, with documented values that are easy to tune.
3. A CLI parser that mirrors the constants where applicable.
4. Frozen dataclasses for domain types.
5. Helper sections grouped by concern: LAS X interaction, image analysis, and visualization.
6. Pipeline `step_*` functions that read top-to-bottom in `main()`.
7. A `summary.json` written alongside the TIFFs, capturing every input parameter and measured result so the run is reproducible from disk alone.

## Operator Preconditions

- A job is currently selected in the LAS X UI.
- `ImageTransformation = TOPLEFT` in LAS X Advanced Settings.
- AFC / autofocus OFF; no LAS X modal dialogs.
- `calibration/vendor/leica/navigator_expert/current/calibration.json` and `calibration/vendor/leica/navigator_expert/current/limits.json` exist. Run the calibration notebooks first and adopt the generated config.

## Outputs

Each script writes disposable run outputs under `workflows/vendor/leica/navigator_expert/examples/output/<scope>/<timestamp>/` by default:

- `objective_switch_target.py` -> `examples/output/objective_target/<ts>/`
- `galvo_zoom_in.py` -> `examples/output/galvo_zoom/<ts>/`
- `segment_and_define_rois.py` -> `examples/output/segment_and_rois/<ts>/`
