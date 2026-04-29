"""
calibrate_objectives.py — unified objective-switch calibration.

One script. Writes the live calibration to ``calibration/config/config.json``
and per-run snapshots to ``calibration/runs/<ts>/``.

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

4. **Parcentric XY (image residual)** – optional (``--measure-xy``).
   Acquires a high-quality slice on each objective and uses multi-method
   voting registration to measure the residual beyond the motor delta.
   If ``--measure-parfocal`` is omitted, both slices are acquired at
   z-galvo 0; this is the preferred dry-objective path when the lenses
   are parfocal in practice.

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
    python calibrate_objectives.py --job Overview --ref-slot 1 --target-slots 2 \\
        --ref-zoom 3.0 --measure-xy --verify
    python calibrate_objectives.py --job Overview --target-slots 2 \\
        --measure-parfocal             # incremental: only refresh slot 2 dZ
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.machine_config import (
    load_machine_config,
    save_machine_config,
    load_stage_config,
    set_reference,
    set_sign_convention,
    update_target,
    save_calibration_report,
    make_run_dir,
    now_timestamp,
    MACHINE_SCHEMA_VERSION,
)
from navigator_expert.calibration.lib.lasx_state import (
    apply_stage_limits,
    configure_z_stack,
    disable_z_stack,
    make_acquirer,
    setup_reference_state,
    switch_to_target,
)
from navigator_expert.calibration.lib.registration import (
    VOTING_MIN_AGREE,
    _VOTING_METHODS,
    brenner_focus,
)
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
    p.add_argument("--measure-parfocal", action="store_true",
                   help="Measure parfocal Z shift via Z-stacks (slow).")
    p.add_argument("--measure-xy", action="store_true",
                   help="Measure parcentric XY shift "
                        "(uses z-galvo 0 unless --measure-parfocal).")

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
    phases_to_run = ["sign"] if measure_sign else []
    phases_to_run.append("offset")
    if args.measure_parfocal:
        phases_to_run.append("parfocal_shift")
    if args.measure_xy:
        phases_to_run.append("parcentric_shift")

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
    set_reference(machine_cfg, args.ref_slot,
                  summary=ref_summary, anchor_xy_um=home_xy)

    acquire_single, acquire_stack = make_acquirer(client, args.job, stage_cfg)

    report = {
        "schema_version": MACHINE_SCHEMA_VERSION,
        "timestamp": now_timestamp(),
        "machine_config": "machine.json",
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

        if args.measure_xy:
            log.info("phase 4 prep: ref focus slice at z-galvo=%+.2f", ref_z_galvo_um)
            disable_z_stack(client, args.job)
            drv.set_z_stack_definition(client, args.job,
                                       begin_um=ref_z_galvo_um,
                                       end_um=ref_z_galvo_um)
            img_ref_focus = acquire_single()
    elif args.measure_xy:
        log.info("phase 4 prep: ref slice at z-galvo=+0.00 (parfocal skipped)")
        disable_z_stack(client, args.job)
        drv.set_z_stack_definition(client, args.job, begin_um=0.0, end_um=0.0)
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

        switch_to_target(client, args.job, hw, ts,
                         settle_s=args.settle, zoom=ts_zoom,
                         scan_format=args.scan_format,
                         scan_speed=args.scan_speed)

        target_report = {}
        target_update = {"summary": ts_summary}
        dz_um = 0.0

        # Phase 2: parcentric offset (firmware get_xy delta on switch).
        # Diagnostic only — recorded so operators can track firmware
        # behaviour over time. Cookbook math does not use it.
        offset_um, offset_report = phases.measure_parcentric_offset(client, home_xy)
        target_report["offset"] = offset_report
        target_update["parcentric_offset_um"] = offset_um

        # Phase 3: parfocal Z shift (optional).
        if args.measure_parfocal:
            dz_um, dz_residual_um, parfocal_report = phases.measure_parfocal(
                client, args.job,
                acquire_stack=acquire_stack,
                ref_focus=ref_focus,
                z_range_um=args.z_range_um,
                z_step_um=args.z_step_um,
            )
            target_report["parfocal"] = parfocal_report
            target_update["parfocal_shift_um"] = dz_um
            # parfocal_offset_um is not currently measured (no Z get/set
            # readback delta). We could capture it via drv.get_z if the
            # firmware moves Z on objective switch.

        # Phase 4: parcentric XY shift via registration with stage parked
        # at home_xy. This is THE value the cookbook applies. (optional)
        if args.measure_xy:
            shift_xy, shift_report = phases.measure_parcentric_shift(
                client, args.job,
                acquire_single=acquire_single,
                img_ref_focus=img_ref_focus,
                home_xy=home_xy,
                dz_um=dz_um,
                image_to_stage=image_to_stage,
                ts_zoom=ts_zoom,
                voting_min_agree=VOTING_MIN_AGREE,
                voting_method_count=len(_VOTING_METHODS),
            )
            target_report["parcentric_shift"] = shift_report
            if shift_xy is not None:
                target_update["parcentric_shift_um"] = list(shift_xy)

        update_target(machine_cfg, ts, **target_update)
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
    live_path = save_machine_config(machine_cfg, run_dir)
    report_path = save_calibration_report(report, run_dir)

    print(f"\nLive config:        {live_path}")
    print(f"Run folder:         {run_dir}")
    print(f"  config:           {run_dir / 'config.json'}")
    print(f"  report:           {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
