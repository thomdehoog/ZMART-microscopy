"""build_object_table -- the object table every reader of this workflow relies on.

The last per-tile step. It takes the features the previous step measured,
names the columns the way the table promises them (``centroid-0`` becomes
``centroid_row_px``, and so on), adds where each object sits on the stage
and a stable name for it, and checks that every column has one value per
object and the tile says where it was taken. Then it drops the image, the
masks and the raw features from the result, since the table is what travels
on; ``keep_intermediate: true`` keeps them.

Publishes under ``pipeline_data["object_analysis"]``::

    objects     properties (one list per column, one entry per object) and
                n_objects
    geometry    the tile's id, stage position, pixel size, size in pixels,
                and the matrix from image axes to stage axes
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from segment_cellpose import to_builtin  # noqa: E402

METADATA = {
    "description": "Build the public object_analysis table",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--object_analysis--classical",
}

#: The columns every object table has, whatever features were measured.
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

#: What a tile says about where it was taken, so a pixel can become a stage position.
REQUIRED_GEOMETRY_FIELDS = (
    "tile_id",
    "tile_stage_xy_um",
    "source_pixel_size_um",
    "source_image_size_px",
    "image_to_stage",
)

#: The feature columns renamed for the table, from what scikit-image calls
#: them to what the table promises. Every other column keeps its name.
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

    given = pipeline_data["input"]

    props = _map_feature_columns(pipeline_data["measure_objects"]["properties"])

    n_objects = len(props.get("label", []))

    geometry = _geometry_from_input(given, pipeline_data["read_images"])

    _add_stage_columns(props, geometry)

    _add_identity_columns(props, geometry)

    table = _validated(
        {"objects": {"properties": props, "n_objects": n_objects}, "geometry": geometry}
    )

    pipeline_data["object_analysis"] = table

    if not given.get("keep_intermediate", params.get("keep_intermediate", False)):
        _strip_heavy_intermediates(pipeline_data)

    return pipeline_data


def _map_feature_columns(props: dict) -> dict:
    """The measured columns under the names the table promises; the others keep theirs."""

    table = {}

    for source, public in FEATURE_COLUMN_MAP.items():
        if source not in props:
            raise ValueError(
                f"measure_objects output missing required column {source!r} for public column {public!r}."
            )

        table[public] = to_builtin(props[source])

    for name, values in props.items():
        if name not in FEATURE_COLUMN_MAP and name not in table:
            table[name] = to_builtin(values)

    return table


def _geometry_from_input(given: dict, read: dict) -> dict:
    """Where the tile was taken: what turns an object's pixel position into a stage position.

    What the caller gives wins. Anything left out comes from the image: an
    OME-Zarr image records its pixel size and where its first pixel lies
    (OME-NGFF), and the driver has already lined it up with the stage, so
    the image alone is enough. The tile is then named after its file.
    """

    image_size_px = given.get("source_image_size_px", read["image_size_px"])

    pixel_size_um = given.get("source_pixel_size_um", read.get("pixel_size_um"))

    if pixel_size_um is None:
        raise ValueError(
            "input missing required geometry field 'source_pixel_size_um', and the image "
            "does not record its pixel size."
        )

    stage_xy_um = given.get("tile_stage_xy_um")

    if stage_xy_um is None:
        stage_xy_um = _image_centre(read.get("first_pixel_xy_um"), image_size_px, pixel_size_um)

    tile_id = given.get("tile_id")

    if tile_id is None:
        tile_id = [_file_stem(given["image_path"])]

    return {
        "tile_id": tile_id,
        "tile_stage_xy_um": stage_xy_um,
        # The capture height is a record only; a source that does not know it leaves it None
        "tile_z_um": given.get("tile_z_um"),
        "source_pixel_size_um": pixel_size_um,
        "source_image_size_px": image_size_px,
        "image_to_stage": given.get("image_to_stage", [[1.0, 0.0], [0.0, 1.0]]),
    }


def _image_centre(first_pixel_xy_um, image_size_px, pixel_size_um) -> list[float]:
    """The stage position of the image's centre, from where its first pixel's centre lies."""

    if first_pixel_xy_um is None:
        raise ValueError(
            "input missing required geometry field 'tile_stage_xy_um': only an OME-Zarr "
            "image records where it lies on the stage."
        )

    return [
        float(first_pixel_xy_um[axis])
        + (float(image_size_px[axis]) - 1.0) / 2.0 * float(pixel_size_um[axis])
        for axis in (0, 1)
    ]


def _file_stem(image_path) -> str:
    """The image's file name without its extensions: ``overview0.ome.zarr`` becomes ``overview0``."""

    return Path(str(image_path).rstrip("/\\")).name.split(".")[0]


def _add_stage_columns(props: dict, geometry: dict) -> None:
    """Every object's position on the stage, in micrometres, as ``stage_x_um`` and ``stage_y_um``."""

    positions = [
        _stage_position(row, col, geometry)
        for row, col in zip(props["centroid_row_px"], props["centroid_col_px"], strict=True)
    ]

    props["stage_x_um"] = [float(x_um) for x_um, _ in positions]

    props["stage_y_um"] = [float(y_um) for _, y_um in positions]


def _stage_position(row_px, col_px, geometry: dict) -> tuple[float, float]:
    """Where one point of the image is on the stage, in micrometres.

    A point at pixel index ``i`` is the centre of pixel ``i``, which lies
    ``i + 0.5 - n/2`` pixels from the image centre -- the tile's own position
    is that centre (OME-NGFF counts a pixel from its centre too). The offset
    is turned by the 2x2 ``image_to_stage`` matrix, because image rows and
    columns need not run the way the stage's x and y do, and added to the
    tile's own position.
    """

    nx, ny = geometry["source_image_size_px"]

    pixel_width_um, pixel_height_um = geometry["source_pixel_size_um"]

    tile_x_um, tile_y_um = geometry["tile_stage_xy_um"]

    (m00, m01), (m10, m11) = geometry["image_to_stage"]

    offset_x_um = (float(col_px) + 0.5 - float(nx) / 2.0) * float(pixel_width_um)

    offset_y_um = (float(row_px) + 0.5 - float(ny) / 2.0) * float(pixel_height_um)

    stage_x_um = float(tile_x_um) + float(m00) * offset_x_um + float(m01) * offset_y_um

    stage_y_um = float(tile_y_um) + float(m10) * offset_x_um + float(m11) * offset_y_um

    return stage_x_um, stage_y_um


def _add_identity_columns(props: dict, geometry: dict) -> None:
    """A stable name for the tile and for every object: ``R0_r003_c007_obj00012``."""

    tile = _tile_name(geometry["tile_id"])

    props["tile_name"] = [tile for _ in props["label"]]

    props["object_id"] = [f"{tile}_obj{int(label):05d}" for label in props["label"]]


def _tile_name(tile_id) -> str:
    """A file-name-friendly name for a tile: region, row and column, ``R0_r003_c007``."""

    parts = list(tile_id)

    if len(parts) < 3:
        return "_".join(_slug(part) for part in parts)

    region, row, col = _slug(parts[0]), _axis("r", parts[1]), _axis("c", parts[2])

    return "_".join([region, row, col] + [_slug(part) for part in parts[3:]])


def _axis(prefix: str, value) -> str:
    """A row or column as three digits, ``r003``, or as text when it is not a number."""

    try:
        return f"{prefix}{int(value):03d}"
    except (TypeError, ValueError):
        return f"{prefix}{_slug(value)}"


def _slug(value) -> str:
    """Text safe in a file name: anything else becomes a dash."""

    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-")

    return text or "item"


def _validated(tile: dict) -> dict:
    """The tile as plain values, checked: every column one value per object, the geometry complete.

    Raises ``ValueError`` naming what is missing or the wrong shape.
    """

    tile = to_builtin(tile)

    try:
        json.dumps(tile, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"tile detection is not JSON round-trippable: {exc}") from exc

    props, n_objects = tile["objects"]["properties"], tile["objects"]["n_objects"]

    for name in REQUIRED_OBJECT_COLUMNS:
        if name not in props:
            raise ValueError(f"objects.properties missing required column {name!r}.")

    for name, values in props.items():
        if not isinstance(values, list):
            raise ValueError(f"objects.properties[{name!r}] must be a list.")

        if len(values) != n_objects:
            raise ValueError(
                f"objects.properties[{name!r}] has length {len(values)}; expected n_objects={n_objects}."
            )

    geometry = tile["geometry"]

    for name in REQUIRED_GEOMETRY_FIELDS:
        if name not in geometry:
            raise ValueError(f"geometry missing required field {name!r}.")

    if not isinstance(geometry["tile_id"], list):
        raise ValueError("geometry.tile_id must be a list.")

    for name in ("tile_stage_xy_um", "source_pixel_size_um", "source_image_size_px"):
        if not isinstance(geometry[name], list) or len(geometry[name]) != 2:
            raise ValueError(f"geometry.{name} must have length 2.")

    matrix = geometry["image_to_stage"]

    if (
        not isinstance(matrix, list)
        or len(matrix) != 2
        or any(not isinstance(row, list) or len(row) != 2 for row in matrix)
    ):
        raise ValueError("geometry.image_to_stage must be a 2x2 list.")

    return tile


def _strip_heavy_intermediates(pipeline_data: dict) -> None:
    """Drop the image, the masks and the raw features: the table carries on alone.

    The segmentation's record stays, without its masks: the device it ran on
    is read from there.
    """

    pipeline_data.pop("measure_objects", None)

    pipeline_data.pop("read_images", None)

    for name in ("segment_cellpose", "segment_watershed"):
        if name in pipeline_data:
            pipeline_data[name].pop("masks", None)
