"""The analysis engine runs a real pipeline in its own environment, and the interface reaches it.

ZMART-analysis is installed as the ``engine`` package, but the pipelines it
runs (recipes in YAML, and the steps they name) stay in a clone of its
repository, and each step runs in a conda environment of its own. Three
blocks have to agree for one focus score to come back: the installed engine,
the workflows in the clone, and the step's environment (``ZMART--focus--main``,
made or reused by install.py).

The stack scored here is synthetic and simple, so the right answer is known:
nine planes, all flat grey except one full of texture, which is the only sharp
plane. The focus is therefore at that plane's height, 108 µm.

On Windows computers where programs may only run from approved folders, the
engine's ``conda run`` needs ``TMPDIR`` to point at such a folder; the README
says more.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import time

import numpy as np
import pytest
import tifffile

from conftest import checkout

#: Where the sharp plane is, and the height each plane was taken at.
SHARP_PLANE = 4
HEIGHTS_UM = [100.0 + 2.0 * z for z in range(9)]

#: How long a first focus score may take: a worker has to start in its own
#: environment and import numpy and scipy before it scores anything.
PATIENCE_S = 300


@pytest.fixture
def a_stack_sharp_at_108_um(tmp_path):
    """Nine planes; only plane 4 has detail, so only it is in focus."""
    stack = np.stack([
        np.random.default_rng(0).integers(0, 4096, size=(64, 64)).astype(np.uint16)
        if z == SHARP_PLANE else np.full((64, 64), 100, dtype=np.uint16)
        for z in range(len(HEIGHTS_UM))
    ])
    path = tmp_path / "stack.tiff"
    tifffile.imwrite(path, stack, metadata={"axes": "ZYX"})
    return path


@pytest.fixture
def the_focus_environment():
    """The step's own environment exists; if not, the failure says how to make it."""
    from engine.conda_utils import env_exists, get_conda_info

    if not env_exists(get_conda_info(), "ZMART--focus--main"):
        pytest.fail("the conda environment ZMART--focus--main is missing; "
                    "install.py makes it (or setup_env.py in the focus workflow)")


def test_the_engine_scores_a_focus_stack_in_the_focus_environment(
    a_stack_sharp_at_108_um, the_focus_environment
):
    """The installed engine runs the focus recipe from the clone and finds the sharp plane."""
    from engine import Engine

    recipe = checkout("ZMART-analysis") / "workflows" / "focus" / "pipelines" / "focus.yaml"
    engine = Engine()
    try:
        engine.register("focus", str(recipe))
        engine.submit("focus", {"image_path": str(a_stack_sharp_at_108_um), "z_um": HEIGHTS_UM})
        deadline = time.monotonic() + PATIENCE_S
        results = []
        while not results and time.monotonic() < deadline:
            results = engine.results("focus")
            failures = engine.status("focus").get("failures")
            assert not failures, failures
            time.sleep(0.2)
    finally:
        engine.shutdown()
    assert results, f"no focus score came back within {PATIENCE_S} s"
    found = results[0]["score_focus"]
    assert found["n_planes"] == 9
    assert found["peak_z_um"] == pytest.approx(108.0)


def test_the_interface_reaches_the_engine_the_way_its_focus_map_does(
    a_stack_sharp_at_108_um, the_focus_environment, monkeypatch
):
    """The interface's own door to the analysis finds the workflows and gets the same answer.

    The interface is told where the workflows are with
    ``ZMART_ANALYSIS_WORKFLOWS``, and keeps one engine warm for the whole
    session. This is the call its focus map makes for every point.
    """
    monkeypatch.setenv("ZMART_ANALYSIS_WORKFLOWS", str(checkout("ZMART-analysis")))
    from zmart_interface.parts.analysis.warm import Analysis
    from zmart_interface.parts.analysis.workflows import workflows_root

    assert workflows_root() == (checkout("ZMART-analysis") / "workflows").resolve()
    analysis = Analysis()
    try:
        found = analysis.run("focus", {"image_path": str(a_stack_sharp_at_108_um),
                                       "z_um": HEIGHTS_UM})["score_focus"]
    finally:
        analysis.engine.shutdown()
    assert found["peak_z_um"] == pytest.approx(108.0)
