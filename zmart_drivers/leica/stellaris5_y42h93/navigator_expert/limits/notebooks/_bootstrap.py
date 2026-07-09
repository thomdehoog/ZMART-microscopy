"""Import bootstrap only. Must never choose runtime write paths."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[6]
_DRIVER_PARENT = Path(__file__).resolve().parents[3]  # zmart_drivers/leica/stellaris5_y42h93

# This notebook folder, so a notebook can archive its own executed copy into the
# machine snapshot (a read path, not a runtime write path).
NOTEBOOKS_DIR = Path(__file__).resolve().parent
NOTEBOOK_PATH = NOTEBOOKS_DIR / "set_stage_limits.ipynb"

for _path in (_REPO_ROOT, _DRIVER_PARENT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
