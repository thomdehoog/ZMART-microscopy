"""Import bootstrap only. Must never choose runtime write paths."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[6]
_DRIVER_PARENT = Path(__file__).resolve().parents[3]  # drivers/leica/stellaris5_y42h93

for _path in (_REPO_ROOT, _DRIVER_PARENT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
