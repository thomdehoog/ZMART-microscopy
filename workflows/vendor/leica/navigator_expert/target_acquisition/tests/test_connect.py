"""Tests for workflow.connect_lasx() helper.

connect_lasx() owns the LAS X CAM API connect handshake so the operator
notebook can ask for "connect" in one call without leaking LasxApi
naming / call shape into operator code.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock


def _install_fake_lasxapi(monkeypatch) -> MagicMock:
    """Install a fake `LasxApi` module in sys.modules. Returns the fake
    client class that connect_lasx() will return after Connect()."""
    fake_client_cls = MagicMock(name="LasxApiClientPyModel")
    fake_connector = MagicMock(name="PYLICamApiConnector")
    fake_connector.LasxApiClientPyModel = fake_client_cls
    fake_module = MagicMock(name="LasxApi")
    fake_module.PYLICamApiConnector = fake_connector
    monkeypatch.setitem(sys.modules, "LasxApi", fake_module)
    return fake_client_cls


def test_connect_lasx_returns_connected_client(monkeypatch):
    """connect_lasx() imports LasxApi.PYLICamApiConnector, fetches the
    LasxApiClientPyModel class, calls Connect(role), and returns the
    client. Default role is 'PythonClient'.
    """
    fake_client = _install_fake_lasxapi(monkeypatch)

    from workflow import connect_lasx

    result = connect_lasx()

    fake_client.Connect.assert_called_once_with("PythonClient")
    assert result is fake_client


def test_connect_lasx_passes_role_through(monkeypatch):
    """The role argument is threaded through to client.Connect."""
    fake_client = _install_fake_lasxapi(monkeypatch)

    from workflow import connect_lasx

    result = connect_lasx(role="OtherClient")

    fake_client.Connect.assert_called_once_with("OtherClient")
    assert result is fake_client
