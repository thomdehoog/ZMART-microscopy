"""The password gate of the Remote Control server (the network gate).

The server never serves a client that has not sent the password as its first
frame. mesoSPIM ships with a public placeholder that only works on the local
machine; the driver uses it unless told otherwise. Tested against the offline
mock server, which mirrors the real server's gate so this runs with no
Qt/mesoSPIM.

Author: Thom de Hoog (ZMB, University of Zurich). License: MIT.
"""

from __future__ import annotations

import mesospim as drv
import pytest
from mesospim.connection.client import MesospimClient, MesospimError
from mock_mesospim_server import DEFAULT_TOKEN, MockMesospimServer


def test_default_password_is_mesospims_loopback_placeholder():
    # The driver's default password is the one mesoSPIM ships with, so a
    # local demo works out of the box.
    with MockMesospimServer(token=DEFAULT_TOKEN) as srv:
        c = MesospimClient(srv.host, srv.port, timeout=3.0)
        c.connect()
        try:
            assert c.server_info.get("app") == "mesoSPIM-control"
        finally:
            c.close()


def test_wrong_password_is_refused():
    with MockMesospimServer(token="s3cret") as srv:
        c = MesospimClient(srv.host, srv.port, timeout=3.0, token="nope")
        with pytest.raises(MesospimError, match="password"):
            c.connect()
        assert not c.connected


def test_missing_password_falls_back_to_default_and_is_refused_by_a_custom_one():
    with MockMesospimServer(token="s3cret") as srv:
        c = MesospimClient(srv.host, srv.port, timeout=3.0)  # no token given
        with pytest.raises(MesospimError):
            c.connect()


def test_correct_password_serves_calls():
    with MockMesospimServer(token="s3cret") as srv:
        c = MesospimClient(srv.host, srv.port, timeout=3.0, token="s3cret")
        c.connect()
        try:
            assert c.server_info.get("app") == "mesoSPIM-control"
            assert drv.get_config(c).get("lasers"), "authenticated client should be served"
        finally:
            c.close()


def test_non_ascii_password_roundtrips():
    """A unicode password must work: the server compares UTF-8 bytes in constant time."""
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


def test_a_call_before_the_password_is_refused():
    """Fail-closed: the FIRST frame must be the password; a call in its place is
    answered ``AUTH-FAILED`` and the connection closed."""
    import socket

    from mesospim.protocol import encode_call, frame

    with MockMesospimServer(token="s3cret") as srv:
        raw = socket.create_connection((srv.host, srv.port), timeout=3.0)
        try:
            raw.sendall(frame(encode_call("move_absolute", {"targets": {"x": 100}})))
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
        assert srv.core.moves == 0


def test_session_connect_reads_token_from_connection_dict():
    with MockMesospimServer(token="s3cret") as srv:
        client = drv.connect({"host": srv.host, "port": srv.port, "token": "s3cret"})
        try:
            assert drv.ping(client)
        finally:
            drv.close(client)
