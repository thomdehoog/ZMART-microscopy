"""detect_objects -- Cellpose object detection for one image tile."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _contracts import to_builtin  # noqa: E402
from _detection_checkpoint import (  # noqa: E402
    area_filter_params,
    border_filter_params,
    file_sha256,
    segmentation_params,
    segmentation_params_hash,
)
from _output import analysis_dir, short_name  # noqa: E402
from _segmentation import segment_position  # noqa: E402


METADATA = {
    "description": "Detect objects in a TIFF tile with Cellpose",
    "version": "1.0",
    "max_workers": 1,
    "environment": "SMART--object_analysis--vision",
}


def run(pipeline_data: dict, state: dict, **params) -> dict:
    verbose = pipeline_data.get("metadata", {}).get("verbose", 0)
    inp = pipeline_data["input"]
    seg_params = segmentation_params(inp, params)
    area_params = area_filter_params(inp, params)
    border_params = border_filter_params(inp, params)
    gpu = inp.get("gpu", params.get("gpu", True))
    detection = segment_position(
        inp["image_path"],
        state,
        channels=seg_params["channels"],
        channel_axis=seg_params["channel_axis"],
        border_margin_px=border_params["border_margin_px"],
        min_area_px=area_params["min_area_px"],
        max_area_px=area_params["max_area_px"],
        cellprob_threshold=seg_params["cellprob_threshold"],
        flow_threshold=seg_params["flow_threshold"],
        niter=seg_params["niter"],
        diameter=seg_params["diameter"],
        segmentation_binning=seg_params["segmentation_binning"],
        gpu=gpu,
        verbose=verbose,
        log_prefix="detect_objects",
    )
    detection["area_filter"] = area_params
    detection["border_filter"] = border_params
    raw_masks = detection.pop("raw_masks")
    detection["segmentation_params"] = seg_params
    detection["segmentation_params_hash"] = segmentation_params_hash(seg_params)
    artifacts = _write_detection_checkpoint(detection, raw_masks, inp, params)
    if artifacts:
        detection["artifacts"] = artifacts

    if bool(params.get("persist_only", False)):
        detection = _slim_detection_result(detection)
        pipeline_data["detect_objects"] = detection
        return pipeline_data

    pipeline_data["detect_objects"] = detection
    # Bridge to the shared classical feature extractor's current input contract.
    pipeline_data["preprocess"] = {"image": detection["image"]}
    pipeline_data["segment"] = {
        "masks": detection["masks"],
        "n_cells": detection["n_objects"],
    }
    return pipeline_data


def _write_detection_checkpoint(detection: dict, raw_masks, inp: dict, params: dict) -> dict:
    output_dir = inp.get("output_dir", params.get("output_dir", None))
    # An image inside an acquisition files itself, in the `analysis` folder
    # beside the `data` it came from. One kept outside an acquisition has no
    # such place, and writes nothing unless the caller says where.
    if output_dir is None:
        output_dir = analysis_dir(inp["image_path"])
    if output_dir is None:
        return {}

    import tifffile

    # Filed under the frame's own short name -- the name the driver wrote,
    # minus the channel and plane, which analysis of a frame spans.
    tile_dir = Path(output_dir) / "tiles" / short_name(inp["image_path"])
    tile_dir.mkdir(parents=True, exist_ok=True)
    masks_path = tile_dir / "masks.tif"
    raw_masks_path = tile_dir / "raw_masks.tif"
    checkpoint_path = tile_dir / "detection_checkpoint.json"
    tifffile.imwrite(masks_path, detection["masks"].astype("int32"))
    tifffile.imwrite(raw_masks_path, raw_masks.astype("int32"))

    checkpoint = {
        "image_path": str(inp["image_path"]),
        "image_sha256": file_sha256(inp["image_path"]),
        "tile_id": inp["tile_id"],
        "tile_stage_xy_um": inp["tile_stage_xy_um"],
        "tile_zwide_um": inp["tile_zwide_um"],
        "source_pixel_size_um": inp["source_pixel_size_um"],
        "source_image_size_px": inp.get("source_image_size_px", detection.get("image_size_px")),
        "image_to_stage": inp["image_to_stage"],
        "segmentation_params": detection["segmentation_params"],
        "segmentation_params_hash": detection["segmentation_params_hash"],
        "n_objects": detection["n_objects"],
        "n_raw_objects": detection["n_raw_objects"],
        "dropped_labels": detection["dropped_labels"],
        "area_filter": detection["area_filter"],
        "border_filter": detection["border_filter"],
        "cellpose_params": detection["cellpose_params"],
        "segmentation_resize": detection["segmentation_resize"],
        "image_size_px": detection["image_size_px"],
        "raw_masks_path": str(raw_masks_path),
        "raw_masks_sha256": file_sha256(raw_masks_path),
        "masks_path": str(masks_path),
        "masks_sha256": file_sha256(masks_path),
    }
    checkpoint_path.write_text(json.dumps(to_builtin(checkpoint), indent=2) + "\n", encoding="utf-8")
    return {
        "masks_tif": str(masks_path),
        "raw_masks_tif": str(raw_masks_path),
        "detection_checkpoint_json": str(checkpoint_path),
    }


def _slim_detection_result(detection: dict) -> dict:
    """Return checkpoint metadata without large image/mask arrays."""
    return {
        key: value
        for key, value in detection.items()
        if key not in {"image", "image_2d", "masks"}
    }
