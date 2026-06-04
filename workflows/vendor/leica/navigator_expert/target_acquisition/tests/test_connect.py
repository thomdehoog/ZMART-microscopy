"""Tests for pipeline.connect_lasx() helper.

connect_lasx() owns the LAS X CAM API connect handshake so the operator
notebook can ask for "connect" in one call without leaking runtime loading
details into operator code.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_connect_lasx_returns_connected_client(monkeypatch):
    """connect_lasx() delegates to the shared driver session helper."""
    fake_client = MagicMock(name="client")
    connect_python_client = MagicMock(return_value=fake_client)
    monkeypatch.setattr(
        "navigator_expert.core.session.connect_python_client",
        connect_python_client,
    )

    from pipeline import connect_lasx

    result = connect_lasx()

    connect_python_client.assert_called_once_with(client_name="PythonClient")
    assert result is fake_client


def test_connect_lasx_passes_role_through(monkeypatch):
    """The role argument is threaded through to client.Connect."""
    fake_client = MagicMock(name="client")
    connect_python_client = MagicMock(return_value=fake_client)
    monkeypatch.setattr(
        "navigator_expert.core.session.connect_python_client",
        connect_python_client,
    )

    from pipeline import connect_lasx

    result = connect_lasx(role="OtherClient")

    connect_python_client.assert_called_once_with(client_name="OtherClient")
    assert result is fake_client
