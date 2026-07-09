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

Requires conda on PATH (MinicondaZMB).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / "environment.yml"
DEFAULT_NAME = "zmart-microscopy"

# Imports the env must satisfy after a successful build.
VERIFY = {
    "numpy": "import numpy",
    "scipy": "import scipy",
    "scikit-image": "import skimage",
    "opencv": "import cv2",
    "tifffile": "import tifffile",
    "matplotlib": "import matplotlib",
    "pytest": "import pytest",
    "ipython": "import IPython",
    "ipykernel": "import ipykernel",
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


def build(name: str, update: bool, recreate: bool) -> None:
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
            print(f"+ removing existing env '{name}'")
            if subprocess.call([conda, "env", "remove", "-n", name, "-y"]) != 0:
                sys.exit(f"could not remove existing env '{name}'.")
        action = ["env", "create"]
    cmd = [conda, *action, "-f", str(ENV_FILE), "-n", name]
    print("+", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(HERE))
    if rc != 0:
        sys.exit(f"conda {' '.join(action)} failed (exit {rc}).")


def verify_imports(name: str) -> None:
    py = _env_python(_env_prefix(_conda(), name))
    print(f"\nVerifying imports in env '{name}':")
    failures = []
    for pkg, stmt in VERIFY.items():
        rc = subprocess.call(
            [str(py), "-c", stmt],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"  [{'ok' if rc == 0 else 'FAIL'}] {pkg}")
        if rc != 0:
            failures.append(pkg)
    # pythonnet's clr only resolves on a machine with .NET / LAS X; flag it
    # but do not fail the whole build on that one alone.
    hard = [p for p in failures if p != "pythonnet"]
    if hard:
        sys.exit(f"\nImport check failed for: {', '.join(hard)}")
    if "pythonnet" in failures:
        print("\nNote: pythonnet (clr) did not import -- expected off the LAS X PC.")


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
    print(f"All {count} packages sourced from conda-forge.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default=DEFAULT_NAME, help="conda env name")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--recreate", action="store_true",
                      help="remove an existing env before creating it")
    mode.add_argument("--update", action="store_true",
                      help="update an existing env in place instead of creating it")
    args = ap.parse_args()
    build(args.name, args.update, args.recreate)
    verify_imports(args.name)
    verify_channels(args.name)
    print(f"\nDone. Activate with:  conda activate {args.name}")


if __name__ == "__main__":
    main()
