# Target Acquisition

Pick cells from a low-magnification overview, re-image each at the high-magnification objective. The operator notebook drives the microscope through `zmart_controller`.

1. **Setup and connect** — connect through the controller and ask the microscope for the run root.
2. **Set origin** — set the current microscope position as `(0, 0, 0)`.
3. **Jobs** — capture the overview and target states.
4. **Initial positions** — ask the microscope for scan-field positions.
5. **Focus** — pick focus points in an interactive figure (points already placed in LAS X are pre-filled), press **Measure focus** to autofocus at each one, and inspect the fitted z surface as a heatmap in the same figure.
6. **Validate the calibration** — image the same ring of ~12 sites with both objectives and register each pair: the mean leftover offset is how far the XY calibration is off, the scatter is the stage's own repeatability.
7. **Overview** — acquire one image per position, then browse them as one zoomable map with every tile at its real stage position and per-channel colour / brightness / contrast controls.
8. **Discover targets** — segment the overviews, then gate interactively: put any measured feature on the plot axes, threshold with sliders or draw a lasso, and hover a point to see that cell's image crop.
9. **Acquire targets + summary** — type how many to acquire; a random sample of the gate is re-imaged and reviewed as overview/target image pairs at the same physical scale, then the run report is written.

## Entry Point

Open `zmart_microscopy_v4.ipynb`. The notebook is the operator UI; implementation lives in `workflow/`. All four review widgets update live while the microscope works — tiles, focus points, and image pairs appear the moment they exist.

`zmart_microscopy_v4_react.ipynb` is the same run with the widgets as React apps inside the cells (via `anywidget`): the browser UI streams in real time and its buttons drive the kernel, which drives the hardware through the same gated paths. It needs only the `anywidget` package — React itself ships inside the repository (the official MIT-licensed build), so both notebooks work fully offline.

The setup cell expects a checkout of
[`smart-analysis`](https://github.com/thomdehoog/smart-analysis) on its `v4-engine`
branch at `ANALYSIS_REPO`. Before connecting to LAS X it registers the external
target-acquisition pipeline and runs a 64x64 blank tile through its Cellpose
worker. This fails early when the analysis repository, declared worker conda
environment, Cellpose model, or GPU setup is unavailable; on success the worker
remains warm for the acquired overviews.

## Layout

- `_bootstrap.py` — adds `zmart_drivers/leica/stellaris5_y42h93/`, `microscopes/`, and the repo root to `sys.path` so the notebook can import the driver, calibration, shared packages, and workflow code.
- `workflow/` — public surface for the controller-only workflow plus internal modules with leading underscore.
- `pipeline/` — compatibility import for old notebooks/tests.
- `tests/` — workflow unit tests (offline; no microscope or vendor software).

## Tests

Offline workflow unit tests — no microscope, no vendor software. Run from the
repo root:

```powershell
python -m pytest -q workflows/target_acquisition/tests
```

## Output

Acquisition artifacts write to a `zmart/` tree beside the LAS X native AutoSave base folder, not into this package.
