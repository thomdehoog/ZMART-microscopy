"""Unit tests for preflight capability checks.

Today this exercises only the SUPPORTS_NONE_NPICKS capability check, which
guards against running against a stale smart-analysis version that doesn't
accept n_picks=None.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


class _DummyClient:
    """Minimal stand-in; only used to verify preflight reaches/exceeds the
    capability-check site before any hardware interaction."""


def _install_fake_smart_analysis(
    tmp_path: Path,
    *,
    supports_flag: bool | None,
) -> Path:
    """Build a minimal directory structure that looks like smart-analysis
    enough to be imported. supports_flag controls SUPPORTS_NONE_NPICKS:
        True / False -> the attribute exists with that value
        None         -> the attribute is omitted (AttributeError path)
    """
    repo = tmp_path / "smart-analysis"
    pkg = repo / "workflows" / "target_acquisition" / "steps"
    pkg.mkdir(parents=True)
    for parent in [
        repo / "workflows",
        repo / "workflows" / "target_acquisition",
        repo / "workflows" / "target_acquisition" / "steps",
    ]:
        (parent / "__init__.py").write_text("")
    if supports_flag is None:
        (pkg / "pick_targets.py").write_text("")
    else:
        (pkg / "pick_targets.py").write_text(
            f"SUPPORTS_NONE_NPICKS = {supports_flag}\n"
        )
    return repo


@pytest.fixture(autouse=True)
def _isolate_workflows_imports():
    """Remove any cached `workflows.*` modules and `workflows`-rooted
    sys.path entries before AND after each test, so capability-check
    imports resolve against the fixture's fake repo rather than a
    previously-imported real one."""
    def _scrub():
        for name in [n for n in list(sys.modules) if n == "workflows" or n.startswith("workflows.")]:
            sys.modules.pop(name, None)
    _scrub()
    saved_path = list(sys.path)
    yield
    sys.path[:] = saved_path
    _scrub()


def _try_capability_check(analysis_repo: Path) -> None:
    """Replicates the capability-check block from preflight.preflight().
    Kept in the test rather than importing preflight whole because
    preflight() needs LAS X + driver dependencies we can't mock cheaply."""
    sys.path.insert(0, str(analysis_repo))
    try:
        from workflows.target_acquisition.steps.pick_targets import (
            SUPPORTS_NONE_NPICKS,
        )
        if not SUPPORTS_NONE_NPICKS:
            raise RuntimeError
    except (ImportError, AttributeError, RuntimeError):
        raise RuntimeError(
            f"smart-analysis at {analysis_repo} does not support n_picks=None. "
            f"Update to the latest version."
        )


def test_preflight_capability_check_passes_when_flag_true(tmp_path):
    repo = _install_fake_smart_analysis(tmp_path, supports_flag=True)
    _try_capability_check(repo)   # should not raise


def test_preflight_capability_check_fails_on_old_engine(tmp_path):
    repo = _install_fake_smart_analysis(tmp_path, supports_flag=False)
    with pytest.raises(RuntimeError, match="does not support n_picks=None"):
        _try_capability_check(repo)


def test_preflight_capability_check_fails_when_flag_missing(tmp_path):
    repo = _install_fake_smart_analysis(tmp_path, supports_flag=None)
    with pytest.raises(RuntimeError, match="does not support n_picks=None"):
        _try_capability_check(repo)


# ─── Re-run safety: _LAST_CTX mechanism ───────────────────────────


def test_shutdown_prior_ctx_calls_shutdown_and_clears_slot(monkeypatch):
    """When _LAST_CTX is non-None, _shutdown_prior_ctx_if_any() must
    call .shutdown() on the prior ctx and clear the slot. This is the
    load-bearing piece of re-run idempotency: a second preflight() in
    the same Python session tears down the first ctx before starting
    fresh.
    """
    from unittest.mock import MagicMock
    # workflow.__init__ re-exports the function `preflight`, which shadows
    # the submodule in the package namespace. Reach the module via
    # sys.modules to monkeypatch its module-level _LAST_CTX.
    import workflow.preflight   # noqa: F401  -- ensure submodule is loaded
    preflight_mod = sys.modules["workflow.preflight"]

    prior = MagicMock(name="prior_ctx")
    monkeypatch.setattr(preflight_mod, "_LAST_CTX", prior)

    preflight_mod._shutdown_prior_ctx_if_any()

    prior.shutdown.assert_called_once_with()
    assert preflight_mod._LAST_CTX is None


def test_shutdown_prior_ctx_is_noop_when_slot_empty(monkeypatch):
    """First preflight() in the session has _LAST_CTX is None; the
    helper must be a no-op (not call .shutdown() on None).
    """
    # workflow.__init__ re-exports the function `preflight`, which shadows
    # the submodule in the package namespace. Reach the module via
    # sys.modules to monkeypatch its module-level _LAST_CTX.
    import workflow.preflight   # noqa: F401  -- ensure submodule is loaded
    preflight_mod = sys.modules["workflow.preflight"]

    monkeypatch.setattr(preflight_mod, "_LAST_CTX", None)

    preflight_mod._shutdown_prior_ctx_if_any()   # must not raise

    assert preflight_mod._LAST_CTX is None


def test_shutdown_prior_ctx_clears_slot_even_when_shutdown_raises(monkeypatch):
    """If the prior ctx's shutdown() raises, the slot still gets cleared
    so a single failure does not lock the mechanism for the rest of the
    session.
    """
    from unittest.mock import MagicMock
    # workflow.__init__ re-exports the function `preflight`, which shadows
    # the submodule in the package namespace. Reach the module via
    # sys.modules to monkeypatch its module-level _LAST_CTX.
    import workflow.preflight   # noqa: F401  -- ensure submodule is loaded
    preflight_mod = sys.modules["workflow.preflight"]

    prior = MagicMock(name="prior_ctx")
    prior.shutdown.side_effect = RuntimeError("engine already dead")
    monkeypatch.setattr(preflight_mod, "_LAST_CTX", prior)

    # Helper swallows + logs the exception; should not propagate.
    preflight_mod._shutdown_prior_ctx_if_any()

    prior.shutdown.assert_called_once_with()
    assert preflight_mod._LAST_CTX is None
