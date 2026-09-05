"""The measuring procedures, written once for every microscope.

Each of these takes a :class:`Setup` -- the small vocabulary any driver
supplies -- drives it through the moves and captures a measurement needs,
hands the pictures to :mod:`zmart_analysis`, and returns the document the
driver can publish. Nothing in here names a manufacturer. That is what lets a
new driver inherit the measurements by supplying move-and-capture alone, and
what lets the measurements be checked against saved pictures without a
microscope in the room.

The stage is always returned to where it started, even when a step fails
halfway, so a measurement never leaves the rig somewhere it was not.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from .layer import Setup

_ANALYSIS = Path(__file__).resolve().parents[1] / "zmart_analysis" / "workflows" / "driver_configuration"
_ANALYSIS_STEPS = _ANALYSIS / "steps"
_ANALYSIS_PIPELINES = _ANALYSIS / "pipelines"

#: Which recipe each measurement runs by: the pipeline YAML, whose parameters
#: are the ones the step is run with, and which is archived beside the
#: result so the measurement can be repeated exactly.
PIPELINES = {"measure_orientation": "orientation", "measure_objective_pair": "objective_pair"}


def _analysis_step(name: str):
    """Load one step of the driver_configuration pipeline as the engine would."""
    path = _ANALYSIS_STEPS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"driver_configuration_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pipeline_path(step: str) -> Path:
    """The recipe a step runs by: its pipeline YAML."""
    return _ANALYSIS_PIPELINES / f"{PIPELINES[step]}.yaml"


def _pipeline_params(step: str) -> dict:
    """The step's parameters as the recipe states them, so what runs here is
    what the recipe says and what the archived recipe reproduces."""
    import yaml  # noqa: PLC0415

    recipe = yaml.safe_load(pipeline_path(step).read_text(encoding="utf-8")) or {}
    for key, stages in recipe.items():
        if key == "metadata" or not isinstance(stages, list):
            continue
        for stage in stages:
            if isinstance(stage, dict) and step in stage:
                return dict(stage[step] or {})
    return {}


def _one_plane(record: dict) -> str:
    images = record.get("images") or []
    if not images:
        raise RuntimeError("the driver captured nothing")
    return images[0]


# ---------------------------------------------------------------------------
# limits: the boundary the operator marked
# ---------------------------------------------------------------------------


def read_boundary(setup: Setup) -> dict:
    """The X and Y envelope from the four markers the operator placed.

    Returns ``{"x_um": {"range": [lo, hi]}, "y_um": {"range": [lo, hi]}}`` --
    only those two, because that is all four corners can say. Everything
    else in a limits document is a decision, not a reading.
    """
    points = setup.markers()["points"]
    xs = [float(p["x_um"]) for p in points]
    ys = [float(p["y_um"]) for p in points]
    return {"x_um": {"range": [min(xs), max(xs)]}, "y_um": {"range": [min(ys), max(ys)]}}


# ---------------------------------------------------------------------------
# orientation: three pictures and a known move
# ---------------------------------------------------------------------------


def measure_orientation(setup: Setup, *, into: str | Path, stage_move_um: float = 40.0) -> dict:
    """Image the field at home, after +X, and after +Y; ask the analysis which way
    the picture is turned. Returns the analysis's answer, whose ``orientation``
    is the document to publish when ``accepted``."""
    home = setup.where()
    hx, hy, hz = home["x_um"], home["y_um"], home["z_um"]
    into = Path(into)
    try:
        at_home = setup.acquire(into=into, name="home")
        setup.move(hx + stage_move_um, hy, hz)
        plus_x = setup.acquire(into=into, name="plus_x")
        setup.move(hx, hy, hz)
        setup.move(hx, hy + stage_move_um, hz)
        plus_y = setup.acquire(into=into, name="plus_y")
    finally:
        setup.move(hx, hy, hz)

    step = _analysis_step("measure_orientation")
    answer = step.run(
        {
            "input": {
                "home": _one_plane(at_home),
                "plus_x": _one_plane(plus_x),
                "plus_y": _one_plane(plus_y),
                "stage_move_um": float(stage_move_um),
            },
            "metadata": {"verbose": 0},
        },
        {},
        **_pipeline_params("measure_orientation"),
    )["measure_orientation"]
    answer["pipeline"] = str(pipeline_path("measure_orientation"))
    answer["images"] = {"home": at_home, "plus_x": plus_x, "plus_y": plus_y}
    answer["nominal_pixel_um"] = at_home.get("pixel_um")
    # The picture the notebook shows: what was seen, and the arrows on it.
    answer["diagnostic"] = step.write_diagnostic(
        _one_plane(at_home), _one_plane(plus_x), _one_plane(plus_y), answer, into / "orientation.png",
    )
    return answer


# ---------------------------------------------------------------------------
# calibration: the same field through two lenses
# ---------------------------------------------------------------------------


def capture_lens_view(setup: Setup, *, into: str | Path, name: str, orientation: dict | None,
                      stack_half_um: float = 6.0, stack_step_um: float = 1.0) -> dict:
    """One lens's view of the field where the stage stands, corrected for the
    rig's orientation, plus a short focus stack around the current height.

    Called once under the reference lens and once under the target lens; the
    operator changes lenses between the two in the vendor's own software.
    """
    here = setup.where()
    lens = setup.objective() if setup.can("objective") else {"slot": None, "name": "unknown"}
    into = Path(into) / name
    frame = setup.acquire(into=into, name="frame")
    heights = [here["z_um"] + d for d in _steps(-stack_half_um, stack_half_um, stack_step_um)]
    stack = setup.acquire(into=into, name="stack", z_um=heights)
    view = {
        "lens": lens,
        "pixel_um": frame.get("pixel_um"),
        "image": _corrected(_one_plane(frame), orientation),
        "stack": [_corrected(p, orientation) for p in stack["images"]],
        "z_um": stack.get("z_um") or heights,
        "position": here,
        "records": {"frame": frame, "stack": stack},
    }
    # The notebook shows the focus result under the cell that measured it,
    # so it is worked out here rather than only when the pair is measured.
    step = _analysis_step("measure_objective_pair")
    view["focus"] = step.sharp_height_um(view["stack"], view["z_um"])
    view["diagnostic"] = step.write_focus_diagnostic(
        view["stack"], view["focus"], into / "focus.png", title=f"Software Autofocus · {name}",
    )
    return view


def measure_objective_pair(reference: dict, target: dict) -> dict:
    """Ask the analysis where and at what height the target lens looks,
    relative to the reference lens, from the two views captured above."""
    step = _analysis_step("measure_objective_pair")
    answer = step.run(
        {
            "input": {
                "reference": {"image": reference["image"], "pixel_um": reference["pixel_um"],
                              "stack": reference["stack"], "z_um": reference["z_um"]},
                "target": {"image": target["image"], "pixel_um": target["pixel_um"],
                           "stack": target["stack"], "z_um": target["z_um"]},
            },
            "metadata": {"verbose": 0},
        },
        {},
        **_pipeline_params("measure_objective_pair"),
    )["measure_objective_pair"]
    answer["lenses"] = {"reference": reference["lens"], "target": target["lens"]}
    answer["pipeline"] = str(pipeline_path("measure_objective_pair"))
    into = Path(reference["records"]["frame"]["images"][0]).parent.parent
    answer["diagnostic"] = step.write_overlay_diagnostic(
        {"image": reference["image"], "pixel_um": reference["pixel_um"]},
        {"image": target["image"], "pixel_um": target["pixel_um"]},
        answer, into / "objective_pair.png",
    )
    return answer


def calibration_document(existing: dict, answer: dict) -> dict:
    """Fold one measured pair into a calibration document: the reference lens is
    the anchor at zero, and the target lens is placed relative to it."""
    objectives = dict(existing.get("objectives") or {})
    ref, tgt = answer["lenses"]["reference"], answer["lenses"]["target"]
    ref_key, tgt_key = str(ref.get("slot")), str(tgt.get("slot"))
    objectives.setdefault(ref_key, {"name": ref.get("name"), "pixel_um": answer["pixel_um"]["reference"],
                                    "translation_um": {"x": 0.0, "y": 0.0, "z": 0.0}})
    objectives[tgt_key] = {
        "name": tgt.get("name"),
        "pixel_um": answer["pixel_um"]["target"],
        "translation_um": dict(answer["translation_um"]),
        "measured_against": ref_key,
    }
    return {**existing, "objectives": objectives}


# ---------------------------------------------------------------------------
# origin: where the stage stands right now
# ---------------------------------------------------------------------------


def origin_here(setup: Setup) -> dict:
    """The document that makes the current position (0, 0, 0): the position,
    and every drive's reading and the objective as the instrument reports
    them, so what became zero is on record drive by drive."""
    here = setup.where()
    document = {"x_um": float(here["x_um"]), "y_um": float(here["y_um"]), "z_um": float(here["z_um"])}
    if here.get("actuators"):
        document["actuators"] = {k: dict(v) for k, v in here["actuators"].items()}
    if here.get("objective"):
        document["objective"] = dict(here["objective"])
    return document


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _steps(low: float, high: float, step: float) -> list[float]:
    count = int(round((high - low) / step)) + 1
    return [low + i * step for i in range(count)]


def _corrected(path: str, orientation: dict | None):
    """A raw picture laid down the way the stage sees it, or left raw when no
    orientation is known yet."""
    import numpy as np  # noqa: PLC0415
    import tifffile  # noqa: PLC0415

    array = np.asarray(tifffile.imread(path))
    while array.ndim > 2:
        array = array[0]
    if not orientation:
        return array
    if orientation.get("reflection"):
        array = np.fliplr(array)
    k = int(orientation.get("rotation_deg", 0)) // 90
    if k:
        array = np.rot90(array, k=-k)
    return np.ascontiguousarray(array)
