"""Where the analysis of an acquisition goes.

A ZMART acquisition is a folder with parts. The driver writes its images into
``data``, with the instrument's own metadata copy in ``vendor`` beside them,
and what is made from the pixels afterwards becomes a folder beside them too.
This is the one that says which folder that is, so no step has to spell the
layout out again.

    <acquisition>/
        data/       the images a driver wrote
        vendor/     the instrument's own metadata
        analysis/   everything made from the pixels

The one rule worth stating: nothing here creates a directory. A step that has
something to write creates it when it writes; a step that finds nothing to say
should leave no empty folder behind.
"""

from __future__ import annotations

import re
from pathlib import Path

DATA = "data"
ANALYSIS = "analysis"

#: The channel and plane at the end of a ZMART image name. Everything before
#: it is the frame; a driver writes one file per C and Z of the same frame.
_PLANE = re.compile(r"_C\d{2}_Z\d{5}\.ome\.tiff?$", re.IGNORECASE)


def short_name(image_path: Path | str) -> str:
    """The frame's name, without the channel and plane that vary within it.

    A ZMART driver writes one file per plane::

        <type>_<hash6>_K00_M000001_G000001_P000000_V00_T000000_C00_Z00000.ome.tiff

    and the short name is that without the trailing ``_C..._Z...``::

        <type>_<hash6>_K00_M000001_G000001_P000000_V00_T000000

    which is what results are filed under, because analysis of a frame spans
    its channels and its planes rather than belonging to any one of them.

    An image whose name does not follow the convention keeps its bare stem, so
    a loose file still lands somewhere predictable instead of failing.
    """
    name = Path(image_path).name
    frame = _PLANE.sub("", name)
    return frame if frame != name else name.split(".")[0]


def analysis_dir(image_path: Path | str) -> Path:
    """The ``analysis`` folder for the acquisition an image belongs to.

    Walks up from the image to its acquisition's ``data`` folder and returns
    the ``analysis`` folder beside it. The nearest ``data`` wins, so a run
    nested inside another acquisition resolves to its own.

    Raises ``ValueError`` when the image is not under a ``data`` folder at
    all. That is deliberate: an image written somewhere else has no
    acquisition to file results under, and inventing a place to write is
    worse than saying so.
    """
    path = Path(image_path)
    for folder in path.parents:
        if folder.name == DATA:
            return folder.parent / ANALYSIS
    raise ValueError(
        f"{path} is not inside an acquisition's {DATA!r} folder, so there is "
        f"no {ANALYSIS!r} folder beside it to write to. Pass output_dir "
        f"explicitly for images kept outside an acquisition."
    )
