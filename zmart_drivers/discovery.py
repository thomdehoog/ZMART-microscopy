"""Finding the drivers this checkout has, by their folders.

A driver is a folder. Put one under ``zmart_drivers/<vendor>/<microscope>/``
and it is found at start and offered in the operator page's Microscope
list; take it away and it is gone. Nothing in the bridge names a driver by
path, so adding a microscope never means editing the bridge.

What makes a folder a driver is that it holds a Python package with a
``zmart_adapter`` package inside it, and importing that package registers the
instrument with the controller (that is the driver's own opt-in, see the
Leica adapter's docstring). A ``zmart_adapter/setup.py`` beside it registers
the driver's *setup* -- what the configuration workflow can measure and
publish -- with ``zmart_drivers.setup``. A folder that fails to import is
simply not offered, and the reason is said once on the console, so a driver
whose vendor library is missing on this machine does not stop the others.

The name of the folder is the name of the microscope. A driver takes its
own identity from the folder it is in, so a copy of a driver folder under a
new name is a second microscope, with configurations of its own under
ProgramData, and never quarrels with the original over one name.

The mock driver, the simulator every workflow can be walked on without an
instrument, is not a folder of this shape; the bridge registers it on its
own, always.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: The folder every vendor's drivers are under: this one.
DRIVERS = Path(__file__).resolve().parent
#: The repository root, which has to be importable for ``zmart_drivers.<vendor>``.
ROOT = DRIVERS.parent


@dataclass
class Driver:
    """One driver folder, and what became of importing it."""

    vendor: str
    #: The folder's name: the microscope's name, as the identity spells it
    #: with underscores.
    folder: str
    #: The dotted name of the driver's package, ``zmart_drivers.<vendor>.<folder>.<package>``.
    package: str
    path: Path
    registered: bool = False
    #: Why the driver was not registered, when it was not.
    why: str | None = None
    #: The identity the driver registered under, when it did.
    connection: dict = field(default_factory=dict)


def driver_folders() -> list[Driver]:
    """Every driver folder under ``zmart_drivers``, vendor by vendor, in name order.

    Nothing is imported here; this only says what is there.
    """
    found: list[Driver] = []
    for vendor in sorted(p for p in DRIVERS.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        for folder in sorted(p for p in vendor.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
            for package in sorted(p for p in folder.iterdir() if p.is_dir()):
                if (package / "__init__.py").is_file() and (package / "zmart_adapter" / "__init__.py").is_file():
                    found.append(Driver(
                        vendor=vendor.name, folder=folder.name,
                        package=f"zmart_drivers.{vendor.name}.{folder.name}.{package.name}",
                        path=folder,
                    ))
    return found


def register_every_driver(*, setup: bool = True, say=print) -> list[Driver]:
    """Import every driver folder, so each registers itself, and say how it went.

    ``setup`` also registers each driver's setup, where it has one. ``say``
    is told about every folder that could not be imported. What comes back
    is the list of folders, each marked registered or not.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    drivers = driver_folders()
    for driver in drivers:
        try:
            adapter = importlib.import_module(f"{driver.package}.zmart_adapter")
            if setup and (driver.path / driver.package.rsplit(".", 1)[-1] / "zmart_adapter" / "setup.py").is_file():
                importlib.import_module(f"{driver.package}.zmart_adapter.setup")
            driver.registered = True
            driver.connection = dict(getattr(adapter, "CONNECTION", {}) or {})
        except Exception as why:  # noqa: BLE001 -- a driver this machine cannot run is a normal state
            driver.why = f"{type(why).__name__}: {why}"
            say(f"drivers: {driver.vendor}/{driver.folder} is not available on this machine ({driver.why})")
    return drivers


def microscope_name_of(folder: Path) -> str:
    """The microscope's name in a connection identity, from its folder.

    Identities are spelt with hyphens -- ``leica``, ``navigator-expert`` --
    and folders with underscores, because a Python package name cannot hold
    a hyphen. So ``stellaris5_y42h93`` the folder is ``stellaris5-y42h93``
    the microscope.
    """
    return Path(folder).name.replace("_", "-")
