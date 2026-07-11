"""Visit frame positions and acquire at each -- controller surface only.

Shared by the overview and target steps: optionally apply one captured state,
then move to each (x, y, z) frame position and acquire there. No driver
internals -- only the ``zmart_controller`` session (``set_state`` / ``set_xyz``
/ ``acquire``). The driver owns the frame math and the save.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RunCancelled(RuntimeError):
    """A capture run was stopped on request, cleanly, between two sites.

    Raised by :func:`capture_positions` (and the focus loop) when the
    caller's ``cancel`` check answers True. It means: the stage finished
    the site it was on, nothing was committed, and no further move was
    made. It is an exception on purpose — a cancelled run must look like
    an unfinished run everywhere downstream, never like a shorter
    successful one.
    """


def capture_positions(
    session: Any,
    positions: list[dict],
    acquisition_type: str,
    *,
    state: dict | None = None,
    options: dict | None = None,
    label: Callable[[int, dict], str] | None = None,
    on_record: Callable[[int, dict, dict], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> list[dict]:
    """Move to each frame position and acquire; return the records in order.

    ``positions`` are frame micrometres, each a dict with ``x``/``y``/``z``.
    ``state`` (from :meth:`Session.get_state`) is applied once before the run.
    ``label`` maps ``(index, position) -> position_label`` (default: the 1-based
    index as a string).

    ``on_record`` is called as ``on_record(index, position, record)`` right
    after each acquisition completes — this is how the interactive widgets
    show every image the moment it exists instead of waiting for the whole
    run. An exception from the callback stops the run (loudly), exactly like
    a failed acquisition.

    ``cancel`` (optional) is asked before every move; answering True raises
    :class:`RunCancelled` — a clean stop at a site boundary, never mid-move
    or mid-save. The acquisitions already completed keep their saved files,
    but no records are returned: a cancelled run reads as unfinished, not
    as a shorter success.
    """
    if state is not None:
        session.set_state(state)
    records = []
    for index, pos in enumerate(positions, start=1):
        if cancel is not None and cancel():
            raise RunCancelled(
                f"the run was cancelled before site {index} of {len(positions)}: "
                f"{index - 1} acquisition(s) completed (their files are saved, "
                "but nothing was committed), and no further stage move was made."
            )
        session.set_xyz(pos["x"], pos["y"], pos["z"])
        position_label = str(index) if label is None else label(index, pos)
        record = session.acquire(
            acquisition_type=acquisition_type,
            position_label=position_label,
            options=options,
        )
        records.append(record)
        if on_record is not None:
            on_record(index, pos, record)
    return records
