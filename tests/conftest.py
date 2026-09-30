"""Test setup: register the mock microscope and reset the active session.

The mock is the pretend microscope that ships with the package, so the tests
run without any hardware.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

import pytest

from zmart_controller import mock

mock.register()


@pytest.fixture(autouse=True)
def _reset_active_session():
    """Clear the module-level active session after every test.

    Without this, a test that sets an instrument leaks it into the next test,
    and the "no active microscope" error branch is never exercised.
    """
    yield
    import zmart_controller

    zmart_controller._active = None
