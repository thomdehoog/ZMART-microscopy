"""
Opening and closing a session with NIS-Elements.
================================================
``connect(connection)`` turns a plain connection dict (``host``, ``port``,
``timeout``) into a connected :class:`~.client.NisClient`; ``close`` shuts it
down again. Kept separate from the client so the adapter and notebooks share
one place that reads those keys.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from typing import Any

from .client import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_TIMEOUT_S, NisClient


def connect(connection: dict[str, Any] | None = None) -> NisClient:
    """Connect to the bridge and return a ready client.

    Reads ``host``, ``port`` and ``timeout`` from ``connection`` (all optional;
    the defaults match ``start_bridge.mac``). Raises ``RuntimeError`` when the
    bridge is not reachable.
    """
    connection = connection or {}
    client = NisClient(
        connection.get("host", DEFAULT_HOST),
        connection.get("port", DEFAULT_PORT),
        timeout=float(connection.get("timeout", DEFAULT_TIMEOUT_S)),
    )
    client.connect()
    return client


def close(client: NisClient) -> None:
    """Close the client; safe to call more than once."""
    client.close()
