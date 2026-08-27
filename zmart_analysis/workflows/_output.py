"""Where the analysis of an acquisition goes.

A ZMART acquisition is a folder with parts: the driver writes its images into
``data``, the instrument's own metadata copy sits in ``vendor`` beside them,
and what is made from the pixels becomes ``analysis`` beside both. This says
which folder that is, so no step spells the layout out again.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The channel and plane at the end of a ZMART image name; everything before
#: it is the frame. A driver writes one file per C and Z of the same frame.
_PLANE = re.compile(r"_C\d{2}_Z\d{5}\.ome\.tiff?$", re.IGNORECASE)


def short_name(image_path: Path | str) -> str:
    """The frame's name, without the channel and plane that vary within it::

        overview_a1b2c3_..._V00_T000000_C00_Z00000.ome.tiff   the file
        overview_a1b2c3_..._V00_T000000                       the short name

    Results are filed under it because analysis of a frame spans its channels
    and planes rather than belonging to any one of them. A name outside the
    convention keeps its bare stem.
    """
    name = Path(image_path).name
    frame = _PLANE.sub("", name)
    return frame if frame != name else name.split(".")[0]


def analysis_dir(image_path: Path | str) -> Path:
    """The ``analysis`` folder beside the ``data`` an image came from.

    The nearest ``data`` wins, so a run nested inside another acquisition
    resolves to its own. Raises when the image is under no ``data`` folder at
    all: inventing a place to write is worse than saying there is none.
    """
    for folder in Path(image_path).parents:
        if folder.name == "data":
            return folder.parent / "analysis"
    raise ValueError(
        f"{image_path} is not inside an acquisition's 'data' folder. Pass "
        f"output_dir explicitly for images kept outside an acquisition."
    )
