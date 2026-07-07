"""overview_pixel_to_frame: pixel -> frame um, no orientation (RIGHTTOP dropped)."""

from __future__ import annotations

import pytest
from pipeline._geom import overview_pixel_to_frame


def test_center_pixel_maps_to_image_center():
    x, y = overview_pixel_to_frame(
        centroid_col_row_px=(100, 50),
        image_shape_px=(100, 200),  # (H, W)
        pixel_size_um=0.5,
        image_center_frame_um=(1000.0, 2000.0),
    )
    assert (x, y) == (1000.0, 2000.0)


def test_positive_offset_scales_by_pixel_size():
    x, y = overview_pixel_to_frame(
        centroid_col_row_px=(110, 70),  # +10 col, +20 row from centre (100, 50)
        image_shape_px=(100, 200),
        pixel_size_um=0.5,
        image_center_frame_um=(1000.0, 2000.0),
    )
    assert x == pytest.approx(1005.0)
    assert y == pytest.approx(2010.0)


def test_negative_offset():
    x, y = overview_pixel_to_frame(
        centroid_col_row_px=(90, 30),  # -10 col, -20 row from centre
        image_shape_px=(100, 200),
        pixel_size_um=2.0,
        image_center_frame_um=(0.0, 0.0),
    )
    assert x == pytest.approx(-20.0)
    assert y == pytest.approx(-40.0)
