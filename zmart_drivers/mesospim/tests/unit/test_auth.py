"""Token auth for the command server (the network gate).

The command server can require a shared token. When one is set it must be
presented in the ``hello`` handshake, and until then every command is refused
(fail-closed) -- so a client that skips ``hello`` cannot drive the scope. When no
token is set the server is open (localhost use). Tested against the offline mock
server, which mirrors the real server's auth so this runs with no Qt/mesoSPIM.

Author: Thom de Hoog (ZMB, University of Zurich). License: MIT.
"""
from __future__ import annotations

import pytest
from mock_mesospim_server import MockMesospimServer

import mesospim as drv
from mesospim.connection.client import MesospimClient, MesospimError


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


def test_token_server_refuses_command_before_hello():
    """A client that skips the handshake cannot issue commands (fail-closed)."""
    import json
    import socket

    with MockMesospimServer(token="s3cret") as srv:
        raw = socket.create_connection((srv.host, srv.port), timeout=3.0)
        try:
            raw.sendall(b'{"cmd": "move_absolute", "args": {"targets": {"x": 100}}, "id": 1}\n')
            buf = b""
            while b"\n" not in buf:
                buf += raw.recv(4096)
            resp = json.loads(buf.split(b"\n", 1)[0].decode())
            assert resp["ok"] is False, "unauthenticated command must be refused"
        finally:
            raw.close()
