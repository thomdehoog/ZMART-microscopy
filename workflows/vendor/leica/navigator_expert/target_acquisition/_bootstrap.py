"""Notebook entry point. Importing this module:
  1. Adds necessary paths to sys.path so the workflow package, the
     driver, algorithms, and _shared are all importable.
  2. Re-exports `Config` (workflow) and `Path` (pathlib), so the
     notebook cell is one import line + `cfg = Config(...)`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parents[4]

# navigator_expert.driver needs controller/vendor/leica/ on sys.path
_VENDOR_LEICA = _REPO_ROOT / "controller" / "vendor" / "leica"
if str(_VENDOR_LEICA) not in sys.path:
    sys.path.insert(0, str(_VENDOR_LEICA))

# _shared.output_layout needs controller/vendor/ on sys.path
_VENDOR = _VENDOR_LEICA.parent
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

# algorithms/ lives at repo root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Pre-load navigator_expert.driver so its package identity is
# established before workflow modules trigger the same import.
import navigator_expert.driver  # noqa: E402,F401

# workflow/ is a sibling package to this bootstrap
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from workflow import Config  # noqa: E402

__all__ = ["Config", "Path"]
