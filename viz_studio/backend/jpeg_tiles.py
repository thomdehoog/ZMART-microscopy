"""The small JPEG copies moved to ``application.parts.storage.jpeg_tiles``.

They were written here when this folder was the Viewer prototype's backend.
The bridge still makes the focus slice previews and the JPEG fallback tiles
from them, so they belong with the run's other storage code, where the
supported runtime lives. This file only points the historical tests at the
new home; nothing in the runtime imports this folder any more.
"""

from application.parts.storage.jpeg_tiles import *  # noqa: F401,F403
from application.parts.storage.jpeg_tiles import (  # noqa: F401
    _as_jpeg,
    _flatten,
    _how_bright,
    _note_in,
    _one_brightening_for_the_whole_scan,
    _planes_among,
    _shrink_to,
    _stretch,
    _write_the_note,
)
