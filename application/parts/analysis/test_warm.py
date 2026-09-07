"""The warm analysis: one engine, registered once, shared by every pipeline."""

from __future__ import annotations

import pytest

from application.parts.analysis import warm


class _Engine:
    """A stand-in engine that answers immediately and counts what it was told."""

    def __init__(self, answers=None, failure=None, stale_failures=()):
        self.registered: list[tuple] = []
        self.submitted: list[tuple] = []
        self.stopped = 0
        self._answers = answers if answers is not None else {}
        self._failure = failure
        # Failures the pipeline had before: the engine keeps them for as
        # long as the pipeline lives, and reports them with every status.
        self._failures: list = list(stale_failures)
        self._waiting: list[dict] = []

    def register(self, name, yaml_path):
        self.registered.append((name, yaml_path))

    def submit(self, name, data):
        self.submitted.append((name, data))
        if self._failure is None:  # a job that fails produces no result
            self._waiting.append(self._answers.get(name, {"ran": name}))
        else:
            self._failures.append(self._failure)

    def status(self, name):
        return {"failed": len(self._failures), "failures": list(self._failures)}

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


def test_a_failure_from_before_the_job_is_not_the_jobs():
    """The engine keeps every failure a pipeline ever had; a job is judged
    only by what failed after it was submitted. The first good stack after a
    bad one was declared lost on the bad one's error while its own score was
    still being computed."""

    class _Slow(_Engine):
        def __init__(self):
            super().__init__(stale_failures=["an earlier stack had one plane"])
            self.asked = 0

        def results(self, name):
            self.asked += 1
            return super().results(name) if self.asked > 3 else []

    got = warm.Analysis(_Slow()).run("focus", {"image_paths": ["a", "b", "c"]})
    assert got == {"ran": "focus"}


def test_a_failure_after_an_earlier_one_is_still_raised():
    engine = _Engine(failure="the worker died", stale_failures=["an old one"])
    with pytest.raises(RuntimeError, match="the worker died") as raised:
        warm.Analysis(engine).run("focus", {"image_paths": []})
    assert "an old one" not in str(raised.value)


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


def test_the_workers_are_kept_for_the_whole_session(monkeypatch):
    """The engine's own default reaps a worker idle for 300 s; ours must not.

    The workers' imports are the cost this module exists to pay once. A press
    six minutes after the last one found them reaped and paid it again, six
    seconds on this PC and a silent minute on the rig.
    """
    import zmart_analysis.engine as engine_module

    built = {}

    class _Caught:
        def __init__(self, **kwargs):
            built.update(kwargs)

    monkeypatch.setattr(engine_module, "Engine", _Caught)
    warm.Analysis().engine
    assert built.get("idle_timeout", "unset") is None


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


def test_a_pipeline_is_found_by_its_name_under_whichever_workflow_has_it():
    assert warm.pipeline_yaml("focus").is_file()
    assert warm.pipeline_yaml("object_analysis").is_file()
    # A workflow's second pipeline: the same steps, one of them placed in
    # another environment.
    fast = warm.pipeline_yaml("object_analysis_fast")
    assert fast.is_file()
    assert fast.parent == warm.pipeline_yaml("object_analysis").parent


def test_a_pipeline_nobody_has_is_said_so():
    with pytest.raises(FileNotFoundError, match="no_such_pipeline"):
        warm.pipeline_yaml("no_such_pipeline")


def test_a_new_analysis_is_handed_out_while_the_old_one_is_still_being_put_down():
    """The next run must never get the analysis on its way out.

    The operator's Interrupt puts the analysis down, and the page starts the
    next test the moment the stopped one reports itself done -- while the
    shutdown is still under way. Handed the old analysis, that test died
    with "Engine has been shut down". The door swaps first, shuts down after.
    """
    import threading

    class _SlowEngine(_Engine):
        def __init__(self):
            super().__init__()
            self.shutting_down = threading.Event()
            self.may_finish = threading.Event()

        def shutdown(self, wait=True):
            self.shutting_down.set()
            self.may_finish.wait(timeout=5)
            super().shutdown(wait=wait)

    warm._analysis = None
    old = warm.the_analysis()
    slow = _SlowEngine()
    old._engine = slow
    closer = threading.Thread(target=warm.close, daemon=True)
    closer.start()
    assert slow.shutting_down.wait(timeout=5)
    # The shutdown is under way; whoever asks now gets a fresh analysis.
    fresh = warm.the_analysis()
    assert fresh is not old
    assert fresh._engine is not slow
    slow.may_finish.set()
    closer.join(timeout=5)
    assert warm.the_analysis() is fresh
    warm._analysis = None
