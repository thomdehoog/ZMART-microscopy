"""
Unit tests for template_operations (no LAS X connection needed).
================================================================
Run with: python -m pytest test_template_ops_unit.py -v
"""

import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lasx.template_operations import (
    _strip_xml, _strip_rgn, _count_objects,
    _is_file_locked, _wait_file_stable,
    get_template_state,
    TEMPLATE_XML, STRIPPED_XML,
)

# ── Sample fixtures ─────────────────────────────────────────────────────

SAMPLE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Experiment>
  <Header Name="Test" />
  <ScanFields>
    <ScanFieldData IsEnabled="true" UniqueID="1" ScanOrder="1" ScanRotationAngle="0">
      <LogicalData SectionX="0" SectionY="0" FieldX="0" FieldY="0" />
      <PhysicalData XPosition="1000" YPosition="2000" ZPosition="100" />
    </ScanFieldData>
    <ScanFieldData IsEnabled="true" UniqueID="2" ScanOrder="2" ScanRotationAngle="0">
      <LogicalData SectionX="0" SectionY="0" FieldX="1" FieldY="0" />
      <PhysicalData XPosition="1500" YPosition="2000" ZPosition="100" />
    </ScanFieldData>
  </ScanFields>
  <Footer />
</Experiment>
"""

SAMPLE_RGN = """\
<?xml version="1.0" encoding="utf-8"?>
<StageOverviewRegions>
  <Regions>
    <ShapeList>
      <Items>
        <Item0><Type>ScanFieldArray</Type><Name>{"AM":1}</Name>
          <Verticies><Items><Item0><X>0.001</X><Y>0.002</Y></Item0></Items></Verticies>
        </Item0>
        <Item1><Type>ScanFieldArray</Type><Name>{"AM":1}</Name>
          <Verticies><Items><Item0><X>0.0015</X><Y>0.002</Y></Item0></Items></Verticies>
        </Item1>
      </Items>
      <FillMaskMode>Custom</FillMaskMode>
      <VertexUnitMode>Meters</VertexUnitMode>
    </ShapeList>
  </Regions>
  <FocusMap ZMode="2">
    <FocusPoint Identifier="fp1" X="0.001" Y="0.002" Z="0.0001" Enabled="true" />
  </FocusMap>
</StageOverviewRegions>
"""


@pytest.fixture
def template_files(tmp_path):
    """Create sample XML and RGN files, return (xml_path, rgn_path)."""
    xml_path = tmp_path / "test.xml"
    rgn_path = tmp_path / "test.rgn"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    rgn_path.write_text(SAMPLE_RGN, encoding="utf-8")
    return xml_path, rgn_path


# ── _strip_xml ──────────────────────────────────────────────────────────

class TestStripXml:
    def test_removes_scan_fields(self, template_files):
        xml_path, _ = template_files
        dst = xml_path.parent / "stripped.xml"
        _strip_xml(xml_path, dst)

        text = dst.read_text(encoding="utf-8")
        assert "<ScanFieldData" not in text
        assert "<ScanFields />" in text

    def test_preserves_surrounding_content(self, template_files):
        xml_path, _ = template_files
        dst = xml_path.parent / "stripped.xml"
        _strip_xml(xml_path, dst)

        text = dst.read_text(encoding="utf-8")
        assert "<Header" in text
        assert "<Footer" in text

    def test_smaller_than_original(self, template_files):
        xml_path, _ = template_files
        dst = xml_path.parent / "stripped.xml"
        _strip_xml(xml_path, dst)

        assert dst.stat().st_size < xml_path.stat().st_size

    def test_no_scan_fields_unchanged(self, tmp_path):
        """XML without ScanFields is copied as-is."""
        src = tmp_path / "no_fields.xml"
        dst = tmp_path / "stripped.xml"
        content = "<Experiment><Header /></Experiment>"
        src.write_text(content, encoding="utf-8")
        _strip_xml(src, dst)
        assert dst.read_text(encoding="utf-8") == content


# ── _strip_rgn ──────────────────────────────────────────────────────────

class TestStripRgn:
    def test_creates_minimal_rgn(self, template_files):
        _, rgn_path = template_files
        dst = rgn_path.parent / "stripped.rgn"
        _strip_rgn(rgn_path, dst)

        root = ET.parse(dst).getroot()
        items = root.findall(".//ShapeList/Items/*")
        assert len(items) == 0

    def test_preserves_fill_mask(self, template_files):
        _, rgn_path = template_files
        dst = rgn_path.parent / "stripped.rgn"
        _strip_rgn(rgn_path, dst)

        text = dst.read_text(encoding="utf-8")
        assert "Custom" in text

    def test_preserves_vertex_unit(self, template_files):
        _, rgn_path = template_files
        dst = rgn_path.parent / "stripped.rgn"
        _strip_rgn(rgn_path, dst)

        text = dst.read_text(encoding="utf-8")
        assert "Meters" in text

    def test_preserves_z_mode(self, template_files):
        _, rgn_path = template_files
        dst = rgn_path.parent / "stripped.rgn"
        _strip_rgn(rgn_path, dst)

        text = dst.read_text(encoding="utf-8")
        assert 'ZMode="2"' in text


# ── _count_objects ──────────────────────────────────────────────────────

class TestCountObjects:
    def test_counts_original(self, template_files):
        xml_path, rgn_path = template_files
        fields, items, focus = _count_objects(xml_path, rgn_path)
        assert fields == 2
        assert items == 2
        assert focus == 1

    def test_counts_stripped(self, template_files):
        xml_path, rgn_path = template_files
        s_xml = xml_path.parent / "stripped.xml"
        s_rgn = rgn_path.parent / "stripped.rgn"
        _strip_xml(xml_path, s_xml)
        _strip_rgn(rgn_path, s_rgn)

        fields, items, focus = _count_objects(s_xml, s_rgn)
        assert fields == 0
        assert items == 0
        assert focus == 0

    def test_missing_file_returns_zeros(self, tmp_path):
        missing = tmp_path / "nope.xml"
        fields, items, focus = _count_objects(missing, missing)
        assert (fields, items, focus) == (0, 0, 0)


# ── _is_file_locked ────────────────────────────────────────────────────

class TestIsFileLocked:
    def test_unlocked_file(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_text("hello")
        assert _is_file_locked(p) is False

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nope.txt"
        assert _is_file_locked(p) is False


# ── _wait_file_stable ──────────────────────────────────────────────────

class TestWaitFileStable:
    def test_stable_file_returns_true(self, tmp_path):
        p = tmp_path / "stable.txt"
        p.write_text("data")
        assert _wait_file_stable(p, timeout=2, poll_interval=0.05,
                                 stable_readings=2) is True

    def test_missing_file_times_out(self, tmp_path):
        p = tmp_path / "nope.txt"
        assert _wait_file_stable(p, timeout=0.3, poll_interval=0.05) is False

    def test_empty_file_times_out(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_text("")
        assert _wait_file_stable(p, timeout=0.3, poll_interval=0.05) is False


# ── get_template_state ─────────────────────────────────────────────────

class TestGetTemplateState:
    def test_fresh_no_files(self, tmp_path):
        assert get_template_state(tmp_path) == "fresh"

    def test_unstripped(self, tmp_path):
        (tmp_path / TEMPLATE_XML).write_text("<xml/>")
        assert get_template_state(tmp_path) == "unstripped"

    def test_stripped(self, tmp_path):
        orig = tmp_path / TEMPLATE_XML
        stripped = tmp_path / STRIPPED_XML
        orig.write_text("<xml/>")
        time.sleep(0.05)
        stripped.write_text("<xml/>")
        assert get_template_state(tmp_path) == "stripped"
