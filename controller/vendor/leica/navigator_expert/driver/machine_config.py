"""Calibration configuration: stage + scope state.

Two files describe the scope, both under
``calibration/config/``:

``stage.json`` — physical stage properties (limits + backlash).
Hand-edited; rarely changes.

``config.json`` — calibrated optical state. Sign convention,
reference objective anchor, and per-objective shift / offset
values. Written by ``calibrate_objectives.py``. Read by acquisition
scripts at runtime.

Each calibration run also drops a snapshot ``config.json`` plus a
``report.json`` into ``calibration/runs/<timestamp>/`` so every run
is fully reproducible from disk.

Updates are incremental: a calibration run that re-measures only one
target's parfocal field leaves every other field of every other
objective alone, and bumps only that objective's ``calibrated_at``.

Schema (config.json, v6)::

    {
      "schema_version": 6,
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
            "shift_um":  [dx, dy] | null,      // c1 - c2 from registration
                                               // — what consumers use
            "offset_um": [dx, dy] | null       // get_xy delta on switch
                                               // — diagnostic only
          },
          "parfocal_z": {                      // targets only
            "shift_um":  dz | null,            // focus diff from Brenner
                                               // — what consumers use
            "offset_um": dz | null             // get_z delta if firmware
                                               // moves Z on switch
                                               // — diagnostic only
          },
          "calibrated_at": "<ts>"
        }
      }
    }

A field is ``null`` when its phase has not been run yet. Consumers
read ``shift_um`` directly. ``offset_um`` is recorded so operators
can track firmware behaviour over time, but is not part of the
correction the cookbook applies.

Schema v5 (the old motor + residual form) is gone. There is no
migration path — the v5 ``residual_um`` was a derived value that
folded the firmware shift back in, and reading it without the
matching ``motor_um`` produced wrong corrections. Recalibrate.
"""

import json
import os
from datetime import datetime
from pathlib import Path

MACHINE_SCHEMA_VERSION = 6
STAGE_SCHEMA_VERSION = 1


def _calibration_dir():
    return Path(__file__).resolve().parent.parent / "calibration"


def _config_dir():
    return _calibration_dir() / "config"


def default_machine_path():
    return _config_dir() / "config.json"


def default_stage_path():
    return _config_dir() / "stage.json"


def default_runs_dir():
    return _calibration_dir() / "runs"


def make_run_dir(ts):
    """Create ``calibration/runs/<ts>/`` and return its Path."""
    path = default_runs_dir() / ts
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    """Load config.json. If absent and ``create_if_missing``, return a fresh dict."""
    path = Path(path) if path is not None else default_machine_path()
    if not path.exists():
        if create_if_missing:
            return new_machine_config()
        raise FileNotFoundError(f"calibration config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("schema_version") != MACHINE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported config.json schema_version: "
            f"{cfg.get('schema_version')!r} in {path}"
        )
    return cfg


def save_machine_config(cfg, run_dir=None, *, path=None):
    """Write the live config.json atomically; bump ``last_updated``.

    If ``run_dir`` is provided, also drops a snapshot copy in that dir
    so each run keeps the exact config it produced.
    """
    cfg["last_updated"] = now_timestamp()
    live = Path(path) if path is not None else default_machine_path()
    _atomic_write_json(live, cfg)
    if run_dir is not None:
        _atomic_write_json(Path(run_dir) / "config.json", cfg)
    return live


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
                  parcentric_shift_um=None, parcentric_offset_um=None,
                  parfocal_shift_um=None, parfocal_offset_um=None):
    """Incrementally update a target objective entry.

    Only fields explicitly passed (non-None) are written. The objective's
    ``calibrated_at`` is bumped if any field was actually written.

    ``shift_um`` is the value consumers use to correct between
    objectives — the optical-center difference measured by registration
    with the stage parked at the same XY both times.

    ``offset_um`` is the firmware-induced stage motion on objective
    switch (``get_xy`` delta), recorded for diagnostics only.
    """
    slot = int(slot)
    entry = cfg["objectives"].setdefault(str(slot), {})
    touched = False

    if summary is not None:
        entry.update(_objective_identity(summary))
        touched = True

    if parcentric_shift_um is not None or parcentric_offset_um is not None:
        parc = entry.setdefault("parcentric_xy",
                                {"shift_um": None, "offset_um": None})
        if parcentric_shift_um is not None:
            parc["shift_um"] = [float(parcentric_shift_um[0]),
                                float(parcentric_shift_um[1])]
            touched = True
        if parcentric_offset_um is not None:
            parc["offset_um"] = [float(parcentric_offset_um[0]),
                                 float(parcentric_offset_um[1])]
            touched = True

    if parfocal_shift_um is not None or parfocal_offset_um is not None:
        parf = entry.setdefault("parfocal_z",
                                {"shift_um": None, "offset_um": None})
        if parfocal_shift_um is not None:
            parf["shift_um"] = float(parfocal_shift_um)
            touched = True
        if parfocal_offset_um is not None:
            parf["offset_um"] = float(parfocal_offset_um)
            touched = True

    if touched:
        entry["calibrated_at"] = now_timestamp()


# ── Calibration report ────────────────────────────────────────────

def save_calibration_report(report, run_dir):
    """Write the run's report.json into ``run_dir``."""
    path = Path(run_dir) / "report.json"
    _atomic_write_json(path, report)
    return path
