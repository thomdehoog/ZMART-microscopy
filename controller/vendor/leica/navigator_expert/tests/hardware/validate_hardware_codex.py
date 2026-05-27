"""Manual hardware validator for the Leica Navigator Expert driver.

Run this script before using a restructured driver on the microscope.
It exercises the same public driver API against either the in-process
LAS X simulator or a live LAS X connection:

    python validate_hardware_codex.py
    python validate_hardware_codex.py --live --yes
    python validate_hardware_codex.py --live --job HiRes --skip-acquire

The validator is intentionally not a pytest test. It performs reversible
setting changes, optional stage/Z/objective moves, and at most one
acquisition command. Every command result is logged with timestamped
PASS/WARN/FAIL status so stale LAS X readback is visible without hiding
the actual driver result.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


LOGGER = logging.getLogger("validate_hardware_codex")


@dataclass
class CheckResult:
    """Single validation outcome shown in the final summary."""

    name: str
    status: str
    message: str = ""


class Validator:
    """Small result recorder for command-oriented hardware checks."""

    def __init__(
        self,
        *,
        strict_confirmation: bool = False,
        show_driver_log: bool = False,
    ):
        self.strict_confirmation = strict_confirmation
        self.show_driver_log = show_driver_log
        self.results: list[CheckResult] = []

    def pass_(self, name: str, message: str = "") -> None:
        self._record("PASS", name, message)

    def warn(self, name: str, message: str = "") -> None:
        self._record("WARN", name, message)

    def fail(self, name: str, message: str = "") -> None:
        self._record("FAIL", name, message)

    def skip(self, name: str, message: str = "") -> None:
        self._record("SKIP", name, message)

    def command(self, name: str, func: Callable[[], dict[str, Any]]) -> dict[str, Any] | None:
        """Run a driver command and record success/confirmation state."""
        try:
            result = func()
        except Exception as exc:  # pragma: no cover - hardware safety path
            self.fail(name, f"{type(exc).__name__}: {exc}")
            return None

        if not isinstance(result, dict):
            self.fail(name, f"driver returned {type(result).__name__}: {result!r}")
            return result

        success = bool(result.get("success"))
        confirmed = result.get("confirmed")
        message = _format_command_detail(result)

        if success and confirmed is not False:
            detail = "confirmed" if confirmed is True else "accepted"
            self.pass_(name, _join(detail, message))
        elif success and confirmed is False:
            self.warn(name, _join("accepted but not confirmed", message))
        else:
            self.fail(name, message or repr(result))

        if self.show_driver_log:
            _emit_driver_log(name, result)

        return result

    def callable(self, name: str, func: Callable[[], Any]) -> Any:
        """Run a non-command check and record whether it raised."""
        try:
            value = func()
        except Exception as exc:  # pragma: no cover - hardware safety path
            self.fail(name, f"{type(exc).__name__}: {exc}")
            return None
        self.pass_(name)
        return value

    def compare(self, name: str, actual: Any, expected: Any, *, tolerance: float | None = None) -> None:
        """Record a readback comparison."""
        if tolerance is None:
            ok = actual == expected
        else:
            try:
                ok = abs(float(actual) - float(expected)) <= tolerance
            except (TypeError, ValueError):
                ok = False
        if ok:
            self.pass_(name, f"{actual!r}")
        else:
            self.fail(name, f"expected {expected!r}, got {actual!r}")

    def exit_code(self) -> int:
        if any(result.status == "FAIL" for result in self.results):
            return 1
        if self.strict_confirmation and any(result.status == "WARN" for result in self.results):
            return 1
        return 0

    def summary(self) -> None:
        counts = {status: 0 for status in ("PASS", "WARN", "FAIL", "SKIP")}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        LOGGER.info(
            "summary | pass=%d warn=%d fail=%d skip=%d",
            counts["PASS"],
            counts["WARN"],
            counts["FAIL"],
            counts["SKIP"],
        )

    def _record(self, status: str, name: str, message: str = "") -> None:
        self.results.append(CheckResult(name=name, status=status, message=message))
        text = f"{status:4s} | {name}"
        if message:
            text = f"{text} | {message}"
        if status == "FAIL":
            LOGGER.error(text)
        elif status == "WARN":
            LOGGER.warning(text)
        else:
            LOGGER.info(text)


def _repo_paths() -> tuple[Path, Path, Path]:
    """Return navigator_expert root, Leica package root, and repo root."""
    here = Path(__file__).resolve()
    navigator_root = here.parents[2]
    leica_root = navigator_root.parent
    repo_root = here.parents[6]
    return navigator_root, leica_root, repo_root


def _bootstrap_imports() -> tuple[Any, type]:
    """Make local packages importable and return driver + mock client class."""
    navigator_root, leica_root, repo_root = _repo_paths()
    helpers_root = navigator_root / "tests" / "helpers"

    for path in (str(leica_root), str(repo_root), str(helpers_root)):
        if path not in sys.path:
            sys.path.insert(0, path)

    import navigator_expert.driver as drv  # noqa: PLC0415
    from mock_lasx_api import MockLasxClient  # noqa: PLC0415

    return drv, MockLasxClient


def _connect_client(args: argparse.Namespace, mock_client_cls: type) -> Any:
    """Create the selected LAS X client."""
    if not args.live:
        LOGGER.info("client | simulator | latency=%.3fs", args.simulator_latency)
        return mock_client_cls(latency=args.simulator_latency)

    LOGGER.info("client | live LAS X | connector=LasxApi.PYLICamApiConnector")
    try:
        import LasxApi.PYLICamApiConnector as lasx_api  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - requires LAS X install
        raise RuntimeError(
            "Could not import LasxApi.PYLICamApiConnector. "
            "Run inside the LAS X Python environment."
        ) from exc

    client = lasx_api.LasxApiClientPyModel
    client.Connect(args.client_name)
    return client


def _join(left: str, right: str) -> str:
    return f"{left}: {right}" if right else left


def _format_command_detail(result: dict[str, Any]) -> str:
    """Summarise a driver result envelope for human validation logs."""
    parts = []
    message = str(result.get("message", "")).strip()
    if message:
        parts.append(message)

    timing = result.get("timing") or {}
    if timing:
        total = timing.get("total_s")
        attempts = timing.get("attempts")
        confirm_attempts = timing.get("confirm_attempts")
        method = timing.get("method")
        timing_parts = []
        if total is not None:
            timing_parts.append(f"total={float(total):.3f}s")
        if attempts is not None:
            timing_parts.append(f"attempts={attempts}")
        if confirm_attempts is not None:
            timing_parts.append(f"confirm_attempts={confirm_attempts}")
        if method:
            timing_parts.append(f"method={method}")
        if timing_parts:
            parts.append("timing[" + ", ".join(timing_parts) + "]")

    logs = result.get("logs") or []
    if logs:
        parts.append(f"driver_logs={len(logs)}")

    return "; ".join(parts)


def _emit_driver_log(command_name: str, result: dict[str, Any]) -> None:
    """Emit accumulated driver backbone log entries for one command."""
    for entry in result.get("logs") or []:
        level = str(entry.get("level", "info")).upper()
        message = entry.get("msg", "")
        LOGGER.info("driver-log | %s | %s | %s", command_name, level, message)


def _selected_job_name(drv: Any, client: Any, requested: str | None) -> str:
    jobs = drv.get_jobs(client)
    if not jobs:
        raise RuntimeError("LAS X returned no jobs")

    names = [job.get("Name") for job in jobs]
    if requested:
        if requested not in names:
            raise RuntimeError(f"requested job {requested!r} not found; jobs={names!r}")
        return requested

    selected = next((job for job in jobs if job.get("IsSelected")), None)
    if selected and selected.get("Name"):
        return selected["Name"]
    return names[0]


def _changeable(drv: Any, client: Any, job_name: str) -> dict[str, Any]:
    return drv.make_changeable_copy(drv.get_job_settings(client, job_name))


def _active_setting(changeable: dict[str, Any], setting_index: int) -> dict[str, Any]:
    settings = changeable.get("activeSettings", [])
    if setting_index >= len(settings):
        raise RuntimeError(
            f"setting_index={setting_index} unavailable; activeSettings={len(settings)}"
        )
    return settings[setting_index]


def _choose_different(current: Any, candidates: list[Any]) -> Any:
    for candidate in candidates:
        if candidate != current:
            return candidate
    raise RuntimeError(f"no alternate candidate for {current!r}")


def _choose_float(current: float, candidates: list[float], *, tolerance: float = 1e-6) -> float:
    for candidate in candidates:
        if abs(float(candidate) - float(current)) > tolerance:
            return candidate
    raise RuntimeError(f"no alternate candidate for {current!r}")


def _configure_stage_limits(drv: Any, validator: Validator, stage_config: str | None) -> dict[str, Any] | None:
    cfg = validator.callable(
        "stage config: load",
        lambda: drv.load_stage_config(stage_config) if stage_config else drv.load_stage_config(),
    )
    if not cfg:
        return None
    validator.callable("stage limits: apply", lambda: drv.apply_stage_limits_from_config(cfg))
    return cfg


def _restore_setting(
    validator: Validator,
    name: str,
    setter: Callable[[Any], dict[str, Any]],
    value: Any,
) -> None:
    validator.command(f"{name}: restore", lambda: setter(value))


def validate_readers(drv: Any, validator: Validator, client: Any, job_name: str) -> None:
    """Validate read-only driver state before any writes happen."""
    validator.callable("ping", lambda: drv.ping(client))
    jobs = validator.callable("jobs: read", lambda: drv.get_jobs(client))
    hardware = validator.callable("hardware: read", lambda: drv.get_hardware_info(client))
    changeable = validator.callable("settings: read", lambda: _changeable(drv, client, job_name))
    position = validator.callable("xy: read", lambda: drv.get_xy(client))

    if jobs:
        LOGGER.info("state | jobs=%s | selected_job=%s", [j.get("Name") for j in jobs], job_name)
    if hardware:
        objectives = hardware.get("Microscope", {}).get("objectives", [])
        LOGGER.info("state | objectives=%s", [obj.get("name") for obj in objectives])
    if changeable:
        LOGGER.info(
            "state | job=%s zoom=%s speed=%s format=%s",
            job_name,
            changeable.get("zoom", {}).get("current"),
            changeable.get("scanSpeed", {}).get("value"),
            changeable.get("format"),
        )
        validator.callable("geometry: parse", lambda: drv.parse_tile_geometry(drv.get_job_settings(client, job_name)))
    if position:
        LOGGER.info("state | xy_um=(%.2f, %.2f)", position["x_um"], position["y_um"])


def validate_reversible_settings(
    drv: Any,
    validator: Validator,
    client: Any,
    job_name: str,
    setting_index: int,
    include_light: bool,
) -> None:
    """Validate a focused set of reversible setting commands."""
    changeable = _changeable(drv, client, job_name)
    setting = _active_setting(changeable, setting_index)

    current_zoom = float(changeable["zoom"]["current"])
    target_zoom = _choose_float(current_zoom, [5.0, 10.0, 2.0, 1.0])
    validator.command("zoom: write current", lambda: drv.set_zoom(client, job_name, current_zoom))
    try:
        validator.command("zoom: write alternate", lambda: drv.set_zoom(client, job_name, target_zoom))
        after = _changeable(drv, client, job_name)["zoom"]["current"]
        validator.compare("zoom: readback", after, target_zoom, tolerance=0.1)
    finally:
        _restore_setting(validator, "zoom", lambda value: drv.set_zoom(client, job_name, value), current_zoom)

    changeable = _changeable(drv, client, job_name)
    current_speed = int(changeable["scanSpeed"]["value"])
    target_speed = _choose_different(current_speed, [400, 600, 800, 1000])
    validator.command("scan speed: write current", lambda: drv.set_scan_speed(client, job_name, current_speed))
    try:
        validator.command(
            "scan speed: write alternate",
            lambda: drv.set_scan_speed(client, job_name, target_speed),
        )
        after = _changeable(drv, client, job_name)["scanSpeed"]["value"]
        validator.compare("scan speed: readback", after, target_speed)
    finally:
        _restore_setting(
            validator,
            "scan speed",
            lambda value: drv.set_scan_speed(client, job_name, value),
            current_speed,
        )

    changeable = _changeable(drv, client, job_name)
    current_format = changeable["format"]
    target_format = _choose_different(current_format, ["512 x 512", "1024 x 1024"])
    validator.command("image format: write current", lambda: drv.set_image_format(client, job_name, current_format))
    try:
        validator.command(
            "image format: write alternate",
            lambda: drv.set_image_format(client, job_name, target_format),
        )
        after = _changeable(drv, client, job_name)["format"]
        validator.compare("image format: readback", after, target_format)
    finally:
        _restore_setting(
            validator,
            "image format",
            lambda value: drv.set_image_format(client, job_name, value),
            current_format,
        )

    changeable = _changeable(drv, client, job_name)
    setting = _active_setting(changeable, setting_index)
    current_accumulation = int(setting["frameAccumulation"])
    target_accumulation = _choose_different(current_accumulation, [1, 2, 4])
    validator.command(
        "frame accumulation: write current",
        lambda: drv.set_frame_accumulation(
            client, job_name, setting_index, current_accumulation
        ),
    )
    try:
        validator.command(
            "frame accumulation: write alternate",
            lambda: drv.set_frame_accumulation(
                client, job_name, setting_index, target_accumulation
            ),
        )
        after = _active_setting(_changeable(drv, client, job_name), setting_index)[
            "frameAccumulation"
        ]
        validator.compare("frame accumulation: readback", after, target_accumulation)
    finally:
        _restore_setting(
            validator,
            "frame accumulation",
            lambda value: drv.set_frame_accumulation(client, job_name, setting_index, value),
            current_accumulation,
        )

    if include_light:
        _validate_reversible_laser_intensity(
            drv, validator, client, job_name, setting_index, setting
        )
    else:
        validator.skip("laser intensity", "use --include-light to test laser power")


def _validate_reversible_laser_intensity(
    drv: Any,
    validator: Validator,
    client: Any,
    job_name: str,
    setting_index: int,
    setting: dict[str, Any],
) -> None:
    lasers = setting.get("activeLaserLines", [])
    if not lasers:
        validator.skip("laser intensity", "no active laser line")
        return

    laser = lasers[0]
    beam_route = laser["beamRoute"]
    line_index = int(laser.get("lineIndex", 0))
    current = float(laser["intensity"]["value"])
    target = min(1.0, current + 0.01) if current <= 0.99 else max(0.0, current - 0.01)

    setter = lambda value: drv.set_laser_intensity(
        client, job_name, setting_index, beam_route, line_index, value
    )
    validator.command("laser intensity: write current", lambda: setter(current))
    try:
        validator.command("laser intensity: write alternate", lambda: setter(target))
        after_setting = _active_setting(_changeable(drv, client, job_name), setting_index)
        after_laser = next(
            item
            for item in after_setting.get("activeLaserLines", [])
            if item.get("beamRoute") == beam_route
        )
        validator.compare(
            "laser intensity: readback",
            after_laser["intensity"]["value"],
            target,
            tolerance=0.005,
        )
    finally:
        _restore_setting(validator, "laser intensity", setter, current)


def validate_stage_move(
    drv: Any,
    validator: Validator,
    client: Any,
    dx_um: float,
    dy_um: float,
) -> None:
    """Move XY once and restore the original position."""
    start = drv.get_xy(client)
    x0 = float(start["x_um"])
    y0 = float(start["y_um"])
    x1 = x0 + dx_um
    y1 = y0 + dy_um

    try:
        validator.command("xy: move alternate", lambda: drv.move_xy(client, x1, y1, unit="um"))
        after = drv.get_xy(client)
        validator.compare("xy: x readback", after["x_um"], x1, tolerance=20.0)
        validator.compare("xy: y readback", after["y_um"], y1, tolerance=20.0)
    finally:
        validator.command("xy: restore", lambda: drv.move_xy(client, x0, y0, unit="um"))


def validate_z_move(
    drv: Any,
    validator: Validator,
    client: Any,
    job_name: str,
    dz_um: float,
) -> None:
    """Move galvo Z once and restore the original position."""
    start = _changeable(drv, client, job_name)
    z0 = float(start.get("zPosition", {}).get("z-galvo", 0.0))
    z1 = z0 + dz_um
    try:
        validator.command(
            "z galvo: move alternate",
            lambda: drv.move_z(client, job_name, z1, unit="um", z_mode="galvo"),
        )
        after = _changeable(drv, client, job_name)
        validator.compare(
            "z galvo: readback",
            after.get("zPosition", {}).get("z-galvo"),
            z1,
            tolerance=1.0,
        )
    finally:
        validator.command(
            "z galvo: restore",
            lambda: drv.move_z(client, job_name, z0, unit="um", z_mode="galvo"),
        )


def validate_objective_switch(
    drv: Any,
    validator: Validator,
    client: Any,
    job_name: str,
) -> None:
    """Switch to a different objective slot and restore the original slot."""
    hardware = drv.get_hardware_info(client)
    changeable = _changeable(drv, client, job_name)
    current_name = changeable.get("objective", {}).get("name")
    objectives = hardware.get("Microscope", {}).get("objectives", [])
    candidates = [obj for obj in objectives if obj.get("name") and obj.get("name") != current_name]
    current = next((obj for obj in objectives if obj.get("name") == current_name), None)

    if not current or not candidates:
        validator.skip("objective", "no alternate objective available")
        return

    target = candidates[0]
    try:
        validator.command(
            "objective: switch alternate",
            lambda: drv.set_objective(
                client, job_name, hardware, slot_index=target["slotIndex"]
            ),
        )
    finally:
        validator.command(
            "objective: restore",
            lambda: drv.set_objective(
                client, job_name, hardware, slot_index=current["slotIndex"]
            ),
        )


def validate_acquire(drv: Any, validator: Validator, client: Any, job_name: str) -> None:
    """Fire exactly one acquisition command through the driver."""
    validator.command("acquire: single command", lambda: drv.acquire(client, job_name))


def _confirm_live_write(args: argparse.Namespace) -> None:
    if not args.live or args.read_only or args.yes:
        return
    print(
        "Live validation will perform reversible setting writes and stage movement. "
        "Use --read-only to skip writes."
    )
    answer = input("Type 'yes' to continue: ").strip().lower()
    if answer != "yes":
        raise SystemExit("aborted before live writes")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the Leica Navigator Expert driver against simulator or live LAS X."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--simulator", action="store_true", help="use the in-process LAS X mock")
    mode.add_argument("--live", action="store_true", help="connect to live LAS X")
    parser.add_argument("--client-name", default="PythonClient", help="LAS X client name for --live")
    parser.add_argument("--job", help="job name to validate; defaults to the selected job")
    parser.add_argument("--setting-index", type=int, default=0, help="activeSettings index")
    parser.add_argument("--stage-config", help="explicit stage.json path")
    parser.add_argument("--simulator-latency", type=float, default=0.0, help="mock command latency")
    parser.add_argument("--read-only", action="store_true", help="skip all write/move/acquire checks")
    parser.add_argument("--skip-move", action="store_true", help="skip XY stage move")
    parser.add_argument("--skip-acquire", action="store_true", help="skip acquisition")
    parser.add_argument("--include-light", action="store_true", help="include reversible laser intensity check")
    parser.add_argument("--allow-z", action="store_true", help="include a reversible galvo Z move")
    parser.add_argument("--allow-objective", action="store_true", help="include objective switch/restore")
    parser.add_argument("--dx-um", type=float, default=25.0, help="XY validation move delta X")
    parser.add_argument("--dy-um", type=float, default=25.0, help="XY validation move delta Y")
    parser.add_argument("--dz-um", type=float, default=2.0, help="Z validation move delta")
    parser.add_argument("--strict-confirmation", action="store_true", help="treat WARN as non-zero exit")
    parser.add_argument(
        "--show-driver-log",
        action="store_true",
        help="print accumulated driver backbone log entries for each command",
    )
    parser.add_argument("--yes", action="store_true", help="do not prompt before live writes")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)
    if not args.live:
        args.simulator = True
    return args


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)

    drv, mock_client_cls = _bootstrap_imports()
    validator = Validator(
        strict_confirmation=args.strict_confirmation,
        show_driver_log=args.show_driver_log,
    )
    client = _connect_client(args, mock_client_cls)

    _configure_stage_limits(drv, validator, args.stage_config)

    job_name = validator.callable(
        "job: resolve",
        lambda: _selected_job_name(drv, client, args.job),
    )
    if not job_name:
        validator.summary()
        return validator.exit_code()

    validate_readers(drv, validator, client, job_name)

    if args.read_only:
        validator.skip("write checks", "--read-only")
        validator.summary()
        return validator.exit_code()

    _confirm_live_write(args)

    validate_reversible_settings(
        drv,
        validator,
        client,
        job_name,
        setting_index=args.setting_index,
        include_light=args.include_light,
    )

    if args.skip_move:
        validator.skip("xy move", "--skip-move")
    else:
        validate_stage_move(drv, validator, client, args.dx_um, args.dy_um)

    if args.allow_z:
        validate_z_move(drv, validator, client, job_name, args.dz_um)
    else:
        validator.skip("z galvo", "use --allow-z")

    if args.allow_objective:
        validate_objective_switch(drv, validator, client, job_name)
    else:
        validator.skip("objective", "use --allow-objective")

    if args.skip_acquire:
        validator.skip("acquire", "--skip-acquire")
    else:
        validate_acquire(drv, validator, client, job_name)

    validator.summary()
    return validator.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
