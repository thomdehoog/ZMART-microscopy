"""Force a matplotlib figure to repaint from inside a long-running loop.

While the microscope works, the notebook kernel is busy inside one cell (or
one button callback), and matplotlib's usual ``draw_idle`` only *schedules*
a repaint for a moment that never comes until the loop ends. The widgets
therefore call :func:`force_draw` after every incoming image: it renders the
canvas synchronously and flushes the backend's events, which is what makes a
figure visibly grow tile-by-tile (ipympl sends the fresh pixels to the
browser at that point). On the file-only Agg backend used by the tests,
flushing is meaningless — that is expected and ignored.
"""

from __future__ import annotations

from typing import Any


def force_draw(fig: Any) -> None:
    """Render *fig* now and push it to the screen, whatever the backend."""
    fig.canvas.draw()
    try:
        fig.canvas.flush_events()
    except NotImplementedError:
        # Non-interactive backends (Agg) have no event loop to flush.
        pass
