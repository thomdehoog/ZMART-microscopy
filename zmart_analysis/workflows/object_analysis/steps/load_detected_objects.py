"""load_detected_objects -- re-enter object analysis from saved masks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _image_io import load_channels  # noqa: E402
from _detection_checkpoint import (  # noqa: E402
    area_filter_params,
    file_sha256,
    segmentation_params_hash,
)
from _segmentation import filter_masks_by_area  # noqa: E402


METADATA = {
    "description": "Load a saved object-detection checkpoint",
    "version": "1.0",
    "max_workers": 1,
    "environment": "SMART--object_analysis--vision",
}


def run(pipeline_data: dict, state: dict, **params) -> dict:
    inp = pipeline_data["input"]
    raw_checkpoint_path = inp.get(
        "detection_checkpoint_path",
        params.get("detection_checkpoint_path", None),
    )
    if raw_checkpoint_path is None:
        raise ValueError("load_detected_objects requires detection_checkpoint_path.")
    checkpoint_path = Path(raw_checkpoint_path)
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Detection checkpoint not found: {checkpoint_path}")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))

    expected_hash = inp.get(
        "segmentation_params_hash",
        params.get("segmentation_params_hash", None),
    )
    actual_hash = checkpoint.get("segmentation_params_hash")
    checkpoint_segmentation_params = checkpoint.get("segmentation_params", {})
    # Checkpoints written before channel_axis became part of the identity do
    # not carry that key and retain their legacy hash. New checkpoints can be
    # checked for internal consistency before their parameters are trusted.
    if "channel_axis" in checkpoint_segmentation_params:
        computed_hash = segmentation_params_hash(checkpoint_segmentation_params)
        if actual_hash != computed_hash:
            raise ValueError(
                "Detection checkpoint segmentation parameter hash does not "
                "match its stored parameters. The checkpoint may be corrupt."
            )
    if expected_hash is not None and expected_hash != actual_hash:
        raise ValueError(
            "Detection checkpoint does not match the requested segmentation "
            "parameters. Re-run detection before extracting features."
        )

    image_path = Path(checkpoint["image_path"])
    expected_image_hash = checkpoint.get("image_sha256")
    if expected_image_hash is not None and file_sha256(image_path) != expected_image_hash:
        raise ValueError(
            "Detection checkpoint image hash does not match the current image file. "
            "Re-run detection before extracting features."
        )

    masks_path = Path(checkpoint["raw_masks_path"])
    expected_masks_hash = checkpoint.get("raw_masks_sha256")
    if expected_masks_hash is not None and file_sha256(masks_path) != expected_masks_hash:
        raise ValueError(
            "Detection checkpoint raw mask hash does not match the current mask file. "
            "Re-run detection before extracting features."
        )

    # The masks are this workflow's own output, written as a plain TIFF of
    # labels; the image is the acquisition, and goes through the one contract.
    raw_masks = tifffile.imread(masks_path).astype("int32")
    image, _ = load_channels(
        image_path, checkpoint_segmentation_params.get("channels", None)
    )
    image_2d = image if image.ndim == 2 else image[..., 0]
    if raw_masks.shape != image.shape[:2]:
        raise ValueError(
            f"Detection checkpoint masks have shape {raw_masks.shape}, but selected "
            f"image data has shape {image.shape[:2]}."
        )
    if int(raw_masks.max()) != int(checkpoint["n_raw_objects"]):
        raise ValueError(
            "Detection checkpoint raw mask label count does not match n_raw_objects."
        )

    area_params = _reload_area_filter(inp, params, checkpoint)
    masks, dropped_labels = filter_masks_by_area(
        raw_masks,
        min_area_px=area_params["min_area_px"],
        max_area_px=area_params["max_area_px"],
    )
    n_objects = int(masks.max())

    # Preserve per-run feature params (output_dir/backend/crop/etc.) but restore
    # the geometry and image path that produced the saved masks.
    inp.update({
        "image_path": checkpoint["image_path"],
        "tile_id": checkpoint["tile_id"],
        "tile_stage_xy_um": checkpoint["tile_stage_xy_um"],
        "tile_zwide_um": checkpoint["tile_zwide_um"],
        "source_pixel_size_um": checkpoint["source_pixel_size_um"],
        "source_image_size_px": checkpoint["source_image_size_px"],
        "image_to_stage": checkpoint["image_to_stage"],
        "channels": None,
    })

    detection = {
        "image": image,
        "image_2d": image_2d,
        "masks": masks,
        "n_objects": n_objects,
        "n_raw_objects": int(checkpoint["n_raw_objects"]),
        "dropped_labels": dropped_labels,
        "area_filter": {
            "min_area_px": area_params["min_area_px"],
            "max_area_px": area_params["max_area_px"],
            "min_equivalent_diameter_um": area_params["min_equivalent_diameter_um"],
            "max_equivalent_diameter_um": area_params["max_equivalent_diameter_um"],
        },
        "cellpose_params": checkpoint.get("cellpose_params", {}),
        "segmentation_resize": checkpoint.get("segmentation_resize", {}),
        "image_size_px": checkpoint.get("image_size_px", checkpoint["source_image_size_px"]),
        "segmentation_params": checkpoint.get("segmentation_params", {}),
        "segmentation_params_hash": actual_hash,
        "artifacts": {
            "raw_masks_tif": str(masks_path),
            "detection_checkpoint_json": str(checkpoint_path),
        },
    }

    pipeline_data["detect_objects"] = detection
    pipeline_data["preprocess"] = {"image": detection["image"]}
    pipeline_data["segment"] = {
        "masks": detection["masks"],
        "n_cells": detection["n_objects"],
    }
    return pipeline_data


def _reload_area_filter(inp: dict, params: dict, checkpoint: dict) -> dict:
    """Return feature-run object-size filter, defaulting to the checkpoint.

    Detection writes raw masks plus the area filter that produced the detection
    summary. Feature extraction may retune that post-segmentation filter from
    raw masks, but an omitted filter must mean "use the checkpoint filter", not
    "silently fall back to workflow YAML defaults".
    """
    filter_keys = (
        "min_area_px",
        "max_area_px",
        "min_equivalent_diameter_um",
        "max_equivalent_diameter_um",
    )
    explicit = any(
        (key in inp and inp[key] is not None)
        or (key in params and params[key] is not None)
        for key in filter_keys
    )
    if explicit:
        return area_filter_params(
            inp | {"source_pixel_size_um": checkpoint["source_pixel_size_um"]},
            params,
        )

    stored = checkpoint.get("area_filter", {})
    return {
        "min_area_px": stored.get("min_area_px"),
        "max_area_px": stored.get("max_area_px"),
        "min_equivalent_diameter_um": stored.get("min_equivalent_diameter_um"),
        "max_equivalent_diameter_um": stored.get("max_equivalent_diameter_um"),
    }
