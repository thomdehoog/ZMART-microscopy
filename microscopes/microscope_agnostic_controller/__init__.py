"""Microscope Agnostic Controller.

A small, consistent interface for driving a microscope from a workflow. Two ways
to use it, both giving ``mac.<call>()``:

    # the module IS the active microscope (one at a time) - shortest
    import microscope_agnostic_controller as mac

    instruments = mac.get_instruments()
    mac.set_instrument(instruments[0], reference_stage="motoric", reference_objective="10x")
    mac.set_xyz(10, 20, 5)
    mac.acquire(acquisition_type="prescan", position_label="A1")
    mac.disconnect()

    # or hold the session object explicitly (needed for >1 microscope at once)
    from microscope_agnostic_controller import set_instrument
    mic = set_instrument(instrument, reference_stage="motoric", reference_objective="10x")
    mic.acquire(acquisition_type="prescan", position_label="A1")

Requires the microscopes/ source root on sys.path.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

__version__ = "0.1.0"
__author__ = "Thom de Hoog"
__email__ = "thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com"
__affiliation__ = "Center for Microscopy and Image Analysis (ZMB), University of Zurich"

from .layer import Session
from .layer import set_instrument as _set_instrument
from .registry import get_instruments

__all__ = ["Session", "get_instruments", "set_instrument"]

# The module-level active microscope, so ``import ... as mac; mac.acquire()`` works.
_active: Session | None = None


def set_instrument(*args, **kwargs) -> Session:
    """Select an instrument, set the module's active microscope, return the session.

    The returned :class:`Session` is the explicit handle. The module also
    delegates calls (``mac.acquire()``, …) to it, so a notebook can drive one
    microscope without holding the object.
    """
    global _active
    new = _set_instrument(*args, **kwargs)
    # Resolve the new session first; only then tear down the previous active one,
    # so a failed set_instrument never disconnects a working session.
    if _active is not None and _active is not new:
        _active.disconnect()
    _active = new
    return new


def __getattr__(name: str):
    # Delegate unknown attributes (acquire, set_xyz, …) to the active microscope.
    if _active is not None and hasattr(_active, name):
        return getattr(_active, name)
    if _active is None and not name.startswith("_"):
        raise AttributeError(
            f"no active microscope - call set_instrument(...) before mac.{name}(...)"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
