"""Run the whole test suite with one command.

    python run_tests.py

That is all you need. It makes sure the test tools are installed and that the two
pages the tests open are built — the viewer itself, and the small page the three
ways of drawing are compared on — then runs every test. On a machine with a
graphics card the browser tests render through the real GPU; on one without,
those tests skip and the rest still run.

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

    numpy and zarr run the data-reading tests; pytest runs everything; playwright
    drives the browser tests (which skip on their own if it is not there); and
    pillow opens the screenshots those tests take, which is how we check that a
    picture was actually drawn rather than trusting the engine's own account of
    itself. We install whatever is missing so a fresh checkout just works.
    """
    # What to import to see whether it is there, and what to ask pip for if it is
    # not. Those are usually the same word, but not always: the imaging library is
    # imported as ``PIL`` and installed as ``pillow``, for historical reasons that
    # do not matter here beyond getting the name right.
    needed = {
        "pytest": "pytest",
        "numpy": "numpy",
        "zarr": "zarr",
        "playwright": "playwright",
        "PIL": "pillow",
    }
    missing = [
        package
        for module, package in needed.items()
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        print(f"Installing test tools: {', '.join(missing)} …", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *missing], check=True)
    if "playwright" in missing:
        # Fetch the browser Playwright drives. Harmless (and skipped) where a
        # policy blocks the download; the browser tests then simply skip.
        print("Fetching the browser for the render tests …", flush=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)


def _build_the_pages_the_tests_open() -> None:
    """Build the two pages the browser tests open, if they are not built already.

    There are two, and both are needed for a complete run. One is the viewer
    itself. The other is a much smaller page on which the three ways of drawing
    are compared, which twenty-six of the tests open instead — what they check is
    the promise each of those three makes to the page above it.

    Each is built only if it is missing, so a second run costs nothing.
    """
    viewer_built = (HERE / "frontend" / "dist" / "index.html").exists()
    options_built = (HERE / "options" / "harness" / "dist" / "index.html").exists()
    if viewer_built and options_built:
        return
    # On Windows npm is a command shim.  Passing bare ``npm`` to
    # subprocess.run() can resolve the extensionless POSIX shim from a Conda
    # environment, which CreateProcess cannot execute.  Select npm.cmd
    # explicitly there while retaining the normal executable on other hosts.
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not npm:
        print("Node/npm not found — the browser render tests will skip. "
              "Install Node.js to include them.", flush=True)
        return
    if not viewer_built:
        print("Building the viewer page (one time) …", flush=True)
        subprocess.run([npm, "--prefix", "frontend", "install"], cwd=HERE, check=True)
        subprocess.run([npm, "--prefix", "frontend", "run", "build"], cwd=HERE, check=True)
    if not options_built:
        # This page keeps no packages of its own. It borrows the viewer's, so that
        # the engine it measures is the one the viewer actually ships — which is
        # why it is built after the viewer and never before it.
        print("Building the page the drawing options are compared on …", flush=True)
        subprocess.run(
            [npm, "--prefix", "parked/harness", "run", "build"], cwd=HERE, check=True
        )


def _split_whole_files(extra_args: list[str]) -> list[str]:
    """Ask for whole files to be kept together when the tests run in parallel.

    Running with ``-n 3`` shares the tests out over three copies of Python at
    once, which is a large saving. By default it shares out one *test* at a time,
    and that undoes some of the saving here: several of these files set something
    up once for the whole file — a browser, a served volume — and a file split
    across three copies builds that setup three times. Keeping each file on one
    copy builds it once. It is worth tens of seconds.

    Only added when parallel running was actually asked for, and only when it has
    not been asked for already, so that ``python run_tests.py`` on a machine
    without the parallel-running plugin is unaffected.
    """
    asked_for_parallel = any(arg == "-n" or arg.startswith("-n") for arg in extra_args)
    already_chosen = any(arg.startswith("--dist") for arg in extra_args)
    if asked_for_parallel and not already_chosen:
        return [*extra_args, "--dist", "loadfile"]
    return extra_args


def main(extra_args: list[str]) -> int:
    _install_missing()
    _build_the_pages_the_tests_open()
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", *_split_whole_files(extra_args)],
        cwd=HERE,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
