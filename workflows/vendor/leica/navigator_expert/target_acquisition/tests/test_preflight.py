"""Unit tests for preflight analysis-repo import handling."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


def _install_fake_analysis_repo(tmp_path: Path) -> Path:
    """Build the minimal smart-analysis shape needed by preflight."""
    repo = tmp_path / "smart-analysis"
    engine_pkg = repo / "engine"
    engine_pkg.mkdir(parents=True)
    (engine_pkg / "__init__.py").write_text(
        "class Engine:\n"
        "    pass\n"
    )
    return repo


def _preflight_module():
    import pipeline.preflight  # noqa: F401  -- ensure submodule is loaded
    return sys.modules["pipeline.preflight"]


@pytest.fixture(autouse=True)
def _isolate_analysis_imports():
    """Keep tests independent from cached analysis-package modules."""
    def _scrub():
        for name in [
            n for n in list(sys.modules)
            if (
                n == "workflows"
                or n.startswith("workflows.")
                or n == "engine"
                or n.startswith("engine.")
            )
        ]:
            sys.modules.pop(name, None)

    _scrub()
    saved_path = list(sys.path)
    yield
    sys.path[:] = saved_path
    _scrub()


def test_analysis_repo_is_first_import_root(tmp_path):
    repo = _install_fake_analysis_repo(tmp_path)
    mod = _preflight_module()
    sys.path.insert(0, "already-first")
    sys.path.append(str(repo))

    mod._put_analysis_repo_first(repo)

    assert sys.path[0] == str(repo)
    assert sys.path.count(str(repo)) == 1


def test_analysis_engine_import_uses_configured_repo(tmp_path):
    repo = _install_fake_analysis_repo(tmp_path)
    mod = _preflight_module()

    Engine = mod._analysis_engine_class(repo)

    assert Engine.__module__ == "engine"
    assert Path(sys.modules["engine"].__file__).resolve().is_relative_to(repo)


def test_analysis_engine_import_rejects_cached_wrong_engine(tmp_path):
    repo = _install_fake_analysis_repo(tmp_path)
    wrong = types.ModuleType("engine")
    wrong.__file__ = str(tmp_path / "other_repo" / "engine" / "__init__.py")
    wrong.Engine = object
    sys.modules["engine"] = wrong
    mod = _preflight_module()

    with pytest.raises(RuntimeError, match="not from Config.analysis_repo"):
        mod._analysis_engine_class(repo)


def test_analysis_engine_import_ignores_cached_workflows_package(tmp_path):
    repo = _install_fake_analysis_repo(tmp_path)
    sys.modules["workflows"] = types.ModuleType("workflows")
    mod = _preflight_module()

    Engine = mod._analysis_engine_class(repo)

    assert Engine.__module__ == "engine"


def test_shutdown_prior_ctx_calls_shutdown_and_clears_slot(monkeypatch):
    """A second preflight tears down the previous context before starting."""
    from unittest.mock import MagicMock

    mod = _preflight_module()
    prior = MagicMock(name="prior_ctx")
    monkeypatch.setattr(mod, "_LAST_CTX", prior)

    mod._shutdown_prior_ctx_if_any()

    prior.shutdown.assert_called_once_with()
    assert mod._LAST_CTX is None


def test_shutdown_prior_ctx_is_noop_when_slot_empty(monkeypatch):
    """First preflight in a session has no previous context to close."""
    mod = _preflight_module()
    monkeypatch.setattr(mod, "_LAST_CTX", None)

    mod._shutdown_prior_ctx_if_any()

    assert mod._LAST_CTX is None


def test_shutdown_prior_ctx_clears_slot_even_when_shutdown_raises(monkeypatch):
    """A failed shutdown must not poison future preflight calls."""
    from unittest.mock import MagicMock

    mod = _preflight_module()
    prior = MagicMock(name="prior_ctx")
    prior.shutdown.side_effect = RuntimeError("engine already dead")
    monkeypatch.setattr(mod, "_LAST_CTX", prior)

    mod._shutdown_prior_ctx_if_any()

    prior.shutdown.assert_called_once_with()
    assert mod._LAST_CTX is None
