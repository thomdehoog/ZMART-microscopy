"""The MCP front-end: JSON-RPC handlers over a fake named-call client (pure).

No socket, no LLM -- just that each MCP request maps to the right named call and
the reply is wrapped as MCP content. The mesoSPIM allowlist is exercised
elsewhere; here the point is the MCP<->named-call bridge.
"""

from __future__ import annotations

from mesospim.connection import mcp_server
from mesospim.connection.command_api import known_commands
from mesospim.protocol import Reply


class _FakeClient:
    """Records the last named call and returns a canned Reply."""

    def __init__(self, reply):
        self.reply = reply
        self.last = None

    def try_request(self, name, **args):
        self.last = (name, args)
        return self.reply


def test_initialize_announces_the_server():
    resp = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, None)
    assert resp["result"]["serverInfo"]["name"] == "mesospim"
    assert "tools" in resp["result"]["capabilities"]


def test_tools_list_is_the_named_call_allowlist():
    resp = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, None)
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == list(known_commands())  # every tool is a mesoSPIM call, nothing else


def test_tools_call_forwards_to_one_named_call():
    client = _FakeClient(Reply(ok=True, data={"filter": "561/LP"}))
    resp = mcp_server.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "set_state", "arguments": {"settings": {"filter": "561/LP"}}}},
        client,
    )
    assert client.last == ("set_state", {"settings": {"filter": "561/LP"}})  # exact translation
    assert resp["result"]["isError"] is False
    assert '"filter": "561/LP"' in resp["result"]["content"][0]["text"]


def test_a_failed_call_is_reported_as_an_mcp_error():
    client = _FakeClient(Reply(ok=False, error="unknown command 'x'"))
    resp = mcp_server.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "x"}}, client
    )
    assert resp["result"]["isError"] is True
    assert "unknown command" in resp["result"]["content"][0]["text"]


def test_a_notification_gets_no_reply():
    # notifications have no id -> no response is written back
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, None) is None


def test_an_unknown_method_is_a_json_rpc_error():
    resp = mcp_server.handle({"jsonrpc": "2.0", "id": 5, "method": "resources/list"}, None)
    assert resp["error"]["code"] == -32601
