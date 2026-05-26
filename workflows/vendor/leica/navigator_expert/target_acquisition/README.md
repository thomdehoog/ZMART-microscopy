# Target Acquisition

Leica Navigator Expert target-acquisition pipeline.

## Entry Point

Open `notebook.ipynb`. The notebook is the operator UI and should stay
thin; implementation code lives in `pipeline/`.

## Layout

- `_bootstrap.py` sets import paths for notebook execution.
- `pipeline/` contains the target-acquisition procedure and helpers.
- `tests/` contains pipeline unit tests.

Runtime acquisition output belongs in the operator-selected output
directory, not in this package.
