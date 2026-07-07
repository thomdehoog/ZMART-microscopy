"""Minimal test for the Remote Scripting PR -- framing, token, and dispatch.

Self-contained: it rebuilds ``mesoSPIM_RemoteScripting.py`` straight from the
``0001-*.patch`` new-file hunk (one source of truth -- the patch itself), then
checks what the server promises: frames round-trip, the token is enforced in
constant time, and both front ends (a named call and an MCP tools/call) reach the
same allowlist -- with a hostile-payload sweep proving nothing outside it ever
runs. No Qt, no mesoSPIM, no ZMART imports. Run it either way::

    pytest pull_request/test_remote_scripting.py
    python  pull_request/test_remote_scripting.py

License: MIT (test-side; imports nothing from mesoSPIM).
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

_PATCH = Path(__file__).with_name("0001-Add-optional-remote-scripting-server-Tools-Remote-Sc.patch")


def _load():
    """Materialise the patch's new-file body and import it as a module (Qt-free)."""
    lines = _PATCH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("diff --git a/mesoSPIM/src/mesoSPIM_RemoteScripting.py"))
    hunk = next(i for i, ln in enumerate(lines[start:], start) if ln.startswith("@@ ")) + 1
    body = []
    for ln in lines[hunk:]:
        if ln.startswith("diff --git") or ln.startswith("-- "):  # next file / patch trailer
            break
        if ln.startswith("+") and not ln.startswith("++"):
            body.append(ln[1:])
        elif ln.startswith(" "):  # unchanged context line
            body.append(ln[1:])
    tmp = Path(__file__).with_name("_remote_scripting_under_test.py")
    tmp.write_text("\n".join(body), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_rs_under_test", tmp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tmp.unlink()  # the imported module stays live; the temp file is no longer needed
    return mod


rs = _load()


# -- framing: what frame() writes, FrameDecoder reads back ---------------------

def test_frame_is_length_prefixed_bytes():
    # one frame is b"<byte-count>\n" + payload
    assert rs.frame("abc") == b"3\nabc"


def test_frame_counts_bytes_not_characters():
    # "e-acute" is 1 char but 2 UTF-8 bytes; the count must be the byte length
    assert rs.frame("é") == b"2\n\xc3\xa9"


def test_decoder_reassembles_a_split_then_joined_stream():
    # TCP can split one frame and join the next; feed the bytes in awkward chunks
    dec = rs.FrameDecoder()
    dec.feed(b"3\nab")  # first frame arrives half-way
    assert list(dec.frames()) == []  # payload incomplete -> nothing yet
    dec.feed(b"c5\nhello")  # rest of frame 1, then all of frame 2
    assert list(dec.frames()) == [b"abc", b"hello"]  # both peeled off in order


def test_decoder_rejects_a_non_integer_length():
    # a garbage length prefix is a framing error, not a silent hang
    dec = rs.FrameDecoder()
    dec.feed(b"xx\npayload")
    import pytest
    with pytest.raises(rs.FramingError):
        list(dec.frames())


# -- auth: the shared token gate ----------------------------------------------

def test_no_token_is_open_from_the_start():
    # no token configured -> nothing to prove, the gate is already passed
    assert rs.AuthGate().passed is True


def test_right_token_passes_wrong_token_fails():
    gate = rs.AuthGate("s3cret")  # a token is required
    assert gate.passed is False  # ...and not yet satisfied
    assert gate.check("nope") is False  # wrong guess is rejected
    assert gate.check("s3cret") is True  # correct token passes
    assert gate.passed is True  # ...and the gate remembers it


def test_a_non_ascii_token_works():
    # the token is encoded to bytes before compare_digest -- a str with non-ASCII
    # would otherwise raise. This is why AuthGate.check() encodes.
    assert rs.AuthGate("pä55wörd").check("pä55wörd")


def test_empty_token_counts_as_no_token():
    # an empty string is "no token", so the gate is open, not a lock nobody can open
    assert rs.AuthGate("").required is False


# -- dispatch: named calls AND MCP, one shared allowlist -----------------------

def _fake_core():
    class Sig:
        def __init__(self, fn=None):
            self.fn = fn

        def emit(self, x):
            (self.fn or (lambda *_: None))(x)

    class Core:
        def __init__(self):
            self.state = {"filter": "515/30"}
            self.sig_state_request_and_wait_until_done = Sig(self.state.update)

    return Core()


def test_a_named_call_is_dispatched_and_state_changes():
    core = _fake_core()
    reply = rs.handle_message(core, '{"set_state": {"settings": {"filter": "561/LP"}}}')
    assert reply == "__ZMART_OK__{}"  # the write ack
    assert core.state["filter"] == "561/LP"  # ...and the change landed


def test_mcp_tools_list_is_exactly_the_allowlist():
    reply = rs._mcp_reply(None, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = json.loads(reply)["result"]["tools"]
    assert [t["name"] for t in tools] == list(rs.COMMANDS)  # every tool is a call, nothing else
    # tools that take args are self-describing, so the LLM knows the arg shape
    move = next(t for t in tools if t["name"] == "move_absolute")
    assert "targets" in move["description"]


def test_an_mcp_notification_gets_no_reply():
    assert rs._mcp_reply(None, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_an_mcp_unknown_method_is_a_json_rpc_error():
    reply = rs._mcp_reply(None, {"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    assert json.loads(reply)["error"]["code"] == -32601


# -- adversarial: nothing outside the allowlist ever runs, nothing ever crashes -

_HOSTILE = [
    '{"rm_rf": {}}',                                     # unknown method
    '{"__import__(\'os\').system(\'x\')": {}}',          # code smuggled as a method name
    '{"__class__": {}}',                                 # a dunder name
    '{"ping": {}, "stop": {}}',                          # two methods in one message
    '{}', '[1,2,3]', '"hi"', '42', 'null',               # non-single-key / non-object JSON
    'not json', '{"ping":',                              # malformed JSON
    '{"set_state": "not-a-dict"}',                       # args that aren't an object
    '{"jsonrpc": "2.0", "method": "tools/call"}',        # an MCP payload on the script lane (wrong door)
]


def test_no_hostile_payload_runs_anything_or_crashes():
    # The method is only ever a dict key into COMMANDS -- never eval/exec/getattr --
    # so every hostile input is a lookup miss: an error reply, state untouched.
    for payload in _HOSTILE:
        core = _fake_core()
        before = dict(core.state)
        reply = rs.handle_message(core, payload)  # must never raise
        assert isinstance(reply, str)
        assert core.state == before  # nothing touched the instrument
        assert "__ZMART_OK__" not in reply  # no success ack for a bad/unknown call


# -- input validation: right shape, an allowed option, an in-range value -------
# A bad VALUE (not just a bad name) is refused before it reaches the Core, with a
# specific message. This is what protects the instrument from the MCP/LLM lane.

class _CfgCore:
    """A tiny Core with a cfg, so set_state options can be checked against it."""

    class _Sig:
        def __init__(self, fn):
            self.fn = fn

        def emit(self, x):
            self.fn(x)

    class _Cfg:
        filterdict = {"515/30": 1, "561/LP": 2}
        zoomdict = {"1x": 6.55}
        laserdict = {"488 nm": "PWM"}
        shutteroptions = ("Left", "Right", "Both")

    def __init__(self):
        self.state = {"filter": "515/30", "position": {a + "_pos": 0.0 for a in _AXES}}
        self.cfg = self._Cfg()
        self.sig_state_request_and_wait_until_done = self._Sig(self.state.update)

    def move_absolute(self, sdict, wait_until_done=False):
        for k, v in sdict.items():
            self.state["position"][k.replace("_abs", "") + "_pos"] = float(v)


def test_wrong_arg_shape_is_refused_with_a_specific_message():
    core = _CfgCore()
    r = rs.handle_message(core, '{"move_absolute": {"targets": "not-an-object"}}')
    assert "__ZMART_OK__" not in r and "'targets' must be" in r
    r = rs.handle_message(core, '{"move_absolute": {"targets": {"q": 1}}}')  # unknown axis
    assert "unknown axis 'q'" in r
    r = rs.handle_message(core, '{"move_absolute": {"targets": {"x": "abc"}}}')  # not a number
    assert "must be a number" in r


def test_a_value_not_in_the_configs_options_is_refused():
    core = _CfgCore()
    r = rs.handle_message(core, '{"set_state": {"settings": {"filter": "NOPE"}}}')
    assert "__ZMART_OK__" not in r
    assert "not one of" in r and "515/30" in r  # the message lists the real options
    assert core.state["filter"] == "515/30"  # unchanged
    # and a value that IS in the cfg goes through
    assert rs.handle_message(core, '{"set_state": {"settings": {"filter": "561/LP"}}}') == "__ZMART_OK__{}"
    assert rs.handle_message(core, '{"set_state": {"settings": {"intensity": 250}}}').endswith("[0, 100]")


def test_a_move_outside_the_limit_envelope_is_refused_and_the_stage_does_not_move():
    core = _CfgCore()
    limits = {"x": (-1000.0, 1000.0)}
    r = rs.handle_message(core, '{"move_absolute": {"targets": {"x": 1e9}}}', limits)
    assert "__ZMART_OK__" not in r and "outside the allowed range" in r
    assert core.state["position"]["x_pos"] == 0.0  # never moved
    # an in-range move still works
    assert rs.handle_message(core, '{"move_absolute": {"targets": {"x": 500}}}', limits) == "__ZMART_OK__{}"
    assert core.state["position"]["x_pos"] == 500.0


# -- MCP over HTTP (off-the-shelf LLM clients) + its two safety guards ----------

class _FakeConn:
    """Captures whatever the server writes back, so HTTP tests need no real socket."""

    def __init__(self):
        self.out = b""

    def write(self, b):
        self.out += bytes(b)

    def flush(self):
        pass


def _http(token=None, core=None, *, body="", origin=None, auth=None, method="POST", path="/mcp"):
    """Drive one HTTP request through a bare server instance; return (status_line, body_text)."""
    srv = rs.RemoteScriptingServer.__new__(rs.RemoteScriptingServer)  # skip __init__ (no Qt)
    srv._token, srv.core, srv._conn = token, (core or _fake_core()), _FakeConn()
    srv._httpbuf, srv._mode, srv._limits = b"", "http", {}
    head = f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: {len(body)}\r\n"
    if origin:
        head += f"Origin: {origin}\r\n"
    if auth:
        head += f"Authorization: Bearer {auth}\r\n"
    srv._http_feed((head + "\r\n" + body).encode("latin1"))
    raw = srv._conn.out.decode("latin1")
    status, _, rest = raw.partition("\r\n")
    return status, rest.split("\r\n\r\n", 1)[-1]


def test_http_tools_call_reaches_the_same_dispatch():
    core = _fake_core()
    status, _ = _http(core=core, body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "set_state", "arguments": {"settings": {"filter": "647-LP"}}}}))
    assert status == "HTTP/1.1 200 OK"
    assert core.state["filter"] == "647-LP"  # HTTP door, same COMMANDS lookup


def test_http_rejects_a_foreign_browser_origin():
    # DNS-rebinding / CSRF guard: a web page in the operator's browser must NOT drive
    # the scope. A foreign Origin is 403'd before dispatch -- nothing runs.
    core = _fake_core()
    status, _ = _http(core=core, origin="http://evil.example", body=json.dumps({"jsonrpc": "2.0",
        "id": 1, "method": "tools/call", "params": {"name": "set_state",
        "arguments": {"settings": {"filter": "HACKED"}}}}))
    assert status == "HTTP/1.1 403 Forbidden"
    assert core.state["filter"] == "515/30"  # untouched


def test_http_requires_the_bearer_token_when_one_is_set():
    ok_body = '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
    assert _http(token="s3cret", body=ok_body)[0] == "HTTP/1.1 401 Unauthorized"          # no token
    assert _http(token="s3cret", body=ok_body, auth="nope")[0] == "HTTP/1.1 401 Unauthorized"  # wrong
    assert _http(token="s3cret", body=ok_body, auth="s3cret")[0] == "HTTP/1.1 200 OK"      # right


def test_http_get_has_no_stream_and_a_notification_is_accepted():
    assert _http(method="GET", body="")[0] == "HTTP/1.1 405 Method Not Allowed"
    assert _http(body='{"jsonrpc": "2.0", "method": "notifications/initialized"}')[0] == "HTTP/1.1 202 Accepted"


# =============================================================================
# End-to-end: the REAL server over real sockets, both lanes, every command.
# Starts the actual RemoteScriptingServer (needs PyQt5 + a Qt event loop) against
# a full Core-shaped fake, then drives it from a real TCP client. Only the live
# hardware Core is absent; framing, HTTP, dispatch, and the whole vocabulary run
# for real. Skips cleanly where PyQt5 is unavailable.
# =============================================================================

_AXES = ("x", "y", "z", "f", "theta")

# The real mesoSPIM Core is a QObject, and the server parents its socket to it
# (`QTcpServer(core)`), so our fake must be a QObject too. Fall back to a plain
# object when PyQt5 is absent -- the e2e tests skip in that case anyway.
try:
    from PyQt5.QtCore import QObject as _QObject
except ImportError:
    _QObject = object


def _install_fake_acquisitions():
    """A stand-in ``utils.acquisitions`` so the acquire handler's import resolves offline."""
    if "utils.acquisitions" in sys.modules:
        return
    pkg = sys.modules.setdefault("utils", types.ModuleType("utils"))
    mod = types.ModuleType("utils.acquisitions")
    mod.Acquisition = type("Acquisition", (dict,), {"__init__": lambda s: dict.__init__(s, planes=1, folder="", filename="")})
    mod.AcquisitionList = type("AcquisitionList", (list,), {})
    pkg.acquisitions = mod
    sys.modules["utils.acquisitions"] = mod


class _Sig:
    """A stand-in pyqtSignal whose emit() runs a bound handler."""

    def __init__(self, fn=None):
        self.fn = fn or (lambda *a: None)

    def emit(self, *a):
        self.fn(*a)


class _FullCore(_QObject):
    """A Core-shaped fake with the whole surface every COMMANDS handler touches."""

    def __init__(self):
        super().__init__()
        self.state = {"state": "idle", "position": {a + "_pos": 0.0 for a in _AXES},
                      "laser": "488 nm", "intensity": 10.0, "filter": "515/30", "zoom": "1x",
                      "shutterconfig": "Left", "etl_l_amplitude": 1.0, "etl_l_offset": 2.0,
                      "etl_r_amplitude": 1.0, "etl_r_offset": 2.0}
        self.cfg = type("Cfg", (), {"laserdict": {"488 nm": "PWM", "561 nm": "PWM"},
            "filterdict": {"515/30": 1, "561/LP": 2, "647-LP": 3}, "zoomdict": {"1x": 6.55},
            "shutteroptions": ("Left", "Right", "Both"), "version": "1.20.0-fake",
            "camera_x_pixels": 64, "camera_y_pixels": 64})()
        self.sig_stop_movement = _Sig()
        self.sig_state_request_and_wait_until_done = _Sig(self.state.update)

    def move_absolute(self, sdict, wait_until_done=False):
        for k, v in sdict.items():
            self.state["position"][k.replace("_abs", "") + "_pos"] = float(v)

    def move_relative(self, ddict, wait_until_done=False):
        for k, v in ddict.items():
            self.state["position"][k.replace("_rel", "") + "_pos"] += float(v)

    def zero_axes(self, axes):
        for a in axes:
            self.state["position"][a + "_pos"] = 0.0

    def start(self, row=0):
        acq = self.state["acq_list"][row]
        os.makedirs(acq.get("folder") or ".", exist_ok=True)
        with open(os.path.join(acq.get("folder") or ".", acq.get("filename") or "s.tiff"), "wb") as f:
            f.write(b"II*\x00")  # minimal file so stat_files sees it
        self.state["state"] = "idle"


def _run(token, client_fn, limits=None):
    """Start the real server, drive it with client_fn, and return the fake Core.

    The awkward bit: the server's sockets are Qt objects, and Qt only does socket
    work while its event loop is turning. But our client also needs to block on
    recv(). We can't do both on one thread, so:
      - the CLIENT runs on a background thread (it can block on the socket there);
      - THIS thread just spins the Qt event loop (processEvents) so the server can
        actually accept the connection and answer -- until the client says it's done.
    `box` is the mailbox the two threads pass results/errors through. `port=0` lets
    Qt pick any free port; we read the real one back with serverPort().
    """
    QtCore = __import__("pytest").importorskip("PyQt5.QtCore")  # skip the whole test if no PyQt5
    _install_fake_acquisitions()
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    core = _FullCore()
    server = rs.RemoteScriptingServer(core, "127.0.0.1", 0, token=token, limits=limits)
    box = {}

    def run():
        try:
            client_fn(server._server.serverPort(), box)
        except BaseException as exc:  # stash it; we re-raise on the main thread so pytest sees it
            box["error"] = exc
        finally:
            box["done"] = True  # tell the main loop below it can stop pumping

    th = threading.Thread(target=run)
    th.start()
    deadline = time.time() + 10  # safety net: never hang the suite if the client wedges
    while not box.get("done"):
        app.processEvents()  # let the server accept/read/reply
        if time.time() > deadline:
            break
        time.sleep(0.001)  # don't burn a whole CPU spinning
    th.join(timeout=2)
    server.stop()
    if "error" in box:
        raise box["error"]
    assert box.get("ok"), "client did not finish"
    return core


def _framed_conn(port):
    """A tiny length-framed client bound to one socket: returns (call, send, recv, sock)."""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    buf = bytearray()

    def send(text):
        b = text.encode()
        s.sendall(str(len(b)).encode() + b"\n" + b)

    def recv():
        # read the "<n>\n" length line, then exactly n payload bytes
        while b"\n" not in buf:
            buf.extend(s.recv(4096))
        i = buf.index(b"\n")
        n = int(buf[:i])
        del buf[:i + 1]
        while len(buf) < n:
            buf.extend(s.recv(4096))
        out = bytes(buf[:n])
        del buf[:n]
        return out.decode()

    def call(method, **args):
        send(json.dumps({method: args}))
        r = recv()
        assert r.startswith("__ZMART_OK__"), r
        return json.loads(r[len("__ZMART_OK__"):])

    return call, send, recv, s


def _framed_client(port, box):
    call, send, recv, s = _framed_conn(port)
    try:
        send("tok")
        assert recv() == "OK"                                             # auth
        assert call("ping")["pong"] is True                              # reads
        assert call("hello")["app"] == "mesoSPIM-control"
        assert set(call("get_position")) == set(_AXES)
        assert call("get_state")["filter"] == "515/30"
        cfg = call("get_config")
        assert "515/30" in cfg["filters"] and cfg["lasers"] and cfg["zooms"]
        assert "state" in call("get_progress")
        call("move_absolute", targets={"x": 1000.0, "z": -50.0})         # writes + readback
        assert call("get_position")["x"] == 1000.0
        call("move_relative", deltas={"z": 5.0})
        assert call("get_position")["z"] == -45.0
        call("set_state", settings={"filter": "561/LP"})
        assert call("get_state")["filter"] == "561/LP"
        call("zero", axes=["x"])
        assert call("get_position")["x"] == 0.0
        call("stop")
        folder = tempfile.mkdtemp()                                      # acquisition round-trip
        started = call("acquire_start", acquisition={"folder": folder, "filename": "A.tiff", "planes": 1})
        assert started["started"] and started["files"]
        assert not call("stat_files", files=started["files"])["missing"]
        call("acquire_finish")
        send(json.dumps({"procedure": {"name": "autofocus"}}))           # advertised-but-unimplemented -> NAK
        assert "__ZMART_OK__" not in recv()
        box["ok"] = True
    finally:
        s.close()


def _http_post(s, body, token="tok", origin=None):
    head = f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: {len(body)}\r\n"
    if token:
        head += f"Authorization: Bearer {token}\r\n"
    if origin:
        head += f"Origin: {origin}\r\n"
    s.sendall((head + "\r\n" + body).encode())
    raw = b""
    while b"\r\n\r\n" not in raw:
        raw += s.recv(4096)
    head_b, _, rest = raw.partition(b"\r\n\r\n")
    length = 0
    for ln in head_b.split(b"\r\n")[1:]:
        if ln.lower().startswith(b"content-length:"):
            length = int(ln.split(b":", 1)[1])
    while len(rest) < length:
        rest += s.recv(4096)
    return head_b.split(b"\r\n")[0].decode(), rest[:length].decode()


def _http_client(port, box):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        status, body = _http_post(s, '{"jsonrpc": "2.0", "id": 1, "method": "initialize"}')
        assert status == "HTTP/1.1 200 OK"
        assert json.loads(body)["result"]["serverInfo"]["name"] == "mesoSPIM"
        _, body = _http_post(s, '{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}')
        assert [t["name"] for t in json.loads(body)["result"]["tools"]] == list(rs.COMMANDS)
        _, body = _http_post(s, json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "set_state", "arguments": {"settings": {"filter": "647-LP"}}}}))
        assert json.loads(body)["result"]["isError"] is False
        assert _http_post(s, '{"jsonrpc":"2.0","id":4,"method":"tools/list"}', token="wrong")[0] == "HTTP/1.1 401 Unauthorized"
        assert _http_post(s, '{"jsonrpc":"2.0","id":5,"method":"tools/list"}', origin="http://evil.example")[0] == "HTTP/1.1 403 Forbidden"
        box["ok"] = True
    finally:
        s.close()


def test_e2e_every_command_over_framed_tcp():
    core = _run("tok", _framed_client)
    assert core.state["filter"] == "561/LP"  # the framed set_state persisted


def test_e2e_mcp_over_http_end_to_end():
    core = _run("tok", _http_client)
    assert core.state["filter"] == "647-LP"  # the HTTP tools/call persisted


def _limits_client(port, box):
    call, send, recv, s = _framed_conn(port)
    try:
        send("tok")
        assert recv() == "OK"
        send(json.dumps({"move_absolute": {"targets": {"x": 1e9}}}))  # far outside the envelope
        r = recv()
        assert "__ZMART_OK__" not in r and "outside the allowed range" in r
        call("move_absolute", targets={"x": 500.0})  # in range -> allowed
        assert call("get_position")["x"] == 500.0
        box["ok"] = True
    finally:
        s.close()


def test_e2e_a_move_outside_the_limits_is_refused_by_the_real_server():
    # end-to-end proof of the whole path: __init__ takes the limits map, _validate
    # refuses the out-of-range value over a real socket, the demo stage never moves.
    core = _run("tok", _limits_client, limits={"x": (-1000.0, 1000.0)})
    assert core.state["position"]["x_pos"] == 500.0  # only the in-range move landed


if __name__ == "__main__":  # runnable without pytest, for a quick check next to the PR
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
