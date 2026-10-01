"""Tests for the driver registry.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json

import pytest

from zmart_controller import registry


@pytest.fixture
def scratch_identity():
    """A throwaway identity, removed from the registry after the test."""
    connection = {"vendor": "test", "microscope": "scratch", "api": "t-api"}
    yield connection
    registry.REGISTRY.pop(registry._identity(connection), None)


def _full_ops():
    return {name: (lambda *a, **k: None) for name in registry.OPS}


class TestRegister:
    def test_missing_ops_raise(self, scratch_identity):
        with pytest.raises(ValueError, match="missing ops"):
            registry.register(scratch_identity, ops={"connect": lambda c: None})

    def test_missing_identity_keys_raise_without_values(self):
        # the error must list key names only -- connection dicts may carry credentials
        with pytest.raises(ValueError) as err:
            registry.register({"vendor": "test", "password": "hunter2"}, ops=_full_ops())
        assert "microscope" in str(err.value)
        assert "hunter2" not in str(err.value)

    def test_duplicate_identity_overwrites_with_warning(self, scratch_identity, caplog):
        registry.register(scratch_identity, ops=_full_ops())
        with caplog.at_level("WARNING"):
            registry.register(scratch_identity, ops=_full_ops())
        assert "already registered" in caplog.text

    def test_connection_dict_is_copied(self, scratch_identity):
        registry.register(scratch_identity, ops=_full_ops())
        scratch_identity["client"] = "mutated-later"
        stored = next(i for i in registry.get_instruments() if i["microscope"] == "scratch")
        assert "client" not in stored


class TestGetInstruments:
    def test_returns_copies(self):
        first = registry.get_instruments()[0]
        first["vendor"] = "vandalized"
        assert registry.get_instruments()[0]["vendor"] != "vandalized"

    def test_sorted_by_identity(self, scratch_identity):
        registry.register(scratch_identity, ops=_full_ops())
        vendors = [i["vendor"] for i in registry.get_instruments()]
        assert vendors == sorted(vendors)

    def test_mock_is_registered(self):
        assert any(i["vendor"] == "mock" for i in registry.get_instruments())


class TestDiscovery:
    def test_installed_driver_is_found_without_an_import(self, monkeypatch):
        # Pretend a package is installed that announces the mock as a driver.
        from importlib.metadata import EntryPoint

        fake = EntryPoint("fake", "zmart_driver_mock", registry.ENTRY_POINT_GROUP)
        monkeypatch.setattr(
            registry,
            "entry_points",
            lambda group: [fake] if group == registry.ENTRY_POINT_GROUP else [],
        )
        monkeypatch.setattr(registry, "_discovered", False)
        registry.REGISTRY.pop(("mock", "mock-scope", "mock-api"), None)

        assert any(i["vendor"] == "mock" for i in registry.get_instruments())

    def test_a_broken_driver_does_not_hide_the_others(self, monkeypatch, caplog):
        from importlib.metadata import EntryPoint

        broken = EntryPoint("broken", "no_such_package_xyz", registry.ENTRY_POINT_GROUP)
        monkeypatch.setattr(registry, "entry_points", lambda group: [broken])
        monkeypatch.setattr(registry, "_discovered", False)
        with caplog.at_level("ERROR"):
            registry.get_instruments()  # must not raise
        assert "broken" in caplog.text


FUNCTIONS = """
from zmart_driver_mock.zmart_controller import (
    connect, disconnect, get_info, get_actuators, get_xyz, set_xyz, get_state,
    set_state, get_acquisition_options, acquire, get_procedures, run_procedure,
)
"""


def make_driver(root, microscope, *, functions=FUNCTIONS, manifest=None, plugin=True):
    """Write a driver folder: zmart_controller/zmart.json + __init__.py with the mock's functions."""
    folder = root / "zmart_controller" if plugin else root
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "__init__.py").write_text(functions)
    if manifest is None:
        manifest = {
            "contract": 1,
            "instruments": [{"vendor": "acme", "microscope": microscope, "api": "acme-sdk"}],
        }
    (folder / "zmart.json").write_text(
        manifest if isinstance(manifest, str) else json.dumps(manifest)
    )
    return root


@pytest.fixture
def forget_acme():
    yield
    for key in [k for k in registry.REGISTRY if k[0] == "acme"]:
        registry.REGISTRY.pop(key)


class TestRegisterDriver:
    def test_from_a_driver_folder(self, tmp_path, forget_acme):
        driver = make_driver(tmp_path / "acme", "from-folder")
        added = registry.register_driver(driver)
        assert [i["microscope"] for i in added] == ["from-folder"]
        assert any(i["microscope"] == "from-folder" for i in registry.get_instruments())

    def test_manifest_directly_in_the_folder(self, tmp_path, forget_acme):
        driver = make_driver(tmp_path / "acme", "flat", plugin=False)
        assert [i["microscope"] for i in registry.register_driver(driver)] == ["flat"]

    def test_from_a_module_name(self):
        registry.REGISTRY.pop(("mock", "mock-scope", "mock-api"), None)
        added = registry.register_driver("zmart_driver_mock", remember=False)
        assert [i["vendor"] for i in added] == ["mock"]

    def test_calling_it_twice_is_harmless(self, tmp_path, forget_acme):
        driver = make_driver(tmp_path / "acme", "twice")
        registry.register_driver(driver)
        registry.register_driver(driver)
        assert sum(i["microscope"] == "twice" for i in registry.get_instruments()) == 1

    def test_two_drivers_both_called_zmart_controller_load_side_by_side(
        self, tmp_path, forget_acme
    ):
        first = make_driver(tmp_path / "first", "scope-1")
        second = make_driver(tmp_path / "second", "scope-2")
        registry.register_driver(first)
        registry.register_driver(second)
        names = {i["microscope"] for i in registry.get_instruments() if i["vendor"] == "acme"}
        assert names == {"scope-1", "scope-2"}

    def test_several_instruments_in_one_driver(self, tmp_path, forget_acme):
        manifest = {
            "contract": 1,
            "instruments": [
                {"vendor": "acme", "microscope": "left", "api": "acme-sdk"},
                {"vendor": "acme", "microscope": "right", "api": "acme-sdk", "host": "10.0.0.2"},
            ],
        }
        driver = make_driver(tmp_path / "acme", "", manifest=manifest)
        added = registry.register_driver(driver)
        assert [i["microscope"] for i in added] == ["left", "right"]
        assert added[1]["host"] == "10.0.0.2"

    def test_the_setup_guide_works_on_the_mock(self):
        registry.REGISTRY.pop(("mock", "mock-scope", "mock-api"), None)
        added = registry.register_driver("zmart_driver_mock", remember=False)
        assert [i["vendor"] for i in added] == ["mock"]
        assert registry.remembered_drivers() == []


class TestRegisterDriverRefusals:
    def test_nothing_there(self, tmp_path):
        with pytest.raises(ValueError, match="no driver found"):
            registry.register_driver("acme_does_not_exist_anywhere")
        (tmp_path / "empty").mkdir()
        with pytest.raises(ValueError, match="no zmart_controller/zmart.json"):
            registry.register_driver(tmp_path / "empty")

    def test_a_missing_function_is_named(self, tmp_path):
        functions = FUNCTIONS.replace("get_xyz, ", "")
        driver = make_driver(tmp_path / "acme", "incomplete", functions=functions)
        with pytest.raises(ValueError, match=r"missing these functions: \['get_xyz'\]"):
            registry.register_driver(driver)

    def test_unknown_contract_version(self, tmp_path):
        manifest = {"contract": 99, "instruments": [{"vendor": "a", "microscope": "b", "api": "c"}]}
        driver = make_driver(tmp_path / "acme", "", manifest=manifest)
        with pytest.raises(ValueError, match='"contract": 1'):
            registry.register_driver(driver)

    def test_no_instruments(self, tmp_path):
        driver = make_driver(tmp_path / "acme", "", manifest={"contract": 1, "instruments": []})
        with pytest.raises(ValueError, match="at least one instrument"):
            registry.register_driver(driver)

    def test_instrument_missing_identity(self, tmp_path):
        manifest = {"contract": 1, "instruments": [{"vendor": "acme", "password": "hunter2"}]}
        driver = make_driver(tmp_path / "acme", "", manifest=manifest)
        with pytest.raises(ValueError) as err:
            registry.register_driver(driver)
        assert "microscope" in str(err.value) and "hunter2" not in str(err.value)

    def test_broken_json(self, tmp_path):
        driver = make_driver(tmp_path / "acme", "", manifest="{not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            registry.register_driver(driver)

    def test_nothing_is_registered_when_a_function_is_missing(self, tmp_path):
        functions = FUNCTIONS.replace("acquire, ", "")
        driver = make_driver(tmp_path / "acme", "half", functions=functions)
        with pytest.raises(ValueError):
            registry.register_driver(driver)
        assert not any(i["vendor"] == "acme" for i in registry.get_instruments())


class TestNestedSettingsAreCopied:
    def test_editing_a_listed_instrument_changes_nothing_stored(self, scratch_identity):
        given = dict(scratch_identity, origin={"x": 0.0, "y": 0.0, "z": 0.0})
        registry.register(given, ops=_full_ops())

        listed = next(i for i in registry.get_instruments() if i["microscope"] == "scratch")
        listed["origin"]["x"] = 500.0

        again = next(i for i in registry.get_instruments() if i["microscope"] == "scratch")
        assert again["origin"]["x"] == 0.0
        assert given["origin"]["x"] == 0.0

    def test_editing_the_input_later_changes_nothing_stored(self, scratch_identity):
        given = dict(scratch_identity, origin={"x": 0.0})
        registry.register(given, ops=_full_ops())
        given["origin"]["x"] = 500.0
        stored = next(i for i in registry.get_instruments() if i["microscope"] == "scratch")
        assert stored["origin"]["x"] == 0.0


class TestRememberedDrivers:
    def test_a_registered_driver_is_remembered_and_plugged_in_next_session(
        self, tmp_path, forget_acme, monkeypatch
    ):
        driver = make_driver(tmp_path / "acme", "kept")
        registry.register_driver(driver)
        assert registry.remembered_drivers() == [str(driver.resolve())]

        # A new session: nothing registered, nothing discovered yet.
        registry.REGISTRY.pop(("acme", "kept", "acme-sdk"))
        monkeypatch.setattr(registry, "_discovered", False)
        assert any(i["microscope"] == "kept" for i in registry.get_instruments())

    def test_remember_false_leaves_no_trace(self, tmp_path, forget_acme):
        registry.register_driver(make_driver(tmp_path / "acme", "once"), remember=False)
        assert registry.remembered_drivers() == []

    def test_forget_driver(self, tmp_path, forget_acme):
        driver = make_driver(tmp_path / "acme", "forgot")
        registry.register_driver(driver)
        assert registry.forget_driver(driver) is True
        assert registry.remembered_drivers() == []
        assert registry.forget_driver(driver) is False

    def test_a_remembered_driver_that_vanished_is_skipped(self, monkeypatch, caplog):
        registry._save_remembered(["/no/such/place/acme_gone_driver"])
        monkeypatch.setattr(registry, "_discovered", False)
        with caplog.at_level("ERROR"):
            registry.get_instruments()  # must not raise
        assert "acme_gone_driver" in caplog.text


class TestConfigRoot:
    def test_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZMART_MICROSCOPY_ROOT", str(tmp_path))
        assert registry.config_root() == tmp_path

    def test_per_os_default(self, monkeypatch):
        monkeypatch.delenv("ZMART_MICROSCOPY_ROOT", raising=False)
        monkeypatch.setattr(registry.platform, "system", lambda: "Windows")
        monkeypatch.setenv("PROGRAMDATA", r"C:\\ProgramData")
        assert str(registry.config_root()).endswith("zmart-microscopy")
        monkeypatch.setattr(registry.platform, "system", lambda: "Darwin")
        assert registry.config_root() == registry.Path(
            "/Library/Application Support/zmart-microscopy"
        )
        monkeypatch.setattr(registry.platform, "system", lambda: "Linux")
        assert registry.config_root() == registry.Path("/etc/zmart-microscopy")
