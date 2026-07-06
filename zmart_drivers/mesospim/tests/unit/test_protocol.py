"""Framing + the named-call codec (pure, socket-free).

The transport carries one JSON call each way: the client sends the single-key
``{"<method>": {args}}`` (:func:`encode_call`), the server dispatches and replies
with the ``__ZMART_OK__<json>`` line (:func:`encode_reply`), and the client reads
it back (:func:`parse_result`). On error the reply has no marker line and the
whole text surfaces as the error.
"""

from __future__ import annotations

import pytest
from mesospim import protocol as p

# -- framing ------------------------------------------------------------------


def test_frame_length_prefix():
    assert p.frame("abc") == b"3\nabc"
    assert p.frame(b"hello") == b"5\nhello"


def test_frame_counts_bytes_not_chars():
    # A 1-char non-ASCII string is 2 UTF-8 bytes; the count must be byte length.
    assert p.frame("é") == b"2\n\xc3\xa9"


# -- request codec: encode_call / decode_call ---------------------------------


def test_encode_call_is_single_key_json_data():
    assert p.encode_call("set_state", {"settings": {"filter": "561/LP"}}) == (
        '{"set_state": {"settings": {"filter": "561/LP"}}}'
    )


def test_encode_then_decode_round_trips():
    call, args = p.decode_call(p.encode_call("move_absolute", {"targets": {"x": 1.0}}))
    assert call == "move_absolute" and args == {"targets": {"x": 1.0}}


def test_encode_call_defaults_args_to_empty_object():
    assert p.encode_call("ping") == '{"ping": {}}'


def test_decode_rejects_a_non_single_key_object():
    with pytest.raises(p.ProtocolError):
        p.decode_call('{"a": {}, "b": {}}')


# -- reply codec: encode_reply / parse_result ---------------------------------


def test_reply_round_trips():
    reply = p.parse_result(p.encode_reply({"x": 42}))
    assert reply.ok and reply.data == {"x": 42}


def test_error_reply_has_no_marker_and_surfaces_as_text():
    # the server sends a traceback (no OK line); parse_result returns it as error
    reply = p.parse_result("Traceback (most recent call last):\nValueError: boom")
    assert not reply.ok and "boom" in reply.error


def test_last_marker_wins_over_interleaved_output():
    console = "noise from another thread\n" + p.encode_reply({"v": 1})
    reply = p.parse_result(console)
    assert reply.ok and reply.data == {"v": 1}


def test_malformed_payload_raises_protocol_error():
    with pytest.raises(p.ProtocolError):
        p.parse_result(p.OK_MARKER + "not-json")


def test_ok_result_must_be_an_object():
    with pytest.raises(p.ProtocolError):
        p.parse_result(p.OK_MARKER + "[1, 2, 3]")
