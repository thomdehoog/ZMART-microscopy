"""The interface's test microscope: a pretend instrument, plugged in like any driver.

The mock is a complete ZMART driver that needs no hardware. Its plug-in, the
``ZmartControllerPlugin`` class, is in ``zmart_controller_plugin/`` with its
``NAME``, ``interface-mock``; it is listed here too, so the package itself
can be plugged in like any driver::

    from zmart_controller import ZmartController
    from .. import mock_microscope

    mic = ZmartController(mock_microscope, {"output_root": "my_images"})

or installed once on a computer with ``zmart_controller.register_driver``
(pointed at this folder) and connected to as ``"interface-mock"``.

The mock never needs to decline softly: a request that is itself wrong -- a
move outside the stage's travel, an unknown motor or job -- raises
``ValueError`` before anything moves, and anything else that goes wrong is
raised as well. The controller turns such a raise into the declined answer
every caller reads, ``success`` False with the reason as the output. The mock
writes real image files, so the whole interface -- the bridge, the page, the
analysis and the viewer -- can be run and tested on a desk.

``driver.py`` is the pretend instrument itself, ``window.py`` its own small
window, where a job is chosen the way an operator chooses one in the vendor's
software.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from .driver import open_the_window
from .zmart_controller_plugin.zmart_controller_plugin import (
    CONNECTION,
    NAME,
    ZmartControllerPlugin,
)

__all__ = ["CONNECTION", "NAME", "ZmartControllerPlugin", "open_the_window"]
