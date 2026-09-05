"""ZMART setup: the way a microscope driver is configured, kept apart from the way it is driven.

Two things happen to a microscope in this repository, and they must not share
a door. **Driving** it -- moving, imaging, reading its state -- goes through
:mod:`zmart_controller`, which every workflow and, in time, every agent uses.
**Setting it up** -- publishing how far the stage may travel, which way the
picture is turned, how the objectives line up, and where the frame counts from
-- goes through here, and nothing that holds a controller session can reach it.

That separation is a safety property, not a convenience. The driver refuses
moves outside its published envelope, and independently outside a hard-coded
physical backstop. That is only worth anything while the thing being limited
cannot rewrite its own limits. If publishing an envelope were reachable from
the operating surface, a runaway loop, an honest mistake, or an agent that
reasoned its way there could widen the fence it is being held by. So the
controller carries no configuration op at all, and this package carries no
reference to the controller.

What a driver supplies here is small on purpose, because a vendor's API is not
to be trusted further than it must be: say where the stage is, move it and
read back where it went, take a picture, say which objective is in, and read
and write the four configuration documents. Everything measured from the
pictures happens in :mod:`zmart_analysis`, which never learns which microscope
took them. See :mod:`zmart_setup.registry` for the exact list.

    import zmart_setup
    setup = zmart_setup.open_setup(zmart_setup.get_instruments()[0])
    setup.describe()               # what this driver can configure, and how
    setup.publish("limits", doc)   # a dated snapshot under ProgramData
    setup.close()

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from .layer import Setup, open_setup
from . import procedures
from .registry import SUBSYSTEMS, get_instruments, register

__all__ = ["SUBSYSTEMS", "Setup", "get_instruments", "open_setup", "procedures", "register"]
