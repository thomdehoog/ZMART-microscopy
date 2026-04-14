"""
Dry registration check for parcentricity work.

This script keeps the workflow intentionally narrow:
1. Acquire a reference image.
2. Move the stage by a known XY offset, or pause for a manual move.
3. Acquire a second image.
4. Register the two images and report the measured image shift.

It does not switch objectives, apply a correction, or sweep sign
conventions. The goal is only to verify that the registration path is
working on a minimal acquire-move-acquire sequence.
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Dry acquire-move-acquire registration check")
parser.add_argument("--job", default="Overview",
                    help="LAS X job name to acquire (default: Overview)")
parser.add_argument("--move-x-um", type=float, default=5.0,
                    help="Programmatic X move before the second acquire (default: 5.0)")
parser.add_argument("--move-y-um", type=float, default=0.0,
                    help="Programmatic Y move before the second acquire (default: 0.0)")
parser.add_argument("--settle", type=float, default=1.0,
                    help="Wait time after the move, in seconds (default: 1.0)")
parser.add_argument("--mask-pct", type=float, default=30.0,
                    help="Mask percentile for sub-pixel registration (default: 30)")
parser.add_argument("--upsample", type=int, default=100,
                    help="Sub-pixel upsample factor (default: 100)")
parser.add_argument("--manual", action="store_true",
                    help="Do not move the stage programmatically; pause before the second acquire")
parser.add_argument("--restore-stage", action="store_true",
                    help="Move the stage back to the reference position before exit")
parser.add_argument("--output", default=None,
                    help="Output directory (default: config/alignment/registration_dry_<timestamp>)")
args = parser.parse_args()

import cv2
import matplotlib
import numpy as np
import tifffile
from scipy.ndimage import shift as ndi_shift
from skimage.registration import phase_cross_correlation

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.prechecks import check_idle
from lasx.readers import get_job_settings, get_lasx_settings
from lasx.utils import parse_tile_geometry


REPO_ROOT = Path(__file__).resolve().parent.parent
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = Path(args.output) if args.output else (
    REPO_ROOT / "config" / "alignment" / f"registration_dry_{TIMESTAMP}"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)


def connect_client():
    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        print("ABORT: Cannot connect to LAS X.")
        sys.exit(1)
    if not drv.ping(client):
        print("ABORT: ping failed")
        sys.exit(1)
    drv.set_stage_limits(
        x_min=1000, x_max=130000,
        y_min=1000, y_max=100000,
        z_galvo_min=-200, z_galvo_max=200,
        z_wide_min=0, z_wide_max=25000,
    )
    return client


def to_uint8(image):
    scaled = image.astype(np.float64)
    scaled = scaled / (scaled.max() or 1.0) * 255.0
    return scaled.astype(np.uint8)


def overlay(reference, moving):
    ref_norm = reference.astype(np.float64) / (reference.max() or 1.0)
    mov_norm = moving.astype(np.float64) / (moving.max() or 1.0)
    rgb = np.zeros((*reference.shape, 3), dtype=np.float64)
    rgb[..., 1] = ref_norm
    rgb[..., 0] = mov_norm
    rgb[..., 2] = mov_norm
    return np.clip(rgb, 0.0, 1.0)


def acquire_image(client, label):
    settings = get_job_settings(client, args.job)
    geometry = parse_tile_geometry(settings)
    stage = drv.get_xy(client)

    idle = check_idle(client, timeout=30)
    if not idle["success"]:
        print("WARNING: scanner not idle")

    baseline = drv.read_relative_path(client)
    acquire_start = time.time()
    result = drv.acquire(client, args.job)
    if not result or not result.get("success"):
        raise RuntimeError(f"{label} acquire failed: {result}")

    media_path = get_lasx_settings()["export"]["media_path"]
    detected = drv.detect_new_files(client, baseline, media_path, acquire_start=acquire_start)
    if not detected["success"]:
        raise RuntimeError(f"{label} file detection failed: {detected.get('error')}")

    image_path = Path(sorted(detected["image_files"])[0])
    image = tifffile.imread(str(image_path))
    if image.ndim == 3:
        image = image[0]

    return {
        "label": label,
        "image": image,
        "image_path": str(image_path),
        "pixel_um": float(geometry["pixel_w_um"]),
        "stage_x_um": float(stage["x_um"]),
        "stage_y_um": float(stage["y_um"]),
    }


def register_images(reference, moving, pixel_um):
    ref8 = to_uint8(reference)
    mov8 = to_uint8(moving)
    height, width = mov8.shape
    margin_y = max(1, height // 4)
    margin_x = max(1, width // 4)
    template = mov8[margin_y:height - margin_y, margin_x:width - margin_x]
    if template.size == 0:
        raise RuntimeError("Image is too small for NCC template extraction")

    ncc_result = cv2.matchTemplate(ref8, template, cv2.TM_CCOEFF_NORMED)
    _, ncc_quality, _, max_loc = cv2.minMaxLoc(ncc_result)
    ncc_dx_px = max_loc[0] + template.shape[1] / 2.0 - width / 2.0
    ncc_dy_px = max_loc[1] + template.shape[0] / 2.0 - height / 2.0

    ref_mask = reference > np.percentile(reference, args.mask_pct)
    mov_mask = moving > np.percentile(moving, args.mask_pct)
    shift_px, _, _ = phase_cross_correlation(
        reference.astype(np.float64),
        moving.astype(np.float64),
        upsample_factor=args.upsample,
        reference_mask=ref_mask,
        moving_mask=mov_mask,
    )
    sub_dy_px = float(shift_px[0])
    sub_dx_px = float(shift_px[1])

    return {
        "dx_px": sub_dx_px,
        "dy_px": sub_dy_px,
        "dx_um": sub_dx_px * pixel_um,
        "dy_um": sub_dy_px * pixel_um,
        "dist_px": float(np.hypot(sub_dx_px, sub_dy_px)),
        "dist_um": float(np.hypot(sub_dx_px * pixel_um, sub_dy_px * pixel_um)),
        "ncc_dx_px": float(ncc_dx_px),
        "ncc_dy_px": float(ncc_dy_px),
        "ncc_dx_um": float(ncc_dx_px * pixel_um),
        "ncc_dy_um": float(ncc_dy_px * pixel_um),
        "ncc_quality": float(ncc_quality),
        "agreement_um": float(np.hypot(
            (ncc_dx_px - sub_dx_px) * pixel_um,
            (ncc_dy_px - sub_dy_px) * pixel_um,
        )),
    }


def save_report(reference, moving, aligned, registration):
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.patch.set_facecolor("white")

    axes[0].imshow(reference, cmap="gray")
    axes[0].set_title("Reference")
    axes[0].axis("off")

    axes[1].imshow(overlay(reference, moving))
    axes[1].set_title(
        "Before registration\n"
        f"({registration['dx_um']:+.2f}, {registration['dy_um']:+.2f}) um"
    )
    axes[1].axis("off")

    axes[2].imshow(overlay(reference, aligned))
    axes[2].set_title(
        "After registration\n"
        f"NCC {registration['ncc_quality']:.3f} | agreement {registration['agreement_um']:.2f} um"
    )
    axes[2].axis("off")

    fig.suptitle(f"Dry Registration Check  {TIMESTAMP}", fontsize=14, fontweight="bold")
    fig.savefig(str(OUT_DIR / "report.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def move_stage(client, target_x_um, target_y_um):
    result = drv.move_xy(client, target_x_um, target_y_um)
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(f"move_xy failed: {result}")
    time.sleep(args.settle)


def main():
    print("=" * 60)
    print("Dry Registration Check")
    print("=" * 60)
    print(f"Job:    {args.job}")
    print(f"Output: {OUT_DIR}")

    client = connect_client()
    reference = None
    target = None
    moved_programmatically = False

    try:
        print("\nStep 1: acquire reference image")
        reference = acquire_image(client, "reference")
        tifffile.imwrite(str(OUT_DIR / "reference.tif"), reference["image"])

        print(
            f"Reference stage: ({reference['stage_x_um']:.2f}, "
            f"{reference['stage_y_um']:.2f}) um"
        )
        print(f"Pixel size:      {reference['pixel_um']:.4f} um")

        if args.manual:
            print("\nStep 2: move manually, then acquire target image")
            input("Move the stage, then press Enter to acquire the target image... ")
        else:
            target_x_um = reference["stage_x_um"] + args.move_x_um
            target_y_um = reference["stage_y_um"] + args.move_y_um
            print("\nStep 2: move stage, then acquire target image")
            print(f"Requested move:  ({args.move_x_um:+.2f}, {args.move_y_um:+.2f}) um")
            move_stage(client, target_x_um, target_y_um)
            moved_programmatically = True

        target = acquire_image(client, "target")
        tifffile.imwrite(str(OUT_DIR / "target.tif"), target["image"])

        pixel_delta = abs(target["pixel_um"] - reference["pixel_um"])
        if pixel_delta > 1e-9:
            print(
                "WARNING: pixel size changed between acquisitions: "
                f"{reference['pixel_um']:.4f} -> {target['pixel_um']:.4f} um"
            )

        stage_dx_um = target["stage_x_um"] - reference["stage_x_um"]
        stage_dy_um = target["stage_y_um"] - reference["stage_y_um"]
        stage_dist_um = float(np.hypot(stage_dx_um, stage_dy_um))

        registration = register_images(
            reference["image"],
            target["image"],
            reference["pixel_um"],
        )
        aligned = ndi_shift(
            target["image"].astype(np.float64),
            shift=(registration["dy_px"], registration["dx_px"]),
            order=1,
            mode="nearest",
        )
        save_report(reference["image"], target["image"], aligned, registration)

        tifffile.imwrite(
            str(OUT_DIR / "target_registered_preview.tif"),
            np.clip(aligned, 0, np.iinfo(target["image"].dtype).max).astype(target["image"].dtype),
        )

        summary = {
            "timestamp": TIMESTAMP,
            "job": args.job,
            "manual_move": bool(args.manual),
            "reference": {
                "image_path": reference["image_path"],
                "stage_xy_um": [reference["stage_x_um"], reference["stage_y_um"]],
                "pixel_um": reference["pixel_um"],
            },
            "target": {
                "image_path": target["image_path"],
                "stage_xy_um": [target["stage_x_um"], target["stage_y_um"]],
                "pixel_um": target["pixel_um"],
            },
            "stage_delta_xy_um": [stage_dx_um, stage_dy_um],
            "stage_delta_dist_um": stage_dist_um,
            "registration": registration,
        }
        (OUT_DIR / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print("\nResults")
        print("-" * 60)
        print(f"Target stage:    ({target['stage_x_um']:.2f}, {target['stage_y_um']:.2f}) um")
        print(f"Stage delta:     ({stage_dx_um:+.2f}, {stage_dy_um:+.2f}) um  =  {stage_dist_um:.2f} um")
        print(
            f"Image shift:     ({registration['dx_um']:+.2f}, {registration['dy_um']:+.2f}) um  "
            f"=  {registration['dist_um']:.2f} um"
        )
        print(
            f"Image shift px:  ({registration['dx_px']:+.3f}, {registration['dy_px']:+.3f}) px  "
            f"=  {registration['dist_px']:.3f} px"
        )
        print(
            f"NCC shift:       ({registration['ncc_dx_um']:+.2f}, {registration['ncc_dy_um']:+.2f}) um"
        )
        print(
            f"NCC quality:     {registration['ncc_quality']:.3f}  |  "
            f"method agreement: {registration['agreement_um']:.2f} um"
        )
        if stage_dist_um > 0:
            print(f"Magnitude ratio: {registration['dist_um'] / stage_dist_um:.3f}")
        print(f"Artifacts:       {OUT_DIR}")

    except Exception as exc:
        print(f"\nABORT: {exc}")
        sys.exit(1)
    finally:
        if args.restore_stage and moved_programmatically and reference is not None:
            try:
                print(
                    "\nRestoring stage: "
                    f"({reference['stage_x_um']:.2f}, {reference['stage_y_um']:.2f}) um"
                )
                move_stage(client, reference["stage_x_um"], reference["stage_y_um"])
            except Exception as restore_exc:
                print(f"WARNING: stage restore failed: {restore_exc}")


if __name__ == "__main__":
    main()
