# Target Acquisition

Pick cells from a low-magnification overview, re-image each at the high-magnification objective. Six numbered steps, each a single procedure function called from the operator notebook:

1. **Preflight** — establish output directory, capture console logs, fingerprint the run.
2. **Template** — read the scan field and stage envelope; archive the live LRP and strip non-essential attachments.
3. **Focus** — run the AF job at focus markers and fit a z-wide surface.
4. **Overview** — acquire the overview scan; cellpose-segment each tile; populate per-tile cell counts.
5. **Selection + Target** — operator chooses a selection mode; pipeline switches objective once (via job selection — the job binds the objective) and acquires each pick with per-pick failure isolation.
6. **Summary** — write `run_summary.json` and the final figures.

## Entry Point

Open `smart_microscopy_v3.2.ipynb`. The notebook is the operator UI; implementation lives in `pipeline/`.

## Layout

- `_bootstrap.py` — adds `drivers/leica/stellaris5_y42h93/`, `microscopes/`, and the repo root to `sys.path` so the notebook can import the driver, calibration, shared packages, and workflow code.
- `pipeline/` — public surface (`Config`, `Context`, the step functions, visualization helpers) plus internal modules with leading underscore.
- `tests/` — pipeline unit tests. Run from the repo root with `pytest workflows/target_acquisition/tests/`.

## Output

Acquisition artifacts write to the operator-selected `media_path/smart/` tree (see `shared/output_layout/`), not into this package.
