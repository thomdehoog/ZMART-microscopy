# Compatibility shim. Prefer top-level: from algorithms import ...
import importlib.util as _util
import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[5]
_REAL_PKG = _REPO_ROOT / "algorithms"

if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

_spec = _util.spec_from_file_location(
    "algorithms",
    str(_REAL_PKG / "__init__.py"),
    submodule_search_locations=[str(_REAL_PKG)],
)
_real = _util.module_from_spec(_spec)
_sys.modules["algorithms"] = _real
_spec.loader.exec_module(_real)

_sys.modules[__name__] = _real
