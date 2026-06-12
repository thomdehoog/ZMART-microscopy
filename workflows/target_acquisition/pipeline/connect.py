"""LAS X connection bootstrap.

connect_lasx() owns the LAS X CAM API connect handshake. The notebook
calls connect_lasx() to obtain a connected client, then passes it to
preflight() for validation. preflight() does not open the client.

This module exists so the operator notebook can ask for "connect" in
two lines without leaking LAS X runtime loading details into operator code.
The driver-side LAS X bindings stay encapsulated here.
"""

from __future__ import annotations

from typing import Any


def connect_lasx(role: str = "PythonClient") -> Any:
    """Connect to LAS X through the shared driver session helper.

    Returns the connected client.

    Notebook usage:
        from pipeline import connect_lasx, preflight
        client = connect_lasx()
        ctx = preflight(cfg, client)
    """
    from navigator_expert.runtime.session import connect_python_client

    return connect_python_client(client_name=role)
