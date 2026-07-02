"""Command wrappers against the mock server (with limits configured)."""

from __future__ import annotations

import pytest
from mesospim import commands as cmd
from mesospim.config import limits


@pytest.fixture(autouse=True)
def _limits():
    limits.clear_stage_limits()
    limits.set_stage_limits(
        x=(0, 20000), y=(0, 20000), z=(0, 20000), f=(0, 20000), theta=(-360, 360)
    )
    yield
    limits.clear_stage_limits()


def test_move_absolute_confirms(client):
    r = cmd.move_absolute(client, {"x": 100, "y": 200})
    assert r["success"] and r["confirmed"] is True
    assert r["data"]["position"]["x"] == 100


def test_move_absolute_out_of_limits_no_fire(client):
    r = cmd.move_absolute(client, {"x": 99999})
    assert not r["success"]
    assert "outside limits" in r["message"]
    # stage must not have moved
    from mesospim import readers

    assert readers.get_positions(client)["x"] == 0.0


def test_move_absolute_unknown_axis(client):
    r = cmd.move_absolute(client, {"w": 1})
    assert not r["success"] and "unknown axis" in r["message"]


def test_move_relative_confirms(client):
    cmd.move_absolute(client, {"z": 500})
    r = cmd.move_relative(client, {"z": 250})
    assert r["success"] and r["confirmed"] is True
    from mesospim import readers

    assert readers.get_positions(client)["z"] == 750


def test_move_relative_respects_limits(client):
    cmd.move_absolute(client, {"x": 19000})
    r = cmd.move_relative(client, {"x": 5000})  # would exceed 20000
    assert not r["success"] and "outside limits" in r["message"]


def test_move_relative_baseline_failure_returns_envelope(client, monkeypatch):
    # A dropped link during the pre-fire baseline read must come back as the
    # standard failure envelope, like every sibling -- not a raw exception.
    from mesospim.commands import commands as commands_module

    def broken(_client):
        raise ConnectionError("link down")

    monkeypatch.setattr(commands_module, "get_positions", broken)
    r = cmd.move_relative(client, {"z": 10})
    assert not r["success"] and "baseline" in r["message"]


def test_move_xy_z_focus_rotation(client):
    assert cmd.move_xy(client, 10, 20)["success"]
    assert cmd.move_z(client, 30)["success"]
    assert cmd.move_focus(client, 40)["success"]
    assert cmd.move_rotation(client, 15)["success"]
    from mesospim import readers

    pos = readers.get_positions(client)
    assert (pos["x"], pos["y"], pos["z"], pos["f"], pos["theta"]) == (10, 20, 30, 40, 15)


def test_set_filter_zoom_laser_intensity_shutter(client):
    assert cmd.set_filter(client, "561/LP")["success"]
    assert cmd.set_zoom(client, "2x")["success"]
    assert cmd.set_laser(client, "561 nm")["success"]
    assert cmd.set_intensity(client, 42)["success"]
    assert cmd.set_shutter(client, "Both")["success"]
    from mesospim import readers

    state = readers.get_state(client)
    assert state["filter"] == "561/LP"
    assert state["zoom"] == "2x"
    assert state["laser"] == "561 nm"
    assert state["intensity"] == 42
    assert state["shutterconfig"] == "Both"


def test_set_intensity_out_of_range(client):
    r = cmd.set_intensity(client, 500)
    assert not r["success"] and "out of range" in r["message"]


def test_set_etl(client):
    r = cmd.set_etl(client, "left", amplitude=3.0, offset=1.5)
    assert r["success"]
    from mesospim import readers

    state = readers.get_state(client)
    assert state["etl_l_amplitude"] == 3.0
    assert state["etl_l_offset"] == 1.5


def test_set_etl_bad_side(client):
    assert not cmd.set_etl(client, "middle", amplitude=1)["success"]


def test_stop_and_zero(client):
    assert cmd.stop(client)["success"]
    cmd.move_absolute(client, {"x": 500})
    assert cmd.zero_axes(client, ["x"])["success"]
    from mesospim import readers

    assert readers.get_positions(client)["x"] == 0.0
