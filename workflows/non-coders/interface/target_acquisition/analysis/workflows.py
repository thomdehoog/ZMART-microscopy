"""Where this workflow's analysis pipelines are, and how it reaches them.

In ZMART Microscopy this workflow brings its own pipelines: they are in
``workflows/non-coders/analysis``, beside the folder of interface workflows,
and that is where it looks first. They started as copies of ZMART-analysis's
example pipelines, and they belong to the operator window: the coders' path
has its own copy, in ``workflows/coders/analysis``, which may change on its
own. The rest of this text is the interface example's, which this workflow
started from.

ZMART-analysis is installed as a package (``zmart_analysis``: it starts each
analysis step in its own conda environment and keeps it warm), but the
pipelines it runs -- the YAML files and the step files -- are not part of the
package. They belong to the workflow that uses them. This is the example
workflow of the ZMART interface, so it uses ZMART-analysis's own example
pipelines, ``focus`` and ``object_analysis``, which live in the ``examples``
folder of a checkout of the ZMART-analysis repository. A workflow of your own
points here at the pipelines it brings with it (in ZMART Microscopy, the
``analysis`` folder beside the interface workflows).

It looks in two places, in order:

1. ``ZMART_ANALYSIS_WORKFLOWS``: a folder named in this environment variable,
   either the ZMART-analysis checkout itself, or the folder that holds the
   pipelines' folders (``examples``, or ``workflows`` in ZMART-analysis
   before 0.6.0rc8).
2. Beside the installed engine: when ZMART-analysis was installed from a
   checkout in editable mode (``pip install -e``), its ``examples`` folder
   stands next to the ``zmart_analysis`` package, and is found without being
   named.

If neither holds the workflows, :func:`workflows_root` says so in a sentence
that tells the operator what to set, rather than failing later with a missing
file in the middle of a focus map.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import importlib.util
import os
from functools import cache
from pathlib import Path
from types import ModuleType

#: This workflow's own pipelines, in ZMART Microscopy: ``workflows/non-coders/analysis``.
OUR_PIPELINES = Path(__file__).resolve().parents[3] / "analysis"

#: The environment variable naming the ZMART-analysis checkout, or the folder of pipelines itself.
ENV = "ZMART_ANALYSIS_WORKFLOWS"

#: The names the folder of pipelines has in a ZMART-analysis checkout: ``examples``
#: from 0.6.0rc8 on, ``workflows`` before it.
FOLDER_NAMES = ("examples", "workflows")


class WorkflowsNotFound(RuntimeError):
    """The ZMART-analysis workflows could not be found; the message says where to point."""


def _holds_workflows(folder: Path) -> bool:
    """Whether *folder* holds pipelines' folders: it has at least one pipeline in it."""
    return folder.is_dir() and any(folder.glob("*/pipelines/*.yaml"))


def workflows_root() -> Path:
    """The folder that holds this workflow's pipelines, or :class:`WorkflowsNotFound`."""
    named = os.environ.get(ENV, "").strip()
    if named:
        for candidate in (Path(named), *(Path(named) / name for name in FOLDER_NAMES)):
            if _holds_workflows(candidate):
                return candidate.resolve()
        raise WorkflowsNotFound(
            f"{ENV} points at {named}, which holds no analysis pipelines; point it at "
            "a checkout of github.com/ZMB-UZH/ZMART-analysis or at its examples folder"
        )
    if _holds_workflows(OUR_PIPELINES):
        return OUR_PIPELINES.resolve()
    spec = importlib.util.find_spec("zmart_analysis")
    if spec is not None and spec.origin:
        for name in FOLDER_NAMES:
            beside = Path(spec.origin).resolve().parent.parent / name
            if _holds_workflows(beside):
                return beside
    raise WorkflowsNotFound(
        "the analysis pipelines were not found. Focus maps and object detection "
        "run them, so clone github.com/ZMB-UZH/ZMART-analysis and either install it "
        f"from that folder with `pip install -e .`, or set {ENV} to that folder"
    )


def pipeline_yaml(name: str) -> Path:
    """Where a pipeline's YAML is, by its name, under whichever workflow has it.

    A pipeline's name does not say its workflow: ``focus`` lives in
    ``focus``, ``object_analysis_watershed`` in ``object_analysis``.
    """
    root = workflows_root()
    found = sorted(root.glob(f"*/pipelines/{name}.yaml"))
    if not found:
        raise FileNotFoundError(f"no workflow under {root} has a pipeline {name!r}")
    return found[0]


def step_file(workflow: str, step: str) -> Path:
    """Where one step of a workflow is: ``<workflows>/<workflow>/steps/<step>.py``."""
    path = workflows_root() / workflow / "steps" / f"{step}.py"
    if not path.is_file():
        raise FileNotFoundError(f"the {workflow} workflow has no step {step!r} at {path}")
    return path


@cache
def step_module(workflow: str, step: str) -> ModuleType:
    """One step of a workflow, loaded from its file, the way the engine's worker loads it.

    For using a step's code in this process: the previews read a position
    with ``load_plane`` from object_analysis's ``read_images``, the reader
    detection uses, so the two can never read a stack differently. A step
    file finds the other steps of its workflow by itself.
    """
    path = step_file(workflow, step)
    spec = importlib.util.spec_from_file_location(f"zmart_analysis_step_{workflow}_{step}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

