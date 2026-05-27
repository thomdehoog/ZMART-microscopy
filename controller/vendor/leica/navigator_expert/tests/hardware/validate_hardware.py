"""Hardware validator for navigator_expert.driver.

Connects via LasxApi by default. The validator does not know -- and does
not care -- whether the LAS X session behind the API is running in
simulator mode or driving real optics; that's chosen in LAS X itself.
Run the script against LAS X simulator first to flush out driver bugs,
then point LAS X at the scope and run the same script against hardware.

For CI environments without LasxApi (no LAS X install at all), the
--mock flag swaps in the in-process Python mock at
tests/helpers/mock_lasx_api.py.

Every check produces a structured JSONL record so the results can be
fed into downstream tests or dashboards.

Safe by default:
  - reversible setting writes only
  - stage XY / Z / objective / acquire are all opt-in via separate flags
  - every reversible write is restored in a finally block
  - interactive 'yes' prompt before live writes unless --yes or --mock

Outputs:
  - human-readable progress (stdout, or stderr when JSONL streams to stdout)
  - JSONL records via --output PATH (or '-' for stdout)
    Each record: {name, status, started_at, elapsed_s, message,
                  timing, driver_message, driver_logs, context}
    Final record: {name: '__summary__', status: 'DONE',
                   context.counts, context.exit_code}

Usage:
  python validate_hardware.py --yes                        # LAS X (sim or live)
  python validate_hardware.py --yes --allow-xy             # + stage round-trip
  python validate_hardware.py --yes --allow-xy --allow-acquire
  python validate_hardware.py --output results.jsonl       # capture structured
  python validate_hardware.py --output -                   # stream JSONL to stdout
  python validate_hardware.py --mock                       # CI: python in-process mock

Status semantics:
  PASS   success=True, confirmed=True (or not applicable)
  WARN   success=True, confirmed=False (accepted but readback did not verify)
  FAIL   success=False, exception, or comparison mismatch
  SKIP   gated by flag / precondition

Exit code:
  0  no FAIL
  1  any FAIL (or any WARN with --strict-confirmation)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


# --- Record + classification ------------------------------------------------

@dataclass
class Record:
    """Structured outcome of a single validation step."""
    name: str
    status: str  # PASS, WARN, FAIL, SKIP, DONE
    started_at: str  # ISO-8601 UTC with ms
    elapsed_s: float
    message: str = ""
    timing: dict[str, Any] | None = None
    driver_message: str | None = None
    driver_logs: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


def _classify_result(result: dict) -> str:
    """Map a driver result envelope to PASS / WARN / FAIL."""
    if not result.get("success"):
        return "FAIL"
    if result.get("confirmed") is False:
        return "WARN"
    return "PASS"


def _compact_status(result: dict) -> str:
    """One-line summary of a driver result for the human log."""
    parts: list[str] = []
    msg = (result.get("message") or "").strip()
    if msg:
        parts.append(msg)
    timing = result.get("timing") or {}
    bits = []
    if "total_s" in timing:
        bits.append(f"total={float(timing['total_s']):.3f}s")
    if "attempts" in timing:
        bits.append(f"att={timing['attempts']}")
    if "confirm_attempts" in timing:
        bits.append(f"conf={timing['confirm_attempts']}")
    if "method" in timing:
        bits.append(f"m={timing['method']}")
    if bits:
        parts.append("[" + ", ".join(bits) + "]")
    return "; ".join(parts)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# --- Validator --------------------------------------------------------------

class Validator:
    """Runs and records validation checks against LasxApi or the Python mock."""

    def __init__(
        self,
        *,
        sink: Callable[[Record], None],
        log: logging.Logger,
        strict_confirmation: bool = False,
        show_driver_log: bool = False,
    ):
        self.records: list[Record] = []
        self._sink = sink
        self._log = log
        self.strict_confirmation = strict_confirmation
        self.show_driver_log = show_driver_log

    # Public recording surface ----------------------------------------------

    def command(self, name: str, run: Callable[[], dict], *,
                context: dict | None = None) -> dict | None:
        """Run a driver command. Records timing + structured driver result."""
        started, t0 = _now_iso(), time.monotonic()
        try:
            result = run()
        except Exception as exc:  # noqa: BLE001 -- record any failure mode
            self._emit(Record(
                name=name, status="FAIL", started_at=started,
                elapsed_s=time.monotonic() - t0,
                message=f"{type(exc).__name__}: {exc}",
                context=context or {},
            ))
            return None

        elapsed = time.monotonic() - t0
        if not isinstance(result, dict):
            self._emit(Record(
                name=name, status="FAIL", started_at=started,
                elapsed_s=elapsed,
                message=f"driver returned {type(result).__name__}, not dict",
                context=context or {},
            ))
            return result

        self._emit(Record(
            name=name,
            status=_classify_result(result),
            started_at=started,
            elapsed_s=elapsed,
            message=_compact_status(result),
            timing=result.get("timing"),
            driver_message=result.get("message"),
            driver_logs=list(result.get("logs") or []) if self.show_driver_log else [],
            context=context or {},
        ))
        return result

    def callable(self, name: str, run: Callable[[], Any], *,
                 context: dict | None = None) -> Any:
        """Run a non-command function (reader, helper). PASS unless it raises."""
        started, t0 = _now_iso(), time.monotonic()
        try:
            value = run()
        except Exception as exc:  # noqa: BLE001
            self._emit(Record(
                name=name, status="FAIL", started_at=started,
                elapsed_s=time.monotonic() - t0,
                message=f"{type(exc).__name__}: {exc}",
                context=context or {},
            ))
            return None
        self._emit(Record(
            name=name, status="PASS", started_at=started,
            elapsed_s=time.monotonic() - t0,
            context=context or {},
        ))
        return value

    def compare(self, name: str, actual: Any, expected: Any, *,
                tolerance: float | None = None) -> bool:
        """Record a comparison result. Returns True on match."""
        if tolerance is None:
            ok = actual == expected
        else:
            try:
                ok = abs(float(actual) - float(expected)) <= tolerance
            except (TypeError, ValueError):
                ok = False
        msg = f"expected={expected!r} actual={actual!r}"
        if tolerance is not None:
            msg += f" tol={tolerance}"
        self._emit(Record(
            name=name, status="PASS" if ok else "FAIL",
            started_at=_now_iso(), elapsed_s=0.0, message=msg,
        ))
        return ok

    def skip(self, name: str, reason: str) -> None:
        self._emit(Record(
            name=name, status="SKIP", started_at=_now_iso(),
            elapsed_s=0.0, message=reason,
        ))

    def fail(self, name: str, message: str, *,
             context: dict | None = None) -> None:
        self._emit(Record(
            name=name, status="FAIL", started_at=_now_iso(),
            elapsed_s=0.0, message=message,
            context=context or {},
        ))

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Marker for a phase boundary in the human log (no record)."""
        self._log.info("--- %s ---", name)
        yield

    def summary(self) -> Record:
        """Emit the final summary record and return it."""
        counts = self.counts()
        rec = Record(
            name="__summary__",
            status="DONE",
            started_at=_now_iso(),
            elapsed_s=0.0,
            message=("pass={PASS} warn={WARN} fail={FAIL} skip={SKIP}"
                     .format(**counts)),
            context={"counts": counts, "exit_code": self.exit_code()},
        )
        self._emit(rec)
        return rec

    # Querying ---------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        c = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
        for r in self.records:
            if r.status in c:
                c[r.status] += 1
        return c

    def exit_code(self) -> int:
        c = self.counts()
        if c["FAIL"] > 0:
            return 1
        if self.strict_confirmation and c["WARN"] > 0:
            return 1
        return 0

    # Internal ---------------------------------------------------------------

    def _emit(self, rec: Record) -> None:
        self.records.append(rec)
        self._sink(rec)
        self._log_human(rec)

    def _log_human(self, rec: Record) -> None:
        head = f"{rec.status:4s} | {rec.name}"
        if rec.elapsed_s > 0.001:
            head += f" ({rec.elapsed_s * 1000:.0f}ms)"
        if rec.message:
            head += f" -- {rec.message}"
        if rec.status == "FAIL":
            self._log.error(head)
        elif rec.status == "WARN":
            self._log.warning(head)
        else:
            self._log.info(head)
        if self.show_driver_log and rec.driver_logs:
            for entry in rec.driver_logs:
                self._log.info("    [%s] %s",
                               entry.get("level", "info"),
                               entry.get("msg", ""))


# --- Imports + client -------------------------------------------------------

def _bootstrap() -> tuple[Any, type]:
    """Configure sys.path and return (drv, MockLasxClient)."""
    here = Path(__file__).resolve()
    nav_root = here.parents[2]              # navigator_expert/
    leica_root = nav_root.parent            # vendor/leica/
    repo_root = here.parents[6]             # smart-microscopy/
    helpers = nav_root / "tests" / "helpers"
    for p in (str(leica_root), str(repo_root), str(helpers)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import navigator_expert.driver as drv  # noqa: PLC0415
    from mock_lasx_api import MockLasxClient  # noqa: PLC0415
    return drv, MockLasxClient


def _connect(args: argparse.Namespace, MockClient: type,
             log: logging.Logger) -> Any | None:
    """Build the LAS X client. Mock if --mock else LasxApi. Returns None on failure."""
    if args.mock:
        log.info("client | python in-process mock | latency=%.4fs",
                 args.mock_latency)
        return MockClient(latency=args.mock_latency)
    log.info("client | LasxApi (LAS X simulator or microscope)")
    try:
        import LasxApi.PYLICamApiConnector as lasx_api  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError) as exc:
        log.error("LasxApi import failed: %s", exc)
        return None
    client = lasx_api.LasxApiClientPyModel
    try:
        ok = client.Connect(args.client_name)
    except Exception as exc:  # noqa: BLE001 -- .NET interop throws AggregateException
        log.error("Connect raised (is LAS X running?): %s", exc)
        return None
    if not ok:
        log.error("Connect returned False (LAS X reachable but refused the client name)")
        return None
    return client


def _apply_stage_limits(drv: Any, v: Validator, args: argparse.Namespace) -> bool:
    """Apply calibrated safety limits before any movement happens."""
    stage_cfg = v.callable(
        "stage config: load",
        lambda: drv.load_stage_config(args.stage_config)
        if args.stage_config else drv.load_stage_config(),
        context={"path": args.stage_config or "<current>"},
    )
    if not stage_cfg:
        v.fail("stage limits: apply", "could not load stage configuration")
        return False

    try:
        lim = stage_cfg["limits_um"]
        limits = dict(
            x_min=lim["x"][0], x_max=lim["x"][1],
            y_min=lim["y"][0], y_max=lim["y"][1],
            z_galvo_min=lim["z_galvo"][0], z_galvo_max=lim["z_galvo"][1],
            z_wide_min=lim["z_wide"][0], z_wide_max=lim["z_wide"][1],
        )
    except (KeyError, TypeError, IndexError) as exc:
        v.fail("stage limits: apply", f"invalid stage configuration: {exc}")
        return False

    applied = v.callable(
        "stage limits: apply",
        lambda: _set_stage_limits(drv, limits),
        context={"limits": limits},
    )
    return bool(applied)


def _set_stage_limits(drv: Any, limits: dict[str, float]) -> bool:
    # Truthy wrapper so v.callable can record a successful setup step.
    drv.set_stage_limits(**limits)
    return True


# --- Driver helpers ---------------------------------------------------------

def _settings(drv: Any, client: Any, job_name: str) -> dict:
    """Read + parse current job settings (changeable copy)."""
    return drv.make_changeable_copy(drv.get_job_settings(client, job_name))


def _selected_job_name(drv: Any, client: Any) -> str | None:
    """Return the currently selected LAS X job name, if LAS X reports one."""
    jobs = drv.get_jobs(client)
    selected = next((j for j in jobs if j.get("IsSelected")), None)
    return selected["Name"] if selected else None


def _range_error(value: float, lower: float, upper: float, label: str) -> str | None:
    """Return an explanatory bounds error, or None when value is in range."""
    if value < lower or value > upper:
        return f"{label}={value} outside calibrated limits [{lower}, {upper}]"
    return None


def _xy_limit_error(x_um: float, y_um: float, limits: dict[str, float]) -> str | None:
    """Return why an XY point is outside the calibrated stage envelope."""
    return (
        _range_error(x_um, limits["x_min"], limits["x_max"], "X")
        or _range_error(y_um, limits["y_min"], limits["y_max"], "Y")
    )


def _z_limit_error(z_um: float, z_mode: str, limits: dict[str, float]) -> str | None:
    """Return why a Z point is outside the calibrated stage envelope."""
    if z_mode == "galvo":
        return _range_error(
            z_um, limits["z_galvo_min"], limits["z_galvo_max"], "Z galvo")
    if z_mode == "zwide":
        return _range_error(
            z_um, limits["z_wide_min"], limits["z_wide_max"], "Z wide")
    return f"unknown z_mode {z_mode!r}"


def _pick_alt(current: Any, candidates: list) -> Any | None:
    """Return the first candidate that differs from current, or None."""
    for c in candidates:
        if c != current:
            return c
    return None


# --- Validation phases ------------------------------------------------------

def phase_readonly(drv: Any, v: Validator, client: Any,
                   args: argparse.Namespace) -> str | None:
    """Read-only checks. Returns the job name to use for write phases."""
    with v.phase("read-only"):
        v.callable("ping", lambda: drv.ping(client))
        v.callable("get_scan_status", lambda: drv.get_scan_status(client))
        jobs = v.callable("get_jobs", lambda: drv.get_jobs(client))
        v.callable("get_hardware_info", lambda: drv.get_hardware_info(client))
        v.callable("get_xy", lambda: drv.get_xy(client))

        if not jobs:
            v.skip("job: resolve", "no jobs returned")
            return None
        names = [j["Name"] for j in jobs]
        if args.job:
            if args.job not in names:
                v.skip("job: resolve",
                       f"requested {args.job!r} not in {names!r}")
                return None
            name = args.job
        else:
            sel = next((j for j in jobs if j.get("IsSelected")), None)
            name = sel["Name"] if sel else jobs[0]["Name"]
        v.callable("job: resolved", lambda: name, context={"job": name})
        v.callable("settings: read",
                   lambda: _settings(drv, client, name),
                   context={"job": name})
        return name


def phase_job_selection(drv: Any, v: Validator, client: Any,
                        preferred_job: str) -> None:
    """Select an alternate job, verify, then restore the original selection."""
    with v.phase("job selection round-trip"):
        jobs = v.callable("job selection: read jobs", lambda: drv.get_jobs(client))
        if not jobs:
            v.skip("job selection: round-trip", "no jobs returned")
            return

        names = [j["Name"] for j in jobs]
        original = next(
            (j["Name"] for j in jobs if j.get("IsSelected")), preferred_job)
        target = preferred_job if preferred_job != original else _pick_alt(
            original, names)
        if target is None:
            v.skip("job selection: round-trip", "need at least two jobs")
            return

        ctx = {"current": original, "target": target}
        try:
            v.command("job selection: select alternate",
                      lambda: drv.select_job(client, target),
                      context=ctx)
            selected = v.callable("job selection: read alternate",
                                  lambda: _selected_job_name(drv, client))
            if selected is not None:
                v.compare("job selection: selected alternate", selected, target)
        finally:
            v.command("job selection: restore",
                      lambda: drv.select_job(client, original),
                      context={"restore_to": original})


def phase_settings(drv: Any, v: Validator, client: Any, job_name: str) -> None:
    """Reversible setting writes -- write current, write alternate, verify, restore."""
    with v.phase("settings round-trip"):
        _round_trip(
            v, "zoom", job_name,
            read=lambda: _settings(drv, client, job_name)["zoom"]["current"],
            write=lambda x: drv.set_zoom(client, job_name, x),
            candidates=[5.0, 10.0, 2.0, 1.0],
            tolerance=0.1,
        )
        _round_trip(
            v, "scan_speed", job_name,
            read=lambda: _settings(drv, client, job_name)["scanSpeed"]["value"],
            write=lambda x: drv.set_scan_speed(client, job_name, x),
            candidates=[400, 600, 800, 1000],
        )
        _round_trip(
            v, "image_format", job_name,
            read=lambda: _settings(drv, client, job_name)["format"],
            write=lambda x: drv.set_image_format(client, job_name, x),
            candidates=["512 x 512", "1024 x 1024"],
        )
        _round_trip(
            v, "frame_accumulation", job_name,
            read=lambda: _settings(drv, client, job_name)["activeSettings"][0][
                "frameAccumulation"
            ],
            write=lambda x: drv.set_frame_accumulation(client, job_name, 0, x),
            candidates=[1, 2, 4],
        )


def _round_trip(v: Validator, name: str, job_name: str, *,
                read: Callable[[], Any], write: Callable[[Any], dict],
                candidates: list, tolerance: float | None = None) -> None:
    """Read current, write current (no-op), write alt, verify, restore."""
    try:
        current = read()
    except Exception as exc:  # noqa: BLE001
        v.skip(f"{name}: round-trip", f"cannot read current: {exc}")
        return
    target = _pick_alt(current, candidates)
    if target is None:
        v.skip(f"{name}: round-trip", "no alternate candidate available")
        return
    ctx = {"job": job_name, "current": current, "target": target}
    v.command(f"{name}: write current", lambda: write(current), context=ctx)
    try:
        v.command(f"{name}: write alternate", lambda: write(target), context=ctx)
        try:
            actual = read()
        except Exception as exc:  # noqa: BLE001
            v.skip(f"{name}: readback", f"cannot read back: {exc}")
        else:
            v.compare(f"{name}: readback", actual, target, tolerance=tolerance)
    finally:
        v.command(f"{name}: restore", lambda: write(current),
                  context={"job": job_name, "restore_to": current})


def phase_xy(drv: Any, v: Validator, client: Any,
             args: argparse.Namespace) -> None:
    """Stage XY round-trip."""
    with v.phase("xy round-trip"):
        start = v.callable("xy: read start", lambda: drv.get_xy(client))
        if start is None:
            v.skip("xy: round-trip", "get_xy returned None")
            return
        x0, y0 = float(start["x_um"]), float(start["y_um"])
        x1, y1 = x0 + args.xy_delta_um, y0 + args.xy_delta_um
        limits = drv.get_stage_limits()
        start_error = _xy_limit_error(x0, y0, limits)
        if start_error:
            v.fail(
                "xy: round-trip",
                f"starting position outside limits: {start_error}. "
                "Configure LAS X simulator/hardware inside the calibrated "
                "envelope, or omit --allow-xy.",
                context={"position": (x0, y0), "limits": limits},
            )
            return
        target_error = _xy_limit_error(x1, y1, limits)
        if target_error:
            v.fail(
                "xy: round-trip",
                f"target position outside limits: {target_error}. "
                "Use a smaller --xy-delta-um or reposition the stage.",
                context={"from": (x0, y0), "to": (x1, y1), "limits": limits},
            )
            return
        ctx = {"from": (x0, y0), "to": (x1, y1)}
        try:
            v.command("xy: move alternate",
                      lambda: drv.move_xy(client, x1, y1, unit="um"),
                      context=ctx)
            end = v.callable("xy: read alternate", lambda: drv.get_xy(client))
            if end is None:
                v.skip("xy: readback", "get_xy returned None after move")
            else:
                v.compare("xy: x readback", end["x_um"], x1, tolerance=20.0)
                v.compare("xy: y readback", end["y_um"], y1, tolerance=20.0)
        finally:
            v.command("xy: restore",
                      lambda: drv.move_xy(client, x0, y0, unit="um"),
                      context={"restore_to": (x0, y0)})


def phase_z(drv: Any, v: Validator, client: Any, job_name: str,
            args: argparse.Namespace) -> None:
    """Z-galvo round-trip."""
    with v.phase("z-galvo round-trip"):
        ch = v.callable(
            "z: read start",
            lambda: _settings(drv, client, job_name),
            context={"job": job_name},
        )
        if not ch:
            return
        z0_raw = ch.get("zPosition", {}).get("z-galvo")
        z0 = float(z0_raw) if isinstance(z0_raw, (int, float)) else 0.0
        z1 = z0 + args.z_delta_um
        limits = drv.get_stage_limits()
        start_error = _z_limit_error(z0, "galvo", limits)
        if start_error:
            v.fail(
                "z: round-trip",
                f"starting position outside limits: {start_error}. "
                "Configure LAS X simulator/hardware inside the calibrated "
                "envelope, or omit --allow-z.",
                context={"position": z0, "limits": limits},
            )
            return
        target_error = _z_limit_error(z1, "galvo", limits)
        if target_error:
            v.fail(
                "z: round-trip",
                f"target position outside limits: {target_error}. "
                "Use a smaller --z-delta-um or reposition Z.",
                context={"from": z0, "to": z1, "limits": limits},
            )
            return
        ctx = {"job": job_name, "from": z0, "to": z1}
        try:
            v.command("z: move alternate",
                      lambda: drv.move_z(client, job_name, z1,
                                         unit="um", z_mode="galvo"),
                      context=ctx)
            after_settings = v.callable(
                "z: read alternate",
                lambda: _settings(drv, client, job_name),
                context={"job": job_name},
            )
            after = after_settings.get("zPosition", {}) if after_settings else {}
            actual = after.get("z-galvo")
            v.compare("z: readback", actual, z1, tolerance=1.0)
        finally:
            v.command("z: restore",
                      lambda: drv.move_z(client, job_name, z0,
                                         unit="um", z_mode="galvo"),
                      context={"restore_to": z0})


def phase_objective(drv: Any, v: Validator, client: Any, job_name: str) -> None:
    """Objective switch + restore."""
    with v.phase("objective round-trip"):
        hw = v.callable("objective: read hardware",
                        lambda: drv.get_hardware_info(client))
        ch = v.callable(
            "objective: read start",
            lambda: _settings(drv, client, job_name),
            context={"job": job_name},
        )
        if not hw or not ch:
            return
        current_name = ch.get("objective", {}).get("name")
        objectives = hw.get("Microscope", {}).get("objectives", [])
        current = next((o for o in objectives if o.get("name") == current_name), None)
        alts = [o for o in objectives if o.get("name") != current_name]
        if not current or not alts:
            v.skip("objective: round-trip", "no alternate objective available")
            return
        target = alts[0]
        ctx = {"from": current_name, "to": target.get("name")}
        try:
            v.command("objective: switch alternate",
                      lambda: drv.set_objective(client, job_name, hw,
                                                slot_index=target["slotIndex"]),
                      context=ctx)
        finally:
            v.command("objective: restore",
                      lambda: drv.set_objective(client, job_name, hw,
                                                slot_index=current["slotIndex"]),
                      context={"restore_to": current_name})


def phase_acquire(drv: Any, v: Validator, client: Any, job_name: str) -> None:
    """One acquisition through the driver."""
    with v.phase("acquire"):
        v.command("acquire: single", lambda: drv.acquire(client, job_name),
                  context={"job": job_name})


# --- CLI + output -----------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--mock", action="store_true",
                   help="use the python in-process mock (CI; no LasxApi needed). "
                        "Default is to connect via LasxApi -- the LAS X session "
                        "behind the API can be simulator mode or real hardware.")
    p.add_argument("--client-name", default="PythonClient",
                   help="LAS X client name (LasxApi.Connect)")
    p.add_argument("--job", help="job to validate (default: currently selected)")
    p.add_argument("--mock-latency", type=float, default=0.0,
                   help="per-command latency for --mock (seconds)")
    p.add_argument("--stage-config",
                   help="stage calibration JSON; default is current stage calibration")

    # Phase gates
    p.add_argument("--read-only", action="store_true",
                   help="skip all write/move/acquire phases")
    p.add_argument("--skip-settings", action="store_true",
                   help="skip reversible setting writes")
    p.add_argument("--allow-xy", action="store_true",
                   help="enable XY stage round-trip")
    p.add_argument("--allow-z", action="store_true",
                   help="enable Z galvo round-trip")
    p.add_argument("--allow-objective", action="store_true",
                   help="enable objective switch + restore")
    p.add_argument("--allow-acquire", action="store_true",
                   help="enable one acquisition")

    # Move deltas
    p.add_argument("--xy-delta-um", type=float, default=25.0)
    p.add_argument("--z-delta-um", type=float, default=2.0)

    # Output + interaction
    p.add_argument("--output", default=None,
                   help="JSONL output path; '-' for stdout")
    p.add_argument("--strict-confirmation", action="store_true",
                   help="treat WARN (success but unconfirmed) as exit 1")
    p.add_argument("--show-driver-log", action="store_true",
                   help="include driver backbone log entries in records")
    p.add_argument("--yes", action="store_true",
                   help="skip interactive confirmation before live writes")
    p.add_argument("--allow-missing-lasx", action="store_true",
                   help="record SKIP instead of FAIL when LasxApi cannot connect")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    return p.parse_args(argv)


def _confirm_live_write(args: argparse.Namespace) -> bool:
    """Prompt before writes against a real LAS X session. Bypass for --mock."""
    if args.read_only or args.yes or args.mock:
        return True
    parts = ["reversible setting writes"]
    if args.allow_xy: parts.append("XY move")
    if args.allow_z: parts.append("Z move")
    if args.allow_objective: parts.append("objective switch")
    if args.allow_acquire: parts.append("one acquire")
    sys.stdout.write("LAS X session will receive: " + ", ".join(parts) + ".\n")
    sys.stdout.write("Type 'yes' to continue: ")
    sys.stdout.flush()
    return sys.stdin.readline().strip().lower() == "yes"


def _make_sink(output: str | None,
               log: logging.Logger) -> Callable[[Record], None]:
    """Build the JSONL record sink based on --output."""
    if output is None:
        return lambda _r: None
    if output == "-":
        return lambda r: print(json.dumps(asdict(r)), flush=True)
    fh = open(output, "a", encoding="utf-8")
    log.info("recording JSONL to %s", output)

    def write(r: Record) -> None:
        fh.write(json.dumps(asdict(r)) + "\n")
        fh.flush()
    return write


def _configure_logging(level: str, jsonl_to_stdout: bool) -> logging.Logger:
    target = sys.stderr if jsonl_to_stdout else sys.stdout
    handler = logging.StreamHandler(target)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%H:%M:%S"))
    log = logging.getLogger("validate_hardware")
    log.setLevel(getattr(logging, level))
    if not log.handlers:
        log.addHandler(handler)
    log.propagate = False
    return log


# --- Main -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log = _configure_logging(args.log_level,
                             jsonl_to_stdout=(args.output == "-"))
    sink = _make_sink(args.output, log)
    drv, MockClient = _bootstrap()

    v = Validator(
        sink=sink, log=log,
        strict_confirmation=args.strict_confirmation,
        show_driver_log=args.show_driver_log,
    )

    log.info("=== smart-microscopy hardware validator ===")
    log.info("client=%s job=%s read_only=%s",
             "python-mock" if args.mock else "LasxApi (sim or scope)",
             args.job or "<selected>",
             args.read_only)

    try:
        client = _connect(args, MockClient, log)
        if client is None:
            if args.allow_missing_lasx:
                v.skip("client: connect", "could not establish client")
            else:
                v.fail("client: connect", "could not establish client")
            return v.exit_code()

        if not _apply_stage_limits(drv, v, args):
            return v.exit_code()

        job_name = phase_readonly(drv, v, client, args)
        if job_name is None:
            return v.exit_code()

        if args.read_only:
            log.info("read-only mode: skipping all writes")
            return v.exit_code()

        if not _confirm_live_write(args):
            log.warning("aborted before live writes")
            return v.exit_code()

        phase_job_selection(drv, v, client, job_name)

        if args.skip_settings:
            v.skip("phase: settings", "--skip-settings")
        else:
            phase_settings(drv, v, client, job_name)

        if args.allow_xy:
            phase_xy(drv, v, client, args)
        else:
            v.skip("phase: xy", "use --allow-xy to enable")

        if args.allow_z:
            phase_z(drv, v, client, job_name, args)
        else:
            v.skip("phase: z", "use --allow-z to enable")

        if args.allow_objective:
            phase_objective(drv, v, client, job_name)
        else:
            v.skip("phase: objective", "use --allow-objective to enable")

        if args.allow_acquire:
            phase_acquire(drv, v, client, job_name)
        else:
            v.skip("phase: acquire", "use --allow-acquire to enable")

    finally:
        v.summary()

    return v.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
