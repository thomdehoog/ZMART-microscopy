"""Visit frame positions and acquire at each -- controller surface only.

Shared by the overview and target steps: optionally apply one captured state,
then move to each (x, y, z) frame position and acquire there. No driver
internals -- only the ``zmart_controller`` session (``set_state`` / ``set_xyz``
/ ``acquire``). The driver owns the frame math and the save.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._output import move_record_images, position_label, prepare_acquisition


class RunCancelled(RuntimeError):
    """A capture run was stopped on request, cleanly, between two sites.

    Raised by :func:`capture_positions` (and the focus loop) when the
    caller's ``cancel`` check answers True. It means: the stage finished
    the site it was on, nothing was committed, and no further move was
    made. It is an exception on purpose — a cancelled run must look like
    an unfinished run everywhere downstream, never like a shorter
    successful one.
    """


def _location_index(position: dict, field: str, fallback: int) -> int:
    """Prefer a vendor-provided location index; otherwise use the workflow fallback."""

    location = position.get("location") or {}
    value = location.get(field, position.get(field))
    if field == "group" and isinstance(value, dict):
        value = value.get("index", value.get("region"))
    if value is None:
        return fallback
    if isinstance(value, bool):
        raise ValueError(f"tile position {field} must be a whole-number index, got {value!r}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"tile position {field} must be a whole-number index, got {value!r}"
        ) from exc
    if isinstance(value, float) and value != parsed:
        raise ValueError(f"tile position {field} must be a whole-number index, got {value!r}")
    return parsed


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
    output_root: Any = None,
) -> list[dict]:
    """Move to each frame position and acquire; return the records in order.

    ``positions`` are frame micrometres, each a dict with ``x``/``y``/``z``.
    ``state`` (from :meth:`Session.get_state`) is applied once before the run.
    ``label`` maps ``(index, position) -> position_label``. Without an output
    root the compatibility default is the 1-based index as a string. With an
    output root, vendor `K/M/G/P/V` indices are used when present and missing
    values fall back to zero, except `P`, which counts from zero.

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
    output = (
        prepare_acquisition(output_root, acquisition_type) if output_root is not None else None
    )

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
        label_value = (
            position_label(
                _location_index(pos, "position", index - 1),
                carrier=_location_index(pos, "carrier", 0),
                compartment=_location_index(pos, "compartment", 0),
                group=_location_index(pos, "group", 0),
                view=_location_index(pos, "view", 0),
            )
            if label is None and output is not None
            else str(index)
            if label is None
            else label(index, pos)
        )
        record = session.acquire(
            acquisition_type=acquisition_type,
            position_label=label_value,
            options=options,
        )
        if output is not None:
            move_record_images(record, output.data)
            record["acquisition_root"] = str(output.root)
        records.append(record)
        if on_record is not None:
            on_record(index, pos, record)
    return records
