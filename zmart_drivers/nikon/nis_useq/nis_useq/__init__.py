"""Run useq-schema acquisitions on a Nikon microscope through NIS-Elements.

    from nis_useq.engine import NisEngine      # the engine, for pymmcore-plus
    nis-useq-assistant                         # the chat assistant (a command)

This file stays empty on purpose: NIS-Elements imports the package when it
starts the bridge, and its Python has none of the engine's dependencies.
"""

__version__ = "0.1.0"
