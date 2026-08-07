"""A cold opening has to be the first thing its browser ever does.

The ladder measures every step through one browser, so all but its first row are
opened into a browser that the previous row warmed up -- its code compiled, its
drawing programs built. The cold column exists to say what an operator pays
instead, opening a run by starting the application.

That column has a quiet way of going wrong. If the cold opening were ever handed
the ladder's own browser instead of a fresh one, it would still produce a number,
the number would still look reasonable, and it would simply be the warm reading
again under a colder name. Nothing downstream could tell: the two differ by about
forty milliseconds, which is well inside what either varies by between runs.

So it is refused rather than trusted. A browser that has already opened something
has a context to show for it, and a browser that has not is empty.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from measure_a_run_of_positions import _refuse_a_browser_that_is_not_cold  # noqa: E402


class _ABrowser:
    """Enough of a browser to be asked whether it has been used."""

    def __init__(self, contexts):
        self.contexts = contexts


def test_a_browser_that_has_opened_nothing_is_accepted():
    _refuse_a_browser_that_is_not_cold(_ABrowser([]))


def test_a_browser_that_has_already_opened_something_is_refused():
    with pytest.raises(ValueError):
        _refuse_a_browser_that_is_not_cold(_ABrowser(["a page was opened here"]))


def test_the_refusal_says_what_went_wrong_rather_than_only_that_it_did():
    """Whoever meets this is looking at a column of plausible wrong numbers."""
    with pytest.raises(ValueError) as raised:
        _refuse_a_browser_that_is_not_cold(_ABrowser(["one", "two"]))
    said = str(raised.value).lower()
    assert "cold" in said
    assert "warm" in said


def test_several_contexts_are_refused_as_readily_as_one():
    with pytest.raises(ValueError):
        _refuse_a_browser_that_is_not_cold(_ABrowser(["one", "two", "three"]))
