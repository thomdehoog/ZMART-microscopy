"""A copy drawn with the picture's own display settings.

The Neuroglancer picture draws each channel through a linear window and its
own colour, added together, no gamma. A copy that wears anything else -- the
scan-wide percentile stretch the small copies are made with -- shows the
operator a different sample from the one on the canvas. These pin the rule
on synthetic planes whose every pixel is known.
"""

from __future__ import annotations

import io

import numpy as np
import pytest

tifffile = pytest.importorskip("tifffile")
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from application.parts.storage.jpeg_tiles import picture_as_displayed  # noqa: E402


def _planes(folder, values: dict[int, int], size=64):
    """One uint16 plane per channel, every pixel the channel's value."""
    folder.mkdir(parents=True, exist_ok=True)
    planes = []
    for c, value in values.items():
        path = folder / f"plane_c{c}.ome.tif"
        tifffile.imwrite(path, np.full((size, size), value, dtype=np.uint16))
        planes.append((c, path))
    return planes


def _centre_pixel(jpeg: bytes):
    image = Image.open(io.BytesIO(jpeg)).convert("RGB")
    return image.getpixel((image.width // 2, image.height // 2))


def test_each_channel_is_windowed_linearly_and_tinted_with_its_colour(tmp_path):
    planes = _planes(tmp_path, {0: 1000, 1: 3000})
    display = [
        {"c": 0, "visible": True, "window": [0, 2000], "color": "#00ff00"},
        {"c": 1, "visible": True, "window": [2000, 4000], "color": "#ff00ff"},
    ]
    r, g, b = _centre_pixel(picture_as_displayed(planes, display))
    # channel 0 sits halfway up its window -> half green; channel 1 halfway
    # up its own -> half magenta; added: an even grey.
    assert abs(r - 128) <= 3 and abs(g - 128) <= 3 and abs(b - 128) <= 3


def test_a_hidden_channel_adds_nothing(tmp_path):
    planes = _planes(tmp_path, {0: 1000, 1: 3000})
    display = [
        {"c": 0, "visible": True, "window": [0, 2000], "color": "#00ff00"},
        {"c": 1, "visible": False, "window": [2000, 4000], "color": "#ff00ff"},
    ]
    r, g, b = _centre_pixel(picture_as_displayed(planes, display))
    assert r <= 3 and abs(g - 128) <= 3 and b <= 3


def test_the_window_is_a_clip_not_a_gamma(tmp_path):
    planes = _planes(tmp_path, {0: 1000})
    below = picture_as_displayed(planes, [{"c": 0, "visible": True, "window": [1500, 4000], "color": "#ffffff"}])
    above = picture_as_displayed(planes, [{"c": 0, "visible": True, "window": [0, 500], "color": "#ffffff"}])
    quarter = picture_as_displayed(planes, [{"c": 0, "visible": True, "window": [0, 4000], "color": "#ffffff"}])
    assert max(_centre_pixel(below)) <= 3
    assert min(_centre_pixel(above)) >= 252
    assert all(abs(v - 64) <= 3 for v in _centre_pixel(quarter))


def test_a_channel_the_display_does_not_name_is_left_out(tmp_path):
    planes = _planes(tmp_path, {0: 4000, 1: 4000})
    only_one = picture_as_displayed(planes, [{"c": 1, "visible": True, "window": [0, 4000], "color": "#0000ff"}])
    r, g, b = _centre_pixel(only_one)
    assert r <= 3 and g <= 3 and b >= 252


def test_the_copy_stays_within_its_pixel_budget(tmp_path):
    planes = _planes(tmp_path, {0: 2000}, size=256)
    small = picture_as_displayed(planes, [{"c": 0, "visible": True, "window": [0, 4000], "color": "#ffffff"}], budget_px=64 * 64)
    image = Image.open(io.BytesIO(small))
    assert image.width * image.height <= 64 * 64
