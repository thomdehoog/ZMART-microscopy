# smart-microscopy — Project Structure

## Repository layout

```
smart-microscopy/
│
├── README.md
├── .gitignore
├── PROJECT_STRUCTURE.md
│
├── notebooks/                                  ← user-facing entry points
│   ├── inspect_template.ipynb
│   ├── inspect_template_api.ipynb
│   └── analyze_experiment.ipynb                (future)
│
└── lib/                                        ← all Python modules
    │
    │  ── Generic layer (manufacturer-agnostic) ─────────────
    │
    ├── microscope_connector.py                 ABC + initialize_api()
    ├── initialize_experiment.py                ABC + initialize_experiment()
    ├── microscope_analysis.py                  ABC + initialize_analysis()   (future)
    │
    │  ── Vendor backends ───────────────────────────────────
    │
    ├── vendors/
    │   ├── __init__.py                         (empty — makes it a package)
    │   │
    │   └── lasx/                               Leica LAS X backend
    │       ├── __init__.py                     imports & registers all backends
    │       ├── connector.py                    LasXConnector
    │       ├── inspect.py                      LasXExperimentBackend
    │       ├── parser.py                       XML / LRP / RGN parser
    │       ├── api_enrichment.py               live API enrichment
    │       ├── offline_enrichment.py           OME-TIFF file enrichment
    │       ├── autofocus.py                    LAS X autofocus hardware control
    │       ├── visualizer.py                   tile layout visualiser
    │       └── visualizer_extended.py          z-surface, image overlays
    │
    │  ── Shared utilities ──────────────────────────────────
    │
    └── utils/
        ├── __init__.py
        ├── acquisition_path_planning.py        path planning and ordering
        └── z_interpolation.py                  z-surface interpolation
```


## Why this layout works

**The `lasx_` prefix is gone inside the folder** — the folder *is* the
namespace.  `vendors.lasx.parser` is unambiguous; calling it
`vendors.lasx.lasx_parser` would be redundant.

**One `sys.path` line** in each notebook is all you need:

```python
sys.path.insert(0, str((Path("..") / "lib").resolve()))
```

Then all imports resolve naturally:

```python
from initialize_experiment import initialize_experiment      # generic
from vendors.lasx.parser import parse_template               # vendor-specific
from utils.z_interpolation import interpolate_z_surface      # utility
```


## How auto-import works

When you call `initialize_experiment("lasx")`, the generic layer:

1. Checks the registry — not found yet
2. Tries `import vendors.lasx` (convention: `vendors.{backend_key}`)
3. `vendors/lasx/__init__.py` runs, which imports `connector.py` and
   `inspect.py`, triggering self-registration
4. Registry now has `"lasx"` — proceeds with the pipeline


## `vendors/lasx/__init__.py`

```python
"""
vendors.lasx — Leica LAS X backend for the smart-microscopy framework.

Importing this package registers the LAS X backends with the generic layer:
  - "lasx" connector   → microscope_connector registry
  - "lasx" experiment  → initialize_experiment registry

Submodules
----------
    connector            LasXConnector (API connection)
    inspect              LasXExperimentBackend (experiment initialization pipeline)
    parser               XML / LRP / RGN template parser
    api_enrichment       live API enrichment
    offline_enrichment   OME-TIFF file-based enrichment
    autofocus            LAS X autofocus hardware control
    visualizer           tile layout matplotlib visualiser
    visualizer_extended  z-surface, image overlay, AF path visualiser
"""

# Importing these triggers self-registration with the generic registries.
from .connector import LasXConnector           # noqa: F401
from .inspect import LasXExperimentBackend     # noqa: F401
```


## Internal imports (within the vendor package)

Files inside `vendors/lasx/` use **relative imports** to reference
each other.  This means they don't depend on where `lib/` sits on
`sys.path`:

```python
# vendors/lasx/inspect.py
from .parser import parse_template
from .api_enrichment import enrich_with_api_data
from .offline_enrichment import enrich_offline
from .visualizer import visualize
```

Files that reference the **generic layer** use absolute imports:

```python
# vendors/lasx/inspect.py
from initialize_experiment import ExperimentBackend, register_backend
```

```python
# vendors/lasx/connector.py
from microscope_connector import MicroscopeConnector, register_backend
```


## Three systems, same pattern

```
System              Generic layer                  LAS X backend                    Entry point
─────────────────── ────────────────────────────── ──────────────────────────────── ──────────────────────────────
Connector           microscope_connector.py        vendors/lasx/connector.py        initialize_api("lasx")
Experiment          initialize_experiment.py       vendors/lasx/inspect.py          initialize_experiment("lasx")
Analysis (future)   microscope_analysis.py         vendors/lasx/analysis.py         initialize_analysis("lasx")
```

Adding a new vendor (e.g. Zeiss ZEN):

```
vendors/
├── lasx/       ← existing
└── zen/        ← new folder, same structure
    ├── __init__.py
    ├── connector.py
    ├── inspect.py
    ├── parser.py
    └── ...
```

The generic layer and notebooks never change.


## Call chain

```
notebook
  └─ initialize_experiment("lasx", input="auto")        # initialize_experiment.py
       ├─ auto-import: import vendors.lasx               # triggers __init__.py
       │    ├─ from .connector import LasXConnector       # registers with connector
       │    └─ from .inspect import LasXExperimentBackend # registers with experiment
       ├─ LasXExperimentBackend.resolve_input_auto()     # saves template via API
       ├─ LasXExperimentBackend.find_template_files()    # finds .xml, .lrp, .rgn
       ├─ LasXExperimentBackend.parse()
       │    └─ vendors.lasx.parser.parse_template()      # XML/LRP/RGN → data dict
       ├─ resolve enrich mode (auto → api / files / none)
       ├─ LasXExperimentBackend.enrich_from_api()
       │    └─ vendors.lasx.api_enrichment.enrich_with_api_data()
       ├─ print summary
       └─ LasXExperimentBackend.visualize()
            └─ vendors.lasx.visualizer.visualize()       # matplotlib figure
```


## Migration from current flat layout

```
Old name (flat)              → New location                         → New import
──────────────────────────── ─ ───────────────────────────────────  ──────────────────────────────────
microscope_connector.py      → lib/microscope_connector.py           (unchanged)
microscope_inspect.py        → lib/initialize_experiment.py          from initialize_experiment import ...
lasx_connector.py            → lib/vendors/lasx/connector.py         from vendors.lasx.connector import ...
lasx_inspect.py              → lib/vendors/lasx/inspect.py           from vendors.lasx.inspect import ...
lasx_parser.py               → lib/vendors/lasx/parser.py            from vendors.lasx.parser import ...
lasx_api_enrichment.py       → lib/vendors/lasx/api_enrichment.py    from vendors.lasx.api_enrichment import ...
lasx_offline_enrichment.py   → lib/vendors/lasx/offline_enrichment.py
lasx_visualizer.py           → lib/vendors/lasx/visualizer.py
lasx_visualizer_extended.py  → lib/vendors/lasx/visualizer_extended.py
autofocus_utils.py           → lib/utils/acquisition_path_planning.py
z_interpolation.py           → lib/utils/z_interpolation.py
lasx_inspect_runner.py       → DELETED (absorbed into initialize_experiment.py + vendors/lasx/inspect.py)
```
