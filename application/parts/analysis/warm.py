"""One ZMART_analysis engine, kept warm for as long as the process runs.

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

    from application.parts.analysis import warm

    scored = warm.the_analysis().run("focus", {"image_paths": [...]})

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

#: Where the workflows live. A pipeline is named after its workflow and found
#: at ``<name>/pipelines/<name>.yaml``, so naming one is all a caller does.
WORKFLOWS = Path(__file__).resolve().parents[3] / "zmart_analysis" / "workflows"

#: How often to look for a finished job. The engine has no blocking read.
_LOOK_EVERY_S = 0.05


def pipeline_yaml(name: str) -> Path:
    """Where a pipeline's YAML is, by the name of its workflow."""
    return WORKFLOWS / name / "pipelines" / f"{name}.yaml"


class Analysis:
    """An engine that registers a pipeline the first time it is asked for.

    ``run`` is the whole surface: give it a pipeline's name and its input, get
    that job's result back. One job at a time is what the callers here need --
    a stage visits one place at a time -- and anything wanting many at once
    should use the engine's own ``submit``/``results``, which :attr:`engine`
    exposes unchanged.
    """

    def __init__(self, engine: Any = None) -> None:
        self._engine = engine
        self._registered: set[str] = set()

    @property
    def engine(self) -> Any:
        """The engine itself, started if it has not been."""
        if self._engine is None:
            from zmart_analysis.engine import Engine  # noqa: PLC0415 — see module docstring

            # Analysis started is analysis finished. The engine's own default
            # would cut a step at 300 s, and every such number was wrong for
            # somebody's field -- the first job of a session pays the model
            # loading, a big frame pays its own size. A worker that has
            # genuinely wedged is reached by the operator's hand instead:
            # :meth:`shutdown` puts it down, and nothing else may.
            self._engine = Engine(execution_timeout=None)
        return self._engine

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
        engine = self.engine
        if pipeline not in self._registered:
            engine.register(pipeline, str(pipeline_yaml(pipeline)))
            self._registered.add(pipeline)

        engine.submit(pipeline, given)
        while True:
            status = engine.status(pipeline)
            for result in engine.results(pipeline):
                return result
            if status.get("failed"):
                raise RuntimeError(
                    f"the {pipeline!r} pipeline failed: {status.get('failures')}"
                )
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


_analysis: Analysis | None = None


def the_analysis() -> Analysis:
    """The one analysis this process talks to, built on first use."""
    global _analysis
    if _analysis is None:
        _analysis = Analysis()
    return _analysis


def close() -> None:
    """Let the workers go. Called when nothing is going to ask again soon."""
    global _analysis
    if _analysis is not None:
        _analysis.shutdown()
        _analysis = None
