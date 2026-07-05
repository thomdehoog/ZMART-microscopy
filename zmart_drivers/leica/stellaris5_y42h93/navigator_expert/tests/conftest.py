"""Shared pytest setup and immutable test-data accessors."""

import shutil
import sys
from pathlib import Path

import pytest

# Add the machine dir (parent of navigator_expert) to sys.path so
# `import navigator_expert` works regardless of where pytest is invoked from.
_DRIVER_PARENT = Path(__file__).resolve().parents[2]
if str(_DRIVER_PARENT) not in sys.path:
    sys.path.insert(0, str(_DRIVER_PARENT))

# Add the repo root so `from shared...` imports resolve.
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_HELPERS = Path(__file__).resolve().parent / "helpers"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))

# Add target_acquisition dir so workflow tests imported from this suite
# can resolve `from pipeline...`.
_TARGET_ACQ = _REPO_ROOT / "workflows" / "target_acquisition"
if str(_TARGET_ACQ) not in sys.path:
    sys.path.insert(0, str(_TARGET_ACQ))

TEST_DATA = Path(__file__).resolve().parent / "data"
GENERAL_WORKFLOW_DATA = TEST_DATA / "general_workflow"
SCANFIELD_PARSING_DATA = TEST_DATA / "scanfield_parsing"


def pytest_report_header(config):
    """Print the full environment context at the top of every run.

    This header travels with every captured log, so a failure reported from a
    CI runner or another institute's microscope PC carries the exact system
    context (OS, Python, package versions, git rev, LAS X availability) needed
    to triage it. Diagnostics must never break a run, hence the guard.
    See tests/_diagnostics.py.
    """
    try:
        from _diagnostics import header_lines

        return header_lines()
    except Exception as exc:  # pragma: no cover - diagnostics must not fail a run
        return [f"navigator_expert context: diagnostics unavailable ({exc!r})"]


@pytest.fixture(autouse=True)
def fast_timing_windows(monkeypatch):
    """Shrink the real-time confirm/echo poll windows for the offline suite.

    The shipped defaults (``utils.CONFIRM_POLL_S = 3`` s per confirm attempt,
    ``dispatch.ECHO_SETTLE_TIMEOUT_S = 1`` s per fire) are real hardware
    windows; against mocks they are pure sleep (~35 s of the suite, LT-03).
    The consumers read both values at call time, so patching here reaches
    every poll loop. Shipped values are unchanged; a test that needs a
    specific window passes an explicit ``poll_window=``/``timeout=``.
    """
    from navigator_expert import utils
    from navigator_expert.commands import dispatch

    monkeypatch.setattr(utils, "CONFIRM_POLL_S", 0.05)
    monkeypatch.setattr(dispatch, "ECHO_SETTLE_TIMEOUT_S", 0.05)


@pytest.fixture
def general_workflow_data(tmp_path):
    """Return a writable temp copy of the canonical offline workflow bundle."""
    if not GENERAL_WORKFLOW_DATA.is_dir():
        pytest.skip(f"test data not found: {GENERAL_WORKFLOW_DATA}")
    dst = tmp_path / "general_workflow"
    shutil.copytree(GENERAL_WORKFLOW_DATA, dst)
    return dst
