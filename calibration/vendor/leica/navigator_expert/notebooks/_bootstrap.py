"""Import bootstrap only. Must never choose runtime write paths."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[5]
_VENDOR_LEICA = _REPO_ROOT / "driver" / "vendor" / "leica"

for _path in (_REPO_ROOT, _VENDOR_LEICA):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
