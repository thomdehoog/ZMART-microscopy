"""Subprocess test for the driver's _shared self-bootstrap.

The driver imports _shared.output_layout, which lives at
controller/vendor/_shared/ — parallel to controller/vendor/leica/.
driver/__init__.py inserts controller/vendor/ on sys.path so the
import resolves even for callers that only know about leica/.

This test MUST run in a subprocess: the in-process pytest session
already has controller/vendor/ on sys.path (via conftest.py), so an
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
import navigator_expert.driver as drv
assert drv.acquire_and_save is not None
assert drv.start_run is not None
print("bootstrap-ok")
"""


def test_driver_self_bootstrap_with_only_leica_on_path(tmp_path):
    """Spawn a fresh Python process with PYTHONPATH=controller/vendor/leica
    only (no controller/vendor). The driver's self-bootstrap must add
    controller/vendor/ so `import _shared.output_layout` resolves
    transitively when acquisition.py loads."""
    repo_root = Path(__file__).resolve().parents[5]  # smart-microscopy/
    leica_dir = repo_root / "controller" / "vendor" / "leica"
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
