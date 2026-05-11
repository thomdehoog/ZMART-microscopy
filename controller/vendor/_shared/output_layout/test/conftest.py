"""Add controller/vendor/ to sys.path so `from _shared.output_layout import ...` resolves."""
import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[3]
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
