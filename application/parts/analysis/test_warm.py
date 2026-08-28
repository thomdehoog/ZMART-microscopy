"""The warm analysis: one engine, registered once, shared by every pipeline."""

from __future__ import annotations

import pytest

from application.parts.analysis import warm


class _Engine:
    """A stand-in engine that answers immediately and counts what it was told."""

    def __init__(self, answers=None, failure=None):
        self.registered: list[tuple] = []
        self.submitted: list[tuple] = []
        self.stopped = 0
        self._answers = answers if answers is not None else {}
        self._failure = failure
        self._waiting: list[dict] = []

    def register(self, name, yaml_path):
        self.registered.append((name, yaml_path))

    def submit(self, name, data):
        self.submitted.append((name, data))
        if self._failure is None:  # a job that fails produces no result
            self._waiting.append(self._answers.get(name, {"ran": name}))

    def status(self, name):
        return {"failed": 1, "failures": [self._failure]} if self._failure else {}

    def results(self, name):
        out, self._waiting = self._waiting, []
        return out

    def shutdown(self):
        self.stopped += 1


def test_the_input_reaches_the_step_as_the_step_expects_it():
    """The engine wraps it; a caller that wrapped it too would bury it.

    A step reads its input from ``pipeline_data["input"]``, and the engine is
    what puts it there. Wrapped twice it arrives a level too deep and the step
    reports the input missing -- which is what happened, and only in a worker,
    where nothing in this repository could see it.
    """
    engine = _Engine()
    warm.Analysis(engine).run("focus", {"image_paths": ["a.tiff", "b.tiff"]})
    assert engine.submitted == [("focus", {"image_paths": ["a.tiff", "b.tiff"]})]


def test_a_pipeline_is_registered_once_however_often_it_runs():
    """Registering parses YAML and reads every step; doing it per job is waste."""
    engine = _Engine()
    analysis = warm.Analysis(engine)

    for _ in range(3):
        analysis.run("focus", {"image_paths": []})

    assert [name for name, _path in engine.registered] == ["focus"]
    assert len(engine.submitted) == 3


def test_two_pipelines_share_the_one_engine():
    """Object analysis is the next caller, and it needs nothing new here."""
    engine = _Engine()
    analysis = warm.Analysis(engine)

    analysis.run("focus", {"image_paths": []})
    analysis.run("object_analysis", {"image_paths": []})

    assert [name for name, _path in engine.registered] == ["focus", "object_analysis"]
    assert engine.registered[1][1].endswith("object_analysis.yaml")


def test_a_failed_pipeline_is_raised_and_not_answered_for():
    """A step that measures pixels has no sensible empty answer."""
    analysis = warm.Analysis(_Engine(failure="the worker died"))
    with pytest.raises(RuntimeError, match="the worker died"):
        analysis.run("focus", {"image_paths": []})


def test_a_pipeline_that_never_answers_gives_up_rather_than_hangs():
    """A page waiting forever on a hung worker is a page nobody can use."""

    class _Silent(_Engine):
        def results(self, name):
            return []

    analysis = warm.Analysis(_Silent())
    with pytest.raises(TimeoutError, match="did not answer"):
        analysis.run("focus", {"image_paths": []}, patience_s=0.0)


def test_the_workers_are_let_go_and_can_start_again():
    engine = _Engine()
    analysis = warm.Analysis(engine)
    analysis.run("focus", {"image_paths": []})

    analysis.shutdown()

    assert engine.stopped == 1
    # And a later run registers afresh, because the workers it registered with
    # are gone -- not silently reusing a name the new engine never heard.
    analysis._engine = engine
    analysis.run("focus", {"image_paths": []})
    assert [name for name, _path in engine.registered] == ["focus", "focus"]


def test_the_process_shares_one_analysis():
    assert warm.the_analysis() is warm.the_analysis()
    warm.close()


def test_a_pipeline_is_found_by_the_name_of_its_workflow():
    assert warm.pipeline_yaml("focus").is_file()
    assert warm.pipeline_yaml("object_analysis").is_file()
