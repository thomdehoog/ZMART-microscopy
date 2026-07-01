"""Shared pytest fixtures for the navigator_expert driver test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _hermetic_machine_root(tmp_path_factory, monkeypatch):
    """Point the machine config root at an empty tmp dir for every test.

    The global ``config.machine.MACHINE`` otherwise resolves calibration/limits
    from the real ``C:\\ProgramData\\smart_microscopy`` tree, which would make
    tests depend on (and potentially write) machine-local state. With an empty
    root, default resolution deterministically falls back to the driver-bundled
    defaults. Tests that need snapshots create their own
    ``MachineProfile(programdata_root=...)`` or populate this root.
    """
    root = tmp_path_factory.mktemp("smart_microscopy_root")
    monkeypatch.setenv("SMART_MICROSCOPY_ROOT", str(root))
