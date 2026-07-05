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

    # or hold session objects explicitly (needed for >1 microscope at once).
    # Use layer.set_instrument here: the module-level set_instrument above
    # manages a single active microscope and disconnects the previous one.
    from zmart_controller.layer import set_instrument
    mic_a = set_instrument(instrument_a)
    mic_b = set_instrument(instrument_b)
    mic_a.set_origin()
    mic_a.acquire(acquisition_type="prescan", position_label="A1")

Two caveats on the module-level surface:

- Call through the module attribute (``zmart_controller.set_xyz(...)``); do not
  capture a call into a variable across ``set_instrument`` calls — the captured
  method stays bound to the previous, now-disconnected session.
- The module-level surface (and registry mutation) assumes a single thread.
  From multiple threads, hold explicit ``Session`` handles owned by one thread.

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


def set_instrument(instrument) -> Session:
    """Select an instrument, set the module's active microscope, return the session.

    The returned :class:`Session` is the explicit handle. The module also
    delegates calls (``zmart_controller.acquire()``, …) to it, so a notebook can drive
    one microscope without holding the object. The previous active session, if
    any, is disconnected; to drive several microscopes at once, use
    :func:`zmart_controller.layer.set_instrument` and hold each session.
    """
    global _active
    new = _set_instrument(instrument)
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
