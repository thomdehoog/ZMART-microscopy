"""The warm analysis: one engine, registered once, shared by every pipeline."""

from __future__ import annotations

import pytest

from . import warm


class FakeEngine:
    """A stand-in engine with a job board, as the real one keeps.

    Each submit gets the next id of its pipeline. A job is done (or failed)
    once its board has been asked for ``answer_after`` times; until then it
    is running. ``earlier`` puts jobs on the board that finished before.
    """

    def __init__(self, answers=None, failure=None, answer_after=1, earlier=()):
        self.registered: list[tuple] = []
        self.outputs: list = []
        self.submitted: list[tuple] = []
        self.stopped = 0
        self.answers = answers if answers is not None else {}
        self.failure = failure
        self.answer_after = answer_after
        self.boards: dict = {}
        self.asked: dict = {}
        for name, entry in earlier:
            self.add(name, dict(entry))

    def add(self, name, entry):
        board = self.boards.setdefault(name, {})
        job = len(board) + 1
        board[job] = entry
        return job

    def register(self, name, yaml_path, output):
        self.registered.append((name, yaml_path))
        self.outputs.append(output)

    def outcome(self, pipeline, data):
        """The finished entry this job will show."""
        if self.failure is not None:
            return {"state": "failed", "output": None, "error": self.failure}
        return {"state": "done", "output": self.answers.get(pipeline, {"ran": pipeline})}

    def submit(self, pipeline, data, scope=None, priority=None, complete=None):
        self.submitted.append((pipeline, data))
        entry = {"step": "step", "scope": dict(scope or {}), "state": "running", "output": None}
        job = self.add(pipeline, entry)
        self.asked[(pipeline, job)] = 0
        entry["finished"] = self.outcome(pipeline, data)
        return job

    def status(self, name):
        board = self.boards.get(name, {})
        for job, entry in board.items():
            if "finished" in entry:
                self.asked[(name, job)] += 1
                if self.asked[(name, job)] >= self.answer_after:
                    entry.update(entry.pop("finished"))
        return {job: {k: v for k, v in e.items() if k != "finished"} for job, e in board.items()}

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
    engine = FakeEngine()
    warm.Analysis(engine, output="run").run("focus", {"image_paths": ["a.tiff", "b.tiff"]})
    assert engine.submitted == [("focus", {"image_paths": ["a.tiff", "b.tiff"]})]


def test_a_pipeline_is_registered_once_however_often_it_runs():
    """Registering parses YAML and reads every step; doing it per job is waste."""
    engine = FakeEngine()
    analysis = warm.Analysis(engine, output="run")

    for _ in range(3):
        analysis.run("focus", {"image_paths": []})

    assert [name for name, _path in engine.registered] == ["focus"]
    assert len(engine.submitted) == 3


def test_two_pipelines_share_the_one_engine():
    """Object analysis is the next caller, and it needs nothing new here."""
    engine = FakeEngine()
    analysis = warm.Analysis(engine, output="run")

    analysis.run("focus", {"image_paths": []})
    analysis.run("object_analysis_cellpose", {"image_paths": []})

    assert [name for name, _path in engine.registered] == ["focus", "object_analysis_cellpose"]
    assert engine.registered[1][1].endswith("object_analysis_cellpose.yaml")


def test_a_failed_pipeline_is_raised_and_not_answered_for():
    """A step that measures pixels has no sensible empty answer."""
    analysis = warm.Analysis(FakeEngine(failure="the worker died"), output="run")
    with pytest.raises(RuntimeError, match="the worker died"):
        analysis.run("focus", {"image_paths": []})


def test_a_failure_from_before_the_job_is_not_the_jobs():
    """The board keeps every job a pipeline ever had; a job is judged only
    by its own entry. The first good stack after a bad one was once declared
    lost on the bad one's error while its own score was still being computed."""
    earlier = [
        (
            "focus",
            {
                "step": "score_focus",
                "scope": {},
                "state": "failed",
                "output": None,
                "error": "an earlier stack had one plane",
            },
        )
    ]
    engine = FakeEngine(answer_after=4, earlier=earlier)
    got = warm.Analysis(engine, output="run").run("focus", {"image_paths": ["a", "b", "c"]})
    assert got == {"ran": "focus"}


def test_a_failure_after_an_earlier_one_is_still_raised():
    earlier = [
        (
            "focus",
            {
                "step": "score_focus",
                "scope": {},
                "state": "failed",
                "output": None,
                "error": "an old one",
            },
        )
    ]
    engine = FakeEngine(failure="the worker died", earlier=earlier)
    with pytest.raises(RuntimeError, match="the worker died") as raised:
        warm.Analysis(engine, output="run").run("focus", {"image_paths": []})
    assert "an old one" not in str(raised.value)


def test_an_answer_that_takes_its_time_is_waited_for():
    """Analysis started is analysis finished: no clock of ours may cut it.

    A job is as long as the pixels make it -- the first of a session pays the
    model loading, a big frame pays its own size -- and every give-up number
    we ever chose was wrong for somebody's field. The way out of a genuinely
    wedged worker is the operator's hand (shutdown), never a timer.
    """

    engine = FakeEngine(answer_after=6)
    got = warm.Analysis(engine, output="run").run("focus", {"image_paths": []})
    assert got == {"ran": "focus"}
    assert engine.asked[("focus", 1)] == 6


def test_the_engine_is_built_with_no_per_call_clock(monkeypatch):
    """The engine's own default cuts a step at 300 s; ours must not exist."""
    import zmart_analysis as engine_module

    built = {}

    class _Caught:
        def __init__(self, **kwargs):
            built.update(kwargs)

    monkeypatch.setattr(engine_module, "Engine", _Caught)
    _ = warm.Analysis().engine
    assert built.get("execution_timeout", "unset") is None


def test_the_engine_is_built_with_nothing_but_the_missing_clock(monkeypatch):
    """The workers stay for the session without asking: the engine keeps a
    worker while its recipe is registered, and nothing here deregisters one.

    The workers' imports are the cost this module exists to pay once. When
    the engine still reaped idle workers, a press six minutes after the last
    one paid them again, six seconds on this PC and a silent minute on the rig.
    """
    import zmart_analysis as engine_module

    built = {}

    class _Caught:
        def __init__(self, **kwargs):
            built.update(kwargs)

    monkeypatch.setattr(engine_module, "Engine", _Caught)
    _ = warm.Analysis().engine
    assert built == {"execution_timeout": None}


def test_the_workers_are_let_go_and_can_start_again():
    engine = FakeEngine()
    analysis = warm.Analysis(engine, output="run")
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
    assert warm.pipeline_yaml("focus").parent.parent.name == "focus"
    assert warm.pipeline_yaml("object_analysis_cellpose").is_file()
    # A workflow's second pipeline: the same steps, the segmentation done another way.
    watershed = warm.pipeline_yaml("object_analysis_watershed")
    assert watershed.is_file()
    assert watershed.parent == warm.pipeline_yaml("object_analysis_cellpose").parent


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

    class _SlowEngine(FakeEngine):
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


class WideEngine(FakeEngine):
    """A stand-in that answers in its own time, fails the keys it is told
    to, and counts how many jobs were in flight at once."""

    def __init__(self, *, fail=(), answer_after=1):
        super().__init__(answer_after=answer_after)
        self.fail = set(fail)
        self.widest = 0

    def outcome(self, pipeline, data):
        if data.get("key") in self.fail:
            return {"state": "failed", "output": None, "error": f"field {data['key']} choked"}
        return {"state": "done", "output": {"input": dict(data), "ran": pipeline}}

    def submit(self, pipeline, data, scope=None, priority=None, complete=None):
        job = super().submit(pipeline, data, scope=scope)
        running = sum(e["state"] == "running" for e in self.boards[pipeline].values())
        self.widest = max(self.widest, running)
        return job


def test_run_each_submits_up_to_the_width_at_once_and_answers_by_key():
    engine = WideEngine()
    got = dict(
        warm.Analysis(engine, output="run").run_each(
            "object_analysis_watershed", {3: {"a": 3}, 7: {"a": 7}, 9: {"a": 9}}, at_once=2
        )
    )
    assert set(got) == {3, 7, 9}
    assert got[7]["input"]["a"] == 7
    assert engine.widest == 2
    assert [name for name, _ in engine.registered] == ["object_analysis_watershed"]


def test_run_each_files_a_failure_under_its_own_key_and_goes_on():
    engine = WideEngine(fail={7})
    got = dict(
        warm.Analysis(engine, output="run").run_each(
            "object_analysis_watershed", {3: {"key": 3}, 7: {"key": 7}, 9: {"key": 9}}, at_once=3
        )
    )
    assert isinstance(got[7], RuntimeError) and "choked" in str(got[7])
    assert got[3]["ran"] == "object_analysis_watershed" and got[9]["ran"] == "object_analysis_watershed"


def test_run_each_stops_submitting_when_asked_and_drains_what_is_in_flight():
    engine = WideEngine(answer_after=2)
    asked = {"stop": False}
    seen = []
    for key, _outcome in warm.Analysis(engine, output="run").run_each(
        "focus", {n: {} for n in range(6)}, at_once=2, until=lambda: asked["stop"]
    ):
        seen.append(key)
        asked["stop"] = True
    assert len(engine.submitted) <= 3
    assert seen and len(seen) <= 3


def test_every_pipeline_is_registered_into_the_run_folder():
    engine = FakeEngine()
    analysis = warm.Analysis(engine, output="D:/runs/exp_abc123")
    analysis.run("focus", {"image_paths": []})
    analysis.run("object_analysis_cellpose", {"image_paths": []})
    assert engine.outputs == ["D:/runs/exp_abc123", "D:/runs/exp_abc123"]


def test_an_analysis_without_a_run_folder_says_to_connect():
    with pytest.raises(RuntimeError, match="connect"):
        warm.Analysis(FakeEngine()).run("focus", {"image_paths": []})


def test_open_hands_the_run_folder_on_and_a_new_run_puts_the_old_analysis_down(monkeypatch):
    monkeypatch.setattr(warm, "_analysis", None)
    monkeypatch.setattr(warm, "run_folder", None)
    warm.open("D:/runs/first")
    first = warm.the_analysis()
    engine = first._engine = FakeEngine()
    assert first.output == "D:/runs/first"

    warm.open("D:/runs/first")
    assert warm.the_analysis() is first

    warm.open("D:/runs/second")
    assert engine.stopped == 1
    second = warm.the_analysis()
    assert second is not first and second.output == "D:/runs/second"

    warm.open(None)
    assert warm.run_folder is None and warm._analysis is None
