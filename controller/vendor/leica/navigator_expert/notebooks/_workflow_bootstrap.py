"""Side-effect import: add the workflow/ package to sys.path.

The notebook imports this module once at the top so `from workflow import ...`
resolves regardless of which directory Jupyter was launched from. The
operator-facing notebook stays clean -- one `import _workflow_bootstrap`
line, no inline path manipulation.

Resolution order (first match wins):
  1. The directory this module lives in (sibling to workflow/) -- the
     normal case when Jupyter opens the notebook in place.
  2. cwd / controller/vendor/leica/navigator_expert/notebooks -- when
     Jupyter is launched from the smart-microscopy repo root.
  3. cwd                  -- when launched from the notebooks/ dir.
  4. cwd / notebooks      -- when launched from navigator_expert/.
  5. cwd.parent / notebooks -- one common sibling layout.

If none of these contain `workflow/__init__.py`, raise so the operator
sees a clear error instead of a confusing ModuleNotFoundError later.
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
