"""Writing a run's images to disk, in a shape a viewer can follow as it happens.

This sits apart from both the drivers and the viewer on purpose. The drivers
know how to talk to an instrument, the viewer knows how to draw pictures, and
neither of them should have to know how a run is laid out on disk. Putting that
in one place means an instrument we add later writes runs the viewer can already
read, without either side learning about the other.

It holds three things.

:mod:`zmart_storage.canvas` writes a tiled run into a small, fixed number of
large OME-Zarr images rather than one image per position; the reasoning behind
that is written out at the top of that module. This is the part a run uses while
the microscope is going, and :class:`TileCanvases` is its front door.

:mod:`zmart_storage.coverage` keeps the note of *where* such a run actually
imaged, which the images themselves cannot say — a canvas declares far more room
than any run fills, and an unwritten piece of it reads back as zeros exactly like
a piece of genuinely dark specimen. :func:`imaged_regions` reads that note back.

:mod:`zmart_storage.fuse` is for afterwards. A run that keeps the overlap between
its tiles is spread over several images that only make sense together, and once
it has finished those can be joined into a single picture anything can open.
Nothing during a run needs it, which is why it is imported from its own module
rather than offered here.
"""

from .canvas import Channel, TileCanvases, copies_for_a_canvas, slots_per_axis
from .coverage import Coverage, Region, Tile, imaged_regions

__all__ = [
    "Channel",
    "Coverage",
    "Region",
    "Tile",
    "TileCanvases",
    "copies_for_a_canvas",
    "imaged_regions",
    "slots_per_axis",
]
