"""Structural guard for the controller-only v4 notebook.

Not an execution test (the middle steps need hardware + cellpose). It pins the
notebook to the real API: valid nbformat, every code cell parses, and every
``workflow.<name>`` the notebook calls is actually exported by the workflow package.
This catches the notebook drifting out of sync with the package surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")

import workflow  # noqa: E402

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


def test_setup_cell_runs_from_repo_root(monkeypatch):
    nb = _load()
    setup_cell = _code_sources(nb)[0]
    root = Path("/tmp/zmart-run")

    class FakeController:
        def __init__(self):
            self.procedures = []

        def run_procedure(self, procedure):
            self.procedures.append(procedure)
            return {"root": str(root)}

    class FakeEngine:
        def __init__(self):
            self.shutdown_calls = 0

        def shutdown(self):
            self.shutdown_calls += 1

    fake = FakeController()
    fake_engine = FakeEngine()
    monkeypatch.setattr(workflow, "connect", lambda vendor: fake)
    monkeypatch.setattr(workflow, "load_analysis_engine", lambda repo: fake_engine)
    monkeypatch.setattr(workflow, "preflight_analysis_engine", lambda engine: None)

    namespace = {}
    monkeypatch.chdir(_NB_PATH.parents[2])
    exec(compile(setup_cell, str(_NB_PATH), "exec"), namespace)
    assert namespace["zmart_controller"] is fake
    assert namespace["engine"] is fake_engine
    assert fake.procedures == [{"name": "get_root"}]
    assert namespace["ROOT"] == root


def test_workflow_attributes_used_are_exported():
    """Every ``workflow.<attr>`` accessed in the notebook is in workflow.__all__."""
    nb = _load()
    used: set[str] = set()
    for src in _code_sources(nb):
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "workflow"
            ):
                used.add(node.attr)
    # `__all__` is a legitimate dunder access in the setup cell.
    used.discard("__all__")
    exported = set(workflow.__all__)
    missing = used - exported
    assert not missing, f"notebook calls workflow.{sorted(missing)} not in workflow.__all__"
    # sanity: the notebook actually drives the workflow (acquisition goes
    # through the gallery widget, which wraps acquire_targets)
    assert {"connect", "run_overview", "discover_targets", "acquire_gallery"} <= used


def test_notebook_stays_controller_only():
    """The visible operator flow stays controller/workflow-only."""
    nb = _load()
    joined = "\n".join(_code_sources(nb))
    bootstrap = (_NB_PATH.parent / "_bootstrap.py").read_text(encoding="utf-8")
    assert "navigator_expert.zmart_adapter" in bootstrap  # registration import is hidden there
    assert "navigator_expert" not in joined
    # no direct driver acquisition/motion calls
    for forbidden in ("drv.acquire", "drv.save", "drv.move_", "navigator_expert.acquire"):
        assert forbidden not in joined, f"notebook uses driver call {forbidden!r}"


def test_notebook_is_thin_orchestration_and_teaches_the_session_lifecycle():
    """Keep implementation in workflow modules while showing controller use."""
    trees = [ast.parse(src) for src in _code_sources(_load())]
    implementation_nodes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    assert not any(
        isinstance(node, implementation_nodes) for tree in trees for node in ast.walk(tree)
    ), "operator notebooks must call tested modules, not define new implementation logic"

    joined = "\n".join(_code_sources(_load()))
    for call in (
        'workflow.connect("leica")',
        "zmart_controller.set_origin()",
        "zmart_controller.get_state()",
        'zmart_controller.run_procedure({"name": "get_positions"})',
        "zmart_controller.disconnect()",
    ):
        assert call in joined, f"notebook no longer demonstrates {call}"
