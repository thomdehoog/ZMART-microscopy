"""Driver registry: the one place that points the controller at drivers.

A driver registers an ops table - a mapping of operation name to driver callable
- under a ``connection`` dict. ``get_instruments()`` lists what is registered
(without connecting) as the connection dicts themselves; ``resolve()`` looks one
up for ``set_instrument()``.

The registry keys on the ``(vendor, microscope, api)`` identity carried inside
the connection dict; everything else in that dict is free for the driver to use
(client name, api delay, host, credentials, ...) and is forwarded untouched to
``connect``.

Return contract for ops: every op except ``connect`` and ``disconnect``
returns ``{"success": bool, "report": ...}``, with the report's content the
driver's own. A failure that makes carrying on unsafe is raised instead
(``ValueError`` for a mistake in the request, ``RuntimeError`` for a failure or
refusal on the microscope); the controller forwards return values uninspected
and propagates exceptions unchanged. Error text must be credential-safe:
connection dicts may carry credentials, so messages name keys, never values
(as :func:`_identity` does).

The registry is the plug: it checks only that a driver fits (every required
operation is present, and the identity keys are there). Everything else,
including every refusal about the microscope itself, is the driver's job.
Drivers register themselves, usually when their module is imported; the mock
microscope registers with ``zmart_controller.mock.register()``.

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
    "get_actuators",
    "get_xyz",
    "set_xyz",
    "acquire",
    "get_state",
    "set_state",
    "get_procedures",
    "run_procedure",
    "get_info",
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
