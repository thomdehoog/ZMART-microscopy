"""Handing a captured stack to ZMART_analysis, and reading its answer back.

:func:`~application.parts.microscope.focus_run.measure_focus` drives and
captures; this is how what it captured becomes a height. The two are separate
because the loop is standard library plus ``zmart_controller`` on purpose --
that is what lets the operator page's bridge run on a microscope PC with
nothing installed on it -- while scoring pixels needs numpy, scipy, and an
environment to run them in.

There are two ways to reach the same step, and which one a caller wants depends
on what it can afford:

* :func:`in_process` imports the step and runs it here. The notebook already
  has numpy and scipy loaded, and one import is cheaper than a subprocess.
* :func:`through` sends it to the warm analysis, which keeps a worker alive
  per environment with its modules already imported. That is the one the
  operator page wants: a focus map is one job per point, and paying a conda
  spawn per point would make the map slower than the stage.

Either way the answer is the same shape, because it is the same step.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

#: Which sharpness metric's peak is reported as the height. Both are always
#: scored -- the page charts one against the other -- so this only chooses
#: which one answers.
DEFAULT_METRIC = "brenner"

#: Where the focus step lives, relative to this file.
_STEP = (
    Path(__file__).resolve().parents[3]
    / "zmart_analysis"
    / "workflows"
    / "focus"
    / "steps"
    / "score_focus.py"
)


#: How far either side of the centre a focussing acquisition sweeps.
#:
#: This belongs to the job that takes the stack, and the run states it because
#: no driver reports it *through the seam*. The Leica has it -- the selected
#: job's settings carry a ``stack`` block naming the z-drive and its range,
#: which is how ``readers/derived.py`` already decides whether a drive's
#: position is stale -- but ``get_state`` reports the job's metadata, not its
#: settings, so the range does not reach a caller. Exposing it there is the
#: proper fix and is a change to the driver; until then this is stated, once,
#: where anyone can see it.
#:
#: Stated wrongly it is not subtle: every height comes out scaled about the
#: centre, so a focus map tilts by the same factor everywhere. The default is
#: the range the operator page has always swept.
HALF_A_SWEEP_UM = 34.0


def what_was_captured(record: dict, centre_um: float, half_um: float) -> dict:
    """The step's input for one acquire record: the planes, and their heights.

    A driver writes one 2-D plane per file and reports them in depth order.
    Where each one sits is *not* in the record -- the Leica adapter numbers its
    planes and says nothing in micrometres -- so the heights are worked out
    from what the run itself did: it drove to ``centre_um`` and asked for a
    sweep of ``half_um`` either side, and the planes are spread evenly across
    it. That is the same arithmetic for every driver, which is what lets one be
    swapped for another.

    Nothing is assembled and nothing is copied: the planes are read where the
    acquisition left them.
    """
    planes = sorted(record.get("planes") or [], key=lambda plane: plane.get("z", 0))
    if not planes:
        raise RuntimeError("the capture reported no planes, so there is no stack to score")
    last = len(planes) - 1
    return {
        "image_paths": [plane["path"] for plane in planes],
        "z_um": [
            centre_um - half_um + (2 * half_um * index / last if last else 0.0)
            for index in range(len(planes))
        ],
    }


def as_a_measurement(scored: dict, *, metric: str = DEFAULT_METRIC) -> dict:
    """The step's answer, in the terms a focus map is written in.

    ``traces`` carries every metric's curve, not just the chosen one's, because
    a height alone cannot be argued with: the operator sees where each metric
    would have landed, and can say the routine picked the wrong peak.
    """
    heights = scored.get("z_um") or []
    return {
        "z_um": scored.get("peak_z_um"),
        "metric": metric,
        "traces": {
            name: {
                "samples": [
                    {"z": z, "s": s} for z, s in zip(heights, curve.get("scores") or [])
                ],
                "peak_z_um": curve.get("peak_z_um"),
            }
            for name, curve in (scored.get("metrics") or {}).items()
        },
    }


def in_process(
    *, metric: str = DEFAULT_METRIC, half_um: float = HALF_A_SWEEP_UM, **params: Any
) -> Callable[[dict, float], dict]:
    """Score each stack here, in this process. For callers that already have numpy."""

    def score(record: dict, centre_um: float) -> dict:
        run = _the_step()
        scored = run(
            {
                "input": what_was_captured(record, centre_um, half_um),
                "metadata": {"verbose": 0},
            },
            {},
            metric=metric,
            **params,
        )["score_focus"]
        return as_a_measurement(scored, metric=metric)

    return score


#: The ZMART_analysis workflow that scores a stack.
PIPELINE = "focus"


def through(
    analysis: Any, *, metric: str = DEFAULT_METRIC, half_um: float = HALF_A_SWEEP_UM
) -> Callable[[dict, float], dict]:
    """Score each stack through *analysis*, whose workers are already running.

    The analysis is passed in and never built here, so its lifetime is the
    caller's: held for as long as the page is connected, not one per focus map
    and certainly not one per point. See
    :mod:`application.parts.analysis.warm`.
    """

    def score(record: dict, centre_um: float) -> dict:
        result = analysis.run(PIPELINE, what_was_captured(record, centre_um, half_um))
        return as_a_measurement(result["score_focus"], metric=metric)

    return score


def _the_step() -> Callable:
    """Load ``score_focus.run`` by path, the way the engine's worker loads a step.

    Imported here rather than at module scope so that a caller who only wants
    :func:`through` -- the bridge, which has no numpy -- can import this module
    at start-up without paying for scipy or failing without it.
    """
    import importlib.util  # noqa: PLC0415 — see above

    spec = importlib.util.spec_from_file_location("score_focus", _STEP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run
