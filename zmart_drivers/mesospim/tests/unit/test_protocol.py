"""Pure protocol encode/parse -- no sockets."""

from __future__ import annotations

import pytest
from mesospim import protocol as p


def test_encode_request_roundtrip():
    line = p.encode_request("move_absolute", args={"targets": {"x": 10.0}}, id=3)
    req = p.parse_request(line)
    assert req.cmd == "move_absolute"
    assert req.args == {"targets": {"x": 10.0}}
    assert req.id == 3


def test_encode_request_defaults_empty_args():
    req = p.parse_request(p.encode_request("ping"))
    assert req.cmd == "ping" and req.args == {} and req.id is None


def test_encode_ok_and_parse():
    reply = p.parse_reply(p.encode_ok({"position": {"x": 1}}, id=7))
    assert reply.ok and reply.data == {"position": {"x": 1}} and reply.id == 7 and reply.error == ""


def test_encode_error_and_parse():
    reply = p.parse_reply(p.encode_error("nope", id=1))
    assert not reply.ok and reply.error == "nope" and reply.data == {}


def test_frame_appends_terminator():
    assert p.frame("x").endswith(b"\n")


def test_parse_tolerates_trailing_newline():
    req = p.parse_request(p.encode_request("ping") + "\n")
    assert req.cmd == "ping"


@pytest.mark.parametrize("bad", ["", "not json", "[1,2,3]", "123"])
def test_parse_request_rejects_non_object(bad):
    with pytest.raises(p.ProtocolError):
        p.parse_request(bad)


def test_parse_request_requires_cmd():
    with pytest.raises(p.ProtocolError):
        p.parse_request('{"args": {}}')


def test_parse_reply_requires_ok():
    with pytest.raises(p.ProtocolError):
        p.parse_reply('{"data": {}}')


def test_encode_request_rejects_empty_cmd():
    with pytest.raises(p.ProtocolError):
        p.encode_request("")
