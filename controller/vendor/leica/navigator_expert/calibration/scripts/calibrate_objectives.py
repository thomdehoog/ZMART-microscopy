"""
calibrate_objectives.py — unified objective-switch calibration.

One script. Writes the live calibration to ``calibration/config/config.json``
and per-run snapshots to ``calibration/runs/<ts>/``.

Z model
-------
Z-galvo is held at 0 throughout. All Z motion lives on z-wide:
    - The firmware moves z-wide on every objective switch (parfocal
      compensation). The script reads z-wide before and after each
      switch via ``zPosition.z-wide`` and stores the delta as
      ``zwide_offset_um``. Diagnostic only — firmware re-applies it on
      every switch, so the cookbook does NOT re-apply it.
    - Whatever focus residual the firmware leaves behind is measured
      by Phase 3: a Brenner z-stack scanned on z-wide. The peak gives
      ``zwide_shift_um``, which the cookbook applies on z-wide via
      ``move_z(z_mode='zwide')``.

Phases (in order)
-----------------
1. **Sign convention** — under the reference objective. Stage moves +X
   then +Y, fits a 2x2 image->stage Jacobian, snaps to the nearest D4
   reflection/rotation. Reuses the cached value if ``image_to_stage`` is
   already in the config; pass ``--measure-sign`` to force a re-measure.

2. **Firmware XY offset** — per target, read XY before/after the
   objective switch. Diagnostic only: written to the run report, **not**
   persisted to ``config.json``. The cookbook commands an absolute XY
   after the switch, so this delta isn't part of the correction.

3. **Shift Z (z-wide)** — optional (``--measure-shift-z``). Brenner
   z-stack scanned on z-wide centred at the post-switch z-wide. Peak
   gives ``shift_z_um``. Phase parks z-wide at the peak so phase 4
   acquires in focus.

4. **Shift XY (registration)** — optional (``--measure-shift-xy``).
   Stage parked at the same XY for both acquires; multi-method voting
   registration (phase / masked / NCC / ORB) measures the optical-axis
   shift. The result is the value the cookbook applies. Persisted as
   ``shift_xy_um`` only if voting reaches the configured agreement
   threshold; on low confidence the field is left unset rather than
   recording garbage. If ``--measure-shift-z`` ran, z-wide is at the
   focus peak; otherwise z-wide is at the post-switch firmware
   position and registration may have to fight an out-of-focus image.

Stage state and backlash
------------------------
Every acquisition is preceded by a +X+Y backlash takeup. Stage limits
and takeup parameters come from ``config/stage.json``.

Reference state
---------------
Every phase starts from a known reference state: reference slot active,
pan/ROI reset, Z-stack disabled, zoom at ``--ref-zoom``, z-galvo zeroed,
LAS X idle, AFC off. The script restores this state between targets
and on exit.

Operator preconditions
----------------------
- ``--job`` is the currently selected job in LAS X.
- ImageTransformation is TOPLEFT.
- AFC is off; no LAS X modal dialogs.
- The stage is over a region with enough texture for image registration.
- The reference objective is in focus on the operator's z-wide setting
  before the run starts (z-galvo will be forced to 0).

Usage
-----
    # Fast dry-pair path: skip shift_z (firmware-only z-wide), just
    # measure shift_xy at the post-switch firmware focus.
    python calibrate_objectives.py --job Overview --ref-slot 1 \\
        --target-slots 2 --ref-zoom 3.0 --measure-shift-xy

    # Full run with shift_z (z-wide residual) and shift_xy.
    python calibrate_objectives.py --job Overview --ref-slot 1 \\
        --target-slots 2 --ref-zoom 3.0 \\
        --measure-shift-z --measure-shift-xy \\
        --z-range-um 100 --z-step-um 2

    # Incremental: only refresh slot 2 shift_z; reuses cached sign.
    python calibrate_objectives.py --job Overview --target-slots 2 \\
        --measure-shift-z --z-range-um 100 --z-step-um 2
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.calibration import (
    SCHEMA_VERSION as CALIBRATION_SCHEMA_VERSION,
    load_calibration,
    save_calibration,
    save_calibration_report,
    make_run_dir,
    now_timestamp,
    set_image_to_stage,
    update_objective,
)
from navigator_expert.driver.stage_config import load as load_stage_config
from navigator_expert.calibration.lib.lasx_state import (
    disable_z_stack,
    make_acquirer,
    setup_reference_state,
    switch_to_target,
)
from navigator_expert.analysis import VOTING_MIN_AGREE
from navigator_expert.calibration.lib import phases


log = logging.getLogger("calibrate_objectives")


# ── Constants ────────────────────────────────────────────────────

REF_ZOOM_DEFAULT = 1.0
SETTLE_S_DEFAULT = 3.0
SIGN_MOVE_UM_DEFAULT = 30.0
SIGN_SETTLE_S_DEFAULT = 1.0
Z_RANGE_UM_DEFAULT = 15.0
Z_STEP_UM_DEFAULT = 1.0
SCAN_FORMAT_DEFAULT = "1024 x 1024"  # higher pixel density helps NCC on thin texture
SCAN_SPEED_DEFAULT = 600
ZOOM_MIN = 0.75  # Leica hardware floor; below this LAS X silently clamps


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
    p.add_argument("--measure-shift-z", action="store_true",
                   help="Measure z-wide focus residual via a Brenner stack "
                        "on z-wide (slow). Persists ``shift_z_um``.")
    p.add_argument("--measure-shift-xy", action="store_true",
                   help="Measure optical-axis XY shift via voting "
                        "registration. Z-galvo stays at 0; if "
                        "--measure-shift-z also ran, z-wide is at the focus "
                        "peak. Persists ``shift_xy_um``.")

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
    p.add_argument("--scan-format", default=SCAN_FORMAT_DEFAULT,
                   help=f"Image dimensions, e.g. '1024 x 1024' "
                        f"(default: {SCAN_FORMAT_DEFAULT!r}).")
    p.add_argument("--scan-speed", type=int, default=SCAN_SPEED_DEFAULT,
                   help=f"Scan speed in Hz (default: {SCAN_SPEED_DEFAULT}).")
    return p.parse_args()




# ── Orchestrator ──────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args()

    if args.ref_slot in args.target_slots:
        print("ABORT: --ref-slot cannot appear in --target-slots.")
        return 2

    stage_cfg = load_stage_config()
    cal_cfg = load_calibration(create_if_missing=True)

    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        print("ABORT: cannot connect to LAS X.")
        return 2
    if not drv.ping(client):
        print("ABORT: LAS X ping failed.")
        return 2

    drv.apply_stage_limits_from_config(stage_cfg)

    hw = drv.get_hardware_info(client)
    if not hw:
        print("ABORT: could not read hardware info.")
        return 2

    drv.validate_slots(hw, args.ref_slot, args.target_slots)
    by_slot = drv.objective_by_slot(hw)
    ref_summary = drv.objective_summary(by_slot[args.ref_slot])
    targets_summary = {s: drv.objective_summary(by_slot[s]) for s in args.target_slots}

    measure_sign = args.measure_sign or cal_cfg.get("image_to_stage") is None
    phases_to_run = ["sign"] if measure_sign else []
    phases_to_run.append("xy_firmware_delta")
    if args.measure_shift_z:
        phases_to_run.append("shift_z")
    if args.measure_shift_xy:
        phases_to_run.append("shift_xy")

    print(f"Job:          {args.job}")
    print(f"Reference:    slot {args.ref_slot}  ({ref_summary['name']})")
    for s, sm in targets_summary.items():
        print(f"Target:       slot {s}  ({sm['name']})")
    print(f"Phases:       {', '.join(phases_to_run)}\n")

    setup_reference_state(client, args.job, hw,
                          ref_slot=args.ref_slot, ref_zoom=args.ref_zoom,
                          settle_s=args.settle,
                          scan_format=args.scan_format,
                          scan_speed=args.scan_speed)

    geo = drv.parse_tile_geometry(drv.get_job_settings(client, args.job) or {})
    pixel_size_um = float(geo["pixel_w_um"])
    log.info("ref pixel size = %.4f um (FOV %.1f um)",
             pixel_size_um, float(geo["tile_w_um"]))

    home = drv.get_xy(client)
    home_xy = (float(home["x_um"]), float(home["y_um"]))
    cal_cfg["reference_objective_slot"] = args.ref_slot
    update_objective(cal_cfg, args.ref_slot,
                     name=ref_summary["name"],
                     shift_xy_um=(0.0, 0.0),
                     offset_z_um=0.0,
                     shift_z_um=0.0)

    acquire_single, acquire_stack = make_acquirer(client, args.job, stage_cfg)

    report = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "timestamp": now_timestamp(),
        "calibration_file": "config.json",
        "phases_run": list(phases_to_run),
        "settings": {
            "ref_slot": args.ref_slot,
            "target_slots": list(args.target_slots),
            "ref_zoom": args.ref_zoom,
            "settle_s": args.settle,
            "sign_move_um": args.sign_move_um,
            "z_range_um": args.z_range_um,
            "z_step_um": args.z_step_um,
            "scan_format": args.scan_format,
            "scan_speed": args.scan_speed,
            "backlash_overshoot_um": stage_cfg["backlash"]["overshoot_um"],
            "backlash_settle_ms": stage_cfg["backlash"]["settle_ms"],
        },
        "reference_objective": ref_summary,
        "anchor_xy_um": list(home_xy),
        "sign_convention": None,
        "per_target": {},
    }

    # ── Phase 1: sign convention ────────────────────────────────
    if "sign" in phases_to_run:
        sign = phases.measure_sign_convention(
            client, acquire_single,
            pixel_size_um=pixel_size_um,
            move_um=args.sign_move_um,
            settle_s=args.sign_settle,
        )
        set_image_to_stage(cal_cfg, sign["image_to_stage_um"])
        report["sign_convention"] = sign
    else:
        log.info("sign convention: reusing cached value from config.json")

    image_to_stage = cal_cfg["image_to_stage"]

    # ── Pre-acquire reference focus slice (for phase 4) ─────────
    # Z-galvo is already 0 (setup_reference_state forced it). The
    # operator focused via z-wide before starting the run, so the
    # reference is in focus at the current z-wide. No Brenner search
    # on the reference: the reference's "focus" is whatever the
    # operator chose, by definition.
    img_ref_focus = None
    if args.measure_shift_xy:
        log.info("phase 4 prep: ref slice at galvo=0, operator-focused z-wide")
        disable_z_stack(client, args.job)
        img_ref_focus = acquire_single()

    # ── Per-target loop ─────────────────────────────────────────
    for ts in args.target_slots:
        log.info("=== target slot %d ===", ts)
        ts_summary = targets_summary[ts]
        # Match the reference FOV: target_zoom = ref_zoom * ref_mag / tgt_mag
        ts_zoom_ideal = args.ref_zoom * ref_summary["magnification"] / ts_summary["magnification"]
        ts_zoom = max(ZOOM_MIN, ts_zoom_ideal)
        if ts_zoom > ts_zoom_ideal:
            min_ref_zoom = ZOOM_MIN * ts_summary["magnification"] / ref_summary["magnification"]
            log.warning(
                "target zoom %.3f below hardware min %.2f; clamping to %.2f. "
                "FOV will not match ref — phase 4 voting quality may degrade. "
                "To match FOV, rerun with --ref-zoom %.2f or higher.",
                ts_zoom_ideal, ZOOM_MIN, ZOOM_MIN, min_ref_zoom,
            )

        # Read z-wide BEFORE the firmware switch so we can compute the
        # offset the firmware applies.
        zwide_pre_um = drv.read_zwide_um(client, args.job)
        log.info("z-wide before switch: %.2f um", zwide_pre_um)

        switch_to_target(client, args.job, hw, ts,
                         settle_s=args.settle, zoom=ts_zoom,
                         scan_format=args.scan_format,
                         scan_speed=args.scan_speed)

        zwide_post_um = drv.read_zwide_um(client, args.job)
        zwide_offset_um = float(zwide_post_um - zwide_pre_um)
        log.info("z-wide after switch:  %.2f um  (offset = %+.2f)",
                 zwide_post_um, zwide_offset_um)

        target_report = {
            "summary": ts_summary,
            "zwide_pre_switch_um": zwide_pre_um,
            "zwide_post_switch_um": zwide_post_um,
            "offset_z_um": zwide_offset_um,
        }
        update_kwargs = {
            "name": ts_summary["name"],
            "offset_z_um": zwide_offset_um,
        }

        # Phase 2: firmware get_xy delta on switch. Diagnostic only —
        # recorded in the run report so operators can track firmware
        # behaviour over time. Not persisted in the live calibration
        # because the cookbook commands an absolute XY after the switch.
        _, xy_delta_report = phases.measure_xy_firmware_delta(client, home_xy)
        target_report["xy_firmware_delta"] = xy_delta_report

        # Phase 3: shift_z — z-wide focus residual (optional).
        # Leaves z-wide parked at the Brenner peak.
        if args.measure_shift_z:
            shift_um, shift_z_report = phases.measure_shift_z(
                client, args.job,
                acquire_stack=acquire_stack,
                z_range_um=args.z_range_um,
                z_step_um=args.z_step_um,
                zwide_post_switch_um=zwide_post_um,
            )
            target_report["shift_z"] = shift_z_report
            update_kwargs["shift_z_um"] = shift_um

        # Phase 4: shift_xy — optical-axis XY shift via voting
        # registration at home_xy. THE value the cookbook applies. (optional)
        if args.measure_shift_xy:
            shift_xy, shift_xy_report = phases.measure_shift_xy(
                client, args.job,
                acquire_single=acquire_single,
                img_ref_focus=img_ref_focus,
                home_xy=home_xy,
                image_to_stage=image_to_stage,
                ts_zoom=ts_zoom,
                voting_min_agree=VOTING_MIN_AGREE,
            )
            target_report["shift_xy"] = shift_xy_report
            if shift_xy is not None:
                update_kwargs["shift_xy_um"] = shift_xy

        update_objective(cal_cfg, ts, **update_kwargs)
        report["per_target"][str(ts)] = target_report

        if ts != args.target_slots[-1]:
            setup_reference_state(client, args.job, hw,
                                  ref_slot=args.ref_slot,
                                  ref_zoom=args.ref_zoom,
                                  settle_s=args.settle,
                                  scan_format=args.scan_format,
                                  scan_speed=args.scan_speed)

    # ── Restore + persist ──────────────────────────────────────
    log.info("restoring reference state")
    setup_reference_state(client, args.job, hw,
                          ref_slot=args.ref_slot, ref_zoom=args.ref_zoom,
                          settle_s=args.settle,
                          scan_format=args.scan_format,
                          scan_speed=args.scan_speed)
    drv.move_xy_stage(client, home_xy[0], home_xy[1], unit="um", tolerance=20.0)

    run_dir = make_run_dir(report["timestamp"])
    live_path = save_calibration(cal_cfg, run_dir)
    report_path = save_calibration_report(report, run_dir)

    print(f"\nLive config:        {live_path}")
    print(f"Run folder:         {run_dir}")
    print(f"  config:           {run_dir / 'config.json'}")
    print(f"  report:           {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
