"""Test setup: register the mock microscope and reset the active session.

The mock is the pretend microscope that ships with the package, so the tests
run without any hardware.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

import pytest

from zmart_controller import register_driver

register_driver("zmart_driver_mock", remember=False)


@pytest.fixture(autouse=True)
def _config_in_a_temporary_folder(tmp_path, monkeypatch):
    """Never let a test write to the real configuration folder."""
    monkeypatch.setenv("ZMART_MICROSCOPY_ROOT", str(tmp_path / "config"))


@pytest.fixture(autouse=True)
def _images_in_a_temporary_folder(tmp_path, monkeypatch):
    """Save the mock's images in the test's own folder, never in a shared one."""
    from zmart_controller import registry

    connect = registry.REGISTRY[("mock", "mock-scope", "mock-api")]["ops"]["connect"]
    monkeypatch.setitem(connect.__globals__, "DEFAULT_OUTPUT_ROOT", tmp_path / "images")


@pytest.fixture(autouse=True)
def _reset_active_session():
    """Clear the module-level active session after every test.

    Without this, a test that sets an instrument leaks it into the next test,
    and the "no active microscope" error branch is never exercised.
    """
    yield
    import zmart_controller

    zmart_controller._active = None
