"""Test setup: put the source root on sys.path and register the mock driver.

The mock is a test-only integration, so it is wired into the registry here --
production registry.py never imports it.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_SRC_ROOT = _TESTS_DIR.parents[1]  # repo root (parent of the package)
for _path in (str(_SRC_ROOT), str(_TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest  # noqa: E402

import mock_driver  # noqa: E402

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
