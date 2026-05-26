"""Add required paths so workflow, driver, and shared imports resolve."""
import sys
from pathlib import Path

_TARGET_ACQ = Path(__file__).resolve().parents[1]  # .../target_acquisition/
_REPO_ROOT = _TARGET_ACQ.parents[4]                # .../smart-microscopy/
_VENDOR_LEICA = _REPO_ROOT / "controller" / "vendor" / "leica"

for p in [str(_VENDOR_LEICA), str(_REPO_ROOT), str(_TARGET_ACQ)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Pre-load navigator_expert.driver so its package identity is
# established before pipeline modules trigger the same import.
import navigator_expert.driver  # noqa: E402,F401
