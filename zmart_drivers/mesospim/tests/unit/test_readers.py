"""State readers against the mock server."""

from __future__ import annotations

from mesospim import readers
from mesospim.readers.readers import Reading, _reading_value_after


def test_ping_true(client):
    assert readers.ping(client) is True


def test_ping_false_after_close(client):
    client.close()
    assert readers.ping(client) is False


def test_get_state_has_position_and_settings(client):
    state = readers.get_state(client)
    assert state["state"] == "idle"
    assert set(state["position"]) == {"x", "y", "z", "f", "theta"}
    assert state["laser"] == "488 nm"


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


def test_get_progress(client):
    prog = readers.get_progress(client)
    assert "state" in prog


def test_is_idle(client):
    assert readers.is_idle(client) is True


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
