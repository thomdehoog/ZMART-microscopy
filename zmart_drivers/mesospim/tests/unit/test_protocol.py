"""The Remote Control wire contract (pure, no sockets): framing, calls, replies, operations."""

from __future__ import annotations

import json

import pytest
from mesospim import protocol as p

# -- framing ------------------------------------------------------------------


def test_frame_length_prefix():
    assert p.frame("abc") == b"3\nabc"
    assert p.frame(b"hello") == b"5\nhello"


def test_frame_counts_bytes_not_chars():
    # A 1-char non-ASCII string is 2 UTF-8 bytes; the count must be byte length.
    assert p.frame("é") == b"2\n\xc3\xa9"


def test_frame_refuses_oversized_payload():
    with pytest.raises(p.ProtocolError):
        p.frame(b"x" * (p.MAX_FRAME_BYTES + 1))


def test_frame_length_accepts_only_canonical_headers():
    assert p.frame_length(b"42") == 42
    for bad in (b"", b"-1", b"4a", b"1" * 17, str(p.MAX_FRAME_BYTES + 1).encode()):
        with pytest.raises(p.ProtocolError):
            p.frame_length(bad)


# -- calls ----------------------------------------------------------------------


def test_encode_call_is_one_named_object():
    text = p.encode_call("move_absolute", {"targets": {"x": 100.0}})
    assert json.loads(text) == {"move_absolute": {"targets": {"x": 100.0}}}


def test_encode_call_without_args_sends_empty_object():
    assert json.loads(p.encode_call("ping")) == {"ping": {}}


def test_encode_call_refuses_non_finite_numbers():
    # The server rejects NaN/Infinity as invalid JSON; refuse them before sending.
    with pytest.raises(p.ProtocolError):
        p.encode_call("move_absolute", {"targets": {"x": float("nan")}})


def test_encode_call_needs_a_name():
    with pytest.raises(p.ProtocolError):
        p.encode_call("", {})


# -- replies ---------------------------------------------------------------------


def test_parse_ok_reply():
    reply = p.parse_reply(p.OK_MARKER + '{"x": 1.5, "y": 2}')
    assert reply.ok and reply.data == {"x": 1.5, "y": 2} and reply.code is None


def test_parse_ok_reply_with_non_object_body_is_wrapped():
    reply = p.parse_reply(p.OK_MARKER + "[1, 2]")
    assert reply.ok and reply.data == {"result": [1, 2]}


@pytest.mark.parametrize(
    "text, code",
    [
        ("error: [validation] x=1 is outside the allowed range", "validation"),
        ("error: [busy] busy: move_absolute (op-000001) is running", "busy"),
        ("error: [unknown_command] unknown command: 'bogus'", "unknown_command"),
        ("error: [execution] KeyError('acq_list')", "execution"),
    ],
)
def test_parse_error_reply_carries_code_and_message(text, code):
    reply = p.parse_reply(text)
    assert not reply.ok and reply.code == code
    assert reply.error and reply.error in text


def test_parse_garbage_raises_protocol_error():
    with pytest.raises(p.ProtocolError):
        p.parse_reply("Traceback (most recent call last): ...")
    with pytest.raises(p.ProtocolError):
        p.parse_reply(p.OK_MARKER + "not json")


# -- operations ------------------------------------------------------------------


def test_operation_of_and_is_active():
    accepted = {"accepted": True, "operation": {"id": "op-000001", "status": "processing"}}
    op = p.operation_of(accepted)
    assert op == {"id": "op-000001", "status": "processing"}
    assert p.is_active(op)
    assert p.is_active({"status": "stopping"})
    assert not p.is_active({"status": "completed"})
    assert not p.is_active({"status": "idle"})
    assert p.operation_of({"x": 1}) is None and not p.is_active(None)
