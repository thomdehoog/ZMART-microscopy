"""Structural guard for the controller-only v4 notebook.

Not an execution test (the middle steps need hardware + cellpose). It pins the
notebook to the real API: valid nbformat, every code cell parses, and every
``pipeline.<name>`` the notebook calls is actually exported by ``pipeline``.
This catches the notebook drifting out of sync with the package surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")

import pipeline  # noqa: E402

_NB_PATH = Path(__file__).resolve().parents[1] / "zmart_microscopy_v4.ipynb"


def _load():
    return nbformat.read(str(_NB_PATH), as_version=4)


def test_notebook_is_valid():
    nb = _load()
    nbformat.validate(nb)
    assert nb.cells, "notebook has no cells"


def _code_sources(nb):
    return [c.source for c in nb.cells if c.cell_type == "code"]


def test_all_code_cells_parse():
    nb = _load()
    for src in _code_sources(nb):
        ast.parse(src)  # SyntaxError fails the test with the cell content


def test_pipeline_attributes_used_are_exported():
    """Every ``pipeline.<attr>`` accessed in the notebook is in pipeline.__all__."""
    nb = _load()
    used: set[str] = set()
    for src in _code_sources(nb):
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "pipeline"
            ):
                used.add(node.attr)
    # `__all__` is a legitimate dunder access in the setup cell.
    used.discard("__all__")
    exported = set(pipeline.__all__)
    missing = used - exported
    assert not missing, f"notebook calls pipeline.{sorted(missing)} not in pipeline.__all__"
    # sanity: the notebook actually drives the pipeline
    assert {"connect", "run_overview", "discover_targets", "acquire_targets"} <= used


def test_notebook_stays_controller_only():
    """No `import navigator_expert` as a bare driver call in the operator flow.

    The adapter import is allowed (it registers the instrument); what must not
    appear is a direct `navigator_expert.<op>()` / `drv.` acquisition call.
    """
    nb = _load()
    joined = "\n".join(_code_sources(nb))
    assert "navigator_expert.zmart_adapter" in joined  # registration import present
    # no direct driver acquisition/motion calls
    for forbidden in ("drv.acquire", "drv.save", "drv.move_", "navigator_expert.acquire"):
        assert forbidden not in joined, f"notebook uses driver call {forbidden!r}"
