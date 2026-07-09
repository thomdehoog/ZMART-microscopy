"""Compatibility import for the old ``pipeline`` package name."""

from __future__ import annotations

import importlib

_workflow = importlib.import_module("workflow")
__path__ = _workflow.__path__
__all__ = list(_workflow.__all__)

globals().update({name: getattr(_workflow, name) for name in __all__})
