# Target Acquisition

Pick cells from a low-magnification overview, re-image each at the high-magnification objective. The operator notebook drives the microscope through `zmart_controller`.

1. **Setup and connect** — connect through the controller, discover the output root, and let the workflow create the experiment folder.
2. **Set origin** — set the current microscope position as `(0, 0, 0)`.
3. **Jobs** — capture the overview and target states.
4. **Initial positions** — ask the microscope for scan-field positions.
5. **Focus** — pick focus points in an interactive figure (points already placed in LAS X are pre-filled), press **Measure focus** to autofocus at each one, and inspect the fitted z surface as a heatmap in the same figure.
6. **Overview** — acquire one image per position, then browse them as one zoomable map with every tile at its real stage position and per-channel colour / brightness / contrast controls.
7. **Discover targets** — segment the overviews, then gate interactively: put any measured feature on the plot axes, threshold with sliders or draw a lasso, and hover a point to see that cell's image crop.
8. **Acquire targets + summary** — type how many to acquire; a random sample of the gate is re-imaged and reviewed as overview/target image pairs at the same physical scale, then the run report is written.

## Entry Point

Open `zmart_microscopy_v4.ipynb`. The notebook is the operator UI; implementation lives in `workflow/`. All four review widgets update live while the microscope works — tiles, focus points, and image pairs appear the moment they exist.

`zmart_microscopy_v4_react.ipynb` is the same run with the widgets as React apps inside the cells (via `anywidget`): the browser UI streams in real time and its buttons drive the kernel, which drives the hardware through the same gated paths. It needs only the `anywidget` package — React itself ships inside the repository (the official MIT-licensed build), so both notebooks work fully offline.

The same run also exists as a plain browser page — no Jupyter, no code on
screen: `python run_webapp.py --demo` starts it against a simulated
microscope (see `workflow/webapp/README.md`), and on the microscope PC
`python run_webapp.py --analysis-repo ...` drives the real one. The
server is Python standard library only.

The setup cell expects a checkout of
[`smart-analysis`](https://github.com/thomdehoog/smart-analysis) on its `v4-engine`
branch at `ANALYSIS_REPO`. Before connecting to LAS X it registers the external
target-acquisition pipeline and runs a 64x64 blank tile through its Cellpose
worker. This fails early when the analysis repository, declared worker conda
environment, Cellpose model, or GPU setup is unavailable; on success the worker
remains warm for the acquired overviews.

## Layout

- `_bootstrap.py` — adds `zmart_drivers/leica/stellaris5_y42h93/`, the target-acquisition directory, and the repo root to `sys.path` so the notebook can import driver registration, shared packages, and workflow code.
- `run_webapp.py` — establishes those package paths, then launches the plain-browser UI; live mode registers the adapter before connecting, while demo mode imports no driver.
- `workflow/` — public surface for the controller-only workflow plus internal modules with leading underscore.
- `tests/` — workflow unit tests (offline; no microscope or vendor software).

## Tests

Offline workflow unit tests — no microscope, no vendor software. Run from the
repo root:

```powershell
python -m pytest -q workflows/target_acquisition/tests
```

That suite includes an end-to-end run of BOTH notebooks: every code cell
executes in order against a simulated stage and synthetic sample, and the
operator's button presses are scripted between cells. If a notebook cell
breaks, this is the test that says so — no microscope needed:

```powershell
python -m pytest -q workflows/target_acquisition/tests/test_notebooks_run_end_to_end.py
```

## Output

Unless the workflow supplies an explicit root, Leica discovers a
`ZMART-microscopy/` folder beside the LAS X native AutoSave base folder. The
workflow creates and organizes:

```text
ZMART-microscopy/<experiment>_<hash>/<acquisition_type>/data/
```

The workflow derives `K/M/G/P/V` from each `get_info()["tile_positions"]`
entry when present; otherwise it counts `P` from zero and uses zero for the
other missing indices. The Leica save helper names each returned plane:

```text
<acquisition_type>_<position-hash>_K00_M000000_G000000_P000000_V00_T000000_C00_Z00000.ome.tiff
```

The driver owns the per-position hash and filename. The workflow moves the
file unchanged into `data/` and returns the full final filenames through each
record's `images` and `planes[*].path` fields.
