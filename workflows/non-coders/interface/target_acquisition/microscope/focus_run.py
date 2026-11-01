"""One focus stack, once it has been captured: filed, scored and put in the stage's frame.

A focus map is measured one place at a time. The page drives the stage to a
place, has the microscope capture a z-stack around it, and then hands the
stack to the bridge, which calls :func:`measure_one_stack` here: the stack is
filed under the run, scored by ZMART-analysis, and the sharp height is
reported in the same frame the stage is driven in.

Why focusing is analysis, not a vendor procedure
------------------------------------------------

The instrument's own autofocus returns a height that cannot be argued with:
there is no curve to show, so the operator's choice of sharpness measure
reaches nothing, and the rule that rejects a peak too narrow to be tissue --
the defence against focusing on a speck of dust -- is never applied. So the
instrument is asked for what only it can give, pixels, and the choosing is
done where every other measurement on pixels is done.

``score`` is passed in rather than imported, so how the planes reach the
analysis, and how its environment is kept warm, is the caller's business.

Where the search begins
-----------------------

The stage is driven to the place the operator wants focused, and that place
is the **centre of the stack**. How far either side to look, and in what
steps, belongs to the focussing settings the instrument is set to.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..storage.output import free_name, move_record_images

#: The kind of acquisition a focus stack is. It is what tells the instrument to
#: take a stack rather than a picture: the settings imported for this kind of
#: scan carry the range and the step.
FOCUSSING = "focussing"


def as_state(settings: dict) -> dict:
    """Recorded settings in the shape ``set_state`` reads.

    The driver reads ``changeable`` off what it is handed and applies that;
    the page's recordings store the changeable half bare. Passed through
    unwrapped, the driver found no ``changeable``, applied nothing, and said
    so to nobody — every capture ran on whatever job was selected by hand.
    So the bare half is wrapped here, and a full ``get_state`` answer passes
    through. Nothing waits afterwards: ``set_state`` returns once the
    instrument has taken the settings, or raises. That is the controller's
    contract, and the wait this module once kept on the driver's behalf
    proceeded past its own timeout onto the wrong job.
    """
    return settings if "changeable" in settings else {"changeable": dict(settings)}


def log_focus_scoring_failed(index: int, why: Exception) -> None:
    """Say which point was lost and why, where the run's log is read."""
    import logging

    logging.getLogger(__name__).warning(
        "focus point %d could not be scored and is LOST: %s", index + 1, why
    )


def _keep(measured: dict, acquisition: Any, record: dict) -> None:
    """Write what the analysis said, beside the stack it read.

    ``<acquisition>/analysis``, next to the ``data`` the numbers came from: a
    height on its own cannot be argued with, and the curve it was chosen from
    is the whole evidence. Without this the only copy is on the operator's
    screen, and it goes when the window does.
    """
    where = Path(acquisition) / "analysis"
    where.mkdir(parents=True, exist_ok=True)
    kept = free_name(where, f"{record['acquisition_type']}_{record['position_label']}", "_T000000_focus.json")
    kept.write_text(json.dumps(measured, indent=2), encoding="utf-8")


def measure_one_stack(
    record: dict,
    *,
    x: float,
    y: float,
    centre: float,
    score: Any,
    index: int = 0,
    output: Any = None,
    keep: Any = None,
    cost: dict | None = None,
    on_doing: Any = None,
) -> dict:
    """The half of a point that begins once its stack is in hand.

    File the stack under the run (``output`` given), hand it to the caller's
    own keeping, score it, and keep the measurement beside the stack. What
    comes back is the measurement the page draws as one point of the map. A
    stack that cannot be scored is a LOST point, with the stack it came from
    still filed.

    The heights are used exactly as reported. Each plane's ``z_um`` is a stage
    position in the frame ``set_xyz`` takes -- that is the controller's
    contract, and placing the planes is the driver's business. The interface
    once re-centred them on the height the stage was driven to, which was
    right only for a stack centred there and moved any other stack by half
    its range. ``centre`` is kept for the caller's record and moves nothing.
    """
    cost = dict(cost or {})
    if output is not None:
        move_record_images(record, output)
        # The caller's own keeping of the landed capture -- the bridge
        # converts it to the run's canonical store -- for every stack,
        # lost or scored.
        if keep is not None:
            keep(record)
    if on_doing is not None:
        on_doing(index, "scoring")
    began = time.perf_counter()
    found = {"z_um": None, "traces": None}
    try:
        found = score(record)
        cost["score"] = time.perf_counter() - began
    except Exception as why:  # noqa: BLE001 -- one bad point must not end the map
        log_focus_scoring_failed(index, why)
    measurement = _the_measurement(x, y, found, cost, record)
    if output is not None:
        # The whole measurement, not just the score: a kept height that
        # does not say where it was measured cannot be accounted for.
        _keep(measurement, output, record)
    return measurement


def _the_measurement(x, y, found: dict, cost: dict, record: dict | None) -> dict:
    """One point's record: where, what height, the curves, the cost, the stack."""
    return {
        "x_um": x,
        "y_um": y,
        "z_um": found.get("z_um"),
        "traces": found.get("traces"),
        "cost_s": {key: round(value, 3) for key, value in cost.items()},
        "zarr": (record or {}).get("zarr"),
        # The stack's own files ride with the measurement, height by
        # height, so the chosen number can be looked at as well as read.
        "planes": [
            {"path": str(plane.get("path")), "z_um": plane.get("z_um")}
            for plane in (record or {}).get("planes", [])
        ],
    }
