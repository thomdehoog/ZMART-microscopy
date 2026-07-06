"""Remote-scripting framing + the simple print-the-result harness (pure).

The harness is tested end to end: build a script with ``wrap_script``, actually
``exec`` it capturing stdout (as the server does), then extract the result with
``parse_result``.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
from mesospim import protocol as p


def _run(script: str) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        exec(script, {})  # noqa: S102 - exercising the harness the server runs
    return buf.getvalue()


# -- framing ------------------------------------------------------------------


def test_frame_length_prefix():
    assert p.frame("abc") == b"3\nabc"
    assert p.frame(b"hello") == b"5\nhello"


def test_frame_counts_bytes_not_chars():
    # A 1-char non-ASCII string is 2 UTF-8 bytes; the count must be byte length.
    assert p.frame("é") == b"2\n\xc3\xa9"


# -- harness: ok / error ------------------------------------------------------


def test_wrap_and_parse_ok():
    reply = p.parse_result(_run(p.wrap_script("_result = {'x': 42}")))
    assert reply.ok and reply.data == {"x": 42}


def test_wrap_and_parse_error_is_structured():
    reply = p.parse_result(_run(p.wrap_script("raise ValueError('boom')")))
    assert not reply.ok and "boom" in reply.error


def test_missing_marker_becomes_error():
    # A pre-harness failure (syntax error, auth text, ...) has no marker line; the
    # whole console text is surfaced as the error, not a parse crash.
    reply = p.parse_result("Traceback: SyntaxError somewhere")
    assert not reply.ok and "Traceback" in reply.error


def test_last_marker_wins_over_interleaved_output():
    body = "print('noise from another thread')\n_result = {'v': 1}"
    reply = p.parse_result(_run(p.wrap_script(body)))
    assert reply.ok and reply.data == {"v": 1}


def test_malformed_payload_raises_protocol_error():
    with pytest.raises(p.ProtocolError):
        p.parse_result(p.OK_MARKER + "not-json")


def test_ok_result_must_be_an_object():
    with pytest.raises(p.ProtocolError):
        p.parse_result(p.OK_MARKER + "[1, 2, 3]")
