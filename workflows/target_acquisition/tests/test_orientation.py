"""Post-export image orientation (pipeline.apply_orientation).

Pins the lossless D4 mechanics (each rotation/mirror), the OME dim-swap +
validity for the axis-swapping 90/270, load/validate, and the no-op identity.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import tifffile
from pipeline import Orientation, apply_orientation, load_orientation
from pipeline._orientation import reorient_array

from shared.output_layout.naming import Naming, build_image_name


def _ome_desc(*, size_x, size_y, phys_x=0.5, phys_y=0.5):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        f'<Image ID="Image:0"><Pixels ID="Pixels:0" DimensionOrder="XYCZT" '
        f'Type="uint16" SizeX="{size_x}" SizeY="{size_y}" SizeC="1" SizeZ="1" '
        f'SizeT="1" PhysicalSizeX="{phys_x}" PhysicalSizeY="{phys_y}"/></Image></OME>'
    )


def _saved_plane(tmp_path, arr):
    """Write a flat canonical plane; return (image_path, record)."""
    acq = tmp_path / "overview"
    acq.mkdir(parents=True, exist_ok=True)
    naming = Naming(acquisition_type="overview", hash6="abcdef", position_label="g00000-p00001")
    path = acq / build_image_name(naming)
    h, w = arr.shape
    tifffile.imwrite(
        path, arr, description=_ome_desc(size_x=w, size_y=h), ome=False, photometric="minisblack"
    )
    return path, {"images": [str(path)]}


# --- Orientation schema ---------------------------------------------------


def test_orientation_rejects_non_d4_angle():
    with pytest.raises(ValueError, match="90-degree"):
        Orientation(rotate_deg=45)


def test_orientation_identity_and_swaps():
    assert Orientation().is_identity
    assert not Orientation(rotate_deg=90).is_identity
    assert Orientation(rotate_deg=90).swaps_axes
    assert Orientation(rotate_deg=270).swaps_axes
    assert not Orientation(rotate_deg=180).swaps_axes
    assert not Orientation(mirror=True).swaps_axes


# --- reorient_array (lossless D4) -----------------------------------------

_A = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16)  # (H=2, W=3)


def test_reorient_identity_is_unchanged():
    assert np.array_equal(reorient_array(_A, Orientation()), _A)


def test_reorient_90_clockwise():
    # 90 deg clockwise: top row becomes right column.
    expected = np.array([[4, 1], [5, 2], [6, 3]], dtype=np.uint16)  # (3, 2)
    assert np.array_equal(reorient_array(_A, Orientation(rotate_deg=90)), expected)


def test_reorient_180():
    expected = np.array([[6, 5, 4], [3, 2, 1]], dtype=np.uint16)
    assert np.array_equal(reorient_array(_A, Orientation(rotate_deg=180)), expected)


def test_reorient_270_is_inverse_of_90():
    once = reorient_array(_A, Orientation(rotate_deg=90))
    back = reorient_array(once, Orientation(rotate_deg=270))
    assert np.array_equal(back, _A)


def test_reorient_mirror_then_rotate_order():
    # mirror (fliplr) first, then rotate.
    mirrored = np.fliplr(_A)
    expected = reorient_array(mirrored, Orientation(rotate_deg=90))
    assert np.array_equal(reorient_array(_A, Orientation(rotate_deg=90, mirror=True)), expected)


def test_reorient_is_lossless_roundtrip_over_all_elements():
    rng = np.arange(2 * 3, dtype=np.uint16).reshape(2, 3)
    for deg in (0, 90, 180, 270):
        for mirror in (False, True):
            o = Orientation(rotate_deg=deg, mirror=mirror)
            once = reorient_array(rng, o)
            # inverse D4 element returns the original (lossless, no resample)
            inv_deg = (-deg) % 360
            undo = reorient_array(
                np.fliplr(once) if mirror else once, Orientation(rotate_deg=inv_deg)
            )
            if mirror:
                # mirror is its own inverse but applied first; undo mirror last
                undo = reorient_array(once, Orientation(rotate_deg=inv_deg))
                undo = np.fliplr(undo)
            assert np.array_equal(undo, rng), (deg, mirror)


# --- apply_orientation over saved planes ----------------------------------


def test_apply_identity_is_noop(tmp_path):
    arr = np.arange(4 * 8, dtype=np.uint16).reshape(4, 8)
    path, record = _saved_plane(tmp_path, arr)
    before = path.read_bytes()
    assert apply_orientation([record], Orientation()) == 0
    assert path.read_bytes() == before


def test_apply_90_rotates_pixels_and_swaps_ome_dims(tmp_path):
    arr = np.arange(4 * 8, dtype=np.uint16).reshape(4, 8)  # H=4, W=8
    path, record = _saved_plane(tmp_path, arr)

    n = apply_orientation([record], Orientation(rotate_deg=90))

    assert n == 1
    out = tifffile.imread(path)
    assert out.shape == (8, 4)  # H<->W swapped
    assert np.array_equal(out, np.rot90(arr, k=-1))
    # OME Pixels SizeX/SizeY swapped to match
    with tifffile.TiffFile(path) as tif:
        desc = tif.pages[0].description
    assert 'SizeX="4"' in desc and 'SizeY="8"' in desc


def test_apply_90_output_still_validates_under_ome_types(tmp_path):
    ome_types = pytest.importorskip("ome_types")
    arr = np.arange(4 * 8, dtype=np.uint16).reshape(4, 8)
    path, record = _saved_plane(tmp_path, arr)
    apply_orientation([record], Orientation(rotate_deg=90))
    model = ome_types.from_tiff(str(path))  # parses/validates
    px = model.images[0].pixels
    assert (px.size_x, px.size_y) == (4, 8)


def test_apply_180_keeps_dims(tmp_path):
    arr = np.arange(4 * 8, dtype=np.uint16).reshape(4, 8)
    path, record = _saved_plane(tmp_path, arr)
    apply_orientation([record], Orientation(rotate_deg=180))
    out = tifffile.imread(path)
    assert out.shape == (4, 8)
    assert np.array_equal(out, np.rot90(arr, k=2))


# --- load_orientation + the Leica default ---------------------------------


def test_load_orientation(tmp_path):
    p = tmp_path / "orientation.json"
    p.write_text(json.dumps({"schema_version": 1, "rotate_deg": 270, "mirror": True}))
    o = load_orientation(p)
    assert o == Orientation(rotate_deg=270, mirror=True)


def test_leica_default_orientation_json_is_90():
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    default = (
        repo
        / "zmart_drivers/leica/stellaris5_y42h93/navigator_expert/orientation/defaults/orientation.json"
    )
    o = load_orientation(default)
    assert o == Orientation(rotate_deg=90, mirror=False)
