"""The focus map, one stack at a time: the page drives, the bridge files and scores.

Begin clears the focussing acquisition and names the stacks; the page
drives and captures each; score files the stack, scores it through the
warm analysis and answers the point; end closes the map. The ledger of the
points scored so far is ``ledgers.focus``.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from ..analysis import focus_score, warm
from ..microscope.focus_run import FOCUSSING, measure_one_stack
from ..storage.output import position_label, prepare_acquisition
from . import ledgers, pictures, stage, state, views


def score_a_stack():
    """How a captured stack becomes a height and a curve.

    Through the warm analysis, which is shared with every other step that
    measures pixels and outlives any one focus map. See
    :mod:`target_acquisition.analysis.warm`.
    """
    return focus_score.through(warm.the_analysis())


def begin_focus(asked: dict) -> dict:
    """The page begins a focus map: the focussing acquisition is cleared, the
    ledger emptied, and the stacks named in order.

    The page drives every point itself from here -- ``/api/xyz``, then
    ``/api/acquire`` with the label named here, then ``/api/focus/score`` --
    and ends the map with ``/api/focus/end``. Between two answers the page
    decides, and a stop is its own decision; nothing runs here on its own.
    Refused while a scan or a map has the stage.
    """
    if ledgers.a_run_has_the_stage():
        raise RuntimeError("the instrument is driving a run; a focus map cannot begin now")
    of = int(asked.get("of", 0))
    # Measuring the map again replaces the map: the stacks of the last run
    # would otherwise stand beside the new ones under the same heading.
    pictures.replace_the_acquisition(FOCUSSING)
    ledgers.focus.update(
        running=True, done=0, of=of, error=None, stopped=False, points=[], doing=None,
    )
    return {**dict(ledgers.focus), "labels": [position_label(index) for index in range(of)]}


def score_focus(asked: dict) -> dict:
    """One stack the page just captured: file it, score it, answer the point.

    ``record`` is the driver's own answer to the capture, ``centre`` the
    height the stack was taken around (the drive's answer), ``point`` what
    the page asked with. The point comes back as the map reports it -- the
    height, the curves, the slice copies -- and is kept in the ledger.
    ``startZ`` said where to begin this search; echoing it back would have
    the next run silently begin where this one did.
    """
    if not ledgers.focus["running"]:
        raise RuntimeError("no focus map has begun")
    record = asked["record"]
    # The interface's own grouping, from what it asked for (see ``state.records``).
    record["acquisition_type"] = FOCUSSING
    point = dict(asked.get("point") or {})
    index = len(ledgers.focus["points"])
    measurement = measure_one_stack(
        record, x=float(point["x"]), y=float(point["y"]), centre=float(asked["centre"]),
        score=score_a_stack(), index=index,
        output=prepare_acquisition(state.the_run(), FOCUSSING),
        # Every focus stack also stands as an OME-Zarr position, so the
        # focussing is a source of its own in the viewer.
        keep=lambda landed: pictures.keep_position_as_zarr(landed, FOCUSSING),
        cost=asked.get("cost_s"),
    )
    stage.the_stage_was_sent_to(
        measurement["x_um"], measurement["y_um"],
        measurement["z_um"] if measurement.get("z_um") is not None else 0.0,
    )
    landed = {
        **{key: value for key, value in point.items() if key != "startZ"},
        "zAuto": measurement["z_um"], "z": measurement["z_um"],
        "lost": measurement["z_um"] is None, "traces": measurement["traces"],
        "cost_s": measurement.get("cost_s"),
        "slices": views.the_slice_copies_of(measurement.get("planes") or [],
                                      store=measurement.get("zarr")),
    }
    ledgers.focus["points"].append(landed)
    ledgers.focus["done"] = len(ledgers.focus["points"])
    return landed


def stop_focus() -> dict:
    """The operator's Interrupt for a focus map: reach a point whose scoring has hung.

    The page stops its own loop between two points, but a point whose
    scoring never answers keeps its request open for ever, and the map with
    it. Putting the analysis workers down makes that scoring answer at once
    with an error, as stopping discovery does; the workers start again on
    the next request. The capture in hand is already on disk, so nothing is
    lost. The page still ends the map itself, with ``/api/focus/end``.
    """
    if ledgers.focus["running"]:
        warm.close()
    return dict(ledgers.focus)


def end_focus(asked: dict) -> dict:
    """The page ends the map, stopped by its hand or complete."""
    ledgers.focus.update(running=False, doing=None, stopped=bool(asked.get("stopped")))
    return dict(ledgers.focus)
