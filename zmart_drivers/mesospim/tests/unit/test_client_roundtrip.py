"""MesospimClient <-> MockMesospimServer round-trip over a real localhost socket.

The mock is a faithful Remote Control double: it validates calls the way the
real server does and hands every change back as an operation to poll, so these
exercise the real framing, the call/reply contract and the polling -- only
without a live hardware Core.
"""

from __future__ import annotations

import pytest
from mesospim.connection.client import MesospimClient, MesospimError
from mesospim.protocol import PROTOCOL_VERSION
from mock_mesospim_server import MockMesospimServer


def test_connect_greeting_populates_server_info(client):
    assert client.server_info.get("app") == "mesoSPIM-control"
    assert client.server_info.get("protocol") == PROTOCOL_VERSION


def test_ping_request(client):
    assert client.request("ping").ok


def test_read_timeout_override_is_restored(client):
    # A per-call read_timeout must apply only to that call and then restore the
    # base socket deadline -- and must never be forwarded as a call argument.
    base = client._sock.gettimeout()
    assert client.request("ping", read_timeout=42.0).ok
    assert client._sock.gettimeout() == base


def test_request_returns_data(client):
    reply = client.request("get_config")
    assert reply.ok
    assert "lasers" in reply.data


def test_validation_error_is_a_refusal_with_a_code(client):
    reply = client.try_request("move_absolute", targets={"x": 1e9})
    assert not reply.ok and reply.code == "validation"
    assert "outside the allowed range" in reply.error
    with pytest.raises(MesospimError) as info:
        client.request("move_absolute", targets={"x": 1e9})
    assert info.value.code == "validation"


def test_unknown_command_is_refused_by_the_server(client):
    # The server holds the command list; an unknown name is its refusal, not a
    # client-side crash.
    reply = client.try_request("bogus_command")
    assert not reply.ok and reply.code == "unknown_command"


def test_unknown_argument_is_a_validation_error(client):
    reply = client.try_request("ping", extra=1)
    assert not reply.ok and reply.code == "validation"


def test_injected_execution_error(server):
    with MockMesospimServer(port=0, errors={"get_state"}) as s:
        with MesospimClient(s.host, s.port, timeout=3.0) as c:
            with pytest.raises(MesospimError) as info:
                c.request("get_state")
            assert info.value.code == "execution"


def test_perform_polls_the_operation_to_completion(client, server):
    reply = client.perform("move_absolute", targets={"x": 100.0, "z": 5.0})
    assert reply.ok
    op = reply.data["operation"]
    assert op["status"] == "completed" and op["command"] == "move_absolute"
    assert reply.data["target"] == {"x": 100.0, "z": 5.0}
    names = [name for name, _ in server.calls]
    assert names.index("get_progress") > names.index("move_absolute")
    assert server.core.position()["x"] == 100.0


def test_perform_returns_a_refusal_unchanged(client, server):
    reply = client.perform("move_absolute", targets={"w": 1})
    assert not reply.ok and reply.code == "validation"
    assert server.core.moves == 0


def test_perform_reports_a_failed_operation(client, server):
    server.stall.add("move_absolute")
    server.stall.discard("move_absolute")
    # A run the server accepts but that fails on the microscope side.
    original = server.core.move_absolute

    def broken(sdict, wait_until_done=False):
        raise RuntimeError("stage did not answer")

    server.core.move_absolute = broken
    try:
        reply = client.perform("move_absolute", targets={"x": 1.0})
    finally:
        server.core.move_absolute = original
    assert not reply.ok and reply.code == "operation"
    assert "stage did not answer" in reply.error


def test_perform_times_out_without_resending(client, server):
    server.stall.add("move_absolute")
    with pytest.raises(TimeoutError, match="get_progress"):
        client.perform("move_absolute", targets={"x": 1.0}, timeout=0.2, poll_s=0.02)
    assert [n for n, _ in server.calls].count("move_absolute") == 1


def test_perform_refuses_when_someone_else_took_over(client, server):
    server.stall.add("move_absolute")
    accepted = client.try_request("move_absolute", targets={"x": 1.0})
    assert accepted.ok
    # Another client's change replaces the latest operation.
    server._session["operation"] = {"id": "op-999999", "command": "zero", "status": "completed"}
    with pytest.raises(MesospimError, match="replaced"):
        client.wait_for(accepted.data["operation"], timeout=1.0, poll_s=0.01)


def test_emergency_stop_answers_at_once(client):
    reply = client.perform("stop")
    assert reply.ok and reply.data["operation"]["status"] in ("idle", "completed")


def test_context_manager_connects_and_closes(server):
    with MesospimClient(server.host, server.port, timeout=3.0) as c:
        assert c.connected
    assert not c.connected


def test_request_before_connect_raises(server):
    c = MesospimClient(server.host, server.port, timeout=3.0)
    with pytest.raises(ConnectionError):
        c.try_request("ping")


def test_connect_to_dead_port_raises():
    # Bind then close to obtain a definitely-free port.
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(ConnectionError):
        MesospimClient("127.0.0.1", port, timeout=0.5).connect()


def test_close_is_idempotent(client):
    client.close()
    client.close()  # must not raise
