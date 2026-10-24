"""Every driver plugs into the installed controller, and the two mock microscopes fit its contract.

A driver reaches the ZMART Controller as a folder that holds
``zmart_controller_plugin/``: a ``zmart_controller_plugin.json`` with its
name and connection, beside the ``ZmartControllerPlugin`` class.
``register_driver`` installs it on the computer once, and from then on it is
listed by ``get_instruments`` and connected to by its name. These checks
plug in every driver in the installed ``zmart-drivers`` that way, each in a
fresh Python as an operator's session would.

No real microscope is connected here: the real drivers would need their
vendor's software, so they are only installed and listed. The two pretend
microscopes need none, so they go one step further: the controller's own
``validate_driver`` connects to them and checks every answer against the
contract. One is the controller's mock (a slide of beads, kept with the
controller's tests and cloned into ``work/`` by install.py, named
``"mock"``), the other the interface's (a section of a mouse kidney, the one
the operator window offers first). Nothing above the controller needs to
know which driver is underneath; the two mocks stand in for all of them, and
a capture is only ever taken on a mock (see ``test_viewer_serves``).

The two mocks have names of their own, so they stand side by side.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from conftest import checkout

#: The drivers in the installed package, by module, with the name the
#: controller lists each under.
DRIVERS = {
    "zmart_drivers.leica.stellaris.navigator_expert": "stellaris",
}


def _the_controllers_mock() -> str:
    """The controller's mock, a driver folder in the controller's clone."""
    return str(checkout("ZMART-controller") / "tests" / "mock_driver")


#: Folders inside the drivers' package that hold tests, examples or
#: investigations rather than a driver.
NOT_A_DRIVER = {"tests", "testing", "spike", "pull_request"}


def _drivers_root() -> Path:
    return Path(importlib.util.find_spec("zmart_drivers").submodule_search_locations[0])


def _module_of(path: Path) -> str:
    """The module name of a folder or file inside the installed drivers' package."""
    parts = path.relative_to(_drivers_root()).with_suffix("").parts
    return ".".join(("zmart_drivers", *parts))


def test_the_lists_here_name_every_driver_installed():
    """Every driver in the installed package is checked below.

    A driver is the folder that holds ``zmart_controller_plugin/`` with its
    ``zmart_controller_plugin.json``. Without this, a new driver added to
    zmart-drivers would quietly go unchecked here.
    """
    root = _drivers_root()

    def a_driver(path: Path) -> bool:
        return not NOT_A_DRIVER & set(path.relative_to(root).parts)

    found = sorted(_module_of(settings.parent.parent)
                   for settings in root.rglob("zmart_controller_plugin/zmart_controller_plugin.json")
                   if a_driver(settings))
    assert found == sorted(DRIVERS)


#: Install one driver from its folder, and say what the controller lists.
INSTALL = """
    import importlib.util, json, sys
    import zmart_controller
    folder = importlib.util.find_spec(sys.argv[1]).submodule_search_locations[0]
    name = zmart_controller.register_driver(folder)
    print(json.dumps({"name": name, "listed": zmart_controller.get_instruments()}))
"""


@pytest.mark.parametrize("driver", list(DRIVERS))
def test_a_driver_installs_into_the_installed_controller(driver, fresh_python):
    """The driver installs from its folder under the name its zmart_controller_plugin.json gives, and loads.

    Listing loads every installed driver; one that cannot be loaded is listed
    with an ``error`` instead of its connection, so an operator would see it
    in the list and still fail to connect.
    """
    said = fresh_python(INSTALL, driver)
    assert said["name"] == DRIVERS[driver], said
    listed = said["listed"]
    assert said["name"] in listed, listed
    assert "error" not in listed[said["name"]], listed[said["name"]]


#: Let the controller check every answer of one of the two mocks.
VALIDATE = """
    import json, sys, tempfile
    import zmart_controller
    which = sys.argv[1]
    output_root = tempfile.mkdtemp(prefix="zmart-mock-")
    if which == "interface":
        from zmart_interface.workflows.target_acquisition import mock_microscope as driver
        connection = {**driver.CONNECTION, "output_root": output_root}
    else:
        driver = zmart_controller.register_driver(sys.argv[2])
        connection = {"output_root": output_root, "mock_timing": "instant"}
    print(json.dumps({"problems": zmart_controller.validate_driver(driver, connection)}))
"""


def test_the_controllers_mock_passes_validate_driver(fresh_python):
    """The controller's mock (beads) answers every get_* command the way the contract says."""
    said = fresh_python(VALIDATE, "controller", _the_controllers_mock())
    assert said["problems"] == [], said


def test_the_interfaces_mock_microscope_passes_validate_driver(fresh_python, tmp_path):
    """The interface's mock (kidney) answers every get_* command the way the contract says.

    Its own state file is kept in this check's folder, not in anyone's home.
    """
    said = fresh_python(VALIDATE, "interface",
                        env={"ZMART_MOCK_STATE": str(tmp_path / "instrument.json")})
    assert said["problems"] == [], said


#: Install both mocks from their folders, and say whose plugin each listed mock is.
BOTH_MOCKS = """
    import json, sys
    from pathlib import Path
    import zmart_controller
    from zmart_controller.registry import find_driver
    from zmart_interface.workflows.target_acquisition import mock_microscope
    zmart_controller.register_driver(sys.argv[1])
    zmart_controller.register_driver(Path(mock_microscope.__file__).parent)
    listed = zmart_controller.get_instruments()
    print(json.dumps({"listed": listed, "plugin_from": {
        name: find_driver(name)[0].ZmartControllerPlugin.__module__ for name in listed}}))
"""


def test_the_two_mocks_stand_side_by_side(fresh_python):
    """With both mocks installed on the computer, both are listed, each calling its own plugin.

    The controller's mock is ``"mock"``, the interface's ``"interface-mock"``,
    a name of its own, so an operator choosing one never drives the other.
    """
    said = fresh_python(BOTH_MOCKS, _the_controllers_mock())
    assert set(said["listed"]) == {"mock", "interface-mock"}, said["listed"]
    assert said["plugin_from"]["interface-mock"].startswith(
        "zmart_interface.workflows.target_acquisition.mock_microscope"), said["plugin_from"]
    assert said["plugin_from"]["mock"].startswith("mock_driver."), said["plugin_from"]
