"""Live probe for the alternating API/log change-wait reader.

Exercises ``state_readers.read_change_baseline`` / ``wait_for_change``
against a running LAS X (simulator or scope) in three phases:

  1. read-only: baseline capture for both datums, API vs log side by side;
  2. selected-job switches between two jobs, change-wait after each fire;
  3. reversible XY moves, change-wait with target/tolerance reporting.

The command itself runs on the production path (with its own confirmation);
the probe then measures how the change-wait reader saw the transition. For
the log source the log-line timestamp dates the event itself, so the
"noticed after fire" latency is exact even though the wait starts after the
command returned. No production code or profiles are modified.

Simulator note: the simulated stage moves in 20 um increments, so XY deltas
must be multiples of 20 and the reported tolerance should be >= 20.

Do NOT generalize per-source winner statistics across environments. On the
simulator the LCS log flushes lazily, so the API tends to win; on the real
scope the API selected-job readback is the stale one (wrong job for 15 s+)
while the log CurrentBlock lands in ~0.2 s, so the log wins. The reader is
deliberately source-agnostic: a stale API keeps reporting the OLD value and
simply never confirms - it cannot falsely win - and every disagreement is
reported via ``sources_agree``/``last_reasons``.

Usage:
  python probe_change_wait.py --yes                  # 3 switches, 3 moves
  python probe_change_wait.py --yes --runs 5 --delta-um 100
  python probe_change_wait.py --yes --job-a Overview --job-b HiRes
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # vendor/leica

import navigator_expert as drv
from navigator_expert import state_readers

HERE = Path(__file__).resolve().parent


def _reading_brief(reading):
    if reading is None:
        return None
    return {
        "value": reading.value,
        "observed_at": reading.observed_at,
        "age_s": reading.age_s,
    }


def _result_brief(result, fired_at):
    noticed_after_fire_s = (
        None if result.observed_at is None
        else result.observed_at - fired_at
    )
    return {
        "outcome": result.outcome,
        "source": result.source,
        "value": result.value,
        "elapsed_s": round(result.elapsed_s, 4),
        "noticed_after_fire_s": (
            None if noticed_after_fire_s is None
            else round(noticed_after_fire_s, 4)
        ),
        "api_attempts": result.api_attempts,
        "log_attempts": result.log_attempts,
        "matches_target": result.matches_target,
        "within_tolerance": result.within_tolerance,
        "target_delta": result.target_delta,
        "sources_agree": result.sources_agree,
        "last_reasons": result.diagnostics["last_reasons"],
        "api_skips": result.diagnostics["api_skips"],
    }


def _emit(records, output, record):
    records.append(record)
    with output.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=repr) + "\n")
    print(json.dumps(record, indent=2, default=repr))


def phase_readonly(client, records, output):
    for datum in ("selected_job", "xy"):
        t0 = time.perf_counter()
        baseline = state_readers.read_change_baseline(client, datum)
        _emit(records, output, {
            "phase": "readonly",
            "datum": datum,
            "elapsed_s": round(time.perf_counter() - t0, 4),
            "api": _reading_brief(baseline.api),
            "log": _reading_brief(baseline.log),
            "diagnostics": baseline.diagnostics,
        })


def phase_select_job(client, records, output, job_a, job_b, runs):
    targets = [job_b if i % 2 == 0 else job_a for i in range(runs)]
    # start from a known job so the first switch is a real transition
    drv.select_job(client, job_a)
    for run, target in enumerate(targets, 1):
        baseline = state_readers.read_change_baseline(client, "selected_job")
        fired_at = time.time()
        command = drv.select_job(client, target)
        result = state_readers.wait_for_change(
            client, "selected_job", baseline, target=target)
        _emit(records, output, {
            "phase": "select_job",
            "run": run,
            "target": target,
            "command_success": command.get("success"),
            "command_confirmed": command.get("confirmed"),
            "command_timing": command.get("timing"),
            "baseline_api": _reading_brief(baseline.api),
            "baseline_log": _reading_brief(baseline.log),
            "change_wait": _result_brief(result, fired_at),
        })


def phase_move_xy(client, records, output, delta_um, tolerance_um, runs):
    # Work from the center of the configured envelope: the parked position
    # (often a corner like 0,0) may lie outside the safe working limits.
    limits = drv.get_stage_limits()
    x0 = round((limits["x_min"] + limits["x_max"]) / 2 / 20) * 20
    y0 = round((limits["y_min"] + limits["y_max"]) / 2 / 20) * 20
    home = drv.move_xy(client, x0, y0, unit="um")
    if not home.get("success"):
        raise SystemExit(f"could not reach envelope center: {home}")
    try:
        for run in range(1, runs + 1):
            tx, ty = x0 + delta_um, y0
            baseline = state_readers.read_change_baseline(client, "xy")
            fired_at = time.time()
            command = drv.move_xy(client, tx, ty, unit="um")
            result = state_readers.wait_for_change(
                client, "xy", baseline,
                target=(tx, ty), tolerance=tolerance_um)
            _emit(records, output, {
                "phase": "move_xy",
                "run": run,
                "target_um": [tx, ty],
                "command_success": command.get("success"),
                "command_confirmed": command.get("confirmed"),
                "baseline_api": _reading_brief(baseline.api),
                "baseline_log": _reading_brief(baseline.log),
                "change_wait": _result_brief(result, fired_at),
            })
            drv.move_xy(client, x0, y0, unit="um")
    finally:
        drv.move_xy(client, x0, y0, unit="um")


def summarize(records):
    print("\n=== CHANGE-WAIT PROBE SUMMARY ===")
    for phase in ("select_job", "move_xy"):
        rows = [r for r in records if r["phase"] == phase]
        if not rows:
            continue
        changed = [r for r in rows if r["change_wait"]["outcome"] == "changed"]
        by_source = {}
        for r in changed:
            by_source.setdefault(r["change_wait"]["source"], []).append(r)
        print(f"\n{phase}: {len(changed)}/{len(rows)} changed")
        for source, srows in sorted(by_source.items()):
            noticed = [
                r["change_wait"]["noticed_after_fire_s"] for r in srows
                if r["change_wait"]["noticed_after_fire_s"] is not None
            ]
            stat = (
                f" noticed-after-fire min={min(noticed):.3f}s "
                f"max={max(noticed):.3f}s" if noticed else ""
            )
            print(f"  source={source}: {len(srows)}x{stat}")
        disagreements = [
            r for r in rows if r["change_wait"]["sources_agree"] is False
        ]
        if disagreements:
            print(f"  CONFLICTS reported: {len(disagreements)} "
                  "(other source still on pre-change value at win time)")
    unconfirmed = [
        r for r in records
        if r.get("change_wait", {}).get("outcome") == "unconfirmed"
    ]
    if unconfirmed:
        print(f"\nUNCONFIRMED runs: {len(unconfirmed)} - inspect last_reasons "
              "in the JSONL output")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--yes", action="store_true",
                   help="confirm reversible writes (job switches, XY moves)")
    p.add_argument("--runs", type=int, default=3,
                   help="switches and moves per phase (default 3)")
    p.add_argument("--job-a", default=None, help="first job name")
    p.add_argument("--job-b", default=None, help="second job name")
    p.add_argument("--delta-um", type=float, default=100.0,
                   help="XY move distance; simulator quantizes to 20 um")
    p.add_argument("--tolerance-um", type=float, default=20.0,
                   help="reported (never enforced) target tolerance")
    p.add_argument("--read-only", action="store_true",
                   help="phase 1 only: no job switches, no moves")
    p.add_argument("--output", default=None, help="JSONL output path")
    args = p.parse_args(argv)

    if args.delta_um % 20:
        raise SystemExit("--delta-um must be a multiple of 20 (simulator "
                         "stage increment)")
    if not args.read_only and not args.yes:
        raise SystemExit("job switches and XY moves are reversible writes; "
                         "pass --yes to confirm (or --read-only)")

    output = Path(args.output) if args.output else (
        HERE
        / f"probe_change_wait_{time.strftime('%Y%m%d_%H%M%S')}_results.jsonl"
    )
    records = []

    client = drv.connect_python_client()
    stage_cfg = drv.load_stage_config()
    drv.apply_stage_limits_from_config(stage_cfg)

    phase_readonly(client, records, output)
    if not args.read_only:
        job_a, job_b = args.job_a, args.job_b
        if not (job_a and job_b):
            jobs = drv.get_jobs(client, mode="api") or []
            names = [j.get("Name") for j in jobs if j.get("Name")]
            if len(set(names)) < 2:
                raise SystemExit(f"need two distinct jobs, found {names}")
            job_a, job_b = sorted(set(names))[:2]
            print(f"auto-selected jobs: {job_a!r} <-> {job_b!r}")
        phase_select_job(client, records, output, job_a, job_b, args.runs)
        phase_move_xy(client, records, output,
                      args.delta_um, args.tolerance_um, args.runs)

    summarize(records)
    print(f"\nrecords: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
