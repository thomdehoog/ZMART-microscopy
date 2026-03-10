"""
Unit tests for scanning_template_parsers (no LAS X connection needed).
======================================================================
Run with: python -m pytest test_scanning_template_parsers_unit.py -v
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lasx.scanning_template_parsers import (
    _to_float, _to_int,
    _parse_size_string, _tile_size_from_image_size_str,
    _get_job_names,
    _get_raw_tiles, parse_acquisition_positions,
    parse_base_grid, parse_focus_points,
    parse_lrp, diff_lrp,
    UNASSIGNED_JOB,
)


# ── Sample data ─────────────────────────────────────────────────────────

SAMPLE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Experiment>
  <ScanFields>
    <ScanFieldData IsEnabled="true" UniqueID="1" ScanOrder="1" ScanRotationAngle="0">
      <MainJobData JobName="AF Job" JobId="42" />
      <LogicalData SectionX="0" SectionY="0" FieldX="0" FieldY="0" />
      <PhysicalData XPosition="1000" YPosition="2000" ZPosition="100" />
    </ScanFieldData>
    <ScanFieldData IsEnabled="true" UniqueID="2" ScanOrder="2" ScanRotationAngle="0">
      <MainJobData JobName="AF Job" JobId="42" />
      <LogicalData SectionX="0" SectionY="0" FieldX="1" FieldY="0" />
      <PhysicalData XPosition="1500" YPosition="2000" ZPosition="100" />
    </ScanFieldData>
    <ScanFieldData IsEnabled="false" UniqueID="3" ScanOrder="3" ScanRotationAngle="0">
      <MainJobData JobName="AF Job" JobId="42" />
      <LogicalData SectionX="0" SectionY="0" FieldX="2" FieldY="0" />
      <PhysicalData XPosition="2000" YPosition="2000" ZPosition="100" />
    </ScanFieldData>
  </ScanFields>
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
        <Item1><Type>FocusPoint</Type><Identifier>fp_shape</Identifier><Tag>tag1</Tag>
          <Verticies><Items><Item0><X>0.003</X><Y>0.004</Y><Z>0.0001</Z></Item0></Items></Verticies>
        </Item1>
      </Items>
      <FillMaskMode>None</FillMaskMode>
      <VertexUnitMode>Pixels</VertexUnitMode>
    </ShapeList>
  </Regions>
  <FocusMap ZMode="1">
    <FocusPoint Identifier="fp_map" X="0.005" Y="0.006" Z="0.0002" Enabled="true" />
  </FocusMap>
</StageOverviewRegions>
"""

SAMPLE_LRP = """\
<?xml version="1.0" encoding="utf-8"?>
<LDM_Block_Sequence BlockName="MySequence">
  <LDM_Block_Sequence_Element_List>
    <LDM_Block_Sequence_Element BlockID="b1" />
  </LDM_Block_Sequence_Element_List>
  <LDM_Block_Sequence_Block_List>
    <LDM_Block_Sequence_Block BlockID="b1" BlockType="1">
      <LDM_Block_Sequential BlockName="AF Job">
        <LDM_Block_Sequential_Master>
          <ATLConfocalSettingDefinition LineAverage="2" StackCalculationMode="1" StackCalculationModeName="Constant step size" />
        </LDM_Block_Sequential_Master>
        <LDM_Block_Sequential_List>
          <ATLConfocalSettingDefinition LineAverage="2" />
        </LDM_Block_Sequential_List>
      </LDM_Block_Sequential>
    </LDM_Block_Sequence_Block>
  </LDM_Block_Sequence_Block_List>
</LDM_Block_Sequence>
"""


# ── Type conversion helpers ─────────────────────────────────────────────

class TestToFloat:
    def test_valid(self):
        assert _to_float("3.14") == 3.14

    def test_none(self):
        assert _to_float(None) is None

    def test_invalid(self):
        assert _to_float("abc") is None

    def test_integer_string(self):
        assert _to_float("42") == 42.0


class TestToInt:
    def test_valid(self):
        assert _to_int("42") == 42

    def test_float_string(self):
        assert _to_int("3.7") == 3

    def test_none(self):
        assert _to_int(None) is None

    def test_invalid(self):
        assert _to_int("abc") is None


# ── Tile size helpers ───────────────────────────────────────────────────

class TestParseSizeString:
    def test_micrometers(self):
        r = _parse_size_string("290.63 \u00b5m x 290.63 \u00b5m")
        assert r is not None
        assert r["unit"] == "um"
        assert abs(r["x"] - 290.63) < 0.01

    def test_millimeters(self):
        r = _parse_size_string("1.16 mm x 1.16 mm")
        assert r["unit"] == "mm"

    def test_empty(self):
        assert _parse_size_string("") is None
        assert _parse_size_string(None) is None


class TestTileSizeFromImageSizeStr:
    def test_micrometers(self):
        ts = _tile_size_from_image_size_str("290.63 um x 290.63 um")
        assert ts is not None
        assert abs(ts - 290.63) < 0.01

    def test_millimeters(self):
        ts = _tile_size_from_image_size_str("1.16 mm x 1.16 mm")
        assert ts is not None
        assert abs(ts - 1160.0) < 1.0

    def test_invalid(self):
        assert _tile_size_from_image_size_str("garbage") is None


# ── Job names from LRP ──────────────────────────────────────────────────

class TestGetJobNames:
    def test_extracts_job_names(self, tmp_path):
        lrp = tmp_path / "test.lrp"
        lrp.write_text(SAMPLE_LRP, encoding="utf-8")
        names = _get_job_names(lrp)
        assert names == ["AF Job"]


# ── Tile positions from XML ─────────────────────────────────────────────

class TestGetRawTiles:
    def test_extracts_enabled_tiles(self):
        root = ET.fromstring(SAMPLE_XML)
        tiles = _get_raw_tiles(root)
        assert len(tiles) == 2
        assert tiles[0]["x_um"] == 1000.0
        assert tiles[1]["x_um"] == 1500.0

    def test_skip_jobs(self):
        root = ET.fromstring(SAMPLE_XML)
        tiles = _get_raw_tiles(root, skip_jobs={"AF Job"})
        assert len(tiles) == 0


class TestParseAcquisitionPositions:
    def test_groups_into_regions(self):
        root = ET.fromstring(SAMPLE_XML)
        regions = parse_acquisition_positions(root, {"AF Job": 100.0})
        assert "0" in regions
        region = regions["0"]
        assert region["num_tiles"] == 2
        assert region["job_name"] == "AF Job"
        assert region["tile_size_um"] == 100.0

    def test_bounding_box_present(self):
        root = ET.fromstring(SAMPLE_XML)
        regions = parse_acquisition_positions(root, {"AF Job": 100.0})
        assert "region_bounding_box" in regions["0"]
        for pos in regions["0"]["positions"]:
            assert "bounding_box" in pos

    def test_no_tile_size(self):
        root = ET.fromstring(SAMPLE_XML)
        regions = parse_acquisition_positions(root, {})
        assert regions["0"]["tile_size_um"] is None
        for pos in regions["0"]["positions"]:
            assert "bounding_box" not in pos


# ── Base grid from RGN ──────────────────────────────────────────────────

class TestParseBaseGrid:
    def test_extracts_am1_entries(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN, encoding="utf-8")
        grid = parse_base_grid(rgn)
        assert len(grid) == 1
        assert abs(grid[0]["x_um"] - 1000.0) < 0.1

    def test_missing_file(self, tmp_path):
        assert parse_base_grid(tmp_path / "nope.rgn") == []


# ── Focus points from RGN ──────────────────────────────────────────────

class TestParseFocusPoints:
    def test_extracts_focus_and_map(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN, encoding="utf-8")
        focus, autofocus = parse_focus_points(rgn)
        assert len(focus) == 2
        assert len(autofocus) == 0
        ids = {fp["identifier"] for fp in focus}
        assert "fp_shape" in ids
        assert "fp_map" in ids

    def test_missing_file(self, tmp_path):
        focus, autofocus = parse_focus_points(tmp_path / "nope.rgn")
        assert focus == []
        assert autofocus == []


# ── LRP parser ──────────────────────────────────────────────────────────

class TestParseLrp:
    def test_parses_job(self, tmp_path):
        lrp = tmp_path / "test.lrp"
        lrp.write_text(SAMPLE_LRP, encoding="utf-8")
        parsed = parse_lrp(lrp)
        assert parsed["sequence_name"] == "MySequence"
        assert "AF Job" in parsed["jobs"]
        job = parsed["jobs"]["AF Job"]
        assert "Master" in job
        assert job["Master"]["attrs"]["LineAverage"] == "2"

    def test_sequence_elements(self, tmp_path):
        lrp = tmp_path / "test.lrp"
        lrp.write_text(SAMPLE_LRP, encoding="utf-8")
        parsed = parse_lrp(lrp)
        assert len(parsed["sequence_elements"]) == 1
        assert parsed["sequence_elements"][0]["BlockID"] == "b1"


# ── LRP diff ────────────────────────────────────────────────────────────

class TestDiffLrp:
    def test_identical(self, tmp_path):
        lrp = tmp_path / "test.lrp"
        lrp.write_text(SAMPLE_LRP, encoding="utf-8")
        parsed = parse_lrp(lrp)
        diffs = diff_lrp(parsed, parsed)
        assert diffs == []

    def test_detects_change(self, tmp_path):
        lrp = tmp_path / "test.lrp"
        lrp.write_text(SAMPLE_LRP, encoding="utf-8")
        a = parse_lrp(lrp)
        b = parse_lrp(lrp)
        b["jobs"]["AF Job"]["Master"]["attrs"]["LineAverage"] = "4"
        diffs = diff_lrp(a, b)
        assert len(diffs) >= 1
        paths = [d["path"] for d in diffs]
        assert any("LineAverage" in p for p in paths)
