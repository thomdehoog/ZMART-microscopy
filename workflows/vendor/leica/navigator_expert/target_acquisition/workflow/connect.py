"""LAS X connection bootstrap.

connect_lasx() owns the LAS X CAM API connect handshake. The notebook
calls connect_lasx() to obtain a connected client, then passes it to
preflight() for validation. preflight() does not open the client.

This module exists so the operator notebook can ask for "connect" in
two lines without leaking LasxApi naming / call shape into operator
code. The driver-side LAS X bindings stay encapsulated here.
"""
from __future__ import annotations

from typing import Any


def connect_lasx(role: str = "PythonClient") -> Any:
    """Import LasxApi, obtain the CAM API client, call Connect(role).

    Returns the connected client (a class object in the current LasxApi
    binding; see TARGET_ACQUISITION_DESIGN.md section 7 for why this is
    a class rather than an instance).

    Notebook usage:
        from workflow import connect_lasx, preflight
        client = connect_lasx()
        ctx = preflight(cfg, client)
    """
    from LasxApi import PYLICamApiConnector as _lasx
    client = _lasx.LasxApiClientPyModel
    client.Connect(role)
    return client
