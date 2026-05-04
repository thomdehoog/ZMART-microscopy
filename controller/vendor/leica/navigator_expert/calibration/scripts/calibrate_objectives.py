"""
calibrate_objectives.py — unified objective-switch calibration.

One script. Writes the live calibration to ``calibration/config/config.json``
and per-run snapshots to ``calibration/runs/<ts>/``.

Z model
-------
Z-galvo is held at 0 throughout. All Z motion lives on z-wide:
    - The firmware moves z-wide on every objective switch (parfocal
      compensation). ``offset_z_um`` is the cumulative z-wide motion
      from the operator's reference focus (read at the start of the
      run) to the post-switch z-wide of the current target. Firmware
      re-applies it on every switch, so the cookbook does NOT.
    - ``shift_z_um`` is the difference between the target Brenner
      peak and the reference Brenner peak, minus ``offset_z_um``.
      That is what the cookbook applies on z-wide after the firmware
      has done its parfocal compensation.

Phases (in order)
-----------------
1. **Sign convention** — under the reference objective; always runs.
   Stage moves +X then +Y, fits a 2x2 image->stage Jacobian, snaps
   to the nearest D4 reflection/rotation.

2. **Reference Brenner** — under the reference objective, runs when
   shift_z or shift_xy is requested. One stack on z-wide gives the
   reference's optical focus (``peak_zwide_um``) and the in-focus
   slice used as the registration anchor for shift_xy. Z-wide is
   restored to the operator's setting after the stack.

3. **Firmware XY offset** — per target, read XY before/after the
   objective switch. Diagnostic only: written to the run report,
   **not** persisted to ``config.json``. The cookbook commands an
   absolute XY after the switch, so this delta isn't part of the
   correction.

4. **Shift Z (z-wide)** — optional (``--measure-shift-z``). Brenner
   stack on the target gives the target's optical focus. Pure math
   from the two peaks and the cumulative firmware offset gives
   ``shift_z_um``.

5. **Shift XY (registration)** — optional (``--measure-shift-xy``).
   Stage parked at the same XY for both acquires; multi-method
   voting registration (phase / masked / NCC / ORB) measures the
   optical-axis shift. Persisted as ``shift_xy_um`` only if voting
   reaches the configured agreement threshold; on low confidence
   the field is left unset rather than recording garbage. Both
   anchors are Brenner-peak slices.

Stage state and backlash
------------------------
Every acquisition is preceded by a +X+Y backlash takeup. Stage limits
and takeup parameters come from ``config/stage.json``.

Run flow
--------
Targets run in sequence. The script does NOT switch back to the
reference between targets, and does NOT restore the reference at
the end — once a 40× water immersion is in the target list,
returning to the 10× dry reference would be unsafe (water residue
on the plate). The operator selects the next objective explicitly.

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
    # Full run (default: sign + offsets + shift_z + shift_xy).
    python calibrate_objectives.py --job Overview --ref-slot 1 \\
        --target-slots 2 0 --ref-zoom 3.0

    # Skip shift_xy (e.g. low-texture sample where voting fails).
    python calibrate_objectives.py --job Overview --target-slots 2 \\
        --skip-shift-xy
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

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
from navigator_expert.calibration.lib.lasx_state import (
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
Z_RANGE_UM_DEFAULT = 25.0  # half-range in um (total search = 2 × this)
Z_STEP_UM_DEFAULT = 1.0
SCAN_FORMAT_DEFAULT = "1024 x 1024"  # higher pixel density helps NCC on thin texture
SCAN_SPEED_DEFAULT = 600
ZOOM_MIN = 0.75  # Leica hardware floor; below this LAS X silently clamps


# ── Tiny utilities ────────────────────────────────────────────────


def _abort(msg: str, code: int = 1) -> None:
    print(f"ABORT: {msg}")
    sys.exit(code)


# ── CLI ───────────────────────────────────────────────────────────

def parse_args(argv: Sequence[str] | None = None):
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--job", required=True,
                   help="LAS X job (must already be the selected job).")
    p.add_argument("--ref-slot", type=int, default=1,
                   help="Reference objective slot (default: 1).")
    p.add_argument("--target-slots", type=int, nargs="+", required=True,
                   help="Target slot(s) to calibrate against the reference.")

    p.add_argument("--skip-shift-z", action="store_false",
                   dest="measure_shift_z", default=True,
                   help="Skip shift_z (Brenner stacks on z-wide). "
                        "Default: run.")
    p.add_argument("--skip-shift-xy", action="store_false",
                   dest="measure_shift_xy", default=True,
                   help="Skip shift_xy (voting registration of "
                        "Brenner-peak slices). Default: run.")

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
    return p.parse_args(argv)




# ──────────────────────────────────────────────────────────────────────
# Domain types
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RigContext:
    """Long-lived state shared across calibration steps.

    Built once by :func:`step_setup` from CLI args + live LAS X state.
    Frozen so steps can't accidentally mutate it; per-run results
    (sign, focus slice, target reports) flow through return values.
    """
    args: argparse.Namespace
    client: Any
    hw: dict
    stage_cfg: dict
    ref_summary: dict
    targets_summary: dict[int, dict]
    by_slot: dict[int, dict]


# ──────────────────────────────────────────────────────────────────────
# Pipeline steps
# ──────────────────────────────────────────────────────────────────────


def step_setup(args: argparse.Namespace) -> RigContext:
    """Connect, validate, set stage limits. Build the immutable rig state."""
    if args.ref_slot in args.target_slots:
        _abort("--ref-slot cannot appear in --target-slots.")

    stage_cfg = drv.load_stage_config()
    client = drv.connect_python_client()
    drv.apply_stage_limits_from_config(stage_cfg)

    hw = drv.get_hardware_info(client)
    if not hw:
        _abort("could not read hardware info.", 2)

    drv.validate_slots(hw, args.ref_slot, args.target_slots)
    by_slot = drv.objective_by_slot(hw)
    ref_summary = drv.objective_summary(by_slot[args.ref_slot])
    targets_summary = {
        s: drv.objective_summary(by_slot[s]) for s in args.target_slots
    }

    return RigContext(
        args=args, client=client, hw=hw, stage_cfg=stage_cfg,
        ref_summary=ref_summary, targets_summary=targets_summary,
        by_slot=by_slot,
    )


def step_decide_phases(args: argparse.Namespace) -> list[str]:
    """Resolve the ordered phase list given the CLI flags.

    The sign convention always runs (it's cheap and it anchors every
    downstream measurement); the rest follows the optional flags.
    """
    phases_to_run = ["sign"]
    if args.measure_shift_z or args.measure_shift_xy:
        phases_to_run.append("ref_brenner")
    phases_to_run.append("xy_firmware_delta")
    if args.measure_shift_z:
        phases_to_run.append("shift_z")
    if args.measure_shift_xy:
        phases_to_run.append("shift_xy")
    return phases_to_run


def step_initial_reference(
    rig: RigContext, cal_cfg: dict,
) -> tuple[tuple[float, float], float, float]:
    """Switch to the reference slot, capture run anchors, write the
    reference entry into ``cal_cfg``.

    The ``zwide_at_ref_um`` anchor is the operator's z-wide setting
    at the reference, captured before any objective switch. Every
    target's ``offset_z_um`` is computed relative to it, so the
    cookbook's "ref→target firmware motion" stays meaningful even
    when the run never returns to the reference between targets.

    Returns ``(home_xy_um, pixel_size_um, zwide_at_ref_um)``.
    """
    args = rig.args
    setup_reference_state(
        rig.client, args.job, rig.hw,
        ref_slot=args.ref_slot, ref_zoom=args.ref_zoom,
        settle_s=args.settle,
        scan_format=args.scan_format, scan_speed=args.scan_speed,
    )
    geo = drv.parse_tile_geometry(drv.get_job_settings(rig.client, args.job) or {})
    pixel_size_um = float(geo["pixel_w_um"])
    log.info("ref pixel size = %.4f um (FOV %.1f um)",
             pixel_size_um, float(geo["tile_w_um"]))

    home = drv.get_xy(rig.client)
    home_xy = (float(home["x_um"]), float(home["y_um"]))
    zwide_at_ref_um = float(drv.read_zwide_um(rig.client, args.job))
    log.info("ref anchor: zwide = %.2f um", zwide_at_ref_um)

    cal_cfg["reference_objective_slot"] = args.ref_slot
    update_objective(
        cal_cfg, args.ref_slot,
        name=rig.ref_summary["name"],
        offset_xy_um=(0.0, 0.0),
        shift_xy_um=(0.0, 0.0),
        offset_z_um=0.0,
        shift_z_um=0.0,
    )
    return home_xy, pixel_size_um, zwide_at_ref_um


def step_init_report(
    rig: RigContext, phases_to_run: list[str], home_xy: tuple[float, float],
) -> dict:
    """Build the run report skeleton — settings + per-target placeholder."""
    args = rig.args
    return {
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
            "backlash_overshoot_um": rig.stage_cfg["backlash"]["overshoot_um"],
            "backlash_settle_ms": rig.stage_cfg["backlash"]["settle_ms"],
        },
        "reference_objective": rig.ref_summary,
        "anchor_xy_um": list(home_xy),
        "sign_convention": None,
        "per_target": {},
    }


def step_phase_sign_convention(
    rig: RigContext, cal_cfg: dict, acquire_single, pixel_size_um: float,
) -> dict:
    """Phase 1: image-to-stage matrix + D4 snap. Mutates ``cal_cfg``."""
    args = rig.args
    sign = phases.measure_sign_convention(
        rig.client, acquire_single,
        pixel_size_um=pixel_size_um,
        move_um=args.sign_move_um,
        settle_s=args.sign_settle,
    )
    set_image_to_stage(cal_cfg, sign["image_to_stage_um"])
    return sign


def step_acquire_ref_brenner(
    rig: RigContext, acquire_stack, *, zwide_at_ref_um: float,
) -> phases.BrennerResult:
    """Phase 0: reference Brenner anchor.

    Run once before any objective switch when shift_z or shift_xy is
    requested. ``peak_zwide_um`` is the reference's optical focus
    (the cookbook anchor for shift_z); ``peak_slice`` is the
    in-focus reference slice for shift_xy registration. The stack
    is centred on ``zwide_at_ref_um`` (the run anchor), and
    ``measure_brenner`` restores z-wide to that position so the
    operator's focus is left untouched.
    """
    args = rig.args
    return phases.measure_brenner(
        rig.client, args.job,
        acquire_stack=acquire_stack,
        z_range_um=args.z_range_um, z_step_um=args.z_step_um,
        centre_zwide_um=zwide_at_ref_um,
    )


def step_calibrate_target(
    rig: RigContext, ts: int, *,
    home_xy: tuple[float, float],
    image_to_stage: list,
    zwide_at_ref_um: float,
    ref_brenner: phases.BrennerResult | None,
    acquire_stack,
    cal_cfg: dict,
) -> dict:
    """Run phases 2 – 4 for one target slot and persist its update.

    Returns the per-target report fragment; mutates ``cal_cfg`` with
    the slot's measured values via :func:`update_objective`.
    """
    args = rig.args
    log.info("=== target slot %d ===", ts)
    ts_summary = rig.targets_summary[ts]

    # Match the reference FOV: target_zoom = ref_zoom * ref_mag / tgt_mag
    ts_zoom_ideal = (args.ref_zoom * rig.ref_summary["magnification"]
                     / ts_summary["magnification"])
    ts_zoom = max(ZOOM_MIN, ts_zoom_ideal)
    if ts_zoom > ts_zoom_ideal:
        min_ref_zoom = (ZOOM_MIN * ts_summary["magnification"]
                        / rig.ref_summary["magnification"])
        log.warning(
            "target zoom %.3f below hardware min %.2f; clamping to %.2f. "
            "FOV will not match ref — phase 4 voting quality may degrade. "
            "To match FOV, rerun with --ref-zoom %.2f or higher.",
            ts_zoom_ideal, ZOOM_MIN, ZOOM_MIN, min_ref_zoom,
        )

    switch_to_target(
        rig.client, args.job, rig.hw, ts,
        settle_s=args.settle, zoom=ts_zoom,
        scan_format=args.scan_format, scan_speed=args.scan_speed,
    )

    zwide_post_um = float(drv.read_zwide_um(rig.client, args.job))

    # offset_z is the cumulative z-wide motion from the run's anchor
    # (operator focus at the reference) to the current target. With
    # no return-to-ref between targets, the firmware deltas accumulate
    # naturally — we just read z-wide fresh after each switch and
    # subtract the run anchor.
    offset_z_um = float(zwide_post_um - zwide_at_ref_um)
    log.info("z-wide after switch:  %.2f um  (cumulative offset = %+.2f um)",
             zwide_post_um, offset_z_um)

    target_report: dict[str, Any] = {
        "summary": ts_summary,
        "zwide_post_switch_um": zwide_post_um,
        "offset_z_um": offset_z_um,
    }
    update_kwargs: dict[str, Any] = {
        "name": ts_summary["name"],
        "offset_z_um": offset_z_um,
    }

    # Phase 2: firmware xy delta on switch — cumulative ref→target,
    # because home_xy was captured at the reference and stage hasn't
    # been moved by anything other than firmware switches up to this
    # point (shift_xy moves stage to home as its first step, so the
    # anchor stays valid across targets).
    xy_delta_um, xy_delta_report = phases.measure_xy_firmware_delta(rig.client, home_xy)
    target_report["xy_firmware_delta"] = xy_delta_report
    update_kwargs["offset_xy_um"] = xy_delta_um

    # Target Brenner — required for either shift_z or shift_xy.
    # One stack, two consumers: shift_z reads peak_zwide, shift_xy
    # reads peak_slice. ref_brenner is guaranteed non-None whenever
    # either flag is set (main() runs Phase 0 unconditionally then).
    target_brenner: phases.BrennerResult | None = None
    if args.measure_shift_z or args.measure_shift_xy:
        target_brenner = phases.measure_brenner(
            rig.client, args.job,
            acquire_stack=acquire_stack,
            z_range_um=args.z_range_um, z_step_um=args.z_step_um,
            centre_zwide_um=zwide_post_um,
        )
        target_report["target_brenner"] = target_brenner.report()

    # Phase 3: shift_z — pure math from the two Brenner peaks.
    if args.measure_shift_z:
        shift_um, shift_z_report = phases.compute_shift_z(
            ref_brenner=ref_brenner,
            target_brenner=target_brenner,
            offset_z_um=offset_z_um,
        )
        target_report["shift_z"] = shift_z_report
        update_kwargs["shift_z_um"] = shift_um

    # Phase 4: shift_xy — registration with Brenner-peak anchors.
    if args.measure_shift_xy:
        shift_xy, shift_xy_report = phases.measure_shift_xy(
            rig.client, args.job,
            img_ref_focus=ref_brenner.peak_slice,
            img_tgt_focus=target_brenner.peak_slice,
            home_xy=home_xy,
            image_to_stage=image_to_stage,
            ts_zoom=ts_zoom,
            voting_min_agree=VOTING_MIN_AGREE,
        )
        target_report["shift_xy"] = shift_xy_report
        if shift_xy is not None:
            update_kwargs["shift_xy_um"] = shift_xy

    update_objective(cal_cfg, ts, **update_kwargs)
    return target_report


def step_persist(
    rig: RigContext, cal_cfg: dict, report: dict,
) -> tuple[Any, Any, Any]:
    """Write the live config + run report.

    The calibration leaves the scope in whatever state the last
    target ended in — it does NOT switch back to the reference. With
    a 40× water immersion in the target list, returning to the 10×
    dry reference would be unsafe (water residue on the plate).
    The operator should select the next objective explicitly.

    Returns ``(live_path, run_dir, report_path)`` for the caller to
    print at the end.
    """
    run_dir = make_run_dir(report["timestamp"])
    live_path = save_calibration(cal_cfg, run_dir)
    report_path = save_calibration_report(report, run_dir)
    return live_path, run_dir, report_path


def _print_run_summary(rig: RigContext, phases_to_run: list[str]) -> None:
    args = rig.args
    print(f"Job:          {args.job}")
    print(f"Reference:    slot {args.ref_slot}  ({rig.ref_summary['name']})")
    for s, sm in rig.targets_summary.items():
        print(f"Target:       slot {s}  ({sm['name']})")
    print(f"Phases:       {', '.join(phases_to_run)}\n")


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args(argv)

    rig = step_setup(args)
    cal_cfg = load_calibration(create_if_missing=True)
    phases_to_run = step_decide_phases(args)
    _print_run_summary(rig, phases_to_run)

    home_xy, pixel_size_um, zwide_at_ref_um = step_initial_reference(rig, cal_cfg)
    acquire_single, acquire_stack = make_acquirer(
        rig.client, args.job, rig.stage_cfg,
    )
    report = step_init_report(rig, phases_to_run, home_xy)
    report["zwide_at_ref_um"] = zwide_at_ref_um

    report["sign_convention"] = step_phase_sign_convention(
        rig, cal_cfg, acquire_single, pixel_size_um,
    )
    image_to_stage = cal_cfg["image_to_stage"]

    # Phase 0: reference Brenner anchor. Runs whenever shift_z or
    # shift_xy is requested — its peak is the cookbook anchor for
    # shift_z and its peak slice is the registration anchor for
    # shift_xy.
    ref_brenner: phases.BrennerResult | None = None
    if args.measure_shift_z or args.measure_shift_xy:
        ref_brenner = step_acquire_ref_brenner(
            rig, acquire_stack, zwide_at_ref_um=zwide_at_ref_um,
        )
        report["ref_brenner"] = ref_brenner.report()

    # Targets run in sequence without returning to the reference
    # between them. Per-target ``offset_z_um`` is computed cumulatively
    # against ``zwide_at_ref_um``, so the firmware deltas along the
    # path compose naturally.
    for ts in args.target_slots:
        report["per_target"][str(ts)] = step_calibrate_target(
            rig, ts,
            home_xy=home_xy, image_to_stage=image_to_stage,
            zwide_at_ref_um=zwide_at_ref_um,
            ref_brenner=ref_brenner,
            acquire_stack=acquire_stack,
            cal_cfg=cal_cfg,
        )

    live_path, run_dir, report_path = step_persist(rig, cal_cfg, report)

    print(f"\nLive config:        {live_path}")
    print(f"Run folder:         {run_dir}")
    print(f"  config:           {run_dir / 'config.json'}")
    print(f"  report:           {report_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
