"""Control NIS-Elements from your own Python, through a small bridge inside NIS.

    python -m nis_bridge.install_macros        # once: write start_bridge.mac
    from nis_bridge.client import NisClient    # then, with the macro running in NIS
    NisClient().request("get_position")

This file stays empty on purpose: NIS-Elements imports the package when it
starts the bridge, and its Python has only the standard library and numpy.
"""

__version__ = "0.1.0"
