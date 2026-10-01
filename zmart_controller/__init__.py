"""ZMART Controller: one small, universal way to drive any microscope.

The shortest way drives one microscope through the module itself::

    import zmart_controller

    zmart_controller.register_driver("path/to/driver")
    instrument = next(
        i for i in zmart_controller.get_instruments() if i["microscope"] == "my-scope"
    )
    zmart_controller.set_instrument(instrument)
    zmart_controller.set_xyz(10, 20, 5)
    zmart_controller.acquire(acquisition_type="prescan", position_label="A1")
    zmart_controller.disconnect()

Pick the instrument by its name, as above, rather than by its place in a
list. Drivers installed on the computer are listed too, so the first entry
may be a different microscope. And ``register_driver`` lists only what it
registered during that call, so running the cell a second time can give an
empty list.

To drive several microscopes at once, hold a session for each::

    from zmart_controller.layer import set_instrument

    mic_a = set_instrument(instrument_a)
    mic_b = set_instrument(instrument_b)
    mic_a.acquire(acquisition_type="prescan", position_label="A1")

Two cautions for the short way. Call through the module each time, as in
``zmart_controller.set_xyz(...)``; a command saved in a variable keeps pointing
at the old microscope after a switch. And it assumes one thread; from several
threads, hold a session each.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

__version__ = "0.1.0"
__author__ = "Thom de Hoog"
__email__ = "thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com"
__affiliation__ = "Center for Microscopy and Image Analysis (ZMB), University of Zurich"

from .check import check_driver
from .layer import Session
from .layer import set_instrument as _set_instrument
from .registry import forget_driver, get_instruments, register_driver

__all__ = [
    "Session",
    "check_driver",
    "disconnect",
    "forget_driver",
    "get_instruments",
    "register_driver",
    "set_instrument",
]

# The one active microscope that the module-level commands go to.
_active: Session | None = None


def set_instrument(instrument) -> Session:
    """Connect to an instrument and make it the active microscope.

    Module-level commands then go to it. The previously active microscope is
    disconnected. Returns the :class:`Session` as well, for those who want to
    hold it.
    """
    global _active
    new = _set_instrument(instrument)
    # Connect the new one first, so a failed connect never loses a working
    # session. Record it before closing the old one, so it is never lost if
    # closing raises.
    previous, _active = _active, new
    if previous is not None and previous is not new:
        previous.disconnect()
    return new


def disconnect() -> None:
    """Disconnect the active microscope.

    Module-level commands then raise until :func:`set_instrument` picks a new
    one. With no active microscope this does nothing.
    """
    global _active
    previous, _active = _active, None
    if previous is not None:
        previous.disconnect()


def __getattr__(name: str):
    # Send commands such as acquire or set_xyz to the active microscope.
    if _active is not None and hasattr(_active, name):
        return getattr(_active, name)
    if _active is None and not name.startswith("_"):
        raise AttributeError(
            f"no active microscope - call set_instrument(...) before zmart_controller.{name}(...)"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
