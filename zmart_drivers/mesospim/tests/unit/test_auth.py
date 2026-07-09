"""Token auth for the command server (the network gate).

The command server can require a shared token. When one is set it must be
presented in the ``hello`` handshake, and until then every command is refused
(fail-closed) -- so a client that skips ``hello`` cannot drive the scope. When no
token is set the server is open (localhost use). Tested against the offline mock
server, which mirrors the real server's auth so this runs with no Qt/mesoSPIM.

Author: Thom de Hoog (ZMB, University of Zurich). License: MIT.
"""

from __future__ import annotations

import mesospim as drv
import pytest
from mesospim.connection.client import MesospimClient, MesospimError
from mock_mesospim_server import MockMesospimServer


def test_open_server_allows_connect_without_token():
    with MockMesospimServer() as srv:
        c = MesospimClient(srv.host, srv.port, timeout=3.0)
        c.connect()
        try:
            assert c.server_info.get("app") == "mesoSPIM-control"
        finally:
            c.close()


def test_token_server_refuses_missing_token():
    with MockMesospimServer(token="s3cret") as srv:
        c = MesospimClient(srv.host, srv.port, timeout=3.0)  # no token
        with pytest.raises(MesospimError):
            c.connect()
        assert not c.connected


def test_token_server_refuses_wrong_token():
    with MockMesospimServer(token="s3cret") as srv:
        c = MesospimClient(srv.host, srv.port, timeout=3.0, token="nope")
        with pytest.raises(MesospimError):
            c.connect()


def test_token_server_accepts_correct_token_and_serves_commands():
    with MockMesospimServer(token="s3cret") as srv:
        c = MesospimClient(srv.host, srv.port, timeout=3.0, token="s3cret")
        c.connect()
        try:
            assert c.server_info.get("app") == "mesoSPIM-control"
            assert drv.get_config(c).get("lasers"), "authenticated client should be served"
        finally:
            c.close()


def test_non_ascii_token_roundtrips():
    """A unicode token must work: hmac.compare_digest rejects non-ASCII str, so
    the server compares UTF-8 bytes. Regression for a token like 'bütton'."""
    with MockMesospimServer(token="bütton") as srv:
        good = MesospimClient(srv.host, srv.port, timeout=3.0, token="bütton")
        good.connect()
        try:
            assert good.server_info.get("app") == "mesoSPIM-control"
        finally:
            good.close()
        bad = MesospimClient(srv.host, srv.port, timeout=3.0, token="button")
        with pytest.raises(MesospimError):
            bad.connect()


def test_token_server_refuses_script_before_token():
    """A client whose first frame is not the token is rejected (fail-closed).

    With a token set, the FIRST frame must be that token; anything else (here a
    script) is refused with ``AUTH-FAILED`` and the connection closed, so an
    unauthenticated client can never run code on the scope.
    """
    import socket

    from mesospim.protocol import frame

    with MockMesospimServer(token="s3cret") as srv:
        raw = socket.create_connection((srv.host, srv.port), timeout=3.0)
        try:
            raw.sendall(frame("self.move_absolute({'x_abs': 100}, wait_until_done=True)"))
            buf = b""
            while b"\n" not in buf:
                buf += raw.recv(4096)
            head, _, rest = buf.partition(b"\n")
            length = int(head)
            while len(rest) < length:
                rest += raw.recv(4096)
            assert rest[:length].decode() == "AUTH-FAILED"
        finally:
            raw.close()
