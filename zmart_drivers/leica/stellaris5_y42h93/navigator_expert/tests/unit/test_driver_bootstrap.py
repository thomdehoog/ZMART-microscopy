"""Subprocess test for the driver's standalone package imports.

This test MUST run in a subprocess: the in-process pytest session
already has the repository root on sys.path (via conftest.py), so an
in-process import would succeed even if a hidden shared dependency existed
and silently mask the real failure mode.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

CHILD_SCRIPT = """
import sys
# Mimic an example-script entry point: only leica/ on sys.path.
sys.path.insert(0, r"{leica}")
import navigator_expert as drv
from navigator_expert.connection import lasx_runtime
assert drv.acquire is not None
assert drv.save is not None
assert drv.AcquisitionResult is not None
assert drv.SavedAcquisition is not None
assert lasx_runtime.REQUIRED_DLLS
print("bootstrap-ok")
"""


def test_driver_imports_with_only_leica_on_path(tmp_path):
    """The Leica package must not depend on a repository-level naming package."""
    repo_root = Path(__file__).resolve().parents[6]
    driver_parent = repo_root / "zmart_drivers" / "leica" / "stellaris5_y42h93"
    assert driver_parent.is_dir(), f"missing {driver_parent}"

    script = tmp_path / "child.py"
    script.write_text(CHILD_SCRIPT.format(leica=str(driver_parent)))

    # Inherit parent env (numpy etc. come from site-packages) but the
    # child does NOT call conftest, so sys.path will only contain what
    # site.py provides + what the child script itself inserts. That's
    # the realistic example-script scenario we want to test.
    import os as _os

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        env=_os.environ.copy(),
    )

    assert result.returncode == 0, (
        f"subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "bootstrap-ok" in result.stdout


def test_lasx_runtime_load_smoke_when_installed():
    """Load the installed LAS X runtime when available.

    Bare dev/CI machines can import the loader but cannot load LAS X assemblies;
    hardware validation covers the required installed-runtime path.
    """
    from navigator_expert.connection import lasx_runtime

    try:
        runtime = lasx_runtime.load_lasx_api_runtime()
    except (ImportError, ModuleNotFoundError, RuntimeError) as exc:
        pytest.skip(f"LAS X CAM API runtime unavailable: {exc}")

    assert runtime.LasxApiClientPyModel is not None
    assert runtime.__version__
    assert runtime.__file__.endswith("PYLICamApiConnector.dll")
