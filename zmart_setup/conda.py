"""Finding conda, the environments it has, and where an environment keeps its programs.

ZMART runs in conda environments from conda-forge: one for ZMART itself
(``zmart``), and one for each kind of analysis step (``ZMART--focus--main``
and so on). This module only finds things; making environments is the job of
``blocks`` and ``analysis``.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = platform.system() == "Windows"


def find_conda(environment=None, python: str | None = None) -> str | None:
    """Where the ``conda`` program is, or None.

    Looked for in this order: ``CONDA_EXE`` (set when conda is activated), the
    conda this Python belongs to (``setup_zmart.py`` is run with conda's base
    Python, which answers ``conda info`` itself), and the PATH. No folder is
    guessed: where conda lives differs from computer to computer, and conda
    says so itself.
    """
    environment = os.environ if environment is None else environment
    named = environment.get("CONDA_EXE")
    if named and Path(named).is_file():
        return named
    root = _own_root(python or sys.executable)
    if root is not None:
        found = _program_in(root)
        if found:
            return found
    return shutil.which("conda")


def _own_root(python: str) -> Path | None:
    """The conda installation this Python belongs to, from its own ``conda info``; None without one."""
    try:
        done = subprocess.run([python, "-m", "conda", "info", "--json"], capture_output=True,
                              text=True, timeout=120)
        return Path(json.loads(done.stdout)["root_prefix"]) if done.returncode == 0 else None
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None


def _program_in(root: Path) -> str | None:
    """The ``conda`` program of the installation in ``root``, or None."""
    for candidate in (root / "Scripts" / "conda.exe", root / "condabin" / "conda.bat",
                      root / "bin" / "conda", root / "condabin" / "conda"):
        if candidate.is_file():
            return str(candidate)
    return None


def where_it_keeps(shell, conda: str) -> dict:
    """Where conda is installed and where it makes environments, as ``conda info`` says."""
    done = shell.run([conda, "info", "--json"], timeout=120, quiet=True)
    try:
        said = json.loads(done.output[done.output.index("{"):])
    except ValueError:
        return {}
    return {"root_prefix": said.get("root_prefix"), "envs_dirs": said.get("envs_dirs", [])}


def environments(shell, conda: str) -> dict[str, Path]:
    """Every environment conda knows, by name, with its folder."""
    done = shell.run([conda, "env", "list", "--json"], timeout=120, quiet=True)
    if not done.ok:
        return {}
    try:
        folders = json.loads(done.output[done.output.index("{"):])["envs"]
    except (ValueError, KeyError):
        return {}
    return {Path(folder).name: Path(folder) for folder in folders}


def python_of(prefix: Path) -> Path:
    """The Python of the environment in ``prefix``."""
    return prefix / "python.exe" if WINDOWS else prefix / "bin" / "python"


def programs_of(prefix: Path) -> list[Path]:
    """The folders of an environment where its programs and libraries are."""
    if WINDOWS:
        return [prefix, prefix / "Library" / "bin", prefix / "Scripts"]
    return [prefix / "bin"]


def environment_for(prefix: Path, conda: str, extra: dict | None = None) -> dict:
    """The variables a program in the environment needs, as if the environment were activated.

    Its programs come first on the PATH (pip needs git, the analysis engine
    needs conda), and ``CONDA_EXE`` says where conda is, because the analysis
    engine starts each step's environment through it.
    """
    path = os.pathsep.join([*map(str, programs_of(prefix)), os.environ.get("PATH", "")])
    return {"PATH": path, "CONDA_EXE": conda, **(extra or {})}
