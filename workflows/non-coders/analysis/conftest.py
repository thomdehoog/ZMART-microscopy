"""Shared pytest set-up for the tests of the non-coders' analysis pipelines.

These pipelines started as copies of ZMART-analysis's example workflows, and
their tests came with them. This file is the part of ZMART-analysis's own
test set-up those tests use: it puts this folder (for ``helpers.py``) and every
pipeline's ``steps`` folder on Python's search path, so a test can simply
``import score_focus``, and it offers the engine fixtures and the Cellpose
probe the object_analysis tests skip on. Both pipelines have a
``read_images`` step: tests load it with
``helpers.load_step(workflow, "read_images")``. The markers are declared in
``pytest.ini`` beside this file.

Run the tests from this folder: ``python -m pytest``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
for folder in (ROOT, *sorted(ROOT.glob("*/steps"))):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from helpers import _wait_for_results, _wait_for_status  # noqa: E402

# --------------------------------------------------------------------------
# Engine fixture
# --------------------------------------------------------------------------


@pytest.fixture
def engine_factory():
    """Returns a callable that builds an Engine and ensures shutdown.

    Usage::

        def test_something(engine_factory):
            with engine_factory() as e:
                e.register("test", yaml_path)
                ...

    The factory accepts the same kwargs as ``engine.Engine``.
    """
    from zmart_analysis import Engine

    created = []

    def _make(**kwargs):
        e = Engine(**kwargs)
        created.append(e)
        return e

    yield _make

    for e in created:
        try:
            e.shutdown()
        except Exception:
            pass


@pytest.fixture
def wait_for_results():
    """``wait_for_results(engine, name, expected, timeout=30)``: poll the
    board until *expected* jobs of *name* are done, and return their outputs."""
    return _wait_for_results


@pytest.fixture
def wait_for_status():
    """``wait_for_status(engine, name, expected_total, timeout=30)``: poll
    until that many jobs of *name* have finished; return the board."""
    return _wait_for_status


# --------------------------------------------------------------------------
# Skip helpers
# --------------------------------------------------------------------------


#: The environment the Cellpose step runs in (``environment`` in
#: ``segment_cellpose.py``). The tests run Cellpose through the engine, so the
#: probe looks there, not in the Python that runs pytest.
CELLPOSE_ENVIRONMENT = "ZMART--object_analysis--cellpose"

_CELLPOSE_RUNTIME_CACHE: tuple[bool, str] | None = None


def _has_cellpose_runtime() -> tuple[bool, str]:
    """Return (available, detail) for Cellpose in its own environment.

    When available, ``detail`` is the device that environment's torch sees,
    ``"cuda"`` or ``"cpu"``, so a test can check that a GPU which is there
    was really used. Otherwise it says why, in a way that tells the reader
    what to set up.

    The probe runs in a subprocess: broken Windows torch installs can fail
    while loading native DLLs, which is not always cleanly contained by
    catching Python exceptions in the pytest process.
    """
    global _CELLPOSE_RUNTIME_CACHE
    if _CELLPOSE_RUNTIME_CACHE is not None:
        return _CELLPOSE_RUNTIME_CACHE

    from zmart_analysis.workers import the_interpreter_in, the_prefix_of

    prefix = the_prefix_of(CELLPOSE_ENVIRONMENT)
    if prefix is None:
        _CELLPOSE_RUNTIME_CACHE = (
            False,
            (
                f"the {CELLPOSE_ENVIRONMENT} environment is not set up; create it with "
                "conda env create -f workflows/non-coders/analysis/object_analysis/environments/cellpose.yml"
            ),
        )
        return _CELLPOSE_RUNTIME_CACHE

    code = r"""
import importlib
import sys

for module in ("cellpose.models", "torch"):
    try:
        importlib.import_module(module)
    except Exception as exc:
        print(
            f"{module} unavailable: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2)
import torch
print("cuda" if torch.cuda.is_available() else "cpu")
"""
    try:
        result = subprocess.run(
            [str(the_interpreter_in(prefix)), "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        _CELLPOSE_RUNTIME_CACHE = False, "runtime probe timed out"
        return _CELLPOSE_RUNTIME_CACHE
    except OSError as exc:
        # The environment's folder is there but its interpreter is not: say so,
        # and let the tests that need it skip, rather than ending the whole run.
        _CELLPOSE_RUNTIME_CACHE = (
            False,
            f"the {CELLPOSE_ENVIRONMENT} environment has no interpreter: {exc}",
        )
        return _CELLPOSE_RUNTIME_CACHE

    if result.returncode == 0:
        _CELLPOSE_RUNTIME_CACHE = True, result.stdout.strip().splitlines()[-1]
        return _CELLPOSE_RUNTIME_CACHE

    detail = result.stderr.strip() or result.stdout.strip()
    if not detail:
        detail = f"runtime probe exited with code {result.returncode}"
    _CELLPOSE_RUNTIME_CACHE = False, detail
    return _CELLPOSE_RUNTIME_CACHE


@pytest.fixture
def cellpose_device():
    """The device Cellpose's environment can use, ``"cuda"`` or ``"cpu"``."""
    available, detail = _has_cellpose_runtime()
    if not available:
        pytest.skip(f"cellpose unavailable: {detail}")
    return detail


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests whose optional runtimes are unavailable."""
    if any("cellpose" in item.keywords for item in items):
        available, reason = _has_cellpose_runtime()
        if not available:
            skip = pytest.mark.skip(reason=f"cellpose unavailable: {reason}")
            for item in items:
                if "cellpose" in item.keywords:
                    item.add_marker(skip)
