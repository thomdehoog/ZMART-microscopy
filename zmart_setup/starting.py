"""The start files, and the icons on the desktop that open them.

A person who does not write code should never need a terminal to start ZMART.
So the setup writes a start file for this computer into ``local/`` (kept out
of git), with the places of the ZMART environment, of conda and of our
workflows written in, and puts an icon on the desktop that opens it:

- **ZMART interface** opens the operator window in ``zmart-for-non-coders``, pointed
  at the interface's workflows and the analysis pipelines cloned next to
  ZMART Microscopy.
- **ZMART notebook**, for people who write code, opens JupyterLab in
  ``zmart-for-coders``, in ``workflows/target_acquisition/for-coders/template``.

The start files set up the environment's programs themselves, so nothing has
to be activated first. When ZMART does not start, the window stays open with a
sentence saying what to do, rather than flashing past.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import os
import platform
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import conda
from .layout import CODERS, clones

SYSTEM = platform.system()

#: The icon on the desktop: the microscope from the ZMART Microscopy logo, on a
#: white rounded square so it shows on a dark desktop as well as on a light one.
#: Windows takes the ``.ico``, Linux the ``.png``; macOS keeps its own icon for
#: a start file.
ICON_WINDOWS = Path(__file__).resolve().parent / "zmart.ico"
ICON_LINUX = Path(__file__).resolve().parent / "zmart.png"


@dataclass
class Start:
    """One way to start ZMART: its name on the desktop, its environment, and the command it runs there."""

    name: str
    prefix: Path
    module: list[str]
    variables: dict[str, str]
    folder: Path


def starts_for(operator: Path, coder: Path | None, output_root: str | None = None) -> list[Start]:
    """The ways to start ZMART on this computer: the operator window, and for coders the notebook.

    ``operator`` and ``coder`` are the folders of the two environments; the
    notebook is offered only when there is a coder's environment. TEMP and TMP
    point into the environment, because the analysis runs a small script from
    there, and where an environment's programs may run, that folder may too.
    """
    window = clones()["interface"].workflows
    module = ["-m", "zmart_interface.launcher"] + (["--output-root", output_root] if output_root else [])
    starts = [Start("ZMART interface", operator, module,
                    {"ZMART_INTERFACE_WORKFLOWS": str(window),
                     "ZMART_ANALYSIS_WORKFLOWS": str(clones()["analysis"].workflows),
                     **_temp(operator)}, window)]
    if coder is not None:
        starts.append(Start("ZMART notebook", coder, ["-m", "jupyterlab", f"--notebook-dir={CODERS}"],
                            _temp(coder), CODERS))
    return starts


def _temp(prefix: Path) -> dict[str, str]:
    return {"TEMP": str(prefix / "tmp"), "TMP": str(prefix / "tmp")}


def windows_file(start: Start, conda_exe: str) -> str:
    """A ``.bat`` file that starts ``start`` in its environment."""
    prefix = start.prefix
    programs = ";".join(str(one) for one in conda.programs_of(prefix))
    variables = "\n".join(f'set "{key}={value}"' for key, value in start.variables.items())
    return f"""@echo off
rem {start.name}: written by setup_zmart.py for this computer. Run setup_zmart.py again
rem to write it afresh, for example after ZMART Microscopy has moved to another folder.
title {start.name}
if not exist "{prefix}\\python.exe" (
  echo The ZMART environment is not at {prefix} any more.
  echo Run setup_zmart.py again, in the folder of ZMART Microscopy.
  pause
  exit /b 1
)
set "PATH={programs};%PATH%"
set "CONDA_EXE={conda_exe}"
{variables}
cd /d "{start.folder}"
"{prefix}\\python.exe" {" ".join(_quoted(start.module))}
if errorlevel 1 (
  echo.
  echo {start.name} stopped with an error; what it said is above.
  echo To have Claude Code find out why, open it in the folder of ZMART Microscopy and say:
  echo     Read .claude/agents/zmart-install-doctor.md and follow it.
  pause
)
"""


def _quoted(words: list[str]) -> list[str]:
    """Each word of a command, in double quotes when it holds a space."""
    return [f'"{word}"' if " " in word else word for word in words]


def posix_file(start: Start, conda_exe: str) -> str:
    """A shell script that starts ``start`` in its environment (macOS and Linux)."""
    prefix = start.prefix
    programs = ":".join(str(one) for one in conda.programs_of(prefix))
    variables = "\n".join(f'export {key}="{value}"' for key, value in start.variables.items())
    return f"""#!/bin/sh
# {start.name}: written by setup_zmart.py for this computer. Run setup_zmart.py again
# to write it afresh, for example after ZMART Microscopy has moved to another folder.
if [ ! -x "{prefix}/bin/python" ]; then
  echo "The ZMART environment is not at {prefix} any more."
  echo "Run setup_zmart.py again, in the folder of ZMART Microscopy."
  read -r _ 2>/dev/null
  exit 1
fi
export PATH="{programs}:$PATH"
export CONDA_EXE="{conda_exe}"
{variables}
cd "{start.folder}" || exit 1
"{prefix}/bin/python" {" ".join(_quoted(start.module))} || {{
  echo
  echo "{start.name} stopped with an error; what it said is above."
  echo "To have Claude Code find out why, open it in the folder of ZMART Microscopy and say:"
  echo "    Read .claude/agents/zmart-install-doctor.md and follow it."
  read -r _ 2>/dev/null
}}
"""


def desktop() -> Path | None:
    """The desktop folder of the person running the setup, or None when there is none."""
    if SYSTEM == "Windows":
        found = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, text=True,
        ).stdout.strip()
        return Path(found) if found else None
    folder = Path.home() / "Desktop"
    return folder if folder.is_dir() else None


def write(shell, record, local: Path, operator: Path, coder: Path | None, conda_exe: str,
          output_root: str | None = None, icons: bool = True) -> list[Path]:
    """Write the start files into ``local/``, and an icon for each on the desktop."""
    written = []
    place = desktop() if icons else None
    for start in starts_for(operator, coder, output_root):
        (start.prefix / "tmp").mkdir(parents=True, exist_ok=True)
        if SYSTEM == "Windows":
            path = local / f"{start.name}.bat"
            path.write_text(windows_file(start, conda_exe), encoding="utf-8")
        else:
            suffix = ".command" if SYSTEM == "Darwin" else ".sh"
            path = local / f"{start.name}{suffix}"
            path.write_text(posix_file(start, conda_exe), encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(path)
        icon = _icon(shell, place, start, path) if place else None
        found = f"{path}" + (f", with an icon on the desktop ({icon.name})" if icon else "")
        record.worked(f"the start file '{start.name}'", found)
    return written


def _icon(shell, place: Path, start: Start, target: Path) -> Path | None:
    """An icon on the desktop that opens ``target``; None when one could not be made."""
    if SYSTEM == "Windows":
        link = place / f"{start.name}.lnk"
        script = (
            "$shell = New-Object -ComObject WScript.Shell; "
            f"$link = $shell.CreateShortcut('{link}'); "
            f"$link.TargetPath = '{target}'; "
            f"$link.WorkingDirectory = '{start.folder}'; "
            f"$link.IconLocation = '{ICON_WINDOWS},0'; "
            f"$link.Description = '{start.name}'; "
            "$link.Save()"
        )
        done = shell.run(["powershell", "-NoProfile", "-Command", script], timeout=60, quiet=True)
        return link if done.ok else None
    if SYSTEM == "Darwin":
        link = place / target.name
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(target, link)
        return link
    link = place / f"{start.name.lower().replace(' ', '-')}.desktop"
    link.write_text(
        "[Desktop Entry]\nType=Application\n"
        f"Name={start.name}\nExec={target}\nPath={start.folder}\nIcon={ICON_LINUX}\nTerminal=true\n",
        encoding="utf-8",
    )
    link.chmod(link.stat().st_mode | stat.S_IXUSR)
    return link
