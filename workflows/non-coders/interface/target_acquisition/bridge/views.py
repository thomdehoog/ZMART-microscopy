"""A focus stack's slice copies, made as each point lands for the focus panel's eye.

They are written into the focussing kind's view folder, which ``pictures``
serves as it is.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from ..microscope.focus_run import FOCUSSING
from . import pictures


def the_slice_copies_of(planes: list, *, store=None) -> list:
    """Small copies of one focus stack, one per height, for the panel's eye.

    Made as the point lands -- on the worker's time, never a request's -- and
    named to the page without their folder: where pictures are fetched from
    stays ``viewOf``'s answer. A stack that cannot be copied (a driver whose
    files are not canonical planes) costs the preview and never the run.
    """
    from ..storage.jpeg_tiles import make_slice_copies  # noqa: PLC0415

    try:
        if store is not None:
            return make_slice_copies(pictures.view_of(FOCUSSING), planes, store=store, budget_px=1024 * 1024)
        return make_slice_copies(pictures.view_of(FOCUSSING), planes)
    except Exception as why:  # noqa: BLE001 -- the preview is optional, the height is not
        import logging

        logging.getLogger(__name__).warning("no slice copies for a focus point: %s", why)
        return []
