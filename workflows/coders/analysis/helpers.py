"""What the engine tests build their cases from: step files, pipelines, and waiting.

Every engine test writes a small step file and a pipeline into one temporary
folder for the whole session, registers the pipeline, and waits for the
engine to finish. These are the few functions that do that, kept in a
module of their own so a test can import them by name (``conftest.py`` is
pytest's and cannot be imported from a test under two folders at once).
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import textwrap
import time
from pathlib import Path

# --------------------------------------------------------------------------
# Session-wide temp dir
# --------------------------------------------------------------------------

_SESSION_TEMP = Path(tempfile.mkdtemp(prefix="zmart_analysis_tests_"))
atexit.register(shutil.rmtree, _SESSION_TEMP, True)
_counter = [0]


def _next_id():
    _counter[0] += 1
    return _counter[0]


# --------------------------------------------------------------------------
# Step / YAML factories
# --------------------------------------------------------------------------


#: The engine's own environment, as the engine names it. A test step runs there.
ENGINE_ENVIRONMENT = os.environ.get("CONDA_DEFAULT_ENV") or Path(sys.prefix).name
#: A METADATA that names it, to end a test step's code with.
ENGINE_METADATA = f'\nMETADATA = {{"environment": "{ENGINE_ENVIRONMENT}"}}\n'


def _write_step(code, name=None):
    """Write a step .py file to the session temp dir; return absolute path.

    A step must name its environment, so one that does not gets the
    engine's own, in the METADATA it has or in a new one at the end.
    """
    fname = f"{name}.py" if name else f"step_{_next_id()}.py"
    path = _SESSION_TEMP / fname
    code = textwrap.dedent(code)
    if '"environment"' not in code:
        if "METADATA = {" in code:
            code = code.replace(
                "METADATA = {", f'METADATA = {{"environment": "{ENGINE_ENVIRONMENT}", ', 1
            )
        else:
            code += ENGINE_METADATA
    path.write_text(code)
    return str(path)


def fresh_output():
    """A new, empty output place for one registration."""
    return str(_SESSION_TEMP / f"output_{_next_id()}")


def _write_yaml(content):
    """Write a pipeline YAML to the session temp dir; return absolute path.

    If the content does not declare ``functions_dir``, one pointing at the
    session temp dir is injected so steps written by ``_write_step`` resolve.
    """
    text = textwrap.dedent(content)
    if "functions_dir" not in text:
        functions_dir = _SESSION_TEMP.as_posix()
        header = f'metadata:\n  functions_dir: "{functions_dir}"\n'
        if "metadata:" in text:
            text = text.replace("metadata:", header.rstrip("\n"), 1)
        else:
            text = header + text
    path = _SESSION_TEMP / f"pipeline_{_next_id()}.yaml"
    path.write_text(text)
    return str(path)


# --------------------------------------------------------------------------
# Polling helpers
# --------------------------------------------------------------------------


FINISHED = ("done", "failed", "cancelled")


def outputs(board):
    """The outputs of the done jobs on a board, in job order."""
    return [board[job]["output"] for job in sorted(board) if board[job]["state"] == "done"]


def phase_of(output):
    """0 for an image job's output, 1, 2, ... for a scoped one."""
    return output["metadata"].get("phase", 0)


def tally(board):
    """How many jobs of a board are in each state."""
    counts = dict.fromkeys(("queued", "running", "waiting", "done", "failed", "cancelled"), 0)
    for entry in board.values():
        counts[entry["state"]] += 1
    return counts


def failures(board):
    """The failed entries of a board, in job order, each with its job id."""
    return [{"job": job, **board[job]} for job in sorted(board) if board[job]["state"] == "failed"]


def _wait_for_results(engine, name, expected, timeout=30):
    """Poll the board until *expected* jobs are done; return their outputs."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        done = outputs(engine.status(name))
        if len(done) >= expected:
            return done
        time.sleep(0.05)
    return outputs(engine.status(name))


def _wait_for_status(engine, name, expected_total, timeout=30):
    """Poll the board until *expected_total* jobs have finished; return it."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        board = engine.status(name)
        if sum(entry["state"] in FINISHED for entry in board.values()) >= expected_total:
            return board
        time.sleep(0.05)
    return engine.status(name)


def load_step(workflow, name):
    """One step file of a workflow, loaded by its path under a name of its own.

    Both workflows have a step called ``read_images``, so a plain ``import``
    would find whichever comes first on the search path. The module goes
    into ``sys.modules`` under that name before it runs, as the engine's
    worker does, because a dataclass looks its module up there while it
    is built.
    """
    import importlib.util

    path = Path(__file__).resolve().parent / workflow / "steps" / f"{name}.py"
    module_name = f"{workflow}_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module
