"""The setup registry: what it accepts, what it refuses, and what it never touches."""

from __future__ import annotations

import pytest

from zmart_setup import registry


@pytest.fixture(autouse=True)
def _a_clean_registry(monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY", {})


def _ops(**extra):
    base = {name: (lambda *a, **k: None) for name in registry.OPS}
    base.update(extra)
    return base


CONNECTION = {"vendor": "v", "microscope": "m", "api": "a", "client": "c"}


def test_a_complete_table_registers_and_is_listed_without_hardware():
    registry.register(CONNECTION, ops=_ops())
    assert registry.get_instruments() == [CONNECTION]


def test_a_missing_required_op_is_refused_by_name():
    incomplete = _ops()
    del incomplete["publish"]
    with pytest.raises(ValueError, match=r"missing \['publish'\]"):
        registry.register(CONNECTION, ops=incomplete)


def test_an_unknown_op_is_refused_rather_than_ignored():
    """A misspelt op would otherwise be a silent gap on the page."""
    with pytest.raises(ValueError, match="unknown ops"):
        registry.register(CONNECTION, ops=_ops(publsh=lambda *a: None))


def test_the_optional_ops_are_allowed():
    registry.register(CONNECTION, ops=_ops(objective=lambda h: {}, markers=lambda h: {}))
    ops, _ = registry.resolve(CONNECTION)
    assert "objective" in ops and "markers" in ops


def test_an_incomplete_identity_names_keys_never_values():
    with pytest.raises(ValueError) as caught:
        registry.register({"vendor": "v", "password": "hunter2"}, ops=_ops())
    assert "hunter2" not in str(caught.value)
    assert "microscope" in str(caught.value)


def test_resolve_lays_what_was_asked_over_what_was_registered():
    registry.register(CONNECTION, ops=_ops())
    _, connection = registry.resolve({**CONNECTION, "password": "p", "output_root": "/tmp/x"})
    assert connection["client"] == "c"
    assert connection["password"] == "p"
    assert connection["output_root"] == "/tmp/x"


def test_an_unregistered_identity_is_a_plain_error():
    with pytest.raises(ValueError, match="no setup driver registered"):
        registry.resolve(CONNECTION)


def test_the_setup_package_never_imports_the_controller():
    """The boundary in one line: nothing here can reach a driving session."""
    import importlib
    import sys

    for name in ("zmart_setup", "zmart_setup.registry", "zmart_setup.layer"):
        module = importlib.import_module(name)
        source = open(module.__file__, encoding="utf-8").read()
        assert "import zmart_controller" not in source
        assert "from zmart_controller" not in source
    assert "zmart_setup" in sys.modules
