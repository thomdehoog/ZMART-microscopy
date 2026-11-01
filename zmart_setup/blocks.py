"""The ZMART environment, and the blocks installed into it.

The environment is made from ``zmart_setup/environments/zmart.yml`` (and, for
people who write code, updated with ``zmart-coders.yml``). The blocks are
installed into it with pip, straight from GitHub, at the releases in
``releases.toml``.

They are installed in two rounds. Each block names the others it needs at an
address of its own, and pip refuses one package asked for at two addresses,
so first the blocks are installed at our releases without what they need, and
then everything they need besides each other is installed, as each block
declares it. ``pip check`` then says whether everything fits.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from pathlib import Path

from . import conda
from .releases import Releases

HERE = Path(__file__).resolve().parent
ENVIRONMENTS = HERE / "environments"

#: The name of the environment ZMART runs in.
NAME = "zmart"

#: Asked in the environment's own Python after the blocks are installed
#: without what they need: what the blocks need besides each other. Prints
#: one requirement per line.
WHAT_THE_BLOCKS_NEED = """
import sys
from importlib.metadata import distribution
from packaging.requirements import Requirement

asked = [Requirement(line) for line in sys.argv[1:]]
blocks = {one.name for one in asked}
needed = set()
for block in asked:
    for line in distribution(block.name).requires or []:
        one = Requirement(line)
        if one.name in blocks:
            continue
        if one.marker and not any(one.marker.evaluate({"extra": extra})
                                  for extra in sorted(block.extras) or [""]):
            continue
        one.marker = None
        needed.add(str(one))
print("\\n".join(sorted(needed)))
"""


def which_blocks(microscope: str) -> dict[str, str]:
    """The blocks a computer needs, with the extras of each.

    Every computer gets the controller, the viewer, the analysis engine and
    the interface. The drivers' package is needed only for a real microscope,
    with the extra of its make; the mock microscope comes with our workflow.
    """
    blocks = {"zmart-controller": "", "zmart-viewer": "", "zmart-analysis": "", "zmart-interface": ""}
    if microscope != "mock":
        blocks["zmart-drivers"] = microscope
    return blocks


def make_the_environment(shell, record, conda_exe: str, coder: bool) -> Path | None:
    """The ``zmart`` environment, made if it is not there, and its folder; None when it could not be made."""
    what = "the ZMART environment"
    found = conda.environments(shell, conda_exe)
    if NAME in found:
        record.worked(what, f"'{NAME}' is already on this computer, at {found[NAME]}, and is used")
    else:
        done = shell.run([conda_exe, "env", "create", "--file", ENVIRONMENTS / "zmart.yml"])
        found = conda.environments(shell, conda_exe)
        if not done.ok or NAME not in found:
            record.failed(what, "conda could not make it", "see what conda said in the log; the install "
                          "doctor knows the usual causes", done.shown, done.tail)
            return None
        record.worked(what, f"made '{NAME}' at {found[NAME]}")
    if coder:
        done = shell.run([conda_exe, "env", "update", "--name", NAME, "--file",
                          ENVIRONMENTS / "zmart-coders.yml"])
        if not done.ok:
            record.failed("JupyterLab, for the notebooks", "conda could not add it", "see the log",
                          done.shown, done.tail)
        else:
            record.worked("JupyterLab, for the notebooks", "added to the ZMART environment")
    return found[NAME]


def install_the_blocks(shell, record, prefix: Path, conda_exe: str, releases: Releases,
                       microscope: str) -> bool:
    """Install the blocks this computer needs, at our releases, and say whether they fit."""
    python = conda.python_of(prefix)
    env = conda.environment_for(prefix, conda_exe)
    wanted = which_blocks(microscope)
    addresses = [releases.address(block, extras) for block, extras in wanted.items()]
    shown = ", ".join(f"{block} {releases.refs[block]}" for block in wanted)

    done = shell.run([python, "-m", "pip", "install", "--upgrade", "pip", "packaging"], env=env)
    if not done.ok:
        record.failed("pip, in the ZMART environment", "pip could not update itself",
                      "check the internet connection; see the log", done.shown, done.tail)
        return False

    done = shell.run([python, "-m", "pip", "install", "--upgrade", "--no-deps", *addresses], env=env)
    if not done.ok:
        record.failed("the ZMART blocks", f"pip could not install them from GitHub ({shown})",
                      "check the internet connection and that these releases exist on "
                      f"github.com/{releases.github}; see the log", done.shown, done.tail)
        return False

    names = [f"{block}[{extras}]" if extras else block for block, extras in wanted.items()]
    asked = shell.run([python, "-c", WHAT_THE_BLOCKS_NEED, *names], env=env, timeout=120, quiet=True)
    needed = [line.strip() for line in asked.output.splitlines() if line.strip()] if asked.ok else []
    if not asked.ok:
        record.failed("the ZMART blocks", "could not read what the blocks need", "see the log",
                      asked.shown, asked.tail)
        return False
    if needed:
        done = shell.run([python, "-m", "pip", "install", "--upgrade", *needed], env=env)
        if not done.ok:
            record.failed("what the ZMART blocks need", "pip could not install it",
                          "see the log; a package that will not build is the usual cause",
                          done.shown, done.tail)
            return False
    record.worked("the ZMART blocks", f"installed from github.com/{releases.github}: {shown}")
    return True


def register_the_driver(shell, record, prefix: Path, conda_exe: str, microscope: str) -> bool:
    """Install the microscope's driver into the controller's registry, once on this computer."""
    if microscope == "mock":
        record.skipped("the microscope's driver", "the mock microscope comes with the workflow; no driver is needed")
        return True
    program = (
        "import pathlib, zmart_controller\n"
        "import zmart_drivers.leica.stellaris.navigator_expert as driver\n"
        "print(zmart_controller.register_driver(pathlib.Path(driver.__file__).parent))\n"
    )
    done = shell.run([conda.python_of(prefix), "-c", program],
                     env=conda.environment_for(prefix, conda_exe), timeout=300, quiet=True)
    if not done.ok:
        record.failed("the Leica driver", "it could not be installed into the controller",
                      "see the log; the driver's README says what it needs", done.shown, done.tail)
        return False
    record.worked("the Leica driver", f"installed into the controller as '{done.output.strip().splitlines()[-1]}'")
    return True
