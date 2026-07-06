"""Minimal test for the Remote Scripting PR -- framing + the token gate.

Self-contained: it rebuilds ``mesoSPIM_RemoteScripting.py`` straight from the
``0001-*.patch`` new-file hunk (one source of truth -- the patch itself), then
checks the two things the wire protocol promises: frames round-trip, and the
shared token is enforced in constant time. No Qt, no mesoSPIM, no ZMART imports
-- the framing/auth classes are Qt-free on purpose. Run it either way::

    pytest pull_request/test_remote_scripting.py
    python  pull_request/test_remote_scripting.py

License: MIT (test-side; imports nothing from mesoSPIM).
"""

from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":  # runnable without pytest, for a quick check next to the PR
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
