"""Tests for the driver registry.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

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

        fake = EntryPoint("fake", "zmart_controller.mock:register", registry.ENTRY_POINT_GROUP)
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

        broken = EntryPoint("broken", "no_such_package_xyz:register", registry.ENTRY_POINT_GROUP)
        monkeypatch.setattr(registry, "entry_points", lambda group: [broken])
        monkeypatch.setattr(registry, "_discovered", False)
        with caplog.at_level("ERROR"):
            registry.get_instruments()  # must not raise
        assert "broken" in caplog.text
