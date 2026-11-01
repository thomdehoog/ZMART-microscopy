"""The stage is never sent to a height nobody reported, and a malformed reading is still read.

From the review of 10 October:

- Finding 9. A double-click drive names only x and y, and the axes it leaves
  out stay where the stage reports them. A driver that reported no z got
  ``set_xyz(x, y, 0.0)``: an absolute move to z = 0, the objective's own
  zero. The overview scan already refused to invent a height; the drive now
  does too.
- Finding 19, in part. ``setting?type=a=b`` answered in Python's own words
  ("dictionary update sequence element #0 ..."); it is read as far as it goes.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest

from zmart_interface.framework.bridge import server, workflows
from zmart_interface.framework.test_plain_answers import answered

from ..microscope.instrument import Instrument
from . import readings, stage, state


class Stage:
    """A stage that reports only the axes it is given, and remembers every move."""

    def __init__(self, **standing):
        self.context = {"driver": "stub"}
        self.standing = standing
        self.moves = []

    def get_xyz(self):
        return {"success": True, "output": {axis: {"position": v} for axis, v in self.standing.items()}}

    def set_xyz(self, x, y, z):
        self.moves.append((x, y, z))
        return {"success": True, "output": {"x": {"position": x}, "y": {"position": y}, "z": {"position": z}}}


def test_a_drive_never_sends_the_objective_to_a_height_nobody_reported(monkeypatch):
    held = Stage(x=0.0, y=0.0)
    monkeypatch.setattr(state, "session", Instrument(held))
    with pytest.raises(RuntimeError, match="does not say where the z axis stands"):
        stage.drive_to({"x": 100.0, "y": 200.0})
    assert held.moves == []


def test_a_drive_keeps_every_axis_it_was_not_asked_to_move(monkeypatch):
    held = Stage(x=1.0, y=2.0, z=-380.0)
    monkeypatch.setattr(state, "session", Instrument(held))
    stage.drive_to({"x": 100.0, "y": None})
    assert held.moves == [(100.0, 2.0, -380.0)]


def test_a_drive_to_something_that_is_not_a_number_says_so(monkeypatch):
    held = Stage(x=1.0, y=2.0, z=3.0)
    monkeypatch.setattr(state, "session", Instrument(held))
    with pytest.raises(ValueError, match="x must be a number of micrometres, not 'left'"):
        stage.drive_to({"x": "left"})
    assert held.moves == []


def test_a_reading_asked_with_a_malformed_query_is_read_as_far_as_it_goes(monkeypatch):
    monkeypatch.setattr(server, "ROUTES", {})
    workflows.load_halves(server.add_route)
    asked = []
    monkeypatch.setattr(readings, "reading", lambda kind: asked.append(kind) or {"kind": kind})
    monkeypatch.setattr(state, "session", object())
    status, said = answered("GET", "/api/target_acquisition/setting?type=a=b&other")
    assert status == 200
    assert asked == ["a=b"]
