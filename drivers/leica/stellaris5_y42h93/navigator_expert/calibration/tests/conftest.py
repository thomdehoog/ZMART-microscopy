"""Pytest import-path setup for Leica Navigator Expert calibration tests."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[6]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DRIVER_PARENT = Path(__file__).resolve().parents[3]  # drivers/leica/stellaris5_y42h93
if str(_DRIVER_PARENT) not in sys.path:
    sys.path.insert(0, str(_DRIVER_PARENT))
