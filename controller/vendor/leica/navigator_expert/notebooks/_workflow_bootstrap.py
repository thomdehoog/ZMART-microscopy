"""Notebook entry point. Importing this module:
  1. Adds this file's directory to sys.path so `workflow/` (a sibling
     package) is importable.
  2. Re-exports `Config` (workflow) and `Path` (pathlib), so the
     notebook cell is one import line + `cfg = Config(...)`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from workflow import Config  # noqa: E402

__all__ = ["Config", "Path"]
