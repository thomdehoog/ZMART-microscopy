"""What target acquisition's Python tests share: a machine of their own, and the mock microscope.

The tests stand beside what they test, so this file hangs on the workflow's
folder, the one thing they all belong to.

Every test gets its own computer configuration folder and its own mock
settings file, so nothing a test does reaches the real ``C:\\ProgramData``
folder or the user's home, and no test sees what an earlier one chose.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest
from zmart_controller import ZmartController

from . import mock_microscope
from .microscope.instrument import Instrument


@pytest.fixture(autouse=True)
def _a_machine_of_its_own(tmp_path, monkeypatch):
    """Keep the controller's configuration, its list of drivers and the mock's settings in the test's folder.

    And no mock instrument window: connecting to the mock opens one beside
    the session, which a test has no screen for.
    """
    # The controller keeps its list of installed drivers in the machine's
    # folder, so a test gets a machine folder of its own.
    monkeypatch.setenv("ZMART_MICROSCOPY_ROOT", str(tmp_path / "machine"))
    monkeypatch.setenv("ZMART_MOCK_STATE", str(tmp_path / "mock" / "instrument.json"))
    monkeypatch.setattr(mock_microscope.driver, "open_the_window", lambda connection: None)
    # The bridge as target acquisition starts it: its own mock offered first
    # (``bridge/starting.py``).
    from .bridge import connecting, starting

    monkeypatch.setattr(connecting, "offered", starting.offered())


@pytest.fixture
def mock_instrument(tmp_path) -> dict:
    """The connection the mock is plugged in with, saving its images in this test's folder.

    Hand it to the controller with the mock's module:
    ``ZmartController(mock_microscope, mock_instrument)``.
    """
    return {"client": "mock-client", "output_root": str(tmp_path / "images")}


@pytest.fixture
def mock_session(mock_instrument):
    """A connected mock microscope, read the way the bridge reads it: each answer is its output."""
    session = Instrument(ZmartController(mock_microscope, mock_instrument))
    try:
        yield session
    finally:
        session.disconnect()
