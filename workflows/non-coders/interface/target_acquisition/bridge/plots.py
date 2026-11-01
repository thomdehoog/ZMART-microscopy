"""The population: its one table on disk, and the multidimensional plots drawn over it.

A plot (``pca`` or ``umap``) is a ZMART-analysis pipeline run by the warm
analysis in an environment of its own, so the picture server beside it
never waits; the page polls, then asks for the two columns by object id.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from ..analysis import warm
from ..storage.output import run_hash
from . import ledgers, state


def the_population_table() -> Path:
    """Where the whole overview's population table is written."""
    records = state.records.get("overview") or []
    if not records:
        raise RuntimeError("no overview has been scanned")
    return state.the_run() / "overview" / "analysis" / f"overview_{run_hash(state.the_run())}_objects.csv"


#: The ZMART-analysis pipeline that draws a multidimensional plot of the
#: population, and the two plots it draws with the columns each lands as.
PLOTS_PIPELINE = "reduce_dimensions"


PLOT_KINDS = {"pca": ("pca_1", "pca_2"), "umap": ("umap_1", "umap_2")}


def compute_plot(asked: dict) -> dict:
    """Start a multidimensional plot over the detected population.

    ``kind`` is ``pca`` or ``umap``; ``ids`` narrows the population to the
    objects the page names (the targets in the gates), or is left out for
    every candidate. The plot is a ZMART-analysis pipeline, run by the warm
    analysis detection runs through, in an environment of its own, so the
    picture server beside it never waits; the page polls, then asks for the
    columns.
    """
    if ledgers.plots["running"]:
        raise RuntimeError("a plot is already being computed")
    if ledgers.targets["running"]:
        raise RuntimeError("the objects are still being detected; plot them once detection ends")
    table = the_population_table()
    if not table.is_file():
        raise RuntimeError("detect the whole overview first: a plot is drawn over its population")
    kind = str(asked.get("kind"))
    if kind not in PLOT_KINDS:
        raise ValueError(f"unknown plot {kind!r}; there are {', '.join(PLOT_KINDS)}")
    ids = asked.get("ids")
    ids = None if ids is None else [str(one) for one in ids]
    ledgers.plots_stop["asked"] = False
    what = "UMAP" if kind == "umap" else "principal components"
    ledgers.plots.update(
        running=True, kind=kind, error=None, stopped=False, kinds=[], took_s=None, objects=None,
        of=None if ids is None else len(ids),
        doing=f"computing {what} over {'every candidate' if ids is None else f'{len(ids)} objects'}",
    )
    threading.Thread(target=plot_worker, args=(kind, table, ids), daemon=True).start()
    return dict(ledgers.plots)


def plot_through_the_analysis(kind: str, table: Path, ids: list[str] | None) -> dict:
    """One plot through the warm analysis: what the step published."""
    given = {"table": str(table), "kind": kind, "ids": ids}
    return warm.the_analysis().run(PLOTS_PIPELINE, given)["reduce_dimensions"]


def plot_worker(kind: str, table: Path, ids: list[str] | None) -> None:
    began = time.perf_counter()
    try:
        answered = plot_through_the_analysis(kind, table, ids)
        ledgers.plots.update(kinds=sorted(answered["written"]), objects=answered["objects"])
    except Exception as why:  # noqa: BLE001 -- the page shows the sentence
        if ledgers.plots_stop["asked"]:
            # The hand that stopped the plot put its worker down; that death
            # is the stop, not a failure.
            ledgers.plots["stopped"] = True
        else:
            ledgers.plots["error"] = str(why)
    finally:
        ledgers.plots.update(running=False, doing=None, took_s=round(time.perf_counter() - began, 1))


def stop_plot() -> dict:
    """The operator's Interrupt for a plot: its worker is put down, the only
    hand that reaches a computation already under way. The workers respawn
    on the next job."""
    ledgers.plots_stop["asked"] = True
    if ledgers.plots["running"]:
        warm.close()
    return dict(ledgers.plots)


def plot_columns(kind: str) -> dict:
    """The last plot of *kind*, as the page merges it into its objects."""
    import csv  # noqa: PLC0415 -- the population table's writer imports it the same way

    if kind not in PLOT_KINDS:
        raise ValueError(f"unknown plot {kind!r}")
    table = the_population_table()
    written = table.with_name(table.name.replace("_objects.csv", f"_{kind}.csv"))
    if not written.is_file():
        raise RuntimeError(f"no {kind} plot has been computed")
    with written.open(encoding="utf-8", newline="") as source:
        rows = csv.reader(source)
        header = next(rows)
        ids, first, second = [], [], []
        for an_id, a, b in rows:
            ids.append(an_id)
            first.append(float(a))
            second.append(float(b))
    return {"columns": header[1:], "ids": ids, "values": [first, second]}


def keep_the_population(fields: list) -> None:
    """Every object of the overview in one table, beside the per-field files.

    Gating reads every object's features together, and a script gating
    without the window needs the same: one row an object, one column a
    feature, the union of what any field measured, blank where a field did
    not. Written once, when the whole overview has been run; a settings
    test on one field is not the population and leaves it alone.
    """
    import csv  # noqa: PLC0415 -- the only use in this module

    where = state.the_run() / "overview" / "analysis"
    where.mkdir(parents=True, exist_ok=True)
    measured = sorted({
        name for result in fields for cell in result["cells"]
        for name in (cell.get("features") or {})
    })
    columns = ["field", "position_label", "id", "x_um", "y_um", "area", "intensity", "r", *measured]
    with (where / f"overview_{run_hash(state.the_run())}_objects.csv").open(
        "w", encoding="utf-8", newline=""
    ) as out:
        table = csv.DictWriter(out, fieldnames=columns)
        table.writeheader()
        for result in sorted(fields, key=lambda one: one["field"]):
            for cell in result["cells"]:
                table.writerow({
                    "field": result["field"], "position_label": result["position_label"],
                    "id": cell["id"], "x_um": cell["x"], "y_um": cell["y"],
                    "area": cell.get("area"), "intensity": cell.get("intensity"), "r": cell.get("r"),
                    **(cell.get("features") or {}),
                })
