"""The mock instrument window's rig controls, held to what the setup workflow reads.

The window is pywebview and cannot open here; its ``Api`` can, and that is
where the behaviour is: turning the camera, changing the lens and dropping a
marker have to land in the same rig file the mock's setup driver reads, or
the workflow would be measuring a rig the window was not showing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_window():
    spec = importlib.util.spec_from_file_location(
        "mock_instrument_window", Path(__file__).parent / "mock-instrument.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from zmart_drivers.mock import mock_setup

    monkeypatch.setenv(mock_setup.MACHINE_ROOT_ENV, str(tmp_path / "machine"))
    monkeypatch.setenv("ZMART_MOCK_STATE", str(tmp_path / "instrument.json"))
    return _load_window().Api(), mock_setup


def test_the_window_shows_the_rig_and_what_was_published(api):
    window, mock_setup = api
    state = window.state()
    assert state["rig"]["camera"] == {"rotation_deg": 90, "reflection": False}
    assert state["rig"]["objective_slot"] == 0
    assert state["rig"]["markers"] == []
    assert all("nothing published" in said for said in state["published"].values())


def test_turning_the_camera_is_what_the_setup_driver_then_measures(api):
    window, mock_setup = api
    window.turn_camera(180, True)
    rig = mock_setup.read_rig(mock_setup.where_the_machine_is())
    assert rig["camera"] == {"rotation_deg": 180, "reflection": True}
    with pytest.raises(ValueError, match="quarter-turns"):
        window.turn_camera(45, False)


def test_changing_the_lens_is_observed_by_the_setup_driver(api):
    window, mock_setup = api
    window.change_lens(2)
    handle = mock_setup.open_setup({})
    assert mock_setup.objective(handle)["name"] == "40x dry"
    with pytest.raises(ValueError, match="no objective"):
        window.change_lens(7)


def test_four_markers_dropped_where_the_stage_stands_are_the_boundary(api):
    window, mock_setup = api
    handle = mock_setup.open_setup({})
    for x, y in ((5000, 6000), (110000, 6000), (110000, 70000), (5000, 70000)):
        mock_setup.move(handle, x, y, 16.0)
        window.drop_marker()
    assert mock_setup.markers(handle)["points"][0] == {"x_um": 5000.0, "y_um": 6000.0}
    assert len(window.state()["rig"]["markers"]) == 4
    # A fifth replaces the oldest; clearing empties them.
    window.drop_marker()
    assert len(window.state()["rig"]["markers"]) == 4
    window.clear_markers()
    assert window.state()["rig"]["markers"] == []


def test_what_was_published_reads_back_in_one_line_apiece(api):
    window, mock_setup = api
    handle = mock_setup.open_setup({})
    mock_setup.publish(handle, "orientation", {"rotation_deg": 90, "reflection": False})
    mock_setup.publish(handle, "origin", {"x_um": 1.0, "y_um": 2.0, "z_um": 3.0})
    said = window.state()["published"]
    assert said["orientation"] == "90° (measured)"
    assert said["origin"] == "(1, 2, 3) µm"
    assert "nothing published" in said["limits"]


def test_driving_the_stage_is_what_the_setup_driver_then_reads(api):
    window, mock_setup = api
    window.drive_stage(5000, 6000, 16.0)
    handle = mock_setup.open_setup({})
    assert mock_setup.where(handle)["x_um"] == 5000.0
    window.drop_marker()
    assert mock_setup.read_rig(handle.root)["markers"] == [{"x_um": 5000.0, "y_um": 6000.0}]
    with pytest.raises(ValueError, match="outside the stage's travel"):
        window.drive_stage(-999999, 0, 0)
