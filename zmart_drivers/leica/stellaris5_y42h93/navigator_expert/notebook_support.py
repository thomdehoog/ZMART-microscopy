"""Shared save-checkpoint and archive behavior for operator notebooks."""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

_T = TypeVar("_T")


@dataclass(frozen=True)
class NotebookCheckpoint:
    """Wait for a saved notebook containing the required executed cells."""

    path: Path
    required_code: tuple[str, ...] = ()

    def request_save(self) -> int:
        """Request a browser checkpoint and return the prior disk version."""
        from IPython.display import Javascript, Markdown, display

        previous_mtime_ns = self.path.stat().st_mtime_ns
        display(
            Markdown(
                "**Save this notebook now (`Ctrl+S`), then run the next cell.** "
                "Browser-based Jupyter may save automatically; VS Code requires "
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

    def _contains_required_outputs(self) -> bool:
        try:
            notebook = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        code_cells = [cell for cell in notebook.get("cells", []) if cell.get("cell_type") == "code"]
        return all(
            any(
                marker in "".join(cell.get("source", []))
                and cell.get("execution_count") is not None
                and bool(cell.get("outputs"))
                for cell in code_cells
            )
            for marker in self.required_code
        )

    def wait_for_save(self, previous_mtime_ns: int, timeout_s: float = 60.0) -> Path:
        """Wait for a newer checkpoint containing every required output."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if (
                self.path.stat().st_mtime_ns > previous_mtime_ns
                and self._contains_required_outputs()
            ):
                return self.path
            time.sleep(0.1)
        raise RuntimeError(
            f"the completed notebook was not saved within {timeout_s:g} seconds; "
            f"save {self.path} with Ctrl+S and rerun only the final save cell"
        )

    def save_and_adopt(self, adopter: Callable[[Path], _T]) -> _T:
        """Save the completed notebook, validate its checkpoint, then adopt."""
        previous_mtime_ns = self.request_save()
        return adopter(self.wait_for_save(previous_mtime_ns))


def archive_notebook(
    notebook_path: str | Path,
    root: str | Path,
    *,
    filename: str | None = None,
    directory: str | Path = Path("data") / "notebook",
) -> Path:
    """Atomically archive one notebook under a relative session directory."""
    source = Path(notebook_path)
    relative_dir = Path(directory)
    if relative_dir.is_absolute() or ".." in relative_dir.parts:
        raise ValueError(f"notebook archive directory must stay within the session: {directory}")
    notebook_dir = Path(root) / relative_dir
    notebook_dir.mkdir(parents=True, exist_ok=True)
    destination = notebook_dir / (filename or source.name)
    # Keep an interrupted copy visible and self-explanatory; do not leave a
    # hidden dot-file in an operator session even transiently.
    temporary = destination.with_name(f"{destination.name}.saving")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def archive_notebooks(
    notebook_paths: Iterable[str | Path],
    root: str | Path,
) -> list[Path]:
    """Archive notebooks using the shared ``data/notebook`` convention."""
    return [archive_notebook(path, root) for path in notebook_paths]
