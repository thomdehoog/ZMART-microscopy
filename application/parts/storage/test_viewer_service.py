"""The viewer beside a run is asked what it can promise before it is used.

Once the writer stops measuring a display window for every position, an older
Viewer would fill the gap with the camera's whole range and every real
acquisition would open very nearly black. So :func:`viewer_service.start` asks
the server it just started what it promises, and refuses the integrated canvas
with a plain upgrade sentence when the answer is not enough. These checks stand
in a small HTTP server for the Viewer, so they say nothing about the real
package and everything about the handshake.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from application.parts.storage import viewer_service


def _a_pretend_viewer(health: dict):
    """An HTTP server whose only opinion is what /api/health says."""

    class Answering(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 -- http.server's naming
            body = json.dumps(health).encode()
            self.send_response(200 if self.path.startswith("/api/health") else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return HTTPServer(("127.0.0.1", 0), Answering)


@pytest.fixture
def fresh():
    """The service's module state, clean before and after."""
    viewer_service.stop()
    yield
    viewer_service.stop()


def _start_beside(monkeypatch, tmp_path, health: dict) -> dict:
    import types

    made = _a_pretend_viewer(health)
    pretend = types.SimpleNamespace(make_server=lambda **_: made)
    monkeypatch.setitem(__import__("sys").modules, "zmart_viewer", types.SimpleNamespace(server=pretend))
    monkeypatch.setitem(__import__("sys").modules, "zmart_viewer.server", pretend)
    monkeypatch.setattr(viewer_service, "_allow_the_page_to_read", lambda _server: None)
    viewer_service.start(tmp_path)
    return viewer_service.status()


def test_a_viewer_that_promises_both_is_used(monkeypatch, tmp_path, fresh):
    told = _start_beside(monkeypatch, tmp_path, {
        "ok": True, "version": "0.3.0",
        "capabilities": list(viewer_service.THE_VIEWER_MUST_PROMISE),
    })
    assert told["running"] is True
    assert told["error"] is None


def test_a_viewer_that_promises_neither_is_refused_with_an_upgrade_sentence(
    monkeypatch, tmp_path, fresh,
):
    """Exactly the shape a 0.2.0 Viewer answers: ``{"ok": true}`` and nothing else."""
    told = _start_beside(monkeypatch, tmp_path, {"ok": True})
    assert told["running"] is False
    assert "too old" in told["error"]
    assert "acquisition-display-window-v1" in told["error"]
    assert "absent-display-window-v1" in told["error"]
    assert "zmart-viewer" in told["error"]


def test_one_promise_is_not_enough(monkeypatch, tmp_path, fresh):
    told = _start_beside(monkeypatch, tmp_path, {
        "ok": True, "capabilities": ["acquisition-display-window-v1"],
    })
    assert told["running"] is False
    # The sentence names only what is missing, so the operator is told what
    # to look for and not sent chasing a promise the Viewer already keeps.
    named = told["error"].split("promise ", 1)[1].split(".")[0]
    assert named == "absent-display-window-v1"


def _refuses_connections(port: int) -> bool:
    """True when nothing is listening: the kernel refuses, rather than accepting and idling."""
    import socket

    with socket.socket() as probe:
        probe.settimeout(2)
        try:
            probe.connect(("127.0.0.1", port))
        except ConnectionRefusedError:
            return True
        except OSError:
            return False
        return False


def test_a_refused_viewer_is_stopped_and_its_socket_closed(monkeypatch, tmp_path, fresh):
    """The refusal shuts the server it started and closes the socket.

    A socket left open after the refusal accepts connections that nobody
    answers; a check that only waited for a timeout would pass over that. So
    the check is that the kernel refuses outright.
    """
    made = _a_pretend_viewer({"ok": True})
    port = made.server_address[1]
    import types
    pretend = types.SimpleNamespace(make_server=lambda **_: made)
    monkeypatch.setitem(__import__("sys").modules, "zmart_viewer", types.SimpleNamespace(server=pretend))
    monkeypatch.setitem(__import__("sys").modules, "zmart_viewer.server", pretend)
    monkeypatch.setattr(viewer_service, "_allow_the_page_to_read", lambda _server: None)
    viewer_service.start(tmp_path)
    assert viewer_service.status()["running"] is False
    assert _refuses_connections(port)


def test_an_answer_of_an_unexpected_shape_is_no_promise_and_leaks_no_server(
    monkeypatch, tmp_path, fresh,
):
    """A capabilities list of the wrong shape must not escape as an exception.

    It used to: a list of objects reached ``set(...)``, raised, and the server
    thread kept running where ``stop()`` could not reach it.
    """
    made = _a_pretend_viewer({"ok": True, "capabilities": [{"name": "acquisition-display-window-v1"}]})
    port = made.server_address[1]
    import types
    pretend = types.SimpleNamespace(make_server=lambda **_: made)
    monkeypatch.setitem(__import__("sys").modules, "zmart_viewer", types.SimpleNamespace(server=pretend))
    monkeypatch.setitem(__import__("sys").modules, "zmart_viewer.server", pretend)
    monkeypatch.setattr(viewer_service, "_allow_the_page_to_read", lambda _server: None)
    viewer_service.start(tmp_path)
    told = viewer_service.status()
    assert told["running"] is False
    assert "too old" in told["error"]
    assert _refuses_connections(port)


def test_a_viewer_that_does_not_answer_is_not_called_too_old(monkeypatch, tmp_path, fresh):
    """No answer is a different fact from an old answer, and gets its own sentence."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Silent(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_):
            pass

    made = HTTPServer(("127.0.0.1", 0), Silent)
    import types
    pretend = types.SimpleNamespace(make_server=lambda **_: made)
    monkeypatch.setitem(__import__("sys").modules, "zmart_viewer", types.SimpleNamespace(server=pretend))
    monkeypatch.setitem(__import__("sys").modules, "zmart_viewer.server", pretend)
    monkeypatch.setattr(viewer_service, "_allow_the_page_to_read", lambda _server: None)
    viewer_service.start(tmp_path)
    told = viewer_service.status()
    assert told["running"] is False
    assert "did not answer" in told["error"]
    assert "too old" not in told["error"]
