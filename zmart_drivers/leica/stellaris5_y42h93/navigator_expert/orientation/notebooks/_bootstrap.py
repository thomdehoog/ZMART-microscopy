"""Notebook imports, source path, and save-checkpoint synchronization."""

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
    """Ask the active Jupyter frontend to save and return the prior file version."""
    from IPython.display import Javascript, display

    previous_mtime_ns = NOTEBOOK_PATH.stat().st_mtime_ns
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


def wait_for_notebook_save(previous_mtime_ns: int, timeout_s: float = 15.0) -> Path:
    """Wait until the frontend checkpoint is on disk, or refuse adoption."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if NOTEBOOK_PATH.stat().st_mtime_ns > previous_mtime_ns:
            return NOTEBOOK_PATH
        time.sleep(0.1)
    raise RuntimeError(
        f"notebook was not saved within {timeout_s:g} seconds; save {NOTEBOOK_PATH} "
        "and run the save/adopt cells again"
    )
