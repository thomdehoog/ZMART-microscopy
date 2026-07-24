"""Run the whole test suite with one command.

    python run_tests.py

That is all you need. It makes sure the test tools are installed and the viewer
page is built, then runs every test. On a machine with a graphics card the
browser tests render through the real GPU; on one without, those tests skip and
the rest still run.

To also exercise a real acquisition, point it at an OME-Zarr store first:

    ZMART_TEST_STORE=/path/to/acquisition.ome.zarr python run_tests.py

Anything you add after the command is passed straight through to pytest, so you
can run just part of the suite while you work, for example::

    python run_tests.py -k omezarr        # only the OME-Zarr tests
    python run_tests.py -v                 # one line per test
    python run_tests.py -s -k gpu          # show the GPU renderer it found
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _install_missing() -> None:
    """Install any test tools that are not already present.

    numpy and zarr run the data-reading tests; pytest runs everything; and
    playwright drives the browser tests (which skip on their own if it is not
    there). We install whatever is missing so a fresh checkout just works.
    """
    needed = ["pytest", "numpy", "zarr", "playwright"]
    missing = [m for m in needed if importlib.util.find_spec(m) is None]
    if missing:
        print(f"Installing test tools: {', '.join(missing)} …", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *missing], check=True)
    if "playwright" in missing:
        # Fetch the browser Playwright drives. Harmless (and skipped) where a
        # policy blocks the download; the browser tests then simply skip.
        print("Fetching the browser for the render tests …", flush=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)


def _build_frontend() -> None:
    """Build the viewer page once, so the browser render tests can run."""
    if (HERE / "frontend" / "dist" / "index.html").exists():
        return
    if not shutil.which("npm"):
        print("Node/npm not found — the browser render tests will skip. "
              "Install Node.js to include them.", flush=True)
        return
    print("Building the viewer page (one time) …", flush=True)
    subprocess.run(["npm", "--prefix", "frontend", "install"], cwd=HERE, check=True)
    subprocess.run(["npm", "--prefix", "frontend", "run", "build"], cwd=HERE, check=True)


def main(extra_args: list[str]) -> int:
    _install_missing()
    _build_frontend()
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", *extra_args], cwd=HERE
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
