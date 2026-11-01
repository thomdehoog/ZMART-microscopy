"""Target acquisition's ledgers: what each of its runs has done so far.

One dictionary per run, updated in place and read through this module
(``ledgers.scan``, never a copied name), so a value one module sets is the
value the next one sees and the page that polls reads. ``focus`` is the
focus map, ``scan`` the overview scan, ``targets`` discovery, ``acquired``
the target run and ``plots`` the population plots.

What every run *captured* is the bridge's general record
(``state.records``, by kind of acquisition); these are only how far each
run has got.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

#: The focus map under way, the bridge's ledger of what the page has had
#: scored so far, in the order the page asked. Polled by a page that reopens,
#: and read by the tests that watch a map fill in.
focus = {
    "running": False, "done": 0, "of": 0, "error": None, "stopped": False,
    "points": [],
}

#: The overview scan under way or last finished: how far it is, what it has
#: captured, and the centres it was planned over.
scan = {
    "running": False, "done": 0, "of": 0, "error": None, "stopped": False,
    "acquisition_type": None, "records": [],
    "planned": [],
}

#: Discovery under way, polled by the page the way the scan is. Each field is
#: appended as its targets are found, so the page can draw them while the
#: rest of the overview is still being looked at.
targets = {
    "running": False, "done": 0, "of": 0, "error": None, "stopped": False,
    "fields": [], "failed": [], "phase": None, "objects": 0,
}

#: The target run under way, the bridge's ledger of what the page has landed
#: so far, in the order the page took it. Polled by a page that reopens.
acquired = {
    "running": False, "done": 0, "of": 0, "error": None, "stopped": False,
    "records": [],
}

#: The multidimensional plot under way or last finished, polled by the page.
plots = {
    "running": False, "kind": None, "error": None, "stopped": False,
    "kinds": [], "doing": None, "took_s": None, "of": None, "objects": None,
}

#: The operator's hand on the brake, one per procedure the bridge runs on
#: its own. Set by the stop routes, read by the workers between two fields
#: -- never mid-capture: the capture in flight completes and is kept,
#: because a field interrupted halfway is a file nobody can account for.
#: The focus map has no brake here: the page drives it, and stops itself.
stop_asked = {"scan": False, "targets": False}
plots_stop = {"asked": False}


def a_run_has_the_stage() -> bool:
    """Whether a focus map, a scan, discovery or a target run is under way.

    For as long as one is, its own record of where it sent the stage is the
    stage's clock, even between two sites when the instrument's turn is
    free: a position read right after a move can still report the site
    before, and the mark jumped back and forth on that stale answer.
    """
    return any(run.get("running") for run in (focus, scan, targets, acquired))


def forget() -> None:
    """A fresh session has run nothing: every ledger back to empty."""
    scan.update(
        running=False, done=0, of=0, error=None, stopped=False,
        acquisition_type=None, records=[], planned=[],
    )
    focus.update(running=False, done=0, of=0, error=None, points=[])
    acquired.update(running=False, done=0, of=0, error=None, stopped=False, records=[])
    targets.update(
        running=False, done=0, of=0, error=None, stopped=False, fields=[],
        failed=[], doing=None, phase=None, objects=0,
    )
