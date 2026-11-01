"""Readouts, never procedures: the instrument's state shaped into what the page records.

A preset -- the acquisition settings and the focussing preset alike -- is
the instrument read as it stands, after its operator set it up in the
vendor's own software: a one-line summary, the detail rows behind it, the
frame size the plan is laid with, and the changeable half the step hands
back when it runs. Nothing here moves anything. Capturing once where the
stage stands, and applying settings, are the controller's own verbs
carried through unchanged.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json

from . import state

#: What the operator is told to check when the microscope leaves a size out.
CHECK_THE_JOB = (
    "check that the image settings can be read in the microscope's own software, "
    "then read the settings again"
)


def flatten(prefix: str, mapping: dict, rows: list) -> None:
    for key, value in mapping.items():
        label = f"{prefix}{key}".replace("_", " ")
        if isinstance(value, dict) and "unit" not in value:
            flatten(f"{label} · ", value, rows)
        else:
            rows.append(
                [label, json.dumps(value, default=str) if isinstance(value, dict) else str(value)]
            )


def a_number(value) -> float | None:
    """A positive, finite number, or nothing. Booleans are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 and value == value and value != float("inf") else None


def pixel_size_um(observed: dict) -> float | None:
    """How much sample one pixel covers, in micrometres, or None when not reported.

    The controller's own key, the same on every microscope: ``pixel_size_um``,
    ``[x, y]`` for the current settings. A plan is laid in square frames, so x
    is read.
    """
    said = observed.get("pixel_size_um")
    return a_number(said[0]) if isinstance(said, (list, tuple)) and said else None


def required_pixel_size_um(observed: dict) -> float:
    """The reported pixel size, or a refusal that says what to check.

    Never a guess. Every size on the page -- the frame a scan is planned
    with, the diameter objects are found at -- is counted in pixels times
    this, and a guessed one makes all of them wrong without a word.
    """
    measured = pixel_size_um(observed)
    if measured is None:
        raise RuntimeError(f"the microscope did not report its pixel size; {CHECK_THE_JOB}")
    return measured


def frame_across(observed: dict) -> int:
    """How wide one frame is on the sample, in micrometres: its pixels across times their size.

    Both are the controller's own keys for the current settings,
    ``image_size_px`` and ``pixel_size_um``, so a plan is laid at the frame the
    microscope is set to: a switch from 512 to 2048 pixels changes the ground
    one frame covers by a factor of four, and a plan at the old frame would
    tile the sample with holes or overlaps nobody asked for. When the
    microscope does not say, this raises rather than assume a frame.
    """
    said = observed.get("image_size_px")
    across = a_number(said[0]) if isinstance(said, (list, tuple)) and said else None
    if across is None:
        raise RuntimeError(
            "the microscope did not report how many pixels its image has, so a scan cannot "
            f"be planned; {CHECK_THE_JOB}"
        )
    return round(across * required_pixel_size_um(observed))


def reading(kind: str) -> dict:
    """The instrument's state, now, as the reading the window records.

    ``kind`` is which slot is asking — ``acquisition`` or ``autofocus`` — and
    changes only the labelling: the readout underneath is the same
    ``get_state`` either way, because a preset is a readout and never a
    procedure. The instrument is read as it stands: its operator set it up
    in its own software before pressing Import -- LAS X on the Leica, the
    mock microscope's own window (``mock_microscope/window.py``) on the mock.
    """
    session = state.require_session()
    settings = session.get_state()
    observed = settings.get("observed", {})
    frame_um = frame_across(observed)

    rows: list = []
    flatten("", settings.get("changeable", {}), rows)
    flatten("", observed, rows)

    # The instrument and the frame, the two things every driver says: a
    # collapsed configuration is read to answer "how much ground does one
    # press get me". What else the driver reports (its objective, say) is the
    # driver's own and stands in the detail below, as the driver said it.
    summary = f"{state.context.get('name', 'instrument')} · {frame_um} × {frame_um} µm"
    reading = {
        "summary": summary, "detail": rows, "frameUm": frame_um,
        # The reapplicable half, kept with the reading: a recording is the
        # instrument's changeable state, and the step that recorded it hands
        # it back when it runs. Without this the recordings were readouts
        # that configured nothing.
        "changeable": settings.get("changeable", {}),
    }
    if kind == "autofocus":
        # The stand does not say which family its autofocus is; software is
        # the safe default and the Leica driver's state will name its own.
        # Said in ``kind`` and not in the summary: the row is for the numbers
        # an operator checks, and the family led it as a word nobody asked for.
        reading["kind"] = "software"
    return reading


def apply_state(asked: dict) -> dict:
    """Change settings on the instrument, and answer with what stuck.

    The page names only the settings it is changing; ``changeable`` is where
    the contract says they go, and the page has no business sending an
    ``observed`` half — that is the driver's report about itself, never an
    instruction. What comes back is the driver's own account of what it
    applied, which is not always what was asked: a value it will not take is
    the driver's to refuse.

    Which settings exist here is the driver's business, as it is for the menu.
    On the Leica it is the LAS X job; on another instrument it is whatever
    that instrument lets a client change.

    Nothing on the operator page calls this, and that is a decision rather
    than an omission: the page reads what it is told and leaves the
    choosing to the software that authors the recipes, where what each
    one carries can be seen. The verb is here because the seam mirrors
    the controller's surface, not this one page's needs.
    """
    return state.require_session().set_state({"changeable": dict(asked)})


def capture(asked: dict) -> dict:
    """Capture once where the stage is standing, and answer as the controller does.

    The answer is the controller's own, ``{"success": ..., "output": ...}``,
    passed on untouched: the output's ``files`` lists every file the capture
    saved and its ``planes`` say which channel, depth and stage position each
    picture is. What one capture wrote is known only to the capture, so it is
    answered whole rather than picked over, and a capture the microscope
    declined is an answer with ``success`` false, as it is to a script.

    ``acquisition_settings`` go through as they came from
    ``get_acquisition_settings``: how the capture is triggered. Whatever is
    left out the driver fills from its own actives, which is why nothing here
    invents a default. ``acquisition_type`` is the page's name for the
    acquisition this capture belongs to; the driver is given it, and the
    run's folder for it to save in (see :meth:`Instrument.acquire_answer`),
    and the page files the capture under it itself afterwards, through the
    route it sends the record to.
    """
    return state.require_session().acquire_answer(
        position_label=str(asked["position_label"]),
        acquisition_settings=asked.get("acquisition_settings"),
        acquisition_type=asked.get("acquisition_type"),
    )


def acquisition_settings() -> dict:
    """What the instrument offers for a capture, and what is chosen now.

    The driver's own menu, forwarded untouched: ``{name: {options, active}}``,
    where which settings exist at all is the driver's business. Nothing here
    renames or filters it, because the same shape goes back to ``acquire`` at
    capture time — a page that reworded it would have to word it back.
    """
    return state.require_session().get_acquisition_settings()
