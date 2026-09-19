"""State readers against the mock server."""

from __future__ import annotations

from mesospim import readers
from mesospim.readers.readers import Reading, _reading_value_after


def test_ping_true(client):
    assert readers.ping(client) is True


def test_ping_false_after_close(client):
    client.close()
    assert readers.ping(client) is False


def test_get_state_has_run_state_position_and_settings(client):
    state = readers.get_state(client)
    # Over Remote Control the run state is read truthfully (the old
    # script-injection bridge could not see it).
    assert state["state"] == "idle"
    assert set(state["position"]) == {"x", "y", "z", "f", "theta"}
    assert state["laser"] == "488 nm"
    assert state["etl_l_amplitude"] == 1.0


def test_get_positions_all_axes(client):
    pos = readers.get_positions(client)
    assert set(pos) == {"x", "y", "z", "f", "theta"}
    assert pos["x"] == 0.0


def test_get_position_single_axis(client):
    assert readers.get_position(client, "z") == 0.0


def test_get_xyz_only_linear(client):
    assert set(readers.get_xyz(client)) == {"x", "y", "z"}


def test_get_config_lists(client):
    cfg = readers.get_config(client)
    assert cfg["app"] == "mesoSPIM-control"
    assert readers.get_lasers(client)
    assert "515/30" in readers.get_filters(client)
    assert any(z["name"] == "1x" for z in readers.get_zooms(client))
    assert cfg["camera"] == {"pixels_x": 64, "pixels_y": 64}


def test_get_limits_reports_the_enforced_envelope(client):
    limits = readers.get_limits(client)
    assert limits["stage"]["stage_type"] == "DemoStage"
    assert limits["enforced"]["axes"]["x"] == [-50000.0, 50000.0]
    assert limits["enforced"]["axis_offsets"]["x"] == 0.0


def test_get_info_reports_identity_and_operation(client):
    info = readers.get_info(client)
    assert info["app"] == "mesoSPIM-control" and info["protocol"] == 1
    assert info["operation"] == {"status": "idle"}


def test_get_progress_carries_the_latest_operation(client):
    prog = readers.get_progress(client)
    assert "current_plane" in prog
    assert prog["operation"] == {"status": "idle"}
    client.perform("zero", axes=["x"])
    assert readers.get_progress(client)["operation"]["command"] == "zero"


def test_diagnostics_returns_reading(client):
    reading = readers.get_positions(client, diagnostics=True)
    assert isinstance(reading, Reading)
    assert reading.source == "server"


def test_reading_freshness_gate():
    stale = Reading(value=1, observed_at=100.0)
    assert _reading_value_after(stale, 200.0) is None
    assert _reading_value_after(stale, 50.0) == 1
    # A bare value has no timestamp and passes through.
    assert _reading_value_after(42, 999.0) == 42
