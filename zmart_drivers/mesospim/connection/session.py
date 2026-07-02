"""
Session lifecycle: connect / close.
===================================
The outer connect wrapper (mesoSPIM analog of the Leica
``connect_python_client`` and the ZEN ``connect``): resolve host/port from the
connection dict and/or the connection profile, build a :class:`MesospimClient`,
perform the ``hello`` handshake, and verify the link with a ``ping`` before
handing the client back.

Connection parameters come from the ``connection`` dict the ZMART controller
forwards (``host`` / ``port`` / ``timeout``), falling back to
``config.profiles.CONNECTION`` -- no connection tuning in notebooks or workflows.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
from typing import Any

from ..config.profiles import CONNECTION
from ..readers.readers import ping as _ping
from .client import MesospimClient

log = logging.getLogger(__name__)


def connect(
    connection: dict[str, Any] | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    timeout: float | None = None,
) -> MesospimClient:
    """Connect to a running mesoSPIM command server.

    Args:
        connection: the ZMART controller connection dict; ``host`` / ``port`` /
            ``timeout`` are read from it when present. Explicit keyword
            overrides win over the dict, which wins over the profile default.
        host, port, timeout: explicit overrides.

    Returns:
        A connected, ping-verified :class:`MesospimClient`.

    Raises:
        ConnectionError: the socket could not open or the ping failed.
        MesospimError: the ``hello`` handshake was refused or the server speaks
            an incompatible protocol version.
    """
    connection = connection or {}
    resolved_host = host or connection.get("host") or CONNECTION.host
    resolved_port = int(port or connection.get("port") or CONNECTION.port)
    resolved_timeout = float(
        timeout if timeout is not None else connection.get("timeout", CONNECTION.timeout_s)
    )

    client = MesospimClient(resolved_host, resolved_port, timeout=resolved_timeout)
    client.connect()

    if not _ping(client):
        client.close()
        raise ConnectionError(
            f"connected to {resolved_host}:{resolved_port} but the ping was not answered"
        )
    log.info("mesoSPIM session ready at %s:%d", resolved_host, resolved_port)
    return client


def close(client: MesospimClient) -> None:
    """Close the client's socket. Safe to call more than once."""
    client.close()
