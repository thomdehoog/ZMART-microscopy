"""Hardware smoke test (excluded from the offline run).

Requires a live ZEN + gateway + the ``zen_api`` wheel. Point ``ZENAPI_CONFIG``
at a ZEN API ``config.ini`` and run ``pytest -m hardware`` (or
``run_ci.py --hardware``). Use the first bench run to resolve the design's
open risks (completion semantics, CZI path, status-stream availability).
"""

import os

import pytest

pytestmark = pytest.mark.hardware


def test_connect_move_read():
    config = os.environ.get("ZENAPI_CONFIG")
    if not config:
        pytest.skip("set ZENAPI_CONFIG to a ZEN API config.ini to run hardware tests")

    import zenapi as drv

    client = drv.connect(config)
    try:
        pos = drv.get_xy(client)
        assert "x_um" in pos and "y_um" in pos
        obj = drv.get_objective(client)
        assert "index" in obj
    finally:
        drv.close(client)
