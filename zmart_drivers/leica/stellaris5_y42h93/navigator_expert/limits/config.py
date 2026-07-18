"""Load, validate, and publish the Leica driver's flat ``limits.json``.

The file is deliberately operator-readable: four top-level stage ranges,
``objective_slot``, and one top-level entry for each configurable setter.
Every constraint explicitly says ``range`` or ``allowed``; an empty list means
"reviewed; no limit is enforced". ``objective_slot`` defaults to ``[]``
(unrestricted): which slots exist is hardware knowledge the wrapper checks
live against the turret, so a written allow-list is only for deliberately
fencing automation to specific slots (slots count from 0). There are
no schema/source wrappers, named-constraint indirection, or nested ``functions``
object. Runtime provenance is kept outside JSON in the snapshot's hidden
``.limits-machine`` marker.

``adopt_limits`` publishes a new snapshot holding this ``limits.json`` from the
``set_limits`` notebook. On a fresh install, the bundled defaults are
copied into ProgramData first, so runtime reads still point at machine-local
files and CI can run without executing the notebooks.

The per-run *working* envelope (boundary-marker / scan-field limits) is not
machine state - it belongs to the acquisition workflow, above the vendor
driver - so it is not resolved here.
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

_REQUIRED_AXES = ("x", "y", "z_galvo", "z_wide")
_AXIS_FILE_KEYS = {
    "x": "x_um",
    "y": "y_um",
    "z_galvo": "z_galvo_um",
    "z_wide": "z_wide_um",
}

# These are visible in the file even while unrestricted. Each entry is either
# ``[]`` or one typed constraint, and the command wrapper with the same name
# enforces a typed constraint immediately before its native CAM call.
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
_REQUIRED_FILE_KEYS = (*_AXIS_FILE_KEYS.values(), "objective_slot", *SETTER_LIMIT_KEYS)


def _driver_root() -> Path:
    return Path(__file__).resolve().parents[1]


def defaults_path() -> Path:
    """Path to the active machine limits file in ProgramData.

    Resolves through the machine profile to the newest
    ``limits/<datetime>/limits.json``. If the limits tree is empty, the repo
    default is seeded into a local snapshot before this returns.
    """
    from ..config.machine import LIMITS_FILENAME, MACHINE

    return MACHINE.require_machine_local(LIMITS_FILENAME, "the physical stage envelope")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_range(values: Any, *, path: Path, name: str) -> list[float]:
    """Validate one strict numeric ``[min, max]`` and return floats."""
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError(f"{path} {name} must be [min, max], got {values!r}")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise ValueError(f"{path} {name} must contain numbers, got {values!r}")
    low, high = float(values[0]), float(values[1])
    if not (math.isfinite(low) and math.isfinite(high)):
        raise ValueError(f"{path} {name} is not finite: {values!r}")
    if low > high:
        raise ValueError(f"{path} {name} has min > max: {values!r}")
    return [low, high]


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
        out[axis] = _normalize_range(limits[axis], path=path, name=f"stage limit {axis!r}")
    return out


def _normalize_typed_limit(
    name: str,
    entry: Any,
    *,
    path: Path,
    required_kind: str | None = None,
) -> dict[str, list]:
    if not isinstance(entry, dict) or len(entry) != 1:
        raise ValueError(
            f"{path} {name} must be {{'range': [min, max]}} or {{'allowed': [...]}}, got {entry!r}"
        )
    kind, values = next(iter(entry.items()))
    if kind not in {"range", "allowed"}:
        raise ValueError(f"{path} {name} has unknown limit type {kind!r}")
    if required_kind is not None and kind != required_kind:
        raise ValueError(f"{path} {name} must use {required_kind!r}, got {kind!r}")
    if not isinstance(values, list):
        raise ValueError(f"{path} {name}.{kind} must be a list, got {values!r}")
    if kind == "range":
        return {"range": _normalize_range(values, path=path, name=f"{name}.range")}
    if not values:
        raise ValueError(
            f"{path} {name}.allowed must not be empty; use [] for unrestricted setters"
        )
    if any(type(value) not in (bool, int, float, str) for value in values):
        raise ValueError(
            f"{path} {name}.allowed values must be JSON booleans, numbers, or strings, "
            f"got {values!r}"
        )
    if any(isinstance(value, float) and not math.isfinite(value) for value in values):
        raise ValueError(f"{path} {name}.allowed contains a non-finite number: {values!r}")
    if len({json.dumps(value, sort_keys=True) for value in values}) != len(values):
        raise ValueError(f"{path} {name}.allowed contains duplicates: {values!r}")
    return {"allowed": list(values)}


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

    axes = {
        file_key: _normalize_typed_limit(
            file_key, payload[file_key], path=path, required_kind="range"
        )
        for file_key in _AXIS_FILE_KEYS.values()
    }
    objective_entry = payload["objective_slot"]
    if objective_entry == []:
        objective: Any = []
    else:
        objective = _normalize_typed_limit(
            "objective_slot", objective_entry, path=path, required_kind="allowed"
        )
        slots = objective["allowed"]
        if any(isinstance(slot, bool) or not isinstance(slot, int) or slot < 0 for slot in slots):
            raise ValueError(
                f"{path} objective_slot.allowed must contain non-negative integers "
                f"(turret slots count from 0), got {slots!r}"
            )
    setters: dict[str, Any] = {}
    for name in SETTER_LIMIT_KEYS:
        entry = payload[name]
        setters[name] = [] if entry == [] else _normalize_typed_limit(name, entry, path=path)

    normalized = {
        **axes,
        "objective_slot": objective,
        **setters,
    }
    return normalized


def build_limits_payload(stage_um: dict[str, Any]) -> dict[str, Any]:
    """Build the exact flat document written by the limits notebook."""
    stage = _validate_limits(stage_um, path=Path("limits.json"))
    payload = {
        **{_AXIS_FILE_KEYS[axis]: {"range": bounds} for axis, bounds in stage.items()},
        "objective_slot": [],
        **{name: [] for name in SETTER_LIMIT_KEYS},
    }
    return validate_payload(payload)


def load(limits_path: str | Path | None = None) -> dict[str, Any]:
    """Load the stage envelope and setter limits from ``limits.json``.

    Without an explicit ``limits_path``, this reads the configured file via
    ``defaults_path()`` - the active ProgramData limits snapshot. An explicit
    ``limits_path`` is the caller's deliberate choice and is read as given.

    Returns the internal shapes consumed by motion and the command gate. The
    file itself stays flat and contains no provenance metadata.
    """
    selected = Path(limits_path) if limits_path is not None else defaults_path()
    payload = validate_payload(_read_json(selected), path=selected)

    return {
        "policy": payload,
        "stage_um": {
            axis: payload[file_key]["range"] for axis, file_key in _AXIS_FILE_KEYS.items()
        },
    }


def adopt_limits(
    limits: dict[str, Any],
    *,
    machine: Any = None,
    moment: datetime | None = None,
    notebook_paths: Any = (),
    template_paths: Any = (),
) -> dict:
    """Validate and publish the notebook's flat ``limits.json``.

    ``limits`` should be the complete flat document shown in the notebook. For
    API compatibility, the older four-axis internal shape is also accepted and
    expanded with unrestricted setter entries before
    publication. The file never stores ``source``; the snapshot path itself is
    the machine-provenance evidence used at connection time.

    Args:
        limits: Complete flat limits document, or the legacy four-axis internal
            mapping accepted only as a Python API compatibility convenience.
        machine: ``MachineProfile`` to publish into; ``None`` uses the global one.
        moment: Snapshot timestamp; ``None`` uses ``datetime.now(timezone.utc)``.
        notebook_paths: Saved notebook(s) to archive in the snapshot. Each
            archived copy receives the snapshot datetime in its filename.
        template_paths: The saved LAS X ``.xml``, ``.rgn``, and ``.lrp``
            experiment files to archive with the notebook.

    Returns:
        Snapshot path, limits path, timestamped notebook paths, and template
        paths.
    """
    from ..motion import limits as _motion_limits

    if set(limits) == set(_REQUIRED_AXES):
        payload = build_limits_payload(limits)
    else:
        payload = validate_payload(limits)
    stage_um = {axis: payload[file_key]["range"] for axis, file_key in _AXIS_FILE_KEYS.items()}
    _motion_limits.check_envelope_within_backstop(stage_um)
    if machine is None:
        from ..config.machine import MACHINE

        machine = MACHINE
    if moment is None:
        moment = datetime.now(timezone.utc)

    notebook_paths = tuple(Path(path) for path in notebook_paths)
    template_paths = tuple(Path(path) for path in template_paths)
    if template_paths:
        missing = [str(path) for path in template_paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"template archive files do not exist: {missing}")
        suffixes = [path.suffix.lower() for path in template_paths]
        if len(template_paths) != 3 or set(suffixes) != {".xml", ".rgn", ".lrp"}:
            raise ValueError(
                "template_paths must contain exactly one .xml, .rgn, and .lrp file"
            )
        if len({path.stem for path in template_paths}) != 1:
            raise ValueError("template archive files must share one experiment filename stem")

    archived_notebook_relpaths: list[Path] = []
    archived_template_relpaths: list[Path] = []
    if notebook_paths or template_paths:
        from ..config.machine import format_snapshot_name

        stamp = format_snapshot_name(moment)
        with TemporaryDirectory(prefix="zmart_limits_data_") as temp_dir:
            data_dir = Path(temp_dir) / "data"
            for notebook in notebook_paths:
                notebook_dir = data_dir / "notebook"
                notebook_dir.mkdir(parents=True, exist_ok=True)
                destination = notebook_dir / f"{notebook.stem}_{stamp}{notebook.suffix}"
                if destination.exists():
                    raise FileExistsError(
                        f"duplicate timestamped notebook archive name: {destination.name}"
                    )
                shutil.copy2(notebook, destination)
                archived_notebook_relpaths.append(destination.relative_to(Path(temp_dir)))
            for template in template_paths:
                template_dir = data_dir / "template"
                template_dir.mkdir(parents=True, exist_ok=True)
                destination = template_dir / template.name
                shutil.copy2(template, destination)
                archived_template_relpaths.append(destination.relative_to(Path(temp_dir)))
            snapshot = machine.publish_snapshot(
                moment,
                limits=payload,
                archive_paths=[data_dir],
            )
    else:
        snapshot = machine.publish_snapshot(moment, limits=payload)

    return {
        "snapshot": str(snapshot),
        "limits_path": str(snapshot / "limits.json"),
        "notebook_paths": [
            str(snapshot / relative) for relative in archived_notebook_relpaths
        ],
        "template_paths": [
            str(snapshot / relative) for relative in archived_template_relpaths
        ],
    }
