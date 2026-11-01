"""What a run leaves behind: where it is written, what the driver said it
wrote, and the OME-Zarr image every capture is kept as.

``output.py`` names the run folder and files a capture's record;
``zarr_positions.py`` converts each capture, the moment it lands, into one
OME-Zarr image of its own -- one position, its channels, its planes, and a
few progressively smaller copies for viewing it zoomed out -- declared by
``images.py``; ``jpeg_tiles.py`` makes the small copies the page's gallery
and previews show; ``viewer_service.py`` hands the run's images to ZMART
Viewer, which draws the canvas.

``images.py`` is a small part of the writer kept in ZMART-microscopy
(``zmart_storage``), brought here because that writer has no standalone
home yet. Only what the interface calls was brought: the channel
description, declaring one image, and how many zoomed-out copies a position
can keep.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""
