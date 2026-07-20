#!/usr/bin/env python3
"""Build the ZMART Microscopy Python environment.

Creates (or updates) the conda environment defined in environment.yml,
verifies the core packages import, and asserts every package came from
conda-forge (the conda `defaults` channel is never allowed). The package
list itself lives in environment.yml; this script only orchestrates conda
and checks the result.

Usage:
    python build_env.py                 # create env "zmart-microscopy"
    python build_env.py --recreate      # remove an existing env, then create
    python build_env.py --update        # update an existing env in place
    python build_env.py --name my-env   # override the default "zmart-microscopy"
    python build_env.py --offline       # use cached conda packages/browser only

Requires conda on PATH (MinicondaZMB).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / "environment.yml"
DEFAULT_NAME = "zmart-microscopy"
WINDOWS_ACCESS_VIOLATION = 0xC0000005

# Imports the env must satisfy after a successful build.
VERIFY = {
    "numpy": "import numpy",
    "scipy": "import scipy",
    "scikit-image": "import skimage",
    "opencv": "import cv2",
    "tifffile": "import tifffile",
    "pillow": "from PIL import Image",
    "ome-types": "import ome_types",
    "lxml": "import lxml",
    "matplotlib": "import matplotlib",
    # The v4 operator notebooks need the interactive canvas and the React
    # widget host; a build that misses either would only fail at the scope.
    "ipympl": "import ipympl",
    "anywidget": "import anywidget",
    "traitlets": "import traitlets",
    "playwright-python": "import playwright.sync_api",
    "pytest": "import pytest",
    "pytest-cov": "import pytest_cov",
    "ruff": "import ruff",
    "ipython": "import IPython",
    "ipykernel": "import ipykernel",
    # Without these the notebook end-to-end and guard tests silently skip.
    "nbformat": "import nbformat",
    "nbclient": "import nbclient",
    "pythonnet": "import clr",
}


def _conda() -> str:
    conda = shutil.which("conda")
    if conda is None:
        sys.exit("conda not found on PATH. Activate MinicondaZMB and retry.")
    return conda


def _env_exists(conda: str, name: str) -> bool:
    out = subprocess.run([conda, "env", "list", "--json"], capture_output=True, text=True)
    if out.returncode != 0:
        return False
    try:
        envs = json.loads(out.stdout).get("envs", [])
    except json.JSONDecodeError:
        return False
    return any(Path(p).name == name for p in envs)


def _env_prefix(conda: str, name: str) -> Path:
    """Resolve the env prefix from `conda env list` (never `conda run`).

    `conda run` misreports its exit code on Windows when stdout/stderr are
    redirected, which made the verify steps below report false failures for a
    perfectly healthy env. Reading the prefix from the env list and invoking
    the interpreter directly sidesteps that entirely.
    """
    out = subprocess.run([conda, "env", "list", "--json"], capture_output=True, text=True)
    try:
        envs = json.loads(out.stdout).get("envs", [])
    except json.JSONDecodeError:
        envs = []
    for p in envs:
        if Path(p).name == name:
            return Path(p)
    sys.exit(f"could not resolve prefix for env '{name}'.")


def _env_python(prefix: Path) -> Path:
    py = prefix / "python.exe" if os.name == "nt" else prefix / "bin" / "python"
    if not py.exists():
        sys.exit(f"env interpreter not found at {py}.")
    return py


def _env_process_env(prefix: Path) -> dict[str, str]:
    """Return subprocess variables scoped to the target conda environment."""
    env = os.environ.copy()
    env["CONDA_PREFIX"] = str(prefix)
    env["CONDA_DEFAULT_ENV"] = prefix.name
    # User-profile executables are blocked on managed Windows machines. Keep
    # Playwright's browser beside the approved conda executables instead.
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(prefix / "playwright-browsers")
    return env


def build(name: str, update: bool, recreate: bool, offline: bool) -> None:
    conda = _conda()
    if not ENV_FILE.exists():
        sys.exit(f"environment.yml not found at {ENV_FILE}")
    if update:
        action = ["env", "update", "--prune"]
    else:
        if _env_exists(conda, name):
            if not recreate:
                sys.exit(
                    f"env '{name}' already exists; pass --recreate to rebuild it "
                    f"clean or --update to update it in place."
                )
            print(f"+ removing existing env '{name}'", flush=True)
            if subprocess.call([conda, "env", "remove", "-n", name, "-y"]) != 0:
                sys.exit(f"could not remove existing env '{name}'.")
        action = ["env", "create"]
    cmd = [conda, *action, "-f", str(ENV_FILE), "-n", name]
    conda_env = os.environ.copy()
    if offline:
        conda_env["CONDA_OFFLINE"] = "true"
    print("+", " ".join(cmd), flush=True)
    # conda.BAT is executed through cmd.exe, which cannot use a UNC working
    # directory. The environment file is absolute, so a local cwd is enough.
    rc = subprocess.call(cmd, cwd=str(Path.home()), env=conda_env)
    if (
        os.name == "nt"
        and rc == WINDOWS_ACCESS_VIOLATION
        and conda_env.get("CONDA_SOLVER", "").lower() != "classic"
    ):
        print(
            "conda's default solver crashed with access violation 0xC0000005; "
            "retrying with the classic solver.",
            flush=True,
        )
        conda_env["CONDA_SOLVER"] = "classic"
        rc = subprocess.call(cmd, cwd=str(Path.home()), env=conda_env)
    if rc != 0:
        sys.exit(f"conda {' '.join(action)} failed (exit {rc}).")


def verify_imports(name: str) -> None:
    prefix = _env_prefix(_conda(), name)
    py = _env_python(prefix)
    env = _env_process_env(prefix)
    print(f"\nVerifying imports in env '{name}':", flush=True)
    failures = []
    for pkg, stmt in VERIFY.items():
        started = time.perf_counter()
        try:
            rc = subprocess.call(
                [str(py), "-c", stmt],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=90,
                env=env,
                cwd=str(prefix),
            )
        except subprocess.TimeoutExpired:
            rc = 124
        elapsed = time.perf_counter() - started
        suffix = " (timed out)" if rc == 124 else ""
        print(
            f"  [{'ok' if rc == 0 else 'FAIL'}] {pkg} ({elapsed:.1f}s){suffix}",
            flush=True,
        )
        if rc != 0:
            failures.append(pkg)
    # pythonnet's clr only resolves on a machine with .NET / LAS X; flag it
    # but do not fail the whole build on that one alone.
    hard = [p for p in failures if p != "pythonnet"]
    if hard:
        sys.exit(f"\nImport check failed for: {', '.join(hard)}")
    if "pythonnet" in failures:
        print(
            "\nNote: pythonnet (clr) did not import -- expected off the LAS X PC.",
            flush=True,
        )


def verify_node(name: str) -> None:
    """Prove the generated-widget JavaScript parser is in the environment."""
    prefix = _env_prefix(_conda(), name)
    node = prefix / ("node.exe" if os.name == "nt" else "bin/node")
    try:
        rc = (
            subprocess.call(
                [str(node), "--version"],
                timeout=30,
                env=_env_process_env(prefix),
                cwd=str(prefix),
            )
            if node.exists()
            else 127
        )
    except subprocess.TimeoutExpired:
        rc = 124
    if rc != 0:
        sys.exit("Node.js verification failed; generated widget ESM cannot be checked.")
    print("  [ok] nodejs", flush=True)


def install_and_verify_browser(name: str, offline: bool) -> None:
    """Install Chromium in Playwright's cache and prove it launches.

    The browser cache lives inside the conda prefix so managed Windows machines
    can execute it. In offline mode the install command is skipped and an
    already-cached matching browser is required; otherwise the normal
    idempotent installer is run first.
    """
    prefix = _env_prefix(_conda(), name)
    py = _env_python(prefix)
    env = _env_process_env(prefix)
    if not offline:
        print("\nInstalling the Chromium build matched to Playwright:", flush=True)
        try:
            install_rc = subprocess.call(
                [str(py), "-m", "playwright", "install", "chromium"],
                timeout=600,
                env=env,
                cwd=str(prefix),
            )
        except subprocess.TimeoutExpired:
            install_rc = 124
        if install_rc != 0:
            sys.exit("Playwright Chromium installation failed.")
    print("Verifying headless Chromium launch:", flush=True)
    launch = (
        "from playwright.sync_api import sync_playwright; "
        "p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop()"
    )
    try:
        launch_rc = subprocess.call(
            [str(py), "-c", launch], timeout=120, env=env, cwd=str(prefix)
        )
    except subprocess.TimeoutExpired:
        launch_rc = 124
    if launch_rc != 0:
        hint = "Cache it while online with: python -m playwright install chromium"
        sys.exit(f"Playwright Chromium launch failed. {hint}")
    print("  [ok] playwright Chromium", flush=True)


def verify_channels(name: str) -> None:
    """Assert every conda package came from conda-forge (no defaults).

    Reads the authoritative `conda-meta/*.json` channel field rather than
    `conda list --show-channel-urls`, whose text output mislabels some
    conda-forge packages as `pypi` on conda 25.x.
    """
    conda = _conda()
    meta_dir = _env_prefix(conda, name) / "conda-meta"
    offenders = []
    count = 0
    for jf in sorted(meta_dir.glob("*.json")):
        meta = json.loads(jf.read_text(encoding="utf-8"))
        count += 1
        if "conda-forge" not in meta.get("channel", ""):
            offenders.append(f"{meta.get('name', jf.stem)} ({meta.get('channel') or 'unknown'})")
    if offenders:
        sys.exit("Packages NOT from conda-forge: " + ", ".join(offenders))
    print(f"All {count} packages sourced from conda-forge.", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default=DEFAULT_NAME, help="conda env name")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--recreate", action="store_true", help="remove an existing env before creating it"
    )
    mode.add_argument(
        "--update",
        action="store_true",
        help="update an existing env in place instead of creating it",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="use cached conda packages and an already-cached Playwright Chromium",
    )
    args = ap.parse_args()
    build(args.name, args.update, args.recreate, args.offline)
    verify_imports(args.name)
    verify_node(args.name)
    install_and_verify_browser(args.name, args.offline)
    verify_channels(args.name)
    print(f"\nDone. Activate with:  conda activate {args.name}")


if __name__ == "__main__":
    main()
