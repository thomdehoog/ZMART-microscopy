"""Adversarial and property-style tests for the channel-axis contract."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _detection_checkpoint import segmentation_params, segmentation_params_hash  # noqa: E402
from _segmentation import select_channels  # noqa: E402


pytestmark = pytest.mark.adversarial


def _load_run_pipeline_module():
    path = Path(__file__).resolve().parents[1] / "run_pipeline.py"
    spec = importlib.util.spec_from_file_location("object_analysis_run_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("n_channels", [1, 2, 3, 5, 8])
@pytest.mark.parametrize("axis", [0, -1, 2])
def test_explicit_axis_selection_matches_numpy_reference(n_channels, axis):
    rng = np.random.default_rng(20260711 + n_channels)
    channel_last = rng.integers(
        0, 65535, size=(11, 17, n_channels), dtype=np.uint16
    )
    image = np.moveaxis(channel_last, -1, 0) if axis == 0 else channel_last
    requested = list(range(min(n_channels, 3)))

    actual = select_channels(image, requested, channel_axis=axis)
    expected = channel_last[..., requested]
    if len(requested) == 1:
        expected = expected[..., 0]

    np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize(
    "axis", [1, -2, 3, "0", True, False, 0.0, -1.0, 2.0]
)
def test_invalid_axis_values_are_rejected_consistently(axis):
    image = np.zeros((3, 11, 17), dtype=np.uint8)
    with pytest.raises(ValueError, match="channel_axis must be"):
        select_channels(image, channel_axis=axis)
    with pytest.raises(ValueError, match="channel_axis must be"):
        segmentation_params({"channel_axis": axis}, {})


def test_equal_end_axes_require_explicit_orientation_for_every_channel_count():
    for end_size in (1, 2, 3, 5, 8):
        image = np.zeros((end_size, 13, end_size), dtype=np.uint8)
        with pytest.raises(ValueError, match="infer channel axis"):
            select_channels(image)
        assert select_channels(image, channel_axis=0).shape[:2] == (13, end_size)
        assert select_channels(image, channel_axis=-1).shape[:2] == (
            end_size,
            13,
        )


def test_checkpoint_identity_separates_orientation_but_normalizes_aliases():
    base = {
        "channels": [0, 1],
        "cellprob_threshold": 0.0,
        "flow_threshold": 0.4,
        "niter": None,
        "diameter": None,
        "segmentation_binning": 1,
    }
    first_hash = segmentation_params_hash(base | {"channel_axis": 0})
    last_hash = segmentation_params_hash(base | {"channel_axis": -1})
    alias_hash = segmentation_params_hash(base | {"channel_axis": 2})

    assert first_hash != last_hash
    assert last_hash == alias_hash


def test_input_axis_overrides_yaml_axis_before_hashing():
    params = segmentation_params(
        {"channel_axis": 0, "channels": [0]},
        {"channel_axis": -1, "channels": [1]},
    )
    assert params["channel_axis"] == 0
    assert params["channels"] == [0]


def test_cli_image_size_comes_from_the_image(tmp_path):
    """A (3, 10, 3) image is ambiguous by shape and unambiguous by metadata.

    The CLI used to demand --channel-axis for exactly this case. Reading
    through one contract moved the question to the image itself, so the
    answer no longer depends on what the caller was told to pass.
    """
    import tifffile

    run_pipeline = _load_run_pipeline_module()
    image_path = tmp_path / "declared.tif"
    tifffile.imwrite(
        image_path, np.zeros((3, 10, 3), dtype=np.uint8), metadata={"axes": "CYX"}
    )

    assert run_pipeline._image_size_px(image_path) == [3, 10]
    # The old flag is accepted and ignored rather than changing the answer.
    assert run_pipeline._image_size_px(image_path, 0) == [3, 10]


def test_cli_image_size_refuses_an_undeclared_ambiguous_tiff(tmp_path):
    """Nothing declares the axes, so nothing can honestly resolve them."""
    import tifffile

    run_pipeline = _load_run_pipeline_module()
    image_path = tmp_path / "ambiguous.tif"
    tifffile.imwrite(image_path, np.zeros((3, 10, 3), dtype=np.uint8))

    with pytest.raises(ValueError, match="3-sample .RGB. image"):
        run_pipeline._image_size_px(image_path)
