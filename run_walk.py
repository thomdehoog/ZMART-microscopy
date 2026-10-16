"""Walk the operator window end to end, on the mock microscope, against the installed blocks.

Run it with the Python of the ``zmart-integration`` environment, after ``install.py``:

    python run_walk.py [--output FOLDER]

The walk is the interface's own acceptance test,
``zmart_interface/workflows/target_acquisition/walk.spec.js``: Playwright
opens the operator page in Chromium and presses through all ten steps (connect,
carrier, overview plan, focus map, overview scan, detection, gating, target
areas, target acquisition, and the protocol) on the interface's mock
microscope, through the real bridge, with the focus map and the detection run
by ZMART-analysis in their own environments.

The test itself lives in the interface's clone in ``work/``, but everything it
starts must be the *installed* blocks, because that is what this repository
checks. So the walk is told:

- ``PYTHON``: this environment's Python, which the walk starts the bridge
  with (otherwise it would take whichever ``python`` is first on the PATH);
- ``ZMART_ANALYSIS_WORKFLOWS``: where the analysis workflows are cloned;
- ``ZMART_MICROSCOPY_ROOT``: an empty configuration folder of the walk's own,
  so drivers remembered on this computer neither appear nor change;
- ``ZMART_TEST_OUTPUT`` and ``OPERATOR_EVIDENCE_DIR``: where Playwright keeps
  its traces and where a screenshot of every screen goes, both in the output
  folder.

Before it starts, it asks the walk itself how it will start the bridge, and
runs that Python, in that folder, with those options, to see where it finds
``zmart_interface``. The walk starts it inside the interface's clone, with
``-P`` so that the clone's own ``zmart_interface`` folder does not stand in
front of the installed package. If the answer is the clone, the walk would
test the clone's code rather than the installed block, and it is not started.

Everything the walk printed is kept in ``walk.log`` in the output folder.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("ZMART_INTEGRATION_WORK", HERE / "work")).resolve()
WALK = "zmart_interface/workflows/target_acquisition/walk.spec.js"
WINDOWS = platform.system() == "Windows"


def this_environments_programs() -> list[str]:
    """The folders where this environment keeps node, npx and git."""
    prefix = Path(sys.prefix)
    if WINDOWS:
        return [str(prefix), str(prefix / "Library" / "bin"), str(prefix / "Scripts")]
    return [str(prefix / "bin")]


#: Ask the walk how it starts the bridge's Python, then start that Python the
#: same way and print where it found the interface. Run by Node.js, because the
#: walk's own JavaScript decides the command, its options and its folder.
ASK_THE_WALK = """
import { pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";
const walk = await import(pathToFileURL(process.argv[1]).href);
const python = walk.bridgePython("-c", "import zmart_interface; print(zmart_interface.__file__)");
const said = execFileSync(python.command, python.args, { cwd: python.cwd, encoding: "utf8" });
console.log(JSON.stringify({ ...python, imported: said.trim() }));
"""

#: The walk's file that starts the bridge (and holds ``bridgePython``).
LIVE_BRIDGE = "zmart_interface/workflows/target_acquisition/steps/scan_the_overview/live-bridge.js"


def where_the_walks_bridge_finds_the_interface(interface: Path, env: dict) -> dict:
    """Start Python exactly as the walk starts its bridge, and say where it imported the interface from.

    Returns the command, its options, the folder it ran in, and ``imported``,
    the path of the ``zmart_interface`` it found. Needs the walk's Node.js
    tools (``npm ci`` in the clone), because the walk's file imports Playwright.
    """
    done = subprocess.run(
        ["node", "--input-type=module", "-e", ASK_THE_WALK, str(interface / LIVE_BRIDGE)],
        cwd=interface, env=env, capture_output=True, text=True,
    )
    if done.returncode != 0:
        raise RuntimeError("could not ask the walk how it starts the bridge:\n"
                           + done.stderr[-4000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


def walk_environment(output: Path) -> dict:
    """The environment variables the walk runs with (see this file's description)."""
    configuration = output / "zmart-configuration"
    configuration.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "PATH": os.pathsep.join([*this_environments_programs(), os.environ.get("PATH", "")]),
        "PYTHON": sys.executable,
        "ZMART_ANALYSIS_WORKFLOWS": str(WORK / "ZMART-analysis"),
        "ZMART_MICROSCOPY_ROOT": str(configuration),
        "ZMART_TEST_OUTPUT": str(output / "test-results"),
        "OPERATOR_EVIDENCE_DIR": str(output / "screens"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path,
                        default=WORK / "walk" / time.strftime("%Y-%m-%dT%H-%M-%S"))
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    interface = WORK / "ZMART-interface"
    if not (interface / "node_modules").is_dir():
        sys.exit(f"{interface} has no node_modules; run install.py first")

    env = walk_environment(output)
    bridge = where_the_walks_bridge_finds_the_interface(interface, env)
    started = {
        "python": sys.executable,
        "bridge_started_as": [bridge["command"], *bridge["args"][:1]],
        "bridge_folder": bridge["cwd"],
        "interface_imported_from": bridge["imported"],
        "walk": str(interface / WALK),
        "output": str(output),
    }
    print(json.dumps(started, indent=2), flush=True)
    if interface.resolve() in Path(bridge["imported"]).resolve().parents:
        sys.exit("the walk's bridge would run the clone's interface, not the installed one; stopping")

    npx = "npx.cmd" if WINDOWS else "npx"
    began = time.monotonic()
    with (output / "walk.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [npx, "playwright", "test", WALK], cwd=interface, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace",
        )
        for line in process.stdout:
            sys.stdout.write(line)
            log.write(line)
        code = process.wait()
    finished = {**started, "exit": code, "seconds": round(time.monotonic() - began)}
    (output / "walk-result.json").write_text(json.dumps(finished, indent=2), encoding="utf-8")
    print(json.dumps(finished, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
