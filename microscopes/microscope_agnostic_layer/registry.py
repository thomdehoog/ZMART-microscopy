"""Driver registry: the one place that points the agnostic layer at drivers.

A driver registers an ops table - a mapping of operation name to driver callable
- for a (vendor, microscope, api) triple, plus the vendor's defaults. connect()
calls resolve() to look one up.

Real vendor drivers register here (see the Leica example below, to be filled in
once its adapter exists). Test-only integrations, like the mock, register
themselves from the test side, so no test code is imported into production.

Per DESIGN.md the driver tree will be drivers/vendor/microscope/api and this
registry will mirror it.
"""

from __future__ import annotations

from typing import Any

# Every driver ops table must provide a callable for each of these operations.
# ``disconnect`` is optional.
OPS: tuple[str, ...] = (
    "connect",
    "capabilities",
    "get_xyz",
    "set_xyz",
    "acquire",
    "save",
    "get_state",
    "set_state",
    "get_procedure",
    "set_procedure",
    "get_initial_positions",
)

# vendor -> {"defaults": {...}, "drivers": {(microscope, api): ops_table}}
REGISTRY: dict[str, dict[str, Any]] = {}


def register(
    vendor: str,
    microscope: str,
    api: str,
    *,
    ops: dict[str, Any],
    defaults: dict[str, str],
) -> None:
    """Wire a driver's ops table into the registry under one triple.

    Args:
        vendor: Vendor key, e.g. ``"leica"``.
        microscope: Instrument id under that vendor.
        api: Backend/transport for that instrument.
        ops: Operation name -> driver callable. Must cover every name in
            :data:`OPS`; ``disconnect`` may also be supplied and is optional.
        defaults: Vendor-level fallbacks for ``microscope``/``api``/
            ``objective``/``stage_type`` when a caller omits them.

    Raises:
        ValueError: If ``ops`` is missing any required operation.

    Example::

        register(
            "leica", "stellaris5-01", "navigator-expert",
            ops={"connect": ..., "capabilities": ..., "get_xyz": ..., ...},
            defaults={"microscope": "stellaris5-01", "api": "navigator-expert",
                      "objective": "10x", "stage_type": "motoric"},
        )
    """
    missing = [name for name in OPS if name not in ops]
    if missing:
        raise ValueError(f"driver {vendor}/{microscope}/{api} missing ops: {missing}")
    entry = REGISTRY.setdefault(vendor, {"defaults": defaults, "drivers": {}})
    entry["defaults"] = defaults
    entry["drivers"][(microscope, api)] = ops


# Example for when the Leica adapter exists (kept commented until then):
#
#     from leica_adapter import OPS_TABLE
#     register(
#         "leica", "stellaris5-<id>", "navigator-expert",
#         ops=OPS_TABLE,
#         defaults={"microscope": "stellaris5-<id>", "api": "navigator-expert",
#                   "objective": "10x", "stage_type": "motoric"},
#     )


def resolve(
    vendor: str,
    microscope: str | None = None,
    api: str | None = None,
    *,
    objective: str | None = None,
    stage_type: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Look up the ops table and build the session context.

    ``microscope``/``api``/``objective``/``stage_type`` fall back to the
    vendor's registered defaults when omitted.

    Returns:
        A ``(ops, context)`` pair. ``ops`` is the resolved operation table;
        ``context`` is ``{vendor, microscope, api, objective, stage_type}``,
        which :func:`connect` feeds to the driver.

    Raises:
        ValueError: If the vendor is unknown, or no driver is registered for the
            resolved ``(microscope, api)``.
    """
    try:
        entry = REGISTRY[vendor]
    except KeyError:
        raise ValueError(f"unknown vendor {vendor!r}; known: {sorted(REGISTRY)}") from None

    defaults = entry["defaults"]
    microscope = microscope or defaults["microscope"]
    api = api or defaults["api"]

    try:
        ops = entry["drivers"][(microscope, api)]
    except KeyError:
        known = sorted(entry["drivers"])
        raise ValueError(
            f"no driver for vendor={vendor!r} microscope={microscope!r} api={api!r}; "
            f"known (microscope, api): {known}"
        ) from None

    context = {
        "vendor": vendor,
        "microscope": microscope,
        "api": api,
        "objective": objective or defaults["objective"],
        "stage_type": stage_type or defaults["stage_type"],
    }
    return ops, context
