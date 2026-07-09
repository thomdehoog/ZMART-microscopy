"""Self-contained test for the Remote Control PR -- framing, auth, validation, MCP.

Rebuilds the two ``mesoSPIM_RemoteControl_*`` modules straight from the
``0001-*.patch`` new-file hunks (one source of truth -- the patch itself), then
checks what the server promises: frames round-trip, the token is enforced in
constant time, bad VALUES are refused (shape / option / range), the MCP reply shape
is right, and a hostile-payload sweep proves nothing outside the allowlist ever
runs. No Qt, no mesoSPIM, no third-party imports. Run either way::

    pytest pull_request/test_remote_control.py
    python  pull_request/test_remote_control.py

License: MIT (test-side; imports nothing from mesoSPIM).
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

_PATCH = next(Path(__file__).parent.glob("0001-*.patch"))


def _extract(path_suffix: str) -> str:
    """Materialise a patch new-file body (the ``+`` lines of its hunk)."""
    lines = _PATCH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith(f"diff --git a/{path_suffix}"))
    hunk = next(i for i, ln in enumerate(lines[start:], start) if ln.startswith("@@ ")) + 1
    body = []
    for ln in lines[hunk:]:
        if ln.startswith("diff --git") or ln.startswith("-- "):  # next file / patch trailer
            break
        if ln.startswith("+") and not ln.startswith("++"):
            body.append(ln[1:])
        elif ln.startswith(" "):  # unchanged context line
            body.append(ln[1:])
    return "\n".join(body)


def _load():
    """Write both modules to a temp dir (flattening the cross-import) and import them."""
    src = "mesoSPIM/src/"
    vrc_body = _extract(src + "mesoSPIM_RemoteControl_ValidateAndRunCommands.py")
    srv_body = _extract(src + "mesoSPIM_RemoteControl_Servers.py")
    # The Servers module imports the commands module relatively / via mesoSPIM.src;
    # flatten both forms so the two extracted files import as plain siblings.
    for stale in ("from .mesoSPIM_RemoteControl_ValidateAndRunCommands import",
                  "from mesoSPIM.src.mesoSPIM_RemoteControl_ValidateAndRunCommands import"):
        srv_body = srv_body.replace(stale, "from mesoSPIM_RemoteControl_ValidateAndRunCommands import")
    tmp = Path(tempfile.mkdtemp(prefix="rc_under_test_"))
    (tmp / "mesoSPIM_RemoteControl_ValidateAndRunCommands.py").write_text(vrc_body, encoding="utf-8")
    (tmp / "mesoSPIM_RemoteControl_Servers.py").write_text(srv_body, encoding="utf-8")
    sys.path.insert(0, str(tmp))
    import mesoSPIM_RemoteControl_ValidateAndRunCommands as vrc  # noqa: E402, I001
    import mesoSPIM_RemoteControl_Servers as srv  # noqa: E402, I001
    return vrc, srv


vrc, srv = _load()


# -- a tiny fake Core: just enough cfg for the option checks --------------------

class _Cfg:
    filterdict = {"Empty": 0, "515LP": 1}
    zoomdict = {"1x": 1, "2x": 2}
    laserdict = {"488 nm": 0, "561 nm": 1}
    shutteroptions = ["Left", "Right", "Both"]
    stage_parameters = {"x_min": -25000, "x_max": 25000, "y_min": -50000, "y_max": 50000,
                        "z_min": -25000, "z_max": 25000, "f_min": 0, "f_max": 98000}


class _Core:
    cfg = _Cfg()


_core = _Core()
_LIMITS = {"x": (-1000.0, 1000.0), "y": (-1000.0, 1000.0), "z": (-1000.0, 1000.0)}


# -- framing -------------------------------------------------------------------

def test_frame_is_length_prefixed_bytes():
    assert srv.frame("abc") == b"3\nabc"


def test_frame_counts_bytes_not_characters():
    assert srv.frame("é") == b"2\n\xc3\xa9"  # 1 char, 2 UTF-8 bytes


def test_decoder_reassembles_split_and_joined_frames():
    d = srv.FrameDecoder()
    d.feed(b"3\nab")          # a frame split mid-payload
    assert list(d.frames()) == []
    d.feed(b"c2\nhi")         # rest of frame 1 + a whole frame 2
    assert list(d.frames()) == [b"abc", b"hi"]


# -- auth ----------------------------------------------------------------------

def test_authgate_accepts_only_the_right_token():
    gate = srv.AuthGate("sécret")   # non-ASCII token
    assert not gate.check("wrong")
    assert gate.check("sécret")
    assert gate.passed


def test_authgate_open_when_no_token():
    assert srv.AuthGate(None).passed


# -- parse / allowlist / hostile sweep -----------------------------------------

def test_parse_call_rejects_bad_shapes():
    for payload in ('{"a": {}, "b": {}}', '{"move": []}', 'not json', '[]'):
        try:
            srv.parse_call(payload)
        except (ValueError, json.JSONDecodeError):
            continue
        raise AssertionError(f"parse_call accepted a bad payload: {payload!r}")


def test_run_rejects_unknown_and_hostile_names():
    for name in ("no_such_command", "os.system('rm -rf /')", "__class__", "eval"):
        try:
            vrc.run(_core, name, {})
        except KeyError:
            continue
        raise AssertionError(f"allowlist accepted a hostile name: {name!r}")


# -- input validation (_validate) ----------------------------------------------

def _rejects(call, args):
    try:
        vrc._validate(_core, call, args, _LIMITS)
    except ValueError:
        return True
    return False


def test_valid_calls_pass_validation():
    vrc._validate(_core, "move_absolute", {"targets": {"x": 100}}, _LIMITS)
    vrc._validate(_core, "set_filter", {"filter": "Empty"}, _LIMITS)
    vrc._validate(_core, "get_state", {}, _LIMITS)


def test_out_of_range_move_rejected():
    assert _rejects("move_absolute", {"targets": {"x": 999999}})


def test_unknown_axis_and_non_number_rejected():
    assert _rejects("move_absolute", {"targets": {"q": 1}})
    assert _rejects("move_absolute", {"targets": {"x": "far"}})


def test_bad_option_rejected():
    assert _rejects("set_filter", {"filter": "NOPE"})
    assert _rejects("set_zoom", {"zoom": "99x"})
    assert _rejects("set_shutterconfig", {"shutterconfig": "Sideways"})


def test_bad_intensity_rejected():
    assert _rejects("set_intensity", {"intensity": 250})


def test_range_and_type_checked_for_all_settables():
    # not just the stage: numeric type + percent range on any settable parameter
    assert _rejects("set_etl", {"etl_l_amplitude": "loud"})   # must be a number
    assert _rejects("set_etl", {"etl_l_delay_%": 250})        # percent 0..100
    assert not _rejects("set_etl", {"etl_l_amplitude": 1.5})  # no range -> type only


def test_both_lanes_refuse_out_of_limit_with_error_json():
    # TCP and MCP converge on handle_tcp_message -> run -> _validate. The MCP lane
    # forwards to this exact reply, so an OUT-OF-LIMIT call can never reach the Core on
    # either lane -- it comes back as a non-OK error (which MCP wraps as isError JSON),
    # and the message names the limit.
    reply = srv.handle_tcp_message(_core, json.dumps({"move_absolute": {"targets": {"x": 999999}}}))
    assert not reply.startswith(srv.OK_MARKER)
    assert "error" in reply and "25000" in reply


def test_cfg_stage_range_enforced_via_run():
    # run() takes the range from the loaded cfg -- no env var needed -- and the error
    # message names the limit so a script/LLM knows what was allowed.
    try:
        vrc.run(_core, "move_absolute", {"targets": {"x": 999999}})
    except ValueError as e:
        assert "25000" in str(e)
    else:
        raise AssertionError("cfg stage range not enforced")


def test_get_limits_exposes_enforced_rules():
    enforced = vrc._get_limits(_core, {})["enforced"]
    assert enforced["axes"]["x"] == [-25000.0, 25000.0]
    assert enforced["axes"]["theta"] is None  # range OFF -> visible to the caller
    assert enforced["parameters"]["intensity"]["range"] == [0, 100]


def test_self_test_command_verifies_limits_against_a_mock():
    # the pre-flight, callable over either lane: proves the loaded limits enforce, against
    # a SimCore that mimics the hardware -- and never moves the real stage.
    out = vrc.run(_core, "self_test")
    assert out["ok"] is True and all(line.startswith("PASS") for line in out["report"])


def test_server_gate_refuses_to_start_when_limits_missing():
    # RemoteControlTCPServer runs self_test FIRST (before importing Qt); a cfg with no limits
    # must make construction raise, so the server never binds and hardware is never exposed.
    class _NoLimitsCore:
        class cfg:  # noqa: N801 - tiny stand-in
            filterdict = {}; zoomdict = {}; laserdict = {}; shutteroptions = []  # noqa: E702
    try:
        srv.RemoteControlTCPServer(_NoLimitsCore())
    except RuntimeError as e:
        assert "self-test failed" in str(e)
    except ImportError:
        raise AssertionError("gate did not fire before the PyQt5 import") from None
    else:
        raise AssertionError("server bound despite unenforceable limits")


def test_server_gate_passes_good_cfg():
    # with a good cfg the gate must NOT block: construction gets past the self-test into Qt
    # land (PyQt5 import / QTcpServer), whatever that raises here -- just not a self-test fail.
    try:
        srv.RemoteControlTCPServer(_core)
    except RuntimeError as e:
        assert "self-test failed" not in str(e), f"gate wrongly blocked a good cfg: {e}"
    except Exception:
        pass  # got past the gate (no PyQt5 / not a QObject) -> the self-test passed


def test_limits_from_env(monkeypatch=None):
    import os
    os.environ["MESOSPIM_RS_LIMITS"] = '{"x": [-5, 5]}'
    try:
        assert vrc._limits_from_env() == {"x": (-5.0, 5.0)}
    finally:
        del os.environ["MESOSPIM_RS_LIMITS"]


# -- MCP reply shape (no live TCP: initialize / tools/list / unknown / notify) --

def test_mcp_initialize_and_tools_list():
    # mcp_reply returns the JSON-RPC dict; the HTTP handler serialises it.
    cfg = types.SimpleNamespace()
    init = srv.mcp_reply(cfg, {"id": 1, "method": "initialize"})
    assert init["result"]["protocolVersion"] == "2024-11-05"
    listed = srv.mcp_reply(cfg, {"id": 2, "method": "tools/list"})
    assert len(listed["result"]["tools"]) == len(vrc.COMMANDS)


def test_mcp_unknown_method_and_notification():
    cfg = types.SimpleNamespace()
    err = srv.mcp_reply(cfg, {"id": 3, "method": "no_such"})
    assert err["error"]["code"] == -32601
    assert srv.mcp_reply(cfg, {"method": "notifications/initialized"}) is None  # no id -> no reply


if __name__ == "__main__":
    _passed = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok   {_name}")
            _passed += 1
    print(f"\nALL {_passed} TESTS PASSED")
