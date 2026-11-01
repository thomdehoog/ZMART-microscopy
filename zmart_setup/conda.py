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
from pathlib import Path

WINDOWS = platform.system() == "Windows"

#: Where a conda installation usually is, when it is not on the PATH and was not activated.
LIKELY_PLACES = [
    Path.home() / "miniforge3",
    Path.home() / "Miniforge3",
    Path.home() / "miniconda3",
    Path.home() / "Miniconda3",
    Path.home() / "anaconda3",
    Path("C:/ProgramData/MinicondaZMB"),
    Path("C:/ProgramData/miniforge3"),
    Path("C:/ProgramData/Miniconda3"),
    Path("/opt/conda"),
    Path("/opt/miniforge3"),
]


def find_conda(environment=None) -> str | None:
    """Where the ``conda`` program is, or None.

    Looked for in this order: ``CONDA_EXE`` (set when conda is activated), the
    PATH, and the places conda is usually installed in.
    """
    environment = os.environ if environment is None else environment
    named = environment.get("CONDA_EXE")
    if named and Path(named).is_file():
        return named
    found = shutil.which("conda")
    if found:
        return found
    for place in LIKELY_PLACES:
        for candidate in (place / "Scripts" / "conda.exe", place / "condabin" / "conda.bat",
                          place / "bin" / "conda", place / "condabin" / "conda"):
            if candidate.is_file():
                return str(candidate)
    return None


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
