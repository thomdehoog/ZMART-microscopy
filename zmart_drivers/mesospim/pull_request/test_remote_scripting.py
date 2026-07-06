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
    srv._httpbuf, srv._mode = b"", "http"
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


if __name__ == "__main__":  # runnable without pytest, for a quick check next to the PR
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
