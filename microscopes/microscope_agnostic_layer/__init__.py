"""Microscope-agnostic layer.

Two ways to drive a microscope, both giving ``mic.<call>()``:

    # the module IS the active microscope (one at a time) - shortest
    import microscope_agnostic_layer as mic

    mic.available_microscopes()
    mic.connect_to_microscope(vendor="mock")
    mic.set_coordinate_system(objective="10x", stage_type="motoric")
    mic.acquire()
    mic.export_data(options={"format": "ome-zarr"})
    mic.disconnect()

    # or hold the session object explicitly (needed for >1 microscope at once)
    from microscope_agnostic_layer import connect_to_microscope
    mic = connect_to_microscope(vendor="mock")
    mic.acquire()

See DESIGN.md for the contract. Requires the microscopes/ source root on sys.path.
"""

from .layer import Session
from .layer import connect_to_microscope as _connect_to_microscope
from .registry import available_microscopes

__all__ = ["Session", "available_microscopes", "connect_to_microscope"]

# The module-level active microscope, so ``import ... as mic; mic.acquire()`` works.
_active: Session | None = None


def connect_to_microscope(*args, **kwargs) -> Session:
    """Connect, set the module's active microscope, and return the session.

    The returned :class:`Session` is the explicit handle. The module also
    delegates calls (``mic.acquire()``, …) to it, so a notebook can drive one
    microscope without holding the object.
    """
    global _active
    _active = _connect_to_microscope(*args, **kwargs)
    return _active


def __getattr__(name: str):
    # Delegate unknown attributes (acquire, set_xyz, …) to the active microscope.
    if _active is not None and hasattr(_active, name):
        return getattr(_active, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
