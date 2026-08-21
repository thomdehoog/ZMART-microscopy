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


# -- the load window -----------------------------------------------------------
#
# The window is walked here rather than in each test file for the same reason
# the colormap chooser is: it is worked on, and a gate that drives it by hand
# goes red for a reason that has nothing to do with what it checks. That has
# already happened twice -- the chooser on 2026-08-20, and the window's own
# doors on 2026-08-21, which took five gates in three files down with them.


def _reach_the_listing(page, folder) -> None:
    """Get the window looking at the folder holding what is to be opened.

    Two ways in, because the window offers two: the native chooser, which the
    tests stand in for with the server's ``browse=``, and the path box, for a
    test that knows exactly where it is pointing.
    """
    if folder is None:
        page.get_by_label("choose a folder").click()
    else:
        box = page.get_by_label("folder path")
        box.fill(str(folder))
        box.press("Enter")
    page.wait_for_timeout(500)


def open_through_the_window(page, name: str, *, folder=None) -> None:
    """Open an acquisition the way an operator does: point at it and press Open.

    ``name`` is the row to open -- an image, or a folder holding images; the
    open door takes either. ``folder`` says where to look for it, and when it
    is left out the window's own chooser is pressed instead.
    """
    page.get_by_label("open images").click()
    window = page.get_by_role("dialog", name="load data")
    window.wait_for(timeout=10_000)
    _reach_the_listing(page, folder)
    window.get_by_label(name, exact=True).wait_for(timeout=10_000)
    window.get_by_label(name, exact=True).click()
    window.get_by_label(f"open {name}", exact=True).click()


def replay_through_the_window(page, name: str, *, folder=None) -> None:
    """Relive a finished dataset as a live run, from the experimental door.

    The same walk as :func:`open_through_the_window`, but on the tab that
    exists for testing and troubleshooting rather than for looking at data,
    and pressing the button that says what it will do.
    """
    page.get_by_label("open images").click()
    window = page.get_by_role("dialog", name="load data")
    window.wait_for(timeout=10_000)
    page.get_by_label("experimental", exact=True).click()
    _reach_the_listing(page, folder)
    window.get_by_label(name, exact=True).wait_for(timeout=10_000)
    window.get_by_label(name, exact=True).click()
    page.get_by_label("open as a live run").click()
