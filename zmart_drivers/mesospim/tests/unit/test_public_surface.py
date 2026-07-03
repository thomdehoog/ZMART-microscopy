"""The package public surface: imports, version, session helpers."""

from __future__ import annotations

import mesospim


def test_version_present():
    assert isinstance(mesospim.__version__, str)


def test_all_names_are_importable():
    for name in mesospim.__all__:
        assert hasattr(mesospim, name), f"missing public name: {name}"


def test_key_functions_exposed():
    for name in (
        "connect",
        "close",
        "move_xy",
        "move_z",
        "set_filter",
        "acquire",
        "save",
        "register",
        "load_stage_config",
    ):
        assert callable(getattr(mesospim, name))


def test_connect_close_via_public_api(server):
    client = mesospim.connect({"host": server.host, "port": server.port})
    try:
        assert mesospim.ping(client)
    finally:
        mesospim.close(client)


def test_register_is_safe_without_controller(monkeypatch):
    # register() must not raise even if zmart_controller import fails.
    import builtins

    real_import = builtins.__import__

    def block(name, *a, **k):
        if name.startswith("zmart_controller"):
            raise ImportError("blocked")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", block)
    mesospim.register({"vendor": "mesospim", "microscope": "x", "api": "remote-scripting"})
