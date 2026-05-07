"""Objective calibration: load, save, and read the calibration config.

The calibration lives at ``calibration/config/config.json`` and is
written by ``calibration/scripts/calibrate_objectives.py``. Each
calibration run also drops a snapshot ``config.json`` and a
``report.json`` into ``calibration/runs/<timestamp>/`` for full
reproducibility from disk.

Stage-physical config (limits, backlash) is unrelated and lives in
``stage_config.py``.

Schema (v9)::

    {
      "schema_version": 9,
      "last_updated": "<ts>",
      "reference_objective_slot": <int>,
      "image_to_stage": [[a, b], [c, d]],     // D4-snapped 2x2
      "objectives": {
        "<slot>": {
          "name":            "...",
          "offset_xy_um":    [dx, dy],   // firmware xy diff on switch (cumulative ref→slot)
          "shift_xy_um":     [dx, dy],   // optical-axis xy diff vs ref
          "offset_z_um":     dz_off,     // firmware z-wide diff on switch (cumulative ref→slot)
          "shift_z_um":      dz_shift    // Brenner-derived z-wide correction
        }
      }
    }

Frames and translation
    Each objective defines an "imaging frame": the (x, y, z) at which
    a given physical point is on the optical axis and in focus.
    Frames differ between objectives by:
        - XY: firmware motion on switch (``offset_xy_um``) plus the
              optical-axis correction (``shift_xy_um``).
        - Z:  firmware parfocal motion on switch (``offset_z_um``)
              plus the Brenner-derived correction (``shift_z_um``).
    ``translate_xyz_between_objectives`` maps a position from one
    objective's frame to another by adding the appropriate deltas.

Z motion model (z-galvo held at 0 throughout)
    All focus motion lives on z-wide. ``offset_z_um`` is read from the
    API (``zPosition.z-wide``) before vs after the firmware-driven
    switch; ``shift_z_um`` is the Brenner peak relative to that
    post-switch z-wide. Cookbook moves z-wide via
    ``move_z(z_mode='zwide')`` to the translator-computed target.

The reference slot is a regular entry with all corrections at 0 —
pointer-vs-data is cleanly separated: ``reference_objective_slot`` is
the only thing that distinguishes ref.

``offset_xy_um`` is the firmware-applied stage XY motion observed on
the switch (cumulative ref→target). Together with ``shift_xy_um`` it
forms the full XY frame correction, used by
``translate_xy_between_objectives``.
"""

import json
import os
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 9


# ── Paths ────────────────────────────────────────────────────────────

def _calibration_dir():
    return Path(__file__).resolve().parent.parent / "calibration"


def default_path():
    return _calibration_dir() / "config" / "config.json"


def default_runs_dir():
    return _calibration_dir() / "runs"


def make_run_dir(timestamp):
    """Create ``calibration/runs/<timestamp>/`` and return its Path."""
    path = default_runs_dir() / timestamp
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


# ── Load / save ──────────────────────────────────────────────────────

def _empty():
    return {
        "schema_version": SCHEMA_VERSION,
        "last_updated": now_timestamp(),
        "reference_objective_slot": None,
        "image_to_stage": None,
        "objectives": {},
    }


def load_calibration(path=None, *, create_if_missing=False):
    """Load config.json. If absent and ``create_if_missing``, return a fresh dict."""
    path = Path(path) if path is not None else default_path()
    if not path.exists():
        if create_if_missing:
            return _empty()
        raise FileNotFoundError(f"calibration config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported config.json schema_version: "
            f"{cfg.get('schema_version')!r} in {path}"
        )
    return cfg


def save_calibration(config, run_dir=None, *, path=None):
    """Write the live config.json atomically; bump ``last_updated``.

    If ``run_dir`` is given, also drops a snapshot in that directory so
    each run keeps the exact config it produced.
    """
    config["last_updated"] = now_timestamp()
    live = Path(path) if path is not None else default_path()
    _atomic_write_json(live, config)
    if run_dir is not None:
        _atomic_write_json(Path(run_dir) / "config.json", config)
    return live


def save_calibration_report(report, run_dir):
    """Write the run's report.json into ``run_dir``."""
    path = Path(run_dir) / "report.json"
    _atomic_write_json(path, report)
    return path


# ── Mutators ─────────────────────────────────────────────────────────

def set_image_to_stage(config, matrix):
    """Set the 2x2 image-to-stage Jacobian (D4-snapped)."""
    config["image_to_stage"] = [
        [float(matrix[0][0]), float(matrix[0][1])],
        [float(matrix[1][0]), float(matrix[1][1])],
    ]


def update_objective(config, slot, *,
                     name=None,
                     offset_xy_um=None,
                     shift_xy_um=None,
                     offset_z_um=None,
                     shift_z_um=None):
    """Incrementally update an objective entry. Only fields explicitly
    passed (non-None) are written. Used for both reference and target
    slots — the reference is just a regular entry with zero corrections.
    """
    entry = config["objectives"].setdefault(str(int(slot)), {})
    if name is not None:
        entry["name"] = name
    if offset_xy_um is not None:
        entry["offset_xy_um"] = [float(offset_xy_um[0]),
                                 float(offset_xy_um[1])]
    if shift_xy_um is not None:
        entry["shift_xy_um"] = [float(shift_xy_um[0]),
                                float(shift_xy_um[1])]
    if offset_z_um is not None:
        entry["offset_z_um"] = float(offset_z_um)
    if shift_z_um is not None:
        entry["shift_z_um"] = float(shift_z_um)


# ── Read accessors ───────────────────────────────────────────────────

def get_reference_slot(config):
    """Return the reference objective slot."""
    if "reference_objective_slot" in config:
        return int(config["reference_objective_slot"])
    raise ValueError("calibration config is missing 'reference_objective_slot'")


def get_image_to_stage(config):
    """Return the 2x2 image-to-stage matrix as floats."""
    matrix = config.get("image_to_stage")
    if matrix is None:
        raise ValueError("calibration config is missing 'image_to_stage' matrix")
    if len(matrix) != 2 or any(len(row) != 2 for row in matrix):
        raise ValueError(f"image_to_stage must be 2x2, got {matrix!r}")
    return [
        [float(matrix[0][0]), float(matrix[0][1])],
        [float(matrix[1][0]), float(matrix[1][1])],
    ]


def _entry(config, slot):
    entry = (config.get("objectives") or {}).get(str(int(slot)))
    if entry is None:
        available = sorted(int(s) for s in config.get("objectives", {}))
        raise ValueError(
            f"No calibration entry for slot {slot}. Available: {available}"
        )
    return entry


def get_offset_xy_um(config, slot):
    """Firmware-applied stage XY delta between *slot* and the reference, in um.

    Signed centricity correction that LAS X applies on objective switch.
    Cumulative from the reference. Reference slot returns ``(0.0, 0.0)``.
    Used together with ``shift_xy_um`` in ``translate_xy_between_objectives``.
    """
    entry = _entry(config, slot)
    value = entry.get("offset_xy_um")
    if value is None:
        raise ValueError(
            f"Slot {slot} has no offset_xy_um. "
            f"Re-run calibrate_objectives.py."
        )
    return float(value[0]), float(value[1])


def get_shift_xy_um(config, slot):
    """Optical-axis XY shift between *slot* and the reference, in um.

    Registration-measured. Reference slot returns ``(0.0, 0.0)``.
    Raises if no entry or no measured value.
    """
    entry = _entry(config, slot)
    value = entry.get("shift_xy_um")
    if value is None:
        raise ValueError(
            f"Slot {slot} has no shift_xy_um. "
            f"Re-run calibrate_objectives.py with --measure-shift-xy."
        )
    return float(value[0]), float(value[1])


def get_offset_z_um(config, slot):
    """Firmware-applied z-wide delta between *slot* and the reference, in um.

    Read directly from the API around the firmware-driven objective
    switch. Cumulative from the reference. Combines with
    ``shift_z_um`` to give the slot's full focal-plane offset.
    """
    entry = _entry(config, slot)
    value = entry.get("offset_z_um")
    if value is None:
        raise ValueError(
            f"Slot {slot} has no offset_z_um. "
            f"Re-run calibrate_objectives.py with --measure-shift-z."
        )
    return float(value)


def get_shift_z_um(config, slot):
    """Brenner-derived z-wide correction for *slot*, in um.

    The cookbook applies this on z-wide after the firmware has done
    its parfocal compensation. Combines with ``offset_z_um`` to give
    the slot's full focal-plane offset relative to the reference.
    Reference slot returns 0.0.
    """
    entry = _entry(config, slot)
    value = entry.get("shift_z_um")
    if value is None:
        raise ValueError(
            f"Slot {slot} has no shift_z_um. "
            f"Re-run calibrate_objectives.py with --measure-shift-z."
        )
    return float(value)


def translate_xy_between_objectives(x_um, y_um, config, *,
                                    from_slot, to_slot):
    """Translate a stage XY from *from_slot*'s frame to *to_slot*'s frame.

    Adds ``(offset_xy_um + shift_xy_um)(to) - (offset_xy_um + shift_xy_um)(from)``.
    The reference slot has both at zero, so this works in either
    direction across any pair the config covers.
    """
    ox_from, oy_from = get_offset_xy_um(config, from_slot)
    ox_to, oy_to = get_offset_xy_um(config, to_slot)
    dx_from, dy_from = get_shift_xy_um(config, from_slot)
    dx_to, dy_to = get_shift_xy_um(config, to_slot)
    return (
        float(x_um) + (ox_to - ox_from) + (dx_to - dx_from),
        float(y_um) + (oy_to - oy_from) + (dy_to - dy_from),
    )


def translate_z_between_objectives(z_um, config, *, from_slot, to_slot):
    """Translate a z-wide value from *from_slot*'s frame to *to_slot*'s.

    Adds ``(offset_z + shift_z)(to) - (offset_z + shift_z)(from)``. The
    sum captures the full per-objective focal-plane offset (firmware
    + residual). Reference slot has both at 0.
    """
    oz_from = get_offset_z_um(config, from_slot)
    oz_to = get_offset_z_um(config, to_slot)
    sz_from = get_shift_z_um(config, from_slot)
    sz_to = get_shift_z_um(config, to_slot)
    return float(z_um) + (oz_to - oz_from) + (sz_to - sz_from)


def translate_xyz_between_objectives(x_um, y_um, z_um, config, *,
                                     from_slot, to_slot):
    """Translate a full (x, y, z) from *from_slot*'s frame to *to_slot*'s.

    All three axes use ``(offset + shift)(to) - (offset + shift)(from)``.
    Returns ``(x', y', z')`` suitable as absolute commands:
    ``move_xy_stage(x', y')`` and ``move_z(z', z_mode='zwide')``.
    """
    x_t, y_t = translate_xy_between_objectives(
        x_um, y_um, config, from_slot=from_slot, to_slot=to_slot,
    )
    z_t = translate_z_between_objectives(
        z_um, config, from_slot=from_slot, to_slot=to_slot,
    )
    return x_t, y_t, z_t


def reference_to_objective_command_xy(x_ref_um, y_ref_um, config, target_slot):
    """Translate a reference-frame XY to a stage command under *target_slot*."""
    return translate_xy_between_objectives(
        x_ref_um, y_ref_um, config,
        from_slot=get_reference_slot(config),
        to_slot=target_slot,
    )


def pixel_to_stage_xy_um(px, py, stage_xy_um, pixel_size_um, image_size, config):
    """Convert image pixel coordinates to absolute stage XY in um."""
    matrix = get_image_to_stage(config)
    centre = image_size / 2.0
    dx_image_um = (px - centre) * pixel_size_um
    dy_image_um = (py - centre) * pixel_size_um

    stage_dx = matrix[0][0] * dx_image_um + matrix[0][1] * dy_image_um
    stage_dy = matrix[1][0] * dx_image_um + matrix[1][1] * dy_image_um

    return float(stage_xy_um[0]) + stage_dx, float(stage_xy_um[1]) + stage_dy
