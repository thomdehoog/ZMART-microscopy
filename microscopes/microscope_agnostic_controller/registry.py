"""Driver registry: the one place that points the controller at drivers.

A driver registers an ops table - a mapping of operation name to driver callable
- under a ``connection`` dict, plus the instrument's objective and stage options.
``get_instruments()`` lists what is registered (without connecting) as
ready-to-use instrument dicts; ``resolve()`` looks one up for ``set_instrument()``.

Each instrument is described by exactly three things: a variable ``connection``
dict (driver-defined; forwarded untouched to ``connect``), an ``objectives``
list, and an ``actuators`` per-axis dict. The registry keys on the
``(vendor, microscope, api)`` identity carried inside the connection dict;
everything else in that dict is free for the driver to use.

Real vendor drivers register here. Test-only integrations, like the mock,
register themselves from the test side, so no test code is imported into
production.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from typing import Any

# Every driver ops table must provide a callable for each of these operations.
# disconnect is optional.
OPS: tuple[str, ...] = (
    "connect",
    "acquisition_options",
    "set_coordinate_system",
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

# (vendor, microscope, api) -> {"connection", "objectives", "actuators", "ops"}
REGISTRY: dict[tuple[str, ...], dict[str, Any]] = {}


def _identity(connection: dict[str, Any]) -> tuple[str, ...]:
    """Pull the (vendor, microscope, api) identity out of a connection dict."""
    missing = [key for key in IDENTITY if key not in connection]
    if missing:
        raise ValueError(f"connection missing identity keys {missing}: {connection!r}")
    return tuple(connection[key] for key in IDENTITY)


def register(
    connection: dict[str, Any],
    *,
    ops: dict[str, Any],
    objectives: list[str],
    actuators: dict[str, list[str]],
) -> None:
    """Wire a driver into the registry under its ``connection`` identity.

    ``connection`` is the variable dict forwarded to ``connect`` at session
    open. It must carry the ``vendor`` / ``microscope`` / ``api`` identity the
    registry keys on, and may carry any driver-specific extras (client name,
    api delay, host, ...). ``ops`` must cover every name in :data:`OPS`
    (``disconnect`` is optional). ``objectives`` (a list) and ``actuators`` (a
    per-axis dict of option lists, e.g. ``{"x": ["motoric"], "z": [...]}``) are
    the instrument's static choices, surfaced by :func:`get_instruments` so a
    caller can pick a reference objective and per-axis actuators before
    connecting. Raises ``ValueError`` if an op is missing or the connection
    identity is incomplete.
    """
    missing = [name for name in OPS if name not in ops]
    if missing:
        raise ValueError(f"driver {_identity(connection)} missing ops: {missing}")
    REGISTRY[_identity(connection)] = {
        "connection": dict(connection),
        "objectives": list(objectives),
        "actuators": {axis: list(opts) for axis, opts in actuators.items()},
        "ops": ops,
    }


def get_instruments() -> list[dict[str, Any]]:
    """List the available instruments, without connecting to anything.

    Each entry is the dict you pass straight to :func:`set_instrument`, with
    exactly three keys: a ``connection`` dict (forwarded to the driver at
    connect), plus the instrument's ``objectives`` (list) and ``actuators``
    (per-axis dict) so you can choose a ``reference_objective`` and per-axis
    ``reference_actuators`` from them.
    """
    return [
        {
            "connection": dict(entry["connection"]),
            "objectives": list(entry["objectives"]),
            "actuators": {axis: list(opts) for axis, opts in entry["actuators"].items()},
        }
        for _key, entry in sorted(REGISTRY.items())
    ]


def resolve(instrument: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Look up the ops table for an instrument dict and return its connection.

    ``instrument`` is one of the dicts from :func:`get_instruments`; its
    ``connection`` dict supplies both the registry identity and the params
    forwarded to ``connect`` (the caller may edit it before connecting).
    Returns ``(ops, connection)``. Raises ``ValueError`` if no driver matches
    the connection identity.
    """
    connection = instrument["connection"]
    key = _identity(connection)
    try:
        entry = REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"no driver registered for {dict(zip(IDENTITY, key, strict=True))}; known: {sorted(REGISTRY)}"
        ) from None
    return entry["ops"], connection
