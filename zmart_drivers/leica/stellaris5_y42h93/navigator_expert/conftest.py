"""Shared pytest fixtures for the navigator_expert driver test suite."""

from __future__ import annotations

import matplotlib
import pytest

# Headless before any test imports matplotlib.pyplot -- calibration's overlay
# plots (calibration/core/common.py:plot_overlay) otherwise pull in whatever
# GUI backend matplotlib auto-selects (Tk here), which needs a working Tk/Tcl
# install the test env doesn't carry. Must run before the first pyplot
# import anywhere in the process, so this is the earliest conftest in the tree.
matplotlib.use("Agg")


@pytest.fixture(autouse=True)
def _hermetic_machine_root(tmp_path_factory, monkeypatch):
    """Point the machine config root at an empty tmp dir for every test.

    The global ``config.machine.MACHINE`` otherwise resolves calibration/limits
    from the real ``C:\\ProgramData\\zmart-microscopy`` tree, which would make
    tests depend on (and potentially write) machine-local state. With an empty
    root, default resolution deterministically falls back to the driver-bundled
    defaults. Tests that need snapshots create their own
    ``MachineProfile(programdata_root=...)`` or populate this root.
    """
    root = tmp_path_factory.mktemp("zmart_microscopy_root")
    monkeypatch.setenv("ZMART_MICROSCOPY_ROOT", str(root))
