"""
Measure objective-switch stage XY offsets.
==========================================

Hardware tool: records the change in reported stage XY when LAS X switches
from a reference objective slot to one or more target slots. Performs
exactly one objective switch per target — LAS X's XY readback is
deterministic, so repeats add no information.

Usage:
    python measure_objective_offsets.py --job Overview --ref-slot 1 --target-slots 2
    python measure_objective_offsets.py --job Overview --ref-slot 1 --target-slots 2 0

The job passed to --job must be the one currently selected in the LAS X UI.
This script does not call select_job — LAS X's IsSelected flag lags the UI
and can cause false timeouts.

Writes two files on success:
    config/objective_offsets/objective_offsets_<ts>.json   (archive, gitignored)
    config/objective_offsets.json                          (current; protocols load this)
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv


def parse_args():
    parser = argparse.ArgumentParser(
        description="Measure objective-switch motor XY readback deltas."
    )
    parser.add_argument(
        "--job", required=True,
        help="LAS X job name. Must be currently selected in the LAS X UI.",
    )
    parser.add_argument(
        "--ref-slot", type=int, required=True,
        help="Reference objective slot (e.g. 1 for 10x).",
    )
    parser.add_argument(
        "--target-slots", type=int, nargs="+", required=True,
        help="Target objective slot(s) to measure, e.g. 2 or 2 0.",
    )
    parser.add_argument(
        "--settle", type=float, default=3.0,
        help=f"Seconds to wait after each objective switch "
             f"(default: 3; minimum: {drv.MIN_SETTLE_S}).",
    )
    parser.add_argument(
        "--archive-dir", type=Path, default=None,
        help="Directory for the timestamped archive file "
             "(default: config/objective_offsets/).",
    )
    parser.add_argument(
        "--current-path", type=Path, default=None,
        help="Path for the fixed current-offsets file "
             "(default: config/objective_offsets.json).",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Measure and print without writing any JSON.",
    )
    parser.add_argument(
        "--no-restore", action="store_true",
        help="Do not switch back to the reference slot at the end.",
    )
    return parser.parse_args()


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

    print(f"Job:            {args.job}")
    print(f"Reference slot: {args.ref_slot}")
    print(f"Target slots:   {args.target_slots}")
    print(f"Settle:         {args.settle:.1f}s\n")

    try:
        config = drv.measure_objective_switch_offsets(
            client,
            args.ref_slot,
            args.target_slots,
            job_name=args.job,
            hw_info=hw,
            settle_s=args.settle,
            restore_reference=not args.no_restore,
        )
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 1

    print("\nMeasured objective-switch deltas:")
    for slot, entry in config["offsets"].items():
        dx, dy = entry["motor_delta_um"]
        name = (entry["target_objective"] or {}).get("name", "")
        print(f"  slot {slot}: dx={dx:+.3f} um, dy={dy:+.3f} um  {name}")

    if args.no_save:
        return 0

    try:
        paths = drv.save_objective_offsets(
            config,
            archive_dir=args.archive_dir,
            current_path=args.current_path,
        )
    except Exception as exc:
        print(f"ABORT: failed to write config: {exc}")
        return 1

    print(f"\nArchive: {paths['archive']}")
    print(f"Current: {paths['current']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
