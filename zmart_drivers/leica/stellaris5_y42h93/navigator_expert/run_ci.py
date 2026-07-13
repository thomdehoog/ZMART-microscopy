#!/usr/bin/env python3
"""Navigator Expert driver CI -- the single, self-contained test entry point.

One command runs the driver's full offline quality gate anywhere Python and the
driver import work (a developer laptop, a GitHub runner, the new institute's
microscope PC)::

    python run_ci.py             # MOCK/OFFLINE (default): lint + offline tests + coverage
    python run_ci.py --mock      # explicit spelling of the default
    python run_ci.py --hardware  # LIVE: LAS X validators + acquire smoke

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
    zmart_controller package. Falls back to the machine dir's parent.
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
        if (candidate / "zmart_controller").is_dir():
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Navigator Expert driver CI (offline suite + coverage + reports)."
    )
    parser.add_argument("--mock", action="store_true", help="run the mock/offline suite (default)")
    parser.add_argument("--hardware", action="store_true", help="run the live LAS X hardware suite")
    args = parser.parse_args(argv)
    if args.mock and args.hardware:
        parser.error("--mock and --hardware are mutually exclusive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_mock = not args.hardware
    run_hardware = bool(args.hardware)
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

    # --- lint (non-fatal: report style debt without masking test results) ----
    if run_mock:
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

    cov_available = importlib.util.find_spec("pytest_cov") is not None

    # --- mock/offline suite + coverage (fatal) -------------------------------
    # The portable gate: no microscope, no LAS X, so it runs everywhere.
    # Excludes @pytest.mark.hardware; the mock-backed validator/stress tests run
    # here (they are not marked hardware).
    if run_mock:
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
        if cov_available:
            pytest_cmd += [
                "--cov=navigator_expert",
                f"--cov-config={DRIVER_ROOT / '.coveragerc'}",
                "--cov-report=term-missing:skip-covered",
                f"--cov-report=xml:{REPORT_DIR / 'coverage.xml'}",
                f"--cov-report=html:{REPORT_DIR / 'htmlcov'}",
            ]
        else:
            print(
                "\n  (pytest-cov not installed -- running without coverage; `pip install pytest-cov` to enable)"
            )

        label = "tests: offline suite"
        if cov_available:
            label += " + coverage"
        steps.append(run_step(label, pytest_cmd, env, fatal=True))

    # --- live LAS X validators (fatal) ---------------------------------------
    # --hardware is the canonical bench run: it connects to live LAS X, proves
    # the fail-closed limits gate with a mock first, then runs reader parity,
    # reversible move/state checks, and a real acquire+save smoke. The lower-level
    # validator scripts keep their granular --allow-* flags for manual debugging;
    # run_ci exposes only the two operational modes: mock or hardware.
    if run_hardware:
        hw = DRIVER_ROOT / "tests" / "hardware"
        # SAFETY GATE (hard abort): prove the fail-closed limits machinery works
        # in THIS install against the in-process mock BEFORE connecting to real
        # LAS X or moving the stage. If it fails (bad env, regressed code,
        # missing/invalid limits files), we DO NOT run any hardware validator —
        # the run aborts here, before a single hardware command. In pure
        # hardware mode skips the offline suite, so this is the only place
        # the gate is proven ahead of hardware. Unlike the other fatal steps
        # (which record failure but still run), this one short-circuits: a
        # broken limits gate must never reach the physical stage.
        limits_selftest = run_step(
            "limits: mock self-check (fail-closed gate proven before any hardware)",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                str(DRIVER_ROOT / "tests" / "unit" / "test_limits_adversarial.py"),
            ],
            env,
            fatal=True,
        )
        steps.append(limits_selftest)
        if limits_selftest["returncode"] != 0:
            print(
                "\n  ABORT: the limits mock self-check FAILED. Refusing to run any "
                "hardware validator — the stage is not touched. Fix the limits "
                "gate (see the pytest output above) and re-run.",
                flush=True,
            )
            run_hardware = False  # skip the whole hardware block below

    if run_hardware:
        hardware_steps = [
            (
                "hardware: passive readers (api / log / hybrid)",
                [sys.executable, str(hw / "probe_four_readers.py"), "--read-only"],
                True,
            ),
            (
                "hardware: reader parity + routed modes",
                [
                    sys.executable,
                    str(hw / "validate_readers_side_by_side.py"),
                    "--yes",
                    f"--report-dir={REPORT_DIR}",
                ],
                False,
            ),
            (
                "hardware: zmart adapter (move/state/acquire)",
                [
                    sys.executable,
                    str(hw / "validate_zmart_adapter.py"),
                    "--yes",
                    "--allow-move",
                    "--allow-state",
                    "--allow-acquire",
                    f"--output={REPORT_DIR / 'zmart_adapter_validate.jsonl'}",
                    f"--report-dir={REPORT_DIR}",
                ],
                True,
            ),
        ]
        # End-to-end driver validation once per reader route. The production
        # surface is hybrid, so only hybrid is fatal; api/log runs stay
        # diagnostic and document bench-specific reader disagreements.
        for mode in ("api", "log", "hybrid"):
            hardware_steps.append(
                (
                    f"hardware: end-to-end validator [{mode} reader]",
                    [
                        sys.executable,
                        str(hw / "validate_hardware.py"),
                        "--yes",
                        "--allow-xy",
                        "--allow-z",
                        "--allow-acquire",
                        "--state-reader-mode",
                        mode,
                        f"--output={REPORT_DIR / f'hardware_validate_{mode}.jsonl'}",
                        f"--report-dir={REPORT_DIR}",
                    ],
                    mode == "hybrid",
                )
            )
        for name, cmd, fatal in hardware_steps:
            steps.append(run_step(name, cmd, env, fatal=fatal))

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
    if run_mock:
        print("    junit.xml         machine-readable offline test results")
        if cov_available:
            print("    coverage.xml      coverage for CI tooling")
            print("    htmlcov/index.html  browsable coverage report")
    if run_hardware:
        print(
            "    hardware_validate_{api,log,hybrid}.jsonl  end-to-end checks; hybrid is the fatal production route"
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
            f"\n  WARN: {len(warn_failures)} non-fatal diagnostic step(s) reported issues -- see above."
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
