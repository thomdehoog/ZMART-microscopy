"""Shared string-to-number converters for scan-field parsers.

Used by both the spatial (``parsers.py``) and LRP (``lrp.py``) domains.
Pure helpers with no dependencies.
"""


def _to_float(s: str | None) -> float | None:
    """Convert string to float, returning None on failure."""
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(s: str | None) -> int | None:
    """Convert string to int (via float), returning None on failure."""
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None
