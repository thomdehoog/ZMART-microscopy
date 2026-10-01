"""Does a driver fit? Call every command on an instrument and check the answers.

``check_driver(instrument)`` connects, calls each ``get_*`` function, and
compares the ``answer`` with the contract in ``docs/driver.md``. It returns a
list of problems in plain words; an empty list means the driver fits. It
moves nothing and acquires nothing.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from typing import Any

from .layer import set_instrument

AXES = ("x", "y", "z")


def check_driver(instrument: dict[str, Any]) -> list[str]:
    """Connect to ``instrument`` and check every ``get_*`` answer against the contract.

    Returns the problems found, one sentence each. Empty means the driver fits.
    Raises whatever the driver raises on connect.
    """
    problems: list[str] = []
    session = set_instrument(instrument)
    try:
        checks = {
            "get_info": _check_info,
            "get_actuators": _check_actuators,
            "get_xyz": _check_xyz,
            "get_state": _check_state,
            "get_acquisition_options": _check_acquisition_options,
            "get_procedures": _check_procedures,
        }
        for name, check in checks.items():
            try:
                reply = getattr(session, name)()
            except Exception as exc:
                problems.append(f"{name} raised {type(exc).__name__}: {exc}")
                continue
            answer = _envelope(name, reply, problems)
            if answer is not None:
                check(answer, problems)
    finally:
        session.disconnect()
    return problems


def _envelope(name: str, reply: Any, problems: list[str]):
    """Check the ``{"success", "answer"}`` shape; return the answer, or None."""
    if not isinstance(reply, dict) or not {"success", "answer"} <= set(reply):
        problems.append(
            f'{name} must return {{"success": ..., "answer": ...}}, got {type(reply).__name__}'
        )
        return None
    if not isinstance(reply["success"], bool):
        problems.append(f"{name}: success must be True or False")
    return reply["answer"]


def _check_info(answer, problems):
    if not isinstance(answer, dict) or "output_root" not in answer:
        problems.append("get_info: the answer must contain output_root")


def _check_actuators(answer, problems):
    if not isinstance(answer, dict):
        problems.append("get_actuators: the answer must be a dict of axis -> list of motors")
        return
    for axis in AXES:
        motors = answer.get(axis)
        if not isinstance(motors, list) or not motors:
            problems.append(f"get_actuators: axis {axis!r} must list at least one motor")


def _check_xyz(answer, problems):
    if not isinstance(answer, dict):
        problems.append("get_xyz: the answer must be a dict of axis -> reading")
        return
    for axis in AXES:
        reading = answer.get(axis)
        if not isinstance(reading, dict):
            problems.append(f"get_xyz: axis {axis!r} is missing")
            continue
        for key in ("value", "actuator", "unit", "range"):
            if key not in reading:
                problems.append(f"get_xyz: axis {axis!r} is missing {key!r}")
        rng = reading.get("range")
        if rng is not None and not (isinstance(rng, (list, tuple)) and len(rng) == 2):
            problems.append(f"get_xyz: axis {axis!r} range must be [min, max]")


def _check_state(answer, problems):
    if not isinstance(answer, dict) or not isinstance(answer.get("changeable"), dict):
        problems.append('get_state: the answer must contain a "changeable" dict')
    if not isinstance(answer, dict) or not isinstance(answer.get("read_only"), dict):
        problems.append('get_state: the answer must contain a "read_only" dict')


def _check_acquisition_options(answer, problems):
    if not isinstance(answer, dict):
        problems.append("get_acquisition_options: the answer must be a dict of option -> choices")
        return
    for name, spec in answer.items():
        if not isinstance(spec, dict) or "options" not in spec or "active" not in spec:
            problems.append(f'get_acquisition_options: {name!r} must have "options" and "active"')


def _check_procedures(answer, problems):
    if not isinstance(answer, dict):
        problems.append("get_procedures: the answer must be a dict of name -> description")
        return
    for name, spec in answer.items():
        if not isinstance(spec, dict) or "description" not in spec:
            problems.append(f'get_procedures: {name!r} must have a "description"')
