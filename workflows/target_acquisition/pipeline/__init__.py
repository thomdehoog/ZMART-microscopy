"""Compatibility import for the old ``pipeline`` package name."""

from __future__ import annotations

import importlib
import sys

_workflow = importlib.import_module("workflow")
__path__ = _workflow.__path__
__all__ = list(_workflow.__all__)

globals().update({name: getattr(_workflow, name) for name in __all__})

for _name in (
    "_capture_run",
    "_figsave",
    "_focus_run",
    "_focus_surface",
    "_geom",
    "_hijack",
    "_log_capture",
    "_mock_provider",
    "_save_queue",
    "_saved",
    "discovery",
    "steps",
    "viz",
):
    sys.modules[f"{__name__}.{_name}"] = importlib.import_module(f"workflow.{_name}")
