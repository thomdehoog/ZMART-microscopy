"""Measure the camera's D4 mapping to the stage (the ``set_orientation`` step).

The idea is simple: take three pictures -- one at the start, one after nudging
the stage a little in X, and one after nudging it in Y -- and watch which way the
picture shifts each time. From those shifts we determine the axis assignment,
both axis signs, the quarter-turn, and whether the acquisition is mirrored.

Under the hood this registers each pair of pictures to get the shift, builds a
small 2x2 matrix from the two shifts, and matches it to the nearest lossless D4
mapping (four quarter-turns, each mirrored or not). The result is written to a staging
``orientation.json`` that :func:`adopt_orientation` publishes into a new
``orientation/<datetime>/`` ProgramData snapshot, which is the value the driver
reads at save time.

The three pictures are taken **without** applying any correction, so re-running the
measurement always looks at the real microscope rather than an image that has
already been straightened. A mirror may come from a legitimate acquisition
setting and is recorded. If the shifts do not line up with any clean D4 mapping,
we report that and stop rather than resample the image onto a fractional angle.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
from . import (
    SCHEMA_VERSION,
    Orientation,
    orientation_config,
    orientation_from_config,
    orientation_from_image_to_stage,
)

KIND = "orientation"
STAGING_NAME = "orientation.json"
STAGING_SCHEMA_VERSION = SCHEMA_VERSION
DIAGNOSTIC_NAME = "orientation_diagnostic.png"
_PER_STEP_IMAGES = ("home", "plus_x", "plus_y")


@dataclass
class OrientationSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
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
    is_mirrored: bool | None = None
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
    hw = drv.get_hardware_info(client, mode="api")
    if hw is None:
        raise RuntimeError("get_hardware_info returned None; LAS X unreachable")

    return OrientationSession(
        session_id=session_id,
        paths=paths,
        job_name=job_name,
        client=client,
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


def _normalise_for_display(image: np.ndarray) -> np.ndarray:
    values = np.asarray(image, dtype=np.float64)
    lo, hi = np.percentile(values, (1.0, 99.0))
    if hi <= lo:
        return np.zeros_like(values)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def _registration_overlay(reference: np.ndarray, target: np.ndarray) -> np.ndarray:
    ref = _normalise_for_display(reference)
    tgt = _normalise_for_display(target)
    rgb = np.zeros((*ref.shape, 3), dtype=np.float64)
    rgb[..., 0] = ref
    rgb[..., 2] = ref
    rgb[..., 1] = tgt
    return np.clip(rgb, 0.0, 1.0)


def write_orientation_diagnostic(
    session: OrientationSession,
    vote_x: dict,
    vote_y: dict,
    canonical: np.ndarray,
) -> Path:
    """Render the measured shifts and inferred stage axes to an archived PNG."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(11, 9), constrained_layout=True)
    for ax, target, vote, title in (
        (axes[0, 0], session.images["plus_x"], vote_x, "Stage move +X"),
        (axes[0, 1], session.images["plus_y"], vote_y, "Stage move +Y"),
    ):
        ax.imshow(_registration_overlay(session.images["home"], target), origin="upper")
        ax.set_title(f"{title}\nfeature shift = ({vote['dx_um']:+.2f}, {vote['dy_um']:+.2f}) um")
        ax.set_axis_off()
    axes[0, 0].text(
        0.02,
        0.98,
        "home: magenta\nmoved: green",
        transform=axes[0, 0].transAxes,
        va="top",
        color="white",
        bbox={"facecolor": "black", "alpha": 0.7, "pad": 4},
    )

    shifts = (
        (vote_x, "stage +X", "#0072B2"),
        (vote_y, "stage +Y", "#009E73"),
    )
    limit = max(
        session.stage_move_um,
        *(abs(float(vote[key])) for vote, _label, _color in shifts for key in ("dx_um", "dy_um")),
    )
    limit = max(limit * 1.25, 1.0)
    shift_ax = axes[1, 0]
    shift_ax.axhline(0, color="0.75", linewidth=1)
    shift_ax.axvline(0, color="0.75", linewidth=1)
    for vote, label, color in shifts:
        shift_ax.arrow(
            0,
            0,
            vote["dx_um"],
            vote["dy_um"],
            color=color,
            width=limit * 0.012,
            head_width=limit * 0.09,
            length_includes_head=True,
            label=label,
        )
    shift_ax.set(xlim=(-limit, limit), ylim=(limit, -limit))
    shift_ax.set_aspect("equal")
    shift_ax.set_xlabel("image shift X (um, right +)")
    shift_ax.set_ylabel("image shift Y (um, down +)")
    shift_ax.set_title("Measured feature motion")
    shift_ax.legend(loc="best")
    shift_ax.grid(alpha=0.2)

    mapping_ax = axes[1, 1]
    mapping_ax.axhline(0, color="0.75", linewidth=1)
    mapping_ax.axvline(0, color="0.75", linewidth=1)
    stage_to_image = np.linalg.inv(np.asarray(canonical, dtype=float))
    for vector, label, color in (
        (stage_to_image[:, 0], "stage +X", "#0072B2"),
        (stage_to_image[:, 1], "stage +Y", "#009E73"),
    ):
        mapping_ax.arrow(
            0,
            0,
            vector[0],
            vector[1],
            color=color,
            width=0.025,
            head_width=0.16,
            length_includes_head=True,
        )
        mapping_ax.text(
            vector[0] * 1.12,
            vector[1] * 1.12,
            label,
            color=color,
            ha="center",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 1},
        )
    mapping_ax.set(xlim=(-1.45, 1.45), ylim=(1.45, -1.45))
    mapping_ax.set_aspect("equal")
    mapping_ax.set_xlabel("raw image X (right +)")
    mapping_ax.set_ylabel("raw image Y (down +)")
    if session.orientation is None:
        correction = "save correction: none (measurement rejected)"
    else:
        mirror_step = "mirror horizontally, then " if session.orientation.mirrored else ""
        correction = (
            f"save correction: {mirror_step}{session.orientation.rotate_deg} degrees clockwise"
        )
    mapping_ax.set_title(f"Stage axes in the raw image: {session.d4_label}\n{correction}")
    mapping_ax.grid(alpha=0.2)
    determinant = int(round(float(np.linalg.det(canonical))))
    if session.is_mirrored:
        mirrored_text = "YES"
        mirror_correction = "ENABLED"
        status_color = "#0072B2"
    else:
        mirrored_text = "NO"
        mirror_correction = "not needed"
        status_color = "#009E73"
    mapping_ax.text(
        0.02,
        0.02,
        f"image -> stage = {np.asarray(canonical, dtype=int).tolist()}\n"
        f"mirrored image = {mirrored_text} (det = {determinant:+d})\n"
        f"mirror correction = {mirror_correction}\n"
        f"D4 residual = {session.residual_from_d4:.4f} (limit {D4_RESIDUAL_MAX})",
        transform=mapping_ax.transAxes,
        va="bottom",
        family="monospace",
        bbox={
            "facecolor": "white",
            "edgecolor": status_color,
            "linewidth": 1.5,
            "alpha": 0.9,
            "pad": 4,
        },
    )

    fig.suptitle(
        f"Orientation measurement | {session.reference_objective} | "
        f"stage step {session.stage_move_um:g} um",
        fontsize=14,
    )
    output = session.paths.reports_dir / DIAGNOSTIC_NAME
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return output


def measure(session: OrientationSession) -> OrientationSession:
    """Acquire raw home/+X/+Y, fit the D4, and stage the accepted orientation.

    Sets ``session.orientation`` + ``session.residual_from_d4`` and writes the
    staging ``orientation.json`` only when both votes are trusted and the D4
    residual is within ``D4_RESIDUAL_MAX``. All eight lossless D4 transforms are
    valid, including a mirror introduced by an acquisition setting. Otherwise
    records ``session.failure_reason`` and leaves no staging config.
    """
    session.images.clear()
    session.raw_files.clear()
    session.exported_files.clear()
    session.registrations.clear()
    session.orientation = None
    session.d4_label = None
    session.residual_from_d4 = None
    session.is_mirrored = None
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
    session.is_mirrored = det < 0.0
    if residual > D4_RESIDUAL_MAX:
        session.d4_accepted = False
        session.failure_reason = (
            f"D4 residual {residual:.3f} > {D4_RESIDUAL_MAX}; "
            "drift, sparse texture, or too small a stage_move"
        )
    else:
        session.d4_accepted = True
        session.orientation = orientation_from_image_to_stage(canonical_arr)

    write_orientation_diagnostic(session, vote_x, vote_y, canonical_arr)
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
            "mirrored": session.is_mirrored,
            "determinant": int(round(det)),
            "axis_signs": (
                session.orientation.axis_signs if session.orientation is not None else None
            ),
            "axis_mapping": (
                session.orientation.axis_mapping if session.orientation is not None else None
            ),
            "accepted": session.d4_accepted,
            "failure_reason": session.failure_reason,
            "rotate_deg": (
                int(session.orientation.rotate_deg) if session.orientation is not None else None
            ),
            "image_to_stage": canonical_arr.astype(int).tolist(),
            "registrations": {
                "stage_plus_x": {
                    key: vote_x[key] for key in ("dx_um", "dy_um", "confidence", "agreeing")
                },
                "stage_plus_y": {
                    key: vote_y[key] for key in ("dx_um", "dy_um", "confidence", "agreeing")
                },
            },
            "diagnostic": DIAGNOSTIC_NAME,
        },
    )

    if not session.d4_accepted:
        return session

    out = session.paths.configs_dir / STAGING_NAME
    write_json_atomic(out, orientation_config(session.orientation, measured=True))
    session.config_written = True
    return session


def adopt_orientation(
    session: OrientationSession,
    *,
    machine: Any = None,
    moment: datetime | None = None,
    notebook_paths: Any = (),
) -> dict:
    """Publish the measured D4 mapping into a new orientation timestamp snapshot.

    Reads the staged ``orientation.json`` and atomically appends it together
    with the complete measurement session under the machine's independent
    ``orientation/<datetime>/`` tree. Once publication succeeds, the redundant
    working-session directory is removed. Limits, calibration, and origin are
    not copied. The newest orientation snapshot is what the driver reads when
    it connects and what calibration reads at capture time.

    Args:
        session: The orientation session holding the staged config.
        machine: ``MachineProfile`` to publish into; ``None`` uses the global
            ``MACHINE``. Tests inject a hermetic profile here.
        moment: Snapshot timestamp; ``None`` uses ``datetime.now(timezone.utc)``.
            Must sort strictly after the latest orientation snapshot.
        notebook_paths: Saved notebook(s) to archive in the snapshot.

    Returns:
        ``{"source": str, "snapshot": str, "orientation_path": str}`` -- the new
        snapshot folder and its ``orientation.json``.

    Raises:
        FileNotFoundError: if no accepted staging config exists.
    """
    source = session.paths.configs_dir / STAGING_NAME
    if not source.exists():
        raise FileNotFoundError(
            "No staging orientation to adopt. Review the summary: the "
            "measurement may have failed (weak vote or high "
            "residual). Re-run set_orientation before adopting."
        )
    if machine is None:
        from ..config.machine import MACHINE

        machine = MACHINE
    if moment is None:
        moment = datetime.now(timezone.utc)

    data = json.loads(source.read_text(encoding="utf-8"))
    orientation = orientation_from_config(data)
    snapshot = machine.publish_snapshot(
        moment,
        orientation=orientation_config(orientation, measured=True),
        archive_paths=[session.paths.session_dir],
        notebook_paths=notebook_paths,
    )
    archived_session = snapshot / session.paths.session_dir.name
    archived_source = archived_session / "configs" / STAGING_NAME
    try:
        shutil.rmtree(session.paths.session_dir)
    except OSError as exc:
        raise RuntimeError(
            f"orientation was published to {snapshot}, but the redundant working "
            f"session could not be removed: {session.paths.session_dir}"
        ) from exc
    return {
        "source": str(archived_source),
        "snapshot": str(snapshot),
        "measurement_session": str(archived_session),
        "orientation_path": str(snapshot / STAGING_NAME),
    }
