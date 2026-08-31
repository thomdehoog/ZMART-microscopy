"""Drive to each point, capture a stack there, and have it scored.

This is the whole of "measure a focus map": move the stage to a place, acquire
a z-stack around it, and let ZMART_analysis say which plane is sharp. The
workflow's step 4 does it, and so does the operator page through its bridge,
and they must do it identically -- so they do it here.

They did not, and that is why this file exists. The bridge had a copy of the
loop, and the copy had drifted in three separate ways at once: it named the
procedure under a key no driver reads, it looked for the height under keys no
driver writes, and it drove every point to frame zero first. Every focus map an
operator ran through the page came back a column of zeros. Twenty metres away,
in the workflow, the same loop was right. A procedure written twice is a
procedure that will differ, and the difference will be silent.

Why it is no longer a vendor procedure
--------------------------------------

It called the instrument's own autofocus and kept the height that came back.
That height could not be argued with: there was no curve to show, so the
operator page's choice of sharpness metric reached nothing and the rule that
rejects a peak too narrow to be tissue -- the whole defence against focusing on
a speck of dust -- was never applied. Focusing is not instrument control; it is
an image-analysis routine that happens to run before the picture rather than
after it. So the instrument is asked for what only it can give, pixels, and the
choosing is done where every other measurement on pixels is done.

``score`` is passed in rather than imported. This module is standard library
plus ``zmart_controller`` on purpose -- that is what lets the bridge run on a
microscope PC with nothing installed on it -- so how the planes reach the
analysis, and how its environment is kept warm, is the caller's business and
not this loop's.

Where the search begins
-----------------------

The stage is driven to the place the operator wants focused, and that place is
the **centre of the stack**. How far either side to look and in what steps is
not this loop's business either: it belongs to the focussing settings the
instrument is already set to, which is why ``focussing`` is passed as the kind
of acquisition and nothing here says how many planes to take.

That is the whole difference between running a map again and refining it. Run
again, and every stack centres on the height the objective is standing at --
one good height, found by eye, and a map to rebuild around it. Refine, and each
centres on what the map already predicts there, which is a micrometre or two
from the tissue rather than somewhere near the middle of the plate. Same
focussing settings either way; different centres.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from application.parts.storage.output import (
    move_record_images,
    position_label,
    prepare_acquisition,
)

#: The kind of acquisition a focus stack is. It is what tells the instrument to
#: take a stack rather than a picture: the settings imported for this kind of
#: scan carry the range and the step.
FOCUSSING = "focussing"


class RunCancelled(RuntimeError):
    """Raised between two points when the caller asked to stop.

    Its own class rather than a bare ``RuntimeError`` so a caller can tell an
    operator pressing Stop from an instrument refusing a move. The workflow
    re-exports its own, which this is compatible with.
    """


def apply_state_settled(session: Any, settings: dict, *, timeout_s: float = 8.0) -> None:
    """Apply recorded settings, and wait until the instrument says they took.

    Two lessons from one morning at the Stellaris, both of which ran a scan
    on the wrong job.

    **The shape.** The driver reads ``changeable`` off what it is handed and
    applies that; the page's recordings store the changeable half bare. Passed
    through unwrapped, the driver found no ``changeable``, applied nothing,
    and said so to nobody — every capture ran on whatever job was selected by
    hand. So a caller holding the bare half has it wrapped, and a caller with
    a full ``get_state`` answer passes it through.

    **The wait.** ``set_state`` answers when the selection is dispatched, not
    when LAS X has finished swapping jobs, and the first field of a scan
    fired on the job the focus run left selected — a six-plane stack where an
    overview frame belonged. So the changeable state is read back until it
    matches what was asked. The readback can itself lag reality on this
    instrument, which is why a timeout proceeds with a warning rather than
    refusing a run the instrument may well be ready for.
    """
    state = settings if "changeable" in settings else {"changeable": dict(settings)}
    session.set_state(state)
    asked = state.get("changeable") or {}
    # A session that cannot report its state has nothing to wait for — the
    # controller's sessions all can, but the stubs the tests drive need not.
    reader = getattr(session, "get_state", None)
    if not asked or reader is None:
        return
    deadline = time.monotonic() + timeout_s
    standing: dict = {}
    while time.monotonic() < deadline:
        try:
            standing = reader().get("changeable") or {}
        except Exception:  # noqa: BLE001 — a flaking readback is not a failed apply
            standing = {}
        if all(standing.get(key) == value for key, value in asked.items()):
            return
        time.sleep(0.25)
    import logging

    logging.getLogger(__name__).warning(
        "the instrument's settings did not read back as asked within %.0fs "
        "(asked %r, standing %r) — capturing anyway",
        timeout_s, asked, standing,
    )


def log_focus_scoring_failed(index: int, why: Exception) -> None:
    """Say which point was lost and why, where the run's log is read."""
    import logging

    logging.getLogger(__name__).warning(
        "focus point %d could not be scored and is LOST: %s", index + 1, why
    )


def _the_drive_frames_shift(record: dict | None, centre_um) -> float:
    """How far the stack's own z axis sits from the frame the stage drives in.

    The analysis answers in the axis the planes carry, and on the Leica that
    is the sweep's own: a stack taken with the stage standing at 5781.8 µm
    files its planes as −6…+6, and the peak comes back as "+3.6". Kept that
    way, a surface was fitted through offsets and the overview drove every
    field to 3.6 micrometres above z-zero — five and three quarter
    millimetres from the sample it had just measured.

    The shift is what centres the sweep on the height the stage was driven
    to: the midpoint of the planes' own axis subtracted, the stack's centre
    added. A driver whose planes are already absolute has its midpoint at
    the centre, and the shift is zero.
    """
    planes = (record or {}).get("planes") or []
    zs = [p.get("z_um") for p in planes if isinstance(p.get("z_um"), (int, float))]
    if not zs or not isinstance(centre_um, (int, float)):
        return 0.0
    return float(centre_um) - (min(zs) + max(zs)) / 2.0


def _shifted_into_the_drive_frame(found: dict, shift: float) -> dict:
    """The score's answer, moved by *shift*: the height, and every z its
    curves carry.

    The curves too, not just the number: the plot is dragged to choose a
    height, and an axis left in the sweep's frame would hand back the very
    offsets the shift exists to retire.
    """
    if not shift:
        return found
    moved = dict(found)
    if isinstance(found.get("z_um"), (int, float)):
        moved["z_um"] = float(found["z_um"]) + shift
    traces = found.get("traces")
    if isinstance(traces, dict):
        moved["traces"] = {
            name: _a_curve_shifted(curve, shift) for name, curve in traces.items()
        }
    return moved


def _a_curve_shifted(curve, shift: float):
    if not isinstance(curve, dict):
        return curve
    moved = dict(curve)
    if isinstance(curve.get("samples"), list):
        moved["samples"] = [
            {**sample, "z": float(sample["z"]) + shift}
            if isinstance(sample, dict) and isinstance(sample.get("z"), (int, float))
            else sample
            for sample in curve["samples"]
        ]
    if isinstance(curve.get("peak_z_um"), (int, float)):
        moved["peak_z_um"] = float(curve["peak_z_um"]) + shift
    return moved


def _keep(measured: dict, acquisition: Any, record: dict) -> None:
    """Write what the analysis said, beside the stack it read.

    ``<acquisition>/analysis``, next to the ``data`` the numbers came from: a
    height on its own cannot be argued with, and the curve it was chosen from
    is the whole evidence. Without this the only copy is on the operator's
    screen, and it goes when the window does.
    """
    where = Path(acquisition) / "analysis"
    where.mkdir(parents=True, exist_ok=True)
    name = (
        f"{record['acquisition_type']}_{record['acquisition_hash']}_"
        f"{record['position_label']}_T000000_focus.json"
    )
    (where / name).write_text(json.dumps(measured, indent=2), encoding="utf-8")


def measure_focus(
    session: Any,
    points: list[dict],
    *,
    score: Any,
    state: dict | None = None,
    start_z: float | None = None,
    output_root: Any = None,
    on_point: Any = None,
    cancel: Any = None,
) -> list[dict]:
    """Capture a focus stack at each frame ``(x, y)`` and have it scored.

    ``points`` are frame micrometres, each a dict with ``x``/``y`` and
    optionally ``z`` — the centre of the stack to take there. A point that
    names no centre uses ``start_z``; if that is not given either, the height
    the objective is already at when the run begins, read once.

    ``score(record)`` is given the driver's acquire record and answers
    ``{"z_um": float | None, "traces": {...}}`` — the sharp height, or ``None``
    where nothing in the stack could be chosen, and the curves it was chosen
    from. ``None`` rather than a number, because a made-up height is worse than
    a missing one: a surface is fitted through these, so one invented zero
    drags the whole map towards a place nobody measured.

    What comes back is **in the frame the stage drives in**, whatever axis
    the score answered in: the sweep's own zero is replaced with the height
    the stack was actually centred on, for the peak, the curves and the
    planes alike. Every consumer of a measurement — the fitted surface, a
    refine's start, the scan that drives to what the map predicts — speaks
    stage z, and one relative peak among them sent a whole overview five
    millimetres from the sample.

    ``state`` (from :meth:`Session.get_state`) is the focussing settings, and
    is applied once before the run rather than per point. ``output_root`` is
    the run's own folder: given one, each stack is moved into it before being
    scored, the same way :func:`capture_positions` keeps what it captures.

    ``on_point(measurement)`` fires as each point completes, so a caller can
    show a height while the stage is still working through the rest.
    ``cancel`` is asked before every move; answering True raises
    :class:`RunCancelled` cleanly between two points, having moved nothing.
    """
    output = (
        prepare_acquisition(output_root, FOCUSSING) if output_root is not None else None
    )
    if state is not None:
        apply_state_settled(session, state)
    standing = None
    measured = []
    for index, point in enumerate(points):
        if cancel is not None and cancel():
            raise RunCancelled(
                f"the focus run was cancelled before point {index + 1} of "
                f"{len(points)}: {index} point(s) measured, and no further "
                "stage move was made."
            )
        record = None
        found = {"z_um": None, "traces": None}
        shift = 0.0
        try:
            centre = point.get("z")
            if not isinstance(centre, (int, float)):
                if start_z is None and standing is None:
                    # asked once, and only if some point needs it: on this
                    # microscope reading the stage is the call that can hang
                    standing = float(session.get_xyz()["z"]["value"])
                centre = start_z if start_z is not None else standing
            session.set_xyz(point["x"], point["y"], float(centre))

            record = session.acquire(
                acquisition_type=FOCUSSING, position_label=position_label(index)
            )
            if output is not None:
                move_record_images(record, output.data)
            shift = _the_drive_frames_shift(record, centre)
            found = _shifted_into_the_drive_frame(score(record), shift)
        except RunCancelled:
            raise
        except Exception as why:  # noqa: BLE001 -- one bad point must not end the map
            # A point that cannot be driven to, captured, or scored is a
            # LOST point, not the end of the run: every drive is absolute,
            # so the next point is untouched by this one's failure. The map
            # marches on and the row says what happened. A flaking CAM read
            # once ended the run two points in; the sentence belongs on one
            # row, not across the whole map.
            log_focus_scoring_failed(index, why)
        measurement = {
            "x_um": point["x"],
            "y_um": point["y"],
            "z_um": found.get("z_um"),
            "traces": found.get("traces"),
            # The stack's own files ride with the measurement, height by
            # height, so the chosen number can be looked at as well as read —
            # each height in the drive frame, like the number it argues for.
            "planes": [
                {
                    "path": str(plane.get("path")),
                    "z_um": float(plane["z_um"]) + shift
                    if isinstance(plane.get("z_um"), (int, float))
                    else plane.get("z_um"),
                }
                for plane in (record or {}).get("planes", [])
            ],
        }
        if output is not None and record is not None:
            # The whole measurement, not just the score: a kept height that
            # does not say where it was measured cannot be accounted for. A
            # point lost before its capture has no record to file it beside
            # -- indexing the None ended a run the armor had just saved.
            _keep(measurement, output.root, record)
        measured.append(measurement)
        if on_point is not None:
            on_point(measurement)
    return measured
