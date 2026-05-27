"""Randomized hardware stress runner for navigator_expert.driver.

This script is a manual integration runner, not a pytest test. It uses
the same bootstrap and safety setup as validate_hardware.py, then runs a
seeded sequence of reversible driver operations. The default pool avoids
time-series behavior, LRP/pan/ROI edits, scan-mode mutation, z-stack
setup, laser/filter changes, and detector-gain mutation for fixed/
photon-counting detectors. On HyD systems the detector-gain operation is
expected to report SKIP whenever the detector exposes fixed photon-counting
gain; that skip is part of the stress baseline, not a failed check.
Template strip/restore and acquisition are deterministic one-shot steps,
not random operations. Enable them explicitly when they are part of the
stress run you want to execute.

Use the Python mock for CI and fast refactor checks:
  python stress_hardware.py --mock --rounds 30 --cycles 4 --seed 1

Use LasxApi for the LAS X simulator or microscope:
  python stress_hardware.py --yes --rounds 30 --cycles 4 --seed 1

Stage and objective movement are opt-in:
  python stress_hardware.py --yes --allow-xy --allow-z --allow-objective

Template and acquisition checks are also opt-in:
  python stress_hardware.py --yes --allow-template-roundtrip --allow-acquire

Every stress step emits one JSONL record with its operation, selected job,
seed/cycle/round coordinates, timing, command confirmation, before/target/
after/restore characteristics, and final status. Post-command reader
mismatches are WARN by default because the stress run is meant to expose
reader instability under load without confusing that with command transport
failure. Use --strict-readback when readback mismatches should fail the run.
The summary record reports counts plus per-operation timing statistics so
repeated runs can be compared.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import validate_hardware as vh


@dataclass
class StressRecord:
    """Structured outcome for one stress step or the final summary."""

    kind: str
    status: str
    started_at: str
    elapsed_s: float
    seed: int
    cycle: int | None = None
    round: int | None = None
    step_index: int | None = None
    operation: str = ""
    job: str | None = None
    message: str = ""
    timing: dict[str, Any] | None = None
    driver_message: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


class StressRecorder:
    """Records stress steps to human logs and optional JSONL."""

    def __init__(
        self,
        *,
        seed: int,
        sink: Callable[[StressRecord], None],
        log: logging.Logger,
        strict_confirmation: bool = False,
    ):
        self.seed = seed
        self.records: list[StressRecord] = []
        self._sink = sink
        self._log = log
        self.strict_confirmation = strict_confirmation

    def emit(self, record: StressRecord) -> None:
        self.records.append(record)
        self._sink(record)
        self._log_step(record)

    def counts(self) -> dict[str, int]:
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
        for record in self.records:
            if record.kind == "stress_step" and record.status in counts:
                counts[record.status] += 1
        return counts

    def exit_code(self) -> int:
        counts = self.counts()
        if counts["FAIL"]:
            return 1
        if self.strict_confirmation and counts["WARN"]:
            return 1
        return 0

    def summary(self, *, args: argparse.Namespace) -> StressRecord:
        record = StressRecord(
            kind="stress_summary",
            status="DONE",
            started_at=vh._now_iso(),
            elapsed_s=0.0,
            seed=self.seed,
            message=_summary_message(self.counts()),
            context={
                "counts": self.counts(),
                "exit_code": self.exit_code(),
                "rounds": args.rounds,
                "cycles": args.cycles,
                "allow_template_roundtrip": args.allow_template_roundtrip,
                "allow_acquire": args.allow_acquire,
                "operation_stats": _operation_stats(self.records),
                "cycle_stats": _cycle_stats(self.records),
            },
        )
        self.emit(record)
        return record

    def _log_step(self, record: StressRecord) -> None:
        if record.kind == "stress_summary":
            self._log.info("DONE | %s", record.message)
            return
        head = (
            f"{record.status:4s} | "
            f"cycle={record.cycle} round={record.round} "
            f"op={record.operation}"
        )
        if record.job:
            head += f" job={record.job}"
        head += f" ({record.elapsed_s * 1000:.0f}ms)"
        if record.message:
            head += f" -- {record.message}"
        if record.status == "FAIL":
            self._log.error(head)
        elif record.status == "WARN":
            self._log.warning(head)
        else:
            self._log.info(head)


def _summary_message(counts: dict[str, int]) -> str:
    return "pass={PASS} warn={WARN} fail={FAIL} skip={SKIP}".format(**counts)


def _operation_stats(records: list[StressRecord]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    operations = sorted({
        r.operation for r in records
        if r.kind == "stress_step" and r.operation
    })
    for operation in operations:
        subset = [
            r for r in records
            if r.kind == "stress_step" and r.operation == operation
        ]
        elapsed = [r.elapsed_s for r in subset]
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
        confirm_attempts = []
        for record in subset:
            if record.status in counts:
                counts[record.status] += 1
            timing = record.timing or {}
            if "confirm_attempts" in timing:
                confirm_attempts.append(timing["confirm_attempts"])
        mean_s = statistics.fmean(elapsed) if elapsed else 0.0
        stdev_s = statistics.stdev(elapsed) if len(elapsed) > 1 else 0.0
        stats[operation] = {
            "count": len(subset),
            "counts": counts,
            "mean_s": mean_s,
            "median_s": statistics.median(elapsed) if elapsed else 0.0,
            "max_s": max(elapsed) if elapsed else 0.0,
            "stdev_s": stdev_s,
            "cv": (stdev_s / mean_s) if mean_s > 0 else 0.0,
            "max_confirm_attempts": (
                max(confirm_attempts) if confirm_attempts else None
            ),
        }
    return stats


def _cycle_stats(records: list[StressRecord]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    cycles = sorted({
        r.cycle for r in records
        if r.kind == "stress_step" and r.cycle is not None
    })
    for cycle in cycles:
        subset = [
            r for r in records
            if r.kind == "stress_step" and r.cycle == cycle
        ]
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
        for record in subset:
            if record.status in counts:
                counts[record.status] += 1
        elapsed = [r.elapsed_s for r in subset]
        stats[str(cycle)] = {
            "count": len(subset),
            "counts": counts,
            "total_s": sum(elapsed),
            "mean_step_s": statistics.fmean(elapsed) if elapsed else 0.0,
        }
    return stats


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _make_sink(output: str | None, log: logging.Logger) -> Callable[[StressRecord], None]:
    if output is None:
        return lambda _r: None
    if output == "-":
        return lambda r: print(json.dumps(_json_safe(asdict(r))), flush=True)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("w", encoding="utf-8")
    log.info("recording JSONL to %s", path)

    def write(record: StressRecord) -> None:
        fh.write(json.dumps(_json_safe(asdict(record))) + "\n")
        fh.flush()

    return write


def _configure_logging(level: str, jsonl_to_stdout: bool) -> logging.Logger:
    target = sys.stderr if jsonl_to_stdout else sys.stdout
    handler = logging.StreamHandler(target)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%H:%M:%S"))
    log = logging.getLogger("stress_hardware")
    log.handlers.clear()
    log.setLevel(getattr(logging, level))
    log.addHandler(handler)
    log.propagate = False
    return log


def _confirm_live_write(args: argparse.Namespace) -> bool:
    if args.yes or args.mock:
        return True
    parts = ["reversible setting writes", "job selection"]
    if args.allow_xy:
        parts.append("XY moves")
    if args.allow_z:
        parts.append("Z-galvo moves")
    if args.allow_objective:
        parts.append("objective switches")
    if args.allow_template_roundtrip:
        parts.append("template strip/restore")
    if args.allow_acquire:
        parts.append("one acquisition")
    sys.stdout.write("LAS X session will receive randomized: ")
    sys.stdout.write(", ".join(parts) + ".\n")
    sys.stdout.write("Type 'yes' to continue: ")
    sys.stdout.flush()
    return sys.stdin.readline().strip().lower() == "yes"


def _driver_call(run: Callable[[], dict]) -> tuple[str, str, dict[str, Any] | None, str | None]:
    try:
        result = run()
    except Exception as exc:  # noqa: BLE001 -- convert driver failures into records
        return "FAIL", f"{type(exc).__name__}: {exc}", None, None
    if not isinstance(result, dict):
        return "FAIL", f"driver returned {type(result).__name__}, not dict", None, None
    return (
        vh._classify_result(result),
        vh._compact_status(result),
        result.get("timing"),
        result.get("message"),
    )


def _combine_status(current: str, incoming: str) -> str:
    order = {"PASS": 0, "SKIP": 0, "WARN": 1, "FAIL": 2}
    return incoming if order[incoming] > order[current] else current


def _readback_status(strict_readback: bool) -> str:
    """Status for reader/readback problems after command transport succeeded."""
    return "FAIL" if strict_readback else "WARN"


def _compare(actual: Any, expected: Any, tolerance: float | None) -> bool:
    if tolerance is None:
        return actual == expected
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def _pick_random_alt(rng: random.Random, current: Any, candidates: list[Any]) -> Any | None:
    alts = [candidate for candidate in candidates if candidate != current]
    if not alts:
        return None
    return rng.choice(alts)


def _test_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def _install_general_workflow(source_dir: Path, templates_dir: Path) -> None:
    """Install one offline LRP/XML/RGN bundle under driver template filenames."""
    from navigator_expert.driver.templates.files import (  # noqa: PLC0415
        TEMPLATE_LRP,
        TEMPLATE_RGN,
        TEMPLATE_XML,
    )

    source_xml = next(source_dir.glob("*.xml"))
    base = source_xml.stem
    for suffix, target_name in (
        (".xml", TEMPLATE_XML),
        (".rgn", TEMPLATE_RGN),
        (".lrp", TEMPLATE_LRP),
    ):
        shutil.copy2(source_dir / f"{base}{suffix}", templates_dir / target_name)


@contextmanager
def _template_environment(args: argparse.Namespace) -> Iterator[Path | None]:
    """Provide a mock ScanningTemplates directory when no LAS X is present."""
    if not args.mock:
        yield None
        return

    import navigator_expert.driver.templates.strip_restore as strip_mod  # noqa: PLC0415

    source = _test_data_dir() / "general_workflow"
    if not source.is_dir():
        raise FileNotFoundError(f"missing offline workflow data: {source}")

    old_find = strip_mod.find_scanning_templates_dir
    old_save = strip_mod.save_experiment
    old_load = strip_mod.load_experiment
    with tempfile.TemporaryDirectory(prefix="stress_template_") as tmp:
        templates_dir = Path(tmp)
        _install_general_workflow(source, templates_dir)
        strip_mod.find_scanning_templates_dir = lambda: templates_dir
        strip_mod.save_experiment = (
            lambda *_args, **_kwargs: {"success": True, "confirmed": True}
        )
        strip_mod.load_experiment = (
            lambda *_args, **_kwargs: {"success": True, "confirmed": True}
        )
        try:
            yield templates_dir
        finally:
            strip_mod.find_scanning_templates_dir = old_find
            strip_mod.save_experiment = old_save
            strip_mod.load_experiment = old_load


def _step(
    recorder: StressRecorder,
    *,
    args: argparse.Namespace,
    cycle: int | None,
    round_index: int | None,
    step_index: int,
    operation: str,
    job: str | None,
    run: Callable[[], tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]],
) -> None:
    started, t0 = vh._now_iso(), time.monotonic()
    try:
        status, message, timing, driver_message, context = run()
    except Exception as exc:  # noqa: BLE001 -- stress records failures and restores where possible
        status = "FAIL"
        message = f"{type(exc).__name__}: {exc}"
        timing = None
        driver_message = None
        context = {}
    recorder.emit(StressRecord(
        kind="stress_step",
        status=status,
        started_at=started,
        elapsed_s=time.monotonic() - t0,
        seed=args.seed,
        cycle=cycle,
        round=round_index,
        step_index=step_index,
        operation=operation,
        job=job,
        message=message,
        timing=timing,
        driver_message=driver_message,
        context=context,
    ))


def _setting_round_trip(
    drv: Any,
    client: Any,
    job_name: str,
    rng: random.Random,
    *,
    setting_name: str,
    read: Callable[[], Any],
    write: Callable[[Any], dict],
    candidates: list[Any],
    tolerance: float | None = None,
    strict_readback: bool = False,
) -> tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]:
    context: dict[str, Any] = {
        "op_class": "setting_round_trip",
        "setting": setting_name,
    }
    try:
        current = read()
    except Exception as exc:  # noqa: BLE001
        return "SKIP", f"cannot read current: {exc}", None, None, context
    if current is None:
        return "SKIP", "current value is None; not safe to restore", None, None, context
    target = _pick_random_alt(rng, current, candidates)
    context.update({
        "current": current,
        "target": target,
        "restore_to": current,
    })
    if target is None:
        return "SKIP", "no alternate candidate available", None, None, context

    status = "PASS"
    timing = None
    driver_message = None
    messages: list[str] = []
    try:
        cmd_status, msg, timing, driver_message = _driver_call(lambda: write(target))
        status = _combine_status(status, cmd_status)
        messages.append(msg)
        if cmd_status == "FAIL":
            return status, "; ".join(m for m in messages if m), timing, driver_message, context
        if cmd_status == "WARN":
            messages.append("readback comparison suppressed after unconfirmed command")
        else:
            try:
                after = read()
            except Exception as exc:  # noqa: BLE001
                status = _combine_status(status, _readback_status(strict_readback))
                context["readback_status"] = "read_failed"
                messages.append(f"readback warning: {exc}")
            else:
                context["after"] = after
                if not _compare(after, target, tolerance):
                    status = _combine_status(
                        status, _readback_status(strict_readback))
                    context["readback_status"] = "mismatch"
                    messages.append(
                        f"readback mismatch expected={target!r} actual={after!r}"
                    )
    finally:
        restore_status, restore_msg, _restore_timing, _restore_driver_msg = (
            _driver_call(lambda: write(current))
        )
        context["restore_status"] = restore_status
        if restore_msg:
            context["restore_message"] = restore_msg
        status = _combine_status(status, restore_status)
        try:
            restored = read()
        except Exception as exc:  # noqa: BLE001
            status = _combine_status(status, _readback_status(strict_readback))
            context["restored"] = False
            context["restore_readback_status"] = "read_failed"
            messages.append(f"restore readback warning: {exc}")
        else:
            context["restored_value"] = restored
            context["restored"] = _compare(restored, current, tolerance)
            if not context["restored"]:
                status = _combine_status(status, _readback_status(strict_readback))
                context["restore_readback_status"] = "mismatch"
                messages.append(
                    f"restore mismatch expected={current!r} actual={restored!r}"
                )

    return status, "; ".join(m for m in messages if m), timing, driver_message, context


def _setting(drv: Any, client: Any, job_name: str, path: list[Any]) -> Any:
    value = vh._settings(drv, client, job_name)
    for key in path:
        value = value[key]
    return value


def _active_setting(drv: Any, client: Any, job_name: str) -> dict[str, Any]:
    setting = vh._active_setting(vh._settings(drv, client, job_name))
    if setting is None:
        raise RuntimeError("active setting 0 is missing")
    return setting


def op_select_job(
    drv: Any,
    client: Any,
    job_name: str,
    _rng: random.Random,
    args: argparse.Namespace,
) -> tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]:
    jobs = drv.get_jobs(client)
    names = [job["Name"] for job in jobs]
    selected = next((job["Name"] for job in jobs if job.get("IsSelected")), job_name)
    context: dict[str, Any] = {
        "op_class": "job_selection_sweep",
        "selected_at_start": selected,
        "selected_jobs": [],
        "restore_to": selected,
    }
    if not names:
        return "SKIP", "no jobs returned", None, None, context
    status = "PASS"
    timing = None
    driver_message = None
    messages: list[str] = []
    try:
        for name in names:
            cmd_status, msg, timing, driver_message = _driver_call(
                lambda name=name: drv.select_job(client, name)
            )
            status = _combine_status(status, cmd_status)
            context["selected_jobs"].append(name)
            if msg:
                messages.append(f"{name}: {msg}")
            if cmd_status == "FAIL":
                break
            readback = vh._selected_job_name(drv, client)
            if readback != name:
                status = _combine_status(
                    status, _readback_status(args.strict_readback))
                messages.append(f"{name}: readback={readback!r}")
    finally:
        restore_status, restore_msg, _restore_timing, _restore_driver_msg = _driver_call(
            lambda: drv.select_job(client, selected)
        )
        context["restore_status"] = restore_status
        if restore_msg:
            context["restore_message"] = restore_msg
        status = _combine_status(status, restore_status)
    return status, "; ".join(messages), timing, driver_message, context


def op_scan_mode_read(
    drv: Any,
    client: Any,
    job_name: str,
    _rng: random.Random,
    _args: argparse.Namespace,
) -> tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]:
    mode = vh._settings(drv, client, job_name).get("scanMode")
    context = {"op_class": "read_only", "value": mode, "expected": "xyz"}
    if mode != "xyz":
        return "FAIL", f"scan mode is {mode!r}, expected 'xyz'", None, None, context
    return "PASS", "scan mode is xyz", None, None, context


def op_detector_gain(
    drv: Any,
    client: Any,
    job_name: str,
    rng: random.Random,
    _args: argparse.Namespace,
) -> tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]:
    setting = _active_setting(drv, client, job_name)
    detectors = setting.get("activeDetectors") or []
    context: dict[str, Any] = {"op_class": "detector_gain_round_trip"}
    if not detectors:
        return "SKIP", "no active detector in setting 0", None, None, context
    detector = detectors[0]
    gain = detector.get("gain") or {}
    name = str(detector.get("name") or "")
    beam_route = detector.get("_beamRoute") or detector.get("beamRoute")
    current = gain.get("value")
    lower = gain.get("min", current)
    upper = gain.get("max", current)
    context.update({
        "detector": name,
        "beam_route": beam_route,
        "current": current,
        "range": [lower, upper],
    })
    if beam_route is None or current is None:
        return "SKIP", "detector gain readback incomplete", None, None, context
    if "hyd" in name.lower() or lower == upper:
        return (
            "SKIP",
            f"{name or 'detector'} exposes fixed/photon-counting gain; not mutating gain",
            None,
            None,
            context,
        )
    target = vh._bounded_numeric_candidate(
        float(current), float(lower), float(upper), rng.choice([1.0, 2.0])
    )
    if target is None:
        return "SKIP", "no alternate gain in range", None, None, context
    return _setting_round_trip(
        drv, client, job_name, rng,
        setting_name="detector_gain",
        read=lambda: _active_setting(drv, client, job_name)[
            "activeDetectors"
        ][0]["gain"]["value"],
        write=lambda value: drv.set_detector_gain(
            client, job_name, 0, beam_route, value
        ),
        candidates=[target, current],
        tolerance=0.1,
    )


def op_xy(
    drv: Any,
    client: Any,
    _job_name: str,
    rng: random.Random,
    args: argparse.Namespace,
) -> tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]:
    start = drv.get_xy(client)
    x0, y0 = float(start["x_um"]), float(start["y_um"])
    dx = rng.choice([-1.0, 1.0]) * args.xy_delta_um
    dy = rng.choice([-1.0, 1.0]) * args.xy_delta_um
    x1, y1 = x0 + dx, y0 + dy
    limits = drv.get_stage_limits()
    context: dict[str, Any] = {
        "op_class": "xy_round_trip",
        "current": [x0, y0],
        "target": [x1, y1],
        "delta": [dx, dy],
        "limits": limits,
    }
    start_error = vh._xy_limit_error(x0, y0, limits)
    target_error = vh._xy_limit_error(x1, y1, limits)
    if start_error:
        return "FAIL", f"starting position outside limits: {start_error}", None, None, context
    if target_error:
        return "SKIP", f"target position outside limits: {target_error}", None, None, context
    status = "PASS"
    timing = None
    driver_message = None
    messages: list[str] = []
    try:
        cmd_status, msg, timing, driver_message = _driver_call(
            lambda: drv.move_xy(client, x1, y1, unit="um")
        )
        status = _combine_status(status, cmd_status)
        messages.append(msg)
        if cmd_status == "PASS":
            after = drv.get_xy(client)
            context["after"] = [after["x_um"], after["y_um"]]
            if not (
                _compare(after["x_um"], x1, 20.0)
                and _compare(after["y_um"], y1, 20.0)
            ):
                status = _combine_status(
                    status, _readback_status(args.strict_readback))
                context["readback_status"] = "mismatch"
                messages.append("XY readback mismatch")
    finally:
        restore_status, restore_msg, _restore_timing, _restore_driver_msg = _driver_call(
            lambda: drv.move_xy(client, x0, y0, unit="um")
        )
        context["restore_status"] = restore_status
        if restore_msg:
            context["restore_message"] = restore_msg
        status = _combine_status(status, restore_status)
    return status, "; ".join(m for m in messages if m), timing, driver_message, context


def op_z(
    drv: Any,
    client: Any,
    job_name: str,
    rng: random.Random,
    args: argparse.Namespace,
) -> tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]:
    settings = vh._settings(drv, client, job_name)
    z_raw = settings.get("zPosition", {}).get("z-galvo")
    z0 = float(z_raw) if isinstance(z_raw, (int, float)) else 0.0
    dz = rng.choice([-1.0, 1.0]) * args.z_delta_um
    z1 = z0 + dz
    limits = drv.get_stage_limits()
    context: dict[str, Any] = {
        "op_class": "z_round_trip",
        "current": z0,
        "target": z1,
        "delta": dz,
        "limits": limits,
    }
    start_error = vh._z_limit_error(z0, "galvo", limits)
    target_error = vh._z_limit_error(z1, "galvo", limits)
    if start_error:
        return "FAIL", f"starting position outside limits: {start_error}", None, None, context
    if target_error:
        return "SKIP", f"target position outside limits: {target_error}", None, None, context
    status = "PASS"
    timing = None
    driver_message = None
    messages: list[str] = []
    try:
        cmd_status, msg, timing, driver_message = _driver_call(
            lambda: drv.move_z(client, job_name, z1, unit="um", z_mode="galvo")
        )
        status = _combine_status(status, cmd_status)
        messages.append(msg)
        if cmd_status == "PASS":
            after = vh._settings(drv, client, job_name)
            actual = after.get("zPosition", {}).get("z-galvo")
            context["after"] = actual
            if not _compare(actual, z1, 1.0):
                status = _combine_status(
                    status, _readback_status(args.strict_readback))
                context["readback_status"] = "mismatch"
                messages.append("Z readback mismatch")
    finally:
        restore_status, restore_msg, _restore_timing, _restore_driver_msg = _driver_call(
            lambda: drv.move_z(client, job_name, z0, unit="um", z_mode="galvo")
        )
        context["restore_status"] = restore_status
        if restore_msg:
            context["restore_message"] = restore_msg
        status = _combine_status(status, restore_status)
    return status, "; ".join(m for m in messages if m), timing, driver_message, context


def op_objective(
    drv: Any,
    client: Any,
    job_name: str,
    rng: random.Random,
    _args: argparse.Namespace,
) -> tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]:
    hw = drv.get_hardware_info(client)
    settings = vh._settings(drv, client, job_name)
    current_name = settings.get("objective", {}).get("name")
    objectives = hw.get("Microscope", {}).get("objectives", [])
    current = next((o for o in objectives if o.get("name") == current_name), None)
    alts = [o for o in objectives if o.get("name") != current_name]
    context: dict[str, Any] = {
        "op_class": "objective_round_trip",
        "current": current_name,
        "available": [o.get("name") for o in objectives],
    }
    if not current or not alts:
        return "SKIP", "no alternate objective available", None, None, context
    target = rng.choice(alts)
    context["target"] = target.get("name")
    status = "PASS"
    timing = None
    driver_message = None
    messages: list[str] = []
    try:
        cmd_status, msg, timing, driver_message = _driver_call(
            lambda: drv.set_objective(
                client, job_name, hw, slot_index=target["slotIndex"]
            )
        )
        status = _combine_status(status, cmd_status)
        messages.append(msg)
    finally:
        restore_status, restore_msg, _restore_timing, _restore_driver_msg = _driver_call(
            lambda: drv.set_objective(
                client, job_name, hw, slot_index=current["slotIndex"]
            )
        )
        context["restore_status"] = restore_status
        if restore_msg:
            context["restore_message"] = restore_msg
        status = _combine_status(status, restore_status)
    return status, "; ".join(m for m in messages if m), timing, driver_message, context


def op_template_roundtrip(
    drv: Any,
    client: Any,
    _job_name: str,
    _rng: random.Random,
    args: argparse.Namespace,
) -> tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]:
    context: dict[str, Any] = {
        "op_class": "template_strip_restore",
        "backend": "mock_data" if args.mock else "lasx_scanning_templates",
    }
    status = "PASS"
    messages: list[str] = []
    timing: dict[str, Any] | None = None
    try:
        with _template_environment(args) as templates_dir:
            if templates_dir is not None:
                context["templates_dir"] = str(templates_dir)
            strip_result = drv.strip_template(client, save_timeout=1 if args.mock else 120)
            context["strip_result"] = strip_result
            if strip_result and strip_result.get("success"):
                timing = {"strip_s": strip_result.get("total_s")}
            else:
                status = "FAIL"
                messages.append("strip_template failed")
            try:
                restore_result = drv.restore_template(client)
            finally:
                context["restore_attempted"] = True
            context["restore_result"] = restore_result
            if not restore_result or not restore_result.get("success"):
                status = "FAIL"
                messages.append("restore_template failed")
            else:
                if timing is None:
                    timing = {}
                timing["restore_s"] = restore_result.get("total_s")
                if status == "PASS":
                    messages.append(
                        "strip/restore ok "
                        f"fields={restore_result.get('fields')} "
                        f"items={restore_result.get('items')} "
                        f"focus={restore_result.get('focus')}"
                    )
                else:
                    messages.append("restore_template succeeded after strip failure")
    except Exception as exc:  # noqa: BLE001
        return "FAIL", f"{type(exc).__name__}: {exc}", timing, None, context
    return status, "; ".join(messages), timing, None, context


def op_acquire_once(
    drv: Any,
    client: Any,
    job_name: str,
    _rng: random.Random,
    _args: argparse.Namespace,
) -> tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]]:
    status, message, timing, driver_message = _driver_call(
        lambda: drv.acquire(client, job_name)
    )
    return status, message, timing, driver_message, {
        "op_class": "acquire_once",
        "job": job_name,
    }


Operation = Callable[
    [Any, Any, str, random.Random, argparse.Namespace],
    tuple[str, str, dict[str, Any] | None, str | None, dict[str, Any]],
]


def _operation_pool(args: argparse.Namespace) -> dict[str, Operation]:
    pool: dict[str, Operation] = {
        "zoom": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="zoom",
            read=lambda: _setting(drv, client, job, ["zoom", "current"]),
            write=lambda value: drv.set_zoom(client, job, value),
            candidates=[1.0, 2.0, 5.0, 10.0],
            tolerance=0.1,
            strict_readback=args.strict_readback,
        ),
        "scan_speed": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="scan_speed",
            read=lambda: _setting(drv, client, job, ["scanSpeed", "value"]),
            write=lambda value: drv.set_scan_speed(client, job, value),
            candidates=[400, 600, 800, 1000],
            strict_readback=args.strict_readback,
        ),
        "scan_resonant": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="scan_resonant",
            read=lambda: _setting(drv, client, job, ["scanSpeed", "isResonant"]),
            write=lambda value: drv.set_scan_resonant(client, job, value),
            candidates=[False, True],
            strict_readback=args.strict_readback,
        ),
        "scan_mode_read": op_scan_mode_read,
        "sequential_mode": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="sequential_mode",
            read=lambda: _setting(drv, client, job, ["sequentialMode"]),
            write=lambda value: drv.set_sequential_mode(client, job, value),
            candidates=["Frame", "Line"],
            strict_readback=args.strict_readback,
        ),
        "scan_field_rotation": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="scan_field_rotation",
            read=lambda: _setting(drv, client, job, ["scanFieldRotation", "value"]),
            write=lambda value: drv.set_scan_field_rotation(client, job, value),
            candidates=[-5.0, 0.0, 5.0],
            tolerance=0.5,
            strict_readback=args.strict_readback,
        ),
        "image_format": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="image_format",
            read=lambda: _setting(drv, client, job, ["format"]),
            write=lambda value: drv.set_image_format(client, job, value),
            candidates=["512 x 512", "1024 x 1024"],
            strict_readback=args.strict_readback,
        ),
        "frame_accumulation": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="frame_accumulation",
            read=lambda: _active_setting(drv, client, job)["frameAccumulation"],
            write=lambda value: drv.set_frame_accumulation(client, job, 0, value),
            candidates=[1, 2, 4],
            strict_readback=args.strict_readback,
        ),
        "frame_average": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="frame_average",
            read=lambda: _active_setting(drv, client, job)["frameAverage"],
            write=lambda value: drv.set_frame_average(client, job, 0, value),
            candidates=[1, 2, 4],
            strict_readback=args.strict_readback,
        ),
        "line_accumulation": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="line_accumulation",
            read=lambda: _active_setting(drv, client, job)["lineAccumulation"],
            write=lambda value: drv.set_line_accumulation(client, job, 0, value),
            candidates=[1, 2, 4],
            strict_readback=args.strict_readback,
        ),
        "line_average": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="line_average",
            read=lambda: _active_setting(drv, client, job)["lineAverage"],
            write=lambda value: drv.set_line_average(client, job, 0, value),
            candidates=[1, 2, 4],
            strict_readback=args.strict_readback,
        ),
        "pinhole_airy": lambda drv, client, job, rng, args: _setting_round_trip(
            drv, client, job, rng,
            setting_name="pinhole_airy",
            read=lambda: _active_setting(drv, client, job)["pinholeAiry"]["value"],
            write=lambda value: drv.set_pinhole_airy(client, job, 0, value),
            candidates=[0.8, 1.0, 1.2],
            tolerance=0.05,
            strict_readback=args.strict_readback,
        ),
        "detector_gain": op_detector_gain,
    }
    if args.allow_xy:
        pool["xy_move"] = op_xy
    if args.allow_z:
        pool["z_move"] = op_z
    if args.allow_objective:
        pool["objective_switch"] = op_objective
    return pool


def _run_stress(
    drv: Any,
    client: Any,
    job_name: str,
    recorder: StressRecorder,
    args: argparse.Namespace,
) -> int:
    rng = random.Random(args.seed)
    pool = _operation_pool(args)
    random_names = sorted(pool)
    step_index = 0

    for cycle in range(1, args.cycles + 1):
        # Force one complete job sweep per cycle before randomized settings.
        cycle_plan = ["job_selection"]
        if args.rounds > 1:
            cycle_plan.extend(
                rng.choice(random_names) for _ in range(args.rounds - 1)
            )
        for round_index, operation_name in enumerate(cycle_plan, start=1):
            step_index += 1
            operation = op_select_job if operation_name == "job_selection" else pool[operation_name]
            _step(
                recorder,
                args=args,
                cycle=cycle,
                round_index=round_index,
                step_index=step_index,
                operation=operation_name,
                job=job_name,
                run=lambda operation=operation: operation(
                    drv, client, job_name, rng, args
                ),
            )
    return step_index


def _run_terminal_steps(
    drv: Any,
    client: Any,
    job_name: str,
    recorder: StressRecorder,
    args: argparse.Namespace,
    *,
    step_index: int,
) -> None:
    rng = random.Random(args.seed)
    if args.allow_template_roundtrip:
        step_index += 1
        _step(
            recorder,
            args=args,
            cycle=None,
            round_index=None,
            step_index=step_index,
            operation="template_roundtrip",
            job=job_name,
            run=lambda: op_template_roundtrip(drv, client, job_name, rng, args),
        )
    if args.allow_acquire:
        step_index += 1
        _step(
            recorder,
            args=args,
            cycle=None,
            round_index=None,
            step_index=step_index,
            operation="acquire_once",
            job=job_name,
            run=lambda: op_acquire_once(drv, client, job_name, rng, args),
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mock", action="store_true",
                        help="use the Python in-process mock instead of LasxApi")
    parser.add_argument("--client-name", default="PythonClient",
                        help="LAS X client name passed to Connect")
    parser.add_argument("--job", help="job used for setting and Z operations")
    parser.add_argument("--mock-latency", type=float, default=0.0,
                        help="per-command latency for --mock")
    parser.add_argument("--stage-config",
                        help="stage calibration JSON; default is current calibration")
    parser.add_argument("--rounds", type=int, default=30,
                        help="stress steps per cycle; first step is a job sweep")
    parser.add_argument("--cycles", type=int, default=4,
                        help="number of repeated stress cycles")
    parser.add_argument("--seed", type=int, default=1,
                        help="random seed for reproducible operation order")
    parser.add_argument("--allow-xy", action="store_true",
                        help="include reversible XY moves in the random pool")
    parser.add_argument("--allow-z", action="store_true",
                        help="include reversible Z moves in the random pool")
    parser.add_argument("--allow-objective", action="store_true",
                        help="include reversible objective switches in the random pool")
    parser.add_argument("--allow-template-roundtrip", action="store_true",
                        help="run one template strip/restore round-trip after random stress")
    parser.add_argument("--allow-acquire", action="store_true",
                        help="run one acquisition after random stress")
    parser.add_argument("--xy-delta-um", type=float, default=25.0)
    parser.add_argument("--z-delta-um", type=float, default=2.0)
    parser.add_argument("--output", default=None,
                        help="JSONL output path; '-' for stdout")
    parser.add_argument("--strict-confirmation", action="store_true",
                        help="treat WARN as exit 1")
    parser.add_argument("--strict-readback", action="store_true",
                        help="promote extra post-command readback mismatches "
                             "from WARN to FAIL")
    parser.add_argument("--yes", action="store_true",
                        help="skip interactive confirmation before LasxApi writes")
    parser.add_argument("--allow-missing-lasx", action="store_true",
                        help="record SKIP instead of FAIL when LasxApi cannot connect")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)
    if args.rounds < 1:
        parser.error("--rounds must be >= 1")
    if args.cycles < 1:
        parser.error("--cycles must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log = _configure_logging(args.log_level, jsonl_to_stdout=(args.output == "-"))
    sink = _make_sink(args.output, log)
    drv, MockClient = vh._bootstrap()
    recorder = StressRecorder(
        seed=args.seed,
        sink=sink,
        log=log,
        strict_confirmation=args.strict_confirmation,
    )

    log.info("=== smart-microscopy hardware stress ===")
    log.info(
        "client=%s job=%s seed=%s rounds=%s cycles=%s",
        "python-mock" if args.mock else "LasxApi (sim or scope)",
        args.job or "<selected>",
        args.seed,
        args.rounds,
        args.cycles,
    )

    try:
        client = vh._connect(args, MockClient, log)
        if client is None:
            status = "SKIP" if args.allow_missing_lasx else "FAIL"
            recorder.emit(StressRecord(
                kind="stress_step",
                status=status,
                started_at=vh._now_iso(),
                elapsed_s=0.0,
                seed=args.seed,
                operation="client_connect",
                message="could not establish client",
            ))
            return recorder.exit_code()

        validator = vh.Validator(
            sink=lambda _r: None,
            log=log,
            strict_confirmation=args.strict_confirmation,
        )
        if not vh._apply_stage_limits(drv, validator, args):
            recorder.emit(StressRecord(
                kind="stress_step",
                status="FAIL",
                started_at=vh._now_iso(),
                elapsed_s=0.0,
                seed=args.seed,
                operation="stage_limits",
                message="could not apply stage limits",
            ))
            return recorder.exit_code()

        job_name = vh.phase_readonly(drv, validator, client, args)
        if job_name is None:
            recorder.emit(StressRecord(
                kind="stress_step",
                status="FAIL",
                started_at=vh._now_iso(),
                elapsed_s=0.0,
                seed=args.seed,
                operation="job_resolve",
                message="could not resolve job",
            ))
            return recorder.exit_code()

        if not _confirm_live_write(args):
            log.warning("aborted before live writes")
            return recorder.exit_code()

        step_index = _run_stress(drv, client, job_name, recorder, args)
        _run_terminal_steps(
            drv, client, job_name, recorder, args, step_index=step_index)
    finally:
        recorder.summary(args=args)

    return recorder.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
