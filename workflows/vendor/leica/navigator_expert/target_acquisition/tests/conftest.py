"""Add required paths so workflow and _shared imports resolve."""
import sys
from pathlib import Path

# workflow/ lives at notebooks/workflow/; its __init__.py adds these paths
# at import time, but we need them before that for _shared imports.
_NOTEBOOKS = Path(__file__).resolve().parents[2]   # .../notebooks/
_LEICA = _NOTEBOOKS.parents[1]                     # .../leica/
_VENDOR = _LEICA.parent                            # .../vendor/

for p in [str(_NOTEBOOKS), str(_LEICA), str(_VENDOR)]:
    if p not in sys.path:
        sys.path.insert(0, p)
