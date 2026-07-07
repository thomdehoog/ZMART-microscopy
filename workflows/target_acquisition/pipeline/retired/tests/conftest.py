"""Path setup for the retired (driver-coupled) pipeline tests.

Mirrors ``target_acquisition/tests/conftest.py`` so the retired suite runs
standalone (``pytest pipeline/retired/tests/``). These tests exercise the
pre-controller flow and still import ``navigator_expert``.
"""

import sys
from pathlib import Path

_TARGET_ACQ = Path(__file__).resolve().parents[3]  # .../target_acquisition/
_REPO_ROOT = _TARGET_ACQ.parents[1]  # .../zmart-microscopy/
_DRIVER_PARENT = _REPO_ROOT / "zmart_drivers" / "leica" / "stellaris5_y42h93"

for p in [str(_DRIVER_PARENT), str(_REPO_ROOT), str(_TARGET_ACQ)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Pre-load navigator_expert so its package identity is
# established before pipeline modules trigger the same import.
import navigator_expert  # noqa: E402,F401
