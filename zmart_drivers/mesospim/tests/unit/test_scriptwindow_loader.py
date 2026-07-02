"""Regression tests for the Script-Window loader (the exec-scope fix).

mesoSPIM runs a loaded script via ``exec(script)`` inside
``mesoSPIM_Core.execute_script`` -- a *method*, so ``globals()`` (the mesoSPIM
module) and ``locals()`` (the method frame, holding ``self``) are different
dicts. A *module*-shaped script fails in that scope: its top-level names land in
locals but classes/defaults/inter-function calls resolve via globals, raising
``NameError``. The command server is module-shaped, so it must be loaded by a
FLAT ``scriptwindow_loader.py`` that just imports it and calls ``start(self)``.

These tests reproduce that exact exec scope and lock the fix in. They need no
PyQt5: the server module top-level is Qt-free, and ``MesospimCommandServer`` is
monkeypatched so no real socket opens.

Author: Thom de Hoog (ZMB, University of Zurich). License: MIT.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).resolve().parents[2] / "server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))


class _FakeServer:
    """Stand-in for MesospimCommandServer (no socket)."""

    def __init__(self, core, host=None, port=None, token=None):
        self.core = core
        self.host = host
        self.port = port
        self.token = token
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeCore:
    """Stand-in for mesoSPIM_Core: start() only needs attribute get/set on it."""


def _exec_like_scriptwindow(source, core):
    """Reproduce mesoSPIM_Core.execute_script: ``exec(source)`` inside a method
    with the Core bound as ``self`` in the local scope (globals() != locals())."""
    self = core  # noqa: F841 - the Script Window binds the live Core as `self`
    exec(source)


def _read(name):
    return (_SERVER_DIR / name).read_text(encoding="utf-8")


def test_loader_starts_server_under_scriptwindow_exec(monkeypatch):
    """The flat loader survives exec-in-method-scope and starts the server."""
    import mesospim_command_server as srv

    monkeypatch.setattr(srv, "MesospimCommandServer", _FakeServer)
    core = _FakeCore()
    _exec_like_scriptwindow(_read("scriptwindow_loader.py"), core)
    assert isinstance(core._zmart_cmd_server, _FakeServer)
    assert core._zmart_cmd_server.core is core


def test_raw_server_module_cannot_be_scriptwindow_loaded():
    """Documents WHY the loader exists: exec'ing the module file directly in
    method scope raises NameError (module-level names resolve as globals)."""
    with pytest.raises(NameError):
        _exec_like_scriptwindow(_read("mesospim_command_server.py"), _FakeCore())


def test_loader_requires_core_as_self():
    """Run outside the Script Window (no ``self``) -> a clear error, not a crash."""
    with pytest.raises(RuntimeError):
        exec(_read("scriptwindow_loader.py"), {"__name__": "loader"})


def test_start_is_reload_safe(monkeypatch):
    """start() stops a prior instance so re-loading never hits 'address in use'."""
    import mesospim_command_server as srv

    monkeypatch.setattr(srv, "MesospimCommandServer", _FakeServer)
    core = _FakeCore()
    first = srv.start(core)
    second = srv.start(core)
    assert first.stopped is True
    assert first is not second
    assert core._zmart_cmd_server is second
