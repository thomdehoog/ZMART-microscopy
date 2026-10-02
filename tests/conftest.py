"""What every plug-in check shares: where the clones are, and a clean computer.

The checks run in the ``zmart-integration`` environment that ``install.py``
made, with the five blocks installed from GitHub. Three repositories are also
cloned into ``work/`` for the parts that are not installed as packages (the
controller's mock driver, the analysis workflows, the interface's walk);
``ZMART_INTEGRATION_WORK`` points somewhere else when they live elsewhere.

Two things keep the checks honest:

- **A clean configuration folder.** The controller remembers drivers in a
  folder shared by the whole computer. Every check gets an empty one of its
  own (``ZMART_MICROSCOPY_ROOT``), so it neither sees what was set up on this
  computer before nor leaves anything behind.
- **A fresh Python for each plug-in.** Plugging a driver in imports it, and an
  import cannot be undone. Most checks therefore start a new Python, in a
  folder of its own, as an operator's session would.

What the checks learn about the installed versions is written to
``work/reports/``, so a failure can be read next to what was running.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("ZMART_INTEGRATION_WORK", REPO / "work")).resolve()
REPORTS = WORK / "reports"

#: The five blocks, by the name pip knows them, and the repository each comes from.
BLOCKS = {
    "zmart-controller": "ZMART-controller",
    "zmart-drivers": "ZMART-drivers",
    "zmart-viewer": "ZMART-viewer",
    "zmart-analysis": "ZMART-analysis",
    "zmart-interface": "ZMART-interface",
}


#: The three keys an instrument is known by. Two drivers never share all three.
IDENTITY = ("vendor", "microscope", "api")

#: The interface's mock microscope, a section of a mouse kidney: the one the
#: operator window offers as "Mock" and the walk drives.
KIDNEY_MOCK = ("mock", "kidney-mock", "zmart-interface")

#: The controller's mock microscope, a slide of beads, kept with its tests.
BEADS_MOCK = ("mock", "mock-scope", "mock-api")


def identity_of(entry: dict) -> tuple:
    """An instrument's whole name, the way the controller tells instruments apart."""
    return tuple(entry[key] for key in IDENTITY)


def checkout(name: str) -> Path:
    """A repository cloned into work/ by install.py, or a failure that says so."""
    folder = WORK / name
    if not (folder / ".git").exists():
        pytest.fail(f"{folder} is not there; run install.py first, which clones it")
    return folder


def write_report(name: str, content: dict) -> Path:
    """Keep what a check learned, as JSON in work/reports/, for the person reading a failure."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{name}.json"
    path.write_text(json.dumps(content, indent=2, default=str), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def a_clean_configuration_folder(tmp_path, monkeypatch):
    """An empty ZMART configuration folder, for this check alone."""
    folder = tmp_path / "zmart-configuration"
    folder.mkdir()
    monkeypatch.setenv("ZMART_MICROSCOPY_ROOT", str(folder))
    return folder


@pytest.fixture
def fresh_python(tmp_path):
    """Run a short program in a new Python of this environment, and return what it printed as JSON.

    The program runs in an empty folder, so nothing in a repository's working
    folder can stand in for an installed package. Its last line of output must
    be JSON; everything it printed is shown when it fails.
    """
    where = tmp_path / "fresh"
    where.mkdir(exist_ok=True)

    def run(program: str, *args: str, env: dict | None = None, timeout: float = 300) -> dict:
        done = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(program), *args],
            cwd=where, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, **(env or {})},
        )
        if done.returncode != 0:
            pytest.fail(
                f"the program failed (exit {done.returncode}).\n"
                f"--- output ---\n{done.stdout[-4000:]}\n--- errors ---\n{done.stderr[-6000:]}"
            )
        lines = [line for line in done.stdout.splitlines() if line.strip()]
        try:
            return json.loads(lines[-1])
        except (IndexError, ValueError):
            pytest.fail(f"the program printed no JSON at the end:\n{done.stdout[-4000:]}\n"
                        f"{done.stderr[-4000:]}")

    return run
