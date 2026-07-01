"""
Session lifecycle: connect / close.
===================================
The outer connect wrapper (ZEN analog of the Leica ``connect_python_client``):
resolve connection parameters, build TLS context + metadata, construct the
``ZenClient`` bridge, and verify connectivity with a ping before handing the
client back. Parameters come from a ``config.ini`` and/or explicit overrides,
falling back to the ``ZenApiProfile`` defaults -- no connection tuning in
notebooks or workflows.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging

from ..config.profiles import ZEN_API
from ..readers import ping as _ping
from . import zen_runtime as _rt
from .client import ZenClient

log = logging.getLogger(__name__)


def _resolve_params(config_path, host, port, cert_file, control_token):
    """Merge config.ini values (if any) with explicit overrides.

    Explicit kwargs win over the config file; the config file wins over the
    profile default path. Returns (host, port, cert_file, control_token).
    """
    resolved = {"host": None, "port": None, "cert_file": None, "control_token": None}

    source_path = config_path if config_path is not None else ZEN_API.config_path
    if source_path is not None:
        try:
            resolved.update(_rt.load_config(source_path))
        except FileNotFoundError:
            if config_path is not None:
                raise  # an explicitly named config that is missing is an error
            log.debug("no config.ini at default path %s; using explicit args", source_path)

    if host is not None:
        resolved["host"] = host
    if port is not None:
        resolved["port"] = port
    if cert_file is not None:
        resolved["cert_file"] = cert_file
    if control_token is not None:
        resolved["control_token"] = control_token

    missing = [k for k in ("host", "port", "cert_file", "control_token") if not resolved[k]]
    if missing:
        raise ValueError(
            f"Missing ZEN API connection parameter(s): {', '.join(missing)}. "
            f"Provide a config.ini or pass them explicitly to connect()."
        )
    return resolved["host"], int(resolved["port"]), resolved["cert_file"], resolved["control_token"]


def connect(
    config_path: str | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    cert_file: str | None = None,
    control_token: str | None = None,
    connect_timeout: float | None = None,
) -> ZenClient:
    """Connect to a running ZEN instance through its ZEN API gateway.

    Args:
        config_path: path to a ZEN API ``config.ini`` (``[api]`` section). If
            omitted, the ``ZenApiProfile`` default path is tried.
        host, port, cert_file, control_token: explicit overrides (win over the
            config file). All four must resolve from somewhere.
        connect_timeout: channel-build deadline (seconds); profile default if None.

    Returns:
        A connected, ping-verified ``ZenClient``.

    Raises:
        ValueError: a required connection parameter could not be resolved.
        ConnectionError: the channel built but the ping RPC failed.
    """
    if not _rt.zen_api_available():
        raise RuntimeError(
            "The 'zen_api' wheel is not installed. Install the ZEN API Python "
            "package (ships with the ZEN API toolkit) before connecting."
        )

    host, port, cert_file, control_token = _resolve_params(
        config_path, host, port, cert_file, control_token
    )
    ssl_context = _rt.build_ssl_context(cert_file)
    metadata = _rt.build_metadata(control_token)

    client = ZenClient(
        metadata=metadata,
        channel_factory=lambda: _rt.make_channel(host, port, ssl_context),
        stub_factory=_rt.default_stub_factory,
        messages=_rt.RealMessages(),
        default_call_timeout=ZEN_API.default_call_timeout_s,
        connect_timeout=connect_timeout or ZEN_API.connect_timeout_s,
    )

    if not _ping(client):
        client.close()
        raise ConnectionError(f"Connected to {host}:{port} but the ping RPC failed.")
    log.info("Connected to ZEN API gateway at %s:%d", host, port)
    return client


def close(client: ZenClient) -> None:
    """Close the client's channel and stop its event loop."""
    client.close()
