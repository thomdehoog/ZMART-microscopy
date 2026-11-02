"""The checks: from "is it installed" to "does it work, end to end".

Each check runs a short program in the ZMART environment's own Python, the one
the start files use, and says plainly whether it worked:

1. **The blocks** are installed at the releases this copy of ZMART Microscopy
   names, and ``pip check`` finds nothing that does not fit.
2. **The operator window** finds our workflows and the page built from them.
3. **The operator window's background program** (the bridge) starts, hands out
   the page, and lists the microscopes, the mock among them. This is the
   program the start file opens the window on.
4. **The analysis environments**: every step loads in the environment it
   names (``analysis.check``).
5. **The analysis, end to end**: the engine scores a small z-stack, made up
   here with one sharp plane at 108 µm, through our focus pipeline, and must
   find that plane. Once with the operators' pipelines, and once with the
   coders' when they were installed.
6. **The microscope's driver** is listed by the controller.
7. **JupyterLab**, for people who write code.

``setup_zmart.py --check`` runs these again on their own, without installing
anything.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

from . import conda
from .blocks import which_blocks
from .layout import CODER, CODERS, OPERATOR, clones
from .releases import Releases

#: Answers the installed version of each block named on the command line, as JSON.
VERSIONS = """
import json, sys
from importlib.metadata import PackageNotFoundError, version
out = {}
for name in sys.argv[1:]:
    try:
        out[name] = version(name)
    except PackageNotFoundError:
        out[name] = None
print(json.dumps(out))
"""

#: Whether the interface finds our workflows, and the page built from them.
THE_WORKFLOWS = """
import json
from zmart_interface.framework.bridge import workflows
page = workflows.the_page()
print(json.dumps({"folder": str(workflows.WORKFLOWS), "halves": workflows.halves(),
                  "page": (page / "index.html").is_file()}))
"""

#: Start the bridge, ask it for the page and the microscopes, and stop it.
THE_BRIDGE = """
import json, subprocess, sys, tempfile, time, urllib.request
port = int(sys.argv[1])
runs = tempfile.mkdtemp(prefix="zmart-check-")
bridge = subprocess.Popen([sys.executable, "-m", "zmart_interface.framework.bridge",
                           "--port", str(port), "--output-root", runs])
at = f"http://127.0.0.1:{port}"
try:
    deadline = time.monotonic() + 90
    while True:
        try:
            page = urllib.request.urlopen(at + "/", timeout=5).read()
            break
        except OSError:
            if bridge.poll() is not None or time.monotonic() > deadline:
                raise SystemExit("the bridge did not start answering")
            time.sleep(0.5)
    listed = json.loads(urllib.request.urlopen(at + "/api/target_acquisition/instruments", timeout=30).read())
    print(json.dumps({"page_bytes": len(page), "listed": listed}))
finally:
    bridge.terminate()
    try:
        bridge.wait(timeout=20)
    except subprocess.TimeoutExpired:
        bridge.kill()
"""

#: Score a made-up z-stack with one sharp plane through a focus pipeline, and say where it found focus.
THE_FOCUS = """
import json, sys, tempfile, time
from pathlib import Path
import numpy as np, tifffile
from zmart_analysis import Engine
pipeline = sys.argv[1]
heights = [100.0 + 2.0 * z for z in range(9)]
sharp = 4
stack = np.stack([np.random.default_rng(0).integers(0, 4096, size=(64, 64)).astype(np.uint16)
                  if z == sharp else np.full((64, 64), 100, dtype=np.uint16) for z in range(9)])
folder = Path(tempfile.mkdtemp(prefix="zmart-check-focus-"))
tifffile.imwrite(folder / "stack.tiff", stack, metadata={"axes": "ZYX"})
engine = Engine()
try:
    engine.register("focus", pipeline, str(folder))
    job = engine.submit(pipeline="focus", data={"image_path": str(folder / "stack.tiff"), "z_um": heights})
    deadline = time.monotonic() + 600
    entry = engine.status("focus")[job]
    while entry["state"] not in ("done", "failed") and time.monotonic() < deadline:
        time.sleep(0.5)
        entry = engine.status("focus")[job]
finally:
    engine.shutdown()
found = (entry.get("output") or {}).get("score_focus", {}).get("peak_z_um")
print(json.dumps({"state": entry["state"], "peak_z_um": found, "expected": heights[sharp],
                  "error": entry.get("error")}, default=str))
"""

#: The microscopes the controller lists on this computer.
THE_INSTRUMENTS = """
import json, zmart_controller
print(json.dumps(sorted(zmart_controller.get_instruments())))
"""


def _last_json(text: str):
    """The JSON a check printed on its last line, or None."""
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run_all(shell, record, *, operator: Path, coder: Path | None, conda_exe: str, releases: Releases,
            microscope: str, analysis_environments: dict) -> None:
    """Every check, in order; each says for itself whether it worked.

    ``operator`` and ``coder`` are the folders of the two environments; the
    coder's checks run only when there is a coder's environment.
    """
    from . import analysis

    places = clones()
    variables = {"ZMART_INTERFACE_WORKFLOWS": str(places["interface"].workflows),
                 "ZMART_ANALYSIS_WORKFLOWS": str(places["analysis"].workflows)}

    def runner(prefix: Path):
        env = conda.environment_for(prefix, conda_exe, variables)

        def run(program: str, *args, timeout: float = 300):
            return shell.run([conda.python_of(prefix), "-c", program, *args], env=env, timeout=timeout,
                             quiet=True)
        return run, env

    run, env = runner(operator)

    # 1. The blocks, at our releases, fitting together, in each environment.
    for environment, prefix in ((OPERATOR, operator), (CODER, coder)):
        if prefix is None:
            continue
        in_it, its_env = runner(prefix)
        wanted = which_blocks(microscope, environment)
        done = in_it(VERSIONS, *wanted)
        installed = _last_json(done.output) or {}
        wrong = []
        for block in wanted:
            expected = releases.version(block)
            if installed.get(block) is None:
                wrong.append(f"{block} is not installed")
            elif expected and installed[block] != expected:
                wrong.append(f"{block} is {installed[block]}, not {expected}")
        what = f"the ZMART blocks in {environment.name}, at our releases"
        if wrong:
            record.failed(what, "; ".join(wrong), "run setup_zmart.py again; if it stays, see the log",
                          done.shown, done.tail)
        else:
            record.worked(what, ", ".join(f"{block} {installed[block]}" for block in wanted))
        done = shell.run([conda.python_of(prefix), "-m", "pip", "check"], env=its_env, timeout=120, quiet=True)
        what = f"the blocks fit together in {environment.name} (pip check)"
        if done.ok:
            record.worked(what, "nothing is missing or at a wrong version")
        else:
            record.failed(what, "pip found packages that do not fit", "see what pip check said in the log",
                          done.shown, done.tail)

    # 2. Our workflows, and their page.
    done = run(THE_WORKFLOWS)
    said = _last_json(done.output)
    if said and said["page"] and "target_acquisition" in said["halves"]:
        record.worked("the operator window finds our workflows", f"{', '.join(said['halves'])}, with the page built from them")
    else:
        record.failed("the operator window finds our workflows",
                      "it does not find Target acquisition or its page" if said else "the check could not run",
                      f"check that {places['interface'].workflows / 'built-page'} is there",
                      done.shown, done.tail)

    # 3. The bridge starts, hands out the page and lists the microscopes.
    done = run(THE_BRIDGE, str(_free_port()), timeout=180)
    said = _last_json(done.output)
    if said and said["page_bytes"] > 100_000 and "interface-mock" in json.dumps(said["listed"]):
        record.worked("the operator window's background program starts",
                      "it hands out the page and lists the microscopes, the mock among them")
    else:
        record.failed("the operator window's background program starts",
                      "it did not start, or did not answer as it should",
                      "see what it said in the log", done.shown, done.tail)

    # 4. Every analysis step loads in its environment.
    analysis.check(shell, record, conda_exe, analysis_environments)

    # 5. The analysis, end to end, on each path's own pipelines, in its own environment.
    paths = [("the operators' focus pipeline", places["analysis"].workflows, run)]
    if coder is not None:
        paths.append(("the coders' focus pipeline", CODERS, runner(coder)[0]))
    for what, folder, in_it in paths:
        pipeline = folder / "focus" / "pipelines" / "focus.yaml"
        done = in_it(THE_FOCUS, pipeline, timeout=900)
        said = _last_json(done.output)
        if said and said["state"] == "done" and said["peak_z_um"] == said["expected"]:
            record.worked(f"{what} finds focus, end to end", f"the sharp plane at {said['peak_z_um']} µm, as made")
        else:
            found = (f"it ended {said['state']}, finding {said['peak_z_um']} instead of {said['expected']}"
                     if said else "the check could not run")
            record.failed(f"{what} finds focus, end to end", found,
                          "check that ZMART--focus--main was made (above); see the log",
                          done.shown, done.tail if not said else json.dumps(said, indent=2))

    # 6. The driver.
    if microscope != "mock":
        done = run(THE_INSTRUMENTS)
        listed = _last_json(done.output) or []
        if any("leica" in name.lower() or "stellaris" in name.lower() for name in listed):
            record.worked("the controller lists the Leica", ", ".join(listed))
        else:
            record.failed("the controller lists the Leica", f"it lists: {', '.join(listed) or 'nothing'}",
                          "run setup_zmart.py again; see the log", done.shown, done.tail)

    # 7. JupyterLab.
    if coder is not None:
        done = runner(coder)[0]("import jupyterlab, json; print(json.dumps(jupyterlab.__version__))")
        if done.ok:
            record.worked("JupyterLab, for the notebook", f"version {_last_json(done.output)}")
        else:
            record.failed("JupyterLab, for the notebook", f"it is not installed in {CODER.name}",
                          "run setup_zmart.py again and answer that you write code", done.shown, done.tail)
