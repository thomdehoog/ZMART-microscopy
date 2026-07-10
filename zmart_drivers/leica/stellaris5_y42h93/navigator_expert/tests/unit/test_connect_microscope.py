"""The driver's own connection entry point loads the three machine-local
configs, with per-file load switches.

These exercise ``connection.session.connect_microscope`` against a mock CAM
client and the hermetic ProgramData root the autouse conftest fixture points
at (so limits/orientation/calibration seed from the bundled defaults).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from mock_lasx_api import MockLasxClient
from navigator_expert.commands import gate
from navigator_expert.config.machine import MachineProfile
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


@pytest.mark.parametrize(
    "bad_text",
    [
        "this is not json {",  # unparseable file
        '{"schema_version": 1, "rotate_deg": 45}',  # off-quarter turn
    ],
)
def test_connect_survives_a_bad_orientation_file(bad_text, caplog):
    """A corrupt orientation.json must not fail the connection.

    The session degrades to the identity turn — images saved exactly as the
    camera produced them, the same defined meaning as load_orientation=False —
    with a loud warning, matching the fail-soft posture of the limits fallback
    and the calibration degrade.
    """
    profile = MachineProfile(programdata_root=Path(os.environ["ZMART_MICROSCOPY_ROOT"]))
    snap = profile.ensure_snapshot()
    (snap / "orientation.json").write_text(bad_text, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        client = _connect()

    cfg = session_state.get(client)
    assert cfg is not None
    assert cfg.orientation.is_identity
    # the rest of the connection proceeded normally
    assert gate.state_for(client).ok
    assert any("orientation unavailable" in r.message for r in caplog.records)
