"""Multichannel classical feature extraction tests."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "steps"))
import extract_classical_features as features  # noqa: E402


def _pd(masks, image):
    return {
        "metadata": {"verbose": 0},
        "segment": {"masks": masks},
        "preprocess": {"image": image},
    }


def _two_object_masks():
    masks = np.zeros((8, 10), dtype=np.int32)
    masks[1:4, 1:4] = 1
    masks[4:7, 5:9] = 3
    return masks


def test_three_channel_intensity_columns_are_row_aligned():
    masks = _two_object_masks()
    image = np.zeros(masks.shape + (3,), dtype=np.float32)
    for channel, scale in enumerate((10.0, 20.0, 30.0)):
        image[masks == 1, channel] = scale + channel
        image[masks == 3, channel] = scale * 3 + channel

    pd = features.run(_pd(masks, image), {})
    props = pd["extract_features"]["properties"]

    assert list(props["label"]) == [1, 3]
    assert props["intensity_mean"].tolist() == pytest.approx([10.0, 30.0])
    assert props["intensity_mean_c0"].tolist() == pytest.approx([10.0, 30.0])
    assert props["intensity_mean_c1"].tolist() == pytest.approx([21.0, 61.0])
    assert props["intensity_mean_c2"].tolist() == pytest.approx([32.0, 92.0])
    assert props["intensity_median_c2"].tolist() == pytest.approx([32.0, 92.0])
    assert props["intensity_min_c1"].tolist() == pytest.approx([21.0, 61.0])
    assert props["intensity_max_c2"].tolist() == pytest.approx([32.0, 92.0])
    assert "intensity_mean-0" not in props


def test_two_channel_intensity_processes_available_channels_only():
    masks = _two_object_masks()
    image = np.zeros(masks.shape + (2,), dtype=np.float32)
    image[masks == 1, 0] = 5.0
    image[masks == 1, 1] = 50.0
    image[masks == 3, 0] = 7.0
    image[masks == 3, 1] = 70.0

    pd = features.run(_pd(masks, image), {})
    props = pd["extract_features"]["properties"]

    assert props["intensity_mean"].tolist() == pytest.approx([5.0, 7.0])
    assert props["intensity_mean_c0"].tolist() == pytest.approx([5.0, 7.0])
    assert props["intensity_mean_c1"].tolist() == pytest.approx([50.0, 70.0])
    assert "intensity_mean_c2" not in props


def test_multichannel_intensity_extras_are_channel_specific():
    masks = np.zeros((12, 12), dtype=np.int32)
    masks[4:8, 4:8] = 1
    image = np.zeros(masks.shape + (3,), dtype=np.float32)
    for channel, bg in enumerate((1.0, 2.0, 3.0)):
        image[..., channel] = bg
        image[masks == 1, channel] = bg * 10.0

    pd = features.run(_pd(masks, image), {}, extras=["intensity"], bg_radius=1)
    props = pd["extract_features"]["properties"]

    assert props["bg_global_mean"].tolist() == pytest.approx([1.0])
    assert props["bg_global_mean_c0"].tolist() == pytest.approx([1.0])
    assert props["bg_global_mean_c1"].tolist() == pytest.approx([2.0])
    assert props["bg_global_mean_c2"].tolist() == pytest.approx([3.0])
    assert props["bg_local_mean_c2"].tolist() == pytest.approx([3.0])
    assert props["mean_minus_local_bg_c1"].tolist() == pytest.approx([18.0])
    assert props["total_minus_local_bg_c2"].tolist() == pytest.approx([27.0 * 16])


def test_multichannel_texture_columns_are_channel_specific():
    masks = np.zeros((12, 12), dtype=np.int32)
    masks[2:10, 2:10] = 1
    image = np.zeros(masks.shape + (3,), dtype=np.float32)
    yy, xx = np.indices(masks.shape)
    image[..., 0] = 7.0
    image[..., 1] = xx
    image[..., 2] = yy + xx

    pd = features.run(_pd(masks, image), {}, extras=["texture"])
    props = pd["extract_features"]["properties"]

    for key in (
        "prewitt_magnitude_mean",
        "intensity_uniformity",
        "lbp_mean",
        "fft_mean",
        "glrlm_rlnu",
    ):
        assert key in props
        for channel in range(3):
            assert f"{key}_c{channel}" in props

    assert props["prewitt_magnitude_mean"][0] == pytest.approx(
        props["prewitt_magnitude_mean_c0"][0]
    )
    assert props["prewitt_magnitude_mean_c1"][0] > props["prewitt_magnitude_mean_c0"][0]


@pytest.mark.pooch
def test_immunohistochemistry_multichannel_features_smoke():
    from skimage.data import immunohistochemistry

    try:
        image = immunohistochemistry()
    except Exception as exc:
        pytest.skip(f"skimage immunohistochemistry fixture unavailable: {exc}")

    masks = np.zeros(image.shape[:2], dtype=np.int32)
    masks[120:180, 140:210] = 1
    masks[260:340, 300:390] = 2

    pd = features.run(_pd(masks, image), {}, extras=["gradients"])
    props = pd["extract_features"]["properties"]

    assert pd["extract_features"]["n_cells"] == 2
    for channel in range(3):
        assert f"intensity_mean_c{channel}" in props
        assert f"prewitt_magnitude_mean_c{channel}" in props
