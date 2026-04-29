"""One-off: measure the parcentric offset between two objectives by
acquiring at the same stage XY with each, registering, and reporting the
stage-frame shift.

No motor_delta. No residual-after-firmware. Single measurement.

Run from the project root:
    python vendor/leica/navigator_expert/calibration/scripts/measure_parcentric_only.py \
        --job Overview --source-slot 1 --target-slot 2

The stage parks at whatever XY it is when this script starts; that's the
anchor. After switching to the target slot the script *moves the stage
back to the anchor*, cancelling whatever the firmware did on switch, so
the registration measures purely the optical-center difference between
the two objectives.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.machine_config import (
    load_machine_config,
    load_stage_config,
)
from navigator_expert.calibration.lib.lasx_state import (
    apply_stage_limits,
    disable_z_stack,
    make_acquirer,
    reset_pan_roi_zstack,
    reselect_job,
    apply_scan_format_and_speed,
)
from navigator_expert.calibration.lib.registration import register_voting

log = logging.getLogger("measure_parcentric_only")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--job", required=True)
    p.add_argument("--source-slot", type=int, default=1)
    p.add_argument("--target-slot", type=int, default=2)
    p.add_argument("--source-zoom", type=float, default=3.0,
                   help="Zoom on source objective (default: 3.0).")
    p.add_argument("--target-zoom", type=float, default=1.5,
                   help="Zoom on target objective; should match source FOV "
                        "(default: 1.5 = 3.0 * 10/20 for slot1->slot2).")
    p.add_argument("--scan-format", default="1024 x 1024")
    p.add_argument("--scan-speed", type=int, default=600)
    p.add_argument("--settle", type=float, default=3.0)
    return p.parse_args()


def setup_objective(client, job, hw, slot, *, zoom, settle_s,
                    scan_format, scan_speed):
    log.info("setup slot=%d zoom=%.2f", slot, zoom)
    r = drv.set_objective(client, job, hw, slot_index=slot)
    if not r or not r.get("success"):
        raise RuntimeError(f"objective switch to slot {slot} failed: {r}")
    time.sleep(settle_s)
    reselect_job(client, job)
    reset_pan_roi_zstack(client, job)
    drv.set_zoom(client, job, zoom)
    apply_scan_format_and_speed(client, job, scan_format, scan_speed)
    time.sleep(1.0)
    disable_z_stack(client, job)
    drv.set_z_stack_definition(client, job, begin_um=0.0, end_um=0.0)
    time.sleep(1.0)
    idle = drv.check_idle(client, timeout=30)
    if not idle or not idle.get("success"):
        raise RuntimeError(f"LAS X not idle: {idle}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args()
    if args.source_slot == args.target_slot:
        print("ABORT: source and target slots must differ.")
        return 2

    stage_cfg = load_stage_config()
    machine_cfg = load_machine_config(create_if_missing=False)
    image_to_stage = machine_cfg["image_to_stage"]
    log.info("image_to_stage: %s", image_to_stage)

    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        print("ABORT: cannot connect to LAS X."); return 2
    if not drv.ping(client):
        print("ABORT: ping failed."); return 2
    apply_stage_limits(stage_cfg)
    hw = drv.get_hardware_info(client)
    if not hw:
        print("ABORT: no hardware info."); return 2
    drv.validate_slots(hw, args.source_slot, [args.target_slot])

    acquire_single, _ = make_acquirer(client, args.job, stage_cfg)

    # 1. Source slot at the current stage XY (= anchor for this measurement).
    setup_objective(client, args.job, hw, args.source_slot,
                    zoom=args.source_zoom, settle_s=args.settle,
                    scan_format=args.scan_format, scan_speed=args.scan_speed)
    anchor = drv.get_xy(client)
    anchor_xy = (float(anchor["x_um"]), float(anchor["y_um"]))
    log.info("anchor (source slot, slot %d): (%.3f, %.3f) um",
             args.source_slot, *anchor_xy)
    img_ref = acquire_single()
    src_geo = drv.parse_tile_geometry(drv.get_job_settings(client, args.job) or {})
    src_pixel_um = float(src_geo["pixel_w_um"])
    log.info("source pixel size: %.4f um", src_pixel_um)

    # 2. Switch to target slot. Whatever firmware does to the stage on switch,
    #    we explicitly move it back to anchor_xy before acquiring.
    setup_objective(client, args.job, hw, args.target_slot,
                    zoom=args.target_zoom, settle_s=args.settle,
                    scan_format=args.scan_format, scan_speed=args.scan_speed)
    after_switch = drv.get_xy(client)
    motor_shift = (
        float(after_switch["x_um"] - anchor_xy[0]),
        float(after_switch["y_um"] - anchor_xy[1]),
    )
    log.info("firmware moved stage by (%+.3f, %+.3f) um on switch — cancelling",
             *motor_shift)
    r = drv.move_xy_stage(client, anchor_xy[0], anchor_xy[1],
                          unit="um", tolerance=0.5)
    if not r or not r.get("success"):
        raise RuntimeError(f"move back to anchor failed: {r}")
    time.sleep(1.0)
    back_at_anchor = drv.get_xy(client)
    log.info("stage back at anchor: (%.3f, %.3f) um (diff: (%+.3f, %+.3f))",
             back_at_anchor["x_um"], back_at_anchor["y_um"],
             back_at_anchor["x_um"] - anchor_xy[0],
             back_at_anchor["y_um"] - anchor_xy[1])

    img_tgt = acquire_single()
    tgt_geo = drv.parse_tile_geometry(drv.get_job_settings(client, args.job) or {})
    tgt_pixel_um = float(tgt_geo["pixel_w_um"])
    log.info("target pixel size: %.4f um", tgt_pixel_um)

    # 3. Register and convert to stage frame.
    vote = register_voting(img_ref, img_tgt, tgt_pixel_um)
    log.info("voting: agreeing=%s confidence=%d trusted=%s quality=%.3f",
             vote["agreeing"], vote["confidence"],
             vote["trusted"], vote["quality"])
    log.info("per-method: %s",
             ", ".join(f"{n}=({m.get('dx_um','-'):+.2f},{m.get('dy_um','-'):+.2f})"
                       for n, m in vote["per_method"].items()
                       if m.get("dx_um") is not None
                       and m.get("dy_um") is not None))
    raw_dx, raw_dy = vote["dx_um"], vote["dy_um"]
    stage_dx = image_to_stage[0][0] * raw_dx + image_to_stage[0][1] * raw_dy
    stage_dy = image_to_stage[1][0] * raw_dx + image_to_stage[1][1] * raw_dy

    print()
    print(f"Anchor (stage XY at measurement):  ({anchor_xy[0]:.3f}, {anchor_xy[1]:.3f}) um")
    print(f"Firmware shift on slot{args.source_slot}->slot{args.target_slot} switch: "
          f"({motor_shift[0]:+.3f}, {motor_shift[1]:+.3f}) um  (cancelled)")
    print(f"Image-frame shift (slot1 vs slot2 at same XY): "
          f"({raw_dx:+.3f}, {raw_dy:+.3f}) um")
    print(f"Parcentric offset (stage frame, image_to_stage applied): "
          f"({stage_dx:+.3f}, {stage_dy:+.3f}) um")
    print()
    print("Compare with config.json's stored values:")
    obj_cfg = (machine_cfg.get("objectives") or {}).get(str(args.target_slot)) or {}
    parc = obj_cfg.get("parcentric_xy") or {}
    print(f"  config motor_um:    {parc.get('motor_um')}")
    print(f"  config residual_um: {parc.get('residual_um')}")
    print(f"  config motor+res:   "
          f"{[parc['motor_um'][i] + parc['residual_um'][i] for i in range(2)] if parc.get('motor_um') and parc.get('residual_um') else 'n/a'}")

    # Restore source slot
    setup_objective(client, args.job, hw, args.source_slot,
                    zoom=args.source_zoom, settle_s=args.settle,
                    scan_format=args.scan_format, scan_speed=args.scan_speed)
    drv.move_xy_stage(client, anchor_xy[0], anchor_xy[1],
                      unit="um", tolerance=0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
