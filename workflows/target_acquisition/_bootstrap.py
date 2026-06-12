"""Notebook entry point. Importing this module:
1. Adds necessary paths to sys.path so the pipeline package, the
   driver and shared packages are all importable.
2. Re-exports `Config` (pipeline) and `Path` (pathlib), so the
   notebook cell is one import line + `cfg = Config(...)`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parents[1]
_MICROSCOPES_ROOT = _REPO_ROOT / "microscopes"

# navigator_expert needs microscopes/drivers/vendor/leica/ on sys.path
_VENDOR_LEICA = _MICROSCOPES_ROOT / "driver" / "vendor" / "leica"
if str(_VENDOR_LEICA) not in sys.path:
    sys.path.insert(0, str(_VENDOR_LEICA))

# calibration/ and shared/ live under microscopes/
if str(_MICROSCOPES_ROOT) not in sys.path:
    sys.path.insert(0, str(_MICROSCOPES_ROOT))

# workflows/ lives at repo root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Pre-load navigator_expert so its package identity is
# established before pipeline modules trigger the same import.
import navigator_expert  # noqa: E402,F401

# pipeline/ is a sibling package to this bootstrap
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from pipeline import Config  # noqa: E402

__all__ = ["Config", "Path"]
