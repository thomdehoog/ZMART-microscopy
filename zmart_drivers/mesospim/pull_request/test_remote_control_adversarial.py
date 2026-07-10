"""Wide ADVERSARIAL sweep for the Remote Control PR.

Where ``test_remote_control.py`` proves the happy path and the basic refusals, this
file tries hard to BREAK the two guarantees the server makes:

  1. Nothing outside the ``COMMANDS`` allowlist can ever run.
  2. TCP and MCP can never breach a limit -- a bad type / option / range comes back
     as an error and NEVER reaches the Core; and a client cannot change the limits.

It reuses the exact same modules the sibling test rebuilds straight from the
``0001-*.patch`` (one source of truth), and drives them through the SAME choke point
both real transports use (``handle_tcp_message`` -> ``run`` -> ``_validate``) plus the
MCP reply builder. A ``_RecordingCore`` records every Core call, so we can assert a
rejected call left the instrument untouched. No Qt, no mesoSPIM, no third-party imports. Run::

    pytest pull_request/test_remote_control_adversarial.py
    python  pull_request/test_remote_control_adversarial.py

License: MIT (test-side; imports nothing from mesoSPIM).
"""
from __future__ import annotations

import json
import types

from test_remote_control import _Cfg, srv, vrc  # rebuilt-from-patch modules + fake cfg

INF, NAN = float("inf"), float("nan")


# -- a Core that RECORDS every call, so "never reached the Core" is checkable --------

class _RecordingCore:
    cfg = _Cfg()

    def __init__(self):
        self.calls = []

    def move_absolute(self, sdict, wait_until_done=False):
        self.calls.append(("move_absolute", sdict))

    def move_relative(self, ddict, wait_until_done=False):
        self.calls.append(("move_relative", ddict))

    def set_filter(self, *a, **k):
        self.calls.append(("set_filter", a))

    def set_intensity(self, *a, **k):
        self.calls.append(("set_intensity", a))

    def state_request_handler(self, settings):
        self.calls.append(("state_request_handler", settings))


def _reply(core, obj):
    """Send one call the way a TCP/MCP client does and return (ok, text)."""
    text = srv.handle_tcp_message(core, json.dumps(obj))
    return text.startswith(srv.OK_MARKER), text


def _refused_untouched(obj):
    """The call must come back as an error AND leave the Core with zero calls made."""
    core = _RecordingCore()
    ok, text = _reply(core, obj)
    assert not ok, f"expected refusal, got OK for {obj!r}"
    assert core.calls == [], f"a refused call still reached the Core: {core.calls!r}"
    return text


# =====================================================================================
# 1) The allowlist cannot be escaped -- no name outside COMMANDS ever runs.
# =====================================================================================

HOSTILE_NAMES = [
    "__class__", "__globals__", "__import__", "eval", "exec", "compile",
    "os.system('rm -rf /')", "subprocess", "getattr", "setattr",
    "run", "COMMANDS", "_validate", "handle_tcp_message",          # real internals
    "move_absolute\n", " move_absolute", "move_absolute ", "MOVE_ABSOLUTE",
    "move_absolute;", "move_absolute\x00", "mⲟve_absolute",         # trailing/case/unicode
    "", " ", ".", "..", "*", "%s", "{}", "\t", "a" * 5000,
]


def test_no_hostile_method_name_ever_runs():
    for name in HOSTILE_NAMES:
        _refused_untouched({name: {}})


def test_run_raises_keyerror_for_unknown_names():
    for name in HOSTILE_NAMES:
        try:
            vrc.run(_RecordingCore(), name, {})
        except KeyError:
            continue
        raise AssertionError(f"allowlist accepted {name!r}")


# =====================================================================================
# 2) parse_call rejects every malformed envelope shape (single-key object only).
# =====================================================================================

def test_parse_call_rejects_malformed_envelopes():
    bad = [
        '{}', '{"a":{},"b":{}}', '[]', 'null', '5', '"x"', 'true',
        '{"move_absolute": []}', '{"move_absolute": 5}', '{"move_absolute": "x"}',
        'not json at all', '{', '{"a":}', '',
        '{"a": {"b": {"c": {"d": {"e": 1}}}}, "f": 2}',      # multi-key + nested
    ]
    for payload in bad:
        try:
            srv.parse_call(payload)
        except (ValueError, json.JSONDecodeError):
            continue
        raise AssertionError(f"parse_call accepted {payload!r}")


def test_null_args_become_empty_and_bad_args_type_rejected():
    # {"ping": null} is allowed (null args -> {}); a non-object args is rejected.
    call, args = srv.parse_call('{"ping": null}')
    assert call == "ping" and args == {}
    for payload in ('{"move_absolute": 5}', '{"move_absolute": "x"}', '{"move_absolute": [1]}'):
        try:
            srv.parse_call(payload)
        except ValueError:
            continue
        raise AssertionError(f"parse_call accepted non-object args: {payload!r}")


# =====================================================================================
# 3) Limits cannot be breached -- every axis, every direction, every rogue number.
# =====================================================================================

# cfg envelope in the fake _Cfg: x +/-25000, y +/-50000, z +/-25000, f [0, 98000], no theta.
_AXIS_LIMIT = {"x": (-25000, 25000), "y": (-50000, 50000), "z": (-25000, 25000), "f": (0, 98000)}


def test_every_axis_rejects_just_out_of_range():
    for axis, (lo, hi) in _AXIS_LIMIT.items():
        for value in (hi + 1, lo - 1, hi + 1e9, lo - 1e9):
            text = _refused_untouched({"move_absolute": {"targets": {axis: value}}})
            assert str(hi) in text or str(lo) in text, f"limit not named for {axis}: {text}"


def test_moves_reject_nan_inf_and_huge():
    for value in (NAN, INF, -INF, 1e308 * 10):   # 1e308*10 == inf
        _refused_untouched({"move_absolute": {"targets": {"x": value}}})


def test_boundary_values_pass_validation():
    # exact min/max are IN range -- _validate must not reject them (checked directly,
    # since the real move handler isn't on the fake core).
    lim = vrc._effective_limits(_RecordingCore())
    for axis, (lo, hi) in _AXIS_LIMIT.items():
        vrc._validate(_RecordingCore(), "move_absolute", {"targets": {axis: lo}}, lim)
        vrc._validate(_RecordingCore(), "move_absolute", {"targets": {axis: hi}}, lim)


def test_valid_move_does_reach_core():
    # sanity: the choke point is not just blocking everything -- an in-range move runs.
    core = _RecordingCore()
    ok, _ = _reply(core, {"move_absolute": {"targets": {"x": 100}}})
    assert ok and core.calls and core.calls[0][0] == "move_absolute"


def test_percentages_reject_out_of_0_100():
    for value in (100.5, -0.5, 101, -1, NAN, INF, -INF):
        _refused_untouched({"set_intensity": {"intensity": value}})
        _refused_untouched({"set_etl": {"etl_l_delay_%": value}})


def test_percentage_boundaries_pass():
    lim = {}
    for value in (0, 100, 50, 0.0, 100.0):
        vrc._validate(_RecordingCore(), "set_intensity", {"intensity": value}, lim)


# =====================================================================================
# 4) Type confusion -- wrong JSON types for every value slot are refused.
# =====================================================================================

def test_type_confusion_is_refused():
    cases = [
        {"move_absolute": {"targets": {"x": "far"}}},     # number slot gets a string
        {"move_absolute": {"targets": {"x": True}}},      # bool is NOT a number
        {"move_absolute": {"targets": {"x": None}}},
        {"move_absolute": {"targets": {"x": [1]}}},
        {"move_absolute": {"targets": [1, 2]}},           # targets not an object
        {"move_absolute": {"targets": {}}},               # empty targets
        {"set_filter": {"filter": 1}},                    # string slot gets a number
        {"set_filter": {"filter": None}},
        {"set_filter": {"filter": ["Empty"]}},
        {"set_intensity": {"intensity": "50"}},           # string, not number
        {"set_intensity": {"intensity": True}},           # bool, not number
        {"set_state": {"settings": "laser"}},             # settings not an object
        {"set_state": {"settings": {}}},                  # empty settings
        {"set_etl": {"etl_l_amplitude": [1]}},            # number slot gets a list
        {"set_etl": {"etl_l_amplitude": "loud"}},
    ]
    for obj in cases:
        _refused_untouched(obj)


# =====================================================================================
# 5) The limits themselves cannot be changed by any client.
# =====================================================================================

def test_no_command_can_write_limits():
    # there is simply no allowlisted verb that mutates the config / travel envelope.
    for verb in ("set_limits", "set_stage_parameters", "set_config", "set_cfg",
                 "write_config", "update_limits"):
        assert verb not in vrc.COMMANDS


def test_set_state_cannot_smuggle_a_limit_key():
    # x_max is not a settable state key -> the handler refuses it; the envelope is safe.
    text = _refused_untouched({"set_state": {"settings": {"x_max": 999999}}})
    assert "x_max" in text
    # and the reported limits are unchanged after the attempt
    assert vrc._get_limits(_RecordingCore(), {})["enforced"]["axes"]["x"] == [-25000.0, 25000.0]


def test_get_limits_is_pure():
    core = _RecordingCore()
    a = vrc._get_limits(core, {})
    b = vrc._get_limits(core, {})
    assert a == b and core.calls == []   # reads nothing, changes nothing


# =====================================================================================
# 6) The MCP lane converts a hostile/failed call into an isError JSON -- never a crash,
#    never a local execution of the tool name.
# =====================================================================================

def _mcp_config():
    # points the forwarder at a closed port so tcp_call fails fast (connection refused);
    # the point is that the FAILURE becomes error JSON, and the name is never run locally.
    return types.SimpleNamespace(token="", quiet=True, timeout=0.2,
                                 mesospim_host="127.0.0.1", mesospim_port=1, mesospim_token="")


def test_mcp_tools_call_hostile_name_is_error_not_crash():
    cfg = _mcp_config()
    for name in ("__import__", "os.system('x')", "move_absolute", "eval"):
        reply = srv.mcp_reply(cfg, {"id": 1, "method": "tools/call",
                                    "params": {"name": name, "arguments": {}}})
        assert reply["result"]["isError"] is True
        assert "error" in reply["result"]["content"][0]["text"]


def test_mcp_reply_survives_malformed_messages():
    cfg = _mcp_config()
    for msg in ({"id": 1, "method": "tools/call"},                 # no params
                {"id": 1, "method": "tools/call", "params": None},
                {"id": 1, "method": "tools/call", "params": {"name": None}},
                {"id": 1, "method": 123},                          # non-string method
                {"method": "tools/call", "params": {"name": "x"}}):  # no id -> no reply
        srv.mcp_reply(cfg, msg)  # must not raise


# =====================================================================================
# 7) Framing + auth cannot be tricked.
# =====================================================================================

def test_frame_decoder_rejects_or_waits_but_never_crashes():
    for head in (b"abc\n", b"-5\ndata", b"12x\ndata"):
        d = srv.FrameDecoder()
        d.feed(head)
        try:
            list(d.frames())
        except srv.FramingError:
            continue
        raise AssertionError(f"decoder accepted bad header {head!r}")


def test_frame_decoder_rejects_huge_length_without_waiting_or_allocating():
    d = srv.FrameDecoder()
    d.feed(b"999999999\nhi")     # claims ~1GB; only 2 bytes present
    try:
        list(d.frames())
    except srv.FramingError:
        return
    raise AssertionError("decoder waited for an oversized frame instead of rejecting it")


def test_frame_decoder_reassembles_and_handles_empty_and_joined():
    d = srv.FrameDecoder()
    d.feed(b"0\n")                       # empty payload
    d.feed(b"3\nabc2\nhi")               # two joined frames
    assert list(d.frames()) == [b"", b"abc", b"hi"]


def test_authgate_cannot_be_bypassed():
    gate = srv.AuthGate("sécret")
    for wrong in ("", "secret", "sécre", "sécret ", "SÉCRET", "sécrett"):
        assert not gate.check(wrong)
        assert not gate.passed
    assert gate.check("sécret") and gate.passed


def test_authgate_open_only_when_no_token():
    assert srv.AuthGate(None).passed
    assert srv.AuthGate("").passed        # empty string == no token
    assert not srv.AuthGate("x").passed


if __name__ == "__main__":
    _passed = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok   {_name}")
            _passed += 1
    print(f"\nALL {_passed} ADVERSARIAL TESTS PASSED")
