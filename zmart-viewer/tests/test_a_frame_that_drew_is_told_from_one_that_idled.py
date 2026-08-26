"""Telling a frame that drew the picture from one that merely happened.

Counting frames turns out to measure the harness rather than the run, and this is
the repair. The fault, found on 6 August 2026 by turning the view-nudging off and
re-running: the page issued **no WebGL drawing at all** for three seconds and the
measurement still reported 57.7 frames a second. That is the floor of counting
`requestAnimationFrame` callbacks -- the browser offers them whether or not there
is anything to draw, and an idle callback costs nothing, so the count is set by
the browser's clock and by how often the harness nudges the view. Neither has
anything to do with how many positions a run holds.

Splitting the same callbacks by whether the page actually drew between them
separates two populations that are nowhere near each other:

    interval that contained drawing   0.8 ms
    interval that contained none     17.3 ms

So a frame really costs about 0.8 milliseconds, and the 8.8 that counting reported
was those two averaged in roughly equal measure. Averaging them hides the quantity
being measured inside a constant that is twenty times larger, which is why a run of
ten thousand positions and a run of one came out indistinguishable: they *are*
indistinguishable in that average, whatever the drawing costs.

A drawing frame having no draws in it at all is reported as such rather than as a
tidy nought, because it is the one reading that says the measurement did not
happen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from measure_the_frame_rate_of_a_linked_view import (  # noqa: E402
    how_long_a_drawing_frame_took,
)


def test_frames_that_all_drew_are_all_counted():
    at = [0.0, 10.0, 20.0, 30.0]
    drawn_by = [0, 1, 2, 3]
    split = how_long_a_drawing_frame_took(at, drawn_by)
    assert split["drawing_ms"] == 10.0
    assert split["drawing_frames"] == 3
    assert split["idle_ms"] is None


def test_the_idle_frames_do_not_dilute_the_drawing_ones():
    """The 6 August fault in miniature: one real frame among three empty ones.

    Counting all four gives a mean of about thirteen milliseconds and says the
    frame cost thirteen. It cost one.
    """
    at = [0.0, 1.0, 18.0, 35.0, 52.0]
    drawn_by = [0, 1, 1, 1, 1]
    split = how_long_a_drawing_frame_took(at, drawn_by)
    assert split["drawing_ms"] == 1.0
    assert split["drawing_frames"] == 1
    assert split["idle_ms"] == 17.0


def test_the_middle_drawing_frame_is_taken_not_the_mean_of_them():
    """One long frame among short ones must not carry the figure away."""
    at = [0.0, 1.0, 2.0, 3.0, 100.0]
    drawn_by = [0, 1, 2, 3, 4]
    assert how_long_a_drawing_frame_took(at, drawn_by)["drawing_ms"] == 1.0


def test_a_page_that_never_drew_says_so_rather_than_reporting_nought():
    """The reading that means the measurement did not happen.

    Nought would be indistinguishable from a frame too quick to time, and would
    make a page drawing nothing at all look like the best result on the table.
    """
    at = [0.0, 17.0, 34.0, 51.0]
    drawn_by = [0, 0, 0, 0]
    split = how_long_a_drawing_frame_took(at, drawn_by)
    assert split["drawing_ms"] is None
    assert split["drawing_frames"] == 0
    assert split["idle_ms"] == 17.0


def test_several_draws_inside_one_frame_are_one_frame():
    """A frame is a frame however many draw calls the engine made inside it."""
    at = [0.0, 5.0, 10.0]
    drawn_by = [0, 23, 88]
    split = how_long_a_drawing_frame_took(at, drawn_by)
    assert split["drawing_frames"] == 2
    assert split["drawing_ms"] == 5.0


def test_one_timestamp_is_no_intervals_at_all():
    split = how_long_a_drawing_frame_took([4.0], [0])
    assert split["drawing_ms"] is None
    assert split["idle_ms"] is None
    assert split["drawing_frames"] == 0


def test_the_draw_counts_must_line_up_with_the_timestamps():
    """A mismatch means the page was read wrongly, and silence would hide it."""
    with pytest.raises(ValueError):
        how_long_a_drawing_frame_took([0.0, 1.0, 2.0], [0, 1])
