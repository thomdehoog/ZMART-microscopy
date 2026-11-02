"""The environments ZMART runs in, the blocks installed into them, and the two clones.

The operator window's environment (``zmart-for-non-coders``) is made from
``workflows/target_acquisition/for-non-coders/environment.yml``; for people
who write code, the notebook's (``zmart-for-coders``) from
``for-coders/template/environment.yml`` too. The blocks are installed into
them with pip, straight from GitHub, at the releases in ``releases.toml``.

They are installed in two rounds. Each block names the others it needs at an
address of its own, and pip refuses one package asked for at two addresses,
so first the blocks are installed at our releases without what they need, and
then everything they need besides each other is installed, as each block
declares it. ``pip check`` then says whether everything fits.

The interface's steps and the analysis pipelines are not installed as
packages: they are cloned, at the same releases, next to ZMART Microscopy.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from pathlib import Path

from . import conda
from .layout import CODER, OPERATOR, Clone, Environment
from .releases import BLOCKS, Releases

#: The name of the operator window's environment, the one the start file runs.
NAME = OPERATOR.name

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


def which_blocks(microscope: str, environment: Environment = OPERATOR) -> dict[str, str]:
    """The blocks an environment needs, with the extras of each.

    The drivers' package is needed only for a real microscope, with the extra
    of its make; the mock microscope comes with the interface's workflow.
    """
    blocks = {block: "" for block in environment.blocks}
    if microscope != "mock":
        blocks["zmart-drivers"] = microscope
    return blocks


def make_the_environment(shell, record, conda_exe: str, environment: Environment = OPERATOR) -> Path | None:
    """The environment, made from its file if it is not there, and its folder; None when it could not be made."""
    what = f"the environment {environment.name}"
    found = conda.environments(shell, conda_exe)
    if environment.name in found:
        record.worked(what, f"already on this computer, at {found[environment.name]}, and is used")
        return found[environment.name]
    done = shell.run([conda_exe, "env", "create", "--file", environment.file])
    found = conda.environments(shell, conda_exe)
    if not done.ok or environment.name not in found:
        record.failed(what, "conda could not make it", "see what conda said in the log; the install "
                      "doctor knows the usual causes", done.shown, done.tail)
        return None
    record.worked(what, f"made at {found[environment.name]}")
    return found[environment.name]


def install_the_blocks(shell, record, prefix: Path, conda_exe: str, releases: Releases,
                       microscope: str, environment: Environment = OPERATOR) -> bool:
    """Install the blocks the environment needs, at our releases, and say whether they fit."""
    python = conda.python_of(prefix)
    env = conda.environment_for(prefix, conda_exe)
    wanted = which_blocks(microscope, environment)
    addresses = [releases.address(block, extras) for block, extras in wanted.items()]
    shown = ", ".join(f"{block} {releases.refs[block]}" for block in wanted)
    what = f"the ZMART blocks, in {environment.name}"

    done = shell.run([python, "-m", "pip", "install", "--upgrade", "pip", "packaging"], env=env)
    if not done.ok:
        record.failed(f"pip, in {environment.name}", "pip could not update itself",
                      "check the internet connection; see the log", done.shown, done.tail)
        return False

    done = shell.run([python, "-m", "pip", "install", "--upgrade", "--no-deps", *addresses], env=env)
    if not done.ok:
        record.failed(what, f"pip could not install them from GitHub ({shown})",
                      "check the internet connection and that these releases exist on "
                      f"github.com/{releases.github}; see the log", done.shown, done.tail)
        return False

    names = [f"{block}[{extras}]" if extras else block for block, extras in wanted.items()]
    asked = shell.run([python, "-c", WHAT_THE_BLOCKS_NEED, *names], env=env, timeout=120, quiet=True)
    needed = [line.strip() for line in asked.output.splitlines() if line.strip()] if asked.ok else []
    if not asked.ok:
        record.failed(what, "could not read what the blocks need", "see the log", asked.shown, asked.tail)
        return False
    if needed:
        done = shell.run([python, "-m", "pip", "install", "--upgrade", *needed], env=env)
        if not done.ok:
            record.failed(f"what the ZMART blocks need, in {environment.name}", "pip could not install it",
                          "see the log; a package that will not build is the usual cause",
                          done.shown, done.tail)
            return False
    record.worked(what, f"installed from github.com/{releases.github}: {shown}")
    return True


def clone(shell, record, prefix: Path, conda_exe: str, releases: Releases, one: Clone) -> bool:
    """Clone a block's repository next to ZMART Microscopy, at its release, unless it is there already."""
    what = f"{BLOCKS[one.block]}, next to ZMART Microscopy"
    ref = releases.refs[one.block]
    if one.folder.exists():
        record.worked(what, f"{one.folder} is already there and is kept")
        return True
    done = shell.run(["git", "clone", "--branch", ref, "--depth", "1",
                      f"https://github.com/{releases.github}/{BLOCKS[one.block]}", one.folder],
                     env=conda.environment_for(prefix, conda_exe))
    if not done.ok:
        record.failed(what, f"git could not clone it at {ref}", "check the internet connection and that "
                      f"{ref} exists on github.com/{releases.github}; see the log", done.shown, done.tail)
        return False
    record.worked(what, f"cloned at {ref} into {one.folder}")
    return True


def register_the_driver(shell, record, prefix: Path, conda_exe: str, microscope: str,
                        environment: Environment = OPERATOR) -> bool:
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
    what = f"the Leica driver, from {environment.name}"
    if not done.ok:
        record.failed(what, "it could not be installed into the controller",
                      "see the log; the driver's README says what it needs", done.shown, done.tail)
        return False
    record.worked(what, f"installed into the controller as '{done.output.strip().splitlines()[-1]}'")
    return True
