"""Connecting again while a scan is running hands the stage over cleanly.

A page that is reloaded connects again, and the bridge outlives the page.
Before these tests, the new connection reset the scan's record to "not
running" while the old scan carried on: it went on moving the stage, wrote
its pictures into the new run folder, and a second scan could be started
beside it, so two scans took turns moving the stage. The session it was
using was never closed.

Now connecting again first asks the running scan to stop between two fields
and waits for it, then closes the old session, and only then opens the new
one. A scan also stops on its own when the session it started with is no
longer the open one.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import threading
import time

import pytest

from .. import mock_microscope
from ..microscope.instrument import Instrument
from . import connect, connecting, ledgers, pictures, scan, state


class Stage:
    """A stub microscope that answers in the controller's two-part shape and remembers every move."""

    def __init__(self, name, *, pause_s=0.0, on_capture=None):
        self.context = {"driver": name}
        self.moves = []
        self.captures = 0
        self.closed = False
        self.pause_s = pause_s
        self.on_capture = on_capture

    def get_xyz(self):
        return {"success": True, "output": {axis: {"position": 0.0} for axis in "xyz"}}

    def set_xyz(self, x, y, z):
        time.sleep(self.pause_s)
        self.moves.append((x, y, z))
        return {"success": True, "output": {"x": {"position": x}, "y": {"position": y}, "z": {"position": z}}}

    def acquire(self, *, position_label, acquisition_settings, acquisition_type, output_folder):
        self.captures += 1
        if self.on_capture is not None:
            self.on_capture(self.captures)
        return {"success": True, "output": {"position_label": position_label, "planes": [], "files": []}}

    def get_acquisition_settings(self):
        return {"success": True, "output": {}}

    def disconnect(self):
        self.closed = True


@pytest.fixture(autouse=True)
def a_run_without_pictures(tmp_path, monkeypatch):
    """A run folder, and no picture-making: these tests are about who holds the stage."""
    run = tmp_path / "target-acquisition_000001"
    run.mkdir()
    monkeypatch.setattr(state, "run", run)
    monkeypatch.setattr(state, "output_root", str(tmp_path))
    monkeypatch.setattr(state, "records", {})
    monkeypatch.setattr(scan.output, "move_record_images", lambda record, data: record)
    monkeypatch.setattr(pictures, "keep_position_as_zarr", lambda record, kind: None)
    monkeypatch.setattr(pictures, "replace_the_acquisition", lambda kind, keeping=frozenset(): None)
    ledgers.scan.update(running=False, stopped=False, error=None)
    ledgers.stop_asked["scan"] = False
    yield run
    ledgers.stop_asked["scan"] = False


def a_row_of(count):
    return [{"x": float(i), "y": 0.0, "z": 1.0} for i in range(count)]


def test_a_scan_stops_when_its_session_is_no_longer_the_open_one(monkeypatch):
    newer = Stage("newer")

    def another_session_opens(captures):
        if captures == 2:
            state.session = Instrument(newer)

    older = Stage("older", on_capture=another_session_opens)
    monkeypatch.setattr(state, "session", Instrument(older))
    ledgers.scan.update(running=True)

    scan.scan_worker(a_row_of(6))

    assert older.moves == [(0.0, 0.0, 1.0), (1.0, 0.0, 1.0)]
    assert newer.moves == []
    assert ledgers.scan["running"] is False
    assert ledgers.scan["stopped"] is True
    assert "closed" in ledgers.scan["error"]


def test_connecting_again_stops_the_running_scan_before_the_new_session_opens(monkeypatch):
    older = Stage("older", pause_s=0.02)
    monkeypatch.setattr(state, "session", Instrument(older))
    scan.start_scan({"positions": a_row_of(500)})
    while not older.moves:
        time.sleep(0.01)

    try:
        connect({"instrument": mock_microscope.NAME})
        moved_by_then = len(older.moves)
        time.sleep(0.2)
        assert len(older.moves) == moved_by_then, "the old scan kept moving the stage"
        assert moved_by_then < 500
        assert older.closed is True
        assert ledgers.scan["running"] is False
        assert state.session is not None
        assert state.context["name"] == mock_microscope.NAME
    finally:
        connecting.disconnect()


def test_the_last_session_is_closed_when_another_is_opened(monkeypatch):
    older = Stage("older")
    monkeypatch.setattr(state, "session", Instrument(older))
    try:
        connect({"instrument": mock_microscope.NAME})
        assert older.closed is True
    finally:
        connecting.disconnect()


def test_a_run_folder_that_cannot_be_made_leaves_no_session_open(monkeypatch):
    """Finding 10 of the review: the error left the new session open with no run."""
    monkeypatch.setattr(state, "session", None)
    monkeypatch.setattr(state, "run", None)

    def no_permission(root, name):
        raise PermissionError(f"no permission to write in {root}")

    monkeypatch.setattr(connecting, "prepare_experiment", no_permission)
    closed = []
    monkeypatch.setattr(Instrument, "disconnect", lambda self: closed.append(self))
    with pytest.raises(PermissionError):
        connecting.connect({"instrument": mock_microscope.NAME})
    assert state.session is None
    assert state.run is None
    assert len(closed) == 1


def test_two_scans_asked_for_at_once_start_only_one(monkeypatch):
    held = Stage("held", pause_s=0.02)
    monkeypatch.setattr(state, "session", Instrument(held))
    started, refused = [], []
    gate = threading.Barrier(8)

    def ask():
        gate.wait()
        try:
            scan.start_scan({"positions": a_row_of(20)})
            started.append(1)
        except RuntimeError:
            refused.append(1)

    askers = [threading.Thread(target=ask) for _ in range(8)]
    for one in askers:
        one.start()
    for one in askers:
        one.join()
    scan.stop_scan()
    while ledgers.scan["running"]:
        time.sleep(0.01)
    assert len(started) == 1
    assert len(refused) == 7
