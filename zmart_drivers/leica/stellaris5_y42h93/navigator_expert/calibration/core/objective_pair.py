"""Workflow: measure the translation between one objective pair.

Z translation is peak-to-peak between Brenner-fitted reference and
target focus stacks. The operator configures z-stack range / step /
sections in LAS X; this workflow only triggers acquisition and
analyzes what comes back. See CALIBRATION_REF_STACK_UPDATE_PLAN.md.

Five operator steps, each one workflow call:

1. ``start_session`` -- connect, load current ``calibration.json``,
   prepare folders.
2. ``measure_parfocality_reference`` -- under the reference objective,
   record home XY and home z-wide (diagnostic), trigger the configured
   reference z-stack, fit the Brenner peak ``focus_z_ref_um``. The
   workflow only *notes* the peak — it does not move z-wide; the
   operator manages z-wide manually until step 4.
3. ``measure_parfocality_target`` -- after the operator switches to
   the target objective, record ``z_post`` then trigger the configured
   target z-stack, fit ``focus_z_target_um``, compute
   ``translation_z_um = focus_z_target_um - focus_z_ref_um``. As in
   step 2, z-wide is not moved here.
4. ``measure_parcentricity_reference`` -- back at the reference
   objective: return to home XY + ``focus_z_ref_um`` and acquire a
   clean reference image.
5. ``measure_parcentricity_target_and_save`` -- after the operator
   switches to the target objective again, acquire at the post-switch
   XY (no return to home XY), register against the reference image,
   compute ``motor_shift_xy`` / ``correction_xy`` / ``translation_xy``,
   write report unconditionally, write an adoptable staging config
   only when the registration vote is trusted, and unlink any stale
   staging config when the verdict is negative.

The notebook owns the operator-facing markdown and one workflow call
per cell. This module owns LAS X I/O, schema construction, and
visualization.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

import navigator_expert as drv
from shared.algorithms import VOTING_METHODS, brenner, register_voting

from . import model as calib
from .common import (
    STAGING_SCHEMA_VERSION,
    SessionPaths,
    acquire_frame_to,
    acquire_stack_to,
    make_session_paths,
    move_xy_and_verify,
    move_zwide_and_verify,
    now_iso,
    plot_brenner_curve,
    plot_overlay,
    read_job_geometry,
    read_stack_z_positions,
    slug,
    write_json_atomic,
    zero_z_galvo,
)


@dataclass
class ObjectivePairSession:
    session_id: str
    paths: SessionPaths
    job_name: str
    client: Any
    stage_cfg: dict
    from_objective: str
    to_objective: str
    objective_config_name: str
    calibration_path: Path
    image_to_stage: np.ndarray
    kind: str
    # Recorded when the reference XY image is acquired (Step 4). The
    # target XY image (Step 5) must match this pixel size so voting
    # registration sees the same scale on both sides. image_to_stage
    # itself is dimensionless -- it carries only the X/Y sign, not the
    # rig's pixel size or image format.
    ref_xy_pixel_size_um: float | None = None
    home_xy: tuple[float, float] | None = None
    home_z: float | None = None
    z_post: float | None = None
    # Reference focus is the Brenner peak of the operator-configured
    # reference z-stack; home_z is recorded for diagnostics only.
    focus_z_ref_um: float | None = None
    focus_z_target_um: float | None = None
    xy_post: tuple[float, float] | None = None
    ref_image: np.ndarray | None = None
    target_image: np.ndarray | None = None
    ref_z_stack: np.ndarray | None = None
    ref_z_positions_um: list[float] | None = None
    ref_z_brenner: list[float] | None = None
    target_z_stack: np.ndarray | None = None
    target_z_positions_um: list[float] | None = None
    target_z_brenner: list[float] | None = None
    raw_files: dict[str, str] = field(default_factory=dict)
    exported_files: dict[str, str] = field(default_factory=dict)
    motor_shift_xy_um: tuple[float, float] | None = None
    motor_shift_z_um: float | None = None
    correction_xy_um: tuple[float, float] | None = None
    correction_z_um: float | None = None
    translation_xy_um: tuple[float, float] | None = None
    translation_z_um: float | None = None
    registration: dict | None = None
    config_written: bool = False
    failure_reason: str | None = None


# ---------------------------------------------------------------------
# start_session
# ---------------------------------------------------------------------


def _load_image_to_stage(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"calibration not found at {path}. Run "
            "calibrate_image_to_stage.ipynb first and adopt, or pass an "
            "explicit calibration path."
        )
    config = calib.load_calibration(path)
    return {"image_to_stage": calib.get_image_to_stage(config)}


def start_session(
    *,
    session_id: str,
    job_name: str,
    from_objective: str,
    to_objective: str,
    sessions_root: str | Path,
    calibration_path: str | Path,
) -> ObjectivePairSession:
    kind = f"objective_{slug(from_objective)}_to_{slug(to_objective)}"
    objective_config_name = f"{kind}.json"

    # Create the session directory tree BEFORE loading the current config
    # or touching the driver, so an invalid sessions_root surfaces as a
    # single clear setup error before any hardware interaction.
    paths = make_session_paths(session_id, kind, sessions_root)

    # absolute(), not resolve(): keep the operator's drive letter intact
    # for the report's source_calibration_file field.
    resolved_path = Path(calibration_path).absolute()
    i2s = _load_image_to_stage(resolved_path)

    client = drv.connect_python_client()
    stage_cfg = drv.load_stage_config(limits_path=drv.default_stage_limits_path())
    drv.apply_stage_limits_from_config(stage_cfg)
    hw = drv.get_hardware_info(client, mode="api")
    if hw is None:
        raise RuntimeError("get_hardware_info returned None; LAS X unreachable")

    return ObjectivePairSession(
        session_id=session_id,
        paths=paths,
        job_name=job_name,
        client=client,
        stage_cfg=stage_cfg,
        from_objective=from_objective,
        to_objective=to_objective,
        objective_config_name=objective_config_name,
        calibration_path=resolved_path,
        image_to_stage=np.asarray(i2s["image_to_stage"], dtype=float),
        kind=kind,
    )


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _f(v: Any) -> float | None:
    """Coerce to float; map None / NaN / inf to None for strict JSON."""
    if v is None:
        return None
    fv = float(v)
    if not math.isfinite(fv):
        return None
    return fv


def _registration_for_report(vote: dict | None) -> dict | None:
    if vote is None:
        return None
    return {
        "image_shift_um": [_f(vote.get("dx_um")), _f(vote.get("dy_um"))],
        "trusted": bool(vote.get("trusted", False)),
        "confidence": int(vote.get("confidence", 0)),
        "agreeing": list(vote.get("agreeing", [])),
    }


# Stack edge slices are less reliable for focus fitting than interior
# slices. On LAS X stacks, slice 0 can arrive before its file is fully
# stable, and either edge can dominate the Brenner score without
# representing the true focal plane. Parfocality analysis therefore fits
# only the interior slices. The full stack and scores stay on the
# session so edge artifacts remain visible in reports.
_STACK_LEADING_SLICES_TO_SKIP = 1
_STACK_TRAILING_SLICES_TO_SKIP = 1
_MIN_FIT_SAMPLES = 3
_MIN_STACK_SECTIONS_FOR_FOCUS_FIT = (
    _STACK_LEADING_SLICES_TO_SKIP + _STACK_TRAILING_SLICES_TO_SKIP + _MIN_FIT_SAMPLES
)


def _uniform_z_step_um(z_values: np.ndarray) -> float:
    if len(z_values) < 2:
        raise RuntimeError(
            "z-stack focus fitting requires at least "
            f"{_MIN_STACK_SECTIONS_FOR_FOCUS_FIT} sections; got "
            f"{len(z_values)}."
        )
    steps = np.diff(z_values)
    if not np.allclose(steps, steps[0], rtol=1e-6, atol=1e-6):
        raise RuntimeError(
            "z-stack positions are not uniformly spaced; cannot apply "
            "parabolic focus fitting. Re-check the LAS X z-stack setup."
        )
    return float(steps[0])


def _fit_focus_z(z_values: np.ndarray, scores: list[float]) -> float:
    if len(z_values) != len(scores):
        raise RuntimeError(
            f"z-stack position count ({len(z_values)}) does not match "
            f"Brenner score count ({len(scores)})."
        )
    if len(z_values) < _MIN_STACK_SECTIONS_FOR_FOCUS_FIT:
        raise RuntimeError(
            "z-stack focus fitting requires at least "
            f"{_MIN_STACK_SECTIONS_FOR_FOCUS_FIT} sections because the "
            "workflow drops the first and last slices before fitting."
        )

    step = _uniform_z_step_um(z_values)
    lead = _STACK_LEADING_SLICES_TO_SKIP
    trail = _STACK_TRAILING_SLICES_TO_SKIP
    end = len(z_values) - trail
    return _parabolic_peak(z_values[lead:end], scores[lead:end], step)


def _parabolic_peak(z_values: np.ndarray, scores: list[float], z_step_um: float) -> float:
    i_peak = int(np.argmax(scores))
    n = len(z_values)
    if i_peak == 0 or i_peak == n - 1:
        # The operator configures the z-stack around the focal plane, so a
        # valid Brenner peak must be inside the stack. An edge peak means
        # either the first/last slice is an outlier (sensor artifact,
        # partially-written file, stale data) or the stack is not centered
        # on the focal plane. Either way the recorded focus would be wrong;
        # surface the failure rather than silently using a bogus value.
        raise RuntimeError(
            f"Brenner peak found at stack edge (slice {i_peak} of {n}, "
            f"z={float(z_values[i_peak])} um). The peak must be inside the "
            "stack. Likely causes: an artifact slice (often slice 0), or the "
            "stack is not centered on the focal plane. Refocus and re-run."
        )
    s0, s1, s2 = scores[i_peak - 1], scores[i_peak], scores[i_peak + 1]
    denom = s0 - 2.0 * s1 + s2
    if abs(denom) > 1e-12:
        delta = 0.5 * (s0 - s2) / denom
        return float(z_values[i_peak] + delta * z_step_um)
    return float(z_values[i_peak])


def _print_step5_summary(session, summary: dict) -> None:
    """Human-readable operator decision block for the final cell."""
    reg = summary.get("registration") or {}
    trusted = bool(reg.get("trusted"))
    confidence = int(reg.get("confidence", 0))
    shift = reg.get("image_shift_um") or [None, None]
    status = summary.get("status") or ("OK" if summary.get("config_written") else "FAILED")
    # Strip the appended reason: keep the status header short.
    header = status.split(" (", 1)[0]

    print(f"Objective pair calibration: {header}")
    print()
    print(f"  Pair:           {session.from_objective} -> {session.to_objective}")
    state = "trusted" if trusted else "untrusted"
    print(f"  Voting:         {state} ({confidence}/{len(VOTING_METHODS)})")
    if trusted and shift[0] is not None and shift[1] is not None:
        print(f"  Image shift:    ({shift[0]:+.2f}, {shift[1]:+.2f}) um")
    tx = summary.get("translation_xy_um")
    tz = summary.get("translation_z_um")
    if tx is not None and tx[0] is not None and tx[1] is not None:
        print(f"  Translation XY: ({tx[0]:+.2f}, {tx[1]:+.2f}) um")
    if tz is not None:
        print(f"  Translation Z:  {tz:+.2f} um")
    print()
    if summary.get("config_written"):
        print("  Staging config written:")
        print(f"    {summary.get('config_path')}")
        print()
        print("  Run the adopt cell below to copy this to the current config.")
    else:
        print("  No staging config written.")
        if session.failure_reason:
            print(f"  Reason: {session.failure_reason}")


# ---------------------------------------------------------------------
# Invalidation helpers
# ---------------------------------------------------------------------
#
# Every upstream rerun in a multi-step pipeline must invalidate the
# staging config and clear every downstream step that depended on what
# the rerun changed. Otherwise a stale adoptable config can survive a
# rerun (plan Section 15 invariant). Each helper clears one cell's
# outputs; each measure_* composes the helpers it needs.


def _invalidate_staging_config(session: ObjectivePairSession) -> None:
    out = session.paths.configs_dir / session.objective_config_name
    if out.exists():
        out.unlink()
    session.config_written = False


def _clear_parcentricity_target(session: ObjectivePairSession) -> None:
    session.xy_post = None
    session.target_image = None
    session.motor_shift_xy_um = None
    session.correction_xy_um = None
    session.translation_xy_um = None
    session.registration = None
    session.failure_reason = None
    session.raw_files.pop("target_xy", None)
    session.exported_files.pop("target_xy", None)
    # Keep disk state in sync with the session bookkeeping.
    (session.paths.data_dir / "target_xy.tif").unlink(missing_ok=True)


def _clear_parfocality_target(
    session: ObjectivePairSession,
    *,
    wipe_disk: bool,
) -> None:
    session.z_post = None
    session.focus_z_target_um = None
    session.target_z_stack = None
    session.target_z_positions_um = None
    session.target_z_brenner = None
    session.motor_shift_z_um = None
    session.correction_z_um = None
    session.translation_z_um = None
    for key in list(session.raw_files):
        if key.startswith("target_z_stack/"):
            del session.raw_files[key]
    for key in list(session.exported_files):
        if key.startswith("target_z_stack/"):
            del session.exported_files[key]
    if wipe_disk:
        # The session folder is staging for the current measurement,
        # not an archive of every rerun. A smaller z-range rerun would
        # otherwise leave higher-index TIFFs from the previous run.
        shutil.rmtree(
            session.paths.data_dir / "target_z_stack",
            ignore_errors=True,
        )


def _clear_parcentricity_ref(session: ObjectivePairSession) -> None:
    session.ref_image = None
    session.ref_xy_pixel_size_um = None
    session.raw_files.pop("ref_xy", None)
    session.exported_files.pop("ref_xy", None)
    (session.paths.data_dir / "ref_xy.tif").unlink(missing_ok=True)


def _clear_parfocality_reference(
    session: ObjectivePairSession,
    *,
    wipe_disk: bool,
) -> None:
    session.ref_z_stack = None
    session.ref_z_positions_um = None
    session.ref_z_brenner = None
    session.focus_z_ref_um = None
    for key in list(session.raw_files):
        if key.startswith("ref_z_stack/"):
            del session.raw_files[key]
    for key in list(session.exported_files):
        if key.startswith("ref_z_stack/"):
            del session.exported_files[key]
    if wipe_disk:
        shutil.rmtree(
            session.paths.data_dir / "ref_z_stack",
            ignore_errors=True,
        )


# ---------------------------------------------------------------------
# measure_parfocality_reference
# ---------------------------------------------------------------------


def measure_parfocality_reference(
    session: ObjectivePairSession,
    *,
    z_positions_um: list[float] | None = None,
) -> ObjectivePairSession:
    # A 2a rerun invalidates every downstream step: target parfocality
    # (its math anchors on focus_z_ref_um), parcentricity reference
    # (its image is acquired at focus_z_ref_um), and parcentricity
    # target (it depends on translation_z_um). The staging config --
    # if any -- is now stale.
    _clear_parfocality_reference(session, wipe_disk=True)
    _clear_parfocality_target(session, wipe_disk=True)
    _clear_parcentricity_ref(session)
    _clear_parcentricity_target(session)
    _invalidate_staging_config(session)
    session.home_xy = None
    session.home_z = None

    try:
        from IPython.display import display
    except Exception:
        display = None

    zero_z_galvo(session.client, session.job_name)
    xy = drv.get_xy(session.client, mode="api") or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    session.home_xy = (float(xy["x_um"]), float(xy["y_um"]))
    # home_z is diagnostic -- the operator's approximate focus before
    # the reference stack runs. focus_z_ref_um is the load-bearing
    # value, fitted below.
    session.home_z = float(drv.read_zwide_um(session.client, session.job_name))

    stack = acquire_stack_to(session, "ref_z_stack")
    session.ref_z_stack = stack

    positions = read_stack_z_positions(
        session.client,
        session.job_name,
        expected_slices=int(stack.shape[0]),
        override=z_positions_um,
    )
    session.ref_z_positions_um = positions

    scores = [float(brenner(stack[i])) for i in range(stack.shape[0])]
    if not all(math.isfinite(s) for s in scores):
        raise RuntimeError(
            "Brenner scores contain non-finite values; cannot fit focus "
            "peak. Likely cause: blank or corrupted slices in the z-stack. "
            "Re-check the LAS X stack configuration and channel intensity."
        )
    session.ref_z_brenner = scores

    z_arr = np.asarray(positions, dtype=float)
    focus_z = _fit_focus_z(z_arr, scores)
    session.focus_z_ref_um = focus_z

    # The workflow notes the Brenner peak but does not move z-wide.
    # The operator manages z-wide manually.

    fig = plot_brenner_curve(positions, scores, focus_z)
    if display is not None:
        display(fig)
    try:
        import matplotlib.pyplot as _plt

        _plt.close(fig)
    except Exception:
        pass

    print(f"Reference focus: z = {focus_z:.2f} um")
    print(
        f"  home xy = ({session.home_xy[0]:.1f}, {session.home_xy[1]:.1f}) um, "
        f"home z-wide = {session.home_z:.2f} um"
    )
    return session


# ---------------------------------------------------------------------
# measure_parfocality_target
# ---------------------------------------------------------------------


def measure_parfocality_target(
    session: ObjectivePairSession,
    *,
    z_positions_um: list[float] | None = None,
) -> ObjectivePairSession:
    if session.focus_z_ref_um is None:
        raise RuntimeError(
            "measure_parfocality_reference must run before measure_parfocality_target"
        )

    # A 2b rerun changes translation_z_um (which 3b uses to park
    # z-wide before the target acquire), so 3b's outputs are stale.
    # 3a's ref_image is still valid -- home_xy and focus_z_ref_um are
    # unchanged. Wipe the on-disk z-stack so a smaller rerun cannot
    # leave stale higher-index TIFFs in the directory the report
    # points at.
    _clear_parfocality_target(session, wipe_disk=True)
    _clear_parcentricity_target(session)
    _invalidate_staging_config(session)

    try:
        from IPython.display import display
    except Exception:
        display = None

    zero_z_galvo(session.client, session.job_name)
    z_post = float(drv.read_zwide_um(session.client, session.job_name))
    session.z_post = z_post
    # motor_shift_z = post-switch z-wide minus reference focus peak.
    session.motor_shift_z_um = z_post - session.focus_z_ref_um

    stack = acquire_stack_to(session, "target_z_stack")
    session.target_z_stack = stack

    positions = read_stack_z_positions(
        session.client,
        session.job_name,
        expected_slices=int(stack.shape[0]),
        override=z_positions_um,
    )
    session.target_z_positions_um = positions

    scores = [float(brenner(stack[i])) for i in range(stack.shape[0])]
    if not all(math.isfinite(s) for s in scores):
        raise RuntimeError(
            "Brenner scores contain non-finite values; cannot fit focus "
            "peak. Likely cause: blank or corrupted slices in the z-stack. "
            "Re-check the LAS X stack configuration and channel intensity."
        )
    session.target_z_brenner = scores

    z_arr = np.asarray(positions, dtype=float)
    focus_z = _fit_focus_z(z_arr, scores)
    session.focus_z_target_um = focus_z
    session.correction_z_um = focus_z - z_post
    # Peak-to-peak: translation_z_um = focus_target - focus_ref.
    # Equivalent to motor_shift_z + correction_z by construction.
    session.translation_z_um = focus_z - session.focus_z_ref_um

    # The workflow notes the Brenner peak but does not move z-wide.
    # The operator manages z-wide manually.

    fig = plot_brenner_curve(positions, scores, focus_z)
    if display is not None:
        display(fig)
    try:
        import matplotlib.pyplot as _plt

        _plt.close(fig)
    except Exception:
        pass

    print(f"Target focus: z = {focus_z:.2f} um")
    print(f"  z translation: {session.translation_z_um:+.2f} um  (target - reference)")
    print(f"    motor shift: {session.motor_shift_z_um:+.2f} um")
    print(f"    correction:  {session.correction_z_um:+.2f} um")
    return session


# ---------------------------------------------------------------------
# measure_parcentricity_reference
# ---------------------------------------------------------------------


def measure_parcentricity_reference(
    session: ObjectivePairSession,
) -> ObjectivePairSession:
    if session.home_xy is None or session.focus_z_ref_um is None:
        raise RuntimeError(
            "measure_parfocality_reference must run before measure_parcentricity_reference"
        )

    # A 3a rerun replaces ref_image, against which 3b registers. The
    # previous 3b vote, translation_xy, and staging config are all
    # stale.
    _clear_parcentricity_ref(session)
    _clear_parcentricity_target(session)
    _invalidate_staging_config(session)

    move_xy_and_verify(session.client, *session.home_xy)
    zero_z_galvo(session.client, session.job_name)
    # Park z-wide at the reference Brenner focus (measured in Step 2)
    # so the XY image is acquired at the best ref-objective focus.
    move_zwide_and_verify(
        session.client,
        session.job_name,
        session.focus_z_ref_um,
    )

    ref_image = acquire_frame_to(session, "ref_xy")
    session.ref_image = ref_image

    # Record the ref XY pixel size. The target XY (Step 5) must be
    # acquired at the same pixel size so voting registration sees the
    # same scale on both sides.
    geom = read_job_geometry(session.client, session.job_name, ref_image)
    session.ref_xy_pixel_size_um = float(geom.pixel_size_um)

    print(f"Reference XY image acquired.  pixel size = {session.ref_xy_pixel_size_um:.4f} um")
    return session


# ---------------------------------------------------------------------
# measure_parcentricity_target_and_save
# ---------------------------------------------------------------------


def measure_parcentricity_target_and_save(
    session: ObjectivePairSession,
) -> dict:
    if session.home_xy is None or session.focus_z_ref_um is None:
        raise RuntimeError(
            "measure_parfocality_reference must run before measure_parcentricity_target_and_save"
        )
    if session.ref_image is None:
        raise RuntimeError(
            "measure_parcentricity_reference must run before measure_parcentricity_target_and_save"
        )
    if session.focus_z_target_um is None or session.translation_z_um is None:
        raise RuntimeError(
            "measure_parfocality_target must run before measure_parcentricity_target_and_save"
        )

    # Reset this step's outputs.
    session.xy_post = None
    session.target_image = None
    session.motor_shift_xy_um = None
    session.correction_xy_um = None
    session.translation_xy_um = None
    session.registration = None
    session.config_written = False
    session.failure_reason = None
    session.raw_files.pop("target_xy", None)
    session.exported_files.pop("target_xy", None)
    (session.paths.data_dir / "target_xy.tif").unlink(missing_ok=True)

    # Unlink stale staging config BEFORE any driver call. 3b has nine
    # raisable call sites between here and the verdict-mirror block;
    # any of them firing on a rerun would otherwise leave the previous
    # run's objective config adoptable (Section 15 invariant).
    _invalidate_staging_config(session)

    try:
        from IPython.display import display
    except Exception:
        display = None

    xy = drv.get_xy(session.client, mode="api") or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    xy_post = (float(xy["x_um"]), float(xy["y_um"]))
    session.xy_post = xy_post
    session.motor_shift_xy_um = (
        xy_post[0] - session.home_xy[0],
        xy_post[1] - session.home_xy[1],
    )

    zero_z_galvo(session.client, session.job_name)
    # Park z-wide at the target Brenner focus (measured in Step 3) so
    # the XY image is acquired at the best target-objective focus.
    move_zwide_and_verify(
        session.client,
        session.job_name,
        session.focus_z_target_um,
    )

    # IMPORTANT: do NOT return to home_xy. We measure at the post-switch
    # XY so the registration captures only the residual the firmware
    # left behind.
    target_image = acquire_frame_to(session, "target_xy")
    session.target_image = target_image

    # Reference and target XY must be at the same scale so voting
    # registration sees identical magnification on both sides. The
    # workflow does NOT require either image to match image_to_stage's
    # pixel size -- image_to_stage carries only the X/Y sign.
    if tuple(target_image.shape[-2:]) != tuple(session.ref_image.shape[-2:]):
        raise ValueError(
            f"target XY image shape {target_image.shape[-2:]} does not "
            f"match reference shape {session.ref_image.shape[-2:]}. "
            "Reference and target XY must be acquired at the same image size."
        )
    geom = read_job_geometry(session.client, session.job_name, target_image)
    target_pixel_size = float(geom.pixel_size_um)
    if session.ref_xy_pixel_size_um is None or not np.isclose(
        target_pixel_size, session.ref_xy_pixel_size_um, rtol=0, atol=1e-9
    ):
        raise ValueError(
            f"target XY pixel size {target_pixel_size} um does not match "
            f"reference pixel size {session.ref_xy_pixel_size_um} um. "
            "Reference and target XY must be acquired at the same zoom."
        )
    pixel_size_um = session.ref_xy_pixel_size_um

    vote = register_voting(
        session.ref_image,
        target_image,
        pixel_size_um,
    )
    session.registration = vote

    config_written = False
    if vote.get("trusted"):
        image_shift = np.array(
            [float(vote["dx_um"]), float(vote["dy_um"])],
            dtype=float,
        )
        correction_xy = session.image_to_stage @ image_shift
        translation_xy = np.asarray(session.motor_shift_xy_um, dtype=float) + correction_xy
        session.correction_xy_um = (
            float(correction_xy[0]),
            float(correction_xy[1]),
        )
        session.translation_xy_um = (
            float(translation_xy[0]),
            float(translation_xy[1]),
        )
        config_written = True
    else:
        session.failure_reason = "voting registration not trusted"

    overlay_shift = (float(vote["dx_um"]), float(vote["dy_um"])) if vote.get("trusted") else None
    fig = plot_overlay(
        session.ref_image,
        target_image,
        f"objective {session.from_objective} -> {session.to_objective}: ref vs target XY",
        shift_um=overlay_shift,
        pixel_size_um=pixel_size_um,
    )
    if display is not None:
        display(fig)
    try:
        import matplotlib.pyplot as _plt

        _plt.close(fig)
    except Exception:
        pass

    # Mirror the verdict to disk.
    out = session.paths.configs_dir / session.objective_config_name
    config_path: str | None = None
    if config_written:
        payload = {
            "schema_version": STAGING_SCHEMA_VERSION,
            "kind": "objective_translation",
            "created_at": now_iso(),
            "from_objective": session.from_objective,
            "to_objective": session.to_objective,
            "translation_xy_um": list(session.translation_xy_um),
            "translation_z_um": float(session.translation_z_um),
        }
        write_json_atomic(out, payload)
        # Absolute path: sessions_root is operator-supplied and may live
        # anywhere; an absolute string is unambiguous in operator output.
        config_path = str(out)
        session.config_written = True
    else:
        if out.exists():
            out.unlink()
        session.config_written = False

    # Report -- always written, after every available field is populated.
    images = {}
    if "ref_xy" in session.raw_files:
        images["ref_xy"] = session.raw_files["ref_xy"]
    if "target_xy" in session.raw_files:
        images["target_xy"] = session.raw_files["target_xy"]
    # Both z-stacks are referenced as directories rather than
    # enumerating every slice in the report.
    for dirname in ("ref_z_stack", "target_z_stack"):
        z_dir = session.paths.data_dir / dirname
        if z_dir.exists():
            images[dirname] = (
                str(z_dir.relative_to(session.paths.session_dir)).replace("\\", "/") + "/"
            )

    # source_calibration_file: record the absolute source we actually
    # used (current config or override). The operator-supplied path may
    # live outside the package tree, so the absolute string is the only
    # form that round-trips meaningfully.
    source_calibration_file = str(session.calibration_path)

    report = {
        "schema_version": STAGING_SCHEMA_VERSION,
        "kind": "objective_translation_report",
        "created_at": now_iso(),
        "calibration_file": session.objective_config_name,
        "config_written": config_written,
        "source_calibration_file": source_calibration_file,
        "from_objective": session.from_objective,
        "to_objective": session.to_objective,
        "home_xy_um": [_f(session.home_xy[0]), _f(session.home_xy[1])],
        "home_z_um": _f(session.home_z),
        "focus_z_ref_um": _f(session.focus_z_ref_um),
        "xy_post_um": [_f(session.xy_post[0]), _f(session.xy_post[1])],
        "z_post_um": _f(session.z_post),
        "focus_z_target_um": _f(session.focus_z_target_um),
        "motor_shift_xy_um": [_f(session.motor_shift_xy_um[0]), _f(session.motor_shift_xy_um[1])],
        "motor_shift_z_um": _f(session.motor_shift_z_um),
        "correction_xy_um": (
            [_f(session.correction_xy_um[0]), _f(session.correction_xy_um[1])]
            if session.correction_xy_um is not None
            else None
        ),
        "correction_z_um": _f(session.correction_z_um),
        "translation_xy_um": (
            [_f(session.translation_xy_um[0]), _f(session.translation_xy_um[1])]
            if session.translation_xy_um is not None
            else None
        ),
        "translation_z_um": _f(session.translation_z_um),
        "registration": _registration_for_report(vote),
        "brenner_ref": {
            "peak_z_um": _f(session.focus_z_ref_um),
            "scores": [_f(s) for s in (session.ref_z_brenner or [])],
            "z_positions_um": [_f(z) for z in (session.ref_z_positions_um or [])],
        },
        "brenner_target": {
            "peak_z_um": _f(session.focus_z_target_um),
            "scores": [_f(s) for s in (session.target_z_brenner or [])],
            "z_positions_um": [_f(z) for z in (session.target_z_positions_um or [])],
        },
        "images": images,
    }
    report_out = session.paths.reports_dir / f"{session.kind}_report.json"
    write_json_atomic(report_out, report)

    if config_written:
        status = "OK -- staging config written"
    else:
        status = "WEAK VOTE -- report only, no staging config"
        if session.failure_reason:
            status = f"{status} ({session.failure_reason})"

    summary = {
        "config_written": config_written,
        "config_path": config_path,
        "report_path": str(report_out),
        "from_objective": session.from_objective,
        "to_objective": session.to_objective,
        "motor_shift_xy_um": [_f(session.motor_shift_xy_um[0]), _f(session.motor_shift_xy_um[1])],
        "motor_shift_z_um": _f(session.motor_shift_z_um),
        "correction_xy_um": (
            [_f(session.correction_xy_um[0]), _f(session.correction_xy_um[1])]
            if session.correction_xy_um is not None
            else None
        ),
        "correction_z_um": _f(session.correction_z_um),
        "translation_xy_um": (
            [_f(session.translation_xy_um[0]), _f(session.translation_xy_um[1])]
            if session.translation_xy_um is not None
            else None
        ),
        "translation_z_um": _f(session.translation_z_um),
        "focus_z_ref_um": _f(session.focus_z_ref_um),
        "focus_z_target_um": _f(session.focus_z_target_um),
        "registration": {
            "trusted": bool(vote.get("trusted", False)),
            "confidence": int(vote.get("confidence", 0)),
            "image_shift_um": [_f(vote.get("dx_um")), _f(vote.get("dy_um"))],
        },
        "status": status,
    }
    _print_step5_summary(session, summary)
    return summary
