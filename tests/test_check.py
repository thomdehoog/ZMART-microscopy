"""Tests for check_driver, the "does my driver fit?" check."""

import pytest

from zmart_controller import check_driver, registry

MOCK = ("mock", "mock-scope", "mock-api")


def _mock_instrument():
    return {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api"}


def _break(monkeypatch, name, func):
    """Swap one of the mock's functions in the table the registry uses."""
    monkeypatch.setitem(registry.REGISTRY[MOCK]["ops"], name, func)


def test_the_mock_fits():
    assert check_driver(_mock_instrument()) == []


def test_problems_are_named(monkeypatch):
    # Break two answers and expect plain sentences about those two, nothing else.
    _break(monkeypatch, "get_xyz", lambda handle, **kw: {"success": True, "report": {"x": {}}})
    _break(monkeypatch, "get_info", lambda handle: {"success": True, "report": {}})
    problems = check_driver(_mock_instrument())
    assert "get_info: the report must contain output_root" in problems
    assert any(p.startswith("get_xyz: axis 'x' is missing") for p in problems)
    assert any(p.startswith("get_xyz: axis 'y' is missing") for p in problems)
    assert not any(p.startswith("get_state") for p in problems)


def test_a_bare_answer_without_the_envelope_is_reported(monkeypatch):
    _break(monkeypatch, "get_procedures", lambda handle: {"autofocus": {}})
    problems = check_driver(_mock_instrument())
    assert any('get_procedures must return {"success"' in p for p in problems)


@pytest.fixture(autouse=True)
def _mock_present():
    if MOCK not in registry.REGISTRY:
        registry.register_driver("zmart_driver_mock", remember=False)
