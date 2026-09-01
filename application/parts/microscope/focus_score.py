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


def what_was_captured(record: dict) -> dict:
    """The step's input for one acquire record: the stack, and its heights.

    The heights are read straight off the record, because that is the only
    place that knows them: a saved file carries the size of a pixel and
    nothing about where it came from, and the stage stands at the middle of a
    stack while its planes are spread either side of it.

    **What is scored is the run's own store of the stack where there is one.**
    A capture is converted to an OME-Zarr position the moment it lands — one
    image, its axes declared, its channels described — and that is the run's
    canonical form. Scoring it rather than the vendor's loose plane files
    means the numbers on the operator's focus plot come from the same image an
    operator can open in the viewer, in napari or in Fiji, rather than from a
    second reading of a different arrangement of the same pixels. It also
    means the step is handed one path instead of sixty-one, and reads one
    channel of one level rather than opening every file.

    Where no store has been written the plane files are used exactly as
    before, so a driver whose captures are not converted still focusses.

    Nothing is assembled and nothing is copied either way: the pixels are read
    where the acquisition left them.
    """
    every = record.get("planes") or []
    if not every:
        raise RuntimeError("the capture reported no planes, so there is no stack to score")
    # One channel's planes are the stack. A focus job that captures several
    # channels repeats every height once per channel, and scoring the
    # interleaved list refines a peak on a curve nobody measured.
    first = min(int(plane.get("c", 0)) for plane in every)
    planes = sorted(
        (plane for plane in every if int(plane.get("c", 0)) == first),
        key=lambda plane: plane.get("z", 0),
    )
    heights = [plane.get("z_um") for plane in planes]
    if any(height is None for height in heights):
        raise RuntimeError(
            "the capture did not say what height each plane was taken at, so "
            "the sharp one cannot be named in micrometres"
        )
    heights_um = [float(height) for height in heights]

    # The run's own store of this stack, where the capture has already been
    # converted to one. The bridge files it on the record as `zarr` the moment
    # it lands, before anything is scored; a conversion that failed leaves
    # `zarr_error` instead and the planes below are used. See this function's
    # docstring for why the store is preferred when there is one.
    kept = record.get("zarr")
    if kept:
        return {"image_path": str(kept), "z_um": heights_um}

    return {
        "image_paths": [plane["path"] for plane in planes],
        "z_um": heights_um,
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


def in_process(*, metric: str = DEFAULT_METRIC, **params: Any) -> Callable[[dict], dict]:
    """Score each stack here, in this process. For callers that already have numpy."""

    def score(record: dict) -> dict:
        run = _the_step()
        scored = run(
            {"input": what_was_captured(record), "metadata": {"verbose": 0}},
            {},
            metric=metric,
            **params,
        )["score_focus"]
        return as_a_measurement(scored, metric=metric)

    return score


#: The ZMART_analysis workflow that scores a stack.
PIPELINE = "focus"


def through(analysis: Any, *, metric: str = DEFAULT_METRIC) -> Callable[[dict], dict]:
    """Score each stack through *analysis*, whose workers are already running.

    The analysis is passed in and never built here, so its lifetime is the
    caller's: held for as long as the page is connected, not one per focus map
    and certainly not one per point. See
    :mod:`application.parts.analysis.warm`.
    """

    def score(record: dict) -> dict:
        result = analysis.run(PIPELINE, what_was_captured(record))
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
