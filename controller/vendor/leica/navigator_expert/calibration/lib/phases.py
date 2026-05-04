"""Phase functions for objective calibration.

Each phase takes a LAS X client + the state it needs and returns the
data the orchestrator persists. No phase mutates the machine config or
the run report directly — the orchestrator does that, so persistence
stays in one place.

Phase boundaries:

    1. measure_sign_convention      -- under reference objective only
    2. measure_parcentric_offset    -- per target, always runs
                                       (firmware get_xy delta on switch;
                                        diagnostic only)
    3. measure_parfocal_shift       -- per target, optional
                                       (focal-plane shift between objectives)
    4. measure_parcentric_shift     -- per target, optional
                                       (stage-frame XY shift from registration
                                        with stage parked at the same XY both
                                        times — the value the cookbook applies)
    5. verify_target                -- per target, optional
                                       (re-acquire at corrected XY+Z; reports
                                        the system's noise floor, ~2-3 µm)
"""

import logging
import time

import numpy as np

import navigator_expert.driver as drv
from .lasx_state import configure_z_stack, disable_z_stack
from .registration import (
    brenner_focus,
    classify_d4,
    register_phase,
    register_voting,
)


log = logging.getLogger(__name__)


# Above this Frobenius distance the fit is too far from a pure
# reflection/rotation to snap; usual cause is drift or sparse texture.
D4_RESIDUAL_MAX = 0.3


# ── Phase 1: sign convention ─────────────────────────────────────────

def _move_and_verify(client, x_um, y_um, *, settle_s, tolerance_um=0.5):
    r = drv.move_xy_stage(client, x_um, y_um, unit="um", tolerance=tolerance_um)
    if not r or not r.get("success"):
        raise RuntimeError(f"move_xy_stage to ({x_um:.3f}, {y_um:.3f}) failed: {r}")
    time.sleep(settle_s)
    xy = drv.get_xy(client)
    if abs(xy["x_um"] - x_um) > tolerance_um or abs(xy["y_um"] - y_um) > tolerance_um:
        raise RuntimeError(
            f"stage off target: requested ({x_um:.3f}, {y_um:.3f}), "
            f"readback ({xy['x_um']:.3f}, {xy['y_um']:.3f})"
        )


def measure_sign_convention(client, acquire_single, *,
                            pixel_size_um, move_um, settle_s):
    """Phase 1: image-to-stage Jacobian, snapped to nearest D4 element.

    Returns a dict with the canonical D4 matrix, the raw fit, and the
    Frobenius residual from D4. Raises if the fit is too far from D4.
    """
    start = drv.get_xy(client)
    x0, y0 = float(start["x_um"]), float(start["y_um"])
    log.info("sign phase: anchor=(%.3f, %.3f) um", x0, y0)

    img_ref = acquire_single()

    log.info("sign phase: +%.1f um in X", move_um)
    _move_and_verify(client, x0 + move_um, y0, settle_s=settle_s)
    img_x = acquire_single()
    dx_x, dy_x = register_phase(img_ref, img_x, pixel_size_um)
    log.info("  stage +X -> image (%+.3f, %+.3f) um", dx_x, dy_x)
    _move_and_verify(client, x0, y0, settle_s=settle_s)

    log.info("sign phase: +%.1f um in Y", move_um)
    _move_and_verify(client, x0, y0 + move_um, settle_s=settle_s)
    img_y = acquire_single()
    dx_y, dy_y = register_phase(img_ref, img_y, pixel_size_um)
    log.info("  stage +Y -> image (%+.3f, %+.3f) um", dx_y, dy_y)
    _move_and_verify(client, x0, y0, settle_s=settle_s)

    stage_to_image = np.array([
        [dx_x / move_um, dx_y / move_um],
        [dy_x / move_um, dy_y / move_um],
    ])
    image_to_stage_fitted = -np.linalg.inv(stage_to_image)
    label, canonical, residual = classify_d4(image_to_stage_fitted)
    log.info("sign fit: label=%s residual=%.3f", label, residual)
    if residual > D4_RESIDUAL_MAX:
        raise RuntimeError(
            f"sign-convention fit too far from D4 "
            f"(Frobenius residual {residual:.3f} > {D4_RESIDUAL_MAX}). "
            f"Likely cause: drift, sparse texture, or too small a sign-move."
        )
    return {
        "image_to_stage_um": canonical.tolist(),
        "label": label,
        "fitted_matrix": image_to_stage_fitted.tolist(),
        "residual_from_d4": residual,
        "move_um": float(move_um),
    }


# ── Phase 2: parcentric offset (firmware get_xy delta) ───────────────

def measure_parcentric_offset(client, home_xy):
    """Phase 2: ``get_xy`` delta induced by the firmware on objective switch.

    Caller must have already switched to the target objective. The stage
    will read back at ``home_xy + offset``.

    This is recorded for diagnostics (firmware behaviour over time). It
    is **not** part of the correction the cookbook applies — the
    cookbook commands an absolute XY after the switch, overwriting
    whatever the firmware did.

    Returns ``(offset_um, report_fragment)``.
    """
    target_xy = drv.get_xy(client)
    offset_um = [
        float(target_xy["x_um"] - home_xy[0]),
        float(target_xy["y_um"] - home_xy[1]),
    ]
    log.info("parcentric offset (firmware get_xy delta): (%+.3f, %+.3f) um",
             *offset_um)
    return offset_um, {"offset_um": list(offset_um)}


# ── Phase 3: parfocal Z ──────────────────────────────────────────────

def measure_parfocal(client, job, *, acquire_stack, ref_focus,
                     z_range_um, z_step_um):
    """Phase 3: focal-plane shift between target and reference objectives.

    The Brenner peak of slot 2's Z-stack at the post-switch z-wide
    position, minus slot 1's peak, gives the focal-plane offset the
    cookbook still needs to apply *after* whatever the firmware did
    with z-wide. Same shift/offset model as XY — except we can't
    observe the firmware's Z motion separately on this scope (no
    GetZ API), so the Brenner peak difference IS the shift the
    cookbook applies.

    ``ref_focus`` is the brenner_focus dict from the reference objective
    (acquired once by the orchestrator before the per-target loop).
    Caller must have already switched to the target objective. Returns
    ``(dz_um, report_fragment)``.

    No verification stack — for the same reason Phase 5 was dropped.
    A "residual" measured by re-acquiring at the corrected Z is just
    the noise floor of (Z stage repeatability + Brenner peak finder
    accuracy + sample stability). Doesn't validate calibration
    correctness.
    """
    log.info("phase 3: target Z-stack")
    configure_z_stack(client, job, half_range_um=z_range_um, step_um=z_step_um)
    tgt_stack = acquire_stack()
    tgt_focus = brenner_focus(tgt_stack, z_step_um)
    dz_um = float((tgt_focus["peak_sub"] - ref_focus["peak_sub"]) * z_step_um)
    log.info("parfocal shift dZ = %+.2f um", dz_um)

    return dz_um, {
        "ref_brenner_peak_um": ref_focus["peak_um"],
        "tgt_brenner_peak_um": tgt_focus["peak_um"],
        "shift_um": dz_um,
    }


# ── Phase 4: parcentric shift (registration at same stage XY) ────────

def measure_parcentric_shift(
    client, job, *,
    acquire_single, img_ref_focus,
    home_xy, dz_um, image_to_stage,
    ts_zoom, voting_min_agree, voting_method_count,
):
    """Phase 4: stage-frame XY shift between target and reference objectives.

    The clean measurement: caller has switched to the target objective
    (firmware moved the stage by some offset). We **move the stage back
    to ``home_xy``** so img_ref and img_tgt are acquired at the same
    stage XY, then register. The resulting shift is exactly
    ``c1 − c2`` — the optical-axis difference between the two
    objectives — with no firmware-shift contamination.

    Returns ``(shift_xy_or_None, report_fragment)``. ``shift_xy=None``
    means voting failed and the cookbook should not be given a
    correction for this slot.
    """
    log.info("phase 4: moving stage back to home before tgt acquire")
    r = drv.move_xy_stage(
        client, home_xy[0], home_xy[1],
        unit="um", tolerance=0.5,
    )
    if not r or not r.get("success"):
        raise RuntimeError(f"phase 4 move-back-to-home failed: {r}")
    time.sleep(1.0)

    tgt_z_galvo_um = -dz_um
    log.info("phase 4: target focus slice at z-galvo=%+.2f", tgt_z_galvo_um)
    disable_z_stack(client, job)
    drv.set_z_stack_definition(
        client, job,
        begin_um=tgt_z_galvo_um, end_um=tgt_z_galvo_um,
    )
    img_tgt_focus = acquire_single()

    tgt_geo = drv.parse_tile_geometry(drv.get_job_settings(client, job) or {})
    tgt_pixel_um = float(tgt_geo["pixel_w_um"])

    vote = register_voting(img_ref_focus, img_tgt_focus, tgt_pixel_um)
    raw_dx, raw_dy = vote["dx_um"], vote["dy_um"]
    log.info(
        "parcentric shift vote: agreeing=%s confidence=%d/%d trusted=%s quality=%.3f",
        vote["agreeing"], vote["confidence"], voting_method_count,
        vote["trusted"], vote["quality"],
    )
    log.info(
        "  per-method: %s",
        ", ".join(
            f"{n}=({m['dx_um']:+.2f},{m['dy_um']:+.2f})"
            for n, m in vote["per_method"].items()
            if m.get("dx_um") is not None and m.get("dy_um") is not None
        ),
    )

    if not vote["trusted"]:
        log.warning(
            "voting confidence too low (%d < %d agreeing methods); "
            "shift NOT recorded — re-run with more texture in the FOV.",
            vote["confidence"], voting_min_agree,
        )
        return None, {
            "skipped": True,
            "reason": "voting_low_confidence",
            "confidence": vote["confidence"],
            "per_method": vote["per_method"],
        }

    stage_dx = image_to_stage[0][0] * raw_dx + image_to_stage[0][1] * raw_dy
    stage_dy = image_to_stage[1][0] * raw_dx + image_to_stage[1][1] * raw_dy
    shift_xy = [float(stage_dx), float(stage_dy)]
    log.info(
        "parcentric shift: image=(%+.3f, %+.3f) um → stage=(%+.3f, %+.3f) um",
        raw_dx, raw_dy, stage_dx, stage_dy,
    )

    return shift_xy, {
        "raw_image_dx_um": float(raw_dx),
        "raw_image_dy_um": float(raw_dy),
        "shift_stage_um": list(shift_xy),
        "quality": vote["quality"],
        "confidence": vote["confidence"],
        "agreeing": vote["agreeing"],
        "trusted": vote["trusted"],
        "per_method": vote["per_method"],
        "method": "voting",
        "acquisition_zoom": ts_zoom,
        "acquisition_z_galvo_um": tgt_z_galvo_um,
    }


# Phase 5 (verification) deliberately removed.
#
# It used to acquire one more image at home + shift and register against
# img_ref, reporting the residual as a "calibration health check". But
# that residual is bounded below by the noise floor of (stage motor
# accuracy + settle + backlash takeup + registration accuracy +
# correlated sample drift between acquires), all of which are present
# during the Phase-4 measurement too. So Phase 5 cannot tell you whether
# the calibration is right — it can only tell you the noise floor of the
# overall rig.
#
# The honest end-to-end validation is the cookbook landing test, run
# on a different cell at a different stage XY than the calibration
# anchor. That's what catches real targeting errors.
