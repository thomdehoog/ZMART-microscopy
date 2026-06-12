"""Subprocess test for the driver's shared-package self-bootstrap.

The driver imports shared.output_layout, which lives at the repository
root. driver/__init__.py inserts the repository root on sys.path so the
import resolves even for callers that only know about leica/.

This test MUST run in a subprocess: the in-process pytest session
already has the repository root on sys.path (via conftest.py), so an
in-process import would succeed even if the bootstrap were broken
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
from navigator_expert.runtime import lasx_runtime
assert drv.acquire is not None
assert drv.save is not None
assert drv.AcquisitionResult is not None
assert drv.SavedAcquisition is not None
assert lasx_runtime.REQUIRED_DLLS
print("bootstrap-ok")
"""


def test_driver_self_bootstrap_with_only_leica_on_path(tmp_path):
    """Spawn a fresh Python process with only the Leica vendor path.

    The driver's self-bootstrap must add the microscopes root so
    `import shared.output_layout` resolves
    transitively when acquisition.py loads."""
    repo_root = Path(__file__).resolve().parents[6]  # smart-microscopy/
    leica_dir = repo_root / "driver" / "vendor" / "leica"
    assert leica_dir.is_dir(), f"missing {leica_dir}"

    script = tmp_path / "child.py"
    script.write_text(CHILD_SCRIPT.format(leica=str(leica_dir)))

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
    from navigator_expert.runtime import lasx_runtime

    try:
        runtime = lasx_runtime.load_lasx_api_runtime()
    except (ImportError, ModuleNotFoundError, RuntimeError) as exc:
        pytest.skip(f"LAS X CAM API runtime unavailable: {exc}")

    assert runtime.LasxApiClientPyModel is not None
    assert runtime.__version__
    assert runtime.__file__.endswith("PYLICamApiConnector.dll")
