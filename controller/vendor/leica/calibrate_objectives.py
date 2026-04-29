"""
calibrate_objectives.py — unified objective-switch calibration.

One script. Writes incremental updates to ``config/machine.json`` and a
full diagnostics report to ``config/calibration_reports/calibration_report_<ts>.json``.

Phases (in order)
-----------------
1. **Sign convention** — under the reference objective. Stage moves +X
   then +Y, fits a 2x2 image->stage Jacobian, snaps to the nearest D4
   reflection/rotation. Always runs on a fresh machine config; reuses
   the cached value otherwise unless ``--measure-sign``.

2. **Parcentric XY (motor)** — for each target, switch from the
   reference, read XY before/after, store the readback delta. Always
   runs.

3. **Parfocal Z** — optional (``--measure-parfocal``). Z-stacks on
   reference and target, Brenner peak gives focus per objective,
   ``dZ = target - reference``. A shifted verification stack confirms
   the corrected position centres the peak.

4. **Parcentric XY (image residual)** — optional (``--measure-xy``,
   requires ``--measure-parfocal``). High-quality slice on each
   objective at its measured focus Z, OpenCV NCC -> residual beyond
   the motor delta. Sign convention converts image shift -> stage.

5. **Verification** — optional (``--verify``). Re-acquire at the
   fully-corrected XY+Z and report what is left.

Stage state and backlash
------------------------
Every acquisition is preceded by a +X+Y backlash takeup. Stage limits
and takeup parameters come from ``config/stage.json``.

Reference state
---------------
Every phase starts from a known reference state: reference slot active,
pan/ROI reset, Z-stack disabled, zoom at ``--ref-zoom``, LAS X idle,
AFC off. The script restores this state between targets and on exit.

Operator preconditions
----------------------
- ``--job`` is the currently selected job in LAS X.
- ImageTransformation is TOPLEFT.
- AFC is off; no LAS X modal dialogs.
- The stage is over a region with enough texture for image registration.

Usage
-----
    python calibrate_objectives.py --job Overview --target-slots 0 2
    python calibrate_objectives.py --job Overview --target-slots 0 2 \\
        --measure-parfocal --measure-xy --verify
    python calibrate_objectives.py --job Overview --target-slots 2 \\
        --measure-parfocal             # incremental: only refresh slot 2 dZ
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import tifffile
from skimage.registration import phase_cross_correlation

sys.path.insert(0, str(Path(__file__).resolve().parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.machine_config import (
    load_machine_config,
    save_machine_config,
    load_stage_config,
    set_reference,
    set_sign_convention,
    update_target,
    save_calibration_report,
    now_timestamp,
    MACHINE_SCHEMA_VERSION,
)
from lasx.scanning_template_editors_focus import lrp_set_stack_calculation_mode
from lasx.scanning_template_editors_roi import lrp_enable_roi_scan
from lasx.scanning_template_editors_scan import lrp_set_pan
from lasx.scanning_template_editors_z import (
    lrp_set_sections,
    lrp_set_z_stack_active,
    lrp_set_z_use_mode,
)
from lasx.scanning_templates import TEMPLATE_XML, apply_lrp_change
from lasx.stage_motion import correct_backlash

log = logging.getLogger("calibrate_objectives")


# ── Constants ────────────────────────────────────────────────────

D4_ELEMENTS = {
    "+X +Y": [[+1, 0], [0, +1]], "+X -Y": [[+1, 0], [0, -1]],
    "-X +Y": [[-1, 0], [0, +1]], "-X -Y": [[-1, 0], [0, -1]],
    "+Y +X": [[0, +1], [+1, 0]], "+Y -X": [[0, +1], [-1, 0]],
    "-Y +X": [[0, -1], [+1, 0]], "-Y -X": [[0, -1], [-1, 0]],
}

# Above this Frobenius distance the fit is too far from a pure
# reflection/rotation to snap; usual cause is drift or sparse texture.
D4_RESIDUAL_MAX = 0.3

REF_ZOOM_DEFAULT = 1.0
SETTLE_S_DEFAULT = 3.0
SIGN_MOVE_UM_DEFAULT = 30.0
SIGN_SETTLE_S_DEFAULT = 1.0
Z_RANGE_UM_DEFAULT = 15.0
Z_STEP_UM_DEFAULT = 1.0
JOB_SELECT_RETRIES = 3


# ── CLI ───────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--job", required=True,
                   help="LAS X job (must already be the selected job).")
    p.add_argument("--ref-slot", type=int, default=1,
                   help="Reference objective slot (default: 1).")
    p.add_argument("--target-slots", type=int, nargs="+", required=True,
                   help="Target slot(s) to calibrate against the reference.")

    p.add_argument("--measure-sign", action="store_true",
                   help="Re-measure sign convention "
                        "(default: reuse the cached value if present).")
    p.add_argument("--measure-parfocal", action="store_true",
                   help="Measure parfocal dZ via Z-stacks (slow).")
    p.add_argument("--measure-xy", action="store_true",
                   help="Measure image-based XY residual "
                        "(requires --measure-parfocal).")
    p.add_argument("--verify", action="store_true",
                   help="Acquire at corrected position and report residuals.")

    p.add_argument("--ref-zoom", type=float, default=REF_ZOOM_DEFAULT,
                   help=f"Reference zoom (default: {REF_ZOOM_DEFAULT}). "
                        f"Low zoom (large FOV) is robust for the sign phase.")
    p.add_argument("--settle", type=float, default=SETTLE_S_DEFAULT,
                   help=f"Seconds after each objective switch "
                        f"(default: {SETTLE_S_DEFAULT}).")
    p.add_argument("--sign-move-um", type=float, default=SIGN_MOVE_UM_DEFAULT,
                   help=f"Stage test-move size for the sign phase, in um "
                        f"(default: {SIGN_MOVE_UM_DEFAULT}).")
    p.add_argument("--sign-settle", type=float, default=SIGN_SETTLE_S_DEFAULT,
                   help=f"Seconds after each sign-phase stage move "
                        f"(default: {SIGN_SETTLE_S_DEFAULT}).")
    p.add_argument("--z-range-um", type=float, default=Z_RANGE_UM_DEFAULT,
                   help=f"Z-stack half-range in um (default: {Z_RANGE_UM_DEFAULT}).")
    p.add_argument("--z-step-um", type=float, default=Z_STEP_UM_DEFAULT,
                   help=f"Z-stack step size in um (default: {Z_STEP_UM_DEFAULT}).")
    return p.parse_args()


# ── Image analysis ───────────────────────────────────────────────

def to_uint8(img):
    f = img.astype(np.float64)
    return (f / (f.max() or 1) * 255).astype(np.uint8)


def register_ncc(ref, tgt, pixel_um):
    """OpenCV NCC: returns (dx_um, dy_um, ncc_quality)."""
    ref8 = to_uint8(ref)
    tgt8 = to_uint8(tgt)
    h, w = tgt8.shape
    margin = h // 4
    template = tgt8[margin:h - margin, margin:w - margin]
    result = cv2.matchTemplate(ref8, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    dx_px = max_loc[0] + template.shape[1] / 2.0 - w / 2.0
    dy_px = max_loc[1] + template.shape[0] / 2.0 - h / 2.0
    return dx_px * pixel_um, dy_px * pixel_um, float(max_val)


def register_phase(ref, tgt, pixel_um):
    """Phase cross-correlation. Returns (dx_um, dy_um) of tgt relative to ref."""
    shift, _, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64), upsample_factor=100,
    )
    dy_px, dx_px = -shift[0], -shift[1]
    return dx_px * pixel_um, dy_px * pixel_um


def brenner(img):
    f = img.astype(np.float64)
    dx = f[:, 2:] - f[:, :-2]
    return float((dx ** 2).mean())


def subpixel_peak(scores, peak):
    if peak <= 0 or peak >= len(scores) - 1:
        return float(peak)
    y0, y1, y2 = scores[peak - 1], scores[peak], scores[peak + 1]
    denom = 2 * (2 * y1 - y0 - y2)
    if abs(denom) < 1e-10:
        return float(peak)
    return peak + (y0 - y2) / denom


def brenner_focus(stack, z_step):
    scores = [brenner(stack[i]) for i in range(stack.shape[0])]
    peak = int(np.argmax(scores))
    peak_sub = subpixel_peak(scores, peak)
    return {
        "peak_slice": peak,
        "peak_sub": peak_sub,
        "peak_um": float(peak_sub * z_step),
        "scores": [float(s) for s in scores],
    }


def classify_d4(matrix):
    """Return (label, canonical, residual) of the nearest D4 element."""
    m = np.asarray(matrix, dtype=float)
    best_label, best_canonical, best_residual = None, None, float("inf")
    for label, canonical in D4_ELEMENTS.items():
        canonical_arr = np.asarray(canonical, dtype=float)
        residual = float(np.linalg.norm(m - canonical_arr))
        if residual < best_residual:
            best_label, best_canonical, best_residual = label, canonical_arr, residual
    return best_label, best_canonical, best_residual


# ── LAS X helpers ────────────────────────────────────────────────

def reset_pan_roi_zstack(client, job):
    """Pan -> 0, ROI -> off, Z-stack -> off, sections -> 1."""
    def _setup(p):
        lrp_set_pan(p, 0, 0, job)
        lrp_enable_roi_scan(p, False, job)
        lrp_set_z_stack_active(p, False, job)
        lrp_set_sections(p, 1, job)
    apply_lrp_change(client, TEMPLATE_XML, _setup, confirm_delays=(2, 4, 6))


def configure_z_stack(client, job, *, half_range_um, step_um,
                      begin_um=None, end_um=None):
    """Enable a z-galvo stack centred at 0 unless explicit begin/end given.

    Convention: ``begin > end`` so positive slice indices run from
    +z-galvo down to -z-galvo. Brenner peaks indexed against this layout
    convert to z-galvo via ``half_range - peak_sub * step``.
    """
    sections = int(2 * half_range_um / step_um) + 1
    b = begin_um if begin_um is not None else half_range_um
    e = end_um if end_um is not None else -half_range_um

    def _setup(p):
        lrp_set_z_stack_active(p, False, job)
        lrp_set_z_use_mode(p, "z-galvo", job)
        lrp_set_stack_calculation_mode(p, 1, job)
        lrp_set_sections(p, sections, job)
        lrp_set_z_stack_active(p, True, job)
    apply_lrp_change(client, TEMPLATE_XML, _setup, confirm_delays=(2, 4, 6))
    drv.set_z_stack_definition(client, job, begin_um=b, end_um=e)
    drv.set_z_stack_step_size(client, job, step_um)


def disable_z_stack(client, job):
    def _setup(p):
        lrp_set_z_stack_active(p, False, job)
        lrp_set_sections(p, 1, job)
    apply_lrp_change(client, TEMPLATE_XML, _setup, confirm_delays=(2, 4, 6))


def reselect_job(client, job):
    """Re-select the job after an objective switch.

    LAS X drops the job selection on objective switch; the readback also
    lags briefly. Retry until the selection sticks.
    """
    for _ in range(JOB_SELECT_RETRIES):
        drv.select_job(client, job)
        time.sleep(2)
        if (drv.get_selected_job(client) or {}).get("Name", "") == job:
            return
    sel = (drv.get_selected_job(client) or {}).get("Name", "")
    raise RuntimeError(
        f"could not select job {job!r} after objective switch (got {sel!r})"
    )


def setup_reference_state(client, job, hw, *, ref_slot, ref_zoom, settle_s):
    """Switch to the reference slot and put the scope in canonical state."""
    log.info("reference state: slot=%d, zoom=%.2f", ref_slot, ref_zoom)
    r = drv.set_objective(client, job, hw, slot_index=ref_slot)
    if not r or not r.get("success"):
        raise RuntimeError(f"objective switch to ref slot {ref_slot} failed: {r}")
    time.sleep(settle_s)
    reselect_job(client, job)
    reset_pan_roi_zstack(client, job)
    drv.set_zoom(client, job, ref_zoom)
    time.sleep(1.0)
    drv.select_job(client, job)
    time.sleep(1.0)
    idle = drv.check_idle(client, timeout=30)
    if not idle or not idle.get("success"):
        raise RuntimeError(f"LAS X not idle after reference setup: {idle}")


def switch_to_target(client, job, hw, slot, *, settle_s, zoom):
    """Switch to a target objective and re-establish job + zoom."""
    log.info("switching to target slot=%d (zoom=%.2f)", slot, zoom)
    r = drv.set_objective(client, job, hw, slot_index=slot)
    if not r or not r.get("success"):
        raise RuntimeError(f"objective switch to slot {slot} failed: {r}")
    time.sleep(settle_s)
    reselect_job(client, job)
    reset_pan_roi_zstack(client, job)
    drv.set_zoom(client, job, zoom)
    time.sleep(1.0)
    drv.select_job(client, job)
    time.sleep(1.0)


def make_acquirer(client, job, stage_cfg):
    """Return (acquire_single, acquire_stack), each preceded by backlash takeup."""
    bk = stage_cfg["backlash"]
    bl_kwargs = dict(
        overshoot_um=bk["overshoot_um"],
        settle_ms=bk["settle_ms"],
        tolerance_um=bk.get("tolerance_um", 20.0),
    )

    def _files():
        correct_backlash(client, **bl_kwargs)
        idle = drv.check_idle(client, timeout=30)
        if not idle or not idle.get("success"):
            raise RuntimeError(f"scanner not idle before acquire: {idle}")
        baseline = drv.read_relative_path(client)
        t0 = time.time()
        result = drv.acquire(client, job)
        if not result or not result.get("success"):
            raise RuntimeError(f"acquire failed: {result}")
        media = drv.get_lasx_settings()["export"]["media_path"]
        det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
        if not det["success"]:
            raise RuntimeError(f"file detection failed: {det.get('error')}")
        files = sorted(det["image_files"])
        if not files:
            raise RuntimeError("acquire produced no files")
        drv.wait_all_stable(files, timeout=30)
        return files

    def acquire_single():
        files = _files()
        img = tifffile.imread(str(files[0]))
        return img[0] if img.ndim == 3 else img

    def acquire_stack():
        files = _files()
        if len(files) == 1:
            stack = tifffile.imread(str(files[0]))
            if stack.ndim == 2:
                stack = stack[np.newaxis, ...]
        else:
            slices = [tifffile.imread(str(f)) for f in files]
            slices = [s[0] if s.ndim == 3 else s for s in slices]
            stack = np.array(slices)
        return stack

    return acquire_single, acquire_stack


def apply_stage_limits(stage_cfg):
    lim = stage_cfg["limits_um"]
    drv.set_stage_limits(
        x_min=lim["x"][0], x_max=lim["x"][1],
        y_min=lim["y"][0], y_max=lim["y"][1],
        z_galvo_min=lim["z_galvo"][0], z_galvo_max=lim["z_galvo"][1],
        z_wide_min=lim["z_wide"][0], z_wide_max=lim["z_wide"][1],
    )


# ── Phase 1: sign convention ─────────────────────────────────────

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


def measure_sign_convention(acquire_single, client, *,
                            pixel_size_um, move_um, settle_s):
    """Phase 1: image-to-stage Jacobian, snapped to nearest D4 element."""
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


# ── Orchestrator ──────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args()

    if args.measure_xy and not args.measure_parfocal:
        print("ABORT: --measure-xy requires --measure-parfocal "
              "(image residual is measured at the corrected focal plane).")
        return 2

    if args.ref_slot in args.target_slots:
        print("ABORT: --ref-slot cannot appear in --target-slots.")
        return 2

    stage_cfg = load_stage_config()
    machine_cfg = load_machine_config(create_if_missing=True)

    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        print("ABORT: cannot connect to LAS X.")
        return 2
    if not drv.ping(client):
        print("ABORT: LAS X ping failed.")
        return 2

    apply_stage_limits(stage_cfg)

    hw = drv.get_hardware_info(client)
    if not hw:
        print("ABORT: could not read hardware info.")
        return 2

    drv.validate_slots(hw, args.ref_slot, args.target_slots)
    by_slot = drv.objective_by_slot(hw)
    ref_summary = drv.objective_summary(by_slot[args.ref_slot])
    targets_summary = {s: drv.objective_summary(by_slot[s]) for s in args.target_slots}

    measure_sign = args.measure_sign or machine_cfg.get("image_to_stage") is None
    phases = ["sign"] if measure_sign else []
    phases.append("motor_delta")
    if args.measure_parfocal:
        phases.append("parfocal")
    if args.measure_xy:
        phases.append("xy_image")
    if args.verify:
        phases.append("verify")

    print(f"Job:          {args.job}")
    print(f"Reference:    slot {args.ref_slot}  ({ref_summary['name']})")
    for s, sm in targets_summary.items():
        print(f"Target:       slot {s}  ({sm['name']})")
    print(f"Phases:       {', '.join(phases)}\n")

    setup_reference_state(client, args.job, hw,
                          ref_slot=args.ref_slot, ref_zoom=args.ref_zoom,
                          settle_s=args.settle)

    geo = drv.parse_tile_geometry(drv.get_job_settings(client, args.job) or {})
    pixel_size_um = float(geo["pixel_w_um"])
    log.info("ref pixel size = %.4f um (FOV %.1f um)",
             pixel_size_um, float(geo["tile_w_um"]))

    home = drv.get_xy(client)
    home_xy = (float(home["x_um"]), float(home["y_um"]))
    set_reference(machine_cfg, args.ref_slot,
                  summary=ref_summary, anchor_xy_um=home_xy)

    acquire_single, acquire_stack = make_acquirer(client, args.job, stage_cfg)

    report = {
        "schema_version": MACHINE_SCHEMA_VERSION,
        "timestamp": now_timestamp(),
        "machine_config": "machine.json",
        "phases_run": list(phases),
        "settings": {
            "ref_slot": args.ref_slot,
            "target_slots": list(args.target_slots),
            "ref_zoom": args.ref_zoom,
            "settle_s": args.settle,
            "sign_move_um": args.sign_move_um,
            "z_range_um": args.z_range_um,
            "z_step_um": args.z_step_um,
            "backlash_overshoot_um": stage_cfg["backlash"]["overshoot_um"],
            "backlash_settle_ms": stage_cfg["backlash"]["settle_ms"],
        },
        "reference_objective": ref_summary,
        "anchor_xy_um": list(home_xy),
        "sign_convention": None,
        "per_target": {},
    }

    # ── Phase 1: sign convention ────────────────────────────────
    if "sign" in phases:
        sign = measure_sign_convention(
            acquire_single, client,
            pixel_size_um=pixel_size_um,
            move_um=args.sign_move_um,
            settle_s=args.sign_settle,
        )
        set_sign_convention(machine_cfg, sign["image_to_stage_um"])
        report["sign_convention"] = sign
    else:
        log.info("sign convention: reusing cached value from machine.json")

    image_to_stage = machine_cfg["image_to_stage"]

    # ── Pre-acquire reference Z-stack and focus slice ──────────
    # These are reused across all targets — both are properties of the
    # reference objective at the home XY, not of any particular target.
    ref_focus = None
    img_ref_focus = None
    if args.measure_parfocal:
        log.info("phase 3 (ref): acquiring reference Z-stack")
        configure_z_stack(client, args.job,
                          half_range_um=args.z_range_um, step_um=args.z_step_um)
        ref_stack = acquire_stack()
        ref_focus = brenner_focus(ref_stack, args.z_step_um)
        ref_z_galvo_um = args.z_range_um - ref_focus["peak_sub"] * args.z_step_um
        log.info("ref focus: peak_um=%.2f, z-galvo=%+.2f um",
                 ref_focus["peak_um"], ref_z_galvo_um)

        if args.measure_xy or args.verify:
            log.info("phase 4 prep: ref focus slice at z-galvo=%+.2f", ref_z_galvo_um)
            disable_z_stack(client, args.job)
            drv.set_z_stack_definition(client, args.job,
                                       begin_um=ref_z_galvo_um,
                                       end_um=ref_z_galvo_um)
            img_ref_focus = acquire_single()

    # ── Per-target loop ─────────────────────────────────────────
    for ts in args.target_slots:
        log.info("=== target slot %d ===", ts)
        ts_summary = targets_summary[ts]
        # Match the reference FOV: target_zoom = ref_zoom * ref_mag / tgt_mag
        ts_zoom = args.ref_zoom * ref_summary["magnification"] / ts_summary["magnification"]

        switch_to_target(client, args.job, hw, ts,
                         settle_s=args.settle, zoom=ts_zoom)

        # Phase 2: motor delta XY (always)
        target_xy = drv.get_xy(client)
        motor_delta = [
            float(target_xy["x_um"] - home_xy[0]),
            float(target_xy["y_um"] - home_xy[1]),
        ]
        log.info("motor delta: (%+.3f, %+.3f) um", *motor_delta)

        target_report = {"motor_delta_um": motor_delta}
        target_update = {
            "summary": ts_summary,
            "parcentric_motor_um": motor_delta,
        }
        dz_um = None
        residual_xy = None

        # Phase 3: parfocal Z
        if args.measure_parfocal:
            log.info("phase 3 (tgt): target Z-stack")
            configure_z_stack(client, args.job,
                              half_range_um=args.z_range_um,
                              step_um=args.z_step_um)
            tgt_stack = acquire_stack()
            tgt_focus = brenner_focus(tgt_stack, args.z_step_um)
            dz_um = float((tgt_focus["peak_sub"] - ref_focus["peak_sub"])
                          * args.z_step_um)
            log.info("parfocal dZ = %+.2f um", dz_um)

            log.info("phase 3 (ver): shifted Z-stack at corrected position")
            configure_z_stack(client, args.job,
                              half_range_um=args.z_range_um,
                              step_um=args.z_step_um,
                              begin_um=args.z_range_um - dz_um,
                              end_um=-args.z_range_um - dz_um)
            ver_stack = acquire_stack()
            ver_focus = brenner_focus(ver_stack, args.z_step_um)
            dz_residual_um = float((ver_focus["peak_sub"] - ref_focus["peak_sub"])
                                    * args.z_step_um)
            log.info("parfocal verification residual: %+.2f um (target ~0)",
                     dz_residual_um)

            target_report["parfocal"] = {
                "ref_brenner_peak_um": ref_focus["peak_um"],
                "tgt_brenner_peak_um": tgt_focus["peak_um"],
                "dz_um": dz_um,
                "verification_residual_um": dz_residual_um,
            }
            target_update["parfocal_motor_um"] = dz_um
            target_update["parfocal_residual_um"] = dz_residual_um

        # Phase 4: image-based XY residual
        if args.measure_xy:
            tgt_z_galvo_um = -dz_um
            log.info("phase 4: target focus slice at z-galvo=%+.2f", tgt_z_galvo_um)
            disable_z_stack(client, args.job)
            drv.set_z_stack_definition(client, args.job,
                                       begin_um=tgt_z_galvo_um,
                                       end_um=tgt_z_galvo_um)
            img_tgt_focus = acquire_single()

            tgt_geo = drv.parse_tile_geometry(
                drv.get_job_settings(client, args.job) or {})
            tgt_pixel_um = float(tgt_geo["pixel_w_um"])

            raw_dx, raw_dy, ncc_q = register_ncc(img_ref_focus, img_tgt_focus,
                                                  tgt_pixel_um)
            stage_dx = image_to_stage[0][0] * raw_dx + image_to_stage[0][1] * raw_dy
            stage_dy = image_to_stage[1][0] * raw_dx + image_to_stage[1][1] * raw_dy
            residual_xy = [float(stage_dx), float(stage_dy)]
            log.info("image XY residual: stage=(%+.3f, %+.3f) um, NCC=%.3f",
                     stage_dx, stage_dy, ncc_q)

            target_report["image_xy"] = {
                "raw_dx_um": float(raw_dx),
                "raw_dy_um": float(raw_dy),
                "stage_dx_um": float(stage_dx),
                "stage_dy_um": float(stage_dy),
                "ncc_quality": ncc_q,
                "method": "focus_slice",
                "acquisition_zoom": ts_zoom,
                "acquisition_z_galvo_um": tgt_z_galvo_um,
            }
            target_update["parcentric_residual_um"] = residual_xy

        # Phase 5: verification
        if args.verify:
            corrected_x = home_xy[0] + motor_delta[0] + (residual_xy[0] if residual_xy else 0.0)
            corrected_y = home_xy[1] + motor_delta[1] + (residual_xy[1] if residual_xy else 0.0)
            r = drv.move_xy_stage(client, corrected_x, corrected_y,
                                  unit="um", tolerance=20.0)
            if not r or not r.get("success"):
                raise RuntimeError(f"verification move failed: {r}")
            time.sleep(0.5)

            tz = -dz_um if dz_um is not None else 0.0
            disable_z_stack(client, args.job)
            drv.set_z_stack_definition(client, args.job, begin_um=tz, end_um=tz)
            img_ver = acquire_single()

            if img_ref_focus is None:
                target_report["verification"] = {
                    "note": "no reference focus slice; --measure-xy was off",
                }
            else:
                tgt_geo = drv.parse_tile_geometry(
                    drv.get_job_settings(client, args.job) or {})
                tgt_pixel_um = float(tgt_geo["pixel_w_um"])
                ver_dx, ver_dy, ver_q = register_ncc(img_ref_focus, img_ver,
                                                      tgt_pixel_um)
                target_report["verification"] = {
                    "residual_image_um": [float(ver_dx), float(ver_dy)],
                    "ncc_quality": ver_q,
                }
                log.info("verification: image residual=(%+.3f, %+.3f) um NCC=%.3f",
                         ver_dx, ver_dy, ver_q)

        update_target(machine_cfg, ts, **target_update)
        report["per_target"][str(ts)] = target_report

        if ts != args.target_slots[-1]:
            setup_reference_state(client, args.job, hw,
                                  ref_slot=args.ref_slot,
                                  ref_zoom=args.ref_zoom,
                                  settle_s=args.settle)

    # ── Restore + persist ──────────────────────────────────────
    log.info("restoring reference state")
    setup_reference_state(client, args.job, hw,
                          ref_slot=args.ref_slot, ref_zoom=args.ref_zoom,
                          settle_s=args.settle)
    drv.move_xy_stage(client, home_xy[0], home_xy[1], unit="um", tolerance=20.0)

    machine_path = save_machine_config(machine_cfg)
    report_path = save_calibration_report(report, ts=report["timestamp"])

    print(f"\nMachine config: {machine_path}")
    print(f"Report:         {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
