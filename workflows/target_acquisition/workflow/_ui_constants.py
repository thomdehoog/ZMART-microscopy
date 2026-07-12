"""Small values shared by the review widgets in both editions.

The matplotlib widgets, the React widgets, and the plain-browser webapp host
are three front ends onto the same workflow. A couple of values have to agree
across all three, so they live here once rather than being copied into each --
that way a change (say, a different debounce window) happens in one place and
cannot drift between the editions.
"""

from __future__ import annotations

# How long, in seconds, to ignore a repeated Acquire/Measure request after a
# run finishes. While the microscope works the front end is busy, so extra
# button presses queue up and would all fire the instant the run completes --
# silently starting a second hardware run. A deliberate new run comes seconds
# later; a queued double-press comes milliseconds later, so this short window
# tells the two apart.
QUEUED_CLICK_WINDOW_S = 2.0

# The colours a channel can wear, in the order the overview viewer's colour
# button cycles through them. White comes first so a single-channel image just
# looks like the raw grayscale camera image; the rest are colour-vision-
# friendly microscopy staples. Two encodings of the same palette are kept side
# by side: matplotlib colour names for the matplotlib viewer, and the matching
# hex strings for the React viewer (same colours, same order).
CHANNEL_COLORS = ("white", "lime", "magenta", "cyan", "yellow", "red", "blue")

CHANNEL_HEX = (
    "#ffffff",  # white
    "#00ff00",  # lime
    "#ff00ff",  # magenta
    "#00ffff",  # cyan
    "#ffff00",  # yellow
    "#ff0000",  # red
    "#0000ff",  # blue
)

# A colour-vision-friendly alternative (after Okabe & Ito): these hues stay
# distinguishable with the common forms of colour blindness. Pass
# ``palette="colorblind"`` to the React overview viewer to use it.
CHANNEL_HEX_COLORBLIND = (
    "#ffffff",  # white
    "#e69f00",  # orange
    "#56b4e9",  # sky blue
    "#009e73",  # bluish green
    "#f0e442",  # yellow
    "#d55e00",  # vermillion
    "#cc79a7",  # reddish purple
)
