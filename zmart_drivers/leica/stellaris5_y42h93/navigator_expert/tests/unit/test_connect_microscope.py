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
from navigator_expert.config.profiles import IMAGE_SAVE
from navigator_expert.connection import session as drv_session
from navigator_expert.connection import session_state
from navigator_expert.orientation import Orientation, orientation_config


def _connect(**kwargs) -> MockLasxClient:
    client = MockLasxClient(latency=0.0)
    with patch.object(drv_session, "connect_python_client", return_value=client):
        drv_session.connect_microscope(**kwargs)
    return client


def test_connect_loads_limits_orientation_and_calibration_by_default():
    assert IMAGE_SAVE.apply_orientation is True
    client = _connect()
    cfg = session_state.get(client)
    assert cfg is not None
    assert isinstance(cfg.orientation, Orientation)
    # Bundled defaults are deliberately uncalibrated.
    assert cfg.translations == {}
    assert cfg.calibration_info["loaded"] is True
    assert cfg.calibration_info["slots"] == []
    assert cfg.calibration_info["measured_slots"] == []
    # Seeded orientation is deliberately only a placeholder, never mistaken
    # for a measured 0-degree machine orientation.
    assert cfg.orientation_info["measured"] is False
    # limits are installed and govern this client
    assert gate.state_for(client).ok


def test_connect_creates_programdata_layout_when_all_config_loading_is_skipped(
    tmp_path, monkeypatch
):
    root = tmp_path / "fresh-programdata"
    monkeypatch.setenv("ZMART_MICROSCOPY_ROOT", str(root))

    _connect(load_limits=False, load_calibration=False)

    profile = MachineProfile(programdata_root=root)
    assert profile.snapshot_root().is_dir()
    assert all(
        profile.subsystem_root(name).is_dir()
        for name in ("limits", "calibration", "orientation", "origin")
    )


def test_connect_records_adopted_calibration_slots_as_measured():
    """Every stored translation is a measured calibration value."""
    import json

    profile = MachineProfile(programdata_root=Path(os.environ["ZMART_MICROSCOPY_ROOT"]))
    snap = profile.ensure_snapshot("calibration")
    calibration = {
        "schema_version": 13,
        "objectives": {
            "1": {"name": "10x", "translation_um": [0.0, 0.0, 0.0]},
            "2": {"name": "20x", "translation_um": [1.0, 2.0, 3.0]},
        },
    }
    (snap / "calibration.json").write_text(json.dumps(calibration), encoding="utf-8")

    client = _connect()

    info = session_state.get(client).calibration_info
    assert info["loaded"] is True
    assert info["measured_slots"] == [1, 2]
    assert info["slots"] == [1, 2]


def test_connect_can_skip_calibration():
    client = _connect(load_calibration=False)
    assert session_state.get(client).translations is None


def test_connect_skipping_limits_installs_the_default_fallback():
    client = _connect(load_limits=False)
    state = gate.state_for(client)
    assert state.ok
    assert state.limits.describe()["is_fallback"] is True


def test_connect_records_the_selected_calibration_name():
    client = _connect(calibration_name=None)
    assert session_state.get(client).calibration_name is None


def test_connect_records_measured_orientation_as_positive_preflight_evidence():
    profile = MachineProfile(programdata_root=Path(os.environ["ZMART_MICROSCOPY_ROOT"]))
    snap = profile.ensure_snapshot("orientation")
    (snap / "orientation.json").write_text(
        '{"schema_version": 1, "rotate_deg": 0, "measured": true}',
        encoding="utf-8",
    )

    client = _connect()

    info = session_state.get(client).orientation_info
    assert info["loaded"] is True
    assert info["measured"] is True
    assert info["rotate_deg"] == 0


def test_connect_loads_mirror_signs_and_matrix_from_complete_orientation():
    import json

    profile = MachineProfile(programdata_root=Path(os.environ["ZMART_MICROSCOPY_ROOT"]))
    snap = profile.ensure_snapshot("orientation")
    expected = Orientation(rotate_deg=270, mirrored=True)
    (snap / "orientation.json").write_text(
        json.dumps(orientation_config(expected)),
        encoding="utf-8",
    )

    client = _connect()

    cfg = session_state.get(client)
    assert cfg.orientation == expected
    assert cfg.orientation_info["mirrored"] is True
    assert cfg.orientation_info["axis_signs"] == {"stage_x": 1, "stage_y": 1}
    assert cfg.orientation_info["axis_mapping"] == {
        "stage_x_from_image": "+Y",
        "stage_y_from_image": "+X",
    }
    assert cfg.orientation_info["image_to_stage"] == [[0, 1], [1, 0]]


def test_orientation_and_readiness_evidence_come_from_one_validated_read():
    import json

    real_loads = json.loads
    with patch.object(drv_session.json, "loads", wraps=real_loads) as loads:
        orientation, info = drv_session._load_rig_orientation()

    loads.assert_called_once()
    assert info["rotate_deg"] == orientation.rotate_deg
    assert info["measured"] is False


def test_invalid_orientation_cannot_claim_measured_preflight_evidence(caplog):
    profile = MachineProfile(programdata_root=Path(os.environ["ZMART_MICROSCOPY_ROOT"]))
    snap = profile.ensure_snapshot("orientation")
    (snap / "orientation.json").write_text(
        '{"schema_version": 1, "rotate_deg": 45, "measured": true}',
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        client = _connect()

    info = session_state.get(client).orientation_info
    assert info["loaded"] is False
    assert info["measured"] is False
    assert "error" in info


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
    camera produced them, with a loud warning matching the fail-soft posture of
    the limits fallback and the calibration degrade.
    """
    profile = MachineProfile(programdata_root=Path(os.environ["ZMART_MICROSCOPY_ROOT"]))
    snap = profile.ensure_snapshot("orientation")
    (snap / "orientation.json").write_text(bad_text, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        client = _connect()

    cfg = session_state.get(client)
    assert cfg is not None
    assert cfg.orientation.is_identity
    # the rest of the connection proceeded normally
    assert gate.state_for(client).ok
    assert any("orientation unavailable" in r.message for r in caplog.records)
