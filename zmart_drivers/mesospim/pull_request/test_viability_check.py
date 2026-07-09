"""Regression test for the bench VIABILITY CHECK (``demo_client.py --self-check``).

Stands up the REAL server (rebuilt from the patch) on both lanes -- framed TCP plus the
actual MCP-over-HTTP handler forwarding to it -- against a recording fake Core, then runs
the self-check exactly as an operator would right after pressing Start. It asserts the
check reports PASS and, crucially, that the out-of-limit probe left the Core with **zero
moves** -- i.e. proving "a limit cannot be violated" never itself moves the stage. Uses
real localhost sockets but no Qt / mesoSPIM / ZMART. Run::

    pytest pull_request/test_viability_check.py
    python  pull_request/test_viability_check.py

License: MIT (test-side; imports nothing from mesoSPIM).
"""
from __future__ import annotations

import importlib.util
import socket
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from test_remote_control import _Cfg, srv  # rebuilt-from-patch server + fake cfg

_DC = Path(__file__).with_name("demo_client.py")
_spec = importlib.util.spec_from_file_location("demo_client", _DC)
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)

_TOKEN = "sekret"


class _RecordingCore:
    def __init__(self):
        self.cfg = _Cfg()
        self.moved = []
        self.state = {"state": "idle",
                      "position": {a + "_pos": 0.0 for a in ("x", "y", "z", "f", "theta")}}

    def move_absolute(self, sdict, wait_until_done=False):
        self.moved.append(sdict)
        for k, v in sdict.items():
            self.state["position"][k.replace("_abs", "") + "_pos"] = v


def _serve_tcp(core, token):
    """A minimal framed-TCP server using the real srv helpers (like the in-Core one)."""
    listen = socket.socket()
    listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen.bind(("127.0.0.1", 0))
    listen.listen(5)
    listen.settimeout(10)  # bound every server-side wait so a stuck test fails fast, never hangs
    port = listen.getsockname()[1]

    def handle(conn):
        conn.settimeout(10)
        dec, gate = srv.FrameDecoder(), srv.AuthGate(token)
        with conn:
            while True:
                try:
                    data = conn.recv(4096)
                except OSError:
                    return
                if not data:
                    return
                dec.feed(data)
                for fr in dec.frames():
                    text = fr.decode("utf-8")
                    if not gate.passed:
                        conn.sendall(srv.frame("OK" if gate.check(text) else "AUTH-FAILED"))
                    else:
                        conn.sendall(srv.frame(srv.handle_tcp_message(core, text)))

    def serve():
        while True:
            try:
                conn, _ = listen.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return listen, port


def test_self_check_passes_and_stage_never_moves():
    core = _RecordingCore()
    listen, tcp_port = _serve_tcp(core, _TOKEN)
    cfg = SimpleNamespace(token=_TOKEN, quiet=True, timeout=5.0,
                          mesospim_host="127.0.0.1", mesospim_port=tcp_port, mesospim_token=_TOKEN)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_mcp_handler(cfg))
    mcp_port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        ok = dc.self_check("127.0.0.1", tcp_port, _TOKEN, mcp_port=mcp_port, mcp_token=_TOKEN)
    finally:
        httpd.shutdown()
        listen.close()
    assert ok is True                 # both lanes up, both refused the out-of-limit probe
    assert core.moved == []           # and the stage never moved -- the whole point


if __name__ == "__main__":
    test_self_check_passes_and_stage_never_moves()
    print("ok   test_self_check_passes_and_stage_never_moves")
    print("\nVIABILITY CHECK TEST PASSED")
