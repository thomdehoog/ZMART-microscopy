"""
Unit tests for scanning_template_editors_scan (no LAS X connection needed).
============================================================================
Run with: python -m pytest test_scanning_template_editors_scan_unit.py -v
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from navigator_expert.driver.experimental.lrp_edits.scan import (
    lrp_set_zoom, lrp_verify_zoom,
    lrp_set_scan_speed, lrp_verify_scan_speed,
    lrp_set_scan_direction, lrp_verify_scan_direction,
    lrp_set_scan_field_rotation, lrp_verify_scan_field_rotation,
    lrp_set_pan, lrp_verify_pan,
)


# ── Sample LRP ──────────────────────────────────────────────────────────

SAMPLE_LRP = """\
<?xml version="1.0" encoding="utf-8"?>
<LDM_Block_Sequence BlockName="MySequence">
  <LDM_Block_Sequence_Block_List>
    <LDM_Block_Sequence_Block BlockID="b1" BlockType="1">
      <LDM_Block_Sequential BlockName="HiRes">
        <LDM_Block_Sequential_Master>
          <ATLConfocalSettingDefinition Zoom="2.0" ScanSpeed="200" ScanDirectionX="0" ScanDirectionXName="UnknownDirection" RotatorAngle="0" PanFirstDim="0" PanSecondDim="0" />
        </LDM_Block_Sequential_Master>
        <LDM_Block_Sequential_List>
          <ATLConfocalSettingDefinition Zoom="2.0" ScanSpeed="200" ScanDirectionX="0" ScanDirectionXName="UnknownDirection" RotatorAngle="0" PanFirstDim="0" PanSecondDim="0" />
        </LDM_Block_Sequential_List>
      </LDM_Block_Sequential>
    </LDM_Block_Sequence_Block>
  </LDM_Block_Sequence_Block_List>
</LDM_Block_Sequence>
"""


@pytest.fixture
def lrp_file(tmp_path):
    """Create a sample LRP file and return its path."""
    lrp = tmp_path / "test.lrp"
    lrp.write_text(SAMPLE_LRP, encoding="utf-8")
    return lrp


# ── lrp_set_pan / lrp_verify_pan ──────────────────────────────────────────────

class TestSetPan:
    def test_changes_both_dims(self, lrp_file):
        count = lrp_set_pan(lrp_file, 0.25, -0.1, "HiRes")
        assert count == 4  # 2 settings x 2 attributes

        root = ET.parse(lrp_file).getroot()
        for el in root.findall(".//ATLConfocalSettingDefinition"):
            assert el.get("PanFirstDim") == "0.25"
            assert el.get("PanSecondDim") == "-0.1"

    def test_same_values_no_change(self, lrp_file):
        count = lrp_set_pan(lrp_file, 0, 0, "HiRes")
        assert count == 0

    def test_missing_job(self, lrp_file):
        count = lrp_set_pan(lrp_file, 0.5, 0.5, "NoSuchJob")
        assert count == 0

    def test_roundtrip(self, lrp_file):
        for x, y in [(0.1, 0.2), (-0.5, 0.75), (0.0, 0.0)]:
            lrp_set_pan(lrp_file, x, y, "HiRes")
            assert lrp_verify_pan(lrp_file, x, y, "HiRes")


class TestVerifyPan:
    def test_correct_values(self, lrp_file):
        assert lrp_verify_pan(lrp_file, 0, 0, "HiRes") is True

    def test_wrong_x(self, lrp_file):
        assert lrp_verify_pan(lrp_file, 1.0, 0, "HiRes") is False

    def test_wrong_y(self, lrp_file):
        assert lrp_verify_pan(lrp_file, 0, 1.0, "HiRes") is False

    def test_missing_job(self, lrp_file):
        assert lrp_verify_pan(lrp_file, 0, 0, "NoSuchJob") is False

    def test_tolerance(self, lrp_file):
        lrp_set_pan(lrp_file, 0.1005, 0.2005, "HiRes")
        # Within default tolerance of 0.001
        assert lrp_verify_pan(lrp_file, 0.1005, 0.2005, "HiRes") is True
        assert lrp_verify_pan(lrp_file, 0.1006, 0.2006, "HiRes",
                          tolerance=0.001) is True
        # Outside tolerance
        assert lrp_verify_pan(lrp_file, 0.11, 0.2005, "HiRes",
                          tolerance=0.001) is False


# ── lrp_set_zoom / lrp_verify_zoom ────────────────────────────────────────

class TestSetZoom:
    def test_changes_zoom(self, lrp_file):
        count = lrp_set_zoom(lrp_file, 4.0, "HiRes")
        assert count == 2

    def test_same_zoom_no_change(self, lrp_file):
        count = lrp_set_zoom(lrp_file, 2.0, "HiRes")
        assert count == 0

    def test_roundtrip(self, lrp_file):
        lrp_set_zoom(lrp_file, 3.5, "HiRes")
        assert lrp_verify_zoom(lrp_file, 3.5, "HiRes")


# ── lrp_set_scan_speed / lrp_verify_scan_speed ────────────────────────────

class TestSetScanSpeed:
    def test_changes_speed(self, lrp_file):
        count = lrp_set_scan_speed(lrp_file, 400, "HiRes")
        assert count == 2

    def test_same_speed_no_change(self, lrp_file):
        count = lrp_set_scan_speed(lrp_file, 200, "HiRes")
        assert count == 0

    def test_roundtrip(self, lrp_file):
        lrp_set_scan_speed(lrp_file, 100, "HiRes")
        assert lrp_verify_scan_speed(lrp_file, 100, "HiRes")


# ── lrp_set_scan_direction / lrp_verify_scan_direction ────────────────────────

class TestSetScanDirection:
    def test_to_unidirectional(self, lrp_file):
        count = lrp_set_scan_direction(lrp_file, False, "HiRes")
        assert count == 4  # 2 settings x 2 attributes

    def test_same_direction_no_change(self, lrp_file):
        count = lrp_set_scan_direction(lrp_file, True, "HiRes")
        assert count == 0

    def test_roundtrip(self, lrp_file):
        for bidir in (True, False, True):
            lrp_set_scan_direction(lrp_file, bidir, "HiRes")
            assert lrp_verify_scan_direction(lrp_file, bidir, "HiRes")


# ── lrp_set_scan_field_rotation / lrp_verify_scan_field_rotation ──────────

class TestSetScanFieldRotation:
    def test_changes_rotation(self, lrp_file):
        count = lrp_set_scan_field_rotation(lrp_file, 45.0, "HiRes")
        assert count == 2

    def test_same_rotation_no_change(self, lrp_file):
        count = lrp_set_scan_field_rotation(lrp_file, 0, "HiRes")
        assert count == 0

    def test_roundtrip(self, lrp_file):
        lrp_set_scan_field_rotation(lrp_file, 90.0, "HiRes")
        assert lrp_verify_scan_field_rotation(lrp_file, 90.0, "HiRes")
