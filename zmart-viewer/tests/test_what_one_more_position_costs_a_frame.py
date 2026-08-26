"""What one more position costs a frame, and why the rate alone cannot say.

The whole arrangement exists to make the viewer stop caring how many positions a
run holds. `test_one_picture_keeps_the_drawing_rate.py` beside this file shows
that the rate does not collapse; this asks the sharper question, which is what a
*single* further position costs every frame from then on.

The two are not the same question, and the difference is not academic. A frame
rate is bounded above by the browser's own clock: `requestAnimationFrame` fires at
the display's rhythm and no faster, so on a machine quick enough to reach that
ceiling every size reads the same sixty frames a second -- one position or ten
thousand -- and the table says nothing at all. That is exactly what happened when
the run of positions was measured on a fast machine on 6 August 2026: 60.0 to 60.3
frames a second on every row from one position to two thousand, over a picture
that was genuinely being drawn.

A per-position cost cannot saturate that way. It is a slope rather than a level,
so it is nought when the claim holds and rises when it does not, whatever the
machine's ceiling happens to be -- provided the ceiling is off, which is what the
last test here guards.

**It is charged against the middle drawing frame, and getting there took two
wrong answers.** Charging against the middle gap between frames was the first:
uncapped, the browser draws in bursts, so that gap says how tightly a burst is
packed and a cost charged against it is a small constant divided by n, which
falls away as one over n and mimics the very result this hopes to find. Charging
against the mean frame was the second, and worse for being plausible -- the mean
includes the frames in which nothing was drawn at all, which on this machine are
17.3 milliseconds against a real frame's 0.8, so the quantity being measured sits
inside a constant twenty times its size. A page drawing *nothing* scores 57.7
frames a second by that measure.

Only the frames in which the picture was actually redrawn can answer this, which
is why `how_long_a_drawing_frame_took` exists and why the browser is asked to
count its own drawing calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from measure_a_run_of_positions import what_one_more_position_costs  # noqa: E402
from measure_the_frame_rate_of_a_linked_view import BROWSER_ARGS  # noqa: E402


def test_a_flat_frame_time_costs_nothing_per_position():
    """The claim holding looks like nought, not like a small number."""
    rows = [
        {"positions": 1, "drawing_ms": 8.0},
        {"positions": 1000, "drawing_ms": 8.0},
    ]
    assert what_one_more_position_costs(rows) == {1: None, 1000: 0.0}


def test_a_cost_paid_per_position_is_recovered_exactly():
    """Ten microseconds a position, hidden inside ten milliseconds of frame."""
    rows = [
        {"positions": 1, "drawing_ms": 10.0},
        {"positions": 1001, "drawing_ms": 20.0},
    ]
    assert what_one_more_position_costs(rows)[1001] == pytest.approx(10.0)


def test_every_step_is_charged_against_the_smallest_one():
    """Each row answers for itself, so a slope that bends is visible as one."""
    rows = [
        {"positions": 10, "drawing_ms": 5.0},
        {"positions": 110, "drawing_ms": 6.0},
        {"positions": 1010, "drawing_ms": 105.0},
    ]
    costs = what_one_more_position_costs(rows)
    assert costs[110] == pytest.approx(10.0)
    assert costs[1010] == pytest.approx(100.0)


def test_neither_the_mean_frame_nor_the_middle_gap_is_what_is_charged():
    """Both wrong answers of 6 August, pinned so neither can come back.

    Here the mean frame and the middle gap each say a position costs a great deal,
    and the drawing frame says it costs nothing. The drawing frame is the one that
    is right: the other two are diluted by frames in which the browser offered a
    moment and the page drew nothing in it.
    """
    rows = [
        {"positions": 1, "drawing_ms": 0.8, "mean_ms": 8.0, "usual_ms": 1.0},
        {"positions": 1001, "drawing_ms": 0.8, "mean_ms": 17.0, "usual_ms": 9.0},
    ]
    assert what_one_more_position_costs(rows)[1001] == 0.0


def test_a_row_that_drew_nothing_cannot_be_charged_at_all():
    """The row means the measurement did not happen, so it gets no number.

    Treating a page that never drew as costing nought would put the emptiest
    result at the top of the table, which is how this measurement has been fooled
    before.
    """
    rows = [
        {"positions": 1, "drawing_ms": 0.8},
        {"positions": 1001, "drawing_ms": None},
    ]
    assert what_one_more_position_costs(rows)[1001] is None


def test_nothing_can_be_charged_when_the_smallest_run_drew_nothing():
    """Every row is charged against the smallest, so it has to be a real reading."""
    rows = [
        {"positions": 1, "drawing_ms": None},
        {"positions": 1001, "drawing_ms": 0.8},
    ]
    assert what_one_more_position_costs(rows) == {1: None, 1001: None}


def test_a_frame_that_got_quicker_is_reported_as_it_was_measured():
    """Noise makes a later row quicker than the first; it is not clipped to nought.

    Rounding a negative up to nought would turn a measurement that is telling you
    the spread is wider than the effect into one that looks like a clean result.
    """
    rows = [
        {"positions": 1, "drawing_ms": 9.0},
        {"positions": 101, "drawing_ms": 8.0},
    ]
    assert what_one_more_position_costs(rows)[101] == pytest.approx(-10.0)


def test_one_step_on_its_own_has_nothing_to_be_marginal_against():
    rows = [{"positions": 400, "drawing_ms": 12.0}]
    assert what_one_more_position_costs(rows) == {400: None}


def test_the_browser_is_asked_not_to_cap_the_frame_rate():
    """Without this the per-position cost is measured against a ceiling.

    A capped browser draws every size at the same rate, so the slope this file is
    about reads as nought for the one reason that does not mean the claim holds:
    nothing was allowed to get slower.
    """
    assert "--disable-gpu-vsync" in BROWSER_ARGS
    assert "--disable-frame-rate-limit" in BROWSER_ARGS
