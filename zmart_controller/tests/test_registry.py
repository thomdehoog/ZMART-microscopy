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
        with pytest.raises(ValueError, match="missing or non-callable ops"):
            registry.register(scratch_identity, ops={"connect": lambda c: None})

    def test_non_callable_ops_raise(self, scratch_identity):
        # A table full of None placeholders must fail here, at registration,
        # not later with a bare TypeError inside set_instrument.
        ops = _full_ops()
        ops["acquire"] = None
        with pytest.raises(ValueError, match="missing or non-callable ops.*acquire"):
            registry.register(scratch_identity, ops=ops)

    def test_non_string_identity_raises(self):
        # A None placeholder left in a copied template must fail at register,
        # not poison get_instruments() for everyone with a sorting TypeError.
        with pytest.raises(ValueError, match="must be strings"):
            registry.register(
                {"vendor": None, "microscope": "scratch", "api": "t-api"}, ops=_full_ops()
            )

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
