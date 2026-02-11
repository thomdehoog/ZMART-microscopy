"""
vendors.lasx — Leica LAS X backend for the smart-microscopy framework.

Importing this package registers the LAS X backends with the generic layer:
  - ``"lasx"`` connector   → ``microscope_connector`` registry
  - ``"lasx"`` inspection  → ``microscope_inspect`` registry

Submodules
----------
    connector            LasXConnector (API connection)
    inspect              LasXInspectionBackend (template inspection pipeline)
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
    from .inspect import LasXInspectionBackend     # noqa: F401
except ImportError:
    pass
