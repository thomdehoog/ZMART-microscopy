"""Pytest import-path setup for navigator_expert tests."""

import sys
from pathlib import Path

# Add vendor/leica/ to sys.path so `import navigator_expert.driver` works
# regardless of where pytest is invoked from.
_VENDOR_LEICA = Path(__file__).resolve().parents[2]
if str(_VENDOR_LEICA) not in sys.path:
    sys.path.insert(0, str(_VENDOR_LEICA))

# Add repo root to sys.path so `from shared...` imports resolve.
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Add target_acquisition dir so workflow tests imported from this suite
# can resolve `from pipeline...`.
_TARGET_ACQ = (
    _REPO_ROOT / "workflows" / "vendor" / "leica" /
    "navigator_expert" / "target_acquisition"
)
if str(_TARGET_ACQ) not in sys.path:
    sys.path.insert(0, str(_TARGET_ACQ))
