"""Every driver plugs into the installed controller, and the two mock microscopes fit its contract.

A driver reaches the ZMART Controller in one of two ways. The newer way is a
``zmart_driver.json`` beside a ``ZmartDriver`` class: ``register_driver``
installs it on the computer once, and from then on it is listed by
``get_instruments`` and connected to by its name. The older way, which the
Nikon, ZEISS and mesoSPIM drivers still use, is a module with one function per
command (``zmart_controller_plugin.py``), handed to the controller directly.
These checks plug in every driver in the installed ``zmart-drivers`` the way
its shape asks, each in a fresh Python as an operator's session would.

No real microscope is connected here: the real drivers would need their
vendor's software, so they are only plugged in and listed. The two pretend
microscopes need none, so they go one step further: the controller's own
``validate_driver`` connects to them and checks every answer against the
contract. One is the controller's mock (a slide of beads, built into the
controller as ``"mock"``), the other the interface's (a section of a mouse
kidney, the one the operator window offers first). Nothing above the
controller needs to know which driver is underneath; the two mocks stand in
for all of them, and a capture is only ever taken on a mock (see
``test_viewer_serves``).

The last checks are about names. The controller tells instruments apart by
name. The two mocks therefore have names of their own and stand side by side,
and no installed driver can take the name of the controller's mock.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

#: The drivers installed on a computer from their ``zmart_driver.json``, by
#: module, with the name the controller lists each under.
INSTALLED_BY_FILE = {
    "zmart_drivers.leica.stellaris5_y42h93.navigator_expert": "stellaris",
}

#: The drivers still plugged in as a module with one function per command.
PLUGGED_IN_AS_MODULES = [
    "zmart_drivers.mesospim.zmart_controller_plugin",
    "zmart_drivers.nikon.nis_elements_6_10.zmart_controller_plugin",
    "zmart_drivers.zeiss.zenapi.zmart_controller_plugin",
]

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
    """Every driver in the installed package is checked below, in the shape it has.

    A folder with a ``zmart_driver.json`` is a driver installed from that
    file; a ``zmart_controller_plugin.py`` in a folder without one is a
    driver plugged in as a module. Without this, a new driver added to
    zmart-drivers would quietly go unchecked here.
    """
    root = _drivers_root()

    def a_driver(path: Path) -> bool:
        return not NOT_A_DRIVER & set(path.relative_to(root).parts)

    by_file = sorted(_module_of(found.parent) for found in root.rglob("zmart_driver.json")
                     if a_driver(found))
    as_modules = sorted(
        _module_of(found) for found in root.rglob("zmart_controller_plugin.py")
        if a_driver(found) and not (found.parent / "zmart_driver.json").is_file()
    )
    assert by_file == sorted(INSTALLED_BY_FILE)
    assert as_modules == sorted(PLUGGED_IN_AS_MODULES)


#: Install one driver from its folder, and say what the controller lists.
INSTALL = """
    import importlib.util, json, sys
    import zmart_controller
    folder = importlib.util.find_spec(sys.argv[1]).submodule_search_locations[0]
    name = zmart_controller.register_driver(folder)
    print(json.dumps({"name": name, "listed": zmart_controller.get_instruments()}))
"""


@pytest.mark.parametrize("driver", list(INSTALLED_BY_FILE))
def test_a_driver_installs_into_the_installed_controller(driver, fresh_python):
    """The driver installs from its folder under the name its zmart_driver.json gives, and loads.

    Listing loads every installed driver; one that cannot be loaded is listed
    with an ``error`` instead of its connection, so an operator would see it
    in the list and still fail to connect.
    """
    said = fresh_python(INSTALL, driver)
    assert said["name"] == INSTALLED_BY_FILE[driver], said
    listed = said["listed"]
    assert said["name"] in listed, listed
    assert "error" not in listed[said["name"]], listed[said["name"]]


#: Find a module driver's functions the way the controller does when it is handed one.
FUNCTIONS = """
    import importlib, json, sys
    from zmart_controller.registry import driver_functions
    from zmart_controller.zmart_controller import COMMANDS
    found = driver_functions(importlib.import_module(sys.argv[1]))
    print(json.dumps({"found": sorted(found), "commands": sorted(COMMANDS)}))
"""


@pytest.mark.parametrize("driver", PLUGGED_IN_AS_MODULES)
def test_a_module_driver_has_every_command_the_controller_calls(driver, fresh_python):
    """The controller finds a function for every one of its commands in the module.

    This is what ``ZmartController`` does first when it is handed a module, so
    a missing function would stop the driver before it ever reached its
    microscope. ``disconnect`` may be left out; every other command must be
    there.
    """
    said = fresh_python(FUNCTIONS, driver)
    needed = set(said["commands"]) | {"connect"}
    assert needed - {"disconnect"} <= set(said["found"]), said


#: Let the controller check every answer of one of the two mocks.
VALIDATE = """
    import json, sys, tempfile
    import zmart_controller
    which = sys.argv[1]
    output_root = tempfile.mkdtemp(prefix="zmart-mock-")
    if which == "interface":
        from zmart_interface import mock_microscope as driver
        connection = {**driver.CONNECTION, "output_root": output_root}
    else:
        driver = "mock"
        connection = {"output_root": output_root, "mock_timing": "instant"}
    print(json.dumps({"problems": zmart_controller.validate_driver(driver, connection)}))
"""


def test_the_controllers_mock_passes_validate_driver(fresh_python):
    """The controller's mock (beads) answers every get_* command the way the contract says."""
    said = fresh_python(VALIDATE, "controller")
    assert said["problems"] == [], said


def test_the_interfaces_mock_microscope_passes_validate_driver(fresh_python, tmp_path):
    """The interface's mock (kidney) answers every get_* command the way the contract says.

    Its own state file is kept in this check's folder, not in anyone's home.
    """
    said = fresh_python(VALIDATE, "interface",
                        env={"ZMART_MOCK_STATE": str(tmp_path / "instrument.json")})
    assert said["problems"] == [], said


#: Install the kidney mock from its folder, and say whose functions each listed mock calls.
BOTH_MOCKS = """
    import json
    from pathlib import Path
    import zmart_controller
    from zmart_controller.registry import find_driver
    from zmart_interface import mock_microscope
    zmart_controller.register_driver(Path(mock_microscope.__file__).parent)
    listed = zmart_controller.get_instruments()
    print(json.dumps({"listed": listed, "functions_from": {
        name: find_driver(name)[0].get_info.__module__ for name in listed}}))
"""


def test_the_two_mocks_stand_side_by_side(fresh_python):
    """With the kidney mock installed on the computer, both mocks are listed, each calling its own driver.

    The controller lists its own mock as ``"mock"`` always; the interface's
    is ``"interface-mock"``, a name of its own, so an operator choosing one
    never drives the other.
    """
    said = fresh_python(BOTH_MOCKS)
    assert {"mock", "interface-mock"} <= set(said["listed"]), said["listed"]
    assert said["functions_from"]["interface-mock"].startswith(
        "zmart_interface.mock_microscope"), said["functions_from"]
    assert said["functions_from"]["mock"].startswith("zmart_controller.mock"), said["functions_from"]


#: Try to install a driver that calls itself "mock".
A_SECOND_MOCK = """
    import json, sys
    import zmart_controller
    try:
        zmart_controller.register_driver(sys.argv[1])
        refused = None
    except ValueError as why:
        refused = str(why)
    print(json.dumps({"refused": refused, "listed": zmart_controller.get_instruments()}))
"""


def test_no_driver_can_take_the_controllers_mock_name(fresh_python, tmp_path):
    """A driver whose zmart_driver.json calls it ``"mock"`` is refused, and nothing is installed.

    Were it accepted, connecting to ``"mock"`` to try a workflow without
    hardware could drive something real.
    """
    impostor = tmp_path / "impostor"
    impostor.mkdir()
    (impostor / "zmart_driver.json").write_text(json.dumps({"name": "mock"}), encoding="utf-8")
    (impostor / "zmart_driver.py").write_text(
        "class ZmartDriver:\n    def __init__(self, connection):\n        pass\n", encoding="utf-8")
    said = fresh_python(A_SECOND_MOCK, str(impostor))
    assert said["refused"], "the controller installed a second driver called 'mock'"
    assert list(said["listed"]) == ["mock"], said["listed"]
