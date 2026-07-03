"""ZMART: the cross-vendor microscope controller.

A small, consistent interface for driving a microscope from a workflow. Two ways
to use it, both giving ``zmart_controller.<call>()``:

    # the module IS the active microscope (one at a time) - shortest
    import zmart_controller

    instruments = zmart_controller.get_instruments()
    zmart_controller.set_instrument(instruments[0])
    zmart_controller.set_origin()                # (0, 0, 0) is here now
    zmart_controller.set_xyz(10, 20, 5)
    zmart_controller.acquire(acquisition_type="prescan", position_label="A1")
    zmart_controller.disconnect()

    # or hold the session object explicitly (needed for >1 microscope at once)
    from zmart_controller import set_instrument
    mic = set_instrument(instrument)
    mic.set_origin()
    mic.acquire(acquisition_type="prescan", position_label="A1")

Requires the repository root (the package's parent) on sys.path.

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

__all__ = ["Session", "disconnect", "get_instruments", "set_instrument"]

# The module-level active microscope, so ``import zmart_controller; zmart_controller.acquire()`` works.
_active: Session | None = None


def set_instrument(*args, **kwargs) -> Session:
    """Select an instrument, set the module's active microscope, return the session.

    The returned :class:`Session` is the explicit handle. The module also
    delegates calls (``zmart_controller.acquire()``, …) to it, so a notebook can drive
    one microscope without holding the object.
    """
    global _active
    new = _set_instrument(*args, **kwargs)
    # Resolve the new session first; only then tear down the previous active one,
    # so a failed set_instrument never disconnects a working session. Track the
    # new session before the teardown, so it never leaks if teardown raises.
    previous, _active = _active, new
    if previous is not None and previous is not new:
        previous.disconnect()
    return new


def disconnect() -> None:
    """Disconnect the module's active microscope and clear it.

    After this, module-level calls raise until :func:`set_instrument` selects a
    new instrument. A no-op when no microscope is active (like
    :meth:`Session.disconnect`, calling it twice is safe).
    """
    global _active
    previous, _active = _active, None
    if previous is not None:
        previous.disconnect()


def __getattr__(name: str):
    # Delegate unknown attributes (acquire, set_xyz, …) to the active microscope.
    if _active is not None and hasattr(_active, name):
        return getattr(_active, name)
    if _active is None and not name.startswith("_"):
        raise AttributeError(
            f"no active microscope - call set_instrument(...) before zmart_controller.{name}(...)"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
