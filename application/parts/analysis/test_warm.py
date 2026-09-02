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

    def shutdown(self, wait=True):
        self.stopped += 1
        self.waited = wait


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


def test_an_answer_that_takes_its_time_is_waited_for():
    """Analysis started is analysis finished: no clock of ours may cut it.

    A job is as long as the pixels make it -- the first of a session pays the
    model loading, a big frame pays its own size -- and every give-up number
    we ever chose was wrong for somebody's field. The way out of a genuinely
    wedged worker is the operator's hand (shutdown), never a timer.
    """

    class _Slow(_Engine):
        def __init__(self):
            super().__init__()
            self.asked = 0

        def results(self, name):
            self.asked += 1
            return super().results(name) if self.asked > 5 else []

    got = warm.Analysis(_Slow()).run("focus", {"image_paths": []})
    assert got == {"ran": "focus"}


def test_the_engine_is_built_with_no_per_call_clock(monkeypatch):
    """The engine's own default cuts a step at 300 s; ours must not exist."""
    import zmart_analysis.engine as engine_module

    built = {}

    class _Caught:
        def __init__(self, **kwargs):
            built.update(kwargs)

    monkeypatch.setattr(engine_module, "Engine", _Caught)
    warm.Analysis().engine
    assert built.get("execution_timeout", "unset") is None


def test_the_workers_are_let_go_and_can_start_again():
    engine = _Engine()
    analysis = warm.Analysis(engine)
    analysis.run("focus", {"image_paths": []})

    analysis.shutdown()

    assert engine.stopped == 1
    # Put down now, not waited for: this is the hand that stops a field in
    # flight, and an engine that waited for its threads waited for the field.
    assert engine.waited is False
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
