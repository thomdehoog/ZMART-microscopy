#!/usr/bin/env python3
"""mesoSPIM driver CI -- the single, self-contained test entry point.

One command runs the driver's quality gate anywhere Python and the driver import
work (a laptop, a CI runner, the mesoSPIM PC)::

    python run_ci.py             # OFFLINE (default): env header + lint + offline suite + coverage
    python run_ci.py online      # ONLINE:  the live round-trip vs a running mesoSPIM -D demo (needs the
                                 #   Remote Scripting server on MESOSPIM_HOST/PORT; set MESOSPIM_ALLOW_ACQUIRE=1
                                 #   to also exercise the capture path)
    python run_ci.py both        # BOTH:    the offline gate followed by the live round-trip
    python run_ci.py --no-lint   # skip ruff (add to any mode)
    python run_ci.py --no-cov    # skip coverage (faster; no pytest-cov needed)

Design (matching the sibling drivers' run_ci.py):

  * Explicit per step -- every step prints its command, result, and wall-clock time.
  * Diagnosable across systems -- an environment header opens the run and
    machine-readable reports land in tests/_report/ (env.json, junit.xml,
    coverage.xml, htmlcov/, ci_summary.json).
  * Honest exit code -- lint is reported but the exit code is driven by the test
    suites; a fatal step failing fails the run.

Paths resolve from this file, not the working directory -- run it from anywhere.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

DRIVER_ROOT = Path(__file__).resolve().parent          # .../mesospim
DRIVERS_DIR = DRIVER_ROOT.parent                       # .../zmart_drivers (import root for `import mesospim`)
REPORT_DIR = DRIVER_ROOT / "tests" / "_report"


def repo_root() -> Path:
    """Locate the repo root (git first, else walk up to the dir holding shared/)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=str(DRIVER_ROOT), timeout=10,
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
    return DRIVERS_DIR.parent


def build_env() -> dict:
    """Child-process env with the import roots on PYTHONPATH (so coverage, which
    starts before collection, can already import `mesospim`)."""
    env = dict(os.environ)
    roots = [str(DRIVERS_DIR), str(repo_root())]
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([*roots, existing]) if existing else os.pathsep.join(roots)
    # mesoSPIM PCs default to a cp1252 console; keep child stdout UTF-8 so a
    # step's PASS/FAIL glyph can't crash on encoding.
    env.setdefault("PYTHONUTF8", "1")
    return env


def _rule(char: str = "=") -> str:
    return char * 72


def env_header(env: dict) -> dict:
    """Print and return a compact environment header (persisted to env.json)."""
    info = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "cwd": str(DRIVER_ROOT),
        "packages": {},
    }
    # Import the driver + note the optional test deps.
    probe = (
        "import json,sys;"
        "d={};"
        "\nfor m in ('mesospim','pytest','numpy','tifffile','PyQt5','ruff','pytest_cov'):"
        "\n try:\n  mod=__import__(m);d[m]=getattr(mod,'__version__','present')"
        "\n except Exception as e:\n  d[m]=f'MISSING ({type(e).__name__})'"
        "\nprint(json.dumps(d))"
    )
    try:
        out = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=60)
        info["packages"] = json.loads(out.stdout.strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        info["packages"] = {"_error": str(exc)}
    print(_rule())
    print("mesoSPIM DRIVER CI")
    print(_rule())
    print(f"  platform : {info['platform']}")
    print(f"  python   : {info['python']}  ({info['executable']})")
    print("  packages : " + ", ".join(f"{k}={v}" for k, v in info["packages"].items()))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "env.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def run_step(name: str, cmd: list[str], env: dict, *, fatal: bool) -> dict:
    """Run one CI step, streaming its output, and return a structured record."""
    print(f"\n{_rule('-')}")
    print(f"STEP: {name}{'' if fatal else '   (non-fatal)'}")
    print(f"  $ {' '.join(cmd)}")
    print(_rule("-"), flush=True)
    start = time.perf_counter()
    error = None
    try:
        returncode = subprocess.run(cmd, env=env, cwd=str(DRIVER_ROOT)).returncode
    except FileNotFoundError as exc:
        returncode, error = 127, f"command not found: {exc}"
        print(f"  ! {error}")
    elapsed = time.perf_counter() - start
    ok = returncode == 0
    print(f"\n  -> {'OK' if ok else 'FAIL'}  (exit {returncode})  in {elapsed:.1f}s", flush=True)
    return {"name": name, "ok": ok, "fatal": fatal, "returncode": returncode,
            "seconds": round(elapsed, 2), "error": error, "command": cmd}


def main() -> int:
    parser = argparse.ArgumentParser(description="mesoSPIM driver CI (offline suite + live -D demo round-trip).")
    parser.add_argument(
        "mode", nargs="?", choices=["offline", "online", "both"], default="offline",
        help=("which suite to run (default: offline). 'offline' -- no mesoSPIM, no hardware "
              "(mock server); 'online' -- the live round-trip vs a running mesoSPIM -D demo "
              "(needs the Remote Scripting server on MESOSPIM_HOST/PORT); 'both' -- offline then online."),
    )
    parser.add_argument("--no-lint", action="store_true", help="skip ruff")
    parser.add_argument("--no-cov", action="store_true", help="skip coverage (no pytest-cov required)")
    args = parser.parse_args()

    run_offline = args.mode in ("offline", "both")
    run_online = args.mode in ("online", "both")

    overall_start = time.perf_counter()
    env = build_env()
    env_header(env)
    steps: list[dict] = []

    has = lambda m: importlib.util.find_spec(m) is not None  # noqa: E731

    # --- lint (non-fatal: report style debt without masking test results) ----
    if not args.no_lint:
        if has("ruff"):
            steps.append(run_step("lint: ruff check", [sys.executable, "-m", "ruff", "check", "."], env, fatal=False))
        else:
            print("\n  (ruff not installed -- skipping lint; `pip install ruff` to enable)")

    # --- OFFLINE: mock-server suite (+coverage) and the headless Qt validator -
    if run_offline:
        pytest_cmd = [sys.executable, "-m", "pytest", "tests", "-m", "not integration",
                      f"--junit-xml={REPORT_DIR / 'junit.xml'}"]
        if not args.no_cov and has("pytest_cov"):
            pytest_cmd += ["--cov=mesospim", "--cov-branch", "--cov-report=term-missing:skip-covered",
                           f"--cov-report=xml:{REPORT_DIR / 'coverage.xml'}",
                           f"--cov-report=html:{REPORT_DIR / 'htmlcov'}"]
        elif not args.no_cov:
            print("\n  (pytest-cov not installed -- running without coverage; `pip install pytest-cov` to enable)")
        label = "tests: offline suite" + (" + coverage" if (not args.no_cov and has("pytest_cov")) else "")
        steps.append(run_step(label, pytest_cmd, env, fatal=True))

    # --- ONLINE: live round-trip vs a running mesoSPIM -D demo ----------------
    # The integration suite connects to MESOSPIM_HOST/PORT (default 127.0.0.1:42000)
    # and SKIPS cleanly if nothing is listening, so this is safe to run anywhere;
    # a real check needs the -D demo + Remote Scripting server up. Capture is
    # opt-in via MESOSPIM_ALLOW_ACQUIRE=1.
    if run_online:
        host = env.get("MESOSPIM_HOST", "127.0.0.1")
        port = env.get("MESOSPIM_PORT", "42000")
        print(f"\n  online target: {host}:{port}  "
              f"(acquire {'ENABLED' if env.get('MESOSPIM_ALLOW_ACQUIRE') == '1' else 'disabled'} "
              f"-- set MESOSPIM_ALLOW_ACQUIRE=1 to include the capture)")
        steps.append(run_step("tests: live round-trip (-m integration)",
                              [sys.executable, "-m", "pytest", "tests", "-m", "integration", "-v",
                               f"--junit-xml={REPORT_DIR / 'junit-integration.xml'}"],
                              env, fatal=True))

    # --- summary --------------------------------------------------------------
    total = round(time.perf_counter() - overall_start, 2)
    fatal_failed = [s for s in steps if s["fatal"] and not s["ok"]]
    summary = {"mode": args.mode, "seconds": total, "ok": not fatal_failed, "steps": steps}
    (REPORT_DIR / "ci_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"\n{_rule()}")
    print(f"CI SUMMARY  (mode={args.mode}, {total:.1f}s)")
    print(_rule())
    for s in steps:
        tag = "OK  " if s["ok"] else ("FAIL" if s["fatal"] else "warn")
        print(f"  [{tag}] {s['name']}  ({s['seconds']}s)")
    print(_rule())
    if fatal_failed:
        print(f"RESULT: FAIL -- {len(fatal_failed)} fatal step(s) failed.")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
