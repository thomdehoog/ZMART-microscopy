"""Shared pytest fixtures and helpers for the smart-analysis test suite.

This conftest is loaded for every test file in the repo. It provides:

- A session-scoped temp directory cleaned up at the end of the run.
- Factories for creating step .py files and pipeline YAML files
  (``temp_step``, ``temp_yaml``).
- Polling helpers as fixtures (``wait_for_results``, ``wait_for_completion``)
  that replace fixed ``time.sleep(N)`` patterns with bounded polling.
- ``count_children`` helper backed by psutil (a hard test dependency,
  declared in ``[project.optional-dependencies].test`` in pyproject.toml).

Markers
-------
See ``pyproject.toml`` ``[tool.pytest.ini_options]`` for the full marker list.
The most-used:

- ``integration`` -- real YAML pipelines through the v4 API
- ``robustness`` -- edge cases, recovery
- ``adversarial`` -- stress / race / corruption
- ``slow`` -- > ~5s
- ``cellpose`` -- requires cellpose + skimage in the active env
- ``deep`` -- requires torch / DINO in the active env
- ``cluster`` -- requires SMART--target_discovery--cluster
- ``pooch`` -- uses public skimage sample data downloaded/cached by pooch
- ``conda_env`` -- requires SMART--basic_test--env_a
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import psutil
import pytest


# Make the engine package importable regardless of where pytest is invoked
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------
# Session-wide temp dir
# --------------------------------------------------------------------------

_SESSION_TEMP = Path(tempfile.mkdtemp(prefix="smart_analysis_tests_"))
atexit.register(shutil.rmtree, _SESSION_TEMP, True)
_counter = [0]


def _next_id():
    _counter[0] += 1
    return _counter[0]


# --------------------------------------------------------------------------
# Step / YAML factories
# --------------------------------------------------------------------------


def _write_step(code, name=None):
    """Write a step .py file to the session temp dir; return absolute path."""
    fname = f"{name}.py" if name else f"step_{_next_id()}.py"
    path = _SESSION_TEMP / fname
    path.write_text(textwrap.dedent(code))
    return str(path)


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


@pytest.fixture
def temp_step():
    """Factory fixture: returns a callable ``temp_step(code, name=None)``."""
    return _write_step


@pytest.fixture
def temp_yaml():
    """Factory fixture: returns a callable ``temp_yaml(content)``."""
    return _write_yaml


# --------------------------------------------------------------------------
# Polling helpers
# --------------------------------------------------------------------------


def _wait_for_results(engine, name, expected, timeout=30):
    t0 = time.monotonic()
    collected = []
    while time.monotonic() - t0 < timeout:
        collected.extend(engine.results(name))
        if len(collected) >= expected:
            return collected
        time.sleep(0.05)
    return collected


def _wait_for_completion(engine, name, expected_total, timeout=30):
    """Poll results AND status; return as soon as results+failed >= expected.

    Avoids waiting the full timeout when a job has already failed (the
    failure is recorded in status, not as a result).
    """
    t0 = time.monotonic()
    collected = []
    while time.monotonic() - t0 < timeout:
        collected.extend(engine.results(name))
        s = engine.status(name)
        if len(collected) + s["failed"] >= expected_total:
            return collected, s
        time.sleep(0.05)
    return collected, engine.status(name)


def _wait_for_status(engine, name, expected_total, timeout=30):
    """Poll engine.status() until completed+failed >= expected_total."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        s = engine.status(name)
        if s["completed"] + s["failed"] >= expected_total:
            return s
        time.sleep(0.05)
    return engine.status(name)


@pytest.fixture
def wait_for_results():
    return _wait_for_results


@pytest.fixture
def wait_for_completion():
    return _wait_for_completion


@pytest.fixture
def wait_for_status():
    return _wait_for_status


# --------------------------------------------------------------------------
# Process accounting (for resource-leak tests)
# --------------------------------------------------------------------------


def _count_children():
    """Count subprocess children of the current process. Backed by psutil
    because the v4 engine uses subprocess.Popen, which
    multiprocessing.active_children() does not see (would yield 0)."""
    return len(psutil.Process().children(recursive=True))


@pytest.fixture
def count_children():
    return _count_children


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
    from engine import Engine

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


# --------------------------------------------------------------------------
# Skip helpers
# --------------------------------------------------------------------------


_CELLPOSE_RUNTIME_CACHE: tuple[bool, str] | None = None
_DEEP_RUNTIME_CACHE: tuple[bool, str] | None = None


def _has_cellpose_runtime() -> tuple[bool, str]:
    """Return (available, reason) for the cellpose runtime in this env.

    Probe in a subprocess. Broken Windows torch installs can fail while
    loading native DLLs, which is not always cleanly contained by catching
    Python exceptions in the pytest process.
    """
    global _CELLPOSE_RUNTIME_CACHE
    if _CELLPOSE_RUNTIME_CACHE is not None:
        return _CELLPOSE_RUNTIME_CACHE

    code = r"""
import importlib
import sys

for module in ("skimage", "cellpose.models"):
    try:
        importlib.import_module(module)
    except Exception as exc:
        print(
            f"{module} unavailable: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        _CELLPOSE_RUNTIME_CACHE = False, "runtime probe timed out"
        return _CELLPOSE_RUNTIME_CACHE

    if result.returncode == 0:
        _CELLPOSE_RUNTIME_CACHE = True, "ok"
        return _CELLPOSE_RUNTIME_CACHE

    detail = result.stderr.strip() or result.stdout.strip()
    if not detail:
        detail = f"runtime probe exited with code {result.returncode}"
    _CELLPOSE_RUNTIME_CACHE = False, detail
    return _CELLPOSE_RUNTIME_CACHE


def _has_deep_runtime() -> tuple[bool, str]:
    """Return (available, reason) for the deep-feature runtime in this env."""
    global _DEEP_RUNTIME_CACHE
    if _DEEP_RUNTIME_CACHE is not None:
        return _DEEP_RUNTIME_CACHE

    code = r"""
import importlib
import sys

for module in ("torch",):
    try:
        importlib.import_module(module)
    except Exception as exc:
        print(
            f"{module} unavailable: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        _DEEP_RUNTIME_CACHE = False, "runtime probe timed out"
        return _DEEP_RUNTIME_CACHE

    if result.returncode == 0:
        _DEEP_RUNTIME_CACHE = True, "ok"
        return _DEEP_RUNTIME_CACHE

    detail = result.stderr.strip() or result.stdout.strip()
    if not detail:
        detail = f"runtime probe exited with code {result.returncode}"
    _DEEP_RUNTIME_CACHE = False, detail
    return _DEEP_RUNTIME_CACHE


def pytest_configure(config):
    """Register the markers.

    Upstream declares these in its own ``pyproject.toml``; ZMART has no
    repo-wide pytest configuration, so they are registered here instead --
    beside the conftest that uses them, and without a global config that
    would change how the rest of the repository's suites collect.
    """
    for marker, description in (
        ("integration", "end-to-end tests using real YAML pipelines through the v4 API"),
        ("robustness", "edge cases, error recovery, resource cleanup"),
        ("adversarial", "stress / race-condition / corruption / protocol-attack tests"),
        ("slow", "tests that take more than ~5s individually"),
        ("cellpose", "requires real cellpose + skimage in the active env"),
        ("deep", "requires Torch/DINO model access in the active env"),
        ("cluster", "requires SMART--target_discovery--cluster for kNN/Leiden/UMAP"),
        ("pooch", "uses public skimage sample data downloaded/cached by pooch"),
        ("conda_env", "requires SMART--basic_test--env_a conda env"),
    ):
        config.addinivalue_line("markers", f"{marker}: {description}")


@pytest.fixture
def cellpose_available():
    """Return (available, reason). Tests can call pytest.skip() with reason."""
    return _has_cellpose_runtime()


@pytest.fixture
def deep_available():
    """Return (available, reason). Tests can call pytest.skip() with reason."""
    return _has_deep_runtime()


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests whose optional runtimes are unavailable."""
    if any("cellpose" in item.keywords for item in items):
        available, reason = _has_cellpose_runtime()
        if not available:
            skip = pytest.mark.skip(reason=f"cellpose unavailable: {reason}")
            for item in items:
                if "cellpose" in item.keywords:
                    item.add_marker(skip)

    if any("deep" in item.keywords for item in items):
        available, reason = _has_deep_runtime()
        if not available:
            skip = pytest.mark.skip(reason=f"deep runtime unavailable: {reason}")
            for item in items:
                if "deep" in item.keywords:
                    item.add_marker(skip)
