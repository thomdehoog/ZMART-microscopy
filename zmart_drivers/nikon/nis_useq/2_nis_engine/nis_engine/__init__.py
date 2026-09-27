"""Run useq-schema acquisitions on a Nikon microscope through NIS-Elements.

    from nis_engine import NisEngine      # the engine, for the pymmcore-plus runner

Needs the bridge from nis-bridge running in NIS-Elements.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

from .engine import NisEngine

__all__ = ["NisEngine"]
__version__ = "0.1.0"
