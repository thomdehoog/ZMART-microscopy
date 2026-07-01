"""Environment/context diagnostics for cross-system failure triage.

When a test fails on a *different* machine -- a CI runner, or the new
institute's microscope PC -- the first question is always "what was the
environment?". This module answers that question and is wired into two places
so the answer is never missing:

  * ``tests/conftest.py`` calls :func:`header_lines` from ``pytest_report_header``,
    so the context is printed at the top of *every* pytest run (and therefore at
    the top of every captured CI log next to the failures).
  * ``run_ci.py`` runs this module as a script, which prints the same header and
    writes a machine-readable ``tests/_report/env.json`` alongside the JUnit and
    coverage reports.

Everything here is defensive: a missing package, absent git, or an unimportable
driver is *reported*, never raised. Diagnostics must not be able to break a run.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Packages whose versions materially change behaviour across systems. Absent
# packages are reported as "(absent)" rather than omitted, because an absence is
# itself diagnostic (e.g. pythonnet missing on a Linux CI runner is expected;
# numpy missing anywhere is a real problem).
_TRACKED_PACKAGES = (
    "pytest",
    "pytest-cov",
    "coverage",
    "ruff",
    "numpy",
    "scipy",
    "tifffile",
    "pillow",
    "pythonnet",
)


def _package_version(name: str) -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version(name)
        except PackageNotFoundError:
            return "(absent)"
    except Exception as exc:  # pragma: no cover - importlib should always exist
        return f"(error: {exc})"


def _git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=str(_HERE),
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _read_git_ref(gitdir: Path, ref: str) -> str:
    loose = gitdir / ref
    try:
        if loose.exists():
            return loose.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    # packed-refs fallback (refs that have been garbage-collected into a pack)
    try:
        for line in (gitdir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith(("#", "^")) and line.endswith(ref):
                return line.split(" ", 1)[0].strip()
    except Exception:
        pass
    return ""


def _git_branch_sha_dirty() -> tuple[str, str, bool]:
    """Best-effort git revision.

    Prefer the git binary (it also reports a dirty working tree); fall back to
    reading ``.git/`` directly so the revision is still recorded on machines
    where git is not on PATH (e.g. conda-only installs, as on the microscope PC).
    """
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    sha = _git(["rev-parse", "--short", "HEAD"])
    dirty = bool(_git(["status", "--porcelain"])) if sha else False
    if branch and sha:
        return branch, sha, dirty

    directory = _HERE
    for _ in range(10):
        gitdir = directory / ".git"
        if gitdir.is_dir():
            try:
                head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
            except Exception:
                break
            if head.startswith("ref:"):
                ref = head.split(":", 1)[1].strip()
                return ref.rsplit("/", 1)[-1], _read_git_ref(gitdir, ref)[:7], dirty
            return "(detached)", head[:7], dirty
        directory = directory.parent
    return branch, sha, dirty


def _lasx_runtime_status() -> str:
    """Report whether the LAS X CAM runtime looks available -- without loading it.

    We deliberately do *not* call ``load_lasx_api_runtime()``: that imports .NET
    assemblies and is slow / side-effecting, and this runs on every test session.
    We only import the (lazy) module and, if it exposes its install root, report
    whether that path exists. On a machine with no LAS X (CI, Linux) this lands
    on a clean "unavailable", which is the correct, expected answer there.
    """
    try:
        from navigator_expert.connection import lasx_runtime
    except Exception as exc:
        return f"module import failed: {type(exc).__name__}: {exc}"

    root = None
    for attr in ("_runtime_root", "runtime_root", "default_runtime_root"):
        fn = getattr(lasx_runtime, attr, None)
        if callable(fn):
            try:
                root = fn()
                break
            except Exception:
                continue
    if root is None:
        return "module import OK (install-root introspection unavailable)"
    root_path = Path(root)
    return f"root={root_path} exists={root_path.exists()}"


def context() -> dict:
    """Return the full environment context as a JSON-serialisable dict."""
    git_branch, git_sha, git_dirty = _git_branch_sha_dirty()
    ctx: dict = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "node": platform.node(),
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "cwd": os.getcwd(),
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "packages": {name: _package_version(name) for name in _TRACKED_PACKAGES},
        "git_branch": git_branch,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
    }
    try:
        import navigator_expert as drv

        ctx["navigator_expert_version"] = getattr(drv, "__version__", "(unknown)")
        ctx["navigator_expert_path"] = str(Path(drv.__file__).resolve().parent)
    except Exception as exc:
        ctx["navigator_expert_version"] = f"IMPORT FAILED: {type(exc).__name__}: {exc}"
        ctx["navigator_expert_path"] = ""
    ctx["lasx_runtime"] = _lasx_runtime_status()
    return ctx


def header_lines() -> list[str]:
    """Render the context as compact, human-scannable header lines for pytest."""
    c = context()
    packages = "  ".join(f"{name}={ver}" for name, ver in c["packages"].items())
    dirty = " (dirty)" if c["git_dirty"] else ""
    git = f"{c['git_branch'] or '?'}@{c['git_sha'] or '?'}{dirty}"
    return [
        f"navigator_expert test context  ({c['timestamp']})",
        f"  platform : {c['platform']}  [{c['machine']}]  node={c['node']}",
        f"  python   : {c['python_version']} ({c['python_implementation']})"
        f"  [{c['python_executable']}]",
        f"  driver   : navigator_expert {c['navigator_expert_version']}",
        f"  location : {c['navigator_expert_path'] or '(not importable)'}",
        f"  git      : {git}",
        f"  LAS X    : {c['lasx_runtime']}",
        f"  packages : {packages}",
        f"  PYTHONPATH: {c['pythonpath'] or '(unset)'}",
    ]


def write_env_json(report_dir: Path) -> Path:
    """Write the context to ``<report_dir>/env.json`` and return the path."""
    report_dir.mkdir(parents=True, exist_ok=True)
    target = report_dir / "env.json"
    target.write_text(json.dumps(context(), indent=2), encoding="utf-8")
    return target


def _bootstrap_sys_path() -> None:
    """Make the driver importable when this file is run standalone (no PYTHONPATH).

    A no-op when run via run_ci.py or pytest (the import roots are already set),
    but it lets ``python tests/_diagnostics.py`` report the driver version and
    location too -- handy as a quick setup check on a freshly cloned machine.
    """
    machine_root = _HERE.parents[1]  # navigator_expert/tests -> .../<machine>
    if str(machine_root) not in sys.path:
        sys.path.insert(0, str(machine_root))
    directory = machine_root
    for _ in range(8):
        if (directory / "shared").is_dir():
            if str(directory) not in sys.path:
                sys.path.insert(0, str(directory))
            break
        directory = directory.parent


def main() -> int:
    _bootstrap_sys_path()
    for line in header_lines():
        print(line)
    target = write_env_json(_HERE / "_report")
    print(f"  (context written to {target})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
