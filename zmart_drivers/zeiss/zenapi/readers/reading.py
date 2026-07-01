"""
Reading envelope + freshness gate.
==================================
The residue of the Leica ``readers.router`` abstraction that still earns its
keep for ZEN: a small ``Reading`` record carrying the value, its source, and
when it was observed, plus ``_reading_value_after`` -- the belt-and-suspenders
freshness gate confirmations use so a readback taken *before* a command fired
can never be mistaken for post-command evidence.

ZEN has a single evidence source (the gRPC API), so ``source`` is always
``"api"`` today. The field is kept so a second source (e.g. a hardware-event
stream) can be reintroduced without changing the confirmation contract.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Reading:
    """A state read, tagged with its source and observation time."""

    value: Any
    source: str = "api"
    observed_at: float = 0.0

    @staticmethod
    def now(value: Any, source: str = "api") -> "Reading":
        return Reading(value=value, source=source, observed_at=time.time())


def _reading_value_after(reading, observed_after: float):
    """Return the reading's value only if it was observed at/after ``observed_after``.

    Accepts a ``Reading`` (from ``diagnostics=True`` reads) or a bare value
    (from plain reads). A bare value has no timestamp, so it is returned as-is
    -- the freshness gate only applies when the reader supplied provenance.
    """
    if isinstance(reading, Reading):
        if reading.observed_at < observed_after:
            return None
        return reading.value
    return reading
