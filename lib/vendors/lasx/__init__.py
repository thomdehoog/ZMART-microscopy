"""
vendors.lasx — Leica LAS X backend for the smart-microscopy framework.

Importing this package registers the LAS X backends with the generic layer:
  - ``"lasx"`` connector   → ``microscope_connector`` registry
  - ``"lasx"`` experiment  → ``initialize_experiment`` registry

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

# Each import triggers self-registration with the corresponding generic
# registry.  try/except allows backends to be added incrementally.

try:
    from .connector import LasXConnector           # noqa: F401
except ImportError:
    pass

try:
    from .inspect import LasXExperimentBackend      # noqa: F401
except ImportError:
    pass
