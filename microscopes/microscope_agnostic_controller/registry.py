"""Driver registry: the one place that points the controller at drivers.

A driver registers an ops table - a mapping of operation name to driver callable
- for a (vendor, microscope, api) triple, plus the instrument's objective and
stage options. ``get_instruments()`` lists what is registered (without connecting)
as ready-to-use instrument dicts; ``resolve()`` looks one up for
``set_instrument()``.

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

# vendor -> {(microscope, api): {"ops", "objective_options", "stage_options"}}
REGISTRY: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}


def register(
    vendor: str,
    microscope: str,
    api: str,
    *,
    ops: dict[str, Any],
    objective_options: list[str],
    stage_options: list[str],
) -> None:
    """Wire a driver into the registry under one (vendor, microscope, api).

    ``ops`` must cover every name in :data:`OPS` (``disconnect`` is optional).
    ``objective_options`` / ``stage_options`` are the instrument's static choices,
    surfaced by :func:`get_instruments` so a caller can pick a reference objective
    and stage before connecting. Raises ``ValueError`` if an op is missing.
    """
    missing = [name for name in OPS if name not in ops]
    if missing:
        raise ValueError(f"driver {vendor}/{microscope}/{api} missing ops: {missing}")
    REGISTRY.setdefault(vendor, {})[(microscope, api)] = {
        "ops": ops,
        "objective_options": list(objective_options),
        "stage_options": list(stage_options),
    }


def get_instruments() -> list[dict[str, Any]]:
    """List the available instruments, without connecting to anything.

    Each entry is the dict you pass straight to :func:`set_instrument`, and also
    carries the instrument's ``objective_options`` and ``stage_options`` so you
    can choose a ``reference_objective`` and ``reference_stage`` from them.
    """
    return [
        {
            "vendor": vendor,
            "microscope": microscope,
            "api": api,
            "objective_options": entry["objective_options"],
            "stage_options": entry["stage_options"],
        }
        for vendor, drivers in REGISTRY.items()
        for (microscope, api), entry in sorted(drivers.items())
    ]


def resolve(instrument: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Look up the ops table for an instrument dict and build the session context.

    ``instrument`` is one of the dicts from :func:`get_instruments` (only its
    ``vendor`` / ``microscope`` / ``api`` keys are used). Returns ``(ops,
    context)`` where context is ``{vendor, microscope, api}``. Raises
    ``ValueError`` if the vendor is unknown or no driver matches.
    """
    vendor, microscope, api = instrument["vendor"], instrument["microscope"], instrument["api"]
    try:
        drivers = REGISTRY[vendor]
    except KeyError:
        raise ValueError(f"unknown vendor {vendor!r}; known: {sorted(REGISTRY)}") from None
    try:
        entry = drivers[(microscope, api)]
    except KeyError:
        raise ValueError(
            f"no driver for vendor={vendor!r} microscope={microscope!r} api={api!r}; "
            f"known (microscope, api): {sorted(drivers)}"
        ) from None
    context = {"vendor": vendor, "microscope": microscope, "api": api}
    return entry["ops"], context
