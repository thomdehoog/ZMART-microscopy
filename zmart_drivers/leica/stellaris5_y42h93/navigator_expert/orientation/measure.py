"""Measure how the camera is turned relative to the stage (the ``set_orientation`` step).

The idea is simple: take three pictures -- one at the start, one after nudging
the stage a little in X, and one after nudging it in Y -- and watch which way the
picture shifts each time. If moving the stage right makes the picture shift down,
the camera is turned a quarter-turn, and so on. From those two shifts we work out
the turn and record it.

Under the hood this registers each pair of pictures to get the shift, builds a
small 2x2 matrix from the two shifts, and matches it to the nearest whole
quarter-turn (0, 90, 180, or 270 degrees). The result is written to a staging
``orientation.json`` that :func:`adopt_orientation` copies into
``orientation/current.json``, which is the value the driver reads at save time.

The three pictures are taken **without** applying any turn, so re-running the
measurement always looks at the real microscope rather than an image that has
already been straightened. If the shifts do not line up with a clean
quarter-turn -- or come out mirrored -- that means the camera is physically
misaligned. We report that and stop, rather than blur the picture by rotating it
onto a fraction of a pixel.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

import navigator_expert as drv
from shared.algorithms import D4_RESIDUAL_MAX, classify_d4, register_voting

from ..calibration.core.common import (
    SessionPaths,
    acquire_frame_to,
    assert_geometry_matches,
    make_session_paths,
    move_xy_and_verify,
    now_iso,
    read_job_geometry,
    write_json_atomic,
)
from . import Orientation, orientation_from_image_to_stage

KIND = "orientation"
STAGING_NAME = "orientation.json"
STAGING_SCHEMA_VERSION = 1
_PER_STEP_IMAGES = ("home", "plus_x", "plus_y")
_CURRENT = Path(__file__).resolve().parent / "current.json"


@dataclass
class OrientationSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    stage_cfg: dict
    reference_objective: str
    stage_move_um: float
    settle_s: float = 1.0
    image_size_px: tuple[int, int] | None = None
    pixel_size_um: float | None = None
    home_xy: tuple[float, float] | None = None
    images: dict[str, np.ndarray] = field(default_factory=dict)
    raw_files: dict[str, str] = field(default_factory=dict)
    exported_files: dict[str, str] = field(default_factory=dict)
    registrations: dict[str, dict] = field(default_factory=dict)
    orientation: Orientation | None = None
    d4_label: str | None = None
    residual_from_d4: float | None = None
    d4_accepted: bool | None = None
    config_written: bool = False
    failure_reason: str | None = None


def start_session(
    *,
    session_id: str,
    job_name: str,
    reference_objective: str,
    sessions_root: str | Path,
    stage_move_um: float = 30.0,
    settle_s: float = 1.0,
) -> OrientationSession:
    if stage_move_um <= 0:
        raise ValueError(f"stage_move_um must be > 0, got {stage_move_um}")

    # Create the session directory tree BEFORE any driver call so an
    # invalid sessions_root fails before the rig is touched.
    paths = make_session_paths(session_id, KIND, sessions_root)

    client = drv.connect_python_client()
    # Connect-time limits handshake: the measurement moves the stage through
    # the gated drv.move_* wrappers, so it needs validated machine-local
    # limits exactly like any other session.
    limits_state = drv.connect_limits_handshake(client)
    if not limits_state.ok:
        raise RuntimeError(limits_state.error)
    stage_cfg = limits_state.stage_cfg
    hw = drv.get_hardware_info(client, mode="api")
    if hw is None:
        raise RuntimeError("get_hardware_info returned None; LAS X unreachable")

    return OrientationSession(
        session_id=session_id,
        paths=paths,
        job_name=job_name,
        client=client,
        stage_cfg=stage_cfg,
        reference_objective=reference_objective,
        stage_move_um=float(stage_move_um),
        settle_s=float(settle_s),
    )


def _invalidate_staging_config(session: OrientationSession) -> None:
    out = session.paths.configs_dir / STAGING_NAME
    if out.exists():
        out.unlink()
    session.config_written = False


def _acquire_raw_and_validate(
    session: OrientationSession,
    name: str,
    *,
    expected_size_px: tuple[int, int] | None,
    expected_pixel_size_um: float | None,
) -> np.ndarray:
    # RAW frame: pass Orientation() explicitly so the measurement always
    # sees the physical rig, never a partially-reoriented image.
    img = acquire_frame_to(session, name, orientation=Orientation())
    session.images[name] = img
    geom = read_job_geometry(session.client, session.job_name, img)
    if expected_size_px is None or expected_pixel_size_um is None:
        session.image_size_px = tuple(geom.image_size_px)
        session.pixel_size_um = float(geom.pixel_size_um)
    else:
        assert_geometry_matches(
            geom,
            expected_size_px,
            expected_pixel_size_um,
            context=f"{name} image",
        )
    return img


def measure(session: OrientationSession) -> OrientationSession:
    """Acquire raw home/+X/+Y, fit the D4, and stage the accepted orientation.

    Sets ``session.orientation`` + ``session.residual_from_d4`` and writes the
    staging ``orientation.json`` only when both votes are trusted, the fit is a
    proper rotation (not a reflection), and the D4 residual is within
    ``D4_RESIDUAL_MAX``. Otherwise records ``session.failure_reason`` and leaves
    no staging config.
    """
    session.images.clear()
    session.raw_files.clear()
    session.exported_files.clear()
    session.registrations.clear()
    session.orientation = None
    session.d4_label = None
    session.residual_from_d4 = None
    session.d4_accepted = None
    session.config_written = False
    session.failure_reason = None
    session.image_size_px = None
    session.pixel_size_um = None
    session.home_xy = None

    # Unlink stale staging config and per-step TIFFs BEFORE any driver call so
    # a mid-measure failure cannot leave the previous run's adoptable artifact.
    _invalidate_staging_config(session)
    for name in _PER_STEP_IMAGES:
        (session.paths.data_dir / f"{name}.tif").unlink(missing_ok=True)

    xy = drv.get_xy(session.client, mode="api") or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    home_x, home_y = float(xy["x_um"]), float(xy["y_um"])
    session.home_xy = (home_x, home_y)

    try:
        img_home = _acquire_raw_and_validate(
            session, "home", expected_size_px=None, expected_pixel_size_um=None
        )
        expected_size = session.image_size_px
        expected_pixel = session.pixel_size_um

        move_xy_and_verify(
            session.client,
            home_x + session.stage_move_um,
            home_y,
            settle_s=session.settle_s,
        )
        img_plus_x = _acquire_raw_and_validate(
            session, "plus_x", expected_size_px=expected_size, expected_pixel_size_um=expected_pixel
        )

        move_xy_and_verify(session.client, home_x, home_y, settle_s=session.settle_s)
        move_xy_and_verify(
            session.client,
            home_x,
            home_y + session.stage_move_um,
            settle_s=session.settle_s,
        )
        img_plus_y = _acquire_raw_and_validate(
            session, "plus_y", expected_size_px=expected_size, expected_pixel_size_um=expected_pixel
        )

        move_xy_and_verify(session.client, home_x, home_y, settle_s=session.settle_s)
    except Exception:
        # Best-effort recovery: try to return to home so the rig is not left
        # at +X/+Y. Suppress recovery failures so the original exception is
        # what the caller sees.
        try:
            move_xy_and_verify(session.client, home_x, home_y, settle_s=session.settle_s)
        except Exception:
            pass
        raise

    vote_x = register_voting(img_home, img_plus_x, session.pixel_size_um)
    vote_y = register_voting(img_home, img_plus_y, session.pixel_size_um)
    session.registrations["home_to_plus_x"] = vote_x
    session.registrations["home_to_plus_y"] = vote_y

    if not vote_x.get("trusted") or not vote_y.get("trusted"):
        # Weak vote: D4 is never evaluated. Leave d4_accepted=None.
        session.failure_reason = "voting registration not trusted"
        return session

    stage_move = session.stage_move_um
    M_stage_to_image = np.array(
        [
            [vote_x["dx_um"] / stage_move, vote_y["dx_um"] / stage_move],
            [vote_x["dy_um"] / stage_move, vote_y["dy_um"] / stage_move],
        ]
    )
    try:
        fitted = -np.linalg.inv(M_stage_to_image)
    except np.linalg.LinAlgError as exc:
        # Singular / non-invertible fit: D4 classification cannot be
        # completed. d4_accepted stays None (distinct from "rejected").
        session.failure_reason = (
            f"singular stage_to_image matrix ({exc}); collinear or zero voting shifts"
        )
        return session

    label, canonical, residual = classify_d4(fitted)
    session.d4_label = label
    session.residual_from_d4 = float(residual)

    canonical_arr = np.asarray(canonical, dtype=float)
    det = float(np.linalg.det(canonical_arr))
    if det < 0.0:
        session.d4_accepted = False
        session.failure_reason = (
            "reflection candidate selected; this workflow assumes a reflection-free optical path"
        )
        return session
    if residual > D4_RESIDUAL_MAX:
        session.d4_accepted = False
        session.failure_reason = (
            f"D4 residual {residual:.3f} > {D4_RESIDUAL_MAX}; "
            "drift, sparse texture, or too small a stage_move"
        )
        return session

    session.d4_accepted = True
    session.orientation = orientation_from_image_to_stage(canonical_arr)

    out = session.paths.configs_dir / STAGING_NAME
    write_json_atomic(
        out,
        {
            "schema_version": STAGING_SCHEMA_VERSION,
            "rotate_deg": int(session.orientation.rotate_deg),
        },
    )
    session.config_written = True

    # Compact provenance report (no PNG diagnostics -- the accept/reject is a
    # single D4 residual; the operator reads it from the summary).
    write_json_atomic(
        session.paths.reports_dir / "orientation_report.json",
        {
            "schema_version": STAGING_SCHEMA_VERSION,
            "kind": "orientation_report",
            "created_at": now_iso(),
            "reference_objective": session.reference_objective,
            "stage_move_um": float(session.stage_move_um),
            "d4_label": session.d4_label,
            "residual_from_d4": session.residual_from_d4,
            "rotate_deg": int(session.orientation.rotate_deg),
        },
    )
    return session


def adopt_orientation(session: OrientationSession) -> dict:
    """Fold the staged ``orientation.json`` into ``orientation/current.json``.

    ``current.json`` is the value :func:`navigator_expert.orientation.rig_orientation`
    reads at save time. Raises if no accepted staging config exists.
    """
    source = session.paths.configs_dir / STAGING_NAME
    if not source.exists():
        raise FileNotFoundError(
            "No staging orientation to adopt. Review the summary: the "
            "measurement may have failed (weak vote, reflection, or high "
            "residual). Re-run set_orientation before adopting."
        )
    data = json.loads(source.read_text(encoding="utf-8"))
    write_json_atomic(
        _CURRENT,
        {
            "schema_version": STAGING_SCHEMA_VERSION,
            "rotate_deg": int(data["rotate_deg"]),
        },
    )
    return {"source": str(source), "current": str(_CURRENT)}
