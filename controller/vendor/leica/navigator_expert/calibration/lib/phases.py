"""Phase functions for objective calibration.

Each phase takes a LAS X client + the state it needs and returns the
data the orchestrator persists. No phase mutates the machine config or
the run report directly — the orchestrator does that, so persistence
stays in one place.

Z model (entire calibration runs with z-galvo at 0):
    - The firmware applies the bulk parfocal correction by moving
      z-wide on objective switch. The orchestrator records that as
      ``offset_z_um`` (post-switch zwide minus pre-switch zwide).
    - ``measure_shift_z`` measures the residual the firmware leaves
      behind by scanning a Brenner stack on z-wide and recording where
      the peak lands. That residual is ``shift_z_um`` and is what the
      cookbook applies (also on z-wide via the API).

Phase boundaries (function names match the v9 schema fields):

    1. measure_sign_convention   -- under reference objective only
    2. measure_xy_firmware_delta -- per target, always runs
                                    (firmware ``get_xy`` delta on switch;
                                     diagnostic only)
    3. measure_shift_z           -- per target, optional
                                    (z-wide focus residual via Brenner;
                                     leaves z-wide parked at the peak)
    4. measure_shift_xy          -- per target, optional
                                    (stage-frame XY shift from voting
                                     registration with stage parked at the
                                     same XY both times — the value the
                                     cookbook applies)
"""

import logging
import time

import numpy as np

import navigator_expert.driver as drv
from navigator_expert.analysis import (
    D4_RESIDUAL_MAX,
    VOTING_METHODS,
    brenner_focus,
    classify_d4,
    register_phase,
    register_voting,
)

from .lasx_state import configure_z_stack, disable_z_stack


log = logging.getLogger(__name__)


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


# ── Phase 2: firmware XY delta on objective switch ───────────────────

def measure_xy_firmware_delta(client, home_xy):
    """Phase 2: ``get_xy`` delta induced by the firmware on objective switch.

    Caller must have already switched to the target objective. The stage
    will read back at ``home_xy + delta``.

    Recorded for diagnostics (firmware behaviour over time); it is
    **not** part of the correction the cookbook applies — the
    cookbook commands an absolute XY after the switch, overwriting
    whatever the firmware did.

    Returns ``(delta_um, report_fragment)``.
    """
    target_xy = drv.get_xy(client)
    delta_um = [
        float(target_xy["x_um"] - home_xy[0]),
        float(target_xy["y_um"] - home_xy[1]),
    ]
    log.info("firmware xy delta on switch: (%+.3f, %+.3f) um", *delta_um)
    return delta_um, {"delta_um": list(delta_um)}


# ── Phase 3: shift_z — z-wide focus residual ─────────────────────────

def measure_shift_z(client, job, *, acquire_stack,
                    z_range_um, z_step_um, zwide_post_switch_um):
    """Phase 3: focus residual on z-wide after the firmware's switch.

    The firmware moves z-wide on every objective switch (the
    "offset"). What it leaves behind is the residual this phase
    measures: a Brenner z-stack scanned on z-wide, centred at
    ``zwide_post_switch_um``. The peak gives the z-wide position
    that brings the target objective to focus.

    Z-galvo stays at 0 throughout. After the measurement this phase
    parks z-wide at the peak so phase 4 can acquire in focus.

    Returns ``(shift_um, report_fragment)`` where ``shift_um`` is the
    delta from ``zwide_post_switch_um`` to the focused z-wide.
    """
    log.info("phase 3: z-wide brenner stack (centre=%.2f, +/-%.1f um)",
             zwide_post_switch_um, z_range_um)
    configure_z_stack(client, job, z_drive="z-wide",
                      half_range_um=z_range_um, step_um=z_step_um,
                      centre_um=zwide_post_switch_um)
    tgt_stack = acquire_stack()
    tgt_focus = brenner_focus(tgt_stack, z_step_um)
    # Stack layout is begin > end (high z-wide first), so:
    #   peak_zwide = (centre + half_range) - peak_sub * step
    peak_zwide_um = float(
        zwide_post_switch_um + z_range_um - tgt_focus["peak_sub"] * z_step_um
    )
    shift_um = float(peak_zwide_um - zwide_post_switch_um)
    log.info("z-wide brenner peak = %.2f um  shift = %+.2f um",
             peak_zwide_um, shift_um)

    # Park z-wide at the focused position so phase 4 acquires in focus.
    # Wait for idle first — after a long stack acquire LAS X is still
    # writing files and the move-z readback won't confirm in time.
    idle = drv.check_idle(client, timeout=60)
    if not idle or not idle.get("success"):
        raise RuntimeError(f"LAS X not idle after stack: {idle}")
    r = drv.move_z(client, job, peak_zwide_um, unit="um", z_mode="zwide")
    if not r:
        raise RuntimeError("move_z returned None")
    if not r.get("success"):
        # Command was accepted but readback didn't confirm in 15 s.
        # Trust the move and warn — z-wide is consistent on this scope.
        log.warning("park-zwide unconfirmed (%s) — proceeding",
                    r.get("message"))

    return shift_um, {
        "zwide_post_switch_um": float(zwide_post_switch_um),
        "zwide_peak_um": peak_zwide_um,
        "shift_um": shift_um,
        "brenner_peak_image_um": float(tgt_focus["peak_um"]),
    }


# ── Phase 4: shift_xy (registration at same stage XY) ────────────────

def measure_shift_xy(
    client, job, *,
    acquire_single, img_ref_focus,
    home_xy, image_to_stage,
    ts_zoom, voting_min_agree,
):
    """Phase 4: stage-frame XY shift between target and reference objectives.

    The clean measurement: caller has switched to the target objective
    (firmware moved the stage by some delta). We **move the stage back
    to ``home_xy``** so img_ref and img_tgt are acquired at the same
    stage XY, then register. The resulting shift is exactly
    ``c1 − c2`` — the optical-axis difference between the two
    objectives — with no firmware-delta contamination.

    Z-galvo is held at 0 by the orchestrator. If ``measure_shift_z``
    ran, z-wide is already parked at the focus peak; otherwise z-wide
    is at the post-switch firmware position and the focus may be off
    — in that case voting will likely fail and the slot is skipped.

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

    disable_z_stack(client, job)
    img_tgt_focus = acquire_single()

    tgt_geo = drv.parse_tile_geometry(drv.get_job_settings(client, job) or {})
    tgt_pixel_um = float(tgt_geo["pixel_w_um"])

    vote = register_voting(img_ref_focus, img_tgt_focus, tgt_pixel_um)
    raw_dx, raw_dy = vote["dx_um"], vote["dy_um"]
    log.info(
        "shift_xy vote: agreeing=%s confidence=%d/%d trusted=%s quality=%.3f",
        vote["agreeing"], vote["confidence"], len(VOTING_METHODS),
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
        "shift_xy: image=(%+.3f, %+.3f) um → stage=(%+.3f, %+.3f) um",
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
    }
