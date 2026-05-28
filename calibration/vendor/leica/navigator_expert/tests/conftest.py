"""Pytest import-path setup for Leica Navigator Expert calibration tests."""

import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_VENDOR_LEICA = _REPO_ROOT / "driver" / "vendor" / "leica"
if str(_VENDOR_LEICA) not in sys.path:
    sys.path.insert(0, str(_VENDOR_LEICA))
