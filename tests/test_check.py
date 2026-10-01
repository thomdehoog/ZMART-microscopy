"""Tests for check_driver, the "does my driver fit?" check."""

import pytest

from zmart_controller import check_driver, mock


def _mock_instrument():
    return {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api"}


def test_the_mock_fits():
    assert check_driver(_mock_instrument()) == []


def test_problems_are_named(monkeypatch):
    # Break two answers and expect two plain sentences, nothing else broken.
    monkeypatch.setattr(
        mock, "get_xyz", lambda handle, **kw: {"success": True, "report": {"x": {}}}
    )
    monkeypatch.setattr(mock, "get_info", lambda handle: {"success": True, "report": {}})
    from zmart_controller import registry

    registry.register_driver(
        "zmart_controller.mock", remember=False
    )  # pick up the patched functions
    problems = check_driver(_mock_instrument())
    assert "get_info: the report must contain output_root" in problems
    assert any(p.startswith("get_xyz: axis 'x' is missing") for p in problems)
    assert any(p.startswith("get_xyz: axis 'y' is missing") for p in problems)
    assert not any(p.startswith("get_state") for p in problems)


def test_a_bare_answer_without_the_envelope_is_reported(monkeypatch):
    monkeypatch.setattr(mock, "get_procedures", lambda handle: {"autofocus": {}})
    from zmart_controller import registry

    registry.register_driver("zmart_controller.mock", remember=False)
    problems = check_driver(_mock_instrument())
    assert any('get_procedures must return {"success"' in p for p in problems)


@pytest.fixture(autouse=True)
def _restore_mock():
    yield
    from zmart_controller import registry

    registry.register_driver("zmart_controller.mock", remember=False)
