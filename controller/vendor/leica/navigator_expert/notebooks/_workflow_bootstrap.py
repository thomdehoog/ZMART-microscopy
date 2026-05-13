"""Notebook entry point: hide all setup behind a single import.

The operator-facing notebook does only:

    from _workflow_bootstrap import Config, Path
    cfg = Config(...)

This module:
  1. Locates the workflow/ package and adds its parent to sys.path,
     regardless of which directory Jupyter was launched from.
  2. Re-exports `Config` (from workflow) and `Path` (from pathlib) so
     the operator doesn't see any plumbing imports.

Resolution order for the workflow/ package (first match wins):
  1. This module's directory (sibling to workflow/) -- the normal case
     when Jupyter opens the notebook in place.
  2. cwd / controller/vendor/leica/navigator_expert/notebooks -- when
     launched from the smart-microscopy repo root.
  3. cwd                  -- when launched from the notebooks/ dir.
  4. cwd / notebooks      -- when launched from navigator_expert/.
  5. cwd.parent / notebooks -- one common sibling layout.

If none contain `workflow/__init__.py`, raise so the operator sees a
clear error instead of a confusing ModuleNotFoundError later.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _add_workflow_to_sys_path() -> Path:
    here = Path(__file__).parent.resolve()
    cwd = Path.cwd()
    candidates = [
        here,
        cwd / "controller/vendor/leica/navigator_expert/notebooks",
        cwd,
        cwd / "notebooks",
        cwd.parent / "notebooks",
    ]
    for candidate in candidates:
        if (candidate / "workflow" / "__init__.py").exists():
            resolved = str(candidate.resolve())
            if resolved not in sys.path:
                sys.path.insert(0, resolved)
            return candidate
    raise RuntimeError(
        "Could not find notebooks/workflow/. Launch Jupyter from the "
        "smart-microscopy repo root, navigator_expert/, or "
        "navigator_expert/notebooks/."
    )


_add_workflow_to_sys_path()
del _add_workflow_to_sys_path

# Re-exports so the notebook never has to touch workflow internals or
# pathlib directly. `Path` is included because operators always use it
# for the analysis_repo argument.
from workflow import Config  # noqa: E402

__all__ = ["Config", "Path"]
