"""
The mesoSPIM axes and their unit convention.
============================================
The five axes every part of the driver agrees on: the linear stage axes
(``x``, ``y``, ``z``), the focus (detection) axis ``f``, and the sample
rotation ``theta``. Readers, limit checks, and movement commands all validate
against this one list, so an axis name can never mean different things in
different places.

Unit convention: the mesoSPIM driver speaks **micrometers** for the linear
axes and **degrees** for the rotation axis, on both the public API and the
wire. The resident command server is responsible for any conversion to
mesoSPIM's internal units.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

# Linear axes are micrometers; theta is degrees.
LINEAR_AXES = ("x", "y", "z", "f")
ROTARY_AXES = ("theta",)
AXES = LINEAR_AXES + ROTARY_AXES
