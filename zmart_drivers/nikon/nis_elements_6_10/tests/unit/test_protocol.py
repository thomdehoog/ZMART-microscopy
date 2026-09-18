"""The wire format: requests and replies survive a round trip, errors come back as exceptions."""

import pytest
from nis_elements_6_10 import protocol


def test_request_round_trip():
    line = protocol.encode_request(3, "move_xyz", {"x": 1.5, "y": -2, "z": 0})
    assert line.endswith("\n") and "\n" not in line[:-1]
    assert protocol.decode_request(line) == (3, "move_xyz", {"x": 1.5, "y": -2, "z": 0})


def test_reply_round_trip():
    line = protocol.encode_reply(3, {"x": 1.0})
    assert protocol.decode_reply(line) == (3, {"x": 1.0})


@pytest.mark.parametrize(
    "exc, kind",
    [(ValueError("bad arg"), ValueError), (RuntimeError("DR_NOTINITIALIZED"), RuntimeError)],
)
def test_error_reply_raises_same_kind(exc, kind):
    with pytest.raises(kind, match=str(exc)):
        protocol.decode_reply(protocol.encode_error(9, exc))


def test_unknown_exception_becomes_runtime_error_with_type_name():
    with pytest.raises(RuntimeError, match="KeyError"):
        protocol.decode_reply(protocol.encode_error(1, KeyError("x")))


@pytest.mark.parametrize("line", ["not json", "[1,2]", '{"args": {}}', '{"op": "ping", "args": 5}'])
def test_malformed_request_is_a_protocol_error(line):
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_request(line)


def test_malformed_reply_is_a_protocol_error():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_reply('{"id": 1}')
