"""Single-position objective-pair calibration check (driver setup due-diligence).

Image a spot with the reference objective, switch to the target objective, and
drive back to the same spot **using the adopted calibration's predicted offset**
-- the same per-slot translation the driver applies during an experiment when
the active objective differs from the origin's. Then image again and register
the pair. The leftover shift is how far the calibration is off at this spot.
A positive ``(dx_um, dy_um)`` is how far the target objective landed from the
reference spot (the negation of the apparent image shift).

The check reads the calibration at session start and refuses to run against a
slot the calibration does not cover, and it verifies at each step which
objective is actually in -- so it cannot silently bless a run where the
operator forgot to switch objectives. Runs directly against the driver, never
through the controller.

Deliberately single-position; a ring-averaged version can be added later.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

import navigator_expert as drv
from navigator_expert.algorithms import register_voting

from . import model as _model
from .common import (
    SessionPaths,
    acquire_frame_to,
    make_session_paths,
    move_xy_and_verify,
    move_zwide_and_verify,
    now_iso,
    plot_overlay,
    read_active_objective,
    read_job_geometry,
    read_selected_job_name,
    write_json_atomic,
)

KIND = "calibration_check"


@dataclass
class CalibrationCheckSession:
    session_id: str
    acquisition_name: str
    paths: SessionPaths
    job_name: str
    client: Any
    # {slot: (x, y, z) um} from the adopted calibration under test.
    translations: dict[int, tuple[float, float, float]]
    home_xy: tuple[float, float] | None = None
    home_z: float | None = None
    from_slot: int | None = None
    from_objective: str | None = None
    to_slot: int | None = None
    to_objective: str | None = None
    applied_translation_um: tuple[float, float, float] | None = None
    ref_image: np.ndarray | None = None
    ref_pixel_size_um: float | None = None
    target_image: np.ndarray | None = None
    target_pixel_size_um: float | None = None
    report: dict | None = None
    started_at_s: float | None = None
    raw_files: dict[str, str] = field(default_factory=dict)
    exported_files: dict[str, str] = field(default_factory=dict)


def start_session(
    *,
    session_id: str | None = None,
    acquisition_name: str = "validation",
    job_name: str | None = None,
    sessions_root: str | Path | None = None,
    calibration_name: str | None = None,
    parent_session: Any = None,
):
    """Connect and load the adopted calibration this check will test.

    Loading happens first so a missing or unreadable calibration surfaces
    as one clear setup error before any hardware interaction. Pass the same
    ``calibration_name`` the calibration session used, so the check tests
    the set that was just adopted.
    """
    translations = _model.load_translations(calibration_name=calibration_name)
    if len(translations) < 2:
        raise RuntimeError(
            f"the adopted calibration covers only {sorted(translations)} -- "
            "a check needs at least two calibrated objective slots. Run the "
            "calibration steps above and adopt before checking."
        )
    if parent_session is not None:
        if session_id is not None or sessions_root is not None:
            raise ValueError("parent_session replaces session_id and sessions_root")
        session_id = parent_session.session_id
        acquisition_name = parent_session.acquisition_name
        validation_dir = Path(parent_session.paths.session_dir) / "validation"
        paths = SessionPaths(
            session_root=Path(parent_session.paths.session_root),
            session_dir=validation_dir,
            configs_dir=validation_dir,
            reports_dir=validation_dir / "reports",
            data_dir=validation_dir / "data",
        )
        for directory in (paths.data_dir, paths.reports_dir):
            directory.mkdir(parents=True, exist_ok=True)
    else:
        if session_id is None:
            raise ValueError("session_id is required when parent_session is not provided")
        if sessions_root is None:
            from ...config.machine import MACHINE

            sessions_root = MACHINE.subsystem_root("calibration")
        from ...config.machine import validate_calibration_name

        acquisition_name = validate_calibration_name(acquisition_name)
        paths = make_session_paths(
            session_id,
            sessions_root,
            acquisition_name=acquisition_name,
        )
    client = drv.connect_python_client()
    limits_state = drv.connect_limits_handshake(client)
    if not limits_state.ok:
        raise RuntimeError(limits_state.error)
    if drv.get_hardware_info(client, mode="api") is None:
        raise RuntimeError("get_hardware_info returned None; LAS X unreachable")
    if job_name is None:
        job_name = read_selected_job_name(client)
        print(f"Using active Navigator Expert job: {job_name}")
    return CalibrationCheckSession(
        session_id=session_id,
        acquisition_name=acquisition_name,
        paths=paths,
        job_name=job_name,
        client=client,
        translations=translations,
        started_at_s=time.time(),
    )


def _require_calibrated_slot(session: CalibrationCheckSession, slot: int, name: str) -> None:
    if slot not in session.translations:
        raise RuntimeError(
            f"objective slot {slot} ({name}) is not covered by the adopted "
            f"calibration (calibrated slots: {sorted(session.translations)}). "
            "Calibrate this pair first, or switch to a calibrated objective."
        )


def measure_reference(session: CalibrationCheckSession) -> CalibrationCheckSession:
    """Record the spot and image it with the (focused) reference objective."""
    slot, name = read_active_objective(session.client, session.job_name)
    _require_calibrated_slot(session, slot, name)
    session.from_slot, session.from_objective = slot, name
    print(f"Reference objective: slot {slot} — {name}")

    xy = drv.get_xy(session.client, mode="api") or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    session.home_xy = (float(xy["x_um"]), float(xy["y_um"]))
    session.home_z = float(drv.read_zwide_um(session.client, session.job_name))
    session.ref_image = acquire_frame_to(session, "reference")
    session.ref_pixel_size_um = read_job_geometry(
        session.client, session.job_name, session.ref_image
    ).pixel_size_um
    return session


def measure_target_and_report(session: CalibrationCheckSession, *, show: bool = True) -> dict:
    """Return to the spot via the calibrated offset, re-image, report the leftover."""
    if session.home_xy is None or session.home_z is None or session.ref_image is None:
        raise RuntimeError("run measure_reference first")

    slot, name = read_active_objective(session.client, session.job_name)
    if slot == session.from_slot:
        raise RuntimeError(
            f"the target objective is still the reference objective: slot {slot} "
            f"({name}). Switch only the objective, keep the job selected, and rerun."
        )
    _require_calibrated_slot(session, slot, name)
    session.to_slot, session.to_objective = slot, name
    print(f"Target objective: slot {slot} — {name}")

    # The correction under test: the difference between the two slots'
    # adopted translations, exactly what the driver adds to a frame move
    # when the active objective differs from the origin's objective.
    ref_t = session.translations[session.from_slot]
    tgt_t = session.translations[slot]
    delta = (tgt_t[0] - ref_t[0], tgt_t[1] - ref_t[1], tgt_t[2] - ref_t[2])
    session.applied_translation_um = delta

    move_xy_and_verify(session.client, session.home_xy[0] + delta[0], session.home_xy[1] + delta[1])
    move_zwide_and_verify(session.client, session.job_name, session.home_z + delta[2])
    session.target_image = acquire_frame_to(session, "target")
    session.target_pixel_size_um = read_job_geometry(
        session.client, session.job_name, session.target_image
    ).pixel_size_um

    dx, dy, trusted, confidence = _pair_offset_um(
        session.ref_image, session.ref_pixel_size_um,
        session.target_image, session.target_pixel_size_um,
    )
    report = {
        "kind": KIND,
        "created_at": now_iso(),
        "from_slot": session.from_slot,
        "from_objective": session.from_objective,
        "to_slot": session.to_slot,
        "to_objective": session.to_objective,
        "position_frame_um": {"x": session.home_xy[0], "y": session.home_xy[1]},
        "applied_translation_um": list(delta),
        "dx_um": dx,
        "dy_um": dy,
        "offset_um": None if dx is None or dy is None else math.hypot(dx, dy),
        "trusted": trusted,
        "confidence": confidence,
        "duration_s": (
            None
            if session.started_at_s is None
            else round(time.time() - float(session.started_at_s), 3)
        ),
    }
    session.report = report
    write_json_atomic(session.paths.reports_dir / "calibration_check.json", report)
    # This target was acquired only after the calibrated stage move above.
    # Show it as acquired; do not digitally align it for presentation.
    residual = (
        "XY residual unavailable"
        if dx is None or dy is None
        else f"Measured XY residual: ({dx:+.2f}, {dy:+.2f}) µm"
    )
    fig = plot_overlay(
        session.ref_image,
        session.target_image,
        "Acquisition after stage correction",
        subtitle=residual,
    )
    fig.savefig(session.paths.reports_dir / "calibration_check.png", dpi=150)
    if not show:
        import matplotlib.pyplot as plt
        plt.close(fig)
    return report


def _pair_offset_um(ref, ref_ps, tgt, tgt_ps):
    """Register the pair on a shared grid; return the landing error (dx, dy, trusted, confidence).

    The two objectives image at different pixel sizes, so both are sampled onto
    the shared physical window at the finer pixel size before voting. The vote is
    negated: features shift opposite to where the stage landed.
    """
    from scipy.ndimage import map_coordinates

    fine = min(ref_ps, tgt_ps)
    h = max(8, int(round(min(ref.shape[0] * ref_ps, tgt.shape[0] * tgt_ps) / fine)))
    w = max(8, int(round(min(ref.shape[1] * ref_ps, tgt.shape[1] * tgt_ps) / fine)))

    def window(img, ps):
        scale = fine / ps
        rows = (np.arange(h) - h / 2.0) * scale + img.shape[0] / 2.0
        cols = (np.arange(w) - w / 2.0) * scale + img.shape[1] / 2.0
        gr, gc = np.meshgrid(rows, cols, indexing="ij")
        return map_coordinates(np.asarray(img, np.float32), [gr, gc], order=1, mode="nearest")

    ref_w, tgt_w = window(ref, ref_ps), window(tgt, tgt_ps)
    if float(np.std(ref_w)) < 1e-6 or float(np.std(tgt_w)) < 1e-6:
        return None, None, False, 0  # featureless: refuse to fake a perfect result

    vote = register_voting(ref_w, tgt_w, fine)

    def neg(v):
        return None if v is None or not math.isfinite(float(v)) else -float(v)

    return neg(vote.get("dx_um")), neg(vote.get("dy_um")), bool(vote.get("trusted")), vote.get("confidence")
