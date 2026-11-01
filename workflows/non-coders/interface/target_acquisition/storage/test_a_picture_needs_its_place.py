"""A picture whose place on the stage is unknown is refused, not put at the origin.

From the review of 10 October, finding 21: a plane without ``x_um`` or
``y_um`` was placed at the stage's zero (``or 0.0``), so a capture the
driver could not place appeared in the corner of the canvas as if it had
been taken there. The bridge's own picture copies already refused the same
plane; the position store now does too.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest

from . import zarr_positions


@pytest.mark.parametrize("missing", ["x_um", "y_um"])
def test_a_plane_without_a_stage_position_is_refused(missing):
    plane = {"x_um": 100.0, "y_um": 200.0}
    plane[missing] = None
    with pytest.raises(ValueError, match=f"does not say where it was taken .*{missing}"):
        zarr_positions.the_first_voxel_centre_of([plane], (10, 20), (1.0, 1.0), z_origin_um=0.0)


def test_a_plane_at_the_stage_zero_is_still_at_zero():
    first = zarr_positions.the_first_voxel_centre_of(
        [{"x_um": 0.0, "y_um": 0.0}], (10, 20), (1.0, 1.0), z_origin_um=5.0)
    # Ten rows and twenty columns of 1 um about the stage zero: the first
    # voxel's centre is 4.5 um up and 9.5 um left of it.
    assert first == (5.0, -4.5, -9.5)
