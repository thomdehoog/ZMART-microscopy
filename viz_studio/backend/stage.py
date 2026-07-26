"""Turn a box drawn in the viewer into a stage position the microscope can go to.

When you draw a box around something interesting and press **Go to**, the viewer
sends the box's two corners to Python. This module is the piece in between: it
works out where the middle of that box is, in micrometres, and hands that to the
microscope controller so the stage can drive there.

Two things make this worth its own file rather than a few lines in the server.

The first is **units**. The viewer thinks in whatever unit the image file
declares — an OME-Zarr store written in metres and one written in micrometres
describe the same specimen with numbers that differ by a factor of a million.
The microscope, meanwhile, always speaks micrometres from the origin you set at
the start of the session. Getting that conversion wrong would not produce a
slightly-off move; it would command a journey a million times too far. So the
conversion lives here, on its own, where it can be read and tested.

The second is **caution**. Moving a real stage is a physical act: the objective
can collide with the sample or the dish. So nothing here moves anything unless
two separate conditions are both true — a microscope session has been handed to
the server, *and* stage moves have been explicitly switched on. If either is
missing, the request is answered with the position it *would* have gone to and
nothing is touched. That way the whole path can be exercised, and demonstrated,
with no risk to an instrument.

The safety limits themselves are not re-implemented here. Each microscope driver
already knows its own travel range and refuses a move outside it, and
``set_xyz`` goes through that check. If the driver says no, that refusal is
passed straight back to the operator with its reason intact.
"""

from __future__ import annotations

import math
from typing import Any

# How many micrometres one of each unit is worth. The viewer takes these unit
# names from the image file's own axis metadata, and OME-Zarr spells them out in
# full ("micrometer"), while Neuroglancer tends to use the short symbols. Both
# spellings appear in real files, so both are accepted.
#
# A unit that is not in this table is refused rather than guessed at. Guessing
# is the dangerous option: assuming micrometres for a store written in metres
# would turn a 50 µm hop into a 50 m command.
_MICROMETRES_PER_UNIT = {
    "m": 1_000_000.0,
    "meter": 1_000_000.0,
    "metre": 1_000_000.0,
    "mm": 1_000.0,
    "millimeter": 1_000.0,
    "millimetre": 1_000.0,
    "um": 1.0,
    "µm": 1.0,  # micro sign
    "μm": 1.0,  # Greek small letter mu — visually identical, different code point
    "micron": 1.0,
    "micrometer": 1.0,
    "micrometre": 1.0,
    "nm": 0.001,
    "nanometer": 0.001,
    "nanometre": 0.001,
}

# The three axes a stage can be driven along. A store may carry more (a channel
# axis, a time axis); those describe *what* is being shown, not where the stage
# stands, so they are ignored when working out a destination.
_STAGE_AXES = ("x", "y", "z")


def to_micrometres(value: float, unit: str) -> float:
    """Convert one coordinate into micrometres.

    ``unit`` is the axis unit as the image file declares it, for example ``"m"``
    or ``"micrometer"``. An unrecognised or empty unit raises ``ValueError``
    rather than being assumed — see the note above about why guessing here is
    the unsafe choice.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("coordinate values must be numbers")
    if not math.isfinite(value):
        raise ValueError("coordinate values must be finite")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError(
            "the image does not say what unit its coordinates are in, so the "
            "stage position cannot be worked out safely"
        )
    factor = _MICROMETRES_PER_UNIT.get(unit.strip())
    if factor is None:
        raise ValueError(f"unsupported coordinate unit {unit!r}")
    return value * factor


def _axis_micrometres(point: object, axis: str) -> float | None:
    """Read one axis out of a point the viewer sent, in micrometres.

    The viewer sends each point as a small object keyed by axis name, where each
    entry carries its own value and unit, like
    ``{"x": {"value": 1.5e-5, "unit": "m"}, ...}``. Returns ``None`` when the
    point simply does not have that axis, which is normal: a 2-D overview has no
    z to speak of.
    """
    if not isinstance(point, dict):
        raise ValueError("each point must be an object keyed by axis name")
    entry = point.get(axis)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ValueError(f"axis {axis!r} must carry a value and a unit")
    return to_micrometres(entry.get("value"), entry.get("unit", ""))


def target_micrometres(payload: object) -> dict[str, float]:
    """Work out where to drive to, in micrometres, from what the viewer sent.

    A **box** (two corners, ``pointA`` and ``pointB``) drives to its middle —
    that is what "go to this region" means to an operator: put the interesting
    thing in the centre of the field of view. A **point** drives to the point
    itself.

    Only the stage axes (x, y and z) come back. An axis the image does not have
    is simply absent from the result, and an axis present in only one of the two
    corners is treated as missing rather than half-known.

    Raises ``ValueError`` if the request is not a shape this can act on, or if a
    coordinate cannot be converted safely.
    """
    if not isinstance(payload, dict):
        raise ValueError("expected an object describing the target")
    point_a = payload.get("pointA")
    point_b = payload.get("pointB")
    single = payload.get("point")

    if point_a is not None and point_b is not None:
        target = {}
        for axis in _STAGE_AXES:
            a = _axis_micrometres(point_a, axis)
            b = _axis_micrometres(point_b, axis)
            if a is None or b is None:
                continue
            target[axis] = (a + b) / 2.0
    elif single is not None:
        target = {}
        for axis in _STAGE_AXES:
            value = _axis_micrometres(single, axis)
            if value is not None:
                target[axis] = value
    else:
        raise ValueError("a target needs either a box (pointA and pointB) or a point")

    if not target:
        raise ValueError(
            "the target has none of the x, y or z axes the stage moves along"
        )
    return target


class StageRefused(RuntimeError):
    """The microscope declined the move, and this carries its reason.

    Most often this is the driver's own travel-limit check saying the
    destination is out of range — exactly the guard that should stop a move, so
    it is reported to the operator rather than worked around.
    """


def goto(
    payload: object,
    *,
    session: Any | None = None,
    allow_moves: bool = False,
) -> dict:
    """Answer a "go to this box" request, moving the stage only if allowed.

    Returns a small report describing what happened, which the server passes
    back to the viewer so the operator can see it:

    - ``target`` — where the request works out to, in micrometres, always
      included so the answer is informative even when nothing moved.
    - ``moved`` — whether the stage was actually driven.
    - ``action`` — a short sentence to show the operator.
    - ``driver`` — whatever the microscope reported about the move, when one
      happened.

    Nothing moves unless a ``session`` was supplied *and* ``allow_moves`` is
    true. With either missing the target is computed and reported and the
    instrument is left alone, which is what makes the demo safe to run anywhere.

    Raises ``ValueError`` for a request that cannot be understood, and
    :class:`StageRefused` when the microscope declines the move.
    """
    target = target_micrometres(payload)

    if session is None or not allow_moves:
        reason = (
            "no microscope is connected to the viewer"
            if session is None
            else "stage moves are switched off for this session"
        )
        return {
            "target": target,
            "moved": False,
            "action": f"Not moving: {reason}.",
        }

    # The stage needs all three axes to be told where to go. If the image only
    # gave us some of them, hold the others where they are rather than inventing
    # a value — asking the microscope where it currently stands is the only
    # honest way to fill the gap.
    if not all(axis in target for axis in _STAGE_AXES):
        try:
            current = session.get_xyz()
        except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
            raise StageRefused(f"could not read the current position: {exc}") from exc
        for axis in _STAGE_AXES:
            if axis not in target:
                value = _current_axis(current, axis)
                if value is None:
                    raise StageRefused(
                        f"the image gives no {axis} for the target and the "
                        f"microscope did not report its current {axis}"
                    )
                target[axis] = value

    try:
        record = session.set_xyz(target["x"], target["y"], target["z"])
    except ValueError:
        # A caller mistake, by the controller's contract. Let it travel as-is so
        # the server can answer "bad request" rather than "instrument failure".
        raise
    except Exception as exc:  # noqa: BLE001 -- includes the driver's refusal
        raise StageRefused(str(exc)) from exc

    return {
        "target": target,
        "moved": True,
        "action": "Moved the stage to the centre of the target.",
        "driver": record if isinstance(record, dict) else None,
    }


def _current_axis(reading: object, axis: str) -> float | None:
    """Pull one axis out of whatever ``get_xyz`` reported.

    Drivers report a position as a dict, but not all with the same shape: some
    give ``{"x": 12.0}`` and some wrap each axis as ``{"x": {"value": 12.0}}``.
    Both are read here so this works across drivers without each one having to
    change.
    """
    if not isinstance(reading, dict):
        return None
    entry = reading.get(axis)
    if isinstance(entry, dict):
        entry = entry.get("value")
    if isinstance(entry, bool) or not isinstance(entry, (int, float)):
        return None
    return float(entry) if math.isfinite(entry) else None
