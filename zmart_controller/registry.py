"""Driver registry: the one place that points the controller at drivers.

A driver registers an ops table - a mapping of operation name to driver callable
- under a ``connection`` dict. ``get_instruments()`` lists what is registered
(without connecting) as the connection dicts themselves; ``resolve()`` looks one
up for ``set_instrument()``.

The registry keys on the ``(vendor, microscope, api)`` identity carried inside
the connection dict; everything else in that dict is free for the driver to use
(client name, api delay, host, credentials, ...) and is forwarded untouched to
``connect``.

This is where vendor driver adapters register. The first real one is the Leica
Stellaris 5 adapter (``zmart_drivers.leica.stellaris5_y42h93.navigator_expert
.zmart_adapter`` -- import it to register the instrument); the mock driver and
the example notebook register from the test/demo side, so no test code is
imported into production. See ``docs/ZMART.md`` for the integration status.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Every driver ops table must provide a callable for each of these operations.
# disconnect is optional.
OPS: tuple[str, ...] = (
    "connect",
    "get_acquisition_options",
    "set_origin",
    "get_actuators",
    "get_xyz",
    "set_xyz",
    "acquire",
    "get_state",
    "set_state",
    "get_procedures",
    "set_procedure",
    "get_context",
)

# The keys the registry indexes on. Everything else in a connection dict is
# variable and driver-defined (client name, api delay, host, credentials, ...).
IDENTITY: tuple[str, ...] = ("vendor", "microscope", "api")

# (vendor, microscope, api) -> {"connection", "ops"}
REGISTRY: dict[tuple[str, ...], dict[str, Any]] = {}


def _identity(connection: dict[str, Any]) -> tuple[str, ...]:
    """Pull the (vendor, microscope, api) identity out of a connection dict."""
    missing = [key for key in IDENTITY if key not in connection]
    if missing:
        # List only the keys, never the values -- connection dicts may carry credentials.
        raise ValueError(
            f"connection missing identity keys {missing}; has keys {sorted(connection)}"
        )
    return tuple(connection[key] for key in IDENTITY)


def register(connection: dict[str, Any], *, ops: dict[str, Any]) -> None:
    """Wire a driver into the registry under its ``connection`` identity.

    ``connection`` is the variable dict forwarded to ``connect`` at session open.
    It must carry the ``vendor`` / ``microscope`` / ``api`` identity the registry
    keys on, and may carry any driver-specific extras. ``ops`` must cover every
    name in :data:`OPS` (``disconnect`` is optional). Raises ``ValueError`` if an
    op is missing or the connection identity is incomplete. Registering the same
    identity twice logs a warning and overwrites the earlier entry (last wins).
    """
    missing = [name for name in OPS if name not in ops]
    if missing:
        raise ValueError(f"driver {_identity(connection)} missing ops: {missing}")
    key = _identity(connection)
    if key in REGISTRY:
        logger.warning("driver %s already registered; overwriting", key)
    REGISTRY[key] = {"connection": dict(connection), "ops": ops}


def get_instruments() -> list[dict[str, Any]]:
    """List the available instruments, without connecting to anything.

    Each entry is the connection dict you pass straight to :func:`set_instrument`.
    You may edit it first (e.g. drop in a credential); it is forwarded to the
    driver's ``connect`` untouched.
    """
    return [dict(entry["connection"]) for _key, entry in sorted(REGISTRY.items())]


def resolve(instrument: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Look up the ops table for a connection dict and return ``(ops, connection)``.

    ``instrument`` is one of the connection dicts from :func:`get_instruments`;
    its identity selects the driver and the whole dict is forwarded to
    ``connect``. Raises ``ValueError`` if no driver matches the identity.
    """
    key = _identity(instrument)
    try:
        entry = REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"no driver registered for {dict(zip(IDENTITY, key, strict=True))}; "
            f"known: {sorted(REGISTRY)}"
        ) from None
    return entry["ops"], instrument
