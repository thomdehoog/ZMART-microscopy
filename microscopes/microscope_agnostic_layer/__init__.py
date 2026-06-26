"""Microscope-agnostic layer.

Public surface: connect() returns a Session that holds the session context,
feeds it to the driver, and is easy to drive. See DESIGN.md for the contract.

    from microscope_agnostic_layer import connect

    mic = connect(vendor="mock")
    mic.set_xyz(10, 20, 5)
    frame = mic.acquire()
    mic.save(format="ome-zarr", name="well_A1")

Import convention: requires the microscopes/ source root on sys.path.
"""

from .layer import Session, connect

__all__ = ["Session", "connect"]
