"""capture_positions drives the controller surface only (mock instrument)."""

from __future__ import annotations

import pytest
from workflow._capture_run import capture_positions

import zmart_controller
from zmart_controller.tests.mock_driver import register_mock

_MOCK = {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api", "client": "mock-client"}


@pytest.fixture
def mic():
    register_mock()
    session = zmart_controller.set_instrument(_MOCK)
    yield session
    session.disconnect()


def test_visits_each_position_and_returns_records(mic):
    positions = [{"x": 10.0, "y": 20.0, "z": 5.0}, {"x": 30.0, "y": 40.0, "z": 6.0}]

    records = capture_positions(mic, positions, "overview")

    assert [r["position"] for r in records] == positions
    assert [r["position_label"] for r in records] == ["1", "2"]
    assert all(r["acquisition_type"] == "overview" for r in records)


def test_applies_state_once_before_capturing(mic):
    capture_positions(
        mic,
        [{"x": 0.0, "y": 0.0, "z": 0.0}],
        "target",
        state={"changeable": {"laser_power": 9.0}},
    )

    assert mic.get_state()["changeable"]["laser_power"] == 9.0


def test_label_callable_overrides_the_index(mic):
    positions = [{"x": 1.0, "y": 2.0, "z": 3.0}, {"x": 4.0, "y": 5.0, "z": 6.0}]

    records = capture_positions(mic, positions, "target", label=lambda i, p: f"t{i:03d}")

    assert [r["position_label"] for r in records] == ["t001", "t002"]
