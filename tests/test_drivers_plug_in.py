"""Every driver plugs into the installed controller, and the two mock microscopes fit its contract.

A driver is plugged into the ZMART Controller with ``register_driver``, given
either the driver's module name or its folder. The controller then reads the
driver's ``zmart.json``, finds its functions, and lists its instrument. These
checks do exactly that for every driver in the installed ``zmart-drivers``,
both ways, each in a fresh Python as an operator's session would.

No microscope is connected here: the real drivers would need their vendor's
software, so they are only plugged in and listed. The two pretend microscopes
need none, so they go one step further: the controller's own
``validate_driver`` connects to them and checks every answer against the
contract. One is the controller's mock (a slide of beads, kept with the
controller's tests), the other the interface's (a section of a mouse kidney,
the one the operator window offers as "Mock"). Nothing above the controller
needs to know which driver is underneath; the two mocks stand in for all of
them, and a capture is only ever taken on a mock (see ``test_viewer_serves``).

The last checks are about names. The controller tells instruments apart by
their whole name (vendor, microscope and api), and refuses a second driver
that claims a name another driver already holds. The two mocks therefore have
names of their own, and stand side by side.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from conftest import BEADS_MOCK, KIDNEY_MOCK, checkout, identity_of

#: The drivers zmart-drivers ships, by the module name its README gives.
DRIVERS = [
    "zmart_drivers.leica.stellaris5_y42h93.navigator_expert",
    "zmart_drivers.nikon.nis_elements_6_10",
    "zmart_drivers.zeiss.zenapi",
    "zmart_drivers.mesospim",
]

#: Plug one driver in, by module name or by folder, and say what the controller lists.
PLUG_IN = """
    import importlib.util, json, sys
    import zmart_controller
    how, driver = sys.argv[1], sys.argv[2]
    if how == "folder":
        driver = importlib.util.find_spec(driver).submodule_search_locations[0]
    added = zmart_controller.register_driver(driver, remember=False)
    print(json.dumps({"given": driver, "added": added,
                      "listed": zmart_controller.get_instruments()}))
"""

def _shipped_manifest(module: str) -> dict:
    """The zmart.json the installed driver carries."""
    folder = Path(importlib.util.find_spec(module).submodule_search_locations[0])
    return json.loads((folder / "zmart_controller" / "zmart.json").read_text(encoding="utf-8"))


def test_the_list_of_drivers_here_is_every_driver_installed():
    """Every driver folder with a zmart.json in the installed package is checked below.

    Without this, a new driver added to zmart-drivers would quietly go
    unchecked here.
    """
    root = Path(importlib.util.find_spec("zmart_drivers").submodule_search_locations[0])
    found = sorted(
        "zmart_drivers." + ".".join(manifest.parent.parent.relative_to(root).parts)
        for manifest in root.rglob("zmart_controller/zmart.json")
    )
    assert found == sorted(DRIVERS)


@pytest.mark.parametrize("how", ["module", "folder"])
@pytest.mark.parametrize("driver", DRIVERS)
def test_a_driver_plugs_into_the_installed_controller(driver, how, fresh_python):
    """The driver registers by its module name and by its folder, and its instrument is listed.

    The instrument the controller lists must be the one the driver's
    zmart.json names, so that an operator choosing it from the list connects
    to the driver they expect.
    """
    said = fresh_python(PLUG_IN, how, driver)
    named = [identity_of(entry) for entry in _shipped_manifest(driver)["instruments"]]
    added = [identity_of(entry) for entry in said["added"]]
    listed = [identity_of(entry) for entry in said["listed"]]
    assert added == named, said
    for instrument in named:
        assert instrument in listed, f"{instrument} was registered but is not listed: {listed}"


#: Plug a mock in, and let the controller check every one of its answers.
VALIDATE = """
    import json, sys, tempfile
    import zmart_controller
    from zmart_controller.utils import validate_driver
    which, folder = sys.argv[1], sys.argv[2]
    if which == "interface":
        from zmart_interface import mock_microscope
        added = mock_microscope.register()
    else:
        added = zmart_controller.register_driver(folder, remember=False)
    instrument = {**added[0], "output_root": tempfile.mkdtemp(prefix="zmart-mock-")}
    if which == "controller":
        instrument["mock_timing"] = "instant"
    print(json.dumps({"instrument": instrument, "problems": validate_driver(instrument)}))
"""


def test_the_controllers_mock_driver_passes_validate_driver(fresh_python, tmp_path):
    """The controller's mock (beads) answers every get_* command the way the contract says."""
    folder = checkout("ZMART-controller") / "tests" / "mock_zmart_driver"
    said = fresh_python(VALIDATE, "controller", str(folder))
    assert said["problems"] == [], said


def test_the_interfaces_mock_microscope_passes_validate_driver(fresh_python, tmp_path):
    """The interface's mock (kidney) answers every get_* command the way the contract says.

    Its own state file is kept in this check's folder, not in anyone's home.
    """
    said = fresh_python(VALIDATE, "interface", "",
                        env={"ZMART_MOCK_STATE": str(tmp_path / "instrument.json")})
    assert said["problems"] == [], said


#: Plug both mocks in, and say what is listed and whose functions each name calls.
BOTH_MOCKS = """
    import json, sys
    import zmart_controller
    from zmart_controller.utils import resolve
    from zmart_interface import mock_microscope
    zmart_controller.register_driver(sys.argv[1])  # remembered, as the controller's guide says
    mock_microscope.register()                     # what the interface's bridge does first
    listed = zmart_controller.get_instruments()   # ...and then what it lists on the page
    print(json.dumps({"listed": listed, "functions_from": {
        "/".join(one[k] for k in ("vendor", "microscope", "api")):
            resolve(one)[0]["get_info"].__module__
        for one in listed}}))
"""


def test_the_two_mocks_stand_side_by_side(fresh_python):
    """With the controller's mock remembered on the computer, the kidney is still the interface's own.

    The controller's setup guide suggests trying the flow on its mock driver,
    which the computer then remembers. Each mock has a name of its own, so
    both are listed, and each name calls its own driver's functions.
    """
    folder = checkout("ZMART-controller") / "tests" / "mock_zmart_driver"
    said = fresh_python(BOTH_MOCKS, str(folder))
    listed = [identity_of(one) for one in said["listed"]]
    assert KIDNEY_MOCK in listed and BEADS_MOCK in listed, listed
    assert said["functions_from"]["/".join(KIDNEY_MOCK)].startswith(
        "zmart_interface.mock_microscope"), said["functions_from"]
    assert not said["functions_from"]["/".join(BEADS_MOCK)].startswith(
        "zmart_interface"), said["functions_from"]


#: Plug the kidney in, then a different driver that claims the kidney's name.
A_SECOND_KIDNEY = """
    import json, sys
    import zmart_controller
    from zmart_controller.utils import resolve
    from zmart_interface import mock_microscope
    mock_microscope.register()
    try:
        zmart_controller.register_driver(sys.argv[1], remember=False)
        refused = None
    except ValueError as why:
        refused = str(why)
    kidney = next(one for one in zmart_controller.get_instruments()
                  if one["microscope"] == "kidney-mock")
    print(json.dumps({"refused": refused,
                      "functions_from": resolve(kidney)[0]["get_info"].__module__}))
"""


def test_a_different_driver_cannot_take_the_kidneys_name(fresh_python, tmp_path):
    """A driver claiming the kidney mock's whole name is refused, and the kidney stays the interface's.

    The second driver is a copy of the controller's mock in a folder of its
    own, renamed to the kidney's name in its zmart.json. (The copy keeps the
    package's name, because the mock's code imports itself by that name.)
    Were it accepted, choosing "Mock" in the operator window would drive the
    beads.
    """
    impostor = tmp_path / "elsewhere" / "mock_zmart_driver"
    shutil.copytree(checkout("ZMART-controller") / "tests" / "mock_zmart_driver", impostor,
                    ignore=shutil.ignore_patterns("__pycache__"))
    manifest = impostor / "zmart_controller" / "zmart.json"
    content = json.loads(manifest.read_text(encoding="utf-8"))
    for instrument in content["instruments"]:
        instrument.update(zip(("vendor", "microscope", "api"), KIDNEY_MOCK))
    manifest.write_text(json.dumps(content), encoding="utf-8")
    said = fresh_python(A_SECOND_KIDNEY, str(impostor))
    assert said["refused"], "the controller accepted a second driver under the kidney's name"
    assert said["functions_from"].startswith("zmart_interface.mock_microscope"), said
