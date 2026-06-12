"""Two-tile acquire/save smoke test against LAS X.

This is a narrow integration check for the production acquisition path:

1. Resolve the active save exporter from ``core.profiles.ACQUISITION``.
2. Let that save mode discover its own source root.
3. Acquire and save two p-indexed "tiles" into a throwaway SMART output root.
4. Switch jobs between the two acquisitions.
5. Apply one reversible setting change before tile 1, then restore it.
6. Optionally move XY before tile 1, then restore it.
7. Verify files, summary records, source references, and basic TIFF/XML shape.

The script writes only under a temp output root unless ``--output-root`` is
provided. LAS X native AutoSave / export sources are read but not deleted.

Usage:
  python tests/hardware/smoke_two_tile_save.py --yes --allow-xy
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# -- import bootstrap: driver/vendor/leica so `navigator_expert` imports.
_HERE = Path(__file__).resolve()
_LEICA = _HERE.parents[3]  # hardware -> tests -> navigator_expert -> leica
if str(_LEICA) not in sys.path:
    sys.path.insert(0, str(_LEICA))

import navigator_expert as drv  # noqa: E402
from shared.output_layout import Naming, parse_image_name, run_hash  # noqa: E402


class SmokeFailure(RuntimeError):
    """Raised when the smoke test detects a broken acquisition contract."""


@dataclass(frozen=True)
class SettingChange:
    name: str
    job: str
    original: Any
    target: Any
    restore: Callable[[], dict]


def _connect(args: argparse.Namespace):
    return drv.connect_python_client(
        client_name=args.client_name,
        api_delay_ms=args.api_delay_ms,
    )


def _confirm_live_write(args: argparse.Namespace) -> None:
    if args.yes:
        return
    actions = [
        "select jobs",
        "write and restore one job setting",
        "acquire twice",
        "save twice",
    ]
    if args.allow_xy:
        actions.append("move and restore XY")
    print("LAS X session will receive: " + ", ".join(actions) + ".")
    print("Type 'yes' to continue: ", end="", flush=True)
    if sys.stdin.readline().strip().lower() != "yes":
        raise SystemExit("aborted")


def _settings(client: Any, job: str) -> dict:
    raw = drv.get_job_settings(client, job, mode="api")
    parsed = drv.make_changeable_copy(raw)
    if not parsed:
        raise SmokeFailure(f"could not read settings for {job!r}")
    return parsed


def _active_setting(settings: dict) -> dict:
    active = settings.get("activeSettings") or []
    if not active:
        raise SmokeFailure("active setting 0 is missing")
    return active[0]


def _pick_alt(current: Any, candidates: list[Any]) -> Any | None:
    for value in candidates:
        if value != current:
            return value
    return None


def _same(actual: Any, expected: Any, tolerance: float | None = None) -> bool:
    if tolerance is None:
        return actual == expected
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def _setting_attempts(client: Any, job: str):
    return [
        {
            "name": "frame_average",
            "read": lambda: _active_setting(_settings(client, job))["frameAverage"],
            "write": lambda value: drv.set_frame_average(client, job, 0, value),
            "candidates": [1, 2, 4],
            "tolerance": None,
        },
        {
            "name": "line_average",
            "read": lambda: _active_setting(_settings(client, job))["lineAverage"],
            "write": lambda value: drv.set_line_average(client, job, 0, value),
            "candidates": [1, 2, 4],
            "tolerance": None,
        },
        {
            "name": "zoom",
            "read": lambda: _settings(client, job)["zoom"]["current"],
            "write": lambda value: drv.set_zoom(client, job, value),
            "candidates": [1.0, 2.0, 5.0, 10.0],
            "tolerance": 0.1,
        },
        {
            "name": "scan_speed",
            "read": lambda: _settings(client, job)["scanSpeed"]["value"],
            "write": lambda value: drv.set_scan_speed(client, job, value),
            "candidates": [400, 600, 800, 1000],
            "tolerance": None,
        },
    ]


def _apply_setting_change(client: Any, job: str) -> SettingChange:
    errors: list[str] = []
    for attempt in _setting_attempts(client, job):
        name = attempt["name"]
        try:
            original = attempt["read"]()
            target = _pick_alt(original, attempt["candidates"])
            if target is None:
                errors.append(f"{name}: no alternate value for {original!r}")
                continue
            result = attempt["write"](target)
            if not result or not result.get("success"):
                errors.append(f"{name}: write failed: {result}")
                continue
            actual = attempt["read"]()
            if not _same(actual, target, attempt["tolerance"]):
                try:
                    attempt["write"](original)
                finally:
                    errors.append(
                        f"{name}: readback {actual!r} != target {target!r}"
                    )
                continue

            def restore(write=attempt["write"], value=original):
                return write(value)

            return SettingChange(
                name=name,
                job=job,
                original=original,
                target=target,
                restore=restore,
            )
        except Exception as exc:  # noqa: BLE001 - live interop varies
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    raise SmokeFailure("no reversible setting change succeeded: " + "; ".join(errors))


def _jobs(client: Any, args: argparse.Namespace) -> tuple[str, str, str | None]:
    jobs = drv.get_jobs(client, mode="api") or []
    names = [j["Name"] for j in jobs if j.get("Name")]
    if len(names) < 2 and not (args.job_a and args.job_b):
        raise SmokeFailure(f"need at least two jobs for job-switch smoke, got {names}")

    selected = next((j["Name"] for j in jobs if j.get("IsSelected")), None)
    job_a = args.job_a or selected or names[0]
    job_b = args.job_b or next((name for name in names if name != job_a), None)
    if not job_b:
        raise SmokeFailure("could not resolve a second job")
    missing = [name for name in (job_a, job_b) if name not in names]
    if missing:
        raise SmokeFailure(f"requested jobs not present: {missing}; available={names}")
    return job_a, job_b, selected


def _select_job(client: Any, job: str) -> dict:
    result = drv.select_job(client, job)
    if not result or not result.get("success"):
        raise SmokeFailure(f"select_job({job!r}) failed: {result}")
    selected = drv.get_selected_job(client, mode="api") or {}
    if selected.get("Name") != job:
        raise SmokeFailure(
            f"selected-job API readback is {selected.get('Name')!r}, expected {job!r}"
        )
    return result


def _xy_target(client: Any, delta_um: float) -> tuple[dict, tuple[float, float]]:
    start = drv.get_xy(client, mode="api")
    if not start:
        raise SmokeFailure("get_xy returned no start position")
    x0, y0 = float(start["x_um"]), float(start["y_um"])
    x1, y1 = x0 + delta_um, y0 + delta_um
    limits = drv.get_stage_limits()
    x_min = _limit(limits, "x_min")
    x_max = _limit(limits, "x_max")
    y_min = _limit(limits, "y_min")
    y_max = _limit(limits, "y_max")
    if None in {x_min, x_max, y_min, y_max}:
        raise SmokeFailure(f"XY stage limits are not configured: {limits}")

    def _inside(x: float, y: float) -> bool:
        return x_min <= x <= x_max and y_min <= y <= y_max

    if not _inside(x0, y0):
        raise SmokeFailure(f"start XY outside limits: {(x0, y0)} vs {limits}")
    if not _inside(x1, y1):
        x1, y1 = x0 - delta_um, y0 - delta_um
    if not _inside(x1, y1):
        raise SmokeFailure(
            f"no safe +/-{delta_um} um XY target from {(x0, y0)} within {limits}"
        )
    return start, (x1, y1)


def _move_xy(client: Any, x_um: float, y_um: float) -> dict:
    result = drv.move_xy(client, x_um, y_um, unit="um")
    if not result or not result.get("success"):
        raise SmokeFailure(f"move_xy({x_um}, {y_um}) failed: {result}")
    return result


def _limit(limits: dict, key: str) -> float | None:
    value = limits.get(key)
    if value is None:
        value = limits.get(f"{key}_um")
    return None if value is None else float(value)


def _apply_stage_limits(args: argparse.Namespace) -> dict[str, float]:
    cfg = (
        drv.load_stage_config(limits_path=args.limits_config)
        if args.limits_config else drv.load_stage_config()
    )
    try:
        lim = cfg["stage_um"]
        limits = {
            "x_min": lim["x"][0],
            "x_max": lim["x"][1],
            "y_min": lim["y"][0],
            "y_max": lim["y"][1],
            "z_galvo_min": lim["z_galvo"][0],
            "z_galvo_max": lim["z_galvo"][1],
            "z_wide_min": lim["z_wide"][0],
            "z_wide_max": lim["z_wide"][1],
        }
    except (KeyError, TypeError, IndexError) as exc:
        raise SmokeFailure(f"invalid stage configuration: {exc}") from exc
    drv.set_stage_limits(**limits)
    return limits


def _acquire_and_save(
    client: Any,
    job: str,
    output_root: Path,
    hash6: str,
    p: int,
    exporter: str,
) -> dict:
    acquired = drv.acquire(client, job)
    saved = drv.save(
        client,
        acquired,
        output_root,
        Naming(acquisition_type="two-tile-smoke", hash6=hash6, p=p),
        exporter=exporter,
    )
    image_paths = sorted(Path(pth) for pth in saved.image_paths.values())
    xml_paths = sorted(Path(pth) for pth in saved.xml_paths.values())
    if not image_paths:
        raise SmokeFailure(f"tile p={p} produced no image paths")
    if not xml_paths:
        raise SmokeFailure(f"tile p={p} produced no XML paths")
    for path in [*image_paths, *xml_paths]:
        if not path.is_file():
            raise SmokeFailure(f"saved path missing for tile p={p}: {path}")
    for path in image_paths:
        naming = parse_image_name(path.name)
        if naming is None:
            raise SmokeFailure(f"saved image name is not canonical: {path.name}")
        if naming.p != p:
            raise SmokeFailure(f"saved image p={naming.p}, expected {p}: {path.name}")
        _assert_tiff_readable(path)
    for path in xml_paths:
        if b"<OME" not in path.read_bytes():
            raise SmokeFailure(f"saved XML does not contain OME: {path}")
    return {
        "job": job,
        "p": p,
        "acquire": {
            "started_at": acquired.started_at,
            "finished_at": acquired.finished_at,
            "command_result": acquired.command_result,
        },
        "save_exporter": exporter,
        "image_paths": [str(path) for path in image_paths],
        "xml_paths": [str(path) for path in xml_paths],
    }


def _assert_tiff_readable(path: Path) -> None:
    try:
        import tifffile
    except ImportError:
        return
    try:
        with tifffile.TiffFile(str(path)) as tif:
            if not tif.pages:
                raise SmokeFailure(f"TIFF has no pages: {path}")
            _ = tif.pages[0].shape
    except SmokeFailure:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SmokeFailure(f"cannot read TIFF {path}: {exc}") from exc


def _summary_records(output_root: Path) -> list[dict]:
    path = output_root / "summary.json"
    if not path.is_file():
        raise SmokeFailure(f"summary.json missing: {path}")
    return json.loads(path.read_text(encoding="utf-8")).get("acquisitions", [])


def _validate_summary(
    output_root: Path,
    exporter: str,
    source_root: Path,
) -> dict:
    records = _summary_records(output_root)
    if not records:
        raise SmokeFailure("summary.json contains no acquisitions")
    p_values = {int((record.get("naming") or {}).get("p", -1)) for record in records}
    if {0, 1} - p_values:
        raise SmokeFailure(f"summary missing p=0/p=1 records: p_values={p_values}")
    bad_exporters = {
        record.get("source_exporter")
        for record in records
        if record.get("source_exporter") != exporter
    }
    if bad_exporters:
        raise SmokeFailure(f"summary has unexpected source_exporter values: {bad_exporters}")

    missing_sources: list[str] = []
    for record in records:
        for rel in _record_source_refs(record):
            path = Path(rel)
            candidate = path if path.is_absolute() else source_root / rel
            if not candidate.is_file():
                missing_sources.append(rel)
    if missing_sources:
        raise SmokeFailure(f"summary source refs do not resolve: {missing_sources[:5]}")
    return {
        "records": len(records),
        "p_values": sorted(p_values),
        "source_root": str(source_root),
    }


def _record_source_refs(record: dict) -> list[str]:
    refs = []
    if record.get("source"):
        refs.append(record["source"])
    for vendor in record.get("vendor_metadata") or []:
        if vendor.get("source"):
            refs.append(vendor["source"])
    return refs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--yes", action="store_true",
                   help="skip interactive confirmation before live writes")
    p.add_argument("--allow-xy", action="store_true",
                   help="move XY by --xy-delta-um before tile 1, then restore")
    p.add_argument("--xy-delta-um", type=float, default=25.0)
    p.add_argument("--limits-config", type=Path,
                   help="optional stage limits JSON; default driver config")
    p.add_argument("--job-a", help="first job; default selected job")
    p.add_argument("--job-b", help="second job; default first alternate job")
    p.add_argument("--save-exporter",
                   help="override profile save exporter for this smoke test")
    p.add_argument("--output-root", type=Path,
                   help="SMART output root; default is a temp directory")
    p.add_argument("--report", type=Path,
                   help="optional JSON report path")
    p.add_argument("--client-name", default="PythonClient")
    p.add_argument("--api-delay-ms", type=int, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _confirm_live_write(args)

    output_root = (
        args.output_root
        if args.output_root is not None
        else Path(tempfile.mkdtemp(prefix="smart_two_tile_smoke_"))
    )
    output_root.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "status": "FAIL",
        "output_root": str(output_root),
        "tiles": [],
        "restores": {},
    }
    client = _connect(args)
    exporter = drv.active_save_exporter(args.save_exporter)
    source_root = drv.save_source_root(exporter)
    report.update({
        "save_exporter": exporter,
        "source_root": str(source_root),
    })
    if args.allow_xy:
        report["stage_limits"] = _apply_stage_limits(args)

    job_a, job_b, original_job = _jobs(client, args)
    report.update({
        "jobs": {"tile0": job_a, "tile1": job_b, "original": original_job},
    })

    xy_start: dict | None = None
    setting_change: SettingChange | None = None
    try:
        hash6 = run_hash()

        _select_job(client, job_a)
        report["tiles"].append(
            _acquire_and_save(client, job_a, output_root, hash6, 0, exporter)
        )

        _select_job(client, job_b)
        if args.allow_xy:
            xy_start, (x1, y1) = _xy_target(client, args.xy_delta_um)
            _move_xy(client, x1, y1)
            report["xy_move"] = {
                "from": [xy_start["x_um"], xy_start["y_um"]],
                "to": [x1, y1],
            }

        setting_change = _apply_setting_change(client, job_b)
        report["setting_change"] = {
            "name": setting_change.name,
            "job": setting_change.job,
            "from": setting_change.original,
            "to": setting_change.target,
        }
        report["tiles"].append(
            _acquire_and_save(client, job_b, output_root, hash6, 1, exporter)
        )

        report["summary"] = _validate_summary(output_root, exporter, source_root)
        report["status"] = "PASS"
        return_code = 0
    except Exception as exc:  # noqa: BLE001 - this is a CLI smoke report
        report["error"] = f"{type(exc).__name__}: {exc}"
        return_code = 1
    finally:
        if setting_change is not None:
            try:
                restore_result = setting_change.restore()
                report["restores"]["setting"] = restore_result
            except Exception as exc:  # noqa: BLE001
                report["restores"]["setting_error"] = f"{type(exc).__name__}: {exc}"
                return_code = 1
        if xy_start is not None:
            try:
                restore_xy = _move_xy(
                    client,
                    float(xy_start["x_um"]),
                    float(xy_start["y_um"]),
                )
                report["restores"]["xy"] = restore_xy
            except Exception as exc:  # noqa: BLE001
                report["restores"]["xy_error"] = f"{type(exc).__name__}: {exc}"
                return_code = 1
        if original_job:
            try:
                report["restores"]["job"] = _select_job(client, original_job)
            except Exception as exc:  # noqa: BLE001
                report["restores"]["job_error"] = f"{type(exc).__name__}: {exc}"
                return_code = 1

    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
