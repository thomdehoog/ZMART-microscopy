"""Controller-only step functions: connect, load_positions, overview, targets."""

from __future__ import annotations

import json

import pytest
from pipeline._focus_surface import fit_focus_surface
from pipeline.steps import (
    acquire_targets,
    connect,
    load_positions,
    run_overview,
    with_focus_z,
)

from zmart_controller.tests.mock_driver import register_mock

_TILTED = fit_focus_surface(
    [
        {"x_um": 0, "y_um": 0, "z_um": 3.0},
        {"x_um": 10, "y_um": 0, "z_um": 4.0},
        {"x_um": 0, "y_um": 10, "z_um": 5.0},
    ]
)


@pytest.fixture
def mic():
    register_mock()
    session = connect("mock")
    yield session
    session.disconnect()


def test_connect_selects_vendor_and_sets_output_root(tmp_path):
    register_mock()
    session = connect("mock", output_root=tmp_path)
    assert session.context["vendor"] == "mock"
    session.disconnect()


def test_connect_unknown_vendor_raises():
    with pytest.raises(ValueError, match="no registered instrument"):
        connect("does-not-exist")


def test_load_positions_reads_json(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(json.dumps([{"x": 1, "y": 2}, {"x": 3, "y": 4, "z": 5}]), encoding="utf-8")
    assert load_positions(path) == [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0, "z": 5.0}]


def test_with_focus_z_uses_the_surface():
    placed = with_focus_z([{"x": 5, "y": 5}], focus=_TILTED)
    assert placed[0]["z"] == pytest.approx(4.5)


def test_with_focus_z_defaults_to_zero_without_a_surface():
    assert with_focus_z([{"x": 1, "y": 2}]) == [{"x": 1, "y": 2, "z": 0.0}]


def test_run_overview_captures_each_at_focus_z(mic):
    records = run_overview(mic, [{"x": 5.0, "y": 5.0}], focus=_TILTED)
    assert records[0]["acquisition_type"] == "overview"
    assert records[0]["position"]["z"] == pytest.approx(4.5)


def test_acquire_targets_uses_the_target_type(mic):
    records = acquire_targets(mic, [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}])
    assert [r["acquisition_type"] for r in records] == ["target", "target"]
    assert [r["position_label"] for r in records] == ["1", "2"]
