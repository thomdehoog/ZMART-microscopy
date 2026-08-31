"""Detection either side of the analysis: a field's record in, targets out.

The same shape as :mod:`focus_score`: what a capture becomes as the step's
input, what the step's answer becomes in the run's own terms, and a finder
that goes through a warm analysis. The pipeline is ``object_analysis`` in
ZMART_analysis; nothing about detecting is done here.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

#: The ZMART_analysis workflow that finds the objects in one field.
PIPELINE = "object_analysis"

#: Which way the image's axes point on the stage: a column to the right is
#: +x, a row down is +y. The mock cuts its frames straight from the sample, so
#: for it this is simply true. A real driver knows its own turn (the Leica
#: keeps it in ``orientation.json``) and the record is where it belongs; until
#: a record carries it, this is the assumption, made in one place.
IMAGE_TO_STAGE = [[1.0, 0.0], [0.0, 1.0]]


def what_was_captured(record: dict, *, field: int, pixel_um: float, settings: dict) -> dict:
    """The step's input for one field: its first channel, and where it was taken.

    Detection reads one plane, and the first channel is the one a sample's
    nuclei are in. Where the field is comes off the record, because the
    acquisition is the only thing that knows. The settings arrive in the
    page's units -- a diameter in micrometres -- and leave in the detector's,
    pixels, since the detector has never seen the instrument.
    """
    every = [plane for plane in record.get("planes") or [] if int(plane.get("z", 0)) == 0]
    if not every:
        raise RuntimeError(
            "the capture reported no planes, so there is nothing to detect on"
        )
    # The first channel the capture has, whatever the instrument numbers it:
    # requiring the number 0 refused a Leica job whose channels start at 1.
    first = min(int(plane.get("c", 0)) for plane in every)
    plane = next(plane for plane in every if int(plane.get("c", 0)) == first)
    others = sorted(
        (p for p in every if int(p.get("c", 0)) != first),
        key=lambda p: int(p.get("c", 0)),
    )
    given = {
        "image_path": plane["path"],
        "tile_id": [record["acquisition_type"], int(field), 0],
        "tile_stage_xy_um": [float(plane["x_um"]), float(plane["y_um"])],
        "tile_z_um": float(plane["z_um"]),
        "source_pixel_size_um": [float(pixel_um), float(pixel_um)],
        "image_to_stage": IMAGE_TO_STAGE,
        "gpu": True,
    }
    if others:
        # Segmentation stays on the first channel; the rest ride along so
        # the features can be measured on every colour -- each measured
        # column (intensity_mean_c1, ...) becomes a gating axis with no
        # page work at all.
        given["extra_channel_paths"] = [p["path"] for p in others]
    if record.get("zarr"):
        # The capture's canonical form is its OME-Zarr position, and the
        # analysis reads it when there is one: the same reader handles both
        # (`load_plane`), so this only renames the door. The store's channels
        # are packed 0..n-1, so channel 0 is the first channel whatever the
        # instrument numbered it; segmentation stays on it, and the rest ride
        # along by index for the per-colour features. Results stay filed
        # beside the vendor's `data`, where every reader already looks.
        given["image_path"] = record["zarr"]
        given["channels"] = [0]
        given.pop("extra_channel_paths", None)
        if others:
            given["extra_channel_indices"] = list(range(1, len(others) + 1))
        analysis = Path(plane["path"]).parent
        while analysis.name and analysis.name != "data":
            analysis = analysis.parent
        if analysis.name == "data":
            given["output_dir"] = str(analysis.parent / "analysis")
    if settings.get("diameter") is not None:
        given["diameter"] = float(settings["diameter"]) / float(pixel_um)
    if settings.get("cellprob") is not None:
        given["cellprob_threshold"] = float(settings["cellprob"])
    if settings.get("border"):
        # The page says micrometres from the field's edge; the detector is
        # told pixels, like the diameter. Zero means the filter stays off.
        given["border_margin_px"] = float(settings["border"]) / float(pixel_um)
    if int(settings.get("binning") or 1) > 1:
        # Segment on a copy this many times smaller each side: most of the
        # waiting gone, the masks scaled back to the full frame by the
        # pipeline itself. One means full size and nothing is sent.
        given["segmentation_binning"] = int(settings["binning"])
    return given


def as_targets(table: dict, *, field: int, pixel_um: float) -> list[dict]:
    """The object table as targets: each one where it is on the stage, how large
    in micrometres, and how bright -- what the gate is drawn across."""
    props = table["objects"]["properties"]
    pixel_area = float(pixel_um) ** 2
    targets = []
    for index, object_id in enumerate(props["object_id"]):
        area = float(props["area"][index]) * pixel_area
        targets.append({
            "id": object_id,
            "field": int(field),
            "x": float(props["stage_x_um"][index]),
            "y": float(props["stage_y_um"][index]),
            "area": area,
            "intensity": float(props["intensity_mean"][index]),
            "r": math.sqrt(area / math.pi),
            # The mask label this object wears in its field's checkpoint --
            # what lets the page paint exactly this cell's pixels.
            "label": int(props["label"][index]),
            # The whole feature row rides along: what an operator gates on is
            # a decision made later, and a column dropped here is an axis the
            # page cannot offer.
            "features": {
                name: float(values[index])
                for name, values in props.items()
                if isinstance(values[index], (int, float))
            },
        })
    return targets


def through(analysis: Any, *, pixel_um: float) -> Callable[[dict, int, dict], list[dict]]:
    """Find the targets in each field through *analysis*, whose workers are running.

    The analysis is passed in and never built here, so its lifetime is the
    caller's -- held for as long as the page is connected, not one per field.
    """

    def find(record: dict, field: int, settings: dict) -> list[dict]:
        given = what_was_captured(record, field=field, pixel_um=pixel_um, settings=settings)
        result = analysis.run(PIPELINE, given)
        return as_targets(result["object_analysis"], field=field, pixel_um=pixel_um)

    return find
