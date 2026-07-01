"""
Self-contained offline CI gate for the zenapi driver.
=====================================================
    python run_ci.py                # ruff (if present) + offline pytest + coverage (if present)
    python run_ci.py --hardware     # run ONLY the @pytest.mark.hardware suite
    python run_ci.py --no-lint      # skip ruff
    python run_ci.py --no-cov       # skip coverage

Reports land in tests/_report/. Lint and coverage are optional: if ruff /
pytest-cov are not installed, those steps are skipped with a note rather than
failing the run.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT_DIR = HERE / "tests" / "_report"


def _run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=str(HERE)).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="zenapi offline CI gate")
    ap.add_argument("--hardware", action="store_true", help="run only hardware-marked tests")
    ap.add_argument("--no-lint", action="store_true", help="skip ruff")
    ap.add_argument("--no-cov", action="store_true", help="skip coverage")
    args = ap.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # --- lint (optional) ---
    if not args.no_lint:
        if find_spec("ruff") is not None:
            if _run([sys.executable, "-m", "ruff", "check", "."]) != 0:
                print("ruff reported issues.")
                return 1
        else:
            print("ruff not installed; skipping lint.")

    # --- tests ---
    cmd = [sys.executable, "-m", "pytest", "tests",
           "--junit-xml", str(REPORT_DIR / "junit.xml")]
    cmd += ["-m", "hardware"] if args.hardware else ["-m", "not hardware"]

    if not args.no_cov and find_spec("pytest_cov") is not None:
        cmd += ["--cov=zenapi", "--cov-branch",
                "--cov-report", f"xml:{REPORT_DIR / 'coverage.xml'}",
                "--cov-report", f"html:{REPORT_DIR / 'htmlcov'}",
                "--cov-report", "term-missing"]
    elif not args.no_cov:
        print("pytest-cov not installed; running without coverage.")

    return _run(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
