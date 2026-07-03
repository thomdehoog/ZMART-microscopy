"""Qt-free checks on the upstream Remote Scripting patch under ``pull_request/``.

The patch is the artifact we would submit to mesoSPIM-control, and its server
keeps framing + auth socket-free precisely so they test without a Qt event loop.
These tests reconstruct ``mesoSPIM_RemoteScripting.py`` straight from the patch's
new-file hunk (so there is one source of truth -- the patch) and exercise the
security-sensitive logic: frame boundaries, oversized input, and the
constant-time token compare including a non-ASCII token.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATCH = (
    Path(__file__).resolve().parents[2]
    / "pull_request"
    / "0001-Add-optional-remote-scripting-server-Tools-Remote-Sc.patch"
)


def _load_server_module():
    """Materialise the patch's new ``mesoSPIM_RemoteScripting.py`` and import it.

    Extracts the ``+``-prefixed body of the new-file hunk, writes it to a temp
    module, and imports it. The module imports PyQt5 lazily (only inside the
    server class), so the framing/auth classes import here without Qt.
    """
    lines = _PATCH.read_text(encoding="utf-8").splitlines()
    start = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("diff --git a/mesoSPIM/src/mesoSPIM_RemoteScripting.py")
    )
    hunk = next(i for i, line in enumerate(lines[start:], start) if line.startswith("@@ ")) + 1
    body: list[str] = []
    for line in lines[hunk:]:
        if line.startswith("-- ") or line.startswith("diff --git"):
            break
        if line.startswith("+"):
            body.append(line[1:])
    tmp = Path(__file__).with_name("_rs_from_patch.py")
    tmp.write_text("\n".join(body) + "\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_rs_from_patch", tmp)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, tmp


@pytest.fixture(scope="module")
def rs():
    module, tmp = _load_server_module()
    try:
        yield module
    finally:
        tmp.unlink(missing_ok=True)


# -- framing ------------------------------------------------------------------


def test_frame_roundtrips_through_decoder(rs):
    dec = rs.FrameDecoder()
    dec.feed(rs.frame("hello") + rs.frame("world"))
    assert [p.decode() for p in dec.frames()] == ["hello", "world"]


def test_partial_frame_waits_for_the_rest(rs):
    dec = rs.FrameDecoder()
    wire = rs.frame("abcdef")
    dec.feed(wire[:3])
    assert list(dec.frames()) == []  # length line not complete
    dec.feed(wire[3:-2])
    assert list(dec.frames()) == []  # payload not complete
    dec.feed(wire[-2:])
    assert [p.decode() for p in dec.frames()] == ["abcdef"]


def test_frame_length_counts_bytes_not_chars(rs):
    dec = rs.FrameDecoder()
    dec.feed(rs.frame("µm→"))  # multi-byte UTF-8
    assert [p.decode() for p in dec.frames()] == ["µm→"]


def test_bad_length_line_raises(rs):
    dec = rs.FrameDecoder()
    dec.feed(b"notanumber\npayload")
    with pytest.raises(rs.FramingError):
        list(dec.frames())


def test_buffered_tracks_unconsumed_bytes(rs):
    dec = rs.FrameDecoder()
    dec.feed(rs.frame("ab") + b"7\npart")  # one whole frame + an incomplete one
    list(dec.frames())
    assert dec.buffered == len(b"7\npart")


# -- auth ---------------------------------------------------------------------


def test_no_token_passes_from_the_start(rs):
    gate = rs.AuthGate(None)
    assert gate.passed and not gate.required


def test_correct_token_passes(rs):
    gate = rs.AuthGate("s3cret")
    assert gate.required and not gate.passed
    assert gate.check("s3cret") and gate.passed


def test_wrong_token_stays_closed(rs):
    gate = rs.AuthGate("s3cret")
    assert not gate.check("nope")
    assert not gate.passed


def test_non_ascii_token_works(rs):
    # A str token with non-ASCII would crash hmac.compare_digest; bytes is why.
    assert rs.AuthGate("pä55wörd").check("pä55wörd")


def test_empty_token_is_treated_as_no_token(rs):
    assert rs.AuthGate("").passed


# -- robustness: a dropped client must never crash mesoSPIM -------------------


class _ReclaimedSocket:
    """A QTcpSocket whose C++ object Qt has already deleted: every call raises
    ``RuntimeError`` ("wrapped C/C++ object ... has been deleted"), like the real
    thing does after Qt reclaims it."""

    class _Signal:
        def disconnect(self):
            raise RuntimeError("wrapped C/C++ object of type QTcpSocket has been deleted")

    disconnected = _Signal()

    def deleteLater(self):
        raise RuntimeError("wrapped C/C++ object of type QTcpSocket has been deleted")

    def disconnectFromHost(self):
        raise RuntimeError("wrapped C/C++ object of type QTcpSocket has been deleted")


def test_disconnect_of_reclaimed_socket_never_raises(rs):
    # The bug this guards: _on_disconnected/_drop_client called deleteLater() on a
    # socket Qt had already reclaimed, raising RuntimeError that propagated out and
    # crashed the whole mesoSPIM app. A dropped/crashed client must never do that.
    # Build the server via __new__ so no Qt event loop / socket is needed.
    server = rs.RemoteScriptingServer.__new__(rs.RemoteScriptingServer)
    dead = _ReclaimedSocket()

    server._conn = dead
    server._on_disconnected(dead)  # must not raise
    assert server._conn is None

    server._conn = dead
    server._drop_client(dead)  # must not raise
    assert server._conn is None
