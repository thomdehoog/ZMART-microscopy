"""The copies drawn with the canvas's display settings are kept up to a limit.

From the review of 10 October, finding 20: every brightness setting the
operator tried on every field was kept as its own picture, up to about a
megapixel each, until the scan was started again. Dragging the contrast
across a large overview made the bridge grow without bound. The copies are
now kept up to a limit, and the one used longest ago goes first.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest

from ..storage import jpeg_tiles
from . import pictures, state


@pytest.fixture()
def drawn(monkeypatch):
    """A field that was captured, and a drawing that counts how often it is asked."""
    asked = []
    monkeypatch.setattr(state, "records", {"overview": [{"position_label": "P0", "planes": []}]})
    monkeypatch.setattr(state, "displayed_pictures", {})
    monkeypatch.setattr(
        jpeg_tiles, "picture_as_displayed",
        lambda planes, display, **kw: asked.append(display) or f"{display}".encode(),
    )
    return asked


def test_no_more_copies_are_kept_than_the_limit(drawn):
    for level in range(pictures.DISPLAYED_KEPT + 10):
        pictures.a_picture_as_displayed("overview", "P0", [{"window": [0, level]}])
    assert len(state.displayed_pictures) == pictures.DISPLAYED_KEPT


def test_the_copy_used_longest_ago_goes_first(drawn):
    first = [{"window": [0, 0]}]
    pictures.a_picture_as_displayed("overview", "P0", first)
    for level in range(1, pictures.DISPLAYED_KEPT):
        pictures.a_picture_as_displayed("overview", "P0", [{"window": [0, level]}])
    # Asked again, the first is now the most recent, and survives one more.
    pictures.a_picture_as_displayed("overview", "P0", first)
    pictures.a_picture_as_displayed("overview", "P0", [{"window": [0, 9999]}])
    drawn.clear()
    pictures.a_picture_as_displayed("overview", "P0", first)
    assert drawn == [], "the copy asked for recently was kept"
    pictures.a_picture_as_displayed("overview", "P0", [{"window": [0, 1]}])
    assert drawn == [[{"window": [0, 1]}]], "the copy used longest ago was drawn again"
