"""Unit tests for the galvo-pan LRP editing trio.

Covers exactly the surface ``commands.move_galvo_to_pixel`` consumes:
``galvo_pan_for_pixel`` (roi.py), ``lrp_get_pan`` and ``lrp_set_pan``
(scan.py), plus the ``roi_translation_to_pan`` conversion they share.
The wider experimental lrp_edits API is deliberately not tested here —
its fate is an open maintainer decision.

File edits run against a copy of the real workflow LRP bundle in
``tests/data/general_workflow``.
"""

from __future__ import annotations

import pytest
from navigator_expert.experimental.lrp_edits._primitives import _job_setting_attr_values
from navigator_expert.experimental.lrp_edits.roi import (
    galvo_pan_for_pixel,
    roi_translation_to_pan,
)
from navigator_expert.experimental.lrp_edits.scan import (
    lrp_get_pan,
    lrp_set_pan,
    lrp_verify_pan,
)

# The real bundle's pan values are written as 8.6736173798840355e-19
# (LAS X's float-zero); jobs "AF Job"/"Overview"/"HiRes" carry pan
# attributes, the other blocks do not.
_LASX_ZERO = 8.6736173798840355e-19


@pytest.fixture
def lrp_path(general_workflow_data):
    return next(general_workflow_data.glob("*.lrp"))


class TestGalvoPanForPixel:
    def test_centre_pixel_needs_no_pan(self):
        pan = galvo_pan_for_pixel(256, 256, pixel_size_um=0.5, image_size=512, pan_scale_um=10.0)
        assert pan == (0.0, 0.0)

    def test_known_offsets(self):
        # px=384 is 128 px right of centre: tx = 128 * 0.5 um = 64 um,
        # pan_x = -64/10 (LAS X negates X). py=128 is 128 px above centre:
        # ty = -64 um, pan_y = +ty/scale = -6.4.
        pan_x, pan_y = galvo_pan_for_pixel(
            384, 128, pixel_size_um=0.5, image_size=512, pan_scale_um=10.0
        )
        assert pan_x == pytest.approx(-6.4)
        assert pan_y == pytest.approx(-6.4)

    def test_sign_convention_matches_lasx_display_frame(self):
        # Right of centre -> negative pan X; below centre -> positive pan Y.
        pan_x, pan_y = galvo_pan_for_pixel(
            300, 300, pixel_size_um=1.0, image_size=512, pan_scale_um=10.0
        )
        assert pan_x < 0
        assert pan_y > 0

    def test_scales_inversely_with_pan_scale(self):
        # Same pixel, wider objective (larger um-per-pan-unit) -> smaller pan.
        small = galvo_pan_for_pixel(300, 300, pixel_size_um=1.0, image_size=512, pan_scale_um=20.0)
        large = galvo_pan_for_pixel(300, 300, pixel_size_um=1.0, image_size=512, pan_scale_um=10.0)
        assert small[0] == pytest.approx(large[0] / 2.0)
        assert small[1] == pytest.approx(large[1] / 2.0)


class TestRoiTranslationToPan:
    def test_x_is_negated_y_is_not(self):
        # ROI Translation is the offset from stage centre with X negated.
        pan_x, pan_y = roi_translation_to_pan(10e-6, 10e-6, pan_scale_um=10.0)
        assert pan_x == pytest.approx(-1.0)
        assert pan_y == pytest.approx(1.0)


class TestLrpGetPan:
    def test_reads_pan_from_real_bundle(self, lrp_path):
        for job in ("AF Job", "Overview", "HiRes"):
            pan_x, pan_y = lrp_get_pan(lrp_path, job)
            assert pan_x == pytest.approx(_LASX_ZERO)
            assert pan_y == pytest.approx(_LASX_ZERO)

    def test_job_without_pan_attributes_defaults_to_zero(self, lrp_path):
        # "collecting pattern" exists in the sequence but its block carries
        # no PanFirstDim/PanSecondDim: that matches LAS X's "no pan written
        # yet" state and must read back as (0, 0).
        assert lrp_get_pan(lrp_path, "collecting pattern") == (0.0, 0.0)

    def test_missing_job_defaults_to_zero(self, lrp_path):
        assert lrp_get_pan(lrp_path, "No Such Job") == (0.0, 0.0)


class TestLrpSetPan:
    def test_round_trip_on_real_bundle(self, lrp_path):
        # "AF Job" carries pan attributes on 2 of its settings: X and Y on
        # each -> 4 attribute edits.
        changed = lrp_set_pan(lrp_path, 1.25, -0.5, "AF Job")
        assert changed == 4

        assert lrp_get_pan(lrp_path, "AF Job") == (1.25, -0.5)
        assert lrp_verify_pan(lrp_path, 1.25, -0.5, "AF Job") is True
        assert lrp_verify_pan(lrp_path, 0.0, 0.0, "AF Job") is False

    def test_edit_is_scoped_to_the_target_job(self, lrp_path):
        lrp_set_pan(lrp_path, 1.25, -0.5, "AF Job")
        # Other jobs' pan and the job's own unrelated attributes survive.
        pan_x, pan_y = lrp_get_pan(lrp_path, "Overview")
        assert pan_x == pytest.approx(_LASX_ZERO)
        assert pan_y == pytest.approx(_LASX_ZERO)
        assert _job_setting_attr_values(lrp_path, "Zoom", "AF Job") == ["1", "1", "1"]

    def test_verify_tolerance_accepts_near_values(self, lrp_path):
        lrp_set_pan(lrp_path, 1.25, -0.5, "AF Job")
        assert lrp_verify_pan(lrp_path, 1.2501, -0.4999, "AF Job", tolerance=0.001) is True
        assert lrp_verify_pan(lrp_path, 1.26, -0.5, "AF Job", tolerance=0.001) is False

    def test_missing_job_changes_nothing(self, lrp_path):
        before = lrp_path.read_bytes()
        assert lrp_set_pan(lrp_path, 1.0, 2.0, "No Such Job") == 0
        assert lrp_path.read_bytes() == before
