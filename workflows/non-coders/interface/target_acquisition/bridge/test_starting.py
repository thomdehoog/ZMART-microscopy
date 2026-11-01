"""Target acquisition offers its own mock first, and its switches belong to it.

Without it, the list is the controller's. Target acquisition's Python half,
started with the bridge, puts its own mock first, and the mock opens its own
window when its connection says so.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import argparse

import pytest

from zmart_interface.framework.bridge import server, workflows

from .. import mock_microscope
from ..mock_microscope import driver
from . import connecting, starting, state


def test_target_acquisition_offers_its_mock_first(monkeypatch):
    monkeypatch.setattr(connecting, "get_instruments", lambda: {"stellaris": {}, mock_microscope.NAME: {}})
    bridge = server.serve(0)
    try:
        assert [one["name"] for one in connecting.instruments()] == [mock_microscope.NAME, "stellaris"]
    finally:
        bridge.shutdown()
        bridge.server_close()


def test_without_its_own_mock_the_list_is_the_controllers(monkeypatch):
    monkeypatch.setattr(connecting, "get_instruments", lambda: {"stellaris": {}})
    monkeypatch.setattr(connecting, "offered", {})
    assert [one["name"] for one in connecting.instruments()] == ["stellaris"]


def test_the_mock_is_offered_with_its_window():
    name, (plugged, connection) = next(iter(starting.offered().items()))
    assert name == mock_microscope.NAME and plugged is mock_microscope
    assert connection["open_window"] is True


@pytest.mark.parametrize("asked", [True, False])
def test_the_mock_opens_its_own_window_only_when_its_connection_asks(monkeypatch, asked):
    opened = []
    monkeypatch.setattr(driver, "open_the_window", lambda connection: opened.append(connection))
    handle = driver.connect({**mock_microscope.CONNECTION, "open_window": asked})
    driver.disconnect(handle)
    assert len(opened) == (1 if asked else 0)


def test_the_switch_belongs_to_target_acquisition_and_leaves_the_window_its_name(tmp_path):
    general = argparse.ArgumentParser()
    server.add_arguments(general)
    assert "--output-root" not in general.format_help()
    ours = argparse.ArgumentParser()
    halves = workflows.load_halves(server.add_route)
    server.add_arguments(ours, halves)
    assert "--output-root" in ours.format_help()
    bridge = server.a_bridge_on(0, ours.parse_args(["--output-root", str(tmp_path)]), halves=halves)
    try:
        assert bridge.title == "ZMART"
        assert state.output_root == str(tmp_path)
    finally:
        bridge.server_close()
