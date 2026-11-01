"""Closing the window closes the session, the picture server and the bridge.

From the review of 10 October, finding 15: when ``webview.start()`` returned,
the launcher returned too, and the session with the microscope software was
never closed; a driver that holds a client connection to the vendor
software left it hanging until the process was killed. Now the window's
end, however it comes, stops a running scan between two fields, closes the
session (which stops the picture server and the analysis workers), and
shuts the bridge down.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import sys
import types

import pytest

from zmart_interface import launcher
from zmart_interface.framework.bridge import server

from . import connecting, starting


class Listening:
    server_address = ("127.0.0.1", 8601)
    title = "ZMART"

    def __init__(self):
        self.done = []
        self.halves = [("target_acquisition", starting)]

    def shutdown(self):
        self.done.append("shutdown")

    def server_close(self):
        self.done.append("server_close")


@pytest.fixture()
def a_window(monkeypatch, tmp_path):
    """A window that opens and closes at once, over a bridge that only records."""
    events = []
    listening = Listening()
    window = types.SimpleNamespace(
        create_window=lambda *a, **kw: events.append("window"),
        start=lambda **kw: events.append("closed"),
    )
    monkeypatch.setitem(sys.modules, "webview", window)
    monkeypatch.setattr(server, "serve", lambda *a, **kw: listening)
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(server, "THE_PAGE", tmp_path)
    monkeypatch.setattr(connecting, "let_the_last_session_go", lambda wait_s=None: events.append("scan stopped"))
    monkeypatch.setattr(connecting, "disconnect", lambda: events.append("disconnected"))
    return events, listening, window


def test_closing_the_window_closes_the_session_and_the_bridge(a_window):
    events, listening, _ = a_window
    assert launcher.main([]) == 0
    assert events == ["window", "closed", "scan stopped", "disconnected"]
    assert listening.done == ["shutdown", "server_close"]


def test_a_window_that_fails_still_closes_the_session(a_window):
    events, listening, window = a_window

    def broken(**kw):
        raise RuntimeError("the window could not start")

    window.start = broken
    with pytest.raises(RuntimeError, match="could not start"):
        launcher.main([])
    assert events == ["window", "scan stopped", "disconnected"]
    assert listening.done == ["shutdown", "server_close"]


def test_closing_goes_on_when_the_microscope_no_longer_answers(monkeypatch):
    listening = Listening()

    def gone():
        raise ConnectionError("the microscope software has closed")

    monkeypatch.setattr(connecting, "let_the_last_session_go", lambda wait_s=None: None)
    monkeypatch.setattr(connecting, "disconnect", gone)
    server.shut_down(listening)
    assert listening.done == ["shutdown", "server_close"]
