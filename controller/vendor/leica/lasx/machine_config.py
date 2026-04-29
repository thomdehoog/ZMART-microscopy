"""Machine + stage configuration.

Two files describe the scope:

``config/stage.json`` — physical stage properties (limits + backlash).
Hand-edited; rarely changes.

``config/machine.json`` — calibrated optical state. Sign convention,
reference objective anchor, and per-objective parcentric (motor +
residual) and parfocal (motor + residual) offsets. Written by
``calibrate_objectives.py``. Read by protocols at acquisition time.

Updates are incremental: a calibration run that re-measures only one
target's parfocal field leaves every other field of every other
objective alone, and bumps only that objective's ``calibrated_at``.

Schema (machine.json, v5)::

    {
      "schema_version": 5,
      "last_updated": "<ts>",
      "reference_objective_slot": <int>,
      "image_to_stage": [[a, b], [c, d]],     // D4-snapped 2x2
      "objectives": {
        "<slot>": {
          "name": "...", "magnification": ..., "numerical_aperture": ...,
          "immersion": "...", "objective_number": ...,
          "is_reference": true,                // reference only
          "anchor_xy_um": [x, y],              // reference only
          "parcentric_xy": {                   // targets only
            "motor_um":    [dx, dy],
            "residual_um": [rx, ry] | null
          },
          "parfocal_z": {                      // targets only
            "motor_um":    dz   | null,
            "residual_um": rdz  | null
          },
          "calibrated_at": "<ts>"
        }
      }
    }

A field is ``null`` when its phase has not been run yet. Loaders apply
``parcentric.motor + (parcentric.residual or 0)`` and
``parfocal.motor or 0`` as the corrections.
"""

import json
import os
from datetime import datetime
from pathlib import Path

MACHINE_SCHEMA_VERSION = 5
STAGE_SCHEMA_VERSION = 1


def _config_dir():
    return Path(__file__).resolve().parent.parent / "config"


def default_machine_path():
    return _config_dir() / "machine.json"


def default_stage_path():
    return _config_dir() / "stage.json"


def default_report_dir():
    return _config_dir() / "calibration_reports"


def now_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _atomic_write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(str(tmp), str(path))


# ── Stage config ──────────────────────────────────────────────────

def load_stage_config(path=None):
    """Load stage.json. Raises FileNotFoundError if absent."""
    path = Path(path) if path is not None else default_stage_path()
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("schema_version") != STAGE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported stage.json schema_version: "
            f"{cfg.get('schema_version')!r} in {path}"
        )
    for key in ("limits_um", "backlash"):
        if key not in cfg:
            raise ValueError(f"stage.json missing required section: {key!r}")
    for axis in ("x", "y", "z_galvo", "z_wide"):
        if axis not in cfg["limits_um"]:
            raise ValueError(f"stage.json limits_um missing axis: {axis!r}")
    return cfg


# ── Machine config ────────────────────────────────────────────────

def new_machine_config():
    return {
        "schema_version": MACHINE_SCHEMA_VERSION,
        "last_updated": now_timestamp(),
        "reference_objective_slot": None,
        "image_to_stage": None,
        "objectives": {},
    }


def load_machine_config(path=None, *, create_if_missing=False):
    """Load machine.json. If absent and ``create_if_missing``, return a fresh dict."""
    path = Path(path) if path is not None else default_machine_path()
    if not path.exists():
        if create_if_missing:
            return new_machine_config()
        raise FileNotFoundError(f"machine config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("schema_version") != MACHINE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported machine.json schema_version: "
            f"{cfg.get('schema_version')!r} in {path}"
        )
    return cfg


def save_machine_config(cfg, path=None):
    """Write machine.json atomically; bump ``last_updated``."""
    cfg["last_updated"] = now_timestamp()
    path = Path(path) if path is not None else default_machine_path()
    _atomic_write_json(path, cfg)
    return path


def _objective_identity(summary):
    return {
        "name": summary["name"],
        "magnification": summary["magnification"],
        "numerical_aperture": summary["numerical_aperture"],
        "immersion": summary["immersion"],
        "objective_number": summary["objective_number"],
    }


def set_reference(cfg, slot, *, summary, anchor_xy_um):
    """Set the reference objective entry and clear ``is_reference`` on others."""
    slot = int(slot)
    cfg["reference_objective_slot"] = slot
    entry = cfg["objectives"].setdefault(str(slot), {})
    entry.update(_objective_identity(summary))
    entry["is_reference"] = True
    entry["anchor_xy_um"] = [float(anchor_xy_um[0]), float(anchor_xy_um[1])]
    entry["calibrated_at"] = now_timestamp()
    for s, e in cfg["objectives"].items():
        if int(s) != slot and e.get("is_reference"):
            e.pop("is_reference", None)


def set_sign_convention(cfg, image_to_stage_matrix):
    cfg["image_to_stage"] = [
        [float(image_to_stage_matrix[0][0]), float(image_to_stage_matrix[0][1])],
        [float(image_to_stage_matrix[1][0]), float(image_to_stage_matrix[1][1])],
    ]


def update_target(cfg, slot, *,
                  summary=None,
                  parcentric_motor_um=None, parcentric_residual_um=None,
                  parfocal_motor_um=None, parfocal_residual_um=None):
    """Incrementally update a target objective entry.

    Only fields explicitly passed (non-None) are written. The objective's
    ``calibrated_at`` is bumped if any field was actually written.
    """
    slot = int(slot)
    entry = cfg["objectives"].setdefault(str(slot), {})
    touched = False

    if summary is not None:
        entry.update(_objective_identity(summary))
        touched = True

    if parcentric_motor_um is not None or parcentric_residual_um is not None:
        parc = entry.setdefault("parcentric_xy",
                                {"motor_um": None, "residual_um": None})
        if parcentric_motor_um is not None:
            parc["motor_um"] = [float(parcentric_motor_um[0]),
                                float(parcentric_motor_um[1])]
            touched = True
        if parcentric_residual_um is not None:
            parc["residual_um"] = [float(parcentric_residual_um[0]),
                                   float(parcentric_residual_um[1])]
            touched = True

    if parfocal_motor_um is not None or parfocal_residual_um is not None:
        parf = entry.setdefault("parfocal_z",
                                {"motor_um": None, "residual_um": None})
        if parfocal_motor_um is not None:
            parf["motor_um"] = float(parfocal_motor_um)
            touched = True
        if parfocal_residual_um is not None:
            parf["residual_um"] = float(parfocal_residual_um)
            touched = True

    if touched:
        entry["calibrated_at"] = now_timestamp()


# ── Calibration report ────────────────────────────────────────────

def save_calibration_report(report, *, ts, dir_=None):
    dir_ = Path(dir_) if dir_ is not None else default_report_dir()
    path = dir_ / f"calibration_report_{ts}.json"
    _atomic_write_json(path, report)
    return path
