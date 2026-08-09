"""Shared, deliberately strict support for the fault-injection checks.

The checks edit source and expect tests to fail. That expectation makes them
unusually easy to fool: a missing pytest installation, a syntax error, or an
already-red baseline all produce a non-zero process too. This helper makes the
unmodified suite prove it is green before any fault is introduced, then accepts
only pytest's ordinary "tests failed" exit status for a mutation.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PytestRun:
    """What one isolated pytest process reported."""

    returncode: int
    output: str
    failures: int
    first_failure: str

    @property
    def green(self) -> bool:
        """True only when pytest completed and every selected test passed."""
        return self.returncode == 0

    @property
    def caught_the_fault(self) -> bool:
        """True only for pytest's documented "one or more tests failed" status."""
        return self.returncode == 1

    @property
    def could_not_run_tests(self) -> bool:
        """Collection, usage, interruption and internal errors are not catches."""
        return self.returncode not in (0, 1)


def run_pytest(repository: Path, tests: Path) -> PytestRun:
    """Run one test file in a fresh interpreter and retain all diagnostics."""
    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(tests),
            "-q",
            "--no-header",
            "-x",
            "--tb=no",
        ],
        capture_output=True,
        text=True,
        cwd=repository,
    )
    output = "\n".join(part for part in (finished.stdout, finished.stderr) if part)
    failures = re.search(r"(\d+) (?:failed|error)", output)
    named = re.search(r"(?:FAILED|ERROR) \S+::(\S+)", output)
    return PytestRun(
        returncode=finished.returncode,
        output=output,
        failures=int(failures.group(1)) if failures else 0,
        first_failure=named.group(1) if named else "",
    )


def require_green_baseline(repository: Path, tests: Path) -> bool:
    """Refuse to call any later red process evidence when the baseline is red."""
    baseline = run_pytest(repository, tests)
    if baseline.green:
        return True
    print(
        "The unmodified tests are not green, so a failing mutation would prove "
        "nothing. Fix the baseline or its environment before trusting this check."
    )
    print(baseline.output)
    return False


def replace_source(path: Path, text: str) -> None:
    """Replace a mutation subject and prove the bytes match the request.

    Fault checks deliberately edit real source files. A checker that reports
    success but leaves its subject truncated is worse than no checker, so every
    mutation and every restoration is read back immediately.
    """
    if not text.strip():
        raise RuntimeError(f"Refusing to replace mutation subject {path} with an empty file.")
    path.write_text(text, encoding="utf-8")
    if path.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"Mutation subject {path} did not read back exactly after replacement.")
