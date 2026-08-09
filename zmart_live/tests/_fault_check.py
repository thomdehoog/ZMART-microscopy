"""Shared, deliberately strict support for the fault-injection checks.

The checks edit source and expect tests to fail. That expectation makes them
unusually easy to fool: a missing pytest installation, a syntax error, or an
already-red baseline all produce a non-zero process too. This helper makes the
unmodified suite prove it is green before any fault is introduced, then accepts
only pytest's ordinary "tests failed" exit status for a mutation.
"""

from __future__ import annotations

import importlib
import re
import signal
import subprocess
import sys
from contextlib import contextmanager
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


@contextmanager
def make_interruptions_reach_finally():
    """Turn Ctrl-C and termination into exceptions while a campaign mutates code.

    Python normally turns Ctrl-C into :class:`KeyboardInterrupt`, but SIGTERM
    ends the process immediately and skips every ``finally`` block. That was
    observed to leave a deliberately faulty coordinator in the working tree.
    During a mutation campaign both ordinary stop signals therefore raise the
    same exception. The handler ignores a second stop while the stack unwinds,
    so restoration itself cannot be interrupted, then reinstates the process's
    previous handlers.

    SIGKILL and loss of power cannot be caught by any process. A campaign stopped
    that way still requires restoring the subject from version control before
    another test run.
    """
    watched = (signal.SIGINT, signal.SIGTERM)
    previous = {which: signal.getsignal(which) for which in watched}

    def stop_after_restoring(_signal_number, _frame):
        for which in watched:
            signal.signal(which, signal.SIG_IGN)
        raise KeyboardInterrupt("mutation campaign interrupted")

    for which in watched:
        signal.signal(which, stop_after_restoring)
    try:
        yield
    finally:
        for which, handler in previous.items():
            signal.signal(which, handler)


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


def require_green_subject(repository: Path, tests: Path, source: Path) -> bool:
    """Run the baseline from source, never from a stale compiled mutation."""
    _forget_the_compiled_copy(source)
    return require_green_baseline(repository, tests)


def require_restored_subject(
    repository: Path, tests: Path, source: Path, original: str
) -> bool:
    """Prove both the source bytes and its tests are sound after mutations."""
    if source.read_text(encoding="utf-8") != original:
        print(
            f"Mutation subject {source} was not restored byte-for-byte. Stop here "
            "and restore it before running any other tests."
        )
        return False
    if require_green_subject(repository, tests, source):
        return True
    print(
        f"Mutation subject {source} has its original bytes back, but its clean "
        "tests are red. A stale compiled mutation or another damaged dependency "
        "may remain, so the campaign cannot claim successful restoration."
    )
    return False


def _forget_the_compiled_copy(path: Path) -> None:
    """Throw away Python's compiled copy of a file we have just rewritten.

    This exists because of a trap that made two separate fault checks report
    results that were not true, and it is worth understanding rather than
    trusting.

    Python keeps a compiled copy of every module beside it, in ``__pycache__``,
    so that it does not have to read and understand the source again next time.
    It decides whether that copy is still good by comparing two things about the
    source: its **size**, and the **second** in which it was last changed.

    Both of those can be unchanged by a real edit. A fault check often swaps one
    word for another of the same length — ``mode="a"`` for ``mode="w"``, or one
    character of a checksum constant — and then puts the original back within the
    same second. The file is genuinely different, then genuinely correct again,
    and Python cannot tell that anything happened at all.

    What follows is the bad part. The compiled copy left behind holds the
    **faulty** version. The check reports every fault caught and restores every
    file perfectly, and then the next ordinary test run quietly executes the
    broken code from cache. That was observed: one campaign came back green and
    the following test run failed in eight places, from a source file that had
    already been put back.

    So after every rewrite the compiled copy is discarded, and Python is made to
    read the source again. Deleting it is always safe; the worst that happens is
    that the next import is a few milliseconds slower.

    One caveat, stated rather than glossed over. Trying to stage the trap
    deliberately on this machine did **not** reproduce it: writing a same-length
    fault, running it, restoring within the same second and running again gave
    the restored answer every time, so something here — the filesystem's
    timestamps, or the speed of the writes — hides it. That does not make the
    trap imaginary; two separate fault checks ran into it, and one of them was
    followed by eight test failures from a file that had already been put back.
    It does mean this guard is kept because it is cheap and certainly correct,
    not because a test in this repository demonstrates the failure. What *is*
    demonstrated is narrower: the guard removes the compiled copies it says it
    removes.
    """
    cached = path.parent / "__pycache__"
    if not cached.is_dir():
        return
    for compiled in cached.glob(f"{path.stem}.*.pyc"):
        compiled.unlink(missing_ok=True)
    # importlib also keeps its own idea of what it has already read.
    importlib.invalidate_caches()


def replace_source(path: Path, text: str) -> None:
    """Replace a mutation subject and prove the bytes match the request.

    Fault checks deliberately edit real source files. A checker that reports
    success but leaves its subject truncated is worse than no checker, so every
    mutation and every restoration is read back immediately.

    The compiled copy is then discarded as well, for the reason set out in
    :func:`_forget_the_compiled_copy` — without that, a same-length edit reverted
    within the same second leaves Python running the faulty version afterwards.
    """
    if not text.strip():
        raise RuntimeError(f"Refusing to replace mutation subject {path} with an empty file.")
    path.write_text(text, encoding="utf-8")
    if path.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"Mutation subject {path} did not read back exactly after replacement.")
    _forget_the_compiled_copy(path)
