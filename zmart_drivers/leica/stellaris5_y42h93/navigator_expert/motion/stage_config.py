"""Load and publish the Leica driver's flat ``limits.json``.

The file is deliberately operator-readable: four top-level stage ranges,
``objective_slot_allowed``, and one top-level entry for each configurable
setter. An empty setter list means "reviewed; no limit is enforced". There are
no schema/source wrappers, named-constraint indirection, or nested ``functions``
object. Runtime provenance is kept outside JSON in the snapshot's hidden
``.limits-machine`` marker.

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
_AXIS_FILE_KEYS = {
    "x": "x_um",
    "y": "y_um",
    "z_galvo": "z_galvo_um",
    "z_wide": "z_wide_um",
}

# These are visible in the file even while unrestricted. A non-empty setter
# entry is rejected until that setter has a documented value contract; silently
# accepting a limit that is not enforced would be worse than refusing the file.
SETTER_LIMIT_KEYS = (
    "set_zoom",
    "set_scan_speed",
    "set_scan_resonant",
    "set_scan_mode",
    "set_sequential_mode",
    "set_scan_field_rotation",
    "set_image_format",
    "set_z_stack_definition",
    "set_z_stack_step_size",
    "set_z_stack_size",
    "set_frame_accumulation",
    "set_frame_average",
    "set_line_accumulation",
    "set_line_average",
    "set_pinhole_airy",
    "set_detector_gain",
    "set_laser_intensity",
    "set_laser_shutter",
    "set_filter_wheel_slot",
    "set_filter_wheel_spectrum",
)
_REQUIRED_FILE_KEYS = (*_AXIS_FILE_KEYS.values(), "objective_slot_allowed", *SETTER_LIMIT_KEYS)


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


def _validate_objective_slots(value: Any, *, path: Path) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} objective_slot_allowed must be a non-empty list")
    if any(isinstance(slot, bool) or not isinstance(slot, int) or slot <= 0 for slot in value):
        raise ValueError(
            f"{path} objective_slot_allowed must contain positive integers, got {value!r}"
        )
    if len(set(value)) != len(value):
        raise ValueError(f"{path} objective_slot_allowed contains duplicates: {value!r}")
    return list(value)


def validate_payload(payload: Any, *, path: Path = Path("limits.json")) -> dict[str, Any]:
    """Validate and normalize the complete flat limits document."""
    if not isinstance(payload, dict):
        raise ValueError(f"{path} limits must be an object, got {payload!r}")
    missing = sorted(set(_REQUIRED_FILE_KEYS) - set(payload))
    unknown = sorted(set(payload) - set(_REQUIRED_FILE_KEYS))
    if missing:
        raise ValueError(f"{path} missing limits entries: {missing}")
    if unknown:
        raise ValueError(f"{path} has unknown limits entries: {unknown}")

    stage = _validate_limits(
        {axis: payload[file_key] for axis, file_key in _AXIS_FILE_KEYS.items()}, path=path
    )
    objective_slots = _validate_objective_slots(payload["objective_slot_allowed"], path=path)
    setters: dict[str, list] = {}
    for name in SETTER_LIMIT_KEYS:
        entry = payload[name]
        if entry != []:
            raise ValueError(
                f"{path} {name} must currently be [] (reviewed, unrestricted); "
                "non-empty setter limits are not yet defined"
            )
        setters[name] = []

    normalized = {
        **{_AXIS_FILE_KEYS[axis]: bounds for axis, bounds in stage.items()},
        "objective_slot_allowed": objective_slots,
        **setters,
    }
    return normalized


def build_limits_payload(
    stage_um: dict[str, Any],
    *,
    objective_slots: Any = (1, 2, 3, 4, 5, 6),
) -> dict[str, Any]:
    """Build the exact flat document written by the limits notebook."""
    stage = _validate_limits(stage_um, path=Path("limits.json"))
    payload = {
        **{_AXIS_FILE_KEYS[axis]: bounds for axis, bounds in stage.items()},
        "objective_slot_allowed": list(objective_slots),
        **{name: [] for name in SETTER_LIMIT_KEYS},
    }
    return validate_payload(payload)


def load(limits_path: str | Path | None = None) -> dict[str, Any]:
    """Load the stage envelope and objective allow-list from ``limits.json``.

    Without an explicit ``limits_path``, this reads the configured file via
    ``defaults_path()`` - the active ProgramData limits snapshot. An explicit
    ``limits_path`` is the caller's deliberate choice and is read as given.

    Returns the internal shapes consumed by motion and the command gate. The
    file itself stays flat and contains no provenance metadata.
    """
    selected = Path(limits_path) if limits_path is not None else defaults_path()
    payload = validate_payload(_read_json(selected), path=selected)

    return {
        "stage_um": {axis: payload[file_key] for axis, file_key in _AXIS_FILE_KEYS.items()},
        "objective_slot_allowed": payload["objective_slot_allowed"],
        "setter_limits": {name: payload[name] for name in SETTER_LIMIT_KEYS},
    }


def adopt_limits(
    limits: dict[str, Any],
    *,
    source: str = LIMITS_SOURCE_MACHINE,
    machine: Any = None,
    moment: datetime | None = None,
    notebook_paths: Any = (),
) -> dict:
    """Validate and publish the notebook's flat ``limits.json``.

    ``limits`` should be the complete flat document shown in the notebook. For
    API compatibility, the older four-axis internal shape is also accepted and
    expanded with objective slots 1–6 plus unrestricted setter entries before
    publication. The file never stores ``source``; the snapshot path itself is
    the machine-provenance evidence used at connection time.

    Args:
        limits: Complete flat limits document, or the legacy four-axis internal
            mapping accepted only as a Python API compatibility convenience.
        source: Retained for caller compatibility and validation, but not stored
            in JSON. A published snapshot is always reported as machine-owned.
        machine: ``MachineProfile`` to publish into; ``None`` uses the global one.
        moment: Snapshot timestamp; ``None`` uses ``datetime.now(timezone.utc)``.
        notebook_paths: Executed notebook(s) to archive in the snapshot.

    Returns:
        ``{"snapshot": str, "limits_path": str}``.
    """
    from . import limits as _limits

    _validate_source(source)
    if set(limits) == set(_REQUIRED_AXES):
        payload = build_limits_payload(limits)
    else:
        payload = validate_payload(limits)
    stage_um = {axis: payload[file_key] for axis, file_key in _AXIS_FILE_KEYS.items()}
    _limits.check_envelope_within_backstop(stage_um)
    if machine is None:
        from ..config.machine import MACHINE

        machine = MACHINE
    if moment is None:
        moment = datetime.now(timezone.utc)

    snapshot = machine.publish_snapshot(
        moment,
        limits=payload,
        notebook_paths=notebook_paths,
    )
    return {
        "snapshot": str(snapshot),
        "limits_path": str(snapshot / "limits.json"),
    }
