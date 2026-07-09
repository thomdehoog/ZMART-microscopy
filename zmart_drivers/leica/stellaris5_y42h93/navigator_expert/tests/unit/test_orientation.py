"""How the camera's turn relative to the stage is applied at save time.

Checks the quarter-turn mechanics and config resolution, and the save-time
integration: a turned rig reorients each plane losslessly and keeps the saved
metadata consistent (the image width/height follow the rotated picture, and the
physical pixel sizes swap with them for a 90/270 turn). No rig value is
hard-coded here -- the turns are test inputs.
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


def test_rejects_in_between_angle():
    with pytest.raises(ValueError, match="quarter-turn"):
        Orientation(rotate_deg=45)


def test_identity_and_swaps_axes():
    assert Orientation().is_identity
    assert Orientation(rotate_deg=90).swaps_axes
    assert Orientation(rotate_deg=270).swaps_axes
    assert not Orientation(rotate_deg=180).swaps_axes


def test_load_orientation(tmp_path):
    p = tmp_path / "orientation.json"
    p.write_text('{"schema_version": 1, "rotate_deg": 180}')
    assert orient.load_orientation(p) == Orientation(rotate_deg=180)


def test_rig_orientation_defaults_to_identity_template(monkeypatch, tmp_path):
    # With no machine snapshot yet, the rig falls back to the shipped identity
    # template -- "no turn." The real value is measured by the set_orientation
    # notebook, never hard-coded. A hermetic ProgramData root (no snapshot)
    # exercises that fallback without touching the machine's real config.
    from navigator_expert.config.machine import MachineProfile

    monkeypatch.setattr(
        "navigator_expert.config.machine.MACHINE",
        MachineProfile(programdata_root=tmp_path / "programdata"),
    )
    assert orient.rig_orientation() == Orientation()


def test_rig_orientation_reads_the_measured_snapshot(monkeypatch, tmp_path):
    # Once the set_orientation notebook has published a snapshot, the driver
    # reads the measured turn from it -- not the identity template.
    from datetime import datetime, timezone

    from navigator_expert.config.machine import MachineProfile

    machine = MachineProfile(programdata_root=tmp_path / "programdata")
    machine.publish_snapshot(
        datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        orientation={"schema_version": 1, "rotate_deg": 270},
    )
    monkeypatch.setattr("navigator_expert.config.machine.MACHINE", machine)
    assert orient.rig_orientation() == Orientation(rotate_deg=270)


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


# --- image_to_stage matrix -> Orientation converter -----------------------


def test_converter_anchor_known_90_rig():
    # A measured matrix of [[0,-1],[1,0]] (a rig turned a quarter-turn) is
    # corrected by turning the saved image 90 degrees clockwise.
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


def test_reorient_matches_the_converters_rotation_matrices():
    # Pin reorient_array's clockwise convention to the matrices the converter
    # trusts: turning a marker pixel by rotate_deg must move it exactly the way
    # _STAGE_FROM_ROTATION says. If reorient_array's convention ever drifted, the
    # converter would silently mislabel a rig's turn -- this catches that.
    for deg, expected in orient._STAGE_FROM_ROTATION.items():

        def _where_it_lands(marker_row_col, deg=deg):
            img = np.zeros((3, 3), int)
            img[marker_row_col] = 1
            turned = orient.reorient_array(img, Orientation(rotate_deg=deg))
            r, c = np.argwhere(turned == 1)[0]
            return np.array([c - 1, r - 1])  # (column, row) offset from the centre

        # Where a step east (+1 column) and a step south (+1 row) end up.
        got = np.column_stack([_where_it_lands((1, 2)), _where_it_lands((2, 1))])
        assert np.array_equal(got, np.asarray(expected)), deg


def test_converter_rejects_mirror():
    with pytest.raises(ValueError, match="mirror"):
        orient.orientation_from_image_to_stage([[1, 0], [0, -1]])  # a mirror (det = -1)


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


def test_save_three_quarter_turn_rotates_and_swaps_dims(tmp_path):
    src = _write_source(tmp_path)
    original = tifffile.imread(src.path)
    dest = tmp_path / "out.ome.tiff"
    materialize.save_image_source_atomic(
        src,
        dest,
        metadata=_metadata(px_x=0.5, px_y=2.0),
        index=PlaneIndex(t=0, z=0, c=0),
        orientation=Orientation(rotate_deg=270),
    )
    arr, desc = _dest_pixels_and_desc(dest)
    assert arr.shape == (8, 4)  # the other axis-swapping turn
    assert np.array_equal(arr, np.rot90(original, k=-3))
    assert 'SizeX="4"' in desc and 'SizeY="8"' in desc
    assert 'PhysicalSizeX="2"' in desc and 'PhysicalSizeY="0.5"' in desc


def test_save_without_orientation_is_unrotated(tmp_path):
    dest = tmp_path / "out.ome.tiff"
    materialize.save_image_source_atomic(
        _write_source(tmp_path),
        dest,
        metadata=_metadata(),
        index=PlaneIndex(t=0, z=0, c=0),
    )
    assert tifffile.imread(dest).shape == (4, 8)
