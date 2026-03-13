"""
Unit tests for scanning_template_editors (no LAS X connection needed).
======================================================================
Run with: python -m pytest test_scanning_template_editors_unit.py -v
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lasx.scanning_template_editors_focus import (
    STACK_MODES,
    set_stack_calculation_mode,
    verify_stack_calculation_mode,
)


# ── Sample LRP ──────────────────────────────────────────────────────────

SAMPLE_LRP = """\
<?xml version="1.0" encoding="utf-8"?>
<LDM_Block_Sequence BlockName="MySequence">
  <LDM_Block_Sequence_Block_List>
    <LDM_Block_Sequence_Block BlockID="b1" BlockType="1">
      <LDM_Block_Sequential BlockName="AF Job">
        <LDM_Block_Sequential_Master>
          <ATLConfocalSettingDefinition LineAverage="2" StackCalculationMode="1" StackCalculationModeName="Constant step size" />
        </LDM_Block_Sequential_Master>
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


# ── STACK_MODES ─────────────────────────────────────────────────────────

class TestStackModes:
    def test_all_modes_present(self):
        assert 0 in STACK_MODES
        assert 1 in STACK_MODES
        assert 2 in STACK_MODES

    def test_mode_names(self):
        assert STACK_MODES[0] == "Constant steps"
        assert STACK_MODES[1] == "Constant step size"
        assert STACK_MODES[2] == "System optimized step size"


# ── set_stack_calculation_mode ──────────────────────────────────────────

class TestSetStackCalculationMode:
    def test_changes_mode(self, lrp_file):
        count = set_stack_calculation_mode(lrp_file, 0, "AF Job")
        assert count == 2

        root = ET.parse(lrp_file).getroot()
        el = root.find(".//LDM_Block_Sequential_Master/"
                       "ATLConfocalSettingDefinition")
        assert el.get("StackCalculationMode") == "0"
        assert el.get("StackCalculationModeName") == "Constant steps"

    def test_same_mode_no_change(self, lrp_file):
        count = set_stack_calculation_mode(lrp_file, 1, "AF Job")
        assert count == 0

    def test_invalid_mode(self, lrp_file):
        count = set_stack_calculation_mode(lrp_file, 99, "AF Job")
        assert count == 0

    def test_missing_job(self, lrp_file):
        count = set_stack_calculation_mode(lrp_file, 0, "NoSuchJob")
        assert count == 0

    def test_all_modes_roundtrip(self, lrp_file):
        for mode in (0, 1, 2):
            set_stack_calculation_mode(lrp_file, mode, "AF Job")
            assert verify_stack_calculation_mode(lrp_file, mode, "AF Job")


# ── verify_stack_calculation_mode ───────────────────────────────────────

class TestVerifyStackCalculationMode:
    def test_correct_mode(self, lrp_file):
        assert verify_stack_calculation_mode(lrp_file, 1, "AF Job") is True

    def test_wrong_mode(self, lrp_file):
        assert verify_stack_calculation_mode(lrp_file, 0, "AF Job") is False

    def test_missing_job(self, lrp_file):
        assert verify_stack_calculation_mode(lrp_file, 1, "NoSuchJob") is False
