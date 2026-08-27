"""Shared JSON-native contracts for workflow handoff data.

The functions here validate only the stable public handoff shape between
workflows. Feature extraction can add many row-aligned pass-through
columns; the contract pins the minimal columns target discovery needs.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any


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
    "tile_zwide_um",
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
    if hasattr(obj, "item"):
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


def validate_overview(overview: Mapping[str, Any]) -> dict:
    """Validate and return a JSON-native overview of tile detections."""
    overview = _json_checked(to_builtin(overview), "overview")
    if not isinstance(overview, dict):
        raise ValueError("overview must be a dict.")
    tiles = overview.get("tiles")
    if not isinstance(tiles, list):
        raise ValueError("overview.tiles must be a list.")
    return {"tiles": [validate_tile_detection(tile) for tile in tiles]}


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


def save_overview(path: str | Path, overview: Mapping[str, Any]) -> Path:
    """Validate and save an overview JSON file."""
    path = Path(path)
    overview = validate_overview(overview)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(overview, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return path


def load_overview(path: str | Path) -> dict:
    """Load and validate an overview JSON file."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return validate_overview(json.load(handle))


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
