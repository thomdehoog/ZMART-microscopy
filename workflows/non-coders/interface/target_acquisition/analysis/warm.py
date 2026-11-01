"""One ZMART-analysis engine, kept warm for as long as the process runs.

Every step that measures pixels goes through the same door: focus scoring
today, object detection and feature extraction next, and whatever comes after
that. They differ only in which pipeline they name and what they put in, so
this module knows about none of them.

Why it exists at all is cost. A pipeline step runs in its own conda
environment, and spawning one costs seconds -- more than the stage takes to
move. The engine already solves that: its workers are per-environment, not
per-step, and they keep their imports between jobs. What it cannot do is stop a
caller from building a fresh engine per request and shutting it down after,
which would pay the spawn every single time. So the engine is held here, built
on first use, and handed to whoever asks.

    from . import warm

    warm.open(run)                      # at connect: the session's run folder
    scored = warm.the_analysis().run("focus", {"image_paths": [...]})

Every pipeline is registered with that run folder, so its record and files
go into ``<run>/analysis/<pipeline>/``.

The engine is ZMART-analysis's (installed as the ``zmart_analysis`` package);
the pipelines it runs are found in a ZMART-analysis checkout, as
:mod:`target_acquisition.analysis.workflows` describes.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import time
from typing import Any

from .workflows import pipeline_yaml

#: How often to look for a finished job. The engine has no blocking read.
_LOOK_EVERY_S = 0.05


class Analysis:
    """An engine that registers a pipeline the first time it is asked for.

    ``run`` is the whole surface: give it a pipeline's name and its input, get
    that job's result back. One job at a time is what the callers here need --
    a stage visits one place at a time -- and anything wanting many at once
    should use the engine's own ``submit``/``results``, which :attr:`engine`
    exposes unchanged.
    """

    def __init__(self, engine: Any = None, output: str | None = None) -> None:
        self._engine = engine
        self._registered: set[str] = set()
        #: The run folder every pipeline writes into.
        self.output = output

    @property
    def engine(self) -> Any:
        """The engine itself, started if it has not been."""
        if self._engine is None:
            from zmart_analysis import Engine  # noqa: PLC0415 — see module docstring

            # Analysis started is analysis finished. The engine's own default
            # would cut a step at 300 s, and every such number was wrong for
            # somebody's field -- the first job of a session pays the model
            # loading, a big frame pays its own size. A worker that has
            # genuinely wedged is reached by the operator's hand instead:
            # :meth:`shutdown` puts it down, and nothing else may.
            #
            # The workers stay for the session on their own: the engine
            # keeps a worker for as long as a pipeline that needs it is
            # registered, and nothing here deregisters one.
            self._engine = Engine(execution_timeout=None)
        return self._engine

    def ready(self, pipeline: str) -> Any:
        """The engine, with *pipeline* registered into the run folder."""
        if self.output is None:
            raise RuntimeError("the analysis has no run folder yet: connect to a microscope first")
        engine = self.engine
        if pipeline not in self._registered:
            engine.register(pipeline, str(pipeline_yaml(pipeline)), self.output)
            self._registered.add(pipeline)
        return engine

    def run(self, pipeline: str, given: dict) -> dict:
        """Run one job through *pipeline* and return its result.

        ``given`` is the step's own input -- ``image_paths``, ``z_um`` and so
        on. The engine is what puts it under ``pipeline_data["input"]``, so a
        caller that wrapped it itself would have it arrive one level too deep
        and the step would report the input missing.

        Raises if the pipeline fails: a step that measures pixels has no
        sensible empty answer, and a caller that invented one would be
        recording a number nobody measured. There is no give-up clock -- a
        job runs until it answers or its workers are put down by the hand
        that wants it stopped (:meth:`shutdown`), because every duration we
        ever chose to "know" a job had hung was a legitimate one for some
        field, and cutting real work is the worse failure.
        """
        engine = self.ready(pipeline)

        # The job's own id is what is followed on the board, so another
        # job's failure, earlier or at the same time, is never this one's.
        job = engine.submit(pipeline=pipeline, data=given)
        while True:
            outcome = outcome_of(pipeline, engine.status(pipeline)[job])
            if isinstance(outcome, RuntimeError):
                raise outcome
            if outcome is not None:
                return outcome
            time.sleep(_LOOK_EVERY_S)

    def run_each(self, pipeline: str, givens: dict, *, at_once: int, until=None):
        """Run one job per entry of *givens* through *pipeline*, several at a time.

        Yields ``(key, outcome)`` as each job lands, in whatever order the
        engine finishes them: the pipeline's result, or the ``RuntimeError``
        of the job that failed. At most *at_once* jobs are in flight; the
        rest are submitted as answers come back. ``until`` is asked before
        each submission -- once it answers true no more are submitted, and
        what is in flight is still drained.

        Every submission's job id is kept against its key, and each job is
        followed on the board by that id.
        """
        engine = self.ready(pipeline)
        waiting = list(givens.items())
        in_flight: dict = {}  # job id -> key
        while waiting or in_flight:
            while waiting and len(in_flight) < at_once and not (until and until()):
                key, given = waiting.pop(0)
                in_flight[engine.submit(pipeline=pipeline, data=given)] = key
            if until and until():
                waiting = []
            if not in_flight:
                break
            board = engine.status(pipeline)
            landed = False
            for job in list(in_flight):
                outcome = outcome_of(pipeline, board[job])
                if outcome is not None:
                    landed = True
                    yield in_flight.pop(job), outcome
            if not landed:
                time.sleep(_LOOK_EVERY_S)

    def shutdown(self) -> None:
        """Put the workers down now. The next :meth:`run` starts them again.

        Without waiting, on purpose: this is the hand that stops a field in
        flight, and an engine that first waited for its threads waited for
        the field. A :meth:`run` in progress raises, which is the answer the
        hand wanted.
        """
        if self._engine is not None:
            self._engine.shutdown(wait=False)
        self._engine = None
        self._registered.clear()


def outcome_of(pipeline: str, entry: dict):
    """A finished job's output, or the error that ended it; None while it runs."""
    if entry["state"] == "done":
        return entry["output"]
    if entry["state"] in ("failed", "cancelled"):
        why = entry.get("error") or entry["state"]
        return RuntimeError(f"the {pipeline!r} pipeline {entry['state']} at {entry['step']}: {why}")
    return None


_analysis: Analysis | None = None

#: The session's run folder, given by :func:`open`.
run_folder: str | None = None


def open(run) -> None:  # noqa: A001 -- the pair of close()
    """Give the analysis the session's run folder, or None when there is none.

    An analysis still writing into another run is put down, as a
    disconnect would.
    """
    global run_folder
    run_folder = None if run is None else str(run)
    if _analysis is not None and _analysis.output != run_folder:
        close()


def the_analysis() -> Analysis:
    """The one analysis this process talks to, built on first use."""
    global _analysis
    if _analysis is None:
        _analysis = Analysis(output=run_folder)
    return _analysis


def close() -> None:
    """Let the workers go. Called when nothing is going to ask again soon.

    The door is emptied first and the old analysis put down after: the page
    starts the next test the moment a stopped one reports itself done, while
    this is still under way, and a caller handed the analysis on its way out
    died with "Engine has been shut down".
    """
    global _analysis
    leaving, _analysis = _analysis, None
    if leaving is not None:
        leaving.shutdown()
