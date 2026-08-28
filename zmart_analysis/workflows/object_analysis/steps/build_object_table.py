"""build_object_table -- publish the object_analysis public contract."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _contracts import to_builtin, validate_tile_detection  # noqa: E402
from _geometry import image_point_to_stage_xy  # noqa: E402
from _object_ids import object_name, tile_name  # noqa: E402


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
        "tile_zwide_um",
        "source_pixel_size_um",
        "image_to_stage",
    ]
    for name in required:
        if name not in inp:
            raise ValueError(f"input missing required geometry field {name!r}.")

    return {
        "tile_id": inp["tile_id"],
        "tile_stage_xy_um": inp["tile_stage_xy_um"],
        "tile_zwide_um": inp["tile_zwide_um"],
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
