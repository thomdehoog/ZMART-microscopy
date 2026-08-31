"""build_object_table -- publish the object_analysis public contract."""

from __future__ import annotations
from typing import Any
from collections.abc import Mapping
import math
import json

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


METADATA = {
    "description": "Build the public object_analysis table",
    "version": "1.0",
    "max_workers": 1,
}


FEATURE_COLUMN_MAP = {
    "label": "label",
    "centroid-0": "centroid_row_px",
    "centroid-1": "centroid_col_px",
    "bbox-0": "bbox_min_row_px",
    "bbox-1": "bbox_min_col_px",
    "bbox-2": "bbox_max_row_px",
    "bbox-3": "bbox_max_col_px",
    "area": "area",
    "intensity_mean": "intensity_mean",
    "eccentricity": "eccentricity",
}

def run(pipeline_data: dict, state: dict, **params) -> dict:
    feature_output = pipeline_data["extract_features"]
    props = feature_output["properties"]

    public_props = _map_feature_columns(props)
    n_objects = len(public_props.get("label", []))
    geometry = _geometry_from_input(
        pipeline_data["input"],
        pipeline_data.get("detect_objects", {}),
    )
    _add_stage_columns(public_props, geometry)
    _add_identity_columns(public_props, geometry)

    objects = {
        "properties": public_props,
        "n_objects": n_objects,
    }

    tile_detection = validate_tile_detection({
        "objects": objects,
        "geometry": geometry,
    })

    pipeline_data["object_analysis"] = tile_detection
    if not _setting(pipeline_data["input"], params, "keep_intermediate", False):
        _strip_heavy_intermediates(pipeline_data)
    return pipeline_data


def _map_feature_columns(props: dict) -> dict:
    public_props = {}
    for source, public in FEATURE_COLUMN_MAP.items():
        if source not in props:
            raise ValueError(
                f"extract_features output missing required column {source!r} "
                f"for public column {public!r}."
            )
        public_props[public] = to_builtin(props[source])

    mapped_sources = set(FEATURE_COLUMN_MAP)
    for name, values in props.items():
        if name not in mapped_sources and name not in public_props:
            public_props[name] = to_builtin(values)
    return public_props


def _add_stage_columns(props: dict, geometry: dict) -> None:
    stage_x = []
    stage_y = []
    for row in range(len(props["label"])):
        x_um, y_um = image_point_to_stage_xy(
            centroid_row_px=props["centroid_row_px"][row],
            centroid_col_px=props["centroid_col_px"][row],
            image_size_px=geometry["source_image_size_px"],
            pixel_size_um=geometry["source_pixel_size_um"],
            tile_stage_xy_um=geometry["tile_stage_xy_um"],
            image_to_stage=geometry["image_to_stage"],
        )
        stage_x.append(float(x_um))
        stage_y.append(float(y_um))
    props["stage_x_um"] = stage_x
    props["stage_y_um"] = stage_y


def _add_identity_columns(props: dict, geometry: dict) -> None:
    t_name = tile_name(geometry["tile_id"])
    props["tile_name"] = [t_name for _ in props["label"]]
    props["object_id"] = [
        object_name(geometry["tile_id"], int(label)) for label in props["label"]
    ]


def _geometry_from_input(inp: dict, detection: dict) -> dict:
    required = [
        "tile_id",
        "tile_stage_xy_um",
        "source_pixel_size_um",
        "image_to_stage",
    ]
    for name in required:
        if name not in inp:
            raise ValueError(f"input missing required geometry field {name!r}.")

    return {
        "tile_id": inp["tile_id"],
        "tile_stage_xy_um": inp["tile_stage_xy_um"],
        # The height the tile was captured at, in the frame the acquisition
        # reports z in -- provenance, and optional: a source that does not
        # know it says so rather than writing a fabricated zero.
        "tile_z_um": inp.get("tile_z_um"),
        "source_pixel_size_um": inp["source_pixel_size_um"],
        "source_image_size_px": inp.get(
            "source_image_size_px", detection.get("image_size_px")
        ),
        "image_to_stage": inp["image_to_stage"],
    }


def _strip_heavy_intermediates(pipeline_data: dict) -> None:
    pipeline_data.pop("preprocess", None)
    pipeline_data.pop("segment", None)
    pipeline_data.pop("extract_features", None)
    detection = pipeline_data.get("detect_objects")
    if isinstance(detection, dict):
        detection.pop("image", None)
        detection.pop("image_2d", None)
        detection.pop("masks", None)



def _setting(inp: dict, params: dict, key: str, default):
    return inp[key] if key in inp else params.get(key, default)


def image_point_to_stage_xy(
    *,
    centroid_row_px,
    centroid_col_px,
    image_size_px,
    pixel_size_um,
    tile_stage_xy_um,
    image_to_stage,
) -> tuple[float, float]:
    """Convert an image centroid to absolute stage coordinates.

    ``image_size_px`` is ``[nx, ny]``. ``pixel_size_um`` is
    ``[pixel_width_um, pixel_height_um]``. Image centroids are row/col;
    stage offsets are x/y, so col maps to x and row maps to y.
    """
    nx, ny = image_size_px
    pixel_width_um, pixel_height_um = pixel_size_um
    tile_x_um, tile_y_um = tile_stage_xy_um
    m00, m01 = image_to_stage[0]
    m10, m11 = image_to_stage[1]

    offset_x_um = (float(centroid_col_px) - float(nx) / 2.0) * float(pixel_width_um)
    offset_y_um = (float(centroid_row_px) - float(ny) / 2.0) * float(pixel_height_um)

    stage_x_um = float(tile_x_um) + float(m00) * offset_x_um + float(m01) * offset_y_um
    stage_y_um = float(tile_y_um) + float(m10) * offset_x_um + float(m11) * offset_y_um
    return stage_x_um, stage_y_um


def tile_name(tile_id) -> str:
    """Return a stable path-friendly tile name."""
    parts = list(tile_id)
    if len(parts) >= 3:
        region = _slug(parts[0])
        row = _format_axis("r", parts[1])
        col = _format_axis("c", parts[2])
        rest = [_slug(part) for part in parts[3:]]
        return "_".join([region, row, col] + rest)
    return "_".join(_slug(part) for part in parts)


def object_name(tile_id, label: int) -> str:
    """Return a stable path-friendly object name."""
    return f"{tile_name(tile_id)}_obj{int(label):05d}"


def _format_axis(prefix: str, value) -> str:
    try:
        return f"{prefix}{int(value):03d}"
    except (TypeError, ValueError):
        return f"{prefix}{_slug(value)}"


def _slug(value) -> str:
    text = str(value)
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")
    return text or "item"


REQUIRED_OBJECT_COLUMNS = (
    "label",
    "centroid_row_px",
    "centroid_col_px",
    "bbox_min_row_px",
    "bbox_min_col_px",
    "bbox_max_row_px",
    "bbox_max_col_px",
    "area",
    "intensity_mean",
    "eccentricity",
    "stage_x_um",
    "stage_y_um",
)

REQUIRED_GEOMETRY_FIELDS = (
    "tile_id",
    "tile_stage_xy_um",
    "source_pixel_size_um",
    "source_image_size_px",
    "image_to_stage",
)

REQUIRED_TARGET_FIELDS = (
    "target_id",
    "tile_id",
    "object_label",
    "score",
    "source_feature",
    "centroid_row_px",
    "centroid_col_px",
    "bbox_min_row_px",
    "bbox_min_col_px",
    "bbox_max_row_px",
    "bbox_max_col_px",
    "stage_x_um",
    "stage_y_um",
)


def to_builtin(obj: Any) -> Any:
    """Return a JSON-native copy of ``obj``.

    Numpy arrays/scalars are converted via ``tolist``/``item`` without
    importing numpy. Tuples become lists, and non-finite floats become
    ``None`` so ``json.dump(..., allow_nan=False)`` remains valid.
    """
    if obj is None or type(obj) in (str, bool, int):
        return obj
    if type(obj) is float:
        return obj if math.isfinite(obj) else None
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Mapping):
        return {str(key): to_builtin(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_builtin(value) for value in obj]
    if hasattr(obj, "item") and getattr(obj, "ndim", 0) == 0:
        # Only true scalars take the item() door: a ONE-element numpy array
        # answers item() just as happily, and taking it collapsed every
        # column of a single-object field to a bare number -- len() then
        # died on an int at the top of the table step.
        try:
            return to_builtin(obj.item())
        except (TypeError, ValueError):
            pass
    if hasattr(obj, "tolist"):
        return to_builtin(obj.tolist())
    raise TypeError(f"Value of type {type(obj).__name__} is not JSON-native.")


def validate_tile_detection(tile: Mapping[str, Any]) -> dict:
    """Validate and return a JSON-native per-tile detection output."""
    tile = _json_checked(to_builtin(tile), "tile detection")
    if not isinstance(tile, dict):
        raise ValueError("tile detection must be a dict.")

    objects = _require_dict(tile, "objects", "tile detection")
    props = _require_dict(objects, "properties", "objects")
    n_objects = objects.get("n_objects")
    if not isinstance(n_objects, int) or isinstance(n_objects, bool) or n_objects < 0:
        raise ValueError("objects.n_objects must be a non-negative int.")

    for name in REQUIRED_OBJECT_COLUMNS:
        if name not in props:
            raise ValueError(f"objects.properties missing required column {name!r}.")

    for name, values in props.items():
        if not isinstance(values, list):
            raise ValueError(f"objects.properties[{name!r}] must be a list.")
        if len(values) != n_objects:
            raise ValueError(
                f"objects.properties[{name!r}] has length {len(values)}; "
                f"expected n_objects={n_objects}."
            )

    geometry = _require_dict(tile, "geometry", "tile detection")
    for name in REQUIRED_GEOMETRY_FIELDS:
        if name not in geometry:
            raise ValueError(f"geometry missing required field {name!r}.")

    _require_list_len(geometry, "tile_id", None, "geometry")
    _require_list_len(geometry, "tile_stage_xy_um", 2, "geometry")
    _require_list_len(geometry, "source_pixel_size_um", 2, "geometry")
    _require_list_len(geometry, "source_image_size_px", 2, "geometry")
    matrix = _require_list_len(geometry, "image_to_stage", 2, "geometry")
    for row in matrix:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("geometry.image_to_stage must be a 2x2 list.")

    embeddings = objects.get("embeddings")
    if embeddings is not None:
        if not isinstance(embeddings, dict):
            raise ValueError("objects.embeddings must be a dict when present.")
        if "label" in embeddings:
            labels = embeddings["label"]
            if not isinstance(labels, list) or len(labels) != n_objects:
                raise ValueError(
                    "objects.embeddings.label must be a list aligned to n_objects."
                )
            if labels != props["label"]:
                raise ValueError(
                    "objects.embeddings.label must match objects.properties.label."
                )
        if "vectors" in embeddings:
            vectors = embeddings["vectors"]
            if not isinstance(vectors, list) or len(vectors) != n_objects:
                raise ValueError(
                    "objects.embeddings.vectors must be a list aligned to n_objects."
                )
            for idx, vector in enumerate(vectors):
                if not isinstance(vector, list):
                    raise ValueError(
                        f"objects.embeddings.vectors[{idx}] must be a list."
                    )

    return tile


def validate_targets(result: Mapping[str, Any]) -> dict:
    """Validate and return JSON-native target discovery output."""
    result = _json_checked(to_builtin(result), "targets result")
    if not isinstance(result, dict):
        raise ValueError("targets result must be a dict.")
    targets = result.get("targets")
    if not isinstance(targets, list):
        raise ValueError("targets must be a list.")

    for idx, target in enumerate(targets):
        if not isinstance(target, dict):
            raise ValueError(f"targets[{idx}] must be a dict.")
        for name in REQUIRED_TARGET_FIELDS:
            if name not in target:
                raise ValueError(f"targets[{idx}] missing required field {name!r}.")
        if not isinstance(target["target_id"], list):
            raise ValueError(f"targets[{idx}].target_id must be a list.")
        if not isinstance(target["tile_id"], list):
            raise ValueError(f"targets[{idx}].tile_id must be a list.")
        for name in REQUIRED_TARGET_FIELDS:
            if name in {"target_id", "tile_id"}:
                continue
            if isinstance(target[name], (dict, list)):
                raise ValueError(f"targets[{idx}].{name} must be a scalar.")

    return result


def _json_checked(obj: Any, label: str) -> Any:
    try:
        json.dumps(obj, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not JSON round-trippable: {exc}") from exc
    return obj


def _require_dict(parent: Mapping[str, Any], key: str, label: str) -> dict:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{label}.{key} must be a dict.")
    return value


def _require_list_len(
    parent: Mapping[str, Any], key: str, expected_len: int | None, label: str
) -> list:
    value = parent.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{label}.{key} must be a list.")
    if expected_len is not None and len(value) != expected_len:
        raise ValueError(f"{label}.{key} must have length {expected_len}.")
    return value
