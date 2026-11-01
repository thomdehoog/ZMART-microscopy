"""The mock microscope's plug-in: the class the ZMART Controller makes when it connects.

It only translates. The work of every command is in ``driver.py``; each
method here hands the call on and gives the controller the values the
contract asks for, as ``True`` and the values, or ``False`` and a message
when the microscope did not do it. A request that is wrong raises
``ValueError`` before anything moves, and the controller reports it with its
text.

``NAME`` is what the mock is listed as, and ``CONNECTION`` what it is plugged
in with when nothing else is given; both are read from
``zmart_controller_plugin.json`` beside this file, the file the controller's
registry reads, so the two can never disagree.

Install it once on a computer, and it is listed by the controller like any
other driver::

    import zmart_controller
    zmart_controller.register_driver("path/to/examples/target_acquisition/mock_microscope")

The interface does not need that: when its bridge starts, target
acquisition (``bridge/starting.py``) offers the mock first and plugs this
class in directly, with ``open_window`` set so the mock's own window opens
beside the session.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import driver

SETTINGS = json.loads(
    (Path(__file__).parent / "zmart_controller_plugin.json").read_text(encoding="utf-8")
)

#: What the mock is listed as. Not "mock": an operator who chose the
#: interface's mock must get this one, whatever else is installed.
NAME: str = SETTINGS["name"]

#: What the mock is plugged in with when nothing else is given. Images go to
#: ``mock-output`` in the working folder unless ``output_root`` says otherwise,
#: when acquire names no folder of its own.
CONNECTION: dict = dict(SETTINGS.get("connection") or {})

#: The axes, in the order the controller takes them.
AXES = ("x", "y", "z")


class ZmartControllerPlugin:
    """One connected mock microscope. ``handle`` is the pretend instrument."""

    def __init__(self, connection: dict[str, Any]) -> None:
        self.handle = driver.connect(connection)

    def disconnect(self) -> None:
        driver.disconnect(self.handle)

    def get_info(self):
        info = driver.get_info(self.handle)
        return True, (
            info["description"],
            info["setup"],
            info["chooses_its_own_folder"],
            info["connection_status"],
        )

    def get_actuators(self):
        motors = driver.get_actuators(self.handle)
        return True, tuple(motors[axis] for axis in AXES)

    def get_xyz(self, with_actuators):
        return True, xyz_values(driver.get_xyz(self.handle, with_actuators=with_actuators))

    def set_xyz(self, x, y, z, with_actuators):
        moved = driver.set_xyz(self.handle, x, y, z, with_actuators=with_actuators)
        return True, xyz_values(moved)

    def get_state(self):
        state = driver.get_state(self.handle)
        return True, (state["changeable"], state["observed"])

    def set_state(self, changeable):
        """Apply the settings; none at all applied is a failure."""
        applied = driver.set_state(self.handle, {"changeable": changeable})["applied"]
        if not applied:
            return False, "nothing was applied: changeable names no setting"
        return True, applied

    def get_acquisition_settings(self):
        return True, driver.get_acquisition_settings(self.handle)

    def acquire(self, position_label, acquisition_type, output_folder, acquisition_settings):
        taken = driver.acquire(
            self.handle,
            position_label=position_label,
            acquisition_type=acquisition_type,
            output_folder=output_folder,
            acquisition_settings=acquisition_settings,
        )
        return True, (taken["files"], taken["planes"])

    def get_procedures(self):
        return True, driver.get_procedures(self.handle)

    def run_procedure(self, procedure):
        return True, driver.run_procedure(self.handle, procedure)["ran"]


def xyz_values(reading: dict) -> tuple:
    """``(x, y, z, actuator_readings, canvas)``, the values the controller builds ``get_xyz`` from."""
    readings = {axis: dict(reading[axis]["actuator_readings"]) for axis in AXES}
    canvas = tuple(end for axis in AXES for end in reading[axis]["canvas"])
    return (*(reading[axis]["position"] for axis in AXES), readings, canvas)
