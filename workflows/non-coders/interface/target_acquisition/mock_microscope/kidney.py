"""The mock microscope's sample: one plane of a mouse kidney section, shipped with the package.

The section is scikit-image's ``kidney`` sample, imaged by Genevieve Buckley
at Monash Micro Imaging in 2018 on a Nikon C1 confocal microscope and
released under CC0 (free to use for any purpose). Only its middle plane is
used, three channels of 512 x 512 pixels, and that plane is kept here in
``kidney-plane.npz`` (about 1.3 MB) rather than downloaded: scikit-image
fetches the whole 25 MB stack from the internet the first time it is asked,
and the microscope computer has no network.

The mock microscope lays it across its whole stage.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

#: The plane, as scikit-image gives it: (row, column, channel), 16 bits.
THE_PLANE = Path(__file__).resolve().parent / "kidney-plane.npz"


@lru_cache(maxsize=1)
def the_kidney_plane() -> np.ndarray:
    """The section's middle plane as (channel, row, column), 16-bit, read once.

    The array is shared by everyone who asks, so it is handed out read-only:
    a caller that wants to change it makes its own copy first.
    """
    with np.load(THE_PLANE) as stored:
        plane = np.ascontiguousarray(np.moveaxis(stored["plane"], -1, 0))
    plane.setflags(write=False)
    return plane
