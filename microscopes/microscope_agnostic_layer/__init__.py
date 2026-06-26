"""Microscope-agnostic layer.

Public surface: available() lists what you can connect to; connect() returns a
Session that holds the session context, feeds it to the driver, and is easy to
drive. See DESIGN.md for the contract.

    from microscope_agnostic_layer import available, connect

    available()                                 # what can I connect to?
    mic = connect(vendor="mock")
    mic.set_coordinate_system(objective="10x", stage_type="motoric")
    mic.set_xyz(10, 20, 5)
    frame = mic.acquire()
    mic.save(format="ome-zarr", name="well_A1")

Import convention: requires the microscopes/ source root on sys.path.
"""

from .layer import Session, connect
from .registry import available

__all__ = ["Session", "available", "connect"]
