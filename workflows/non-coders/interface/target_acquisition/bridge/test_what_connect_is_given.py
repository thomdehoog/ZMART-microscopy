"""The Connect step's fields: what the bridge tells the page, and what it hands the driver.

Every microscope shows the same seven fields on the Connect step, the
controller's connection words: the microscope, its API, the host, the
client, the password, the config and the output folder. The bridge tells
the page, per listed microscope, which of them its driver's connection
names and the value each was saved with -- never a password's value, only
that one is needed -- and the folder the last run went to. On connect,
what the operator typed goes over the saved connection, plus the output
folder, in the one dict the controller is opened with; a driver uses the
words it needs and leaves the rest.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .. import mock_microscope
from . import connecting, routes, state

#: A driver whose connection names the connection words, and a setting of
#: its own that the Connect step does not show.
NAMES_THEM = {
    "microscope": "scope-1", "api_type": "socket", "host": "10.0.0.5", "client": "c",
    "password": None, "config": None, "output_root": None, "api_delay_ms": None,
}


class Opened(Exception):
    """Raised where the controller would be opened: the test has what it was handed."""


@pytest.fixture
def handed(monkeypatch):
    """The connection the controller is opened with, caught before anything opens."""
    caught = []

    def the_controller(driver, connection):
        caught.append(connection)
        raise Opened

    monkeypatch.setattr(connecting, "ZmartController", the_controller)
    monkeypatch.setattr(connecting, "accept_the_controller", lambda installed: None)
    return caught


def the_answer(path):
    """What a GET route of the workflow answers, called as the bridge calls it."""
    registered = {}
    routes(lambda method, where, handler, prefix=False: registered.__setitem__((method, where), handler))
    return registered[("GET", path)]({}, "")


def test_each_microscope_is_listed_with_the_settings_its_connection_names(monkeypatch):
    monkeypatch.setitem(connecting.offered, "names-them", (object(), dict(NAMES_THEM)))
    monkeypatch.setattr(connecting, "get_instruments", lambda: {"stellaris": {"microscope": "s-1", "host": ""}})
    assert connecting.instruments() == [
        {"name": mock_microscope.NAME, "settings": {
            "microscope": "mock", "api_type": "Mock API", "host": "localhost", "client": "mock-client",
            "password": None, "config": None,
        }, "configs": None},
        {"name": "names-them", "settings": {
            "microscope": "scope-1", "api_type": "socket", "host": "10.0.0.5", "client": "c",
            "password": None, "config": None,
        }, "configs": None},
        {"name": "stellaris", "settings": {"microscope": "s-1", "host": ""}, "configs": None},
    ]


class KeepsConfigsPlugin:
    """The plugin of a driver that says which configs it keeps."""

    @staticmethod
    def configurations():
        return ["config_20261026_1952", "config_20260907_0714"]


class CannotSayPlugin:
    """The plugin of a driver that fails to say."""

    @staticmethod
    def configurations():
        raise OSError("the config folder cannot be read")


#: The drivers, as the controller is handed a driver package: something holding its plugin.
KeepsConfigs = SimpleNamespace(ZmartControllerPlugin=KeepsConfigsPlugin)
CannotSay = SimpleNamespace(ZmartControllerPlugin=CannotSayPlugin)


def test_a_driver_that_lists_its_configs_has_them_offered_the_most_recent_first(monkeypatch):
    monkeypatch.setitem(connecting.offered, "keeps", (KeepsConfigs, {"config": None}))
    monkeypatch.setitem(connecting.offered, "cannot-say", (CannotSay, {"config": None}))
    monkeypatch.setattr(connecting, "get_instruments", lambda: {})
    listed = {one["name"]: one["configs"] for one in connecting.instruments()}
    assert listed["keeps"] == ["config_20261026_1952", "config_20260907_0714"]
    # One that cannot say, and the mock that keeps none, are typed into.
    assert listed["cannot-say"] is None
    assert listed[mock_microscope.NAME] is None


def test_a_password_is_only_ever_named_never_given(monkeypatch):
    """The controller refuses a driver file that holds one; an offered connection is held to the same."""
    monkeypatch.setitem(connecting.offered, "holds-one", (object(), {"password": "hunter2"}))
    monkeypatch.setattr(connecting, "get_instruments", lambda: {})
    listed = {one["name"]: one["settings"] for one in connecting.instruments()}
    assert listed["holds-one"] == {"password": None}


def test_the_list_says_where_the_runs_went_last(monkeypatch):
    monkeypatch.setattr(connecting, "get_instruments", lambda: {})
    monkeypatch.setattr(state, "output_root", "D:/runs")
    answer = the_answer("instruments")
    assert answer["output_root"] == "D:/runs"
    assert [one["name"] for one in answer["instruments"]] == [mock_microscope.NAME]


def test_what_the_operator_typed_goes_over_the_saved_connection(monkeypatch, handed):
    monkeypatch.setitem(connecting.offered, "names-them", (object(), dict(NAMES_THEM)))
    with pytest.raises(Opened):
        connecting.connect({
            "instrument": "names-them", "host": "10.0.0.9", "client": "zmart", "config": "C:/scope/setup.xml",
            "password": "hunter2", "output_root": "D:/chosen",
            # Neither is the operator's to set: the microscope and its API are the driver's.
            "microscope": "another", "api_type": "grpc",
        })
    assert handed == [{
        **NAMES_THEM, "host": "10.0.0.9", "client": "zmart", "password": "hunter2",
        "config": "C:/scope/setup.xml", "output_root": "D:/chosen",
    }]


def test_a_word_the_driver_does_not_name_is_handed_on_for_it_to_leave(monkeypatch, handed):
    monkeypatch.setitem(connecting.offered, "names-none", (object(), {"mock_timing": "instant"}))
    with pytest.raises(Opened):
        connecting.connect({
            "instrument": "names-none", "host": "10.0.0.9", "client": "zmart", "config": "x.xml",
            "password": "hunter2", "output_root": "D:/chosen",
        })
    assert handed == [{
        "mock_timing": "instant", "host": "10.0.0.9", "client": "zmart", "password": "hunter2",
        "config": "x.xml", "output_root": "D:/chosen",
    }]


def test_a_field_left_empty_keeps_what_was_saved(monkeypatch, handed):
    monkeypatch.setitem(connecting.offered, "names-them", (object(), dict(NAMES_THEM)))
    monkeypatch.setattr(state, "output_root", "D:/started-with")
    with pytest.raises(Opened):
        connecting.connect({"instrument": "names-them", "host": "", "password": "", "output_root": ""})
    assert handed[0]["host"] == "10.0.0.5"
    assert handed[0]["password"] is None
    assert handed[0]["output_root"] == "D:/started-with"


def test_the_folder_a_run_went_to_is_the_one_offered_next(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "output_root", str(tmp_path / "started-with"))
    monkeypatch.setattr(connecting.viewer_service, "start", lambda *args, **kwargs: None)
    chosen = tmp_path / "chosen"
    try:
        connecting.connect({"instrument": mock_microscope.NAME, "output_root": str(chosen)})
        assert state.the_run().parent == chosen
    finally:
        connecting.disconnect()
    monkeypatch.setattr(connecting, "get_instruments", lambda: {})
    assert the_answer("instruments")["output_root"] == str(chosen)


def test_a_folder_no_run_could_be_made_in_is_not_offered_again(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "output_root", str(tmp_path / "started-with"))

    def no_permission(root, name):
        raise PermissionError(f"no permission to write in {root}")

    monkeypatch.setattr(connecting, "prepare_experiment", no_permission)
    with pytest.raises(PermissionError):
        connecting.connect({"instrument": mock_microscope.NAME, "output_root": str(tmp_path / "locked")})
    assert state.output_root == str(tmp_path / "started-with")


def test_without_a_folder_from_either_the_operator_or_the_start_connect_says_where_to_give_one(monkeypatch):
    monkeypatch.setattr(state, "output_root", None)
    with pytest.raises(RuntimeError, match="Output folder"):
        connecting.connect({"instrument": mock_microscope.NAME})
