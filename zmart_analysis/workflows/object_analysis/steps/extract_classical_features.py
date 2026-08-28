"""object_analysis wrapper for shared classical feature extraction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "parts"))
from _features import run  # noqa: E402


METADATA = {
    "description": "Extract classical object features",
    "version": "1.0",
    "environment": "SMART--object_analysis--classical",
}
