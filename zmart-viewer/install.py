"""Set this viewer up, in one command.

    python install.py

That is the whole of it. It installs what Python needs, installs and builds
the page, and then tells you the command that opens a folder of data.

Before this existed, setting the viewer up meant: clone, make a virtual
environment, copy ``node_modules`` from somewhere, run two builds, and set
``PYTHONPATH`` by hand -- a developer's checkout rather than something to hand
a colleague. Every one of those steps is still happening; they are just
happening here instead of in somebody's head.

Options, for the two machines that need them:

    --no-page      skip the page build (Python-only checkout, no browser work)
    --dev          also install the test tools
    --browsers     also fetch the browser the picture tests drive

Site settings, read from the environment when they are set, because a lab
machine's rules are not this script's business:

    ZMART_NPM        the npm to use, when it is not on the path
    NPM_CONFIG_CACHE where npm may keep its cache, when the profile is small
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE / "app" / "page"


def say(what: str) -> None:
    print(f"\n== {what}", flush=True)


def run(command: list[str], where: Path) -> None:
    """Run a step, and stop plainly on the first one that fails.

    Plainly on purpose: a setup script that carries on after a failed step
    hands back something half-built and calls it success, which is worse than
    stopping, because the failure then shows up as a mystery much later.
    """
    printed = " ".join(str(part) for part in command)
    print(f"   {printed}", flush=True)
    finished = subprocess.run(command, cwd=where)
    if finished.returncode != 0:
        raise SystemExit(
            f"\nthat step failed ({finished.returncode}).\n"
            f"    {printed}\n"
            f"    in {where}\n"
        )


def the_npm() -> str | None:
    """Whichever npm this machine has, or None if it has none.

    ``ZMART_NPM`` first, because on a managed machine node often lives inside
    a project environment rather than on the path, and guessing wrong there
    wastes more time than asking.
    """
    told = os.environ.get("ZMART_NPM", "").strip()
    if told:
        return told
    return shutil.which("npm")


def main() -> int:
    asked = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    asked.add_argument("--no-page", action="store_true",
                       help="skip installing and building the page")
    asked.add_argument("--dev", action="store_true",
                       help="also install the tools the tests need")
    asked.add_argument("--browsers", action="store_true",
                       help="also fetch the browser the picture tests drive")
    given = asked.parse_args()

    if sys.version_info < (3, 10):
        raise SystemExit(f"this needs Python 3.10 or newer; this is "
                         f"{sys.version_info.major}.{sys.version_info.minor}")

    say("what Python needs")
    what = ".[dev]" if given.dev else "."
    run([sys.executable, "-m", "pip", "install", "-e", what], HERE)

    if not given.no_page:
        npm = the_npm()
        if npm is None:
            print("\n   no npm found, so the page was not built. Install Node,"
                  "\n   or set ZMART_NPM to it, then run this again."
                  "\n   Everything Python needs is installed either way.")
        else:
            say("the page")
            run([npm, "install", "--no-audit"], PAGE)
            run([npm, "run", "build"], PAGE)

    if given.browsers:
        say("the browser the picture tests drive")
        run([sys.executable, "-m", "playwright", "install", "chromium"], HERE)

    built = (PAGE / "dist" / "index.html").exists()
    say("done")
    print(f"   the page is {'built' if built else 'NOT built'}")
    print()
    print("   Open a folder of data:")
    print(f"       {Path(sys.executable).name} demos/run_demo.py --data <folder>")
    print()
    print("   Or watch the demo spiral assemble itself:")
    print(f"       {Path(sys.executable).name} demos/show_thy1_one_source.py --help")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
