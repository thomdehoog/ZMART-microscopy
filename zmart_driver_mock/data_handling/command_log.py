"""The command log: a record of everything the dispatchers did.

Both dispatchers write a line here for every retry, refusal, lost reply and
confirmation. Data handling saves the lines that belong to an acquisition
next to its images, so that afterwards anyone can see what was asked, what
happened, and whether it was confirmed.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("zmart_driver_mock")

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

# The log keeps at most this many lines, so a long experiment cannot fill the memory.
MAX_ENTRIES = 10_000


class CommandLog:
    """An ordered list of ``{"time", "level", "message"}`` entries."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._dropped = 0

    def record(self, level: str, message: str) -> None:
        """Add one line. ``level`` is debug, info, warning or error."""
        self._entries.append({"time": time.time(), "level": level, "message": message})
        logger.log(_LEVELS.get(level, logging.INFO), message)
        if len(self._entries) > MAX_ENTRIES:
            del self._entries[0]
            self._dropped += 1

    def mark(self) -> int:
        """A bookmark; pass it to :meth:`since` to get every line added after it."""
        return self._dropped + len(self._entries)

    def since(self, mark: int) -> list[dict[str, Any]]:
        """Every line added after the bookmark ``mark``."""
        start = max(0, mark - self._dropped)
        return [dict(entry) for entry in self._entries[start:]]
