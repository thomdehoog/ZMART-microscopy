"""Does a driver fit? Call every command on an instrument and check the answers.

``check_driver(instrument)`` connects, calls each ``get_*`` function, and
compares the ``report`` with the contract in ``docs/driver.md``. It returns a
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
                answer = getattr(session, name)()
            except Exception as exc:
                problems.append(f"{name} raised {type(exc).__name__}: {exc}")
                continue
            report = _envelope(name, answer, problems)
            if report is not None:
                check(report, problems)
    finally:
        session.disconnect()
    return problems


def _envelope(name: str, answer: Any, problems: list[str]):
    """Check the ``{"success", "report"}`` shape; return the report, or None."""
    if not isinstance(answer, dict) or not {"success", "report"} <= set(answer):
        problems.append(
            f'{name} must return {{"success": ..., "report": ...}}, got {type(answer).__name__}'
        )
        return None
    if not isinstance(answer["success"], bool):
        problems.append(f"{name}: success must be True or False")
    return answer["report"]


def _check_info(report, problems):
    if not isinstance(report, dict) or "output_root" not in report:
        problems.append("get_info: the report must contain output_root")


def _check_actuators(report, problems):
    if not isinstance(report, dict):
        problems.append("get_actuators: the report must be a dict of axis -> list of motors")
        return
    for axis in AXES:
        motors = report.get(axis)
        if not isinstance(motors, list) or not motors:
            problems.append(f"get_actuators: axis {axis!r} must list at least one motor")


def _check_xyz(report, problems):
    if not isinstance(report, dict):
        problems.append("get_xyz: the report must be a dict of axis -> reading")
        return
    for axis in AXES:
        reading = report.get(axis)
        if not isinstance(reading, dict):
            problems.append(f"get_xyz: axis {axis!r} is missing")
            continue
        for key in ("value", "actuator", "unit", "range"):
            if key not in reading:
                problems.append(f"get_xyz: axis {axis!r} is missing {key!r}")
        rng = reading.get("range")
        if rng is not None and not (isinstance(rng, (list, tuple)) and len(rng) == 2):
            problems.append(f"get_xyz: axis {axis!r} range must be [min, max]")


def _check_state(report, problems):
    if not isinstance(report, dict) or not isinstance(report.get("changeable"), dict):
        problems.append('get_state: the report must contain a "changeable" dict')
    if not isinstance(report, dict) or not isinstance(report.get("observed"), dict):
        problems.append('get_state: the report must contain an "observed" dict')


def _check_acquisition_options(report, problems):
    if not isinstance(report, dict):
        problems.append("get_acquisition_options: the report must be a dict of option -> choices")
        return
    for name, spec in report.items():
        if not isinstance(spec, dict) or "options" not in spec or "active" not in spec:
            problems.append(f'get_acquisition_options: {name!r} must have "options" and "active"')


def _check_procedures(report, problems):
    if not isinstance(report, dict):
        problems.append("get_procedures: the report must be a dict of name -> description")
        return
    for name, spec in report.items():
        if not isinstance(spec, dict) or "description" not in spec:
            problems.append(f'get_procedures: {name!r} must have a "description"')
