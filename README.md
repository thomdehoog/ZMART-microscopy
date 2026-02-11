# smart-microscopy

Manufacturer-agnostic tools for microscope experiment inspection and analysis.

Currently supports **Leica LAS X**. Designed so that adding new vendors
(Zeiss ZEN, Nikon NIS-Elements, ...) requires only new backend files — the
generic layer and notebooks never change.

## Quick start

Open a notebook in `notebooks/` and run:

```python
from initialize_experiment import initialize_experiment

data = initialize_experiment("lasx", input="auto", verbose=1)
```

## Repository layout

```
smart-microscopy/
├── notebooks/              user-facing entry points (Jupyter)
│   ├── inspect_template.ipynb
│   └── inspect_template_api.ipynb
└── lib/                    all Python modules
    ├── initialize_experiment.py   experiment initialization (ABC + factory)
    ├── microscope_connector.py    API connection (ABC + factory)
    ├── vendors/
    │   └── lasx/           Leica LAS X backend
    └── utils/              shared utilities
```

See `PROJECT_STRUCTURE.md` for the full architecture description.

## Systems

| System     | Generic entry point              | What it does                                      |
|------------|----------------------------------|---------------------------------------------------|
| Connector  | `initialize_api("lasx")`         | Connect to the microscope API                     |
| Experiment | `initialize_experiment("lasx")`  | Parse, enrich, and visualise a scanning template  |
| Analysis   | `initialize_analysis("lasx")`    | *(future)* Analyse acquired experiment data       |

## Requirements

- Python >= 3.9
- matplotlib, numpy
- qtpy *(optional, for interactive folder picker)*
- Leica LAS X with API server *(optional, for live enrichment / input="auto")*
