"""The pixel size and the frame size come from the microscope, or the reading is refused.

From the review of 10 October, finding 8. A driver may report its pixel size
as nothing (the Leica does when a job's geometry cannot be read). The bridge
then used 1 µm per pixel, and a 512-pixel frame when the format was missing
too. A plan laid on those numbers has gaps or overlaps, and objects are
measured at the wrong size, so a guess is never made: the reading is refused
with a sentence that says what the microscope did not report. Both sizes are
the controller's own keys, ``image_size_px`` and ``pixel_size_um``.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest

from ..microscope.instrument import Instrument
from . import readings, state


class Reporting:
    """A microscope whose state reports exactly the ``observed`` it is given."""

    def __init__(self, observed):
        self.context = {"driver": "stub"}
        self.observed = observed

    def get_state(self):
        return {"success": True, "output": {"changeable": {}, "observed": self.observed}}


def read(observed, monkeypatch):
    monkeypatch.setattr(state, "session", Instrument(Reporting(observed)))
    return readings.reading("acquisition")


def test_a_reading_with_both_sizes_reported_is_taken(monkeypatch):
    said = read({"pixel_size_um": [0.5, 0.5], "image_size_px": [1024, 1024]}, monkeypatch)
    assert said["frameUm"] == 512
    assert said["summary"].endswith("512 × 512 µm")


@pytest.mark.parametrize("pixel", [None, [], [None, None], [0, 0]])
def test_a_reading_without_a_pixel_size_is_refused(monkeypatch, pixel):
    with pytest.raises(RuntimeError, match="did not report its pixel size"):
        read({"pixel_size_um": pixel, "image_size_px": [1024, 1024]}, monkeypatch)


def test_a_reading_without_an_image_size_is_refused(monkeypatch):
    with pytest.raises(RuntimeError, match="how many pixels"):
        read({"pixel_size_um": [1.0, 1.0]}, monkeypatch)


def test_nothing_in_the_bridge_is_a_guessed_size_any_more():
    assert not hasattr(readings, "A_GUESSED_FORMAT_PX")
    assert not hasattr(readings, "A_GUESSED_PIXEL_UM")

