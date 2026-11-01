"""Detection either side of the analysis: a field's record in, targets out.

The same shape as :mod:`focus_score`: what a capture becomes as the step's
input, what the step's answer becomes in the run's own terms, and a finder
that goes through a warm analysis. The pipelines are in ZMART-analysis's
``object_analysis`` workflow; nothing about detecting is done here.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: The ZMART-analysis pipeline that finds the objects in one field, by how the
#: page asked for them to be found. Both answer under the same name; the
#: watershed one runs in the classical environment, so it never pays the torch
#: worker's spawn.
PIPELINES = {"robust": "object_analysis_cellpose", "fast": "object_analysis_watershed"}

#: Where each pipeline's segmentation step leaves its record, with the device it ran on.
SEGMENTATION_STEPS = ("segment_cellpose", "segment_watershed")

def pixel_size_of(record: dict) -> float:
    """The pixel size the capture was taken at, in micrometres, from its OME-Zarr store.

    The store is the one account of the capture. What the microscope reports
    *now* is only right while the same settings are still in place: a
    detection re-run after the target job was chosen took the 40x pixel size
    for the 10x overview, and a 30 um diameter became 211 px.
    """
    store = record.get("zarr")
    if not store:
        raise RuntimeError("the capture has no OME-Zarr store, so there is nothing to detect on")
    import zarr  # noqa: PLC0415 -- kept off the import path, as the bridge does

    multiscale = dict(zarr.open(str(store), mode="r").attrs)["ome"]["multiscales"][0]
    axes = [axis.get("name") for axis in multiscale.get("axes", [])]
    for transform in multiscale["datasets"][0].get("coordinateTransformations", []):
        if transform.get("type") == "scale" and "x" in axes:
            return float(transform["scale"][axes.index("x")])
    raise RuntimeError(f"the capture's store {store} does not say its pixel size")


def what_was_captured(record: dict, *, field: int, settings: dict) -> dict:
    """The step's input for one field: the capture's store, and how to find the objects in it.

    The store says where the field lies, how large a pixel is and which
    colours it holds; the analysis reads all of that from it, so none of it is
    handed alongside. Segmentation reads the colour the page chose -- the
    first unless it said otherwise -- and the Z maximum; the other colours
    ride along by index, each a column of features to gate on. The settings
    arrive in the page's units -- a diameter in micrometres -- and leave in
    the detector's, pixels, at the store's pixel size.
    """
    planes = record.get("planes") or []
    if not planes:
        raise RuntimeError("the capture reported no planes, so there is nothing to detect on")
    pixel_um = pixel_size_of(record)
    store = Path(record["zarr"])
    colours = len({int(plane.get("c", 0)) for plane in planes})
    # Which colour is segmented, by its place in the store; a protocol written
    # before the choice existed says nothing, and that was the first colour.
    chosen = int(settings.get("channel") or 0)
    if not 0 <= chosen < colours:
        raise ValueError(f"channel {chosen} was chosen, but the capture has {colours}")
    given = {
        "image_path": str(store),
        "tile_id": [record["acquisition_type"], int(field), 0],
        "channels": [chosen],
        "z_selection": "max",
        "gpu": True,
    }
    if colours > 1:
        given["extra_channel_indices"] = [c for c in range(colours) if c != chosen]
    # The results are filed beside the ``data`` the capture was saved in, where the
    # page reads the masks from: found from a plane's file, since a capture saved
    # as files is kept as a store of its own in the run's ``positions``.
    saved = Path(planes[0]["path"])
    data = next((folder for folder in (saved, *saved.parents) if folder.name == "data"), None)
    if data is not None:
        given["output_dir"] = str(data.parent / "analysis")
    # How the objects are found: the page's word for it is the step's.
    method = settings.get("method") or "robust"
    if method not in PIPELINES:
        raise ValueError(f"unknown detection method {method!r}")
    given["method"] = method
    if method == "fast" and settings.get("threshold") is not None:
        given["threshold"] = float(settings["threshold"])
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


def through(analysis: Any) -> Callable[[dict, int, dict], dict]:
    """Find the targets in each field through *analysis*, whose workers are running.

    The analysis is passed in and never built here, so its lifetime is the
    caller's -- held for as long as the page is connected, not one per field.
    Each field answers ``{"cells": [...], "device": ...}``: the device the
    segmentation ran on travels with the field, because a run that fell back
    to the CPU took ten times longer and nothing on the page said why.
    """

    def found_in(result: dict, record: dict, field: int) -> dict:
        # The table stands under the pipeline's name; the segmentation step's
        # own record stands beside it, stripped of its arrays, and that is
        # where the device it ran on is written.
        detection = next((result[step] for step in SEGMENTATION_STEPS if step in result), {})
        device = (detection.get("detector_params") or {}).get("device")
        return {
            "cells": as_targets(
                result["object_analysis"], field=field, pixel_um=pixel_size_of(record)
            ),
            "device": device,
        }

    class Finder:
        """One field at a time by a call; many at once by :meth:`each`."""

        def __call__(self, record: dict, field: int, settings: dict) -> dict:
            given = what_was_captured(record, field=field, settings=settings)
            return found_in(analysis.run(PIPELINES[given["method"]], given), record, field)

        def each(self, records: dict, settings: dict, *, at_once: int, until=None):
            """Find in every field of *records* (``{field: record}``), *at_once*
            of them in flight, yielding ``(field, found)`` as each lands and
            ``(field, error)`` for one whose pipeline failed. Fields are
            independent, so the order they land in is the engine's."""
            givens = {
                field: what_was_captured(record, field=field, settings=settings)
                for field, record in records.items()
            }
            pipelines = {PIPELINES[given["method"]] for given in givens.values()}
            if len(pipelines) != 1:
                raise ValueError("every field of one run is found the same way")
            for field, outcome in analysis.run_each(pipelines.pop(), givens, at_once=at_once, until=until):
                if isinstance(outcome, Exception):
                    yield field, outcome
                else:
                    yield field, found_in(outcome, records[field], field)

    return Finder()


def width_of(settings: dict) -> int:
    """How many fields are found at once, by how they are found.

    The watershed is about a second of one CPU a field and fields are
    independent, so the fast way runs as wide as half the machine's cores,
    up to the twelve the pipeline allows. Cellpose holds a model on the
    card, so the robust way runs one at a time. ``at_once`` in the settings
    is the operator's own number.
    """
    import os  # noqa: PLC0415 -- the only use in this module

    asked = settings.get("at_once")
    if asked:
        return max(1, int(asked))
    if (settings.get("method") or "robust") == "fast":
        return max(2, min(12, (os.cpu_count() or 2) // 2))
    return 1
