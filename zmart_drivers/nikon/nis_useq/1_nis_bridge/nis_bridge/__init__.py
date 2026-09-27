"""Control NIS-Elements from your own Python, through a small bridge inside NIS.

    python -m nis_bridge.install_macros        # once: write start_bridge.mac
    from nis_bridge.client import NisClient    # then, with the macro running in NIS
    NisClient().request("get_position")

This file imports nothing on purpose: NIS-Elements imports the package when it
starts the bridge, and its Python has only the standard library and numpy.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

__version__ = "0.1.0"
