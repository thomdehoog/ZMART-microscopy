"""
MCP front-end for the mesoSPIM named-call server (LLM access).
==============================================================
The mesoSPIM Remote Scripting server accepts named JSON calls (see
:mod:`mesospim.connection.command_api`). This module re-exposes that exact
vocabulary as **MCP tools**, so an LLM can drive the microscope through the same
validate -> translate -> dispatch path a script uses. It is a thin bridge: MCP
tool call in, one named call to mesoSPIM, JSON result out. Nothing new is
executable -- the tools ARE ``command_api.known_commands()``, and the mesoSPIM
server still rejects anything outside its allowlist.

Run it as the LLM's MCP server (stdio transport)::

    python -m mesospim.connection.mcp_server --host 127.0.0.1 --port 42000 --token <token>

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
import sys

from .command_api import known_commands

MCP_PROTOCOL_VERSION = "2024-11-05"

# One-line hint per call so the LLM knows the argument shape. The mesoSPIM server
# is the real gate; these are guidance. Any call not listed still appears (name only).
_HINTS = {
    "move_absolute": "move axes to absolute targets. args: {targets: {x,y,z,f,theta -> um/deg}}",
    "move_relative": "move axes by relative offsets. args: {deltas: {axis -> um/deg}}",
    "zero": "define current position as zero. args: {axes: [x,y,z,f,theta]} (omit = all)",
    "stop": "halt all stage motion. args: {}",
    "set_state": "change instrument settings. args: {settings: {filter,zoom,laser,intensity,shutterconfig,etl_*,...}}",
    "get_state": "read full state (position + settings). args: {}",
    "get_position": "read stage position. args: {}",
    "get_config": "read config (lasers, filters, zooms, shutter configs, camera). args: {}",
    "get_progress": "read acquisition progress. args: {}",
    "ping": "liveness check. args: {}",
}


def _tools() -> list[dict]:
    """The MCP tool list -- one tool per mesoSPIM named call."""
    return [
        {"name": name, "description": _HINTS.get(name, f"mesoSPIM {name} call"),
         "inputSchema": {"type": "object"}}
        for name in known_commands()
    ]


def handle(request: dict, client) -> dict | None:
    """Turn one JSON-RPC request into its response (or None for a notification).

    Pure: ``client`` only needs ``try_request(name, **args) -> Reply``, so this
    tests without a socket. Unknown methods get a JSON-RPC "method not found".
    """
    method, rid = request.get("method"), request.get("id")
    if rid is None:  # a notification (e.g. notifications/initialized) -- no reply
        return None
    if method == "initialize":
        result = {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "mesospim", "version": 1}}
    elif method == "tools/list":
        result = {"tools": _tools()}
    elif method == "tools/call":
        params = request.get("params") or {}
        reply = client.try_request(params.get("name"), **(params.get("arguments") or {}))
        text = json.dumps(reply.data if reply.ok else {"error": reply.error})
        result = {"content": [{"type": "text", "text": text}], "isError": not reply.ok}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def serve(client, stdin=None, stdout=None) -> None:
    """Read newline-delimited JSON-RPC from stdin, write replies to stdout (MCP stdio)."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        response = handle(json.loads(line), client)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


def main(argv=None) -> None:
    import argparse

    from .session import connect

    ap = argparse.ArgumentParser(description="MCP server bridging an LLM to a mesoSPIM named-call server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=42000)
    ap.add_argument("--token", default=None)
    args = ap.parse_args(argv)

    client = connect(host=args.host, port=args.port, token=args.token)
    try:
        serve(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()
