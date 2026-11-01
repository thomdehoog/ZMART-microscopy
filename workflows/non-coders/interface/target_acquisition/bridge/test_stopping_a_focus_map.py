"""The operator's Interrupt reaches a focus point whose scoring has hung.

From the review of 10 October, finding 16: the page's Interrupt only set a
flag that the page reads between two points. A point whose scoring never
answered (an analysis worker that stopped responding) kept the request open
for ever, the focus map stayed "running", and every scan and new map was
refused until the operator reconnected. Stopping discovery already puts the
analysis workers down; stopping a focus map now does the same.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest

from zmart_interface.framework.bridge import server, workflows

from . import focus, ledgers

STOP = ("POST", "/api/target_acquisition/focus/stop")


@pytest.fixture(autouse=True)
def the_workflows_routes(monkeypatch):
    """The bridge's routes with the built-in workflows' halves loaded, as at start-up."""
    monkeypatch.setattr(server, "ROUTES", dict(server.ROUTES))
    workflows.load_halves(server.add_route)


def test_stopping_a_running_map_puts_the_analysis_workers_down(monkeypatch):
    closed = []
    monkeypatch.setattr(focus.warm, "close", lambda: closed.append(True))
    monkeypatch.setitem(ledgers.focus, "running", True)
    answer = server.ROUTES[STOP]({}, "")
    assert closed == [True]
    assert answer["running"] is True, "the page still ends the map itself"


def test_stopping_when_no_map_runs_leaves_the_workers_alone(monkeypatch):
    closed = []
    monkeypatch.setattr(focus.warm, "close", lambda: closed.append(True))
    monkeypatch.setitem(ledgers.focus, "running", False)
    server.ROUTES[STOP]({}, "")
    assert closed == []
