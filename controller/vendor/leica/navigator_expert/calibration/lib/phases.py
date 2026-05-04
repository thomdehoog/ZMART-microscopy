"""Phase functions for objective calibration.

Each phase takes a LAS X client + the state it needs and returns the
data the orchestrator persists. No phase mutates the machine config or
the run report directly — the orchestrator does that, so persistence
stays in one place.

Z model (entire calibration runs with z-galvo at 0):
    - The firmware applies the bulk parfocal correction by moving
      z-wide on objective switch. The orchestrator records that as
      ``offset_z_um`` (post-switch zwide minus pre-switch zwide).
    - ``measure_brenner`` is the single Brenner-stack primitive. Run
      once on the reference (peak gives the operator's focus error)
      and once per target (peak gives the firmware's parfocal
      residual, plus a focused slice for shift_xy registration).
      Each call restores z-wide to its pre-stack position so the
      measurement is reversible.
    - ``compute_shift_z`` is pure math on two Brenner results:
      ``shift = target_residual - ref_residual``. Both anchors are
      Brenner peaks, so the operator's focus accuracy at the
      reference does not bias the cookbook value.

Phase boundaries:

    measure_sign_convention   -- under reference objective only
    measure_brenner           -- one stack on z-wide; used both for
                                 the reference anchor (Phase 0, run
                                 once) and the per-target anchor
                                 (Phase 3 input). Restores z-wide.
    measure_xy_firmware_delta -- per target, always runs (firmware
                                 ``get_xy`` delta on switch; diagnostic)
    compute_shift_z           -- per target (when shift_z is
                                 requested); pure math from the
                                 target's BrennerResult + the ref
                                 residual.
    measure_shift_xy          -- per target (when shift_xy is
                                 requested); voting registration with
                                 both anchors at their Brenner peaks.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

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

from .lasx_state import configure_z_stack


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


# ── Brenner stack (used for both reference and target) ──────────────

@dataclass(frozen=True)
class BrennerResult:
    """Outcome of one Brenner z-stack on z-wide.

    A single value type carried between :func:`measure_brenner` and
    its consumers (orchestrator, :func:`compute_shift_z`,
    :func:`measure_shift_xy`).

    ``residual_um`` is the focus error of ``centre_zwide_um`` — the
    z-wide position where the stack was centred — relative to the
    Brenner peak. For the reference stack this is the operator's
    focus error; for a target stack centred at ``zwide_post_switch``
    it is the firmware's parfocal-compensation residual.
    """
    centre_zwide_um: float
    peak_zwide_um: float
    peak_slice: Any              # in-focus slice from the stack
    peak_image_um: float         # peak_sub * z_step (relative to stack origin)
    scores: list[float]          # per-slice Brenner scores

    @property
    def residual_um(self) -> float:
        return self.peak_zwide_um - self.centre_zwide_um

    def report(self) -> dict:
        return {
            "centre_zwide_um": float(self.centre_zwide_um),
            "peak_zwide_um": float(self.peak_zwide_um),
            "residual_um": float(self.residual_um),
            "peak_image_um": float(self.peak_image_um),
            "scores": list(self.scores),
        }


def measure_brenner(client, job, *, acquire_stack,
                    z_range_um, z_step_um, centre_zwide_um) -> BrennerResult:
    """Run one Brenner z-stack on z-wide, centred at ``centre_zwide_um``.

    The stack acquisition itself moves z-wide from ``centre +
    half_range`` down to ``centre - half_range``. To keep the
    measurement reversible — so the caller can rely on z-wide state
    matching the pre-call state — this function restores z-wide to
    ``centre_zwide_um`` after the stack. Without that restore, the
    next firmware switch would compensate from a drifted z-wide and
    the per-target ``offset_z`` math would be off by ``half_range``.

    Used for both the reference anchor (Phase 0) and per-target
    (Phase 3) — same measurement, same restore protocol. The
    orchestrator decides what to compute from the result.
    """
    log.info("brenner: stack on z-wide (centre=%.2f, +/-%.1f um)",
             centre_zwide_um, z_range_um)
    configure_z_stack(client, job, z_drive="z-wide",
                      half_range_um=z_range_um, step_um=z_step_um,
                      centre_um=centre_zwide_um)
    stack = acquire_stack()
    focus = brenner_focus(stack, z_step_um)

    # Stack layout is begin > end (high z-wide first), so:
    #   peak_zwide = (centre + half_range) - peak_sub * step
    peak_zwide_um = float(
        centre_zwide_um + z_range_um - focus["peak_sub"] * z_step_um
    )

    # Restore z-wide to the pre-stack position. After the stack
    # acquire LAS X is still writing files; wait for idle so the
    # move readback can confirm.
    idle = drv.check_idle(client, timeout=60)
    if not idle or not idle.get("success"):
        raise RuntimeError(f"LAS X not idle after stack: {idle}")
    r = drv.move_z(client, job, centre_zwide_um, unit="um", z_mode="zwide")
    if not r:
        raise RuntimeError("z-wide restore: move_z returned None")
    if not r.get("success"):
        # Command was accepted but readback didn't confirm in 15 s.
        # Trust the move and warn — z-wide is consistent on this scope.
        log.warning("z-wide restore unconfirmed (%s) — proceeding",
                    r.get("message"))

    log.info("brenner peak = %.2f um  residual = %+.2f um",
             peak_zwide_um, peak_zwide_um - centre_zwide_um)

    return BrennerResult(
        centre_zwide_um=float(centre_zwide_um),
        peak_zwide_um=peak_zwide_um,
        peak_slice=stack[focus["peak_slice"]],
        peak_image_um=float(focus["peak_um"]),
        scores=[float(s) for s in focus["scores"]],
    )


# ── Phase 3: shift_z — pure math from a target Brenner result ───────

def compute_shift_z(target_brenner: BrennerResult, *,
                    zwide_post_switch_um: float,
                    ref_residual_um: float):
    """Phase 3: objective shift_z from a target Brenner result.

    Both anchors are Brenner peaks, so the operator's focus accuracy
    at the reference does not enter the calibration:

        shift_um = (peak_target - zwide_post)
                 - (peak_ref - zwide_at_ref)
                 = target.residual_um - ref_residual_um

    The cookbook applies ``shift_um`` on z-wide AFTER the firmware
    has shifted z-wide for the objective switch.

    Pure math + report fragment — no LAS X interaction; the
    measurement was done by :func:`measure_brenner`.
    """
    raw_um = float(target_brenner.peak_zwide_um - zwide_post_switch_um)
    shift_um = float(raw_um - ref_residual_um)
    log.info(
        "shift_z: raw residual = %+.2f um  ref residual = %+.2f um  "
        "objective = %+.2f um",
        raw_um, ref_residual_um, shift_um,
    )
    return shift_um, {
        "zwide_post_switch_um": float(zwide_post_switch_um),
        "zwide_peak_um": float(target_brenner.peak_zwide_um),
        "shift_raw_um": raw_um,
        "shift_um": shift_um,
        "ref_residual_um": float(ref_residual_um),
        "peak_image_um": float(target_brenner.peak_image_um),
    }


# ── Phase 4: shift_xy (registration at same stage XY) ────────────────

def measure_shift_xy(
    client, job, *,
    img_ref_focus, img_tgt_focus,
    home_xy, image_to_stage,
    ts_zoom, voting_min_agree,
):
    """Phase 4: stage-frame XY shift between target and reference objectives.

    Both ``img_ref_focus`` and ``img_tgt_focus`` are required: they
    must be the Brenner-peak slices from :func:`measure_brenner` on
    the reference and on this target, respectively. Anchoring both
    images at their optical focus is what makes voting registration
    robust on objectives with shallow depth of field.

    The caller has switched to the target objective (firmware moved
    the stage). We **move the stage back to** ``home_xy`` so the two
    anchor images correspond to the same stage XY, then register.
    The resulting shift is exactly ``c1 − c2`` — the optical-axis
    difference between the two objectives — with no firmware-delta
    contamination.

    Returns ``(shift_xy_or_None, report_fragment)``. ``shift_xy=None``
    means voting failed and the cookbook should not be given a
    correction for this slot.
    """
    log.info("phase 4: moving stage back to home before registration")
    r = drv.move_xy_stage(
        client, home_xy[0], home_xy[1],
        unit="um", tolerance=0.5,
    )
    if not r or not r.get("success"):
        raise RuntimeError(f"phase 4 move-back-to-home failed: {r}")
    time.sleep(1.0)

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
