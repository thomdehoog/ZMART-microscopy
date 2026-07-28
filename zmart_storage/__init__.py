"""Writing a run's images to disk, in a shape a viewer can follow as it happens.

This sits apart from both the drivers and the viewer on purpose. The drivers
know how to talk to an instrument, the viewer knows how to draw pictures, and
neither of them should have to know how a run is laid out on disk. Putting that
in one place means an instrument we add later writes runs the viewer can already
read, without either side learning about the other.

Today it holds one thing: :mod:`zmart_storage.canvas`, which writes a tiled run
into a small, fixed number of large OME-Zarr images rather than one image per
position. The reasoning behind that is written out at the top of that module.
"""

from .canvas import Channel, TileCanvases, slots_per_axis

__all__ = ["Channel", "TileCanvases", "slots_per_axis"]
