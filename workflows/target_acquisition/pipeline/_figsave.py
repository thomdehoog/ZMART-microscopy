"""Save a matplotlib figure as a PNG plus vector siblings.

The PNG is the quick-look QC image; the SVG and PDF written next to it
are vector copies the operator opens in Affinity or Illustrator to build
posters. (Image content -- imshow tiles, crops, targets -- is embedded
as a raster; the overlays, axes, and text stay vector.)

Callers pass the ``.png`` path they already build; the siblings are
written alongside it with the suffix swapped.
"""
from __future__ import annotations

from pathlib import Path

# Vector copies written next to every saved PNG: SVG opens natively in
# Affinity, PDF is the cleanest path into Illustrator.
_VECTOR_SUFFIXES = (".svg", ".pdf")


def save_figure(fig, png_path, *, dpi: int = 300, **savefig_kwargs) -> None:
    """Write ``fig`` to ``png_path`` and a ``.svg`` / ``.pdf`` beside it.

    300 dpi is print/poster quality: it sets the PNG resolution and the
    resolution of the microscopy raster embedded in the SVG / PDF (the
    only resolution-bound part -- overlays and text stay vector).
    """
    png_path = Path(png_path)
    fig.savefig(png_path, dpi=dpi, **savefig_kwargs)
    for suffix in _VECTOR_SUFFIXES:
        fig.savefig(png_path.with_suffix(suffix), dpi=dpi, **savefig_kwargs)
