"""The overview scan, run in a background thread: drive to each position, capture, keep the record.

Started by the page with the positions and the recorded preset, polled for
its progress, and asked to stop between two fields on the operator's
Interrupt. What each capture wrote is kept in ``state.records``, because
nothing else can reconstruct it.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import sys
import threading
import time

from ..microscope.focus_run import as_state
from ..storage import output
from ..storage.output import position_label, prepare_acquisition
from . import ledgers, pictures, stage, state


def scan_worker(
    positions: list, acquisition_type: str = "overview", recorded: dict | None = None,
    *, session=None, run=None,
) -> None:
    """Drive to each position, capture, and keep what came back.

    The records are kept because nothing else can reconstruct them: where a
    run lands is knowable in advance, what each capture wrote is not. They
    were dropped on the floor here, so a run could be caused and never
    accounted for.

    The scan belongs to the session and the run folder that were open when
    it started. It used to look both up afresh for every field, so a page
    that connected again in the middle of a scan handed the old scan the new
    session: it kept moving the stage and wrote into the new run. Now it
    stops, between two fields, as soon as its session is no longer the open
    one. ``session`` and ``run`` are the ones the scan was started with;
    left out, they are the ones open now.
    """
    standing = None
    # What polling this invocation reports. The durable acquisition records
    # may also contain frames retained while one selected target is rerun.
    ledgers.scan["records"] = []
    try:
        session = session or state.require_session()
        run = run or state.the_run()
        if recorded:
            # The recorded configuration for this kind of scan, applied once
            # before the first drive. ``set_state`` returns once the
            # instrument has taken it, or raises -- recording it and never
            # applying it captured everything with whatever job happened to
            # be selected.
            with state.the_instruments_turn:
                session.set_state(as_state(recorded))
        for i, position in enumerate(positions):
            if ledgers.stop_asked["scan"]:
                # Between two fields, on the operator's say-so: what was
                # captured stands, and no further stage move is made.
                ledgers.scan["stopped"] = True
                break
            with state.the_instruments_turn:
                if state.session is not session:
                    ledgers.scan["stopped"] = True
                    ledgers.scan["error"] = (
                        "the scan stopped because its session was closed or another was opened; "
                        "what it captured before that is kept"
                    )
                    break
                z = position.get("z")
                if z is None:
                    # A position that names no height means "image where the
                    # objective stands", read once. It defaulted to 0.0 -- an
                    # absolute drive to the frame's z-zero for every field of
                    # every scan, while the panel above reported a measured
                    # focus map.
                    if standing is None:
                        standing = float(session.get_xyz()["z"]["position"])
                    z = standing
                session.set_xyz(float(position["x"]), float(position["y"]), float(z))
                stage.the_stage_was_sent_to(position["x"], position["y"], z)
                record = session.acquire(
                    position_label=label_for(i, position), acquisition_type=acquisition_type,
                )
                # Filed under what this scan asked for, not under anything the
                # driver answered: the grouping is the interface's own.
                record["acquisition_type"] = acquisition_type
                record["requested_position_um"] = {
                    "x": float(position["x"]),
                    "y": float(position["y"]),
                    "z": float(z),
                }
                # When the frame was taken: a rerun rewrites the same label,
                # and the page tells the new pixels from the old by this.
                record["taken"] = time.time()
                output.move_record_images(record, prepare_acquisition(run, acquisition_type))
            if record.get("timing_s"):
                # Where the seconds of this site went, as the driver clocked them.
                print(
                    f"site {i + 1}/{len(positions)} timing_s: "
                    + " ".join(f"{k}={v}" for k, v in record["timing_s"].items()),
                    file=sys.stderr,
                    flush=True,
                )
            # Outside the instrument's turn: the conversion reads files the
            # capture already wrote, and holding the lock for it would keep
            # the stage waiting on disk work.
            pictures.keep_position_as_zarr(record, acquisition_type)
            records = state.records.setdefault(acquisition_type, [])
            replaced = next(
                (at for at, old in enumerate(records)
                 if old.get("position_label") == record.get("position_label")),
                None,
            )
            if replaced is None:
                records.append(record)
            else:
                records[replaced] = record
            ledgers.scan["records"].append(record)
            ledgers.scan["done"] = i + 1
    except Exception as why:  # noqa: BLE001 — the window shows the sentence
        ledgers.scan["error"] = str(why)
    finally:
        ledgers.scan["running"] = False


def label_for(index: int, position: dict) -> str:
    """Where on the sample this capture is, in the workflow's own label.

    It was a running index, ``pos_00000``, which names nothing: a file called
    that cannot be traced back to a well. The caller says which compartment
    and which group a position belongs to — it drew them — and what it leaves
    out is zero, which is honest about not knowing rather than invented.
    """
    return position_label(
        int(position.get("position_index", index)),
        carrier=int(position.get("carrier", 0)),
        compartment=int(position.get("compartment", 0)),
        group=int(position.get("group", 0)),
        view=int(position.get("view", 0)),
    )


#: Held while a scan is being started, so that two requests that arrive
#: together cannot both find "nothing running" and start two scans that take
#: turns moving the stage.
starting = threading.Lock()


def start_scan(asked: dict) -> dict:
    with starting:
        return start_one_scan(asked)


def start_one_scan(asked: dict) -> dict:
    # The name first: it arrives from the page and decides what is deleted below.
    acquisition_type = output.checked_name(
        asked.get("acquisition_type", "overview"), field="acquisition_type",
    )
    if ledgers.scan["running"]:
        raise RuntimeError("a scan is already running")
    if ledgers.focus["running"]:
        raise RuntimeError("a focus map is being measured; the stage is its until it ends")
    if ledgers.acquired["running"]:
        raise RuntimeError("the targets are being taken; the stage is theirs until the run ends")
    state.require_session()
    positions = asked.get("positions", [])
    state.records[acquisition_type] = []
    pictures.replace_the_acquisition(
        acquisition_type,
        keeping={f"{acquisition_type}_{label_for(i, p)}.ome.zarr" for i, p in enumerate(positions)},
    )
    for key in [key for key in state.displayed_pictures if key[0] == acquisition_type]:
        del state.displayed_pictures[key]
    ledgers.stop_asked["scan"] = False
    planned = asked.get("planned") or positions
    ledgers.scan.update(
        running=True, done=0, of=len(positions), error=None, stopped=False,
        acquisition_type=acquisition_type, records=[],
        planned=[(float(p.get("x", 0.0)), float(p.get("y", 0.0))) for p in planned],
    )
    threading.Thread(
        target=scan_worker, args=(positions, acquisition_type, asked.get("state")),
        kwargs={"session": state.require_session(), "run": state.the_run()}, daemon=True,
    ).start()
    return the_scan()


def stop_scan() -> dict:
    """The operator's Interrupt: ask the scan to stop between two fields.

    The flag is all this does; the worker reads it before each drive, so the
    field being captured completes and is kept. Idempotent, and harmless
    when nothing runs.
    """
    ledgers.stop_asked["scan"] = True
    return the_scan()


def the_scan(since: int | None = None) -> dict:
    """The scan under way or last finished, with what it has captured so far.

    A page that polls while the scan runs already holds the records it was
    given last time; asked ``since`` that many, it gets only the ones that
    landed after. Every record rides along otherwise, so a run can always be
    accounted for from one answer.
    """
    answer = dict(ledgers.scan)
    if since is not None:
        answer["records"] = answer["records"][max(0, since):]
    return answer
