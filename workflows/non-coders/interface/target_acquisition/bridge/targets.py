"""The target run, driven by the page one tile at a time, like the focus map.

Begin clears the targets acquisition (unless appending) and names the
captures; the page drives and captures each, with a focussing stack first
when the operator asked for one; landed files the target's record the way
the scan filed its own; end closes the run. The ledger is ``ledgers.acquired``.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from ..microscope.focus_run import measure_one_stack
from ..storage import output, viewer_service
from ..storage.output import prepare_acquisition
from . import focus, ledgers, pictures, scan, stage, state

#: The stacks taken before a target when the operator asked for focussing
#: there: an acquisition of their own, beside the targets they were taken for.
TARGET_FOCUSSING = "target-focussing"


def begin_target_run(asked: dict) -> dict:
    """The page begins the target run: the targets acquisition is cleared
    (unless one selected target is being taken again), the ledger emptied,
    and the captures named in order.

    The page drives every tile itself from here -- ``/api/xyz``, a focussing
    stack through ``/api/acquire`` and ``/api/targets/acquire/focus`` when the
    operator asked for one, ``/api/acquire`` for the target, then
    ``/api/targets/acquire/landed`` -- and ends the run with
    ``/api/targets/acquire/end``. Between two answers the page decides, and a
    stop is its own decision; nothing runs here on its own. Refused while a
    scan, a map or another run has the stage.
    """
    if ledgers.a_run_has_the_stage():
        raise RuntimeError("the instrument is driving a run; the targets cannot begin now")
    positions = asked.get("positions", [])
    if asked.get("append"):
        state.records.setdefault("targets", [])
        # The view's ordinary JPEG copies are derived from the records. One
        # retained label has new pixels now, so rebuild the set rather than
        # serving the old copy under its stable name.
        shutil.rmtree(pictures.view_of("targets"), ignore_errors=True)
        with state.view_lock:
            state.view_built.pop("targets", None)
    else:
        state.records["targets"] = []
        pictures.replace_the_acquisition(
            "targets",
            keeping={f"targets_{scan.label_for(i, p)}.ome.zarr" for i, p in enumerate(positions)},
        )
        # The focussing stacks belong to the run they were taken for.
        pictures.replace_the_acquisition(TARGET_FOCUSSING)
    for key in [key for key in state.displayed_pictures if key[0] == "targets"]:
        del state.displayed_pictures[key]
    ledgers.acquired.update(running=True, done=0, of=len(positions), error=None, stopped=False, records=[])
    return {**dict(ledgers.acquired), "labels": [scan.label_for(i, p) for i, p in enumerate(positions)]}


def score_target_focus(asked: dict) -> dict:
    """One focussing stack the page just captured before a target: file it
    under the target focussing acquisition, score it, answer the height.

    ``record`` is the driver's answer to the capture, ``centre`` the height
    the stack was taken around. The peak is the page's choice, made on the
    curves answered here with the same rule the focus map uses; ``z`` is the
    scorer's own tallest, for a page that wants no more than that.
    """
    if not ledgers.acquired["running"]:
        raise RuntimeError("no target run has begun")
    # The interface's own grouping, from what it asked for (see ``state.records``).
    asked["record"]["acquisition_type"] = TARGET_FOCUSSING
    measurement = measure_one_stack(
        asked["record"], x=float(asked["x"]), y=float(asked["y"]), centre=float(asked["centre"]),
        score=focus.score_a_stack(), index=ledgers.acquired["done"],
        output=prepare_acquisition(state.the_run(), TARGET_FOCUSSING),
        keep=lambda landed: pictures.keep_position_as_zarr(landed, TARGET_FOCUSSING),
    )
    return {
        "z": measurement["z_um"], "lost": measurement["z_um"] is None,
        "traces": measurement["traces"], "cost_s": measurement.get("cost_s"),
    }


def target_landed(asked: dict) -> dict:
    """One target the page just captured: kept the way the scan kept its own.

    ``position`` is where the page drove for it, ``focus`` what the focussing
    before it found (or None when none was asked): both go on the record, so
    a later reading knows at which height the target was imaged and why.
    """
    if not ledgers.acquired["running"]:
        raise RuntimeError("no target run has begun")
    record = asked["record"]
    # The interface's own grouping, from what it asked for (see ``state.records``).
    record["acquisition_type"] = "targets"
    position = asked.get("position") or {}
    record["requested_position_um"] = {
        "x": float(position.get("x", 0.0)), "y": float(position.get("y", 0.0)),
        "z": float(position.get("z", 0.0)),
    }
    # When the frame was taken: a rerun rewrites the same label, and the
    # page tells the new pixels from the old by this.
    record["taken"] = time.time()
    record["focus"] = asked.get("focus")
    stage.the_stage_was_sent_to(
        record["requested_position_um"]["x"], record["requested_position_um"]["y"],
        record["requested_position_um"]["z"],
    )
    with state.the_instruments_turn:
        output.move_record_images(record, prepare_acquisition(state.the_run(), "targets"))
    pictures.keep_position_as_zarr(record, "targets")
    records = state.records.setdefault("targets", [])
    replaced = next(
        (at for at, old in enumerate(records)
         if old.get("position_label") == record.get("position_label")),
        None,
    )
    if replaced is None:
        records.append(record)
    else:
        records[replaced] = record
    ledgers.acquired["records"].append(record)
    ledgers.acquired["done"] = len(ledgers.acquired["records"])
    return record


def end_target_run(asked: dict) -> dict:
    """The page ends the run, stopped by its hand or complete."""
    ledgers.acquired.update(running=False, stopped=bool(asked.get("stopped")))
    return dict(ledgers.acquired)


def the_target_run(since: int | None = None) -> dict:
    """The target run under way or last finished, with the records landed so
    far; asked ``since`` the number a page holds, only the ones after."""
    answer = dict(ledgers.acquired)
    if since is not None:
        answer["records"] = answer["records"][max(0, since):]
    return answer


def raise_target(asked: dict) -> dict:
    """Put one acquired target's frame on top of its neighbours.

    Publish overlap order; the shared viewer recomposes affected chunks without
    rewriting the original position store.
    """
    label = str(asked.get("position_label", ""))
    record = next((one for one in state.records.get("targets", []) if one.get("position_label") == label), None)
    if record is None:
        raise ValueError(f"no acquired target is labelled {label!r}")
    folder = state.the_run() / "positions" / "targets"
    viewer_service.raise_position("targets", folder, Path(record["zarr"]))
    return {"raised": label}
