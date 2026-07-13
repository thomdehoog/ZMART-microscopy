"""Single-position objective-pair calibration check (driver setup due-diligence).

Image a spot with the reference objective, switch to the target objective, return
to the same frame position -- a normal gated move, so the driver applies the
calibrated translation -- image again, and register the pair. The leftover shift
is how far the calibration is off there. A positive ``(dx_um, dy_um)`` is how far
the target objective landed from the reference spot (the negation of the apparent
image shift). Runs directly against the driver, never through the controller.

Deliberately single-position; a ring-averaged version can be added later.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

import navigator_expert as drv
from navigator_expert.algorithms import register_voting

from .common import (
    SessionPaths,
    acquire_frame_to,
    make_session_paths,
    move_xy_and_verify,
    now_iso,
    plot_overlay,
    read_job_geometry,
    write_json_atomic,
)

KIND = "calibration_check"


@dataclass
class CalibrationCheckSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    home_xy: tuple[float, float] | None = None
    ref_image: np.ndarray | None = None
    ref_pixel_size_um: float | None = None
    target_image: np.ndarray | None = None
    target_pixel_size_um: float | None = None
    report: dict | None = None
    raw_files: dict[str, str] = field(default_factory=dict)
    exported_files: dict[str, str] = field(default_factory=dict)


def start_session(*, session_id: str, job_name: str, sessions_root: str | Path):
    paths = make_session_paths(session_id, KIND, sessions_root)
    client = drv.connect_python_client()
    limits_state = drv.connect_limits_handshake(client)
    if not limits_state.ok:
        raise RuntimeError(limits_state.error)
    if drv.get_hardware_info(client, mode="api") is None:
        raise RuntimeError("get_hardware_info returned None; LAS X unreachable")
    return CalibrationCheckSession(session_id=session_id, paths=paths, job_name=job_name, client=client)


def measure_reference(session: CalibrationCheckSession) -> CalibrationCheckSession:
    """Record the spot and image it with the (focused) reference objective."""
    xy = drv.get_xy(session.client, mode="api") or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    session.home_xy = (float(xy["x_um"]), float(xy["y_um"]))
    session.ref_image = acquire_frame_to(session, "reference")
    session.ref_pixel_size_um = read_job_geometry(
        session.client, session.job_name, session.ref_image
    ).pixel_size_um
    return session


def measure_target_and_report(session: CalibrationCheckSession, *, show: bool = True) -> dict:
    """Re-image the same spot with the switched-in target objective; report the offset."""
    if session.home_xy is None or session.ref_image is None:
        raise RuntimeError("run measure_reference first")
    move_xy_and_verify(session.client, *session.home_xy)
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
        "position_frame_um": {"x": session.home_xy[0], "y": session.home_xy[1]},
        "dx_um": dx,
        "dy_um": dy,
        "offset_um": None if dx is None or dy is None else math.hypot(dx, dy),
        "trusted": trusted,
        "confidence": confidence,
    }
    session.report = report
    write_json_atomic(session.paths.reports_dir / "calibration_check.json", report)
    fig = plot_overlay(session.ref_image, session.target_image, "calibration check",
                       shift_um=(dx, dy), pixel_size_um=session.ref_pixel_size_um)
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
