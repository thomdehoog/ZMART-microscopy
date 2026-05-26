"""Workflow: measure the rig's image_to_stage orientation matrix.

Acquires three frames under the reference objective (home, +X, +Y),
runs voting registration on each pair, fits a 2x2 stage_to_image
Jacobian and snaps it to the nearest D4 element. Writes a diagnostic
report unconditionally; writes a promotable staging config only when
both votes are trusted AND the D4 fit is within tolerance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

import navigator_expert.driver as drv
from algorithms import (
    D4_RESIDUAL_MAX,
    VOTING_METHODS,
    classify_d4,
    register_voting,
)

from .common import (
    SCHEMA_VERSION,
    SessionPaths,
    acquire_frame_to,
    assert_geometry_matches,
    make_session_paths,
    move_xy_and_verify,
    now_iso,
    plot_d4_candidates,
    plot_overlay,
    plot_raw_triplet,
    read_job_geometry,
    write_json_atomic,
)


KIND = "image_to_stage"
_STAGING_NAME = "image_to_stage.json"
_PER_STEP_IMAGES = ("home", "plus_x", "plus_y")


def _invalidate_staging_config(session: "ImageToStageSession") -> None:
    """Unlink the staging config and reset config_written.

    Mirrors objective_pair._invalidate_staging_config so a mid-measure
    failure cannot leave the previous run's matrix on disk.
    """
    out = session.paths.configs_dir / _STAGING_NAME
    if out.exists():
        out.unlink()
    session.config_written = False


@dataclass
class ImageToStageSession:
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
    fitted_image_to_stage: list[list[float]] | None = None
    image_to_stage: list[list[float]] | None = None
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
) -> ImageToStageSession:
    if stage_move_um <= 0:
        raise ValueError(f"stage_move_um must be > 0, got {stage_move_um}")

    # Create the session directory tree BEFORE any driver call so an
    # invalid sessions_root fails before the rig is touched.
    paths = make_session_paths(session_id, KIND, sessions_root)

    client = drv.connect_python_client()
    stage_cfg = drv.load_stage_config()
    drv.apply_stage_limits_from_config(stage_cfg)
    hw = drv.get_hardware_info(client)
    if hw is None:
        raise RuntimeError("get_hardware_info returned None; LAS X unreachable")

    return ImageToStageSession(
        session_id=session_id,
        paths=paths,
        job_name=job_name,
        client=client,
        stage_cfg=stage_cfg,
        reference_objective=reference_objective,
        stage_move_um=float(stage_move_um),
        settle_s=float(settle_s),
    )


def _acquire_and_validate(
    session: ImageToStageSession,
    name: str,
    *,
    expected_size_px: tuple[int, int] | None,
    expected_pixel_size_um: float | None,
) -> np.ndarray:
    img = acquire_frame_to(session, name)
    session.images[name] = img
    geom = read_job_geometry(session.client, session.job_name, img)
    if expected_size_px is None or expected_pixel_size_um is None:
        session.image_size_px = tuple(geom.image_size_px)
        session.pixel_size_um = float(geom.pixel_size_um)
    else:
        assert_geometry_matches(
            geom, expected_size_px, expected_pixel_size_um,
            context=f"{name} image",
        )
    return img


def measure(session: ImageToStageSession) -> ImageToStageSession:
    # Reset transient measurement state so a rerun in the same session
    # cannot leak values from a previous attempt. save_and_visualize
    # mirrors the on-disk staging config to the new verdict.
    session.images.clear()
    session.raw_files.clear()
    session.exported_files.clear()
    session.registrations.clear()
    session.fitted_image_to_stage = None
    session.image_to_stage = None
    session.d4_label = None
    session.residual_from_d4 = None
    session.d4_accepted = None
    session.config_written = False
    session.failure_reason = None
    session.image_size_px = None
    session.pixel_size_um = None
    session.home_xy = None

    # Unlink stale staging config and per-step TIFFs BEFORE any driver
    # calls. If measure() then raises mid-execution, the previous run's
    # promotable artifact is already gone (Section 15 invariant) and
    # data_dir's TIFF set matches the new session state at every point.
    _invalidate_staging_config(session)
    for name in _PER_STEP_IMAGES:
        (session.paths.data_dir / f"{name}.tif").unlink(missing_ok=True)

    xy = drv.get_xy(session.client) or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    home_x, home_y = float(xy["x_um"]), float(xy["y_um"])
    session.home_xy = (home_x, home_y)

    try:
        img_home = _acquire_and_validate(
            session, "home",
            expected_size_px=None, expected_pixel_size_um=None,
        )
        expected_size = session.image_size_px
        expected_pixel = session.pixel_size_um

        move_xy_and_verify(
            session.client, home_x + session.stage_move_um, home_y,
            settle_s=session.settle_s,
        )
        img_plus_x = _acquire_and_validate(
            session, "plus_x",
            expected_size_px=expected_size,
            expected_pixel_size_um=expected_pixel,
        )

        move_xy_and_verify(
            session.client, home_x, home_y,
            settle_s=session.settle_s,
        )
        move_xy_and_verify(
            session.client, home_x, home_y + session.stage_move_um,
            settle_s=session.settle_s,
        )
        img_plus_y = _acquire_and_validate(
            session, "plus_y",
            expected_size_px=expected_size,
            expected_pixel_size_um=expected_pixel,
        )

        move_xy_and_verify(
            session.client, home_x, home_y,
            settle_s=session.settle_s,
        )
    except Exception:
        # Best-effort recovery: try to return to home so the rig is not
        # left at +X/+Y. Suppress recovery failures so the original
        # exception is what the caller sees.
        try:
            move_xy_and_verify(
                session.client, home_x, home_y,
                settle_s=session.settle_s,
            )
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
    M_stage_to_image = np.array([
        [vote_x["dx_um"] / stage_move, vote_y["dx_um"] / stage_move],
        [vote_x["dy_um"] / stage_move, vote_y["dy_um"] / stage_move],
    ])
    try:
        fitted = -np.linalg.inv(M_stage_to_image)
    except np.linalg.LinAlgError as exc:
        # Singular / non-invertible fit: D4 classification cannot be
        # completed. fitted_image_to_stage means -inv(M); since inv
        # never produced a result, leave it None. d4_accepted stays
        # None (distinct from "evaluated and rejected").
        session.failure_reason = (
            f"singular stage_to_image matrix ({exc}); "
            "collinear or zero voting shifts"
        )
        return session

    label, canonical, residual = classify_d4(fitted)
    session.fitted_image_to_stage = fitted.tolist()
    session.image_to_stage = np.asarray(canonical, dtype=float).tolist()
    session.d4_label = label
    session.residual_from_d4 = float(residual)

    # Reflection guard runs first so the rig-specific assumption that
    # was violated (reflection-free optical path) is named in the
    # failure_reason and surfaces in the Step 2 review before Step 3
    # ever runs. The 8-element D4 evaluation upstream is unchanged --
    # only the acceptance gate is tightened here.
    canonical_arr = np.asarray(canonical, dtype=float)
    det = float(np.linalg.det(canonical_arr))
    if det < 0.0:
        session.d4_accepted = False
        session.failure_reason = (
            "reflection candidate selected; this workflow assumes a "
            "reflection-free optical path"
        )
    elif residual > D4_RESIDUAL_MAX:
        session.d4_accepted = False
        session.failure_reason = (
            f"D4 residual {residual:.3f} > {D4_RESIDUAL_MAX}; "
            "drift, sparse texture, or too small a stage_move"
        )
    else:
        session.d4_accepted = True
    return session


def _f(v: Any) -> float | None:
    """Coerce to float; map None / NaN / inf to None for strict JSON."""
    if v is None:
        return None
    fv = float(v)
    if not math.isfinite(fv):
        return None
    return fv


def _registration_for_report(vote: dict) -> dict:
    return {
        "image_shift_um": [_f(vote.get("dx_um")), _f(vote.get("dy_um"))],
        "trusted": bool(vote.get("trusted", False)),
        "confidence": int(vote.get("confidence", 0)),
        "agreeing": list(vote.get("agreeing", [])),
    }


def _overlay_shift_for_vote(vote: dict) -> tuple[float, float] | None:
    dx = vote.get("dx_um")
    dy = vote.get("dy_um")
    if dx is None or dy is None:
        return None
    fx = _f(dx)
    fy = _f(dy)
    if fx is None or fy is None:
        return None
    return (fx, fy)


_GEOMETRY_FROM_ROTATION_LABEL: dict[str, str] = {
    "+X +Y": "identity",
    "-Y +X": "90 deg CCW rotation",
    "-X -Y": "180 deg rotation",
    "+Y -X": "90 deg CW rotation",
}


def _geometry_for_label(label: str | None, snapped) -> str:
    """Human-readable geometry tag for a D4 label and its snapped matrix.

    Reflections are tagged via the same determinant test the reflection
    guard uses upstream, so a rename of any label string would not
    silently leak a mirrored geometry into the operator summary.
    """
    if label is None or snapped is None:
        return "not evaluated"
    try:
        det = float(np.linalg.det(np.asarray(snapped, dtype=float)))
    except Exception:
        det = 0.0
    if det < 0.0:
        return "reflection"
    return _GEOMETRY_FROM_ROTATION_LABEL.get(label, "rotation")


def _operator_status_header(
    *, config_written: bool, failure_reason: str | None,
    trusted_x: bool, trusted_y: bool, d4_accepted: bool | None,
) -> str:
    if config_written:
        return "OK"
    if failure_reason and "reflection-free" in failure_reason:
        return "REFLECTION REJECTED"
    if failure_reason and "singular" in failure_reason:
        return "FAILED -- singular fit"
    if not (trusted_x and trusted_y):
        return "FAILED -- voting registration not trusted"
    if d4_accepted is False:
        return "FAILED -- D4 residual too high"
    if d4_accepted is None:
        return "FAILED -- D4 not evaluated"
    return "FAILED"


def _print_text_summary(
    session: "ImageToStageSession",
    *,
    config_path: str | None,
) -> None:
    """Human-readable operator decision block.

    Internal helper. Always called from ``save_and_visualize`` after
    the report and (when accepted) staging config have been written.
    The full numerical state already lives in the report JSON and the
    returned summary dict; this block is the at-the-rig go/no-go view.
    """
    vote_x = session.registrations.get("home_to_plus_x", {})
    vote_y = session.registrations.get("home_to_plus_y", {})
    trusted_x = bool(vote_x.get("trusted", False))
    trusted_y = bool(vote_y.get("trusted", False))
    config_written = bool(session.config_written)
    n_methods = len(VOTING_METHODS)

    header = _operator_status_header(
        config_written=config_written,
        failure_reason=session.failure_reason,
        trusted_x=trusted_x, trusted_y=trusted_y,
        d4_accepted=session.d4_accepted,
    )

    conf_x = int(vote_x.get("confidence", 0))
    conf_y = int(vote_y.get("confidence", 0))
    state_x = "trusted" if trusted_x else "untrusted"
    state_y = "trusted" if trusted_y else "untrusted"

    geometry = _geometry_for_label(session.d4_label, session.image_to_stage)
    if session.d4_label is None:
        orientation_line = "not evaluated"
    else:
        orientation_line = f"{session.d4_label}  ({geometry})"

    print(f"Image-to-stage calibration: {header}")
    print()
    print(f"  Reference objective:  {session.reference_objective}")
    print(f"  Stage move:           {float(session.stage_move_um):.1f} um")
    print(
        f"  Voting:               "
        f"+X {state_x} ({conf_x}/{n_methods}),  "
        f"+Y {state_y} ({conf_y}/{n_methods})"
    )
    orientation_label_field = (
        "Orientation winner:  " if config_written else "Orientation:         "
    )
    print(f"  {orientation_label_field} {orientation_line}")
    if session.residual_from_d4 is not None:
        print(
            f"  D4 residual:          "
            f"{float(session.residual_from_d4):.2f} um  "
            f"(threshold {float(D4_RESIDUAL_MAX):.2f} um)"
        )
    print()
    if config_written:
        print("  Staging config written:")
        print(f"    {config_path}")
        print()
        print("  Run the promote cell below to copy this to the live config.")
    else:
        print("  No staging config written.")
        if session.failure_reason:
            print(f"  Reason: {session.failure_reason}")


def save_and_visualize(session: ImageToStageSession) -> dict:
    try:
        from IPython.display import display
    except Exception:
        display = None
    try:
        import matplotlib.pyplot as _plt
    except Exception:
        _plt = None

    vote_x = session.registrations.get("home_to_plus_x", {})
    vote_y = session.registrations.get("home_to_plus_y", {})

    home = session.images.get("home")
    plus_x = session.images.get("plus_x")
    plus_y = session.images.get("plus_y")

    # Build the same figures Step 2 displayed, save them as PNG
    # diagnostics under reports/, then display inline. The session
    # dataclass does not cache Figure objects.
    figure_records: list[tuple[str, str, object]] = []

    def _save_and_register(key: str, filename: str, fig) -> None:
        # Fail loud. A silent PNG omission would let Step 3 write the
        # report and (on the success path) the staging config while
        # quietly skipping the diagnostic that justifies the verdict.
        out_png = session.paths.reports_dir / filename
        try:
            fig.savefig(out_png, dpi=120)
        except Exception as exc:
            raise RuntimeError(
                f"failed to write diagnostic PNG {out_png}: {exc}"
            ) from exc
        # Report `figures:` paths stay session-root-relative.
        rel = str(
            out_png.relative_to(session.paths.session_dir)
        ).replace("\\", "/")
        figure_records.append((key, rel, fig))

    if home is not None and plus_x is not None and plus_y is not None:
        _save_and_register(
            "raw_triplet",
            "image_to_stage_raw_triplet.png",
            plot_raw_triplet(
                home, plus_x, plus_y,
                title="image_to_stage raw triplet",
            ),
        )
    if home is not None and plus_x is not None:
        _save_and_register(
            "overlay_home_plus_x",
            "image_to_stage_overlay_home_plus_x.png",
            plot_overlay(
                home, plus_x,
                "image_to_stage: home vs. +X",
                shift_um=_overlay_shift_for_vote(vote_x),
                pixel_size_um=session.pixel_size_um,
            ),
        )
    if home is not None and plus_y is not None:
        _save_and_register(
            "overlay_home_plus_y",
            "image_to_stage_overlay_home_plus_y.png",
            plot_overlay(
                home, plus_y,
                "image_to_stage: home vs. +Y",
                shift_um=_overlay_shift_for_vote(vote_y),
                pixel_size_um=session.pixel_size_um,
            ),
        )
    if (home is not None and plus_x is not None and plus_y is not None
            and session.pixel_size_um is not None):
        _save_and_register(
            "d4_candidates",
            "image_to_stage_d4_candidates.png",
            plot_d4_candidates(
                home, plus_x, plus_y,
                stage_move_um=float(session.stage_move_um),
                pixel_size_um=float(session.pixel_size_um),
                measured_plus_x_um=(vote_x.get("dx_um"), vote_x.get("dy_um")),
                measured_plus_y_um=(vote_y.get("dx_um"), vote_y.get("dy_um")),
                selected_label=session.d4_label,
                d4_accepted=session.d4_accepted,
                failure_reason=session.failure_reason,
            ),
        )

    # Inline display matches Step 2: only the D4 grid + the text
    # summary. Raw triplet and overlay PNGs were just saved and now
    # close without display() so the operator's notebook output stays
    # focused on the candidate grid.
    if display is not None:
        for key, _, fig in figure_records:
            if key == "d4_candidates":
                display(fig)
    if _plt is not None:
        for _, _, fig in figure_records:
            _plt.close(fig)

    figures_block = {key: rel for key, rel, _ in figure_records}

    trusted_x = bool(vote_x.get("trusted", False))
    trusted_y = bool(vote_y.get("trusted", False))
    # Three-state d4_accepted: True (evaluated, ok), False (evaluated,
    # rejected), None (never evaluated -- weak vote or singular fit).
    d4_accepted = session.d4_accepted
    config_written = trusted_x and trusted_y and (d4_accepted is True)

    config_path: str | None = None
    out = session.paths.configs_dir / _STAGING_NAME
    if config_written:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "created_at": now_iso(),
            "reference_objective": session.reference_objective,
            "image_size_px": [int(session.image_size_px[0]),
                              int(session.image_size_px[1])],
            "pixel_size_um": float(session.pixel_size_um),
            "image_to_stage": session.image_to_stage,
        }
        write_json_atomic(out, payload)
        # Absolute path: sessions_root is operator-supplied and may live
        # anywhere; an absolute string is unambiguous in operator output.
        config_path = str(out)
        session.config_written = True
    else:
        # Defense-in-depth: measure() already unlinks at its top, but
        # mirror the verdict here too so the contract holds even if a
        # future caller skips measure() and calls save_and_visualize
        # directly.
        _invalidate_staging_config(session)

    # Compute the verdict text BEFORE the report write so the saved
    # report carries the same status the operator sees in the summary
    # dict and in the printed text block. This is the audit trail for
    # rejections (reflection, residual, weak vote, singular fit) --
    # without it, a future reader of the report can see config_written
    # == false but cannot tell why.
    if config_written:
        status = "OK -- staging config written"
    elif not (trusted_x and trusted_y):
        status = "WEAK VOTE -- report only, no staging config"
    elif (session.failure_reason
            and "reflection-free" in session.failure_reason):
        status = "REFLECTION REJECTED -- report only, no staging config"
    elif d4_accepted is False:
        status = "D4 RESIDUAL TOO HIGH -- report only, no staging config"
    elif d4_accepted is None:
        status = "D4 NOT EVALUATED -- report only, no staging config"
    else:
        status = "NOT WRITTEN -- report only"
    if session.failure_reason and not config_written:
        status = f"{status} ({session.failure_reason})"

    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "image_to_stage_report",
        "created_at": now_iso(),
        "calibration_file": "image_to_stage.json",
        "config_written": config_written,
        "status": status,
        "failure_reason": session.failure_reason,
        "d4_accepted": d4_accepted,
        "stage_move_um": float(session.stage_move_um),
        "image_size_px": (
            [int(session.image_size_px[0]), int(session.image_size_px[1])]
            if session.image_size_px is not None else None
        ),
        "pixel_size_um": (
            float(session.pixel_size_um)
            if session.pixel_size_um is not None else None
        ),
        "images": {k: session.raw_files[k] for k in session.raw_files},
        "registrations": {
            "home_to_plus_x": _registration_for_report(vote_x),
            "home_to_plus_y": _registration_for_report(vote_y),
        },
        "d4_label": session.d4_label,
        "fitted_image_to_stage": session.fitted_image_to_stage,
        "image_to_stage": session.image_to_stage,
        "residual_from_d4": session.residual_from_d4,
        "figures": figures_block,
    }
    report_out = session.paths.reports_dir / "image_to_stage_report.json"
    write_json_atomic(report_out, report)

    # Operator-facing decision block: header + voting + orientation +
    # residual + the absolute path of the staging config (when written)
    # or the failure reason (when not).
    _print_text_summary(session, config_path=config_path)

    return {
        "config_written": config_written,
        "config_path": config_path,
        "report_path": str(report_out),
        "d4_label": session.d4_label,
        "d4_accepted": d4_accepted,
        "residual_from_d4": session.residual_from_d4,
        "voting": {
            "home_to_plus_x": {
                "trusted": trusted_x,
                "confidence": int(vote_x.get("confidence", 0)),
            },
            "home_to_plus_y": {
                "trusted": trusted_y,
                "confidence": int(vote_y.get("confidence", 0)),
            },
        },
        "status": status,
    }
