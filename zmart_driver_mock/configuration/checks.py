"""The checks that every configuration file must pass.

A configuration file decides where the stage may go, so a mistake in it must
be caught when the driver connects, not halfway through an experiment. Each
check raises ``ValueError`` with the file name and a plain description of the
problem.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

AXES = ("x", "y", "z")
SETTING_NAMES = ("laser_power", "gain", "exposure_ms")


def _fail(where: str, problem: str) -> None:
    raise ValueError(f"{where}: {problem}")


def _keys(value: Any, expected: set[str], where: str) -> None:
    if not isinstance(value, dict):
        _fail(where, "must be a JSON object")
    missing = expected - set(value)
    extra = set(value) - expected
    if missing:
        _fail(where, f"is missing {sorted(missing)}")
    if extra:
        _fail(where, f"has unknown entries {sorted(extra)}")


def _number(value: Any, where: str, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(where, f"{name} must be a number")
    return float(value)


def _span(value: Any, where: str, name: str) -> None:
    if not isinstance(value, list) or len(value) != 2:
        _fail(where, f"{name} must be [lowest, highest]")
    low = _number(value[0], where, name)
    high = _number(value[1], where, name)
    if not low < high:
        _fail(where, f"{name}: the lowest value must be below the highest")


def _slots(value: Any, where: str, name: str) -> None:
    if not isinstance(value, dict) or not value:
        _fail(where, f"{name} must list at least one objective slot")
    for slot in value:
        if not str(slot).isdigit():
            _fail(where, f"{name}: {slot!r} is not an objective slot number")


def check_machine_description(value: Any, where: str) -> None:
    _keys(value, {"serial", "software", "tested_versions"}, where)
    if not isinstance(value["serial"], str) or not value["serial"]:
        _fail(where, "serial must be the instrument's serial number")
    if not isinstance(value["tested_versions"], list) or not value["tested_versions"]:
        _fail(where, "tested_versions must list at least one software version")


def check_image_stage_registration(value: Any, where: str) -> None:
    _keys(value, {"orientation", "pixel_size_um"}, where)
    orientation = value["orientation"]
    try:
        (a, b), (c, d) = orientation
    except (TypeError, ValueError):
        _fail(where, "orientation must be [[a, b], [c, d]]")
    entries = (a, b, c, d)
    if any(isinstance(e, bool) or e not in (-1, 0, 1) for e in entries) or abs(a * d - b * c) != 1:
        _fail(where, "orientation must be a 90° turn or a mirror, using only -1, 0 and 1")
    if (a != 0 and b != 0) or (c != 0 and d != 0):
        _fail(where, "orientation must line the camera up with the stage axes")
    _slots(value["pixel_size_um"], where, "pixel_size_um")
    for slot, size in value["pixel_size_um"].items():
        if _number(size, where, f"pixel_size_um[{slot}]") <= 0:
            _fail(where, f"pixel_size_um[{slot}] must be above 0")


def check_origin(value: Any, where: str) -> None:
    _keys(value, set(AXES), where)
    for axis in AXES:
        _number(value[axis], where, axis)


def check_limits(value: Any, where: str) -> None:
    _keys(value, {"stage_um", "settings", "objectives", "acquisition"}, where)
    _keys(value["stage_um"], set(AXES), f"{where} (stage_um)")
    for axis in AXES:
        _span(value["stage_um"][axis], where, f"stage_um.{axis}")
    _keys(value["settings"], set(SETTING_NAMES), f"{where} (settings)")
    for name in SETTING_NAMES:
        _span(value["settings"][name], where, f"settings.{name}")
    objectives = value["objectives"]
    if not isinstance(objectives, list) or not all(
        isinstance(slot, int) and not isinstance(slot, bool) for slot in objectives
    ):
        _fail(where, "objectives must list the allowed slot numbers, e.g. [1, 2, 3]")
    _keys(value["acquisition"], {"max_z_planes"}, f"{where} (acquisition)")
    planes = value["acquisition"]["max_z_planes"]
    if isinstance(planes, bool) or not isinstance(planes, int) or planes < 1:
        _fail(where, "acquisition.max_z_planes must be a whole number of at least 1")


def check_optical_calibration(value: Any, where: str) -> None:
    _keys(value, {"objective_offsets_um"}, where)
    _slots(value["objective_offsets_um"], where, "objective_offsets_um")
    for slot, offset in value["objective_offsets_um"].items():
        _keys(offset, set(AXES), f"{where} (objective {slot})")
        for axis in AXES:
            _number(offset[axis], where, f"objective_offsets_um[{slot}].{axis}")


CHECKS: dict[str, Callable[[Any, str], None]] = {
    "machine_description": check_machine_description,
    "image_stage_registration": check_image_stage_registration,
    "origin": check_origin,
    "limits": check_limits,
    "optical_calibration": check_optical_calibration,
}
