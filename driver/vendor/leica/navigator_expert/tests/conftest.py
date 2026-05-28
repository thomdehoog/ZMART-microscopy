"""Shared pytest setup and immutable test-data accessors."""

import shutil
import sys
from pathlib import Path

import pytest

# Add vendor/leica/ to sys.path so `import navigator_expert` works
# regardless of where pytest is invoked from.
_VENDOR_LEICA = Path(__file__).resolve().parents[2]
if str(_VENDOR_LEICA) not in sys.path:
    sys.path.insert(0, str(_VENDOR_LEICA))

# Add repo root to sys.path so `from shared...` imports resolve.
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_HELPERS = Path(__file__).resolve().parent / "helpers"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))

# Add target_acquisition dir so workflow tests imported from this suite
# can resolve `from pipeline...`.
_TARGET_ACQ = (
    _REPO_ROOT / "workflows" / "vendor" / "leica" /
    "navigator_expert" / "target_acquisition"
)
if str(_TARGET_ACQ) not in sys.path:
    sys.path.insert(0, str(_TARGET_ACQ))

TEST_DATA = Path(__file__).resolve().parent / "data"
GENERAL_WORKFLOW_DATA = TEST_DATA / "general_workflow"
POSITION_PARSING_DATA = TEST_DATA / "position_parsing"


@pytest.fixture
def general_workflow_data(tmp_path):
    """Return a writable temp copy of the canonical offline workflow bundle."""
    if not GENERAL_WORKFLOW_DATA.is_dir():
        pytest.skip(f"test data not found: {GENERAL_WORKFLOW_DATA}")
    dst = tmp_path / "general_workflow"
    shutil.copytree(GENERAL_WORKFLOW_DATA, dst)
    return dst
