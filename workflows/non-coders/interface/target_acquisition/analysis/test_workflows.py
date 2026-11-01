"""Finding the analysis pipelines: named by the environment, or beside the installed engine."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from . import workflows


@pytest.fixture(autouse=True)
def _forget_what_was_loaded():
    workflows.step_module.cache_clear()
    yield
    workflows.step_module.cache_clear()


def test_without_the_variable_our_own_pipelines_are_used(monkeypatch):
    """In ZMART Microscopy the workflow finds the pipelines beside it, in non-coders/analysis."""
    monkeypatch.delenv(workflows.ENV, raising=False)
    assert workflows.workflows_root() == workflows.OUR_PIPELINES.resolve()
    for name in ("focus", "object_analysis_cellpose", "object_analysis_watershed", "reduce_dimensions"):
        assert workflows.pipeline_yaml(name).is_file(), name



def _a_checkout(root, folder="examples"):
    (root / folder / "focus" / "pipelines").mkdir(parents=True)
    (root / folder / "focus" / "pipelines" / "focus.yaml").write_text("steps: []\n")
    (root / folder / "object_analysis" / "steps").mkdir(parents=True)
    (root / folder / "object_analysis" / "steps" / "read_images.py").write_text("WHERE = 'the checkout'\n")
    return root


@pytest.mark.parametrize("folder", ["examples", "workflows"])
def test_the_environment_variable_names_the_checkout_or_its_folder_of_pipelines(tmp_path, monkeypatch, folder):
    """ZMART-analysis keeps them in ``examples`` from 0.6.0rc8 on, and in ``workflows`` before."""
    checkout = _a_checkout(tmp_path / "ZMART-analysis", folder)
    monkeypatch.setenv(workflows.ENV, str(checkout))
    assert workflows.workflows_root() == (checkout / folder).resolve()
    monkeypatch.setenv(workflows.ENV, str(checkout / folder))
    assert workflows.workflows_root() == (checkout / folder).resolve()
    assert workflows.pipeline_yaml("focus").name == "focus.yaml"
    assert workflows.step_module("object_analysis", "read_images").WHERE == "the checkout"


def test_a_folder_without_workflows_is_said_plainly(tmp_path, monkeypatch):
    monkeypatch.setenv(workflows.ENV, str(tmp_path))
    with pytest.raises(workflows.WorkflowsNotFound, match="holds no analysis pipelines"):
        workflows.workflows_root()

