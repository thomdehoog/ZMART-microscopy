"""Load the stage envelope from the single limits file.

The physical stage envelope and the function-keyed gate policy live in ONE
machine-local ``limits.json`` (decision §7b) that resolves through the machine
profile - the newest snapshot under ``C:\\ProgramData\\zmart-microscopy\\...``
(see :mod:`navigator_expert.config.machine`). The file is the function-keyed
format: ``constraints`` (the ``stage.*`` envelope) + ``functions`` (the gate
policy, read by ``commands/gate``). This module reads the envelope from
``constraints.stage.*``; the commands gate reads ``constraints`` +
``functions`` from the same file. There is no separate ``function_limits.json``
and no ``backlash`` block - backlash is a plain motion utility with baked-in
default params (:mod:`navigator_expert.motion.movement`), not config
(decision §2b).

``adopt_limits`` publishes a new snapshot holding this ``limits.json`` from the
``set_stage_limits`` notebook. On a fresh install, the bundled defaults are
copied into ProgramData first, so runtime reads still point at machine-local
files and CI can run without executing the notebooks.

The per-run *working* envelope (boundary-marker / scan-field limits) is not
machine state - it belongs to the acquisition workflow, above the vendor
driver - so it is not resolved here.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LIMITS_SCHEMA_VERSION = 1
LIMITS_SOURCE_DEFAULTS = "defaults"
LIMITS_SOURCE_MACHINE = "machine"
LIMITS_SOURCE_BOUNDARY_MARKERS = "boundary_markers"
LIMITS_SOURCE_CFG_FALLBACK = "cfg_fallback"
LIMITS_SOURCE_SCAN_FIELD = "scan_field"
LIMITS_SOURCE_MIGRATION = "migration"
LIMITS_SOURCES = frozenset(
    {
        LIMITS_SOURCE_DEFAULTS,
        LIMITS_SOURCE_MACHINE,
        LIMITS_SOURCE_BOUNDARY_MARKERS,
        LIMITS_SOURCE_CFG_FALLBACK,
        LIMITS_SOURCE_SCAN_FIELD,
        LIMITS_SOURCE_MIGRATION,
    }
)

_REQUIRED_AXES = ("x", "y", "z_galvo", "z_wide")
_STAGE_CONSTRAINT_PREFIX = "stage."


def _driver_root() -> Path:
    return Path(__file__).resolve().parents[1]


def defaults_path() -> Path:
    """Path to the active physical stage envelope in ProgramData.

    Resolves through the machine profile to the newest ProgramData snapshot's
    ``limits.json``. If ProgramData is empty, the repo defaults are seeded into
    a local snapshot before this returns.
    """
    from ..config.machine import LIMITS_FILENAME, MACHINE

    return MACHINE.require_machine_local(LIMITS_FILENAME, "the physical stage envelope")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _validate_limits(limits: dict[str, Any], *, path: Path) -> dict[str, list[float]]:
    if not isinstance(limits, dict):
        raise ValueError(f"{path} stage limits must be an object, got {limits!r}")
    unknown = sorted(set(limits) - set(_REQUIRED_AXES))
    if unknown:
        # An axis this machine does not have is a wrong-machine (or corrupt)
        # file; ignoring it would silently accept an envelope we cannot check.
        raise ValueError(
            f"{path} stage limits carry unknown axes {unknown}; expected exactly "
            f"{list(_REQUIRED_AXES)}"
        )
    out: dict[str, list[float]] = {}
    for axis in _REQUIRED_AXES:
        if axis not in limits:
            raise ValueError(f"{path} stage limits missing axis: {axis!r}")
        values = limits[axis]
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError(f"{path} stage limit {axis!r} must be [min, max], got {values!r}")
        try:
            low, high = float(values[0]), float(values[1])
        except (TypeError, ValueError):
            raise ValueError(
                f"{path} stage limit {axis!r} must be two numbers, got {values!r}"
            ) from None
        if not (math.isfinite(low) and math.isfinite(high)):
            # json.loads accepts NaN/Infinity literals, and NaN compares False
            # against every bound - reject non-finite numbers outright.
            raise ValueError(f"{path} stage limit {axis!r} is not finite: {values!r}")
        if low > high:
            raise ValueError(f"{path} stage limit {axis!r} has min > max: {values!r}")
        out[axis] = [low, high]
    return out


def _validate_source(source: Any, *, path: Path | None = None) -> str:
    if not isinstance(source, str) or not source:
        where = f"{path} " if path is not None else ""
        raise ValueError(f"{where}source must be a non-empty string")
    if source not in LIMITS_SOURCES:
        where = f"{path} " if path is not None else ""
        allowed = ", ".join(sorted(LIMITS_SOURCES))
        raise ValueError(f"{where}source {source!r} is not one of: {allowed}")
    return source


def _stage_um_from_constraints(constraints: Any, *, path: Path) -> dict[str, list[float]]:
    """Derive the flat ``stage_um`` envelope from the file's ``constraints``.

    The merged limits.json states the envelope once, under ``constraints`` by
    name (``stage.x`` = ``{"min": .., "max": ..}``). This lifts the ``stage.*``
    constraints into the ``{"x": [min, max], ...}`` shape the motion check
    consumes; non-``stage.`` constraints (if any) are not the motion envelope
    and are ignored here (the commands gate consumes the full constraint set).
    Downstream :func:`_validate_limits` enforces exactly this machine's axes,
    finite numbers, and min <= max.
    """
    if not isinstance(constraints, dict):
        raise ValueError(f"{path} constraints must be an object, got {constraints!r}")
    stage: dict[str, list[float]] = {}
    for name, bound in constraints.items():
        if not name.startswith(_STAGE_CONSTRAINT_PREFIX):
            continue
        axis = name[len(_STAGE_CONSTRAINT_PREFIX) :]
        if not isinstance(bound, dict) or "min" not in bound or "max" not in bound:
            raise ValueError(
                f"{path} constraint {name!r} must be an object with 'min' and 'max', got {bound!r}"
            )
        stage[axis] = [bound["min"], bound["max"]]
    return stage


def _read_payload(path: Path) -> dict[str, Any]:
    """Read + schema/source-validate the merged limits.json once."""
    payload = _read_json(path)
    if payload.get("schema_version") != LIMITS_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported limits.json schema_version {payload.get('schema_version')!r} in {path}"
        )
    _validate_source(payload.get("source"), path=path)
    return payload


def _read_limits(path: Path) -> dict[str, list[float]]:
    """The validated ``stage_um`` envelope from the merged limits.json."""
    payload = _read_payload(path)
    if "constraints" not in payload:
        raise ValueError(f"{path} missing constraints section")
    stage = _stage_um_from_constraints(payload["constraints"], path=path)
    return _validate_limits(stage, path=path)


def load(limits_path: str | Path | None = None) -> dict[str, Any]:
    """Load the stage envelope from the single limits.json.

    Without an explicit ``limits_path``, this reads the configured file via
    ``defaults_path()`` - the active ProgramData limits snapshot. An explicit
    ``limits_path`` is the caller's deliberate choice and is read as given.

    Returns ``{"stage_um": {axis: [min, max]}}``; the envelope is derived from
    ``constraints.stage.*`` (decision §7b). Backlash is a motion utility with
    baked-in defaults (decision §2b), not config, so it is not read here. Any
    stray ``backlash`` key in an older file is ignored.
    """
    selected = Path(limits_path) if limits_path is not None else defaults_path()
    payload = _read_payload(selected)

    if "constraints" not in payload:
        raise ValueError(f"{selected} missing constraints section")
    stage = _validate_limits(
        _stage_um_from_constraints(payload["constraints"], path=selected), path=selected
    )

    return {
        "stage_um": stage,
    }


def adopt_limits(
    stage_um: dict[str, Any],
    *,
    source: str = LIMITS_SOURCE_DEFAULTS,
    machine: Any = None,
    moment: datetime | None = None,
    notebook_paths: Any = (),
) -> dict:
    """Publish a new machine snapshot holding the single ``limits.json`` (§7b).

    Validates *stage_um* against the limits schema (finite numbers, min <= max,
    exactly the machine's axes) AND against the hardcoded physical backstop
    (:data:`navigator_expert.motion.limits.STAGE_BACKSTOP_UM`), then publishes a
    copy-forward snapshot whose single ``limits.json`` is the function-keyed
    format: ``constraints`` (the adopted envelope, stated by name) and the
    standard ``functions`` gate map. No ``backlash`` block: backlash is a plain
    motion utility with baked-in defaults (decision §2b), not config. Calibration
    and orientation are carried forward from ProgramData, or seeded from repo
    defaults on a fresh machine. This is the writer for the ``set_stage_limits``
    notebook.

    Args:
        stage_um: ``{"x": [min, max], "y": ..., "z_galvo": ..., "z_wide": ...}``.
        source: Provenance tag (defaults to ``"defaults"``, the configured
            physical baseline).
        machine: ``MachineProfile`` to publish into; ``None`` uses the global one.
        moment: Snapshot timestamp; ``None`` uses ``datetime.now(timezone.utc)``.
        notebook_paths: Executed notebook(s) to archive in the snapshot.

    Returns:
        ``{"snapshot": str, "limits_path": str}``.
    """
    from ..commands import gate as _gate
    from . import limits as _limits

    validated = _validate_limits(stage_um, path=Path("limits.json"))
    _limits.check_envelope_within_backstop(validated)
    if machine is None:
        from ..config.machine import MACHINE

        machine = MACHINE
    if moment is None:
        moment = datetime.now(timezone.utc)

    # The single limits.json: constraints + functions (the gate map).
    payload = _gate.build_function_limits_payload(validated, source=_validate_source(source))

    snapshot = machine.publish_snapshot(
        moment,
        limits=payload,
        notebook_paths=notebook_paths,
    )
    return {
        "snapshot": str(snapshot),
        "limits_path": str(snapshot / "limits.json"),
    }
