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
import math
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

import navigator_expert as drv
from navigator_expert.algorithms import D4_RESIDUAL_MAX, classify_d4, register_voting

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
    reorient_array,
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
    # Wall-clock second the session was opened; reports record how long the
    # whole measurement took (a slow run often means a struggling stage or
    # LAS X, so the number is diagnostic, not decoration).
    started_at_s: float | None = None


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
        started_at_s=time.time(),
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


def _mapping_label(orientation: Orientation) -> str:
    mapping = orientation.axis_mapping
    return f"{mapping['stage_x_from_image']} {mapping['stage_y_from_image']}"


def _correction_label(orientation: Orientation) -> str:
    steps = []
    if orientation.mirrored:
        steps.append("flip left-right")
    if orientation.rotate_deg:
        steps.append(f"rotate {orientation.rotate_deg} deg CW")
    return ", then ".join(steps) if steps else "no correction"


def _sign_label(value: int) -> str:
    return "+" if value > 0 else "-"


def _reflection_label(orientation: Orientation) -> str:
    return {
        None: "none",
        "vertical": "vertical axis (left-right flip)",
        "horizontal": "horizontal axis (top-bottom flip)",
        "main_diagonal": "main diagonal (\\)",
        "anti_diagonal": "anti-diagonal (/)",
    }[orientation.reflection_axis]


def _reflection_tag(orientation: Orientation) -> str:
    """Short glance-label naming the net reflection axis (or a pure rotation).

    Leads with the physical axis so the panel is not read as "left-right only":
    a mirror is a handedness flip whose axis is one of four.
    """
    return {
        None: "no flip",
        "vertical": "left-right flip",
        "horizontal": "top-bottom flip",
        "main_diagonal": "diagonal flip (\\)",
        "anti_diagonal": "diagonal flip (/)",
    }[orientation.reflection_axis]


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
    from matplotlib.patches import Rectangle

    candidate = orientation_from_image_to_stage(canonical)
    accepted = session.orientation is not None
    selected_color = "#087F5B" if accepted else "#C56A00"
    selected_word = "DETECTED" if accepted else "NEAREST CANDIDATE - REJECTED"

    fig = Figure(figsize=(16, 12.25), facecolor="white")
    FigureCanvasAgg(fig)
    grid = fig.add_gridspec(
        3,
        1,
        height_ratios=(1.0, 0.10, 1.85),
        left=0.045,
        right=0.975,
        bottom=0.055,
        top=0.93,
        hspace=0.18,
    )
    summary_grid = grid[0].subgridspec(1, 12, wspace=0.30)
    gallery_grid = grid[2].subgridspec(2, 4, hspace=0.62, wspace=0.34)

    evidence_ax = fig.add_subplot(summary_grid[0, 4:12])
    evidence_ax.set_axis_off()
    evidence_ax.add_patch(
        Rectangle(
            (0, 0),
            1,
            1,
            transform=evidence_ax.transAxes,
            facecolor="#F2F8F5" if accepted else "#FFF7E8",
            edgecolor=selected_color,
            linewidth=2,
            clip_on=False,
        )
    )
    candidate_signs = candidate.axis_signs
    evidence_ax.text(
        0.045,
        0.90,
        f"CHOSEN ORIENTATION - {selected_word}",
        transform=evidence_ax.transAxes,
        ha="left",
        va="top",
        fontsize=14,
        fontweight="bold",
        color=selected_color,
    )
    evidence_ax.plot(
        [0.5, 0.5],
        [0.10, 0.76],
        transform=evidence_ax.transAxes,
        color="#C8D8D1" if accepted else "#E1CDA6",
        linewidth=1.2,
    )
    evidence_ax.text(
        0.045,
        0.73,
        f"CORRECTION\n"
        f"Rotation: {candidate.rotate_deg} deg clockwise\n"
        f"Reflection: {_reflection_label(candidate)}\n"
        f"Handedness flipped: {'Yes' if candidate.mirrored else 'No'}\n"
        f"Apply: {_correction_label(candidate)}\n\n"
        f"DERIVED MAPPING\n"
        f"Image to stage: {_mapping_label(candidate)}\n"
        f"Axis signs: X {_sign_label(candidate_signs['stage_x'])}, "
        f"Y {_sign_label(candidate_signs['stage_y'])}",
        transform=evidence_ax.transAxes,
        ha="left",
        va="top",
        fontsize=11.5,
        linespacing=1.35,
        color="#25302C",
    )
    evidence_ax.text(
        0.545,
        0.73,
        f"MEASUREMENT EVIDENCE\n"
        f"Stage +X: ({vote_x['dx_um']:+.2f}, {vote_x['dy_um']:+.2f}) um\n"
        f"Stage +Y: ({vote_y['dx_um']:+.2f}, {vote_y['dy_um']:+.2f}) um\n"
        f"D4 residual: {session.residual_from_d4:.4f}\n"
        f"Acceptance limit: {D4_RESIDUAL_MAX}\n\n"
        f"VISUAL CHECK\n"
        f"White shows magenta/green alignment.\n"
        f"The chosen option should have the\n"
        f"strongest overlap.",
        transform=evidence_ax.transAxes,
        ha="left",
        va="top",
        fontsize=11.5,
        linespacing=1.35,
        color="#25302C",
    )

    gallery_heading = fig.add_subplot(grid[1])
    gallery_heading.set_axis_off()
    gallery_heading.text(
        0.5,
        0.5,
        "All eight candidates | magenta = home | green = aligned +X/+Y frames | "
        "white = overlap | chosen option highlighted",
        ha="center",
        va="center",
        fontsize=10.5,
        fontweight="bold",
        color="#30363D",
    )

    gallery_stride = max(1, int(np.ceil(max(session.images["home"].shape) / 384)))
    gallery_home = session.images["home"][::gallery_stride, ::gallery_stride]
    gallery_plus_x = session.images["plus_x"][::gallery_stride, ::gallery_stride]
    gallery_plus_y = session.images["plus_y"][::gallery_stride, ::gallery_stride]
    gallery_pixel_size_um = session.pixel_size_um * gallery_stride

    def _draw_candidate(
        ax,
        orientation: Orientation,
        *,
        selected: bool,
        show_details: bool = True,
    ) -> None:
        border_color = selected_color if selected else "#A8ADB3"
        border_width = 5.0 if selected else 1.2
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
        reflection_tag = _reflection_tag(orientation)
        signs = orientation.axis_signs
        title = f"Rotation {orientation.rotate_deg} deg | {reflection_tag}"
        if not show_details:
            word = "Detected" if accepted else "Nearest (rejected)"
            title = f"{word}: {orientation.rotate_deg} deg CW | {reflection_tag}"
        ax.set_title(
            title,
            color=selected_color if selected else "#252A30",
            fontweight="bold" if selected else "normal",
            fontsize=11 if selected else 10,
            pad=5,
        )
        if show_details:
            ax.set_xlabel(
                f"Map {_mapping_label(orientation)} | "
                f"X{_sign_label(signs['stage_x'])} / Y{_sign_label(signs['stage_y'])}\n"
                f"Net reflection: {_reflection_label(orientation)}\n"
                f"Apply: {_correction_label(orientation)}",
                color=selected_color if selected else "#4A5057",
                fontweight="bold" if selected else "normal",
                fontsize=9.5 if selected else 9,
                labelpad=6,
            )
        if selected:
            ax.text(
                0.5,
                0.98,
                "DETECTED - BEST OVERLAP" if accepted else "NEAREST - REJECTED",
                transform=ax.transAxes,
                ha="center",
                va="top",
                color="white",
                fontsize=9,
                fontweight="bold",
                bbox={"facecolor": selected_color, "edgecolor": "none", "pad": 4},
            )

    winner_ax = fig.add_subplot(summary_grid[0, 0:4])
    _draw_candidate(winner_ax, candidate, selected=True, show_details=False)

    gallery_slots = tuple((row, column) for row in range(2) for column in range(4))
    for orientation, (row, column) in zip(_gallery_orientations(), gallery_slots, strict=True):
        _draw_candidate(
            fig.add_subplot(gallery_grid[row, column]),
            orientation,
            selected=orientation == candidate,
        )

    fig.suptitle(
        f"Orientation measurement | {session.reference_objective} | "
        f"stage step {session.stage_move_um:g} um",
        fontsize=14,
    )
    output = session.paths.reports_dir / DIAGNOSTIC_NAME
    fig.savefig(output, dpi=160)
    return output


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
        # Weak vote: D4 is never evaluated. Leave d4_accepted=None, but still
        # write the report JSON — a failed run should be as reviewable from
        # disk as a rejected one, not vanish with the notebook output.
        session.failure_reason = "voting registration not trusted"
        write_json_atomic(
            session.paths.reports_dir / "orientation_report.json",
            {
                "schema_version": STAGING_SCHEMA_VERSION,
                "kind": "orientation_report",
                "created_at": now_iso(),
                "reference_objective": session.reference_objective,
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
            "schema_version": STAGING_SCHEMA_VERSION,
            "kind": "orientation_report",
            "created_at": now_iso(),
            "reference_objective": session.reference_objective,
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
