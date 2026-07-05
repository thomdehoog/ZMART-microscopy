#!/usr/bin/env python3
"""Navigator Expert driver CI -- the single, self-contained test entry point.

One command runs the driver's full offline quality gate anywhere Python and the
driver import work (a developer laptop, a GitHub runner, the new institute's
microscope PC)::

    python run_ci.py             # OFFLINE (default): env header + lint + offline tests + coverage
    python run_ci.py online      # ONLINE: just the live LAS X validators (needs live LAS X)
    python run_ci.py online --live-writes  # ONLINE + reversible write phases (the bench run);
                                 #   writes Markdown run reports to tests/_report/
    python run_ci.py both        # BOTH:   offline suite + the live LAS X validators
    python run_ci.py --no-lint   # skip ruff (add to any mode)
    python run_ci.py --no-cov    # skip coverage (faster; no pytest-cov needed)

Design goals (matching the suite's standard):

  * Explicit per step -- every step prints its command, its result, and its
    wall-clock time. Nothing runs silently.
  * Diagnosable across systems -- the run opens with a full environment header
    (see tests/_diagnostics) and writes machine-readable reports to
    tests/_report/ (env.json, junit.xml, coverage.xml, htmlcov/, ci_summary.json)
    so a failure carries its own context off-machine.
  * Honest exit code -- lint is reported but non-fatal (pre-existing style debt
    must not mask test results); a test failure fails the run. CI can flip lint
    to fatal once it is clean.

This file is the CI *definition*; the repo-root GitHub workflow is only a thin
trigger that calls it. Run it from anywhere -- paths are resolved from this
file's location, not the working directory.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DRIVER_ROOT = Path(__file__).resolve().parent  # .../navigator_expert
MACHINE_ROOT = DRIVER_ROOT.parent  # .../<machine> (import root)
REPORT_DIR = DRIVER_ROOT / "tests" / "_report"
TEST_PATHS = [DRIVER_ROOT / "tests", DRIVER_ROOT / "calibration" / "tests"]


def repo_root() -> Path:
    """Locate the repo root robustly (no fragile parents[N] depth counting).

    Prefer git; otherwise walk up until we find the directory that holds the
    shared/ package. Falls back to the machine dir's parent.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(DRIVER_ROOT),
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception:
        pass
    candidate = DRIVER_ROOT
    for _ in range(8):
        if (candidate / "shared").is_dir():
            return candidate
        candidate = candidate.parent
    return MACHINE_ROOT.parent


def build_env() -> dict:
    """Child-process environment with the import roots on PYTHONPATH up front.

    Setting these here (rather than relying only on conftest) means coverage,
    which starts before collection, can already import navigator_expert.
    """
    env = dict(os.environ)
    roots = [str(MACHINE_ROOT), str(repo_root())]
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([*roots, existing]) if existing else os.pathsep.join(roots)
    # Force-colour off in subprocesses we capture nothing from; pytest handles
    # its own colour based on tty. Nothing to set here -- documented intent only.
    return env


def _rule(char: str = "=") -> str:
    return char * 72


def run_step(name: str, cmd: list[str], env: dict, *, fatal: bool) -> dict:
    """Run one CI step, streaming its output, and return a structured record."""
    print(f"\n{_rule('-')}")
    print(f"STEP: {name}{'' if fatal else '   (non-fatal)'}")
    print(f"  $ {' '.join(cmd)}")
    print(f"{_rule('-')}", flush=True)
    start = time.perf_counter()
    try:
        completed = subprocess.run(cmd, env=env)
        returncode = completed.returncode
        error = None
    except FileNotFoundError as exc:
        returncode = 127
        error = f"command not found: {exc}"
        print(f"  ! {error}")
    except OSError as exc:
        # Any other launch failure must still yield a step result — the CI
        # summary and ci_summary.json are the off-machine triage context.
        returncode = 126
        error = f"command failed to launch: {exc}"
        print(f"  ! {error}")
    elapsed = time.perf_counter() - start
    ok = returncode == 0
    status = "OK" if ok else "FAIL"
    print(f"\n  -> {status}  (exit {returncode})  in {elapsed:.1f}s", flush=True)
    return {
        "name": name,
        "ok": ok,
        "fatal": fatal,
        "returncode": returncode,
        "seconds": round(elapsed, 2),
        "error": error,
        "command": cmd,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Navigator Expert driver CI (offline suite + coverage + reports)."
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["offline", "online", "both"],
        default="offline",
        help=(
            "which suite to run (default: offline). 'offline' -- no microscope, "
            "no LAS X (the portable gate); 'online' -- the live LAS X validators "
            "only (api/log/hybrid passive readers, api-vs-log parity, and the "
            "read-only end-to-end validator per reader route; needs live LAS X); "
            "'both' -- the offline suite followed by the live validators"
        ),
    )
    parser.add_argument("--no-lint", action="store_true", help="skip ruff lint/format checks")
    parser.add_argument(
        "--no-cov", action="store_true", help="skip coverage (no pytest-cov required)"
    )
    parser.add_argument(
        "--live-writes",
        action="store_true",
        help=(
            "online/both only: run the validators' reversible write phases "
            "(settings + job-selection round-trips per reader route, the XY "
            "pattern + Z round-trip, and the adapter move/state round-trips) "
            "instead of read-only. Everything is restored in finally blocks; "
            "objective switches and acquisitions stay opt-in via the scripts' "
            "own --allow-* flags. This is the canonical bench validation."
        ),
    )
    args = parser.parse_args()

    if args.live_writes and args.mode == "offline":
        parser.error("--live-writes needs mode 'online' or 'both' (it drives live LAS X)")

    run_offline = args.mode in ("offline", "both")
    run_hardware = args.mode in ("online", "both")

    overall_start = time.perf_counter()
    run_reports_since = time.time()  # wall-clock mark for this run's markdown reports
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    env = build_env()

    # --- environment header (printed + persisted to env.json) ----------------
    print(_rule())
    print("NAVIGATOR EXPERT DRIVER CI")
    print(_rule())
    subprocess.run([sys.executable, str(DRIVER_ROOT / "tests" / "_diagnostics.py")], env=env)

    steps: list[dict] = []

    # --- lint (non-fatal: report style debt without masking test results;
    # online mode is 'just the live validators', so lint runs only when the
    # offline suite does) ----
    if not args.no_lint and run_offline:
        ruff_available = importlib.util.find_spec("ruff") is not None
        if ruff_available:
            steps.append(
                run_step(
                    "lint: ruff check",
                    [sys.executable, "-m", "ruff", "check", str(DRIVER_ROOT)],
                    env,
                    fatal=False,
                )
            )
            steps.append(
                run_step(
                    "lint: ruff format --check",
                    [sys.executable, "-m", "ruff", "format", "--check", str(DRIVER_ROOT)],
                    env,
                    fatal=False,
                )
            )
        else:
            print("\n  (ruff not installed -- skipping lint; `pip install ruff` to enable)")

    cov_requested = not args.no_cov
    cov_available = importlib.util.find_spec("pytest_cov") is not None

    # --- offline suite + coverage (fatal) -- runs for mode 'offline' | 'both' -
    # The portable gate: no microscope, no LAS X, so it runs everywhere.
    # Excludes @pytest.mark.hardware; the mock-backed validator/stress tests run
    # here (they are not marked hardware).
    if run_offline:
        pytest_cmd = [
            sys.executable,
            "-m",
            "pytest",
            *[str(p) for p in TEST_PATHS],
            "-m",
            "not hardware",
            # Absolute path: pytest resolves a relative --junit-xml against the
            # cwd, so pin it to the report dir regardless of launch dir.
            f"--junit-xml={REPORT_DIR / 'junit.xml'}",
        ]
        if cov_requested and cov_available:
            pytest_cmd += [
                "--cov=navigator_expert",
                f"--cov-config={DRIVER_ROOT / '.coveragerc'}",
                "--cov-report=term-missing:skip-covered",
                f"--cov-report=xml:{REPORT_DIR / 'coverage.xml'}",
                f"--cov-report=html:{REPORT_DIR / 'htmlcov'}",
            ]
        elif cov_requested and not cov_available:
            print(
                "\n  (pytest-cov not installed -- running without coverage; `pip install pytest-cov` to enable)"
            )

        label = "tests: offline suite"
        if cov_requested and cov_available:
            label += " + coverage"
        steps.append(run_step(label, pytest_cmd, env, fatal=True))

    # --- live LAS X validators (fatal) -- runs for mode 'online' | 'both' -----
    # Live validators, through this same step framework: streamed output,
    # per-step timing, CI SUMMARY. Read-only and non-interactive by default --
    # no moves, writes, acquisitions, or prompts. --live-writes switches the
    # validators to their reversible write phases (the canonical bench run);
    # objective switches / acquisitions still need the scripts' own --allow-*
    # flags in a manual run. Every validator writes a Markdown run report of
    # every attempted instrument change into tests/_report/ (paths printed in
    # the summary below).
    if run_hardware:
        hw = DRIVER_ROOT / "tests" / "hardware"
        write_mode = "writes" if args.live_writes else "read-only"
        sxs_gate = ["--yes"] if args.live_writes else ["--read-only"]
        vh_gate = ["--yes", "--allow-xy", "--allow-z"] if args.live_writes else ["--read-only"]
        adapter_gate = (
            ["--yes", "--allow-move", "--allow-state"] if args.live_writes else ["--read-only"]
        )
        hardware_steps = [
            (
                "hardware: passive readers (api / log / hybrid)",
                [sys.executable, str(hw / "probe_four_readers.py"), "--read-only"],
            ),
            (
                f"hardware: reader parity + routed modes ({write_mode})",
                [
                    sys.executable,
                    str(hw / "validate_readers_side_by_side.py"),
                    *sxs_gate,
                    f"--report-dir={REPORT_DIR}",
                ],
            ),
            (
                f"hardware: zmart adapter (controller round-trip, {write_mode})",
                [
                    sys.executable,
                    str(hw / "validate_zmart_adapter.py"),
                    *adapter_gate,
                    "--allow-missing-lasx",  # SKIP (not FAIL) if no live LAS X
                    f"--output={REPORT_DIR / 'zmart_adapter_validate.jsonl'}",
                    f"--report-dir={REPORT_DIR}",
                ],
            ),
        ]
        # End-to-end driver validation once PER reader route, so the driver's own
        # read/gating behaviour is exercised under api, log, AND hybrid -- not
        # just the passive reader comparison above. With --live-writes each route
        # also runs the reversible settings + job-selection round-trips (and the
        # XY/Z movement phases), so command confirmations are exercised per mode.
        for mode in ("api", "log", "hybrid"):
            hardware_steps.append(
                (
                    f"hardware: end-to-end validator [{mode} reader] ({write_mode})",
                    [
                        sys.executable,
                        str(hw / "validate_hardware.py"),
                        *vh_gate,
                        "--allow-missing-lasx",  # SKIP (not FAIL) if no live LAS X
                        "--state-reader-mode",
                        mode,
                        f"--output={REPORT_DIR / f'hardware_validate_{mode}.jsonl'}",
                        f"--report-dir={REPORT_DIR}",
                    ],
                )
            )
        for name, cmd in hardware_steps:
            steps.append(run_step(name, cmd, env, fatal=True))

    # --- summary -------------------------------------------------------------
    total_elapsed = time.perf_counter() - overall_start
    fatal_failures = [s for s in steps if not s["ok"] and s["fatal"]]
    warn_failures = [s for s in steps if not s["ok"] and not s["fatal"]]

    print(f"\n{_rule()}")
    print("CI SUMMARY")
    print(_rule())
    for step in steps:
        flag = "OK  " if step["ok"] else ("FAIL" if step["fatal"] else "WARN")
        print(f"  [{flag}]  {step['name']:<34}  {step['seconds']:>6.1f}s")
    print(f"\n  total: {total_elapsed:.1f}s")
    print(f"  reports written to: {REPORT_DIR}")
    print(
        "    env.json          environment context for this run (read this first on a remote failure)"
    )
    if run_offline:
        print("    junit.xml         machine-readable offline test results")
        if cov_requested and cov_available:
            print("    coverage.xml      coverage for CI tooling")
            print("    htmlcov/index.html  browsable coverage report")
    if run_hardware:
        print(
            "    hardware_validate_{api,log,hybrid}.jsonl  end-to-end validator checks per reader route"
        )
    print("    ci_summary.json   this step summary")

    if run_hardware:
        # Markdown run reports: one per validator run, every attempted
        # instrument change (incl. restores) with confirmation + timing.
        run_reports = sorted(
            p
            for p in REPORT_DIR.glob("hardware_run_report_*.md")
            if p.stat().st_mtime >= run_reports_since
        )
        print("\n  markdown run reports (every attempted instrument change):")
        if run_reports:
            for p in run_reports:
                print(f"    {p}")
        else:
            print("    (none produced -- validators did not reach their report step)")

    summary = {
        "total_seconds": round(total_elapsed, 2),
        "passed": not fatal_failures,
        "fatal_failures": [s["name"] for s in fatal_failures],
        "warnings": [s["name"] for s in warn_failures],
        "steps": steps,
    }
    (REPORT_DIR / "ci_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if warn_failures:
        print(
            f"\n  WARN: {len(warn_failures)} non-fatal step(s) reported issues (lint) -- see above."
        )
    if fatal_failures:
        print(
            f"\n  RESULT: FAILED -- {len(fatal_failures)} fatal step(s): "
            f"{', '.join(s['name'] for s in fatal_failures)}."
        )
        print(
            f"  To triage on another system: read the environment header above "
            f"(also in {REPORT_DIR / 'env.json'}) next to the failing tests in "
            f"{REPORT_DIR / 'junit.xml'}."
        )
        return 1

    print("\n  RESULT: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
