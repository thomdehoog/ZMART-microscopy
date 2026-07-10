"""The driver's own connection entry point loads the three machine-local
configs, with per-file load switches.

These exercise ``connection.session.connect_microscope`` against a mock CAM
client and the hermetic ProgramData root the autouse conftest fixture points
at (so limits/orientation/calibration seed from the bundled defaults).
"""

from __future__ import annotations

from unittest.mock import patch

from mock_lasx_api import MockLasxClient
from navigator_expert.commands import gate
from navigator_expert.connection import session as drv_session
from navigator_expert.connection import session_state
from navigator_expert.orientation import Orientation


def _connect(**kwargs) -> MockLasxClient:
    client = MockLasxClient(latency=0.0)
    with patch.object(drv_session, "connect_python_client", return_value=client):
        drv_session.connect_microscope(**kwargs)
    return client


def test_connect_loads_limits_orientation_and_calibration_by_default():
    client = _connect()
    cfg = session_state.get(client)
    assert cfg is not None
    assert isinstance(cfg.orientation, Orientation)
    # the seeded default calibration lists objectives, so translations load
    assert cfg.translations is not None and cfg.translations
    # limits are installed and govern this client
    assert gate.state_for(client).ok


def test_connect_can_skip_calibration():
    client = _connect(load_calibration=False)
    assert session_state.get(client).translations is None


def test_connect_skipping_orientation_is_the_identity_turn():
    client = _connect(load_orientation=False)
    assert session_state.get(client).orientation.is_identity


def test_connect_skipping_limits_installs_the_default_fallback():
    client = _connect(load_limits=False)
    state = gate.state_for(client)
    assert state.ok
    assert state.limits.describe()["is_fallback"] is True


def test_connect_records_the_selected_calibration_name():
    client = _connect(calibration_name=None)
    assert session_state.get(client).calibration_name is None
