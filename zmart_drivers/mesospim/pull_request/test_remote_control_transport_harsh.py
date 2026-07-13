"""Bounded black-box adversarial tests for both remote-control transports.

Every attack in this file enters through a real loopback transport:

* MCP attacks are HTTP POSTs handled by the production ``MCPHandler``.
* TCP attacks are length-framed socket messages decoded by the production
  ``FrameDecoder`` and ``AuthGate`` before production dispatch.

The MCP server forwards to the TCP test server exactly like the real deployment.
A recording fake Core proves that rejected inputs never reach instrument methods.
The corpus is intentionally small and deterministic: no sleeps, no open-ended
fuzzing, and a 0.6 second socket deadline.
"""
from __future__ import annotations

import json
import os
import random
import socket
import socketserver
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


_SOURCE_ROOT = os.environ.get("MESOSPIM_RC_SOURCE_ROOT")
if _SOURCE_ROOT:
    sys.path.insert(0, str(Path(_SOURCE_ROOT)))
    from mesoSPIM.src import mesoSPIM_RemoteControl_Servers as srv
    from mesoSPIM.src import mesoSPIM_RemoteControl_ValidateAndRunCommands as vrc

    class _Cfg:
        filterdict = {"Empty": 0, "515LP": 1}
        zoomdict = {"1x": 1, "2x": 2}
        laserdict = {"488 nm": 0, "561 nm": 1}
        shutteroptions = ["Left", "Right", "Both"]
        stage_parameters = {
            "x_min": -25000, "x_max": 25000,
            "y_min": -50000, "y_max": 50000,
            "z_min": -25000, "z_max": 25000,
            "f_min": 0, "f_max": 98000,
            "theta_min": -999, "theta_max": 999,
            "y_load_position": 1000, "y_unload_position": -1000,
            "x_center_position": 0, "z_center_position": 0,
        }
else:
    from test_remote_control import _Cfg, srv, vrc


TOKEN = "harsh-MCP+TCP-token-Ac"
REQUEST_TIMEOUT = 0.6
MAX_ACCEPTED_BODY = 1 << 20
MAX_FUZZ_CASES = 48
BUSY_STRESS_MUTATIONS = 16
BUSY_STRESS_READS = 8


class _RecordingCore:
    """Small fake instrument with a thread-safe, externally inspectable call log."""

    cfg = _Cfg()

    def __init__(self):
        self._calls = []
        self._lock = threading.Lock()
        self._reset_state()
        self.serial_worker = _RecordingSerialWorker(self)
        for name in (
            "sig_stop_movement", "sig_state_request", "sig_state_request_and_wait_until_done",
            "sig_load_sample", "sig_unload_sample", "sig_center_sample", "sig_save_etl_config",
        ):
            setattr(self, name, _RecordingSignal(self, name))

    def _reset_state(self):
        self.state = {
            "state": "idle",
            "position": {
                "x_pos": 24999.0,
                "y_pos": 0.0,
                "z_pos": 0.0,
                "f_pos": 1000.0,
                "theta_pos": 0.0,
            },
            "laser": "488 nm",
            "intensity": 10,
            "filter": "Empty",
            "zoom": "1x",
            "shutterconfig": "Left",
            "shutterstate": False,
            "ETL_cfg_file": "etl.csv",
            "selected_row": 0,
            "acq_list": [],
        }

    def reset(self):
        with self._lock:
            self._calls.clear()
            self._reset_state()

    def calls(self):
        with self._lock:
            return list(self._calls)

    def _record(self, name, *args, **kwargs):
        with self._lock:
            self._calls.append((name, args, kwargs))

    def move_absolute(self, *args, **kwargs):
        self._record("move_absolute", *args, **kwargs)
        for key, value in args[0].items():
            self.state["position"][key.replace("_abs", "_pos")] = float(value)

    def move_relative(self, *args, **kwargs):
        # A synchronous remote call must use serial_worker.move_relative directly.
        # Reaching this Core method reproduces the old signal/early-return path.
        self._record("core_move_relative_fallback", *args, **kwargs)

    def state_request_handler(self, *args, **kwargs):
        self._record("state_request_handler", *args, **kwargs)
        self.state.update(args[0])

    def set_filter(self, *args, **kwargs):
        self._record("set_filter", *args, **kwargs)
        self.state["filter"] = args[0]

    def set_zoom(self, *args, **kwargs):
        self._record("set_zoom", *args, **kwargs)
        self.state["zoom"] = args[0]

    def set_laser(self, *args, **kwargs):
        self._record("set_laser", *args, **kwargs)
        self.state["laser"] = args[0]

    def set_intensity(self, *args, **kwargs):
        self._record("set_intensity", *args, **kwargs)
        self.state["intensity"] = args[0]

    def set_shutterconfig(self, *args, **kwargs):
        self._record("set_shutterconfig", *args, **kwargs)
        self.state["shutterconfig"] = args[0]

    def run_time_lapse(self, *args, **kwargs):
        self._record("run_time_lapse", *args, **kwargs)

    def zero_axes(self, *args, **kwargs):
        self._record("zero_axes", *args, **kwargs)

    def unzero_axes(self, *args, **kwargs):
        self._record("unzero_axes", *args, **kwargs)

    def stop(self, *args, **kwargs):
        self._record("stop", *args, **kwargs)
        self.state["state"] = "idle"

    def open_shutters(self, *args, **kwargs):
        self._record("open_shutters", *args, **kwargs)
        self.state["shutterstate"] = True

    def close_shutters(self, *args, **kwargs):
        self._record("close_shutters", *args, **kwargs)
        self.state["shutterstate"] = False

    def start(self, *args, **kwargs):
        self._record("start", *args, **kwargs)
        self.state["state"] = "run_acquisition_list"

    def preview_acquisition(self, *args, **kwargs):
        self._record("preview_acquisition", *args, **kwargs)

    def snap(self, *args, **kwargs):
        self._record("snap", *args, **kwargs)

    def set_state(self, *args, **kwargs):
        self._record("set_state", *args, **kwargs)
        self.state["state"] = args[0]

    def execute_galil_program(self, *args, **kwargs):
        self._record("execute_galil_program", *args, **kwargs)

    def get_free_disk_space(self, *args, **kwargs):
        self._record("get_free_disk_space", *args, **kwargs)
        return 1_000_000_000

    def get_required_disk_space(self, *args, **kwargs):
        self._record("get_required_disk_space", *args, **kwargs)
        return 0

    def check_motion_limits(self, *args, **kwargs):
        self._record("check_motion_limits", *args, **kwargs)
        return []

    def stop_time_lapse(self, *args, **kwargs):
        self._record("stop_time_lapse", *args, **kwargs)


class _RecordingSerialWorker:
    def __init__(self, core):
        self.core = core

    def move_relative(self, *args, **kwargs):
        self.core._record("move_relative", *args, **kwargs)
        for key, value in args[0].items():
            pos_key = key.replace("_rel", "_pos")
            self.core.state["position"][pos_key] += float(value)


class _RecordingSignal:
    def __init__(self, core, name):
        self.core = core
        self.name = name

    def emit(self, *args):
        self.core._record(self.name, *args)
        if self.name in {"sig_state_request", "sig_state_request_and_wait_until_done"}:
            settings = args[0]
            if "ETL_cfg_file" in settings:
                self.core.state["ETL_cfg_file"] = settings["ETL_cfg_file"]


_core = _RecordingCore()
_tcp_server = None
_tcp_thread = None
_mcp_server = None
_mcp_thread = None
_tcp_port = None
_mcp_port = None
_original_defer = vrc._defer
_saved_utils_modules = {}


class _TransportTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _TCPHandler(socketserver.BaseRequestHandler):
    """Socket shell matching the production Qt server's framing/auth/dispatch flow."""

    def handle(self):
        self.request.settimeout(REQUEST_TIMEOUT)
        decoder = srv.FrameDecoder()
        auth = srv.AuthGate(TOKEN)
        while True:
            try:
                chunk = self.request.recv(65536)
            except (ConnectionError, OSError, socket.timeout):
                return
            if not chunk:
                return
            decoder.feed(chunk)
            try:
                for payload in decoder.frames():
                    message = payload.decode("utf-8", "replace")
                    if not auth.passed:
                        reply = "OK" if auth.check(message) else "AUTH-FAILED"
                        self.request.sendall(srv.frame(reply))
                        if reply != "OK":
                            return
                    else:
                        try:
                            self.request.sendall(srv.frame(srv.handle_tcp_message(_core, message)))
                        except (ConnectionError, OSError):
                            return
            except srv.FramingError as exc:
                try:
                    self.request.sendall(srv.frame(f"framing error: {exc}"))
                except (ConnectionError, OSError):
                    pass
                return


class _FakeAcquisition(dict):
    pass


class _FakeAcquisitionList(list):
    pass


def _install_fake_acquisitions():
    package = types.ModuleType("utils")
    module = types.ModuleType("utils.acquisitions")
    module.Acquisition = _FakeAcquisition
    module.AcquisitionList = _FakeAcquisitionList
    package.acquisitions = module
    for name, value in (("utils", package), ("utils.acquisitions", module)):
        _saved_utils_modules.setdefault(name, sys.modules.get(name))
        sys.modules[name] = value


def setup_module(_module=None):
    global _tcp_server, _tcp_thread, _mcp_server, _mcp_thread, _tcp_port, _mcp_port
    if _tcp_server is not None or _mcp_server is not None:
        return
    _install_fake_acquisitions()
    vrc._defer = lambda function, *args, **kwargs: function(*args, **kwargs)
    _tcp_server = _TransportTCPServer(("127.0.0.1", 0), _TCPHandler)
    _tcp_port = _tcp_server.server_address[1]
    _tcp_thread = threading.Thread(target=_tcp_server.serve_forever, daemon=True)
    _tcp_thread.start()

    config = types.SimpleNamespace(
        token=TOKEN,
        quiet=True,
        timeout=REQUEST_TIMEOUT,
        mesospim_host="127.0.0.1",
        mesospim_port=_tcp_port,
        mesospim_token=TOKEN,
    )
    _mcp_server = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_mcp_handler(config))
    _mcp_port = _mcp_server.server_address[1]
    _mcp_thread = threading.Thread(target=_mcp_server.serve_forever, daemon=True)
    _mcp_thread.start()


def teardown_module(_module=None):
    global _tcp_server, _tcp_thread, _mcp_server, _mcp_thread, _tcp_port, _mcp_port
    for server in (_mcp_server, _tcp_server):
        if server is not None:
            server.shutdown()
            server.server_close()
    for thread in (_mcp_thread, _tcp_thread):
        if thread is not None:
            thread.join(timeout=1.0)
    _tcp_server = _tcp_thread = _mcp_server = _mcp_thread = None
    _tcp_port = _mcp_port = None
    vrc._defer = _original_defer
    for name, previous in _saved_utils_modules.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def _mcp_http(body, *, token=TOKEN, origin="http://127.0.0.1", path="/mcp"):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    request = urllib.request.Request(
        f"http://127.0.0.1:{_mcp_port}{path}",
        data=body if isinstance(body, bytes) else body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    # Windows can very occasionally report WSAECONNABORTED when the local
    # HTTP server rejects a request before consuming its body. Retry that one
    # loopback transport condition once; all protocol errors and timeouts
    # still fail immediately, so the adversarial suite remains tightly bounded.
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except ConnectionAbortedError:
            if attempt:
                raise


def _mcp_tool(name, arguments):
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, allow_nan=True)
    status, raw = _mcp_http(body)
    reply = json.loads(raw) if raw else None
    return status, reply


def _mcp_rejected(name, arguments):
    before = _core.calls()
    status, reply = _mcp_tool(name, arguments)
    if status == 200:
        assert reply["result"]["isError"] is True, reply
    else:
        assert status == 400, (status, reply)
    assert _core.calls() == before, f"MCP rejection reached Core: {_core.calls()!r}"


def _tcp_connect(token=TOKEN):
    sock = socket.create_connection(("127.0.0.1", _tcp_port), timeout=REQUEST_TIMEOUT)
    sock.settimeout(REQUEST_TIMEOUT)
    sock.sendall(srv.frame(token))
    return sock, srv.read_frame(sock)


def _read_tcp_frames(sock, count):
    """Read multiple pipelined replies without discarding coalesced frames."""
    buffer = b""
    replies = []
    while len(replies) < count:
        while b"\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("TCP server closed before all replies arrived")
            buffer += chunk
        head, _, payload = buffer.partition(b"\n")
        if not head or not head.isdigit():
            raise srv.FramingError("expected canonical byte-count header")
        length = int(head)
        while len(payload) < length:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("TCP server closed inside a reply")
            payload += chunk
        replies.append(payload[:length].decode(srv.ENCODING, "replace"))
        buffer = payload[length:]
    return replies


def _tcp_call(payload):
    sock, auth = _tcp_connect()
    try:
        assert auth == "OK"
        text = payload if isinstance(payload, str) else json.dumps(payload, allow_nan=True)
        sock.sendall(srv.frame(text))
        return srv.read_frame(sock)
    finally:
        sock.close()


def _tcp_rejected(name, arguments):
    before = _core.calls()
    reply = _tcp_call({name: arguments})
    assert not reply.startswith(srv.OK_MARKER), reply
    assert _core.calls() == before, f"TCP rejection reached Core: {_core.calls()!r}"


def _raw_http(headers, body=b"", *, shutdown_write=False):
    sock = socket.create_connection(("127.0.0.1", _mcp_port), timeout=REQUEST_TIMEOUT)
    sock.settimeout(REQUEST_TIMEOUT)
    lines = [b"POST /mcp HTTP/1.1", b"Host: 127.0.0.1", b"Connection: close"]
    lines.extend(h.encode("ascii") for h in headers)
    sock.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + body)
    if shutdown_write:
        sock.shutdown(socket.SHUT_WR)
    chunks = []
    try:
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    except socket.timeout:
        pass
    finally:
        sock.close()
    response = b"".join(chunks)
    status = int(response.split(b" ", 2)[1]) if response.startswith(b"HTTP/") else None
    return status, response


HOSTILE_NAMES = [
    "__class__", "__globals__", "__import__", "eval", "exec", "compile",
    "os.system('calc')", "subprocess.Popen", "COMMANDS", "run", "_validate",
    "move_absolute\x00", "move_absolute\r\nX-Evil: yes", "MOVE_ABSOLUTE",
    " move_absolute", "move_absolute ", "move\u202eetulosba", "m\u043eve_absolute",
    "..", "*", "", "\ud800", "A" * 4096,
]


def test_attack_corpus_is_deliberately_bounded():
    assert REQUEST_TIMEOUT <= 0.6
    assert len(HOSTILE_NAMES) < MAX_FUZZ_CASES
    assert MAX_ACCEPTED_BODY <= 1 << 20


def test_hostile_names_are_rejected_over_mcp_and_tcp_without_core_touch():
    _core.reset()
    for name in HOSTILE_NAMES:
        _mcp_rejected(name, {})
        _tcp_rejected(name, {})


def test_seeded_unicode_and_delimiter_fuzz_is_bounded_and_rejected_on_both_lanes():
    rng = random.Random(0x5EED)
    alphabet = ["a", "Z", "_", ".", "/", "\\", "\x00", "\n", "\t", "м", "K", "／"]
    names = set()
    while len(names) < MAX_FUZZ_CASES:
        name = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 32)))
        if name not in vrc.COMMANDS:
            names.add(name)
    _core.reset()
    for name in sorted(names):
        _mcp_rejected(name, {"targets": {"x": 0}})
        _tcp_rejected(name, {"targets": {"x": 0}})


def test_limit_type_and_shape_bypasses_fail_over_both_transports():
    attacks = [
        ("move_absolute", {"targets": {"x": 25000.0000001}}),
        ("move_absolute", {"targets": {"x": -25000.0000001}}),
        ("move_absolute", {"targets": {"y": 50001}}),
        ("move_absolute", {"targets": {"z": -25001}}),
        ("move_absolute", {"targets": {"f": -1}}),
        ("move_absolute", {"targets": {"x": True}}),
        ("move_absolute", {"targets": {"x": "0"}}),
        ("move_absolute", {"targets": {"x": [0]}}),
        ("move_absolute", {"targets": {"__proto__": 0}}),
        ("move_absolute", {"targets": {}}),
        ("set_intensity", {"intensity": -1}),
        ("set_intensity", {"intensity": 101}),
        ("set_intensity", {"intensity": False}),
        ("set_filter", {"filter": "Empty\x00"}),
        ("set_state", {"settings": {"x_max": 999999999}}),
    ]
    _core.reset()
    for name, arguments in attacks:
        _mcp_rejected(name, arguments)
        _tcp_rejected(name, arguments)


def test_nonfinite_numbers_never_reach_even_unbounded_numeric_handlers():
    _core.reset()
    for value in (float("nan"), float("inf"), float("-inf"), 1e309, -1e309):
        for name, arguments in (
            ("set_etl", {"etl_l_amplitude": value}),
            ("set_camera", {"camera_exposure_time": value}),
            ("move_relative", {"deltas": {"x": value}}),
        ):
            _mcp_rejected(name, arguments)
            _tcp_rejected(name, arguments)


def test_relative_move_cannot_cross_absolute_envelope_on_either_transport():
    _core.reset()
    # Fake Core starts at x=24999, so +2 would land at 25001 beyond x_max=25000.
    arguments = {"deltas": {"x": 2}}
    _mcp_rejected("move_relative", arguments)
    _tcp_rejected("move_relative", arguments)


def test_mcp_auth_bypass_matrix_is_401_and_never_forwards():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "move_absolute", "arguments": {"targets": {"x": 0}}}})
    wrong = [None, "", "harsh-MCP+TCP-token", TOKEN + " ", " " + TOKEN,
             TOKEN.upper(), TOKEN + "\x00", "Bearer " + TOKEN]
    _core.reset()
    for candidate in wrong:
        status, _ = _mcp_http(body, token=candidate)
        assert status == 401, (candidate, status)
        assert _core.calls() == []


def test_mcp_origin_bypass_matrix_is_403_and_never_forwards():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "move_absolute", "arguments": {"targets": {"x": 0}}}})
    hostile = [
        "null", "http://evil.example", "http://localhost.evil.example",
        "http://127.0.0.1.evil", "http://127.0.0.1:42100",
        "http://user@localhost", "HTTP://LOCALHOST", "http://localhost.",
        "https://localhost@evil.example", "file://localhost",
    ]
    _core.reset()
    for origin in hostile:
        status, _ = _mcp_http(body, origin=origin)
        assert status == 403, (origin, status)
        assert _core.calls() == []


def test_duplicate_security_headers_fail_closed_before_forwarding():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "move_absolute", "arguments": {"targets": {"x": 0}}}}).encode()
    base = ["Content-Type: application/json", f"Content-Length: {len(body)}"]
    _core.reset()
    status, _ = _raw_http(base + [
        f"Authorization: Bearer {TOKEN}",
        "Authorization: Bearer definitely-wrong",
        "Origin: http://127.0.0.1",
    ], body)
    assert status == 401
    assert _core.calls() == []

    status, _ = _raw_http(base + [
        f"Authorization: Bearer {TOKEN}",
        "Origin: http://127.0.0.1",
        "Origin: http://evil.example",
    ], body)
    assert status == 403
    assert _core.calls() == []


def test_duplicate_json_members_are_rejected_on_mcp_and_tcp():
    _core.reset()
    mcp = (
        '{"jsonrpc":"2.0","id":1,"method":"tools/call",'
        '"params":{"name":"move_absolute","arguments":{"targets":{"x":25001,"x":0}}}}'
    )
    status, _ = _mcp_http(mcp)
    assert status == 400
    assert _core.calls() == []

    tcp = '{"move_absolute":{"targets":{"x":25001,"x":0}}}'
    reply = _tcp_call(tcp)
    assert not reply.startswith(srv.OK_MARKER)
    assert _core.calls() == []


def test_mcp_malformed_json_batch_and_bad_params_never_forward_or_kill_server():
    bodies = [
        b"", b"{", b"[]", b"null", b"true", b"\xff\xfe",
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":[]}',
        b'[{"jsonrpc":"2.0","id":1,"method":"tools/list"}]',
        b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"move_absolute",'
        b'"arguments":{"targets":{"x":0}}}}',
    ]
    _core.reset()
    for body in bodies:
        status, _ = _mcp_http(body)
        assert status in (200, 202, 400), status
        assert _core.calls() == []
    status, reply = _mcp_tool("get_state", {})
    assert status == 200 and reply["result"]["isError"] is False


def test_mcp_oversized_body_is_rejected_before_read_or_forward():
    _core.reset()
    start = time.monotonic()
    status, _ = _raw_http([
        f"Authorization: Bearer {TOKEN}",
        "Origin: http://127.0.0.1",
        "Content-Type: application/json",
        f"Content-Length: {MAX_ACCEPTED_BODY + 1}",
    ], shutdown_write=True)
    assert status == 413
    assert time.monotonic() - start < REQUEST_TIMEOUT
    assert _core.calls() == []


def test_tcp_auth_confusion_fails_closed_without_core_touch():
    _core.reset()
    for token in ("", TOKEN + " ", " " + TOKEN, TOKEN.upper(), TOKEN + "\x00"):
        sock, reply = _tcp_connect(token)
        try:
            assert reply == "AUTH-FAILED"
        finally:
            sock.close()
        assert _core.calls() == []


def test_tcp_bad_and_oversized_frame_headers_fail_fast_without_core_touch():
    _core.reset()
    for malformed in (b"abc\n", b"-1\n", b"12x\n", b"+1\nX", b"1 0\n"):
        sock, auth = _tcp_connect()
        try:
            assert auth == "OK"
            sock.sendall(malformed)
            reply = srv.read_frame(sock)
            assert reply.startswith("framing error:"), reply
        finally:
            sock.close()
        assert _core.calls() == []

    sock, auth = _tcp_connect()
    try:
        assert auth == "OK"
        start = time.monotonic()
        sock.sendall(str(MAX_ACCEPTED_BODY + 1).encode("ascii") + b"\n")
        reply = srv.read_frame(sock)
        assert reply.startswith("framing error:"), reply
        assert time.monotonic() - start < REQUEST_TIMEOUT
    finally:
        sock.close()
    assert _core.calls() == []


def test_tcp_invalid_utf8_and_pipelined_attacks_do_not_poison_next_call():
    _core.reset()
    sock, auth = _tcp_connect()
    try:
        assert auth == "OK"
        bad_utf8 = b'{"move_\xffabsolute":{"targets":{"x":0}}}'
        hostile = json.dumps({"__import__": {}}).encode()
        healthy = json.dumps({"get_state": {}}).encode()
        sock.sendall(srv.frame(bad_utf8) + srv.frame(hostile) + srv.frame(healthy))
        first, second, third = _read_tcp_frames(sock, 3)
        assert not first.startswith(srv.OK_MARKER)
        assert not second.startswith(srv.OK_MARKER)
        assert third.startswith(srv.OK_MARKER)
    finally:
        sock.close()
    assert _core.calls() == []


def _operation_call(lane, name, arguments):
    if lane == "mcp":
        status, reply = _mcp_tool(name, arguments)
        assert status == 200
        result = reply["result"]
        payload = json.loads(result["content"][0]["text"])
        return not result["isError"], payload
    reply = _tcp_call({name: arguments})
    if reply.startswith(srv.OK_MARKER):
        return True, json.loads(reply[len(srv.OK_MARKER):])
    return False, {"error": reply}


@pytest.mark.parametrize("lane", ["mcp", "tcp"])
def test_preview_completes_on_blocking_return_at_idle(lane):
    """Preview has no sig_finished, so its blocking return is the completion proof."""
    _core.reset()
    _core.sig_finished = object()
    for attr in ("_mesospim_remote_operation", "_mesospim_remote_operation_counter"):
        if hasattr(_core, attr):
            delattr(_core, attr)
    try:
        ok, reply = _operation_call(
            lane, "preview_acquisition", {"row": 0, "z_update": True})
        assert ok, reply
        assert reply["accepted"] is True
        assert reply["operation"]["status"] == "completed"
        preview = [call for call in _core.calls() if call[0] == "preview_acquisition"][-1]
        assert preview[2]["z_update"] is True
    finally:
        delattr(_core, "sig_finished")
        for attr in ("_mesospim_remote_operation", "_mesospim_remote_operation_counter"):
            if hasattr(_core, attr):
                delattr(_core, attr)


@pytest.mark.parametrize("lane", ["mcp", "tcp"])
def test_stopping_finished_time_lapse_does_not_leave_stuck_gate(lane):
    """An idempotent stop has no future cancellation signal to wait for."""
    _core.reset()
    _core.state["state"] = "run_acquisition_list"
    _core.timelapse_active = False
    _core.sig_time_lapse_finished = object()
    for attr in ("_mesospim_remote_operation", "_mesospim_remote_operation_counter"):
        if hasattr(_core, attr):
            delattr(_core, attr)
    try:
        ok, reply = _operation_call(lane, "time_lapse_stop", {})
        assert ok, reply
        assert reply["operation"]["status"] == "completed"
    finally:
        delattr(_core, "timelapse_active")
        delattr(_core, "sig_time_lapse_finished")
        _core.reset()
        for attr in ("_mesospim_remote_operation", "_mesospim_remote_operation_counter"):
            if hasattr(_core, attr):
                delattr(_core, attr)


@pytest.mark.parametrize("lane", ["mcp", "tcp"])
def test_idle_stop_is_idempotent_and_does_not_reabort_workers(lane):
    _core.reset()
    ok, reply = _operation_call(lane, "stop_activity", {})
    assert ok, reply
    assert reply["operation"]["status"] == "completed"
    assert reply["state"] == "idle"
    assert _core.calls() == []


@pytest.mark.parametrize("first_lane,second_lane", [("mcp", "tcp"), ("tcp", "mcp")])
def test_busy_gate_acknowledges_rejects_reports_and_releases_across_lanes(
        first_lane, second_lane):
    """One active operation serializes MCP/TCP while reads and emergency stop remain live."""
    _core.reset()
    _core.sig_finished = object()  # makes start_live genuinely asynchronous to the gate
    for attr in ("_mesospim_remote_operation", "_mesospim_remote_operation_counter"):
        if hasattr(_core, attr):
            delattr(_core, attr)
    try:
        ok, accepted = _operation_call(first_lane, "start_live", {})
        assert ok
        assert accepted["accepted"] is True
        assert accepted["accepted_command"] == "start_live"
        operation = accepted["operation"]
        assert operation["status"] == "processing"
        assert operation["command"] == "start_live"

        before = _core.calls()
        ok, rejected = _operation_call(second_lane, "set_intensity", {"intensity": 20})
        assert not ok
        assert "system busy" in rejected["error"]
        assert "start_live" in rejected["error"]
        assert operation["id"] in rejected["error"]
        assert _core.calls() == before

        ok, progress = _operation_call(second_lane, "get_progress", {})
        assert ok
        assert progress["operation"]["id"] == operation["id"]
        assert progress["operation"]["status"] == "processing"

        ok, stopping = _operation_call(second_lane, "stop_activity", {})
        assert ok
        assert stopping["accepted"] is True
        assert stopping["accepted_command"] == "stop_activity"
        assert stopping["operation"]["status"] == "stopping"

        assert vrc.complete_operation(_core, "finished") is True
        ok, completed = _operation_call(first_lane, "get_progress", {})
        assert ok
        assert completed["operation"]["status"] == "completed"

        ok, next_call = _operation_call(second_lane, "set_intensity", {"intensity": 20})
        assert ok
        assert next_call["accepted"] is True
        assert next_call["operation"]["status"] == "completed"
        assert _core.state["intensity"] == 20
    finally:
        delattr(_core, "sig_finished")
        for attr in ("_mesospim_remote_operation", "_mesospim_remote_operation_counter"):
            if hasattr(_core, attr):
                delattr(_core, attr)
        _core.reset()


def test_busy_gate_bounded_concurrent_burst_is_atomic_across_mcp_and_tcp():
    """A mixed 24-call burst cannot leak a second mutation through the active gate."""
    _core.reset()
    _core.sig_finished = object()
    for attr in ("_mesospim_remote_operation", "_mesospim_remote_operation_counter"):
        if hasattr(_core, attr):
            delattr(_core, attr)
    try:
        ok, accepted = _operation_call("mcp", "start_live", {})
        assert ok, accepted
        operation = accepted["operation"]
        assert operation["status"] == "processing"
        before = _core.calls()

        attempts = []
        for index in range(BUSY_STRESS_MUTATIONS):
            attempts.append(("mutation", "mcp" if index % 2 == 0 else "tcp"))
            if index < BUSY_STRESS_READS:
                attempts.append(("read", "tcp" if index % 2 == 0 else "mcp"))
        release = threading.Event()

        def attempt(item):
            release.wait()
            kind, lane = item
            if kind == "mutation":
                return kind, lane, _operation_call(
                    lane, "set_intensity", {"intensity": 20})
            return kind, lane, _operation_call(lane, "get_progress", {})

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(attempt, item) for item in attempts]
            release.set()
            results = [future.result() for future in futures]

        for kind, _lane, (call_ok, reply) in results:
            if kind == "mutation":
                assert not call_ok, reply
                assert "system busy" in reply["error"]
                assert operation["id"] in reply["error"]
                assert operation["command"] in reply["error"]
            else:
                assert call_ok, reply
                assert reply["operation"]["id"] == operation["id"]
                assert reply["operation"]["status"] == "processing"
        assert _core.calls() == before

        assert vrc.complete_operation(_core, "finished") is True
        for lane in ("mcp", "tcp"):
            ok, next_call = _operation_call(
                lane, "set_intensity", {"intensity": 20})
            assert ok, next_call
            assert next_call["operation"]["status"] == "completed"
    finally:
        delattr(_core, "sig_finished")
        for attr in ("_mesospim_remote_operation", "_mesospim_remote_operation_counter"):
            if hasattr(_core, attr):
                delattr(_core, attr)
        _core.reset()


@pytest.mark.parametrize("lane", ["mcp", "tcp"])
def test_set_state_cannot_smuggle_an_unknown_state_machine_mode(lane):
    _core.reset()
    before = _core.calls()
    ok, reply = _operation_call(
        lane, "set_state", {"settings": {"state": "__invalid_remote_state__"}})
    assert not ok, reply
    assert "not one of" in reply["error"]
    assert _core.calls() == before
    assert _core.state["state"] == "idle"


def test_both_servers_remain_healthy_after_the_full_attack_corpus():
    status, reply = _mcp_tool("get_state", {})
    assert status == 200 and reply["result"]["isError"] is False
    assert _tcp_call({"get_state": {}}).startswith(srv.OK_MARKER)


if __name__ == "__main__":
    setup_module()
    try:
        passed = 0
        for name, function in sorted(globals().items()):
            if name.startswith("test_") and callable(function):
                function()
                print(f"ok   {name}")
                passed += 1
        print(f"\nALL {passed} BOUNDED TRANSPORT ADVERSARIAL TESTS PASSED")
    finally:
        teardown_module()
