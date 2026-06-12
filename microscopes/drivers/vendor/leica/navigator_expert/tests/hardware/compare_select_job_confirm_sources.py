"""Compare API-backed and log-backed selected-job confirmation timings.

This is a hardware utility, not production driver logic. It runs the normal
``validate_hardware.py`` flow repeatedly with two selected-job confirmation
sources:

  - api: the default production confirmation source
  - log: LAS X log polling via ``state_readers.log_wait``

The validator still owns the actual checks and reversible setting writes. This
script only orchestrates repeated runs, parses the JSONL output, and reports
whether log-backed selected-job confirmation is reliable and faster/slower in
the same full-validator context.

Default usage mirrors the comparison we ran manually:

  python compare_select_job_confirm_sources.py --yes --runs 10

Useful variants:

  python compare_select_job_confirm_sources.py --yes --runs 10 --read-only
  python compare_select_job_confirm_sources.py --yes --runs 10 --prime-log-select-cluster
  python compare_select_job_confirm_sources.py --yes --runs 10 --api-delay-ms 0
  python compare_select_job_confirm_sources.py --yes --runs 10 --validator-arg=--allow-xy

``--mock`` can smoke-test the subprocess/summary harness, but it cannot
validate log-backed confirmation because the Python mock does not write the
LAS X log stream.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as stats
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE / "validate_hardware.py"


def _now_stamp() -> str:
    """Return a filesystem-friendly timestamp for this comparison run."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load validator records from a JSONL file."""
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                records.append(
                    {
                        "name": "__json_error__",
                        "status": "FAIL",
                        "message": f"{path}:{line_no}: {exc}",
                        "context": {"path": str(path), "line_no": line_no},
                    }
                )
    return records


def _record_target(record: dict[str, Any]) -> str:
    """Extract the selected-job target from a validator record."""
    context = record.get("context") or {}
    job = context.get("job")
    if job:
        return str(job)
    message = record.get("message") or ""
    prefix = "SelectJob '"
    if prefix in message:
        rest = message.split(prefix, 1)[1]
        return rest.split("'", 1)[0]
    return "<unknown>"


def _record_total_s(record: dict[str, Any]) -> float | None:
    """Extract the command total duration from a validator record."""
    timing = record.get("timing") or {}
    value = timing.get("total_s")
    if value is None:
        value = record.get("elapsed_s")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _record_confirm_s(record: dict[str, Any]) -> float | None:
    """Extract the confirmation duration when the validator captured it."""
    timing = record.get("timing") or {}
    value = timing.get("confirm_s")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _describe(values: list[float]) -> dict[str, float | int | None]:
    """Return compact descriptive statistics for a list of timings."""
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if not clean:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "p95": None,
            "stdev": None,
        }
    ordered = sorted(clean)

    def percentile(pct: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        pos = (len(ordered) - 1) * pct / 100.0
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            return ordered[lo]
        return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)

    return {
        "n": len(clean),
        "mean": stats.mean(clean),
        "median": stats.median(clean),
        "min": min(clean),
        "max": max(clean),
        "p95": percentile(95.0),
        "stdev": stats.stdev(clean) if len(clean) > 1 else 0.0,
    }


def _round_summary(value: Any) -> Any:
    """Round floats in nested summary structures for stable display."""
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: _round_summary(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_summary(v) for v in value]
    return value


def _build_validator_command(
    *,
    source: str,
    output: Path,
    args: argparse.Namespace,
) -> list[str]:
    """Build one validate_hardware.py subprocess command."""
    command = [sys.executable, str(VALIDATOR)]
    if args.mock:
        command.append("--mock")
    if args.yes:
        command.append("--yes")
    if args.read_only:
        command.append("--read-only")
    if args.api_delay_ms is not None:
        command.extend(["--api-delay-ms", str(args.api_delay_ms)])
    command.extend(["--select-job-confirm-source", source])
    if source == "log" and args.prime_log_select_cluster:
        command.append("--prime-log-select-cluster")
    if args.log_select_confirm_timeout_s is not None:
        command.extend(
            [
                "--log-select-confirm-timeout-s",
                str(args.log_select_confirm_timeout_s),
            ]
        )
    if args.log_select_cluster_max_age_s is not None:
        command.extend(
            [
                "--log-select-cluster-max-age-s",
                str(args.log_select_cluster_max_age_s),
            ]
        )
    command.extend(args.validator_arg or [])
    command.extend(["--output", str(output)])
    return command


def _run_validator_passes(args: argparse.Namespace, stamp: str) -> list[dict[str, Any]]:
    """Run API and log validator passes and return per-run metadata."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_records: list[dict[str, Any]] = []

    for source in ("api", "log"):
        for run in range(1, args.runs + 1):
            output = output_dir / (
                f"validate_hardware_full_{source}_{stamp}_run{run}_results.jsonl"
            )
            if output.exists() and not args.append:
                raise FileExistsError(f"{output} already exists. Use a new --stamp or --append.")
            command = _build_validator_command(
                source=source,
                output=output,
                args=args,
            )
            print(f"\n=== {source.upper()} full validator run {run}/{args.runs} ===")
            print(" ".join(command))
            completed = subprocess.run(command, check=False)
            run_records.append(
                {
                    "source": source,
                    "run": run,
                    "returncode": completed.returncode,
                    "output": str(output),
                }
            )
            print(f"=== {source.upper()} run {run} exit={completed.returncode} output={output} ===")
    return run_records


def _parse_outputs(run_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse validator outputs and build the comparison summary."""
    select_records: list[dict[str, Any]] = []
    nonpass_records: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    for run_meta in run_records:
        path = Path(run_meta["output"])
        for record in _read_jsonl(path):
            record["_source"] = run_meta["source"]
            record["_run"] = run_meta["run"]
            record["_path"] = str(path)
            name = record.get("name")
            status = record.get("status")
            if name == "job selection: select job":
                select_records.append(record)
            if name == "__summary__":
                summaries.append(record)
            if status not in (None, "PASS", "DONE", "SKIP"):
                nonpass_records.append(record)

    by_source: dict[str, list[float]] = defaultdict(list)
    by_source_target: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_run: dict[tuple[str, int], list[float]] = defaultdict(list)
    by_run_target: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    status_counts: Counter[tuple[str, str]] = Counter()

    for record in select_records:
        source = record["_source"]
        run = int(record["_run"])
        target = _record_target(record)
        total_s = _record_total_s(record)
        if total_s is None:
            continue
        by_source[source].append(total_s)
        by_source_target[(source, target)].append(total_s)
        by_run[(source, run)].append(total_s)
        by_run_target[(run, target)][source] = total_s
        status_counts[(source, record.get("status") or "<missing>")] += 1

    paired_diffs = []
    for (run, target), values in sorted(by_run_target.items()):
        if "api" not in values or "log" not in values:
            continue
        paired_diffs.append(
            {
                "run": run,
                "target": target,
                "api_s": values["api"],
                "log_s": values["log"],
                "log_minus_api_s": values["log"] - values["api"],
            }
        )

    per_source = {source: _describe(values) for source, values in sorted(by_source.items())}
    per_target: dict[str, dict[str, Any]] = {}
    targets = sorted({target for (_source, target) in by_source_target})
    for target in targets:
        per_target[target] = {
            source: _describe(by_source_target.get((source, target), []))
            for source in ("api", "log")
        }

    per_cycle = {}
    for source in ("api", "log"):
        cycle_sums = [
            sum(values)
            for (src, _run), values in sorted(by_run.items())
            if src == source and len(values) == len(targets)
        ]
        per_cycle[source] = {
            "summary": _describe(cycle_sums),
            "values_s": cycle_sums,
        }

    return {
        "runs": run_records,
        "select_record_count": len(select_records),
        "status_counts": {
            f"{source}:{status}": count for (source, status), count in sorted(status_counts.items())
        },
        "per_source_s": per_source,
        "per_target_s": per_target,
        "per_cycle_s": per_cycle,
        "paired_diffs": paired_diffs,
        "log_faster_count": sum(1 for diff in paired_diffs if diff["log_minus_api_s"] < 0),
        "paired_count": len(paired_diffs),
        "summaries": summaries,
        "nonpass_records": nonpass_records,
    }


def _print_summary(summary: dict[str, Any], summary_path: Path) -> None:
    """Print a concise human-readable comparison."""
    print("\n=== SELECT-JOB CONFIRMATION COMPARISON ===")
    print(f"summary_json: {summary_path}")
    print(f"select records: {summary['select_record_count']}")
    print(f"status counts: {summary['status_counts']}")

    print("\nPer source command totals:")
    for source in ("api", "log"):
        desc = summary["per_source_s"].get(source, {})
        print(f"  {source:<3} {_round_summary(desc)}")

    print("\nPer target command totals:")
    for target, data in summary["per_target_s"].items():
        api = _round_summary(data.get("api", {}))
        log = _round_summary(data.get("log", {}))
        print(f"  {target}: api={api} log={log}")

    print("\nPer full job-selection cycle:")
    for source in ("api", "log"):
        data = summary["per_cycle_s"].get(source, {})
        print(
            f"  {source:<3} summary={_round_summary(data.get('summary', {}))} "
            f"values={_round_summary(data.get('values_s', []))}"
        )

    paired_count = summary["paired_count"]
    log_faster = summary["log_faster_count"]
    print(
        f"\nPaired switches: log faster {log_faster}/{paired_count}; "
        f"api faster/equal {paired_count - log_faster}/{paired_count}"
    )

    nonpass = summary["nonpass_records"]
    if nonpass:
        print("\nWARN/FAIL records:")
        for record in nonpass:
            print(
                f"  {record['_source']} run {record['_run']}: "
                f"{record.get('status')} | {record.get('name')} | "
                f"{record.get('message')}"
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run repeated full validate_hardware.py passes and compare "
            "API vs log selected-job confirmation timings."
        )
    )
    parser.add_argument("--runs", type=int, default=10, help="number of validator runs per source")
    parser.add_argument("--yes", action="store_true", help="confirm live reversible writes")
    parser.add_argument(
        "--mock", action="store_true", help="run validator against the Python mock backend"
    )
    parser.add_argument(
        "--read-only", action="store_true", help="pass --read-only to validate_hardware.py"
    )
    parser.add_argument(
        "--api-delay-ms",
        type=int,
        help="override profiles.LASX_API.delay_ms in each validate_hardware.py pass",
    )
    parser.add_argument(
        "--output-dir", default=str(HERE), help="directory for per-run JSONL and summary JSON"
    )
    parser.add_argument("--stamp", default=None, help="output filename timestamp; default: now")
    parser.add_argument(
        "--append", action="store_true", help="append to existing per-run JSONL outputs"
    )
    parser.add_argument(
        "--prime-log-select-cluster",
        action="store_true",
        help="prime log job clusters before log confirmation",
    )
    parser.add_argument(
        "--log-select-confirm-timeout-s",
        type=float,
        default=None,
        help="override log selected-job confirmation timeout",
    )
    parser.add_argument(
        "--log-select-cluster-max-age-s",
        type=float,
        default=None,
        help="override log selected-job cluster max age",
    )
    parser.add_argument(
        "--validator-arg",
        action="append",
        default=[],
        help=(
            "extra argument forwarded to validate_hardware.py; repeat for "
            "multiple arguments, e.g. --validator-arg=--allow-xy"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the comparison and return a process exit code."""
    args = parse_args(argv)
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    if not args.mock and not args.yes:
        raise SystemExit(
            "This comparison runs reversible validator writes. "
            "Use --yes for LAS X/scope, or --mock for the Python mock."
        )

    stamp = args.stamp or _now_stamp()
    output_dir = Path(args.output_dir)
    run_records = _run_validator_passes(args, stamp)
    summary = _parse_outputs(run_records)

    summary_path = output_dir / (f"select_job_confirm_source_compare_{stamp}_summary.json")
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    _print_summary(summary, summary_path)

    any_run_failed = any(run["returncode"] != 0 for run in run_records)
    any_record_failed = any(record.get("status") == "FAIL" for record in summary["nonpass_records"])
    return 1 if any_run_failed or any_record_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
