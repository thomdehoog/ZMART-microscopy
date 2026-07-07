"""Visit frame positions and acquire at each -- controller surface only.

Shared by the overview and target steps: optionally apply one captured state,
then move to each (x, y, z) frame position and acquire there. No driver
internals -- only the ``zmart_controller`` session (``set_state`` / ``set_xyz``
/ ``acquire``). The driver owns the frame math and the save.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def capture_positions(
    session: Any,
    positions: list[dict],
    acquisition_type: str,
    *,
    state: dict | None = None,
    options: dict | None = None,
    label: Callable[[int, dict], str] | None = None,
) -> list[dict]:
    """Move to each frame position and acquire; return the records in order.

    ``positions`` are frame micrometres, each a dict with ``x``/``y``/``z``.
    ``state`` (from :meth:`Session.get_state`) is applied once before the run.
    ``label`` maps ``(index, position) -> position_label`` (default: the 1-based
    index as a string).
    """
    if state is not None:
        session.set_state(state)
    records = []
    for index, pos in enumerate(positions, start=1):
        session.set_xyz(pos["x"], pos["y"], pos["z"])
        position_label = str(index) if label is None else label(index, pos)
        records.append(
            session.acquire(
                acquisition_type=acquisition_type,
                position_label=position_label,
                options=options,
            )
        )
    return records
