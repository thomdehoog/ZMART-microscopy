"""Structural guard for the React edition of the v4 notebook.

Same idea as test_v4_notebook: not an execution test — it pins the
notebook to the real API surface so the cells cannot silently drift away
from the packages they drive.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")
pytest.importorskip("anywidget")

import workflow  # noqa: E402
from workflow import react as wreact  # noqa: E402

_NB_PATH = Path(__file__).resolve().parents[1] / "zmart_microscopy_v4_react.ipynb"


def _load():
    return nbformat.read(str(_NB_PATH), as_version=4)


def _code_sources(nb):
    return [c.source for c in nb.cells if c.cell_type == "code"]


def test_notebook_is_valid_and_parses():
    nb = _load()
    nbformat.validate(nb)
    for src in _code_sources(nb):
        ast.parse(src)


def test_widget_attributes_used_are_exported():
    """Every ``wreact.<attr>`` / ``workflow.<attr>`` the notebook calls exists."""
    nb = _load()
    used = {"workflow": set(), "wreact": set()}
    for src in _code_sources(nb):
        for node in ast.walk(ast.parse(src)):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in used
            ):
                used[node.value.id].add(node.attr)
    missing_wf = {n for n in used["workflow"] if n != "react"} - set(workflow.__all__)
    missing_re = used["wreact"] - set(wreact.__all__)
    assert not missing_wf, f"notebook calls workflow.{sorted(missing_wf)} not exported"
    assert not missing_re, f"notebook calls wreact.{sorted(missing_re)} not exported"
    # sanity: the notebook actually drives the React widgets
    assert {"view_overview", "pick_focus_points", "explore_targets", "acquire_gallery"} <= used[
        "wreact"
    ]


def test_react_notebook_runs_the_same_hardware_flow():
    """The React edition must not drop any hardware step of the v4 run."""
    joined = "\n".join(_code_sources(_load()))
    for step in (
        "set_origin",
        "get_state",
        "start_calibration_check",
        "finish_calibration_check",
        "run_overview",
        "discover_targets",
        "write_run_report",
        "disconnect",
    ):
        assert step in joined, f"the React notebook lost the {step} step"
    # and it must not need the matplotlib interactive backend
    assert "run_line_magic" not in joined


def test_react_notebook_is_thin_controller_orchestration():
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
        assert call in joined, f"React notebook no longer demonstrates {call}"
