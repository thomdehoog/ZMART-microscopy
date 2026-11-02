"""Set up the rest of the target acquisition workflow for non-coders (README.md, step 3).

Run it from a conda prompt, in this folder, after steps 1 and 2:

    python install.py --output-root D:\\ZMART-data

It adds the ZMART Interface to the base environment, clones ZMART Analysis
next to ZMART-microscopy and makes the environments of its example workflows,
and writes a launcher, zmart-interface.bat, with a shortcut on the desktop.
An environment or clone that already exists is kept.

Only the standard library; it calls conda, git and, for the shortcut,
PowerShell. --dry-run prints the commands without running them.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ANALYSIS_REPO = "https://github.com/ZMB-UZH/ZMART-analysis"
ANALYSIS_VERSION = "v0.6.0rc9"
INTERFACE = "zmart-interface @ git+https://github.com/ZMB-UZH/ZMART-interface@v0.1.0rc6"
BASE_ENV = "zmart-for-non-coders"
HERE = Path(__file__).resolve().parent

#: The environments of the analysis workflows the interface runs, by name
ANALYSIS_ENVS = {
    "ZMART--focus--main": "examples/focus/environments/main.yml",
    "ZMART--object_analysis--classical": "examples/object_analysis/environments/classical.yml",
    "ZMART--object_analysis--cellpose": "examples/object_analysis/environments/cellpose.yml",
    "ZMART--object_analysis--umap": "examples/object_analysis/environments/umap.yml",
}


def main() -> None:
    args = _arguments()

    conda = _conda()

    # The interface, in the base environment of step 1; it brings the viewer and the engine
    envs = _environments(conda)

    if BASE_ENV not in envs and not args.dry_run:
        sys.exit(f"{BASE_ENV} does not exist yet: make it first (README.md, step 1).")

    _run([conda, "run", "-n", BASE_ENV, "pip", "install", INTERFACE], args.dry_run)

    # ZMART Analysis next to ZMART-microscopy, and its environments
    analysis = HERE.parents[2].parent / "ZMART-analysis"

    _clone(conda, analysis, args.dry_run)

    for name, file in ANALYSIS_ENVS.items():
        _create_env(conda, envs, name, analysis / file, args.dry_run)

    # Tell the interface where the workflows are, for a manual start too
    examples = analysis / "examples"

    _run([conda, "env", "config", "vars", "set", "-n", BASE_ENV, f"ZMART_ANALYSIS_WORKFLOWS={examples}"], args.dry_run)

    # The launcher, beside the base environment, and its shortcut on the desktop
    prefix = envs.get(BASE_ENV) or Path(_conda_base(conda)) / "envs" / BASE_ENV

    _launcher(Path(_conda_base(conda)), Path(prefix), examples, args.output_root, args.dry_run)

    print("\nDone. Start the interface from the shortcut on the desktop (README.md, step 4).")


def _arguments() -> argparse.Namespace:
    """The output folder for the runs, and whether to only print the commands."""

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-root", required=True, help="the folder the runs are saved in, e.g. D:\\ZMART-data")
    parser.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")

    return parser.parse_args()


def _conda() -> str:
    """The conda executable of the prompt this runs in."""

    conda = os.environ.get("CONDA_EXE")

    if not conda:
        sys.exit("conda was not found: run this from a conda prompt (Miniforge or Miniconda).")

    return conda


def _conda_base(conda: str) -> str:
    """The folder conda is installed in."""

    return json.loads(subprocess.check_output([conda, "info", "--json"], text=True))["root_prefix"]


def _environments(conda: str) -> dict[str, str]:
    """The conda environments that exist, by name, with their folders."""

    found = json.loads(subprocess.check_output([conda, "env", "list", "--json"], text=True))["envs"]

    return {Path(prefix).name: prefix for prefix in found}


def _create_env(conda: str, envs: dict, name: str, file: Path, dry_run: bool) -> None:
    """Make an environment from its file, unless it exists already."""

    if name in envs:
        print(f"{name} exists and is kept. To rebuild it: conda env remove -n {name}, then run this again.")
        return

    _run([conda, "env", "create", "-f", str(file)], dry_run)


def _clone(conda: str, folder: Path, dry_run: bool) -> None:
    """Clone ZMART Analysis at its version, unless the folder exists already."""

    if folder.exists():
        print(f"{folder} exists and is kept.")
        return

    _run([conda, "run", "-n", BASE_ENV, "git", "clone", "-b", ANALYSIS_VERSION, ANALYSIS_REPO, str(folder)], dry_run)


def _launcher(base: Path, prefix: Path, examples: Path, output_root: str, dry_run: bool) -> None:
    """zmart-interface.bat beside the base environment, and a shortcut to it on the desktop."""

    bat = prefix / "zmart-interface.bat"

    text = (
        "@echo off\n"
        f'call "{base / "condabin" / "conda.bat"}" activate {BASE_ENV}\n'
        f'set "ZMART_ANALYSIS_WORKFLOWS={examples}"\n'
        f'zmart-interface --output-root "{output_root}"\n'
    )

    print(f"\nwrite {bat}:\n{text}")

    if os.name != "nt":
        print("Not Windows: no launcher written. Start the interface as README.md, step 4, says.")
        return

    # The desktop the user sees, also when it lives in OneDrive
    shortcut = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\\ZMART Interface.lnk\");"
        f"$s.TargetPath='{bat}';$s.Save()"
    )

    if not dry_run:
        bat.write_text(text, encoding="utf-8")

    _run(["powershell", "-NoProfile", "-Command", shortcut], dry_run)


def _run(command: list[str], dry_run: bool) -> None:
    """Run one command, or only print it."""

    print(">", " ".join(command))

    if not dry_run:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
