"""Offline sign-convention guard for the driver's registration primitives.

The orientation measurement fits the image-to-stage matrix straight off
``register_voting``'s ``(dx_um, dy_um)``. That fit is a signed inverse, so a
flipped sign in any one method (e.g. dropping the negation in ``pcc``'s
``dy_px, dx_px = -shift[0], -shift[1]``) would silently rotate every measured
orientation while the orientation tests -- whose synthetic forward-model shares
the same convention -- stayed green.

These tests pin the sign NON-CIRCULARLY: a feature blob is shifted by a KNOWN
number of pixels (ground truth, no matrix maths), and the reported displacement
must carry that same sign. The documented convention is
``navigator_expert/algorithms/registration.py`` lines 19-29: a POSITIVE shift
means features in TGT lie at +x / +y (larger column / row) relative to REF.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("cv2")  # register_voting imports cv2/skimage at module load

from navigator_expert.algorithms import pcc, register_voting


def _blob_image(shape=(220, 220), seed=7) -> np.ndarray:
    """Non-periodic, microscopy-like features with stable registration landmarks."""
    rng = np.random.RandomState(seed)
    yy, xx = np.indices(shape, dtype=float)
    img = np.zeros(shape, dtype=float)
    margin = min(shape) * 0.18
    for _ in range(40):
        cx = rng.uniform(margin, shape[1] - margin)
        cy = rng.uniform(margin, shape[0] - margin)
        sx = rng.uniform(2.0, 7.0)
        sy = rng.uniform(2.0, 7.0)
        img += rng.uniform(0.3, 1.0) * np.exp(
            -0.5 * (((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2)
        )
    img += rng.normal(0.0, 0.008, shape)
    img -= img.min()
    return (img / img.max() * np.iinfo(np.uint16).max).astype(np.uint16)


def _shift_features(img: np.ndarray, dx_px: int, dy_px: int) -> np.ndarray:
    """Move features by (+dx columns, +dy rows) with NO edge wrap -- ground truth."""
    out = np.full_like(img, int(np.median(img)))
    src_x = slice(max(0, -dx_px), min(img.shape[1], img.shape[1] - dx_px))
    src_y = slice(max(0, -dy_px), min(img.shape[0], img.shape[0] - dy_px))
    dst_x = slice(max(0, dx_px), min(img.shape[1], img.shape[1] + dx_px))
    dst_y = slice(max(0, dy_px), min(img.shape[0], img.shape[0] + dy_px))
    out[dst_y, dst_x] = img[src_y, src_x]
    return out


# The pixel size is deliberately non-unity so a sign flip cannot hide behind a
# 1:1 px==um coincidence, and the assertion is in micrometres end to end.
PIXEL_UM = 0.5


@pytest.mark.parametrize(
    "dx_px,dy_px",
    [(8, 5), (-6, 3), (0, -9), (10, 0), (-7, -4)],
)
def test_register_voting_reports_ground_truth_shift_with_correct_sign(dx_px, dy_px):
    home = _blob_image()
    moved = _shift_features(home, dx_px, dy_px)

    vote = register_voting(home, moved, PIXEL_UM)

    assert vote["trusted"], vote
    # Positive dx_um == features moved toward +columns; positive dy_um == +rows.
    assert vote["dx_um"] == pytest.approx(dx_px * PIXEL_UM, abs=PIXEL_UM)
    assert vote["dy_um"] == pytest.approx(dy_px * PIXEL_UM, abs=PIXEL_UM)


def test_register_voting_reversed_pair_negates_the_shift():
    # Swapping REF and TGT must flip both signs -- the antisymmetry a dropped
    # negation would break.
    home = _blob_image()
    moved = _shift_features(home, 9, -6)

    forward = register_voting(home, moved, PIXEL_UM)
    backward = register_voting(moved, home, PIXEL_UM)

    assert forward["dx_um"] == pytest.approx(-backward["dx_um"], abs=PIXEL_UM)
    assert forward["dy_um"] == pytest.approx(-backward["dy_um"], abs=PIXEL_UM)


def test_pcc_primitive_sign_matches_the_documented_convention():
    # Pin the primitive directly: pcc negates skimage's shift so that a TGT whose
    # features sit at +x/+y returns positive (dx_um, dy_um).
    home = _blob_image()
    moved = _shift_features(home, 7, 4)

    dx_um, dy_um, quality = pcc(home, moved, PIXEL_UM)

    assert dx_um == pytest.approx(7 * PIXEL_UM, abs=PIXEL_UM)
    assert dy_um == pytest.approx(4 * PIXEL_UM, abs=PIXEL_UM)
    # Quality is incidental here (the no-wrap median border depresses the phase
    # residual); this test guards the SIGN, so only require a usable number.
    assert np.isfinite(quality)
