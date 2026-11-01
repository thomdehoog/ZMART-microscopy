"""How target acquisition takes part in starting and closing the interface.

The bridge knows no instrument. Target acquisition offers its own mock
microscope first, so a page opened by accident drives nothing real, with the
mock's small window opened beside the session as a vendor's software would
be. Closing the window stops a running scan between two fields and closes
the session.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from .. import mock_microscope
from . import connecting, state


def offered() -> dict[str, tuple[object, dict]]:
    """The microscopes offered before the controller's list: the mock, with its window."""
    return {mock_microscope.NAME: (mock_microscope, {**mock_microscope.CONNECTION, "open_window": True})}


def add_arguments(group) -> None:
    """``--output-root``."""
    group.add_argument("--output-root",
                       help="where runs go, for a driver that cannot discover its own")


def start(args) -> None:
    """Offer the mock, and keep where runs go; the window keeps its own name.

    Everything a start sets is set afresh, so a bridge started twice in one
    process (as the tests do) carries nothing over from the first.
    """
    connecting.offered = offered()
    state.output_root = getattr(args, "output_root", None)


def close(wait_s: float) -> None:
    """Stop a running scan between two fields, then close the session."""
    connecting.let_the_last_session_go(wait_s=wait_s)
    connecting.disconnect()
