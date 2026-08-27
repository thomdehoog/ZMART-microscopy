"""Shared image-coordinate to stage-coordinate geometry helpers."""

from __future__ import annotations


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
