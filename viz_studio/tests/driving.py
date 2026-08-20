"""Driving the panel's controls the way an operator does.

Kept here rather than repeated in each test file because the panel's controls
change shape as it is worked on, and a test that drives one of them by hand is
a test that goes red for a reason that has nothing to do with what it checks.
The colormap chooser proved it: it stopped being a dropdown on 2026-08-20 and
five gates in three files went red on a control that no longer existed.
"""

from __future__ import annotations


def pick_colormap(page, channel: str, name: str) -> None:
    """Paint a channel with a colour or a lookup table, by name.

    The chooser is a small list rather than a dropdown, because every entry
    shows its own colour beside its name and a dropdown can only offer words.
    So this opens it and presses an entry. ``name`` is what the entry says --
    "green", "viridis" -- with no ``flat:`` in front of the flat colours: that
    prefix is how the panel tells its own entries apart, not something an
    operator ever sees.
    """
    page.locator(f"[aria-label='colormap {channel}']").click()
    page.wait_for_timeout(200)
    page.locator(f"[aria-label='{name} for {channel}']").click()
    page.wait_for_timeout(600)


def colormap_now(page, channel: str) -> str:
    """What the chooser says a channel is painted with.

    Without the little caret: that is the chooser saying it opens, not part
    of the name of anything.
    """
    face = page.locator(f"[aria-label='colormap {channel}']").inner_text()
    return face.replace("▾", "").strip()
