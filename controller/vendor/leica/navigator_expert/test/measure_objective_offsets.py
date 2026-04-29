"""
Objective-switch calibration: two-phase hardware script.
========================================================

Produces a single JSON config describing, for the microscope it is run on:
    1. the image→stage 2×2 sign/rotation transform (a property of the scope
       optical path, common to all objectives), and
    2. the per-target motor-delta each objective switch induces in LAS X's
       reported stage XY (a property of each target objective).

Both pieces are needed to translate "a pixel in an image taken under
objective A" into "a stage command to visit that point under objective B".

Usage
    python measure_objective_offsets.py --job Overview --ref-slot 1 --target-slots 2
    python measure_objective_offsets.py --job Overview --ref-slot 1 --target-slots 2 0

Operator preconditions
    - The ``--job`` passed must already be the currently selected job in the
      LAS X UI. This script does not call ``select_job`` — the driver's
      ``IsSelected`` readback lags the UI and causes false confirm timeouts.
    - ``ImageTransformation = TOPLEFT`` in LAS X Advanced Settings (required
      so pixel math in protocols is consistent with what's saved to disk).
    - Autofocus (AFC) disabled and no modal dialog open. ``check_idle``
      fails fast if either is true.
    - The stage is positioned over a region with enough image texture to
      register. Phase 1 acquires on the reference objective at zoom 1.0
      (~1160 µm FOV on 10x) — an area with multiple cells is ideal.

Phases
    Phase 1 — Sign convention (image ↔ stage axes)
        Under the reference objective, set zoom to 1.0, acquire a reference
        image, move the stage +X and +Y by ``--sign-move-um`` (default 30),
        acquire after each move, and register with phase cross-correlation.
        Build the stage→image Jacobian from the two moves, invert to
        image→stage, snap to the nearest D4 element (pure reflection /
        rotation). Abort if the fit is too far from any D4 element —
        usually a symptom of drift or a featureless region.

        Design notes from validation:
        - Stage physical accuracy on this class of stage is ~5 µm; we
          don't rely on it for precision. Snapping to D4 erases any stage
          non-linearity in the saved matrix.
        - Zoom 1.0 during Phase 1 is deliberate: at high zoom the pixel
          size is small and a 30 µm move becomes >25% of the image, past
          phase correlation's reliable range.
        - The stage readback from LAS X echoes the commanded value, so
          ``_move_and_verify`` with a 0.5 µm tolerance catches only gross
          failures (e.g. unset stage limits). Small sub-µm errors in the
          actual physical move are absorbed by the D4 snap.

    Phase 2 — Motor-delta per target
        Switch from the reference slot to each target slot and record the
        stage XY readback before and after. No image analysis, no repeats
        — LAS X's readback is deterministic for a given (objective,
        commanded XY) pair.

Outputs
    config/objective_offsets/objective_offsets_<ts>.json   (archive, gitignored)
    config/objective_offsets.json                          (current; protocols load this)
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import tifffile
from skimage.registration import phase_cross_correlation

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv


log = logging.getLogger("measure_objective_offsets")


# ── Sign-convention phase (image analysis) ────────────────────────

_D4 = {
    "+X +Y": [[+1, 0], [0, +1]],
    "+X -Y": [[+1, 0], [0, -1]],
    "-X +Y": [[-1, 0], [0, +1]],
    "-X -Y": [[-1, 0], [0, -1]],
    "+Y +X": [[0, +1], [+1, 0]],
    "+Y -X": [[0, +1], [-1, 0]],
    "-Y +X": [[0, -1], [+1, 0]],
    "-Y -X": [[0, -1], [-1, 0]],
}


def _acquire_frame(client, job_name):
    """Acquire one single image; return the numpy array."""
    baseline = drv.read_relative_path(client)
    t_start = time.time()
    result = drv.acquire(client, job_name)
    if not result or not result.get("success"):
        raise RuntimeError(f"acquire failed: {result}")
    media = drv.get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t_start)
    if not det["success"]:
        raise RuntimeError(f"file detection failed: {det.get('error')}")
    files = sorted(det["image_files"])
    drv.wait_all_stable(files, timeout=30)
    img = tifffile.imread(str(files[0]))
    return img[0] if img.ndim == 3 else img


def _image_shift_um(ref, tgt, pixel_size_um):
    """Return (dx_um, dy_um) — how much tgt has shifted relative to ref."""
    shift_px, _, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100,
    )
    # phase_cross_correlation returns the shift required to align tgt with
    # ref, in (row, col) = (y, x) order. The *image shift of tgt relative
    # to ref* is the negative of that.
    dy_px, dx_px = -shift_px[0], -shift_px[1]
    return dx_px * pixel_size_um, dy_px * pixel_size_um


def _classify_d4(matrix):
    """Return (label, canonical_matrix, Frobenius residual) for the nearest D4 element."""
    m = np.asarray(matrix, dtype=float)
    best_label, best_canonical, best_residual = None, None, float("inf")
    for label, canonical in _D4.items():
        canonical_arr = np.asarray(canonical, dtype=float)
        residual = float(np.linalg.norm(m - canonical_arr))
        if residual < best_residual:
            best_label, best_canonical, best_residual = label, canonical_arr, residual
    return best_label, best_canonical, best_residual


# Above this the fitted matrix is too far from any pure reflection/rotation
# to snap safely. Usually means drift, sparse texture, or a bad move size.
D4_RESIDUAL_MAX = 0.3


def _move_and_verify(client, x_um, y_um, *, settle_s, tolerance_um=0.5):
    """Move the stage and verify readback actually reached the target.

    The default MOVE_XY tolerance (20 um) is larger than typical sign-phase
    test moves, so a no-op can pass as "confirmed." We force a tight
    tolerance, check the driver return value, and read back explicitly.
    """
    result = drv.move_xy_stage(
        client, x_um, y_um, unit="um", tolerance=tolerance_um,
    )
    if not result or not result.get("success"):
        raise RuntimeError(
            f"move_xy_stage to ({x_um:.3f}, {y_um:.3f}) um failed: {result}"
        )
    time.sleep(settle_s)
    xy = drv.get_xy(client)
    err_x = xy["x_um"] - x_um
    err_y = xy["y_um"] - y_um
    if abs(err_x) > tolerance_um or abs(err_y) > tolerance_um:
        raise RuntimeError(
            f"stage did not reach ({x_um:.3f}, {y_um:.3f}) um; "
            f"readback ({xy['x_um']:.3f}, {xy['y_um']:.3f}) "
            f"off by ({err_x:+.3f}, {err_y:+.3f}) um"
        )
    return xy["x_um"], xy["y_um"]


def measure_sign_convention(client, job_name, pixel_size_um, *,
                            move_um, settle_s):
    """Measure the image→stage 2×2 transform at the current objective.

    Acquires one reference image, then moves the stage +move_um in X and +Y
    separately, registering each against the reference. Builds the
    stage→image Jacobian from the two moves, inverts to get image→stage.
    Returns the measured transform along with a nearest-D4 label.
    """
    start = drv.get_xy(client)
    x0, y0 = start["x_um"], start["y_um"]
    log.info("sign convention: anchor = (%.3f, %.3f) um", x0, y0)

    ref_img = _acquire_frame(client, job_name)

    log.info("sign convention: stage +%.1f um X", move_um)
    x_after, y_after = _move_and_verify(
        client, x0 + move_um, y0, settle_s=settle_s,
    )
    log.info("  readback after +X: (%.3f, %.3f)  delta=(%+.3f, %+.3f)",
             x_after, y_after, x_after - x0, y_after - y0)
    img_x = _acquire_frame(client, job_name)
    dx_from_x, dy_from_x = _image_shift_um(ref_img, img_x, pixel_size_um)
    log.info("  stage +X → image shift (%+.3f, %+.3f) um", dx_from_x, dy_from_x)

    _move_and_verify(client, x0, y0, settle_s=settle_s)

    log.info("sign convention: stage +%.1f um Y", move_um)
    x_after, y_after = _move_and_verify(
        client, x0, y0 + move_um, settle_s=settle_s,
    )
    log.info("  readback after +Y: (%.3f, %.3f)  delta=(%+.3f, %+.3f)",
             x_after, y_after, x_after - x0, y_after - y0)
    img_y = _acquire_frame(client, job_name)
    dx_from_y, dy_from_y = _image_shift_um(ref_img, img_y, pixel_size_um)
    log.info("  stage +Y → image shift (%+.3f, %+.3f) um", dx_from_y, dy_from_y)

    _move_and_verify(client, x0, y0, settle_s=settle_s)

    # stage-to-image Jacobian: ΔI_image = stage_to_image @ ΔS_stage.
    stage_to_image = np.array([
        [dx_from_x / move_um, dx_from_y / move_um],
        [dy_from_x / move_um, dy_from_y / move_um],
    ])

    # image-to-stage (um/um): maps a feature's image-frame offset from
    # centre to the feature's stage-frame offset from the current stage.
    # Derivation: when we move the stage by ΔS, a feature that was at the
    # image centre before is now at image offset ΔI = stage_to_image @ ΔS.
    # That feature is at stage offset -ΔS from the new stage position
    # (it hasn't physically moved). So image_to_stage @ ΔI = -ΔS, giving
    # image_to_stage = -inv(stage_to_image).
    image_to_stage_fitted = -np.linalg.inv(stage_to_image)

    label, canonical, residual = _classify_d4(image_to_stage_fitted)
    log.info(
        "sign convention: fitted image-to-stage = [[%+.3f, %+.3f], [%+.3f, %+.3f]]  "
        "nearest D4 = %s  residual = %.3f",
        image_to_stage_fitted[0, 0], image_to_stage_fitted[0, 1],
        image_to_stage_fitted[1, 0], image_to_stage_fitted[1, 1],
        label, residual,
    )

    if residual > D4_RESIDUAL_MAX:
        raise RuntimeError(
            f"sign-convention fit is too far from a pure reflection/rotation "
            f"(Frobenius residual {residual:.3f} > {D4_RESIDUAL_MAX}). "
            f"Usual causes: sample drift, sparse image texture at this zoom, "
            f"or a sign-move-um that's too small. Try --sign-move-um 30 at "
            f"a zoom with dense cells in view."
        )

    # Snap to the nearest D4 element for the saved config — a clean ±1
    # permutation matrix, free of measurement noise. The fitted matrix and
    # residual are kept for diagnostics.
    return {
        "image_to_stage_um": canonical.tolist(),
        "label": label,
        "move_um": move_um,
        "fitted_matrix": image_to_stage_fitted.tolist(),
        "residual_from_d4": residual,
    }


# ── CLI / main ────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Two-phase objective-switch calibration."
    )
    p.add_argument("--job", required=True,
                   help="LAS X job name. Must be currently selected in LAS X.")
    p.add_argument("--ref-slot", type=int, required=True,
                   help="Reference objective slot (e.g. 1 for 10x).")
    p.add_argument("--target-slots", type=int, nargs="+", required=True,
                   help="Target objective slot(s) to measure.")
    p.add_argument("--settle", type=float, default=3.0,
                   help=f"Seconds to wait after each objective switch "
                        f"(default: 3; minimum: {drv.MIN_SETTLE_S}).")
    p.add_argument("--sign-move-um", type=float, default=30.0,
                   help="Stage test-move magnitude for the sign phase "
                        "(default: 30 um). Larger values are more robust "
                        "against drift and sparse texture.")
    p.add_argument("--sign-settle", type=float, default=1.0,
                   help="Seconds to wait after each sign-phase stage move "
                        "(default: 1).")
    p.add_argument("--no-restore", action="store_true",
                   help="Do not switch back to the reference slot at the end.")
    return p.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args()

    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        print("ABORT: Cannot connect to LAS X.")
        return 2
    if not drv.ping(client):
        print("ABORT: LAS X ping failed.")
        return 2

    hw = drv.get_hardware_info(client)
    if not hw:
        print("ABORT: Could not read hardware info.")
        return 2

    # Stage limits must be configured before any move — move_xy_stage returns
    # {"success": False} silently when limits are unset. These values cover
    # the usable range of the ZMB STELLARIS stage with safety margins.
    drv.set_stage_limits(
        x_min=1000, x_max=130000,
        y_min=1000, y_max=100000,
        z_galvo_min=-200, z_galvo_max=200,
        z_wide_min=0, z_wide_max=25000,
    )

    print(f"Job:            {args.job}")
    print(f"Reference slot: {args.ref_slot}")
    print(f"Target slots:   {args.target_slots}")
    print(f"Settle:         {args.settle:.1f}s\n")

    # Phase 1 — under the reference objective, measure the sign convention.
    # Set zoom to 1.0 first: at high zoom the pixel size is too small for
    # reliable image-shift measurement (the stage move becomes a large
    # fraction of the FOV, which breaks phase correlation).
    log.info("switching to reference objective for sign phase")
    drv.set_objective(client, args.job, hw, slot_index=args.ref_slot)
    time.sleep(args.settle)

    log.info("setting zoom to 1.0 for sign phase")
    drv.set_zoom(client, args.job, 1.0)
    time.sleep(1.0)

    geo = drv.parse_tile_geometry(drv.get_job_settings(client, args.job) or {})
    pixel_size_um = geo["pixel_w_um"]
    log.info("reference pixel size = %.4f um  (FOV = %.1f um)",
             pixel_size_um, geo["tile_w_um"])

    sign_convention = measure_sign_convention(
        client, args.job, pixel_size_um,
        move_um=args.sign_move_um, settle_s=args.sign_settle,
    )

    # Phase 2 — motor-delta measurement for each target.
    try:
        config = drv.measure_objective_switch_offsets(
            client,
            args.ref_slot,
            args.target_slots,
            job_name=args.job,
            hw_info=hw,
            settle_s=args.settle,
            restore_reference=not args.no_restore,
            sign_convention=sign_convention,
        )
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 1

    print("\nSign convention:")
    print(f"  matrix = {sign_convention['image_to_stage_um']}")
    print(f"  label  = {sign_convention['label']}  "
          f"(residual from D4 = {sign_convention['residual_from_d4']:.3f})")

    print("\nMeasured objective-switch deltas:")
    for slot, entry in config["offsets"].items():
        dx, dy = entry["motor_delta_um"]
        name = (entry["target_objective"] or {}).get("name", "")
        print(f"  slot {slot}: dx={dx:+.3f} um, dy={dy:+.3f} um  {name}")

    paths = drv.save_objective_offsets(config)
    print(f"\nArchive: {paths['archive']}")
    print(f"Current: {paths['current']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
