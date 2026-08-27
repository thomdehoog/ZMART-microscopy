"""Shared position-based tile and object identifiers."""

from __future__ import annotations

import re


def tile_name(tile_id) -> str:
    """Return a stable path-friendly tile name."""
    parts = list(tile_id)
    if len(parts) >= 3:
        region = _slug(parts[0])
        row = _format_axis("r", parts[1])
        col = _format_axis("c", parts[2])
        rest = [_slug(part) for part in parts[3:]]
        return "_".join([region, row, col] + rest)
    return "_".join(_slug(part) for part in parts)


def object_name(tile_id, label: int) -> str:
    """Return a stable path-friendly object name."""
    return f"{tile_name(tile_id)}_obj{int(label):05d}"


def _format_axis(prefix: str, value) -> str:
    try:
        return f"{prefix}{int(value):03d}"
    except (TypeError, ValueError):
        return f"{prefix}{_slug(value)}"


def _slug(value) -> str:
    text = str(value)
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")
    return text or "item"
