"""Measure the camera's D4 mapping to the stage (the ``set_orientation`` step).

The idea is simple: take three pictures -- one at the start, one after nudging
the stage a little in X, and one after nudging it in Y -- and watch which way the
picture shifts each time. From those shifts we determine the axis assignment,
both axis signs, the quarter-turn, and whether the acquisition is mirrored.

Under the hood this registers each pair of pictures to get the shift, builds a
small 2x2 matrix from the two shifts, and matches it to the nearest lossless D4
mapping (four quarter-turns, each mirrored or not). Each notebook run owns one
``orientation/<datetime>/`` directory. Measurement and validation replace
their own outputs when rerun. Only Save and Adopt writes ``orientation.json``;
until then the visible session is retained as evidence but ignored by the driver.

The three pictures are taken **without** applying any correction, so re-running the
measurement always looks at the real microscope rather than an image that has
already been straightened. A mirror may come from a legitimate acquisition
setting and is recorded. If the shifts do not line up with any clean D4 mapping,
we report that and stop rather than resample the image onto a fractional angle.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import math
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

import navigator_expert as drv
from navigator_expert.acquisition.naming import Naming, run_hash
from navigator_expert.algorithms import D4_RESIDUAL_MAX, classify_d4, register_voting

from ..calibration.core.common import (
    SessionPaths,
    acquire_frame_to,
    assert_geometry_matches,
    move_xy_and_verify,
    now_iso,
    read_job_geometry,
    read_selected_job_name,
    write_json_atomic,
)
from ..notebook_support import archive_notebook as archive_operator_notebook
from . import (
    SCHEMA_VERSION,
    Orientation,
    orientation_config,
    orientation_from_image_to_stage,
    reorient_array,
)

KIND = "orientation"
ORIENTATION_NAME = "orientation.json"
REPORT_SCHEMA_VERSION = SCHEMA_VERSION
DIAGNOSTIC_NAME = "orientation_diagnostic.png"
_PER_STEP_IMAGES = ("home", "plus_x", "plus_y")


@dataclass
class OrientationSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    stage_move_um: float
    settle_s: float = 1.0
    machine: Any = None
    target_dir: Path | None = None
    adopted: bool = False
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
    # Wall-clock second the session was opened; reports record how long the
    # whole measurement took (a slow run often means a struggling stage or
    # LAS X, so the number is diagnostic, not decoration).
    started_at_s: float | None = None


_NOTEBOOK_SESSION: OrientationSession | None = None


def start_session(
    *,
    job_name: str | None = None,
    stage_move_um: float = 40.0,
    settle_s: float = 1.0,
    machine: Any = None,
    moment: datetime | None = None,
) -> OrientationSession:
    if stage_move_um <= 0:
        raise ValueError(f"stage_move_um must be > 0, got {stage_move_um}")

    if machine is None:
        from ..config.machine import MACHINE

        machine = MACHINE
    moment = moment or datetime.now(timezone.utc)
    target_dir = machine.new_snapshot_dir(moment, "orientation")

    # The timestamp directory is the session from the start. It becomes active
    # only when Save and Adopt writes orientation.json into it.
    run_dir = target_dir
    paths = SessionPaths(
        session_root=run_dir,
        session_dir=run_dir,
        configs_dir=run_dir,  # compatibility field; no configs/ is created
        reports_dir=run_dir / "reports",
        data_dir=run_dir / "data",
    )
    for directory in (paths.data_dir, paths.reports_dir, run_dir / "validation"):
        directory.mkdir(parents=True, exist_ok=False)

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
    if job_name is None:
        job_name = read_selected_job_name(client)
        print(f"Using active Navigator Expert job: {job_name}")
    return OrientationSession(
        session_id=target_dir.name,
        paths=paths,
        job_name=job_name,
        client=client,
        stage_move_um=float(stage_move_um),
        settle_s=float(settle_s),
        machine=machine,
        target_dir=target_dir,
        started_at_s=time.time(),
    )


def _invalidate_orientation_config(session: OrientationSession) -> None:
    session.config_written = False


def _reset_measurement_outputs(session: OrientationSession) -> None:
    """Clear only this session's owned outputs before a measurement rerun."""
    session_dir = Path(session.paths.session_dir)
    directories = (
        Path(session.paths.data_dir),
        Path(session.paths.reports_dir),
        session_dir / "validation",
    )
    for directory in directories:
        if directory.parent != session_dir:
            raise RuntimeError(f"refusing to clear data outside orientation session: {directory}")
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir()


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


def _gallery_orientations() -> tuple[Orientation, ...]:
    """All valid D4 corrections, grouped by mirror state then rotation."""
    return tuple(
        Orientation(rotate_deg=degrees, mirrored=mirrored)
        for mirrored in (False, True)
        for degrees in (0, 90, 180, 270)
    )


def _candidate_alignment_overlay(
    home: np.ndarray,
    plus_x: np.ndarray,
    plus_y: np.ndarray,
    *,
    stage_move_um: float,
    pixel_size_um: float,
    orientation: Orientation,
) -> np.ndarray:
    """Align both moved frames as one D4 candidate predicts, then overlay them."""
    from scipy.ndimage import shift

    stage_to_image = -np.linalg.inv(np.asarray(orientation.image_to_stage, dtype=float))
    expected_x = stage_to_image[:, 0] * stage_move_um
    expected_y = stage_to_image[:, 1] * stage_move_um

    def _align(image: np.ndarray, expected_um: np.ndarray) -> np.ndarray:
        background = float(np.median(image))
        return shift(
            np.asarray(image),
            shift=(-expected_um[1] / pixel_size_um, -expected_um[0] / pixel_size_um),
            order=1,
            mode="constant",
            cval=background,
            prefilter=False,
        )

    aligned_x = _align(plus_x, expected_x)
    aligned_y = _align(plus_y, expected_y)
    aligned_moves = (aligned_x.astype(np.float64) + aligned_y.astype(np.float64)) / 2.0
    overlay = _registration_overlay(home, aligned_moves)
    return reorient_array(overlay, orientation)


def _reflection_label(orientation: Orientation) -> str:
    return "Reflection" if orientation.mirrored else "No reflection"


def write_orientation_diagnostic(
    session: OrientationSession,
    vote_x: dict,
    vote_y: dict,
    canonical: np.ndarray,
) -> Path:
    """Render measured overlays and an eight-case D4 gallery to an archived PNG."""
    # Build the figure directly on the Agg (image-file) canvas instead of
    # going through pyplot: pyplot auto-selects a GUI backend, which needs a
    # working desktop toolkit this machine may not have. The figure is only
    # ever saved to a PNG, never shown, so the file-only canvas is exactly
    # right — and a broken GUI install can no longer take the diagnostic
    # (and the whole measurement) down with it.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import FancyBboxPatch, Patch

    candidate = orientation_from_image_to_stage(canonical)
    accepted = session.orientation is not None
    selected_color = "#087F5B" if accepted else "#C56A00"

    fig = Figure(figsize=(14, 9.4), facecolor="#F4F6F7")
    FigureCanvasAgg(fig)
    grid = fig.add_gridspec(
        3,
        1,
        height_ratios=(0.58, 0.14, 2.0),
        left=0.035,
        right=0.985,
        bottom=0.07,
        top=0.97,
        hspace=0.12,
    )
    gallery_grid = grid[2].subgridspec(
        2,
        5,
        width_ratios=(0.18, 1, 1, 1, 1),
        hspace=0.16,
        wspace=0.10,
    )

    summary_ax = fig.add_subplot(grid[0])
    summary_ax.set_axis_off()
    summary_ax.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.012,rounding_size=0.025",
            transform=summary_ax.transAxes,
            facecolor="white",
            edgecolor="#DDE2E5",
            linewidth=1.2,
            clip_on=False,
        )
    )
    candidate_mapping = candidate.axis_mapping
    summary_ax.text(
        0.025,
        0.84,
        "DETECTED IMAGE CORRECTION" if accepted else "ORIENTATION NOT ACCEPTED",
        transform=summary_ax.transAxes,
        ha="left",
        va="center",
        fontsize=11.5,
        fontweight="bold",
        color=selected_color,
    )
    summary_ax.text(
        0.025,
        0.57,
        "ROTATION",
        transform=summary_ax.transAxes,
        ha="left",
        va="center",
        fontsize=9.5,
        fontweight="bold",
        color="#7A858C",
    )
    summary_ax.text(
        0.025,
        0.28,
        f"{candidate.rotate_deg}° clockwise",
        transform=summary_ax.transAxes,
        ha="left",
        va="center",
        fontsize=20,
        fontweight="bold",
        color="#172126",
    )
    summary_ax.text(
        0.30,
        0.57,
        "REFLECTION",
        transform=summary_ax.transAxes,
        ha="left",
        va="center",
        fontsize=9.5,
        fontweight="bold",
        color="#7A858C",
    )
    summary_ax.text(
        0.30,
        0.28,
        "Yes" if candidate.mirrored else "No",
        transform=summary_ax.transAxes,
        ha="left",
        va="center",
        fontsize=20,
        fontweight="bold",
        color="#172126",
    )
    summary_ax.text(
        0.52,
        0.57,
        "SIGN CONVENTION",
        transform=summary_ax.transAxes,
        ha="left",
        va="center",
        fontsize=9.5,
        fontweight="bold",
        color="#7A858C",
    )
    summary_ax.text(
        0.52,
        0.28,
        f"Stage X  ←  image {candidate_mapping['stage_x_from_image']}     "
        f"Stage Y  ←  image {candidate_mapping['stage_y_from_image']}",
        transform=summary_ax.transAxes,
        ha="left",
        va="center",
        fontsize=16,
        fontweight="bold",
        color="#172126",
    )

    legend_ax = fig.add_subplot(grid[1])
    legend_ax.set_axis_off()
    legend_ax.legend(
        handles=(
            Patch(facecolor="#FF00FF", edgecolor="none", label="Home image"),
            Patch(
                facecolor="#00C853",
                edgecolor="none",
                label="Moved images corrected by each candidate",
            ),
            Patch(facecolor="white", edgecolor="#9AA3A8", label="Agreement / overlap"),
        ),
        loc="center left",
        bbox_to_anchor=(0.005, 0.5),
        ncol=3,
        frameon=False,
        fontsize=10,
        handlelength=1.2,
        columnspacing=1.8,
    )
    legend_ax.text(
        0.995,
        0.5,
        "The selected candidate has the strongest white overlap.",
        transform=legend_ax.transAxes,
        ha="right",
        va="center",
        fontsize=9.5,
        color="#667179",
    )

    gallery_stride = max(1, int(np.ceil(max(session.images["home"].shape) / 256)))
    gallery_home = session.images["home"][::gallery_stride, ::gallery_stride]
    gallery_plus_x = session.images["plus_x"][::gallery_stride, ::gallery_stride]
    gallery_plus_y = session.images["plus_y"][::gallery_stride, ::gallery_stride]
    gallery_pixel_size_um = session.pixel_size_um * gallery_stride

    def _draw_candidate(
        ax,
        orientation: Orientation,
        *,
        selected: bool,
    ) -> None:
        border_color = selected_color if selected else "#A8ADB3"
        border_width = 4.0 if selected else 0.9
        overlay = _candidate_alignment_overlay(
            gallery_home,
            gallery_plus_x,
            gallery_plus_y,
            stage_move_um=session.stage_move_um,
            pixel_size_um=gallery_pixel_size_um,
            orientation=orientation,
        )
        ax.imshow(overlay, interpolation="nearest")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color(border_color)
            spine.set_linewidth(border_width)
        if selected:
            ax.text(
                0.5,
                0.965,
                "SELECTED" if accepted else "NEAREST - REJECTED",
                transform=ax.transAxes,
                ha="center",
                va="top",
                color="white",
                fontsize=8.5,
                fontweight="bold",
                bbox={"facecolor": selected_color, "edgecolor": "none", "pad": 3.5},
            )

    for row, label in enumerate(("NO\nREFLECTION", "REFLECTION")):
        label_ax = fig.add_subplot(gallery_grid[row, 0])
        label_ax.set_axis_off()
        label_ax.text(
            0.52,
            0.5,
            label,
            transform=label_ax.transAxes,
            ha="center",
            va="center",
            fontsize=9.5,
            linespacing=1.25,
            fontweight="bold",
            color="#667179",
        )

    gallery_slots = tuple((row, column + 1) for row in range(2) for column in range(4))
    for orientation, (row, column) in zip(_gallery_orientations(), gallery_slots, strict=True):
        ax = fig.add_subplot(gallery_grid[row, column])
        if row == 0:
            ax.set_title(
                f"{orientation.rotate_deg}°",
                fontsize=11,
                fontweight="bold",
                color="#354047",
                pad=7,
            )
        _draw_candidate(
            ax,
            orientation,
            selected=orientation == candidate,
        )

    fig.text(
        0.5,
        0.025,
        "Eight lossless possibilities: four rotations × reflection absent or present.",
        ha="center",
        va="center",
        fontsize=9.5,
        color="#667179",
    )
    output = session.paths.reports_dir / DIAGNOSTIC_NAME
    fig.savefig(output, dpi=105, pil_kwargs={"compress_level": 9, "optimize": True})
    return output


def show_measurement_result(session: OrientationSession) -> None:
    """Display the compact eight-option result without notebook-side plotting."""
    from IPython.display import Image, Markdown, display

    diagnostic = session.paths.reports_dir / DIAGNOSTIC_NAME
    if diagnostic.is_file():
        display(Image(filename=str(diagnostic), width=1350))
        return
    display(Markdown(f"**Orientation not accepted:** {session.failure_reason}"))


def _session_duration_s(session) -> float | None:
    """Seconds since the session was opened, or None for hand-built sessions."""
    if session.started_at_s is None:
        return None
    return round(time.time() - float(session.started_at_s), 3)


def _finite_registration(vote: dict) -> dict:
    """One vote's report entry, with non-finite shifts mapped to None."""

    def _num(value):
        return None if value is None or not math.isfinite(float(value)) else float(value)

    return {
        "dx_um": _num(vote.get("dx_um")),
        "dy_um": _num(vote.get("dy_um")),
        "confidence": vote.get("confidence"),
        "agreeing": list(vote.get("agreeing") or []),
    }


def measure(session: OrientationSession) -> OrientationSession:
    """Acquire raw home/+X/+Y and derive the candidate orientation.

    Sets ``session.orientation`` + ``session.residual_from_d4`` only when both
    votes are trusted and the D4 residual is within ``D4_RESIDUAL_MAX``. All
    eight lossless D4 transforms are valid. Save and Adopt writes the active
    config later, after validation.
    """
    if session.adopted:
        raise RuntimeError("this orientation session is already adopted")
    _reset_measurement_outputs(session)
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

    # Invalidate state BEFORE any driver call so a mid-measure failure cannot
    # leave this session looking valid.
    _invalidate_orientation_config(session)

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
        # Weak vote: D4 is never evaluated. Leave d4_accepted=None, but still
        # write the report JSON — a failed run should be as reviewable from
        # disk as a rejected one, not vanish with the notebook output.
        session.failure_reason = "voting registration not trusted"
        write_json_atomic(
            session.paths.reports_dir / "orientation_report.json",
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "kind": "orientation_report",
                "created_at": now_iso(),
                "job_name": session.job_name,
                "stage_move_um": float(session.stage_move_um),
                "accepted": False,
                "failure_reason": session.failure_reason,
                "duration_s": _session_duration_s(session),
                # An untrusted vote can carry NaN shifts, which strict JSON
                # refuses; store None for anything non-finite.
                "registrations": {
                    "stage_plus_x": _finite_registration(vote_x),
                    "stage_plus_y": _finite_registration(vote_y),
                },
            },
        )
        return session

    stage_move = session.stage_move_um
    M_stage_to_image = np.array(
        [
            [vote_x["dx_um"] / stage_move, vote_y["dx_um"] / stage_move],
            [vote_x["dy_um"] / stage_move, vote_y["dy_um"] / stage_move],
        ]
    )
    try:
        # Sign convention (bench-checkable; guarded by the sign-anchor test in
        # tests/unit/test_orientation_measure.py and the register_voting sign
        # guard in tests/unit/test_registration.py). M_stage_to_image
        # is the measured feature-shift per stage move. A perfectly aligned rig
        # moves features OPPOSITE the stage (+X stage -> -column), so M = -I and
        # the image->stage correction is -inv(M) = I. Flipping this sign would
        # rotate every result by a uniform 180 deg -- it can never introduce a
        # mirror. Confirm once on the rig: on an aligned rig, +X moves features
        # toward -column.
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
            "schema_version": REPORT_SCHEMA_VERSION,
            "kind": "orientation_report",
            "created_at": now_iso(),
            "job_name": session.job_name,
            "stage_move_um": float(session.stage_move_um),
            "d4_label": session.d4_label,
            "residual_from_d4": session.residual_from_d4,
            "mirrored": session.is_mirrored,
            "reflection_axis": (
                session.orientation.reflection_axis if session.orientation is not None else None
            ),
            "determinant": int(round(det)),
            "axis_signs": (
                session.orientation.axis_signs if session.orientation is not None else None
            ),
            "axis_mapping": (
                session.orientation.axis_mapping if session.orientation is not None else None
            ),
            "accepted": session.d4_accepted,
            "failure_reason": session.failure_reason,
            "duration_s": _session_duration_s(session),
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

    return session


def run_notebook_measurement() -> OrientationSession:
    """Measure in one reusable notebook session without creating rerun litter."""
    global _NOTEBOOK_SESSION

    if _NOTEBOOK_SESSION is None:
        _NOTEBOOK_SESSION = start_session()
    if _NOTEBOOK_SESSION.adopted:
        raise RuntimeError("this notebook session is adopted; restart the kernel for a new run")
    _NOTEBOOK_SESSION = measure(_NOTEBOOK_SESSION)
    return _NOTEBOOK_SESSION


def acquire_validation_image(
    session: OrientationSession,
) -> tuple[np.ndarray, Path]:
    """Acquire, save, and reload one image with this run's orientation.

    The returned pixels come from the saved OME-TIFF, so displaying them checks
    the same rotation and reflection that later acquisitions will receive.
    """
    if session.orientation is None or not session.d4_accepted:
        raise RuntimeError("Measure the orientation successfully before running validation.")

    output_root = session.paths.session_dir / "validation"
    if output_root.parent != session.paths.session_dir:
        raise RuntimeError(f"refusing to clear data outside orientation session: {output_root}")
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir()

    acquisition = drv.acquire(session.client, session.job_name)
    saved = drv.save(
        session.client,
        acquisition,
        output_root,
        Naming(
            acquisition_type="orientation-validation",
            hash6=run_hash(),
            position_label="validation",
        ),
        orientation=session.orientation,
    )
    if len(saved.image_paths) != 1:
        raise ValueError(f"Validation expected one saved image; got {len(saved.image_paths)}.")

    image_path = Path(next(iter(saved.image_paths.values())))
    image = np.asarray(tifffile.imread(image_path))
    if image.ndim == 3 and image.shape[0] == 1:
        image = image[0]
    if image.ndim != 2:
        raise ValueError(f"Validation expected a 2-D image; got shape {image.shape!r}.")
    return image, image_path


def validate(session: OrientationSession) -> Path:
    """Acquire validation data and show a compact JPEG preview in the notebook."""
    from IPython.display import Image, Markdown, display
    from PIL import Image as PillowImage

    image, image_path = acquire_validation_image(session)
    preview_path = image_path.parent / "orientation_validation_preview.jpg"
    preview = PillowImage.fromarray(
        np.rint(_normalise_for_display(image) * 255).astype(np.uint8),
        mode="L",
    )
    preview.thumbnail((720, 720), PillowImage.Resampling.LANCZOS)
    preview.save(preview_path, quality=78, optimize=True)
    display(Image(filename=str(preview_path), width=640))
    display(Markdown(f"Validation image: `{image_path}`"))
    return image_path


def archive_notebook(session: OrientationSession, notebook_path: str | Path) -> Path:
    """Archive the completed notebook under this run's ``data/notebook``."""
    return archive_operator_notebook(notebook_path, session.paths.session_dir)


def adopt_orientation(session: OrientationSession, notebook_path: str | Path) -> dict[str, str]:
    """Activate a validated orientation by writing its config last."""
    if session.orientation is None or not session.d4_accepted:
        raise RuntimeError("measure and accept the orientation before adoption")
    if not any((session.paths.session_dir / "validation").rglob("*.tif*")):
        raise RuntimeError("run orientation validation before adoption")
    if session.machine is None or session.target_dir is None:
        raise RuntimeError("orientation session has no machine adoption target")

    target = Path(session.target_dir)
    session_dir = Path(session.paths.session_dir)
    if session_dir != target:
        raise RuntimeError(f"unexpected orientation session directory: {session_dir}")

    if session.adopted:
        archived = archive_operator_notebook(notebook_path, session_dir)
        return {
            "snapshot": str(target),
            "orientation_path": str(target / ORIENTATION_NAME),
            "notebook_path": str(archived),
        }

    latest = session.machine.latest_snapshot("orientation")
    if latest is not None and latest != target and target.name <= latest.name:
        raise RuntimeError(
            f"cannot adopt {target.name}: a newer orientation {latest.name} is already active"
        )

    # Archive the executed notebook first. orientation.json is the sole
    # activation signal and is deliberately the final atomic write.
    archived = archive_operator_notebook(notebook_path, session_dir)
    write_json_atomic(
        session_dir / ORIENTATION_NAME,
        orientation_config(session.orientation, measured=True),
    )
    session.config_written = True
    session.adopted = True
    return {
        "snapshot": str(target),
        "orientation_path": str(target / ORIENTATION_NAME),
        "notebook_path": str(archived),
    }
