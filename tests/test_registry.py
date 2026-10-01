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
        with pytest.raises(ValueError, match="missing ops"):
            registry.register(scratch_identity, ops={"connect": lambda c: None})

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


class TestDiscovery:
    def test_installed_driver_is_found_without_an_import(self, monkeypatch):
        # Pretend a package is installed that announces the mock as a driver.
        from importlib.metadata import EntryPoint

        fake = EntryPoint("fake", "zmart_controller.mock:register", registry.ENTRY_POINT_GROUP)
        monkeypatch.setattr(
            registry,
            "entry_points",
            lambda group: [fake] if group == registry.ENTRY_POINT_GROUP else [],
        )
        monkeypatch.setattr(registry, "_discovered", False)
        registry.REGISTRY.pop(("mock", "mock-scope", "mock-api"), None)

        assert any(i["vendor"] == "mock" for i in registry.get_instruments())

    def test_a_broken_driver_does_not_hide_the_others(self, monkeypatch, caplog):
        from importlib.metadata import EntryPoint

        broken = EntryPoint("broken", "no_such_package_xyz:register", registry.ENTRY_POINT_GROUP)
        monkeypatch.setattr(registry, "entry_points", lambda group: [broken])
        monkeypatch.setattr(registry, "_discovered", False)
        with caplog.at_level("ERROR"):
            registry.get_instruments()  # must not raise
        assert "broken" in caplog.text


DRIVER_SOURCE = """
from zmart_controller import mock
from zmart_controller.registry import OPS, register

ops = {name: getattr(mock, name) for name in OPS}
register({"vendor": "acme", "microscope": "%s", "api": "acme-sdk"}, ops=ops)
"""


@pytest.fixture
def forget_acme():
    yield
    for key in [k for k in registry.REGISTRY if k[0] == "acme"]:
        registry.REGISTRY.pop(key)
    import sys

    for name in [n for n in sys.modules if n.startswith("acme_")]:
        del sys.modules[name]


class TestRegisterDriver:
    def test_from_a_file(self, tmp_path, forget_acme):
        driver = tmp_path / "acme_file_driver.py"
        driver.write_text(DRIVER_SOURCE % "from-file")
        added = registry.register_driver(driver)
        assert [i["microscope"] for i in added] == ["from-file"]
        assert any(i["microscope"] == "from-file" for i in registry.get_instruments())

    def test_from_a_package_folder(self, tmp_path, forget_acme):
        package = tmp_path / "acme_pkg_driver"
        package.mkdir()
        (package / "__init__.py").write_text(DRIVER_SOURCE % "from-folder")
        added = registry.register_driver(package)
        assert [i["microscope"] for i in added] == ["from-folder"]

    def test_from_a_module_name(self, tmp_path, forget_acme, monkeypatch):
        (tmp_path / "acme_named_driver.py").write_text(DRIVER_SOURCE % "from-name")
        monkeypatch.syspath_prepend(str(tmp_path))
        added = registry.register_driver("acme_named_driver")
        assert [i["microscope"] for i in added] == ["from-name"]

    def test_calling_it_twice_is_harmless(self, tmp_path, forget_acme):
        driver = tmp_path / "acme_twice_driver.py"
        driver.write_text(DRIVER_SOURCE % "twice")
        registry.register_driver(driver)
        assert registry.register_driver(driver) == []  # already plugged in
        assert sum(i["microscope"] == "twice" for i in registry.get_instruments()) == 1

    def test_a_register_function_is_called_when_import_alone_does_nothing(
        self, tmp_path, forget_acme
    ):
        driver = tmp_path / "acme_lazy_driver.py"
        driver.write_text(
            "def register():\n"
            + "\n".join("    " + line for line in (DRIVER_SOURCE % "lazy").splitlines())
        )
        added = registry.register_driver(driver)
        assert [i["microscope"] for i in added] == ["lazy"]

    def test_nothing_there_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="no driver found"):
            registry.register_driver("acme_does_not_exist_anywhere")
        empty = tmp_path / "acme_empty_driver.py"
        empty.write_text("x = 1\n")
        with pytest.raises(ValueError, match="registered no instrument"):
            registry.register_driver(empty)

    def test_the_setup_guide_works_on_the_mock(self):
        # docs/setup.md, step 3, with the mock in place of a real driver.
        registry.REGISTRY.pop(("mock", "mock-scope", "mock-api"), None)
        added = registry.register_driver("zmart_controller.mock")
        assert [i["vendor"] for i in added] == ["mock"]


class TestRegisterDriverEdgeCases:
    """Cases from the release candidate review that the tests above miss."""

    def test_two_files_with_the_same_name_both_load(self, tmp_path, forget_acme):
        # Two microscopes may each keep their driver in a file called driver.py.
        # The second must load its own file, not reuse the first.
        import sys

        first = tmp_path / "first" / "acme_same_name.py"
        second = tmp_path / "second" / "acme_same_name.py"
        first.parent.mkdir()
        second.parent.mkdir()
        first.write_text(DRIVER_SOURCE % "first-scope")
        second.write_text(DRIVER_SOURCE % "second-scope")
        try:
            assert [i["microscope"] for i in registry.register_driver(first)] == ["first-scope"]
            assert [i["microscope"] for i in registry.register_driver(second)] == ["second-scope"]
            # Calling it again for either file reuses that file's module.
            assert registry.register_driver(first) == []
            assert registry.register_driver(second) == []
        finally:
            for name in [n for n in sys.modules if n.startswith("acme_same_name")]:
                del sys.modules[name]

    def test_a_different_package_with_a_taken_name_is_refused(self, tmp_path, forget_acme):
        import sys

        first = tmp_path / "first" / "acme_same_pkg"
        second = tmp_path / "second" / "acme_same_pkg"
        for folder, scope in ((first, "pkg-first"), (second, "pkg-second")):
            folder.mkdir(parents=True)
            (folder / "__init__.py").write_text(DRIVER_SOURCE % scope)
        try:
            registry.register_driver(first)
            with pytest.raises(ValueError, match="already loaded"):
                registry.register_driver(second)
        finally:
            sys.modules.pop("acme_same_pkg", None)
            for folder in (first.parent, second.parent):
                if str(folder) in sys.path:
                    sys.path.remove(str(folder))

    def test_a_replacement_is_reported_not_refused(self, tmp_path, forget_acme):
        registry.register(
            {"vendor": "acme", "microscope": "replaced", "api": "acme-sdk"}, ops=_full_ops()
        )
        driver = tmp_path / "acme_replacing_driver.py"
        driver.write_text(DRIVER_SOURCE % "replaced")
        added = registry.register_driver(driver)
        assert [i["microscope"] for i in added] == ["replaced"]
        # The new driver's functions are the ones in use.
        from zmart_controller import mock

        ops = registry.REGISTRY[("acme", "replaced", "acme-sdk")]["ops"]
        assert ops["connect"] is mock.connect

    def test_a_register_function_from_a_submodule_is_called(self, tmp_path, forget_acme):
        import sys

        package = tmp_path / "acme_split_driver"
        package.mkdir()
        (package / "__init__.py").write_text("from .adapter import register\n")
        (package / "adapter.py").write_text(
            "def register():\n"
            + "\n".join("    " + line for line in (DRIVER_SOURCE % "split").splitlines())
        )
        try:
            for _ in range(2):  # the second call must give the same answer
                added = registry.register_driver(package)
                assert [i["microscope"] for i in added] == ["split"]
        finally:
            for name in [n for n in sys.modules if n.startswith("acme_split_driver")]:
                del sys.modules[name]
            sys.path.remove(str(tmp_path))


class TestNestedSettingsAreCopied:
    def test_editing_a_listed_instrument_changes_nothing_stored(self, scratch_identity):
        given = dict(scratch_identity, origin={"x": 0.0, "y": 0.0, "z": 0.0})
        registry.register(given, ops=_full_ops())

        listed = next(i for i in registry.get_instruments() if i["microscope"] == "scratch")
        listed["origin"]["x"] = 500.0

        again = next(i for i in registry.get_instruments() if i["microscope"] == "scratch")
        assert again["origin"]["x"] == 0.0
        assert given["origin"]["x"] == 0.0

    def test_editing_the_input_later_changes_nothing_stored(self, scratch_identity):
        given = dict(scratch_identity, origin={"x": 0.0})
        registry.register(given, ops=_full_ops())
        given["origin"]["x"] = 500.0
        stored = next(i for i in registry.get_instruments() if i["microscope"] == "scratch")
        assert stored["origin"]["x"] == 0.0


class TestRememberedDrivers:
    def test_a_registered_driver_is_remembered_and_plugged_in_next_session(
        self, tmp_path, forget_acme, monkeypatch
    ):
        driver = tmp_path / "acme_kept_driver.py"
        driver.write_text(DRIVER_SOURCE % "kept")
        registry.register_driver(driver)
        assert registry.remembered_drivers() == [str(driver.resolve())]

        # A new session: nothing imported, nothing registered, nothing discovered yet.
        import sys

        sys.modules.pop("acme_kept_driver", None)
        registry.REGISTRY.pop(("acme", "kept", "acme-sdk"))
        monkeypatch.setattr(registry, "_discovered", False)
        assert any(i["microscope"] == "kept" for i in registry.get_instruments())

    def test_remember_false_leaves_no_trace(self, tmp_path, forget_acme):
        driver = tmp_path / "acme_once_driver.py"
        driver.write_text(DRIVER_SOURCE % "once")
        registry.register_driver(driver, remember=False)
        assert registry.remembered_drivers() == []

    def test_forget_driver(self, tmp_path, forget_acme):
        driver = tmp_path / "acme_forgot_driver.py"
        driver.write_text(DRIVER_SOURCE % "forgot")
        registry.register_driver(driver)
        assert registry.forget_driver(driver) is True
        assert registry.remembered_drivers() == []
        assert registry.forget_driver(driver) is False

    def test_a_remembered_driver_that_vanished_is_skipped(self, monkeypatch, caplog):
        registry._save_remembered(["/no/such/place/acme_gone_driver.py"])
        monkeypatch.setattr(registry, "_discovered", False)
        with caplog.at_level("ERROR"):
            registry.get_instruments()  # must not raise
        assert "acme_gone_driver" in caplog.text

    def test_a_driver_folder_with_a_plugin_subfolder(self, tmp_path, forget_acme):
        import sys

        root = tmp_path / "acme_whole_driver"
        (root / "zmart_plugin").mkdir(parents=True)
        (root / "vendor_stuff.py").write_text("x = 1\n")
        (root / "zmart_plugin" / "__init__.py").write_text(DRIVER_SOURCE % "plugin-folder")
        try:
            added = registry.register_driver(root, remember=False)
            assert [i["microscope"] for i in added] == ["plugin-folder"]
        finally:
            sys.modules.pop("zmart_plugin", None)
            if str(root) in sys.path:
                sys.path.remove(str(root))


class TestConfigRoot:
    def test_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZMART_MICROSCOPY_ROOT", str(tmp_path))
        assert registry.config_root() == tmp_path

    def test_per_os_default(self, monkeypatch):
        monkeypatch.delenv("ZMART_MICROSCOPY_ROOT", raising=False)
        monkeypatch.setattr(registry.platform, "system", lambda: "Windows")
        monkeypatch.setenv("PROGRAMDATA", r"C:\\ProgramData")
        assert str(registry.config_root()).endswith("zmart-microscopy")
        monkeypatch.setattr(registry.platform, "system", lambda: "Darwin")
        assert registry.config_root() == registry.Path(
            "/Library/Application Support/zmart-microscopy"
        )
        monkeypatch.setattr(registry.platform, "system", lambda: "Linux")
        assert registry.config_root() == registry.Path("/etc/zmart-microscopy")
