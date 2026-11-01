"""The operator page we commit is the one the interface builds from our workflows.

The ZMART interface brings no workflow and no page of its own. It runs the
workflows in ``workflows/non-coders/interface/``, and serves the page built
from them, which is committed beside them in ``built-page/``, because a
microscope PC has no Node.js and cannot build it. That only holds if the
committed page is exactly what the build makes from the workflows as they are
now: a workflow changed without building the page again would put an old page
in front of the operator, with nothing to say so.

This builds the page afresh with the interface's checkout in ``work/`` (its
``npm ci`` is done by ``install.py``), into a folder of the check's own, and
compares it with the committed one, file by file. When the page differs,
build it again and commit it:

    cd work/ZMART-interface
    ZMART_INTERFACE_WORKFLOWS=<this repository>/workflows/non-coders/interface npm run build

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import INTERFACE_WORKFLOWS, checkout

#: The page committed beside our workflows.
OUR_PAGE = INTERFACE_WORKFLOWS / "built-page"


def _digest(folder: Path) -> dict[str, str]:
    """Every file under *folder*, by its path inside it, with its SHA-256."""
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def test_the_page_is_committed_beside_our_workflows():
    names = sorted(_digest(OUR_PAGE))
    assert "index.html" in names and len(names) == 3, names


def test_the_committed_page_is_what_the_build_makes_from_our_workflows(tmp_path):
    interface = checkout("ZMART-interface")
    if not (interface / "node_modules").is_dir():
        pytest.skip(f"{interface} has no node_modules; install.py runs npm ci there")
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if npm is None:
        pytest.skip("npm is not on the PATH of this environment")
    out = tmp_path / "built-page"
    done = subprocess.run(
        f'"{npm}" run build -- --outDir "{out}" --emptyOutDir',
        cwd=interface, shell=True, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
        env={**os.environ, "NO_COLOR": "1", "PYTHON": sys.executable,
             "ZMART_INTERFACE_WORKFLOWS": str(INTERFACE_WORKFLOWS)},
    )
    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-4000:]
    assert _digest(out) == _digest(OUR_PAGE), (
        "the committed page is not what the build makes from our workflows: build it again "
        "(see this file's description) and commit workflows/non-coders/interface/built-page"
    )
