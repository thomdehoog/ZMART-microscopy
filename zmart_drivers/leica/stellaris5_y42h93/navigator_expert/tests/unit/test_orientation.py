"""Rig image->stage orientation, applied at save time (behind the scenes).

Unit-tests the D4 mechanics + config resolution, and the materialize
integration: a non-identity rig D4 reorients the plane losslessly and keeps the
OME self-consistent (SizeX/Y follow the rotated shape; PhysicalSizeX/Y swap for
a quarter-turn). No rig value is hard-coded here -- rotations are test inputs.
"""

from __future__ import annotations

import numpy as np
import pytest
import tifffile
from navigator_expert import orientation as orient
from navigator_expert.acquisition import materialize
from navigator_expert.acquisition.product import (
    AcquisitionMetadata,
    ChannelMetadata,
    PlaneIndex,
    PlaneSource,
)

Orientation = orient.Orientation


# --- schema + config resolution -------------------------------------------


def test_rejects_non_d4_angle():
    with pytest.raises(ValueError, match="90-degree"):
        Orientation(rotate_deg=45)


def test_identity_and_swaps_axes():
    assert Orientation().is_identity
    assert Orientation(rotate_deg=90).swaps_axes
    assert Orientation(rotate_deg=270).swaps_axes
    assert not Orientation(rotate_deg=180).swaps_axes
    assert not Orientation(mirror=True).swaps_axes


def test_load_orientation(tmp_path):
    p = tmp_path / "orientation.json"
    p.write_text('{"schema_version": 1, "rotate_deg": 180, "mirror": true}')
    assert orient.load_orientation(p) == Orientation(rotate_deg=180, mirror=True)


def test_rig_orientation_defaults_to_identity_template():
    # The shipped default is an identity template -- the rig value is measured
    # by the set_orientation notebook, never hard-coded.
    assert orient.rig_orientation() == Orientation()


# --- reorient_array (lossless D4) -----------------------------------------

_A = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16)  # (H=2, W=3)


def test_reorient_identity_unchanged():
    assert np.array_equal(orient.reorient_array(_A, Orientation()), _A)


def test_reorient_quarter_turn_clockwise():
    expected = np.array([[4, 1], [5, 2], [6, 3]], dtype=np.uint16)  # (3, 2)
    assert np.array_equal(orient.reorient_array(_A, Orientation(rotate_deg=90)), expected)


def test_reorient_quarter_turns_are_inverse():
    once = orient.reorient_array(_A, Orientation(rotate_deg=90))
    assert np.array_equal(orient.reorient_array(once, Orientation(rotate_deg=270)), _A)


def test_reorient_mirror_is_applied_first():
    expected = orient.reorient_array(np.fliplr(_A), Orientation(rotate_deg=90))
    got = orient.reorient_array(_A, Orientation(rotate_deg=90, mirror=True))
    assert np.array_equal(got, expected)


# --- image_to_stage matrix -> Orientation converter -----------------------


def test_converter_anchor_bundled_default_is_90():
    # The bundled calibration image_to_stage ([[0,-1],[1,0]], a 90-deg rig)
    # corrects with a 90-deg clockwise image rotation.
    assert orient.orientation_from_image_to_stage([[0, -1], [1, 0]]) == Orientation(rotate_deg=90)


@pytest.mark.parametrize(
    "matrix,expected",
    [
        ([[1, 0], [0, 1]], Orientation(rotate_deg=0)),
        ([[0, -1], [1, 0]], Orientation(rotate_deg=90)),
        ([[-1, 0], [0, -1]], Orientation(rotate_deg=180)),
        ([[0, 1], [-1, 0]], Orientation(rotate_deg=270)),
    ],
)
def test_converter_maps_each_rotation(matrix, expected):
    assert orient.orientation_from_image_to_stage(matrix) == expected


def test_converter_is_the_transform_reorient_applies():
    # Correctness by construction: reorient by O maps an image displacement
    # through exactly M, so a feature's reoriented pixel offset equals the
    # stage offset M @ image_offset -> objective_pair correction becomes identity.
    for matrix in ([[1, 0], [0, 1]], [[0, -1], [1, 0]], [[-1, 0], [0, -1]], [[0, 1], [-1, 0]]):
        o = orient.orientation_from_image_to_stage(matrix)
        assert np.array_equal(orient._displacement_transform(o), np.asarray(matrix, float))


def test_converter_rejects_reflection():
    with pytest.raises(ValueError, match="reflection"):
        orient.orientation_from_image_to_stage([[1, 0], [0, -1]])  # det = -1


# --- materialize integration ----------------------------------------------


def _metadata(px_x=0.5, px_y=2.0) -> AcquisitionMetadata:
    # Deliberately anisotropic so a physical-size swap is observable.
    return AcquisitionMetadata(
        size_x=8,
        size_y=4,
        size_t=1,
        size_z=1,
        size_c=1,
        pixel_type="uint16",
        physical_size_x_um=px_x,
        physical_size_y_um=px_y,
        channels=(ChannelMetadata(index=0, name="C0"),),
    )


def _write_source(tmp_path) -> PlaneSource:
    src = tmp_path / "src.tif"
    arr = np.arange(4 * 8, dtype=np.uint16).reshape(4, 8)  # H=4, W=8
    tifffile.imwrite(src, arr, photometric="minisblack")
    return PlaneSource(path=src)


def _dest_pixels_and_desc(path):
    arr = tifffile.imread(path)
    with tifffile.TiffFile(path) as tif:
        desc = tif.pages[0].description
    return arr, desc


def test_save_identity_orientation_does_not_rotate(tmp_path):
    dest = tmp_path / "out.ome.tiff"
    materialize.save_image_source_atomic(
        _write_source(tmp_path),
        dest,
        metadata=_metadata(),
        index=PlaneIndex(t=0, z=0, c=0),
        orientation=Orientation(),
    )
    arr, desc = _dest_pixels_and_desc(dest)
    assert arr.shape == (4, 8)
    assert 'SizeX="8"' in desc and 'SizeY="4"' in desc


def test_save_quarter_turn_rotates_pixels_and_swaps_dims(tmp_path):
    src = _write_source(tmp_path)
    original = tifffile.imread(src.path)
    dest = tmp_path / "out.ome.tiff"

    materialize.save_image_source_atomic(
        src,
        dest,
        metadata=_metadata(px_x=0.5, px_y=2.0),
        index=PlaneIndex(t=0, z=0, c=0),
        orientation=Orientation(rotate_deg=90),
    )

    arr, desc = _dest_pixels_and_desc(dest)
    # pixels rotated clockwise, grid transposed 4x8 -> 8x4
    assert arr.shape == (8, 4)
    assert np.array_equal(arr, np.rot90(original, k=-1))
    # OME follows: SizeX/Y from the rotated shape, PhysicalSizeX/Y swapped
    assert 'SizeX="4"' in desc and 'SizeY="8"' in desc
    # physical sizes swap with the axes (0.5/2.0 -> 2/0.5); "2.0" prints as "2"
    assert 'PhysicalSizeX="2"' in desc and 'PhysicalSizeY="0.5"' in desc


def test_save_half_turn_keeps_dims(tmp_path):
    src = _write_source(tmp_path)
    original = tifffile.imread(src.path)
    dest = tmp_path / "out.ome.tiff"
    materialize.save_image_source_atomic(
        src,
        dest,
        metadata=_metadata(),
        index=PlaneIndex(t=0, z=0, c=0),
        orientation=Orientation(rotate_deg=180),
    )
    arr, desc = _dest_pixels_and_desc(dest)
    assert arr.shape == (4, 8)
    assert np.array_equal(arr, np.rot90(original, k=2))
    assert 'SizeX="8"' in desc and 'SizeY="4"' in desc


def test_save_without_orientation_is_unrotated(tmp_path):
    dest = tmp_path / "out.ome.tiff"
    materialize.save_image_source_atomic(
        _write_source(tmp_path),
        dest,
        metadata=_metadata(),
        index=PlaneIndex(t=0, z=0, c=0),
    )
    assert tifffile.imread(dest).shape == (4, 8)
