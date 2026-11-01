"""Finding the targets in the overview's fields, through the warm analysis.

Started by the page over every field or the ones named, polled like the
scan with each field's targets appended as they are found, and stopped on
the operator's Interrupt by putting the analysis workers down. What was
found is written beside the field it was found in, and the whole
population into one table when the whole overview was run.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import threading

from ..analysis import detection, warm
from ..storage.output import free_name
from . import ledgers, plots, state


def find_targets():
    """The finder for this session: detection through the warm analysis, each
    field read from its own store. Built when discovery starts rather than at
    import, so the bridge loads with no analysis installed."""
    return detection.through(warm.the_analysis())


def discover_targets(asked: dict) -> dict:
    """Start detection over the overview: every field, or only the ones named.

    ``fields`` names the overview's fields by index -- one, to try settings on
    before the whole sample is run -- and left out means all of them.
    """
    if ledgers.targets["running"]:
        raise RuntimeError("targets are already being discovered")
    records = state.records.get("overview", [])
    if not records:
        raise RuntimeError("no overview has been scanned, so there is nothing to find targets in")
    chosen = asked.get("fields")
    fields = list(range(len(records))) if chosen is None else [int(field) for field in chosen]
    ledgers.stop_asked["targets"] = False
    ledgers.targets.update(
        running=True, done=0, of=len(fields), error=None, stopped=False,
        fields=[], failed=[], doing=None, phase="objects", objects=0,
    )
    threading.Thread(
        target=targets_worker,
        args=(fields, dict(asked.get("settings") or {}), chosen is None),
        daemon=True,
    ).start()
    return dict(ledgers.targets)


def targets_worker(fields: list, settings: dict, whole: bool) -> None:
    """Every feature is measured inside a field's own pipeline, so discovery
    is complete when its last field lands: nothing is computed over the
    whole population after them. A map of every cell's features (UMAP) once
    was, and went -- it grew with the population and gave automation nothing
    a threshold on a measured column does not. What the population does get
    is its one table on disk, when the *whole* overview was run.
    """
    try:
        find = find_targets()
        records = {field: state.records["overview"][field] for field in fields}
        # Fields are independent, so the fast way finds several at once --
        # a second of one CPU each -- and the robust way one at a time,
        # every Cellpose worker holding a model on the card.
        at_once = detection.width_of(settings)

        def what_is_being_done() -> str:
            in_flight = min(at_once, len(fields) - ledgers.targets["done"])
            return (
                f"detecting and measuring objects in {in_flight} "
                f"position{'s' if in_flight != 1 else ''} at once, "
                f"{ledgers.targets['done']} of {len(fields)} done"
            )

        ledgers.targets["doing"] = what_is_being_done()
        stopped = lambda: ledgers.stop_asked["targets"]  # noqa: E731 -- the brake, asked by the finder
        for field, found in find.each(records, settings, at_once=at_once, until=stopped):
            record = records[field]
            if isinstance(found, Exception):
                if ledgers.stop_asked["targets"]:
                    # The hand that stopped the run also put its workers
                    # down; that death is the stop, not a bad field.
                    break
                # One bad field is filed and stepped over, the way the focus
                # map files a lost point: a nine-field run died whole on the
                # one field the pipeline choked on, and nothing short of
                # running everything again could recover it.
                ledgers.targets["failed"].append({"field": field, "why": str(found)})
                ledgers.targets["done"] += 1
                ledgers.targets["doing"] = what_is_being_done()
                continue
            keep_targets(found["cells"], record)
            ledgers.targets["fields"].append({
                "field": field, "position_label": record["position_label"],
                "cells": found["cells"],
                # The device the field was segmented on, for the page to say:
                # a run that fell back to the CPU took ten minutes a field.
                "device": found.get("device"),
            })
            ledgers.targets["objects"] += len(found["cells"])
            ledgers.targets["done"] += 1
            ledgers.targets["doing"] = what_is_being_done()
        if ledgers.stop_asked["targets"]:
            ledgers.targets["stopped"] = True
        # Kept in landing order: a page's cursor into the list holds.
        if whole and ledgers.targets["fields"]:
            plots.keep_the_population(ledgers.targets["fields"])
    except Exception as why:  # noqa: BLE001 -- the window shows the sentence
        if ledgers.stop_asked["targets"]:
            # The hand that stopped the run also put its worker down, and a
            # worker dying of that press is the stop itself, not a failure.
            ledgers.targets["stopped"] = True
        else:
            ledgers.targets["error"] = str(why)
    finally:
        ledgers.targets["running"] = False
        ledgers.targets["doing"] = None
        ledgers.targets["phase"] = "complete"


def stop_targets() -> dict:
    """The operator's Interrupt for discovery: stop now, not at the next field.

    Sets the brake and puts the analysis workers down. Unlike a capture, an
    analysis field in flight loses nothing when it dies -- its pixels are on
    disk and detection re-runs from its own checkpoint -- and killing the
    worker is the only hand that reaches one that has genuinely wedged, now
    that no clock cuts a step short. The workers respawn on the next run.
    """
    ledgers.stop_asked["targets"] = True
    if ledgers.targets["running"]:
        warm.close()
    return dict(ledgers.targets)


def the_targets(since: int | None = None) -> dict:
    """Discovery under way or last finished, with the fields found so far.

    A page that polls while discovery runs already holds the fields it was
    given last time; asked ``since`` that many, it gets only the ones that
    landed after. A poll that carried every field found so far grew with the
    run -- 900 MB at three hundred fields, 26 s to answer, asked three times
    a second -- and that was the whole of what looked like a stalled run.
    """
    answer = dict(ledgers.targets)
    if since is not None:
        answer["fields"] = answer["fields"][max(0, since):]
    return answer


def keep_targets(cells: list, record: dict) -> None:
    """Write what was found beside the field it was found in.

    ``<acquisition>/analysis``, next to the ``data`` the objects came from, the
    way a focus curve is kept: without this the only copy is on the operator's
    screen, and it goes when the window does.
    """
    where = state.the_run() / record["acquisition_type"] / "analysis"
    where.mkdir(parents=True, exist_ok=True)
    kept = free_name(where, f"{record['acquisition_type']}_{record['position_label']}", "_T000000_targets.json")
    kept.write_text(json.dumps(cells, indent=2), encoding="utf-8")
