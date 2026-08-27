"""Drive to each point and let the instrument focus there.

This is the whole of "measure a focus map": move the stage to a place, ask the
driver to focus, keep the height it reports. The workflow's step 4 does it, and
so does the operator page through its bridge, and they must do it identically —
so they do it here.

They did not, and that is why this file exists. The bridge had a copy of the
loop, and the copy had drifted in three separate ways at once: it named the
procedure under a key no driver reads, it looked for the height under keys no
driver writes, and it drove every point to frame zero first. Every focus map an
operator ran through the page came back a column of zeros. Twenty metres away,
in the workflow, the same loop was right. A procedure written twice is a
procedure that will differ, and the difference will be silent.

What it must not do is import the rest of the workflow. The bridge is standard
library plus ``zmart_controller`` on purpose — that is what lets it run on a
microscope PC with nothing installed on it — so this module is too, and it
lives beside ``workflow/`` rather than inside it.

Where the search begins
-----------------------

The stage is driven to the place the operator wants focused, and that place is
the **centre of the range the instrument sweeps**. The stack itself is not this
loop's business: the driver's autofocus procedure decides how far either side
to look and in what steps, from the focussing configuration the instrument is
already set to. So a point's ``z`` is not a height to keep, it is a height to
look around.

That is the whole difference between running a map again and refining it. Run
again, and every search centres on the height the objective is standing at —
one good height, found by eye, and a map to rebuild around it. Refine, and each
centres on what the map already predicts there, which is a micrometre or two
from the tissue rather than somewhere near the middle of the plate. Same
focussing configuration either way; different centres.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from typing import Any

#: Where a driver reports the height its autofocus settled on, most telling
#: first. ``frame_z_um`` is the drivers' own contract — the sharp height in
#: frame terms, which is the only one of these in the caller's coordinates.
_WHERE_THE_HEIGHT_IS = ("frame_z_um", "focus_um", "z")


class RunCancelled(RuntimeError):
    """Raised between two points when the caller asked to stop.

    Its own class rather than a bare ``RuntimeError`` so a caller can tell an
    operator pressing Stop from an instrument refusing a move. The workflow
    re-exports its own, which this is compatible with.
    """


def height_reported(answer: dict) -> float | None:
    """The height an autofocus came back with, or ``None`` if it named none.

    ``None`` rather than a number, because a made-up height is worse than a
    missing one: a surface is fitted through these, so one invented zero drags
    the whole map towards a place nobody measured.
    """
    for key in _WHERE_THE_HEIGHT_IS:
        if isinstance(answer.get(key), (int, float)) and not isinstance(answer.get(key), bool):
            return float(answer[key])
    inside = answer.get("position")
    if isinstance(inside, dict) and isinstance(inside.get("z"), (int, float)):
        return float(inside["z"])
    return None


def measure_focus(
    session: Any,
    points: list[dict],
    *,
    af_job: str | None = None,
    start_z: float | None = None,
    on_point: Any = None,
    cancel: Any = None,
) -> list[dict]:
    """Autofocus at each frame ``(x, y)``; return ``[{"x_um","y_um","z_um"}]``.

    ``points`` are frame micrometres, each a dict with ``x``/``y`` and
    optionally ``z`` — the centre of the range to search there. A point that
    names no centre uses ``start_z``; if that is not given either, the height
    the objective is already at when the run begins, read once.

    ``af_job`` names the autofocus job, and is omitted when the instrument has
    exactly one. ``z_um`` is what the driver reported, or ``None`` where it
    reported nothing.

    ``on_point(measurement)`` fires as each point completes, so a caller can
    show a height while the stage is still working through the rest.
    ``cancel`` is asked before every move; answering True raises
    :class:`RunCancelled` cleanly between two points, having moved nothing.
    """
    standing = None
    measured = []
    for index, point in enumerate(points, start=1):
        if cancel is not None and cancel():
            raise RunCancelled(
                f"the focus run was cancelled before point {index} of "
                f"{len(points)}: {index - 1} point(s) measured, and no further "
                "stage move was made."
            )
        centre = point.get("z")
        if not isinstance(centre, (int, float)):
            if start_z is None and standing is None:
                # asked once, and only if some point needs it: on this
                # microscope reading the stage is the call that can hang
                standing = float(session.get_xyz()["z"]["value"])
            centre = start_z if start_z is not None else standing
        session.set_xyz(point["x"], point["y"], float(centre))

        procedure = {"name": "autofocus"}
        if af_job is not None:
            procedure["job"] = af_job
        found = height_reported(session.run_procedure(procedure))

        measurement = {"x_um": point["x"], "y_um": point["y"], "z_um": found}
        measured.append(measurement)
        if on_point is not None:
            on_point(measurement)
    return measured
