"""Test setup: put the source root on sys.path and register the mock driver.

The mock driver lives with the other drivers, in ``zmart_drivers/mock/``, and
is registered here because that is what any client does with a driver it wants
to use -- production ``registry.py`` imports no driver at all, which is the
property that keeps the controller free of them.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]  # repo root (parent of the package)
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from zmart_drivers.mock import mock_driver  # noqa: E402
import pytest  # noqa: E402

mock_driver.register_mock()


@pytest.fixture(autouse=True)
def _reset_active_session():
    """Clear the module-level active session after every test.

    Without this, a test that sets an instrument leaks it into the next test,
    and the "no active microscope" error branch is never exercised.
    """
    yield
    import zmart_controller

    zmart_controller._active = None
