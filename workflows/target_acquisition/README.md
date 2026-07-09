# Target Acquisition

Pick cells from a low-magnification overview, re-image each at the high-magnification objective. The operator notebook drives the microscope through `zmart_controller`.

1. **Setup and connect** — connect through the controller and ask the microscope for the run root.
2. **Set origin** — set the current microscope position as `(0, 0, 0)`.
3. **Jobs** — capture the overview and target states.
4. **Initial positions** — ask the microscope for scan-field positions.
5. **Focus** — ask the microscope for focus points and fit a z surface.
6. **Overview** — acquire overviews and discover targets.
7. **Targets + summary** — acquire target images and write the run report.

## Entry Point

Open `zmart_microscopy_v4.ipynb`. The notebook is the operator UI; implementation lives in `workflow/`.

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
