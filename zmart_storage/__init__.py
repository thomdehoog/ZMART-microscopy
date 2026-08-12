"""Writing a run's images to disk, in a shape a viewer can follow as it happens.

This sits apart from both the drivers and the viewer on purpose. The drivers
know how to talk to an instrument, the viewer knows how to draw pictures, and
neither of them should have to know how a run is laid out on disk. Putting that
in one place means an instrument we add later writes runs the viewer can already
read, without either side learning about the other.

It holds three things.

:mod:`zmart_storage.canvas` writes a tiled run into one large OME-Zarr image per
acquisition type, rather than one image per position; the reasoning behind that
is written out at the top of that module. This is the part a run uses while the
microscope is going, and :class:`TileCanvases` is its front door. It asks for an
acquisition whose tiles butt up against one another, because one image holds a
single value per voxel and overlapping tiles would be written over each other.

:mod:`zmart_storage.cropped` is for the very common case that ``canvas`` cannot
take: an acquisition that overlaps on purpose, so that a stitcher can afterwards
work out where the stage really went. It writes the run twice — every tile whole
in a small image of its own, and every tile trimmed where it meets its neighbours
into one canvas for the viewer — so that the overlap is kept and the viewer still
has a single picture to draw. :class:`TilesAndCanvas` is its front door.

:mod:`zmart_storage.coverage` keeps the note of *where* such a run actually
imaged, which the images themselves cannot say — a canvas declares far more room
than any run fills, and an unwritten piece of it reads back as zeros exactly like
a piece of genuinely dark specimen. :func:`imaged_regions` reads that note back.
"""

from .canvas import (
    Channel,
    TileCanvases,
    copies_for_a_canvas,
    rmtree_despite_brief_holds,
)
from .coverage import Coverage, Region, Tile, imaged_regions
from .cropped import TilesAndCanvas, Trimming

__all__ = [
    "Channel",
    "Coverage",
    "Region",
    "Tile",
    "TileCanvases",
    "TilesAndCanvas",
    "Trimming",
    "copies_for_a_canvas",
    "imaged_regions",
    "rmtree_despite_brief_holds",
]
