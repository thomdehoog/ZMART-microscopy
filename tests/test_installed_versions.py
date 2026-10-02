"""The five blocks installed together, from GitHub, without disagreeing.

Before asking whether the blocks plug into each other, these checks ask
whether they can stand in one environment at all: whether pip sees any
package asking for a version another package does not allow, whether each
block really came from its GitHub repository (and not from a folder on this
computer), and whether the clones in ``work/`` hold the same code as the
installed packages. They also write down the versions that were running, so a
failure elsewhere can be read against them.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution

import pytest

from conftest import BLOCKS, WORK, checkout, write_report

#: Packages beside the blocks whose versions decide whether two blocks read
#: each other's files the same way: the image arrays, the OME-Zarr format and
#: its reader, and the window.
KEY_PACKAGES = ["numpy", "zarr", "ngio", "tifffile", "scikit-image", "scipy", "pyyaml",
                "pywebview", "pytest"]


def _where_from(name: str) -> dict:
    """What pip wrote down about where *name* was installed from (PEP 610)."""
    text = distribution(name).read_text("direct_url.json")
    return json.loads(text) if text else {}


def _version(name: str) -> str | None:
    try:
        return distribution(name).version
    except PackageNotFoundError:
        return None


def test_pip_finds_no_package_in_conflict_with_another():
    """``pip check`` passes: every installed package's requirements are met.

    A conflict here means two blocks ask for versions of a shared package
    that cannot both be satisfied, and one of them is running on a version it
    was not made for.
    """
    done = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    write_report("pip-check", {"exit": done.returncode, "said": done.stdout + done.stderr})
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize("name", list(BLOCKS))
def test_each_block_was_installed_from_its_github_repository(name):
    """The block came from github.com/thomdehoog/<repository>, as a normal (not editable) install.

    An editable install, or one from a folder on this computer, would test
    whatever happens to be in that folder rather than what a new user gets.
    """
    where = _where_from(name)
    assert where, f"{name} has no record of where it came from; it was not installed from a URL"
    assert where.get("url", "").rstrip("/").endswith(f"github.com/thomdehoog/{BLOCKS[name]}"), where
    assert "vcs_info" in where, f"{name} was not installed from git: {where}"
    assert not where.get("dir_info", {}).get("editable"), f"{name} is an editable install"


@pytest.mark.parametrize("repository", ["ZMART-controller", "ZMART-analysis", "ZMART-interface"])
def test_each_clone_holds_the_same_code_as_the_installed_package(repository):
    """The clone in work/ is at the same commit as the package installed from the same repository.

    The clones supply what is not packaged (the mock driver, the analysis
    workflows, the browser walk). If a clone were newer or older than the
    installed package, a check could pass or fail on a mix of two versions.
    """
    name = next(n for n, r in BLOCKS.items() if r == repository)
    installed = _where_from(name).get("vcs_info", {}).get("commit_id")
    cloned = subprocess.run(["git", "-C", str(checkout(repository)), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    assert installed == cloned, (
        f"{repository}: the installed package is commit {installed}, the clone is {cloned}; "
        "run install.py again so both come from the same moment"
    )


def test_the_interface_accepts_the_installed_viewer():
    """The interface's own version check accepts the viewer that pip installed beside it.

    The interface refuses a viewer outside the versions it was tested with,
    and says so only when a run is connected. Asking here finds it before.
    """
    from zmart_interface.parts.storage import viewer_service

    provenance = viewer_service.viewer_provenance()
    viewer_service._the_viewers_make_server()
    assert provenance["version"] == _version("zmart-viewer")


def test_the_versions_are_written_down():
    """A record of Python, the blocks and the shared packages, in work/reports/versions.json.

    This is not a pass-or-fail question; it is the record a person needs when
    another check fails. The one firm requirement is zarr 3: the interface
    writes OME-Zarr 0.5 and the viewer reads it, and both need zarr 3.
    """
    blocks = {}
    for name in BLOCKS:
        where = _where_from(name)
        blocks[name] = {
            "version": _version(name),
            "commit": where.get("vcs_info", {}).get("commit_id"),
            "url": where.get("url"),
        }
    record = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "blocks": blocks,
        "packages": {name: _version(name) for name in KEY_PACKAGES},
        "work": str(WORK),
    }
    path = write_report("versions", record)
    print(json.dumps(record, indent=2))
    assert path.is_file()
    assert record["packages"]["zarr"].split(".")[0] == "3", record["packages"]["zarr"]
