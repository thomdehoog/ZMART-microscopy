"""Microscope-agnostic layer.

Public surface: available_microscopes() lists what you can connect to;
connect_to_microscope() returns a Session that holds the session context, feeds
it to the driver, and is easy to drive. See DESIGN.md for the contract.

    from microscope_agnostic_layer import available_microscopes, connect_to_microscope

    available_microscopes()                     # what can I connect to?
    mic = connect_to_microscope(vendor="mock")
    mic.set_coordinate_system(objective="10x", stage_type="motoric")
    mic.set_xyz(10, 20, 5)
    frame = mic.acquire()
    mic.save(format="ome-zarr", name="well_A1")

Import convention: requires the microscopes/ source root on sys.path.
"""

from .layer import Session, connect_to_microscope
from .registry import available_microscopes

__all__ = ["Session", "available_microscopes", "connect_to_microscope"]
