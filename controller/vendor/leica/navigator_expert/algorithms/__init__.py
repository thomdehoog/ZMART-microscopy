# Compatibility shim. Prefer top-level: from algorithms import ...
import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = str(_Path(__file__).resolve().parents[5])
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)

from algorithms import *  # noqa: F401,F403
from algorithms import __all__  # noqa: F401
