"""
Confirmation descriptor table.
==============================
One row per per-setting readback confirmation that shares the generic poll
skeleton in ``confirmations._confirm_readback``. Each row captures the
handful of things that vary between settings and nothing else:

  * ``label``   — display name used verbatim in DEBUG + timeout logs.
  * ``extract`` — pull the current value out of a readback dict.
  * ``compare`` — exact ``==`` or absolute-tolerance ``abs(a-b) < tol``.
  * ``errors``  — exception types extraction may raise (caught + retried).

Tolerance defaults live on the ``_confirm_<name>`` wrapper signatures in
``confirmations`` (and the command profiles override them per call), so the
table carries no tolerance of its own.

The table is the single source of truth: ``confirmations`` builds one thin
``_confirm_<name>`` wrapper per row, and ``tests/unit/test_confirm_specs``
asserts the table covers exactly that set of wrappers so the two cannot
silently drift apart.

This module is deliberately pure data + pure functions — it imports nothing
from the driver, so ``confirmations`` can import it without a cycle.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# -- exception tuples caught while extracting the readback value -------------
# Each matches the ``except (...)`` clause of the original bespoke confirm:
# a bare dict path, an ``activeSettings[si]`` index, or a ``next(...)`` search.
_DICT_ERRORS = (KeyError, TypeError)
_INDEXED_ERRORS = (KeyError, TypeError, IndexError)
_SEARCH_ERRORS = (KeyError, TypeError, IndexError, StopIteration)


# -- comparators -------------------------------------------------------------
def _cmp_exact(actual, target, tolerance):
    """Exact match (discrete values: speeds, modes, counts, slots, bools)."""
    return actual == target


def _cmp_tolerance(actual, target, tolerance):
    """Absolute-tolerance match (continuous values)."""
    return abs(actual - target) < tolerance


# -- extractors: (readback_dict, params) -> current value --------------------
# ``params`` carries the per-call selectors (si / beam_route / line_index /
# fw_type). Each body reproduces the original confirm's extraction expression
# exactly, including the dict keys and the ``next(...)`` search predicate.
def _x_scan_field_rotation(ch, p):
    return ch["scanFieldRotation"]["value"]


def _x_scan_speed(ch, p):
    return ch["scanSpeed"]["value"]


def _x_scan_resonant(ch, p):
    return ch["scanSpeed"]["isResonant"]


def _x_scan_mode(ch, p):
    return ch["scanMode"]


def _x_sequential_mode(ch, p):
    return ch["sequentialMode"]


def _x_z_stack_step_size(ch, p):
    return ch["stack"]["stepSize"]


def _x_pinhole_airy(ch, p):
    return ch["activeSettings"][p["si"]]["pinholeAiry"]["value"]


def _x_frame_accumulation(ch, p):
    return ch["activeSettings"][p["si"]]["frameAccumulation"]


def _x_frame_average(ch, p):
    return ch["activeSettings"][p["si"]]["frameAverage"]


def _x_line_accumulation(ch, p):
    return ch["activeSettings"][p["si"]]["lineAccumulation"]


def _x_line_average(ch, p):
    return ch["activeSettings"][p["si"]]["lineAverage"]


def _x_detector_gain(ch, p):
    det = next(
        d
        for d in ch["activeSettings"][p["si"]]["activeDetectors"]
        if d["_beamRoute"] == p["beam_route"]
    )
    return det["gain"]["value"]


def _x_laser_intensity(ch, p):
    las = next(
        line
        for line in ch["activeSettings"][p["si"]]["activeLaserLines"]
        if line["_beamRoute"] == p["beam_route"] and line["_lineIndex"] == p["line_index"]
    )
    return las["intensity"]["value"]


def _x_laser_shutter(ch, p):
    las = next(
        line
        for line in ch["activeSettings"][p["si"]]["activeLaserLines"]
        if line["_beamRoute"] == p["beam_route"]
    )
    return las["shutterOpen"]


def _x_filter_wheel_spectrum(ch, p):
    fw = next(
        f
        for f in ch["activeSettings"][p["si"]]["filterWheels"]
        if f["_beamRoute"] == p["beam_route"] and f.get("type") == p["fw_type"]
    )
    return fw["spectrumPosition"]


def _x_filter_wheel_slot(ch, p):
    fw = next(
        f
        for f in ch["activeSettings"][p["si"]]["filterWheels"]
        if f["_beamRoute"] == p["beam_route"] and f.get("type") == p["fw_type"]
    )
    return fw["filterIndex"]


@dataclass(frozen=True)
class ConfirmSpec:
    """One readback-confirmation descriptor. See module docstring for fields."""

    label: str
    extract: Callable[..., Any]
    compare: Callable[..., bool]
    errors: tuple[type, ...]


# Field order: label, extract, compare, errors.
CONFIRM_SPECS = {
    # -- approximate match (absolute tolerance) ------------------------------
    "scan_field_rotation": ConfirmSpec(
        "ScanFieldRotation", _x_scan_field_rotation, _cmp_tolerance, _DICT_ERRORS
    ),
    "pinhole_airy": ConfirmSpec("PinholeAiry", _x_pinhole_airy, _cmp_tolerance, _INDEXED_ERRORS),
    "detector_gain": ConfirmSpec("DetectorGain", _x_detector_gain, _cmp_tolerance, _SEARCH_ERRORS),
    "laser_intensity": ConfirmSpec(
        "LaserIntensity", _x_laser_intensity, _cmp_tolerance, _SEARCH_ERRORS
    ),
    "filter_wheel_spectrum": ConfirmSpec(
        "FilterWheelSpectrum", _x_filter_wheel_spectrum, _cmp_tolerance, _SEARCH_ERRORS
    ),
    "z_stack_step_size": ConfirmSpec(
        "Z-stack step", _x_z_stack_step_size, _cmp_tolerance, _DICT_ERRORS
    ),
    # -- exact match ---------------------------------------------------------
    "scan_speed": ConfirmSpec("ScanSpeed", _x_scan_speed, _cmp_exact, _DICT_ERRORS),
    "scan_resonant": ConfirmSpec("ScanResonant", _x_scan_resonant, _cmp_exact, _DICT_ERRORS),
    "scan_mode": ConfirmSpec("ScanMode", _x_scan_mode, _cmp_exact, _DICT_ERRORS),
    "sequential_mode": ConfirmSpec("SequentialMode", _x_sequential_mode, _cmp_exact, _DICT_ERRORS),
    "frame_accumulation": ConfirmSpec(
        "FrameAccumulation", _x_frame_accumulation, _cmp_exact, _INDEXED_ERRORS
    ),
    "frame_average": ConfirmSpec("FrameAverage", _x_frame_average, _cmp_exact, _INDEXED_ERRORS),
    "line_accumulation": ConfirmSpec(
        "LineAccumulation", _x_line_accumulation, _cmp_exact, _INDEXED_ERRORS
    ),
    "line_average": ConfirmSpec("LineAverage", _x_line_average, _cmp_exact, _INDEXED_ERRORS),
    "laser_shutter": ConfirmSpec("LaserShutter", _x_laser_shutter, _cmp_exact, _SEARCH_ERRORS),
    "filter_wheel_slot": ConfirmSpec(
        "FilterWheelSlot", _x_filter_wheel_slot, _cmp_exact, _SEARCH_ERRORS
    ),
}
