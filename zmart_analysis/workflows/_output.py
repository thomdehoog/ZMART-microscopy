"""Where an acquisition's analysis goes, and under what name.

The driver writes images into ``data``, the instrument's metadata copy sits in
``vendor``, and analysis becomes ``analysis`` beside both.
"""

from __future__ import annotations

import re
from pathlib import Path

#: A driver writes one file per C and Z of a frame; this is the tail that
#: varies within one, and everything before it names the frame.
_PLANE = re.compile(r"_C\d{2}_Z\d{5}\.ome\.tiff?$", re.IGNORECASE)


def short_name(image_path: Path | str) -> str:
    """``..._T000000_C00_Z00000.ome.tiff`` -> ``..._T000000``.

    Results are filed under the frame, not one plane of it. A name outside the
    convention keeps its bare stem.
    """
    name = Path(image_path).name
    frame = _PLANE.sub("", name)
    return frame if frame != name else name.split(".")[0]


def analysis_dir(image_path: Path | str) -> Path | None:
    """The ``analysis`` folder beside the ``data`` an image came from.

    The nearest ``data`` wins. ``None`` for an image kept outside an
    acquisition, which has no folder to be filed under and is a thing that
    happens rather than a thing that is wrong.
    """
    for folder in Path(image_path).parents:
        if folder.name == "data":
            return folder.parent / "analysis"
    return None
