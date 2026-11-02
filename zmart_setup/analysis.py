"""The analysis environments, made from the pipelines' own environment files, and checked.

Each analysis step runs in a conda environment of its own, which it names in
its file (``"environment": "ZMART--focus--main"``). The environments are made
from the files in each pipeline's ``environments/`` folder, in ZMART
Analysis's ``examples`` (the operator window's pipelines) and, for people who
write code, the notebook template's own (``for-coders/template``) too.

An environment that is already on the computer is used as it is and never
removed: removing one is its owner's decision, and the install doctor says
how. Each environment is then checked by loading, in that environment, every
step that names it: a step loads only when everything it imports is there.

Cellpose (the robust detection) is the one large environment, with PyTorch:
it is made only when asked for, and its check says whether it sees a GPU.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import conda

#: The name of the large environment that is made only when asked for.
CELLPOSE = "ZMART--object_analysis--cellpose"


@dataclass
class Environment:
    """One analysis environment: its name, the file it is made from, and the steps that run in it."""

    name: str
    file: Path
    steps: list[Path] = field(default_factory=list)


def environments_in(analysis: Path) -> dict[str, Environment]:
    """Every environment the pipelines in ``analysis`` describe, with the steps that name each."""
    found: dict[str, Environment] = {}
    for file in sorted(analysis.glob("*/environments/*.yml")):
        named = re.search(r"^name:\s*(\S+)", file.read_text(encoding="utf-8"), re.M)
        if named:
            found[named[1]] = Environment(named[1], file)
    for step in sorted(analysis.glob("*/steps/*.py")):
        named = re.search(r'"environment":\s*"([^"]+)"', step.read_text(encoding="utf-8"))
        if named and named[1] in found:
            found[named[1]].steps.append(step)
    return found


def wanted(folders: list[Path], cellpose: bool) -> dict[str, Environment]:
    """The environments to make for these folders of pipelines, the first folder's file winning a shared name."""
    out: dict[str, Environment] = {}
    for folder in folders:
        for name, one in environments_in(folder).items():
            if name == CELLPOSE and not cellpose:
                continue
            if name in out:
                out[name].steps += one.steps
            else:
                out[name] = one
    return out


#: Run in an analysis environment: load every step file named on the command
#: line, the way the engine's worker loads it, and say which could not load.
LOAD_THE_STEPS = """
import importlib.util, json, sys, traceback
from pathlib import Path
failed = {}
for number, path in enumerate(map(Path, sys.argv[1:])):
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(f"zmart_check_{number}_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    except Exception:
        failed[path.name] = traceback.format_exc(limit=3)
    finally:
        sys.path.pop(0)
gpu = None
try:
    import torch
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no GPU: Cellpose runs on the CPU"
except Exception:
    pass
print(json.dumps({"failed": failed, "gpu": gpu}))
"""


def make(shell, record, conda_exe: str, environments: dict[str, Environment]) -> None:
    """Make each analysis environment that is not on the computer yet."""
    existing = conda.environments(shell, conda_exe)
    for name, one in environments.items():
        what = f"the analysis environment {name}"
        if name in existing:
            record.worked(what, "already on this computer, and is used")
            continue
        done = shell.run([conda_exe, "env", "create", "--file", one.file.name], cwd=one.file.parent)
        if done.ok:
            record.worked(what, f"made from {one.file}")
        else:
            record.failed(what, "conda could not make it",
                          "see what conda said in the log; the install doctor knows the usual causes",
                          done.shown, done.tail)


def check(shell, record, conda_exe: str, environments: dict[str, Environment]) -> None:
    """Load every step in the environment it names, and say per environment whether all of them load."""
    import json

    existing = conda.environments(shell, conda_exe)
    for name, one in environments.items():
        what = f"the steps that run in {name}"
        if name not in existing:
            record.failed(what, "the environment is not on this computer",
                          f"make it with: conda env create -f {one.file}")
            continue
        python = conda.python_of(existing[name])
        done = shell.run([python, "-c", LOAD_THE_STEPS, *one.steps], timeout=600, quiet=True)
        try:
            said = json.loads(done.output.strip().splitlines()[-1])
        except (ValueError, IndexError):
            record.failed(what, "the check could not run in the environment",
                          "the environment may be broken; see the log", done.shown, done.tail)
            continue
        if said["failed"]:
            names = ", ".join(sorted(said["failed"]))
            record.failed(what, f"these steps do not load: {names}",
                          "a package in the environment is missing or broken; see the log",
                          done.shown, "\n".join(said["failed"].values()))
        else:
            found = f"{len(one.steps)} step(s) load"
            if said.get("gpu"):
                found += f"; PyTorch sees: {said['gpu']}"
            record.worked(what, found)
