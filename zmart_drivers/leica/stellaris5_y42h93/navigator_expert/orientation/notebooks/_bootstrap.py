"""Notebook imports, source path, and save-checkpoint synchronization."""

import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[6]
_DRIVER_PARENT = Path(__file__).resolve().parents[3]  # zmart_drivers/leica/stellaris5_y42h93

# This notebook folder, so a notebook can archive its own executed copy into the
# machine snapshot (a read path, not a runtime write path).
NOTEBOOKS_DIR = Path(__file__).resolve().parent
NOTEBOOK_PATH = NOTEBOOKS_DIR / "set_orientation.ipynb"

for _path in (_REPO_ROOT, _DRIVER_PARENT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def request_notebook_save() -> int:
    """Request a browser checkpoint and return the prior on-disk version.

    VS Code does not expose its editor save command to notebook output
    JavaScript, so its user must press Ctrl+S before running the adopt cell.
    """
    from IPython.display import Javascript, Markdown, display

    previous_mtime_ns = NOTEBOOK_PATH.stat().st_mtime_ns
    display(
        Markdown(
            "**Save this notebook now (`Ctrl+S`), then run the next cell.** "
            "Browser-based Jupyter may save it automatically; VS Code requires "
            "the manual save."
        )
    )
    display(
        Javascript(
            """
(async () => {
  if (window.Jupyter && window.Jupyter.notebook) {
    await window.Jupyter.notebook.save_checkpoint();
    return;
  }
  if (window.jupyterapp && window.jupyterapp.commands) {
    await window.jupyterapp.commands.execute('docmanager:save');
    return;
  }
  throw new Error('This notebook frontend does not expose a save command.');
})();
"""
        )
    )
    return previous_mtime_ns


def _has_saved_measurement_output() -> bool:
    try:
        notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(
        cell.get("cell_type") == "code"
        and "session = wf.measure(session)" in "".join(cell.get("source", []))
        and cell.get("execution_count") is not None
        and bool(cell.get("outputs"))
        for cell in notebook.get("cells", [])
    )


def wait_for_notebook_save(previous_mtime_ns: int, timeout_s: float = 60.0) -> Path:
    """Wait for a newer checkpoint containing the executed measurement."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if NOTEBOOK_PATH.stat().st_mtime_ns > previous_mtime_ns and _has_saved_measurement_output():
            return NOTEBOOK_PATH
        time.sleep(0.1)
    raise RuntimeError(
        f"the executed measurement was not saved within {timeout_s:g} seconds; "
        f"save {NOTEBOOK_PATH} with Ctrl+S and rerun only this save/adopt cell"
    )
