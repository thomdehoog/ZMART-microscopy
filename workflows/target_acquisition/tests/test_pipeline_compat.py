"""Compatibility guard for the old pipeline package name."""

from __future__ import annotations


def test_pipeline_top_level_submodules_alias_workflow():
    import pipeline.steps as pipeline_steps
    import workflow.steps as workflow_steps

    assert pipeline_steps is workflow_steps
    assert pipeline_steps.connect is workflow_steps.connect
