"""Measure focus at operator-chosen points -- controller surface only.

Step 4: the workflow decides WHERE to focus (its own logic); this moves to each
frame (x, y) point, captures a stack there and has ZMART_analysis score it --
no vendor autofocus anywhere. Feed the result to
:func:`_focus_surface.fit_focus_surface`.

The loop itself lives in :mod:`application.parts.microscope.focus_run`,
beside the other
procedures that drive the instrument, because the operator page's bridge runs
it too and the two must not be able to differ. They did: the bridge had a copy
that named the procedure wrongly, read the height from keys no driver writes,
and drove every point to frame zero, and every focus map the page ran came back
a column of zeros while this one was right.

What stays here is the workflow's own view of it -- the name its notebook and
its widgets import, and the cancellation type they catch.
"""

from __future__ import annotations

# Named in full rather than relatively: this package is imported as top-level
# ``workflow`` (the notebook's bootstrap and the tests both put its folder on
# the path), so a relative hop to a sibling of its parent has nowhere to go.
# The repo root is on the path in every context that can import this at all.
from application.parts.microscope.focus_run import (  # noqa: E402
    RunCancelled,
    measure_focus,
)

__all__ = ["RunCancelled", "measure_focus"]
