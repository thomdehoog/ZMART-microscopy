"""Exercise the three Leica passive state-reader paths on LAS X.

The three paths are:

  1. ``api``: routed passive reader pinned to the CAM API;
  2. ``log``: routed passive reader pinned to LAS X logs;
  3. ``hybrid``: mixed passive reader that races API/log.

Default mode is read-only. With ``--yes`` the probe performs reversible writes:
two rounds of job changes and a 10-position XY pattern by default. Every step
records command timing, reader timing, values, source/age metadata, and error
messages to JSONL while also printing a compact console table.

Each write step ends with passive api/log/hybrid reads for diagnostics.

Typical real-scope run:

  python probe_four_readers.py --yes

Safer first pass:

  python probe_four_readers.py --read-only
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # vendor/leica

import navigator_expert as drv
from navigator_expert import readers

HERE = Path(__file__).resolve().parent
PASSIVE_MODES = ("api", "log", "hybrid")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def _selected_name(value: Any) -> str | None:
    return value.get("Name") if isinstance(value, dict) else None


def _xy_pair(value: Any) -> list[float] | None:
    if not isinstance(value, dict):
        return None
    try:
        return [float(value["x_um"]), float(value["y_um"])]
    except (KeyError, TypeError, ValueError):
        return None


def _max_abs_delta_um(value: Any, target: tuple[float, float]) -> float | None:
    pair = _xy_pair(value)
    if pair is None:
        return None
    return max(abs(pair[0] - target[0]), abs(pair[1] - target[1]))


def _value_summary(value: Any) -> dict[str, Any]:
    if value is None:
        return {"kind": "none"}
    if isinstance(value, dict):
        if "x_um" in value and "y_um" in value:
            return {
                "kind": "xy",
                "x_um": round(float(value["x_um"]), 3),
                "y_um": round(float(value["y_um"]), 3),
            }
        if "Name" in value:
            return {
                "kind": "selected_job",
                "name": value.get("Name"),
                "id": value.get("ID"),
                "is_selected": value.get("IsSelected"),
            }
        microscope = value.get("Microscope")
        if isinstance(microscope, dict):
            return {
                "kind": "hardware_info",
                "microscope": microscope.get("name"),
            }
        return {"kind": "dict", "keys": sorted(str(k) for k in value)[:12]}
    if isinstance(value, list):
        names = [item.get("Name") for item in value if isinstance(item, dict) and item.get("Name")]
        selected = [
            item.get("Name") for item in value if isinstance(item, dict) and item.get("IsSelected")
        ]
        return {
            "kind": "list",
            "count": len(value),
            "names": names,
            "selected": selected,
        }
    return {"kind": type(value).__name__, "repr": repr(value)[:200]}


def _reading_to_record(reading: Any, elapsed_ms: float) -> dict[str, Any]:
    if reading is None:
        return {
            "status": "none",
            "elapsed_ms": round(elapsed_ms, 3),
            "source": None,
            "value": None,
            "summary": {"kind": "none"},
        }
    error = getattr(reading, "error", None)
    value = getattr(reading, "value", None)
    status = "error" if error is not None else ("none" if value is None else "ok")
    return {
        "status": status,
        "elapsed_ms": round(elapsed_ms, 3),
        "source": getattr(reading, "source", None),
        "observed_at": getattr(reading, "observed_at", None),
        "age_s": getattr(reading, "age_s", None),
        "error": None if error is None else f"{type(error).__name__}: {error}",
        "value": _jsonable(value),
        "summary": _value_summary(value),
    }


def _timed_read(fn) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        reading = fn()
    except Exception as exc:  # noqa: BLE001 - hardware exceptions vary
        return {
            "status": "exception",
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "source": None,
            "error": f"{type(exc).__name__}: {exc}",
            "value": None,
            "summary": {"kind": "exception"},
        }
    return _reading_to_record(
        reading,
        (time.perf_counter() - started) * 1000.0,
    )


def _brief_read(record: dict[str, Any]) -> str:
    status = record["status"]
    source = record.get("source") or "-"
    ms = record["elapsed_ms"]
    if status not in {"ok", "none"}:
        return f"{status}@{ms:.0f}ms {record.get('error')}"
    summary = record.get("summary") or {}
    if summary.get("kind") == "xy":
        value = f"({summary['x_um']:.1f},{summary['y_um']:.1f})"
    elif summary.get("kind") == "selected_job":
        value = str(summary.get("name"))
    elif summary.get("kind") == "list":
        value = f"{summary.get('count')} jobs"
    else:
        value = summary.get("kind", "-")
    return f"{source}:{value}@{ms:.0f}ms"


def _emit(records: list[dict[str, Any]], output: Path, record: dict[str, Any]) -> None:
    records.append(record)
    with output.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=repr) + "\n")


def _read_passive(client, datum: str, mode: str, job_name: str | None) -> dict[str, Any]:
    if datum == "selected_job":
        return _timed_read(
            lambda: readers.get_selected_job(client, mode=mode, diagnostics=True)
        )
    if datum == "xy":
        return _timed_read(lambda: readers.get_xy(client, mode=mode, diagnostics=True))
    if datum == "jobs":
        return _timed_read(lambda: readers.get_jobs(client, mode=mode, diagnostics=True))
    if datum == "scan_status":
        return _timed_read(
            lambda: readers.get_scan_status(client, mode=mode, diagnostics=True)
        )
    if datum == "hardware_info":
        return _timed_read(
            lambda: readers.get_hardware_info(client, mode=mode, diagnostics=True)
        )
    if datum == "job_settings":
        if not job_name:
            return {
                "status": "skipped",
                "elapsed_ms": 0.0,
                "source": None,
                "error": "no selected job available",
                "value": None,
                "summary": {"kind": "skipped"},
            }
        return _timed_read(
            lambda: readers.get_job_settings(client, job_name, mode=mode, diagnostics=True)
        )
    raise ValueError(f"unknown passive datum {datum!r}")


def _read_all_passive(
    client,
    datum: str,
    *,
    job_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    return {mode: _read_passive(client, datum, mode, job_name) for mode in PASSIVE_MODES}


def _summarize_selected(reads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        mode: _selected_name(read.get("value") if read else None) for mode, read in reads.items()
    }


def _summarize_xy(
    reads: dict[str, dict[str, Any]],
    target: tuple[float, float],
) -> dict[str, Any]:
    out = {}
    for mode, read in reads.items():
        value = read.get("value") if read else None
        out[mode] = {
            "xy_um": _xy_pair(value),
            "target_delta_um": _max_abs_delta_um(value, target),
            "status": read.get("status") if read else None,
        }
    return out


def phase_read_only(
    client,
    records: list[dict[str, Any]],
    output: Path,
    job_name: str | None,
) -> None:
    print("\n=== READ-ONLY: api / log / hybrid ===")
    for datum in ("selected_job", "xy", "jobs", "scan_status", "hardware_info"):
        reads = _read_all_passive(client, datum, job_name=job_name)
        record = {
            "phase": "read_only",
            "datum": datum,
            "passive": reads,
        }
        _emit(records, output, record)
        cells = " | ".join(f"{mode} {_brief_read(reads[mode])}" for mode in PASSIVE_MODES)
        print(f"{datum:<14} {cells}")

    if job_name:
        reads = _read_all_passive(client, "job_settings", job_name=job_name)
        record = {
            "phase": "read_only",
            "datum": "job_settings",
            "job": job_name,
            "passive": reads,
        }
        _emit(records, output, record)
        cells = " | ".join(f"{mode} {_brief_read(reads[mode])}" for mode in PASSIVE_MODES)
        print(f"{'job_settings':<14} {cells}")

    pending = _timed_read(lambda: readers.get_pending_dialog(diagnostics=True))
    _emit(
        records,
        output,
        {
            "phase": "read_only",
            "datum": "pending_dialog",
            "passive": {"log": pending},
        },
    )
    print(f"{'pending_dialog':<14} log {_brief_read(pending)}")


def _current_selected_job(client) -> str | None:
    selected = readers.get_selected_job(client, mode="api")
    return _selected_name(selected)


def _job_sequence(
    client,
    *,
    job_a: str | None,
    job_b: str | None,
    all_jobs: bool,
) -> list[str]:
    jobs = readers.get_jobs(client, mode="api") or []
    names = [j.get("Name") for j in jobs if j.get("Name")]
    names = sorted(dict.fromkeys(names))
    if job_a or job_b:
        if not (job_a and job_b):
            raise ValueError("--job-a and --job-b must be provided together")
        missing = [name for name in (job_a, job_b) if name not in names]
        if missing:
            raise ValueError(f"requested jobs not found: {missing}; available={names}")
        names = [job_a, job_b]
    elif not all_jobs:
        if len(names) < 2:
            raise ValueError(f"need at least two jobs, found {names}")
        selected = _current_selected_job(client)
        other = next((name for name in names if name != selected), names[0])
        names = [other, selected] if selected and selected != other else names[:2]
    if len(names) < 2:
        raise ValueError(f"need at least two jobs, found {names}")
    current = _current_selected_job(client)
    if current in names and names[0] == current:
        names = names[1:] + names[:1]
    return names


def phase_job_changes(
    client,
    records: list[dict[str, Any]],
    output: Path,
    *,
    rounds: int,
    job_a: str | None,
    job_b: str | None,
    all_jobs: bool,
) -> None:
    sequence = _job_sequence(client, job_a=job_a, job_b=job_b, all_jobs=all_jobs)
    original = _current_selected_job(client)
    print(f"\n=== JOB CHANGES: {rounds} round(s), sequence={sequence} ===")
    try:
        step = 0
        for round_index in range(1, rounds + 1):
            for target in sequence:
                step += 1
                fired_at = time.time()
                started = time.perf_counter()
                try:
                    command = drv.select_job(client, target)
                    command_error = None
                except Exception as exc:  # noqa: BLE001
                    command = None
                    command_error = f"{type(exc).__name__}: {exc}"
                command_ms = (time.perf_counter() - started) * 1000.0

                reads = _read_all_passive(client, "selected_job")
                selected_by_reader = _summarize_selected(reads)
                record = {
                    "phase": "job_change",
                    "step": step,
                    "round": round_index,
                    "target": target,
                    "fired_at": fired_at,
                    "command": {
                        "elapsed_ms": round(command_ms, 3),
                        "error": command_error,
                        "result": _jsonable(command),
                        "success": (None if command is None else command.get("success")),
                        "confirmed": (None if command is None else command.get("confirmed")),
                    },
                    "passive": reads,
                    "selected_by_reader": selected_by_reader,
                }
                _emit(records, output, record)
                _print_job_step(record)
    finally:
        if original:
            print(f"Restoring original job: {original}")
            drv.select_job(client, original)


def _print_job_step(record: dict[str, Any]) -> None:
    selected = record["selected_by_reader"]
    command = record["command"]
    agreeing = [mode for mode in PASSIVE_MODES if selected.get(mode) == record["target"]]
    # The command result grades the step. Passive-reader agreement is
    # reported, never judged: right after a real switch the passive readers
    # can all lag (API stale, log fail-closed), and that is expected
    # behavior, not a failed step.
    ok = command.get("success") is True
    marker = "OK " if ok else "XX "
    print(
        f"{marker}job step={record['step']:02d} round={record['round']} "
        f"target={record['target']!r} cmd={command['elapsed_ms']:.0f}ms "
        f"agree={','.join(agreeing) or 'none'} "
        f"api={selected.get('api')!r} log={selected.get('log')!r} "
        f"hybrid={selected.get('hybrid')!r}"
    )
    if command.get("error"):
        print(f"    errors command={command.get('error')}")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _xy_positions(
    start: tuple[float, float],
    limits: dict[str, float],
    count: int,
    step_um: float,
) -> list[tuple[float, float]]:
    x0, y0 = start
    x_min, x_max = float(limits["x_min"]), float(limits["x_max"])
    y_min, y_max = float(limits["y_min"]), float(limits["y_max"])
    margin = 5.0
    radius = min(
        step_um,
        max(0.0, x0 - x_min - margin),
        max(0.0, x_max - x0 - margin),
        max(0.0, y0 - y_min - margin),
        max(0.0, y_max - y0 - margin),
    )
    if radius < 1.0:
        x0 = (x_min + x_max) / 2.0
        y0 = (y_min + y_max) / 2.0
        radius = min(
            step_um,
            max(1.0, (x_max - x_min) / 4.0),
            max(1.0, (y_max - y_min) / 4.0),
        )
    positions = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        x = _clamp(x0 + radius * math.cos(angle), x_min, x_max)
        y = _clamp(y0 + radius * math.sin(angle), y_min, y_max)
        positions.append((round(x, 3), round(y, 3)))
    return positions


def _api_xy(client) -> tuple[float, float] | None:
    value = readers.get_xy(client, mode="api")
    pair = _xy_pair(value)
    return None if pair is None else (pair[0], pair[1])


def phase_xy_positions(
    client,
    records: list[dict[str, Any]],
    output: Path,
    *,
    count: int,
    step_um: float,
    tolerance_um: float,
) -> None:
    stage_cfg = drv.load_stage_config()
    drv.apply_stage_limits_from_config(stage_cfg)
    limits = drv.get_stage_limits()
    original = _api_xy(client)
    if original is None:
        raise RuntimeError("could not read starting XY position from API")
    positions = _xy_positions(original, limits, count, step_um)
    print(
        f"\n=== XY POSITIONS: {len(positions)} target(s), "
        f"step~{step_um:g}um, tolerance={tolerance_um:g}um ==="
    )
    try:
        for index, target in enumerate(positions, 1):
            fired_at = time.time()
            started = time.perf_counter()
            try:
                command = drv.move_xy(client, target[0], target[1], unit="um")
                command_error = None
            except Exception as exc:  # noqa: BLE001
                command = None
                command_error = f"{type(exc).__name__}: {exc}"
            command_ms = (time.perf_counter() - started) * 1000.0

            reads = _read_all_passive(client, "xy")
            xy_by_reader = _summarize_xy(reads, target)
            record = {
                "phase": "xy_position",
                "index": index,
                "target_um": [target[0], target[1]],
                "fired_at": fired_at,
                "command": {
                    "elapsed_ms": round(command_ms, 3),
                    "error": command_error,
                    "result": _jsonable(command),
                    "success": (None if command is None else command.get("success")),
                    "confirmed": (None if command is None else command.get("confirmed")),
                },
                "passive": reads,
                "xy_by_reader": xy_by_reader,
            }
            _emit(records, output, record)
            _print_xy_step(record)
    finally:
        print(f"Restoring original XY: ({original[0]:.1f}, {original[1]:.1f}) um")
        drv.move_xy(client, original[0], original[1], unit="um")


def _print_xy_step(record: dict[str, Any]) -> None:
    command = record["command"]
    api_delta = (record["xy_by_reader"].get("api") or {}).get("target_delta_um")
    ok = command.get("success") is True and api_delta is not None
    marker = "OK " if ok else "XX "
    target = record["target_um"]
    print(
        f"{marker}xy index={record['index']:02d} "
        f"target=({target[0]:.1f},{target[1]:.1f}) "
        f"cmd={command['elapsed_ms']:.0f}ms "
        f"api_delta={None if api_delta is None else round(api_delta, 3)}"
    )
    for mode in PASSIVE_MODES:
        read = record["passive"][mode]
        delta = (record["xy_by_reader"].get(mode) or {}).get("target_delta_um")
        print(
            f"    {mode:<4} {_brief_read(read)} "
            f"target_delta={None if delta is None else round(delta, 3)}"
        )
    if command.get("error"):
        print(f"    errors command={command.get('error')}")


def _build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    phases = {}
    for record in records:
        phase = record.get("phase")
        phases.setdefault(phase, {"count": 0, "ok": 0, "fail": 0})
        phases[phase]["count"] += 1
        ok = True
        if "command" in record:
            ok = ok and record["command"].get("success") is True
        if phase == "read_only":
            passive = record.get("passive") or {}
            ok = ok and all(
                read.get("status") not in {"error", "exception"} for read in passive.values()
            )
        if ok:
            phases[phase]["ok"] += 1
        else:
            phases[phase]["fail"] += 1
    return {
        "phases": phases,
        "records": len(records),
    }


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--client-name", default="PythonClient")
    parser.add_argument("--api-delay-ms", type=int)
    parser.add_argument("--read-only", action="store_true", help="skip job changes and XY moves")
    parser.add_argument(
        "--yes", action="store_true", help="allow reversible job changes and XY moves"
    )
    parser.add_argument("--job-a", help="first job for pairwise job changes")
    parser.add_argument("--job-b", help="second job for pairwise job changes")
    parser.add_argument(
        "--all-jobs", action="store_true", help="select every API-visible job in each round"
    )
    parser.add_argument(
        "--job-rounds", type=int, default=2, help="number of job-change rounds (default 2)"
    )
    parser.add_argument(
        "--positions", type=int, default=10, help="number of XY targets (default 10)"
    )
    parser.add_argument(
        "--xy-step-um",
        type=float,
        default=100.0,
        help="radius of XY position pattern around current XY",
    )
    parser.add_argument(
        "--xy-tolerance-um", type=float, default=20.0, help="reported XY target tolerance"
    )
    parser.add_argument("--output", default=None, help="JSONL output path")
    parser.add_argument("--append", action="store_true", help="append if --output already exists")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.job_rounds < 1:
        raise SystemExit("--job-rounds must be >= 1")
    if args.positions < 1:
        raise SystemExit("--positions must be >= 1")
    output = (
        Path(args.output)
        if args.output
        else (HERE / f"probe_four_readers_{_stamp()}_results.jsonl")
    )
    if output.exists() and not args.append:
        raise SystemExit(f"{output} exists; pass --append or choose another --output")
    output.parent.mkdir(parents=True, exist_ok=True)

    client = drv.connect_python_client(
        client_name=args.client_name,
        api_delay_ms=args.api_delay_ms,
    )
    records: list[dict[str, Any]] = []
    started_at = time.time()
    config = {
        "client_name": args.client_name,
        "api_delay_ms": args.api_delay_ms,
        "read_only": args.read_only,
        "job_rounds": args.job_rounds,
        "positions": args.positions,
        "xy_step_um": args.xy_step_um,
        "xy_tolerance_um": args.xy_tolerance_um,
        "job_a": args.job_a,
        "job_b": args.job_b,
        "all_jobs": args.all_jobs,
    }
    _emit(
        records,
        output,
        {
            "phase": "__start__",
            "started_at": started_at,
            "config": config,
        },
    )
    print("=== THREE-READER PROBE ===")
    print(f"records: {output}")

    selected_job = _current_selected_job(client)
    phase_read_only(client, records, output, selected_job)

    if args.read_only or not args.yes:
        if not args.yes and not args.read_only:
            print("\nWrites skipped. Pass --yes for two job rounds and 10 XY positions.")
    else:
        phase_job_changes(
            client,
            records,
            output,
            rounds=args.job_rounds,
            job_a=args.job_a,
            job_b=args.job_b,
            all_jobs=args.all_jobs,
        )
        phase_xy_positions(
            client,
            records,
            output,
            count=args.positions,
            step_um=args.xy_step_um,
            tolerance_um=args.xy_tolerance_um,
        )

    summary = _build_summary(records)
    _emit(
        records,
        output,
        {
            "phase": "__summary__",
            "elapsed_s": round(time.time() - started_at, 3),
            "summary": summary,
        },
    )
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"records: {output}")
    return 0 if all(v["fail"] == 0 for v in summary["phases"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
