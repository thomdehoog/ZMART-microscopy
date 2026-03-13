"""
Unit tests for scanning_template_editors_roi (no LAS X connection needed).
===========================================================================
Run with: python -m pytest test_scanning_template_editors_roi_unit.py -v
"""

import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lasx.scanning_template_editors_roi import (
    um,
    ROI_POLYGON, ROI_RECTANGLE, ROI_ELLIPSE, ROI_LINE,
    argb_color, COLOR_RED, COLOR_BLUE,
    enable_roi_scan, verify_roi_scan,
    clear_rois, add_roi,
    verify_roi_count, verify_roi,
    make_rectangle, make_ellipse, make_polygon, make_star, make_line,
)
from lasx.scanning_template_parsers import parse_lrp


# ── Sample LRP with full ROI structure ──────────────────────────────────

SAMPLE_LRP = """\
<?xml version="1.0" encoding="utf-8"?>
<LDM_Block_Sequence BlockName="MySequence">
  <LDM_Block_Sequence_Block_List>
    <LDM_Block_Sequence_Block BlockID="b1" BlockType="1">
      <LDM_Block_Sequential BlockName="HiRes">
        <LDM_Block_Sequential_Master>
          <ATLConfocalSettingDefinition Zoom="2.0" PanFirstDim="0" PanSecondDim="0" IsRoiScanEnable="0">
            <ROI>
              <LMSDataContainerHeader Version="2">
                <Element Name="BleachPointROISet">
                  <Data><ROISet ROISetType="1" /></Data>
                  <Memory Size="0" MemoryBlockID="mb1" />
                  <Children />
                </Element>
                <Element Name="DCROISet">
                  <Data><ROISet ROISetType="1" PossibleChildROITypes="4294967295" PossibleROITransforms="65535" PossibleROIActions="65535" /></Data>
                  <Memory Size="0" MemoryBlockID="mb2" />
                  <Children />
                </Element>
              </LMSDataContainerHeader>
            </ROI>
          </ATLConfocalSettingDefinition>
        </LDM_Block_Sequential_Master>
        <LDM_Block_Sequential_List>
          <ATLConfocalSettingDefinition Zoom="2.0" PanFirstDim="0" PanSecondDim="0" IsRoiScanEnable="0" />
        </LDM_Block_Sequential_List>
      </LDM_Block_Sequential>
    </LDM_Block_Sequence_Block>
  </LDM_Block_Sequence_Block_List>
</LDM_Block_Sequence>
"""

# LRP with one existing ROI using real LAS X format (<P> vertices, nested Transformation)
SAMPLE_LRP_WITH_ROI = """\
<?xml version="1.0" encoding="utf-8"?>
<LDM_Block_Sequence BlockName="MySequence">
  <LDM_Block_Sequence_Block_List>
    <LDM_Block_Sequence_Block BlockID="b1" BlockType="1">
      <LDM_Block_Sequential BlockName="HiRes">
        <LDM_Block_Sequential_Master>
          <ATLConfocalSettingDefinition Zoom="2.0" IsRoiScanEnable="1">
            <ROI>
              <LMSDataContainerHeader Version="2">
                <Element Name="BleachPointROISet">
                  <Data><ROISet ROISetType="1" /></Data>
                  <Memory Size="0" MemoryBlockID="mb1" />
                  <Children />
                </Element>
                <Element Name="DCROISet">
                  <Data><ROISet ROISetType="1" /></Data>
                  <Memory Size="0" MemoryBlockID="mb2" />
                  <Children>
                    <Element Name="ROI 1" Visibility="2" CopyOption="1" UniqueID="test-uuid-1">
                      <Data>
                        <ROISingle RoiType="8" RoiAction="65535" TransformationType="65535" Color="4294901760" FontName="Arial" FontSize="10000" FontStyle="0" IsClosed="1" Inverted="0" VisibleLabel="1" Visible="1" LineWidth="2" AnnotationText="">
                          <Vertices>
                            <P X="0" Y="-1.5e-4" />
                            <P X="-3.5267e-5" Y="-4.8541e-5" />
                            <P X="-1.42658e-4" Y="-4.6353e-5" />
                            <P X="-5.7063e-5" Y="1.8541e-5" />
                          </Vertices>
                          <Transformation Rotation="0">
                            <Scaling XScale="1" YScale="1" />
                            <Translation X="0" Y="0" />
                          </Transformation>
                        </ROISingle>
                      </Data>
                      <Memory Size="0" MemoryBlockID="MemBlock_12345" />
                      <Children />
                    </Element>
                  </Children>
                </Element>
              </LMSDataContainerHeader>
            </ROI>
          </ATLConfocalSettingDefinition>
        </LDM_Block_Sequential_Master>
        <LDM_Block_Sequential_List>
          <ATLConfocalSettingDefinition Zoom="2.0" IsRoiScanEnable="1" />
        </LDM_Block_Sequential_List>
      </LDM_Block_Sequential>
    </LDM_Block_Sequence_Block>
  </LDM_Block_Sequence_Block_List>
</LDM_Block_Sequence>
"""


@pytest.fixture
def lrp_file(tmp_path):
    """Create a sample LRP file (empty ROIs) and return its path."""
    lrp = tmp_path / "test.lrp"
    lrp.write_text(SAMPLE_LRP, encoding="utf-8")
    return lrp


@pytest.fixture
def lrp_with_roi(tmp_path):
    """Create a sample LRP file (one existing ROI) and return its path."""
    lrp = tmp_path / "test_roi.lrp"
    lrp.write_text(SAMPLE_LRP_WITH_ROI, encoding="utf-8")
    return lrp


# ── Constants ────────────────────────────────────────────────────────

class TestConstants:
    def test_roi_types(self):
        assert ROI_POLYGON == "8"
        assert ROI_RECTANGLE == "16"
        assert ROI_ELLIPSE == "32"
        assert ROI_LINE == "64"

    def test_argb_color(self):
        assert argb_color(255, 0, 0) == "4294901760"
        assert argb_color(0, 255, 0) == "4278255360"
        assert argb_color(0, 0, 255) == "4278190335"

    def test_color_constants(self):
        assert COLOR_RED == "4294901760"
        assert COLOR_BLUE == "4278190335"


# ── enable_roi_scan / verify_roi_scan ────────────────────────────────

class TestEnableRoiScan:
    def test_enable(self, lrp_file):
        count = enable_roi_scan(lrp_file, True, "HiRes")
        assert count == 2  # Master + Sequential

        root = ET.parse(lrp_file).getroot()
        for el in root.findall(".//ATLConfocalSettingDefinition"):
            assert el.get("IsRoiScanEnable") == "1"

    def test_disable(self, lrp_with_roi):
        count = enable_roi_scan(lrp_with_roi, False, "HiRes")
        assert count == 2

        root = ET.parse(lrp_with_roi).getroot()
        for el in root.findall(".//ATLConfocalSettingDefinition"):
            assert el.get("IsRoiScanEnable") == "0"

    def test_already_disabled(self, lrp_file):
        count = enable_roi_scan(lrp_file, False, "HiRes")
        assert count == 0

    def test_missing_job(self, lrp_file):
        count = enable_roi_scan(lrp_file, True, "NoSuchJob")
        assert count == 0

    def test_roundtrip(self, lrp_file):
        for enable in (True, False, True):
            enable_roi_scan(lrp_file, enable, "HiRes")
            assert verify_roi_scan(lrp_file, enable, "HiRes")


class TestVerifyRoiScan:
    def test_correct_disabled(self, lrp_file):
        assert verify_roi_scan(lrp_file, False, "HiRes") is True

    def test_correct_enabled(self, lrp_with_roi):
        assert verify_roi_scan(lrp_with_roi, True, "HiRes") is True

    def test_wrong_value(self, lrp_file):
        assert verify_roi_scan(lrp_file, True, "HiRes") is False

    def test_missing_job(self, lrp_file):
        assert verify_roi_scan(lrp_file, False, "NoSuchJob") is False


# ── clear_rois ───────────────────────────────────────────────────────

class TestClearRois:
    def test_removes_existing(self, lrp_with_roi):
        count = clear_rois(lrp_with_roi, "HiRes")
        assert count == 1

        # DCROISet/Children should now be empty
        root = ET.parse(lrp_with_roi).getroot()
        dc = root.find(".//Element[@Name='DCROISet']/Children")
        assert dc is not None
        assert len(list(dc)) == 0

    def test_noop_on_empty(self, lrp_file):
        count = clear_rois(lrp_file, "HiRes")
        assert count == 0

    def test_missing_job(self, lrp_file):
        count = clear_rois(lrp_file, "NoSuchJob")
        assert count == 0


# ── add_roi ──────────────────────────────────────────────────────────

class TestAddRoi:
    def test_add_polygon(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        result = add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        assert result is True

        # Verify via parse_lrp
        parsed = parse_lrp(lrp_file)
        master = parsed["jobs"]["HiRes"]["Master"]
        assert "_ROIs" in master
        assert len(master["_ROIs"]) == 1
        assert master["_ROIs"][0]["RoiType"] == "8"
        assert len(master["_ROIs"][0]["_Vertices"]) == 4

    def test_add_multiple(self, lrp_file):
        for _ in range(3):
            verts = make_rectangle(um(50), um(50))
            add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        assert verify_roi_count(lrp_file, 3, "HiRes")

    def test_add_ellipse(self, lrp_file):
        verts = make_ellipse(um(80), um(40), n_points=12)
        result = add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        assert result is True
        assert verify_roi(lrp_file, "HiRes", 0, roi_type=ROI_POLYGON,
                          n_vertices=12)

    def test_add_line(self, lrp_file):
        verts = make_line(um(-100), 0, um(100), 0)
        result = add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        assert result is True
        assert verify_roi(lrp_file, "HiRes", 0, n_vertices=2)

    def test_missing_job(self, lrp_file):
        result = add_roi(lrp_file, "NoSuchJob", ROI_POLYGON,
                         [(0.0, 0.0), (um(100), um(100))])
        assert result is False

    def test_clear_then_add(self, lrp_with_roi):
        clear_rois(lrp_with_roi, "HiRes")
        assert verify_roi_count(lrp_with_roi, 0, "HiRes")

        verts = make_rectangle(um(80), um(80))
        add_roi(lrp_with_roi, "HiRes", ROI_POLYGON, verts)
        assert verify_roi_count(lrp_with_roi, 1, "HiRes")

    def test_custom_color(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        result = add_roi(lrp_file, "HiRes", ROI_POLYGON, verts,
                         color=COLOR_BLUE)
        assert result is True

        parsed = parse_lrp(lrp_file)
        roi = parsed["jobs"]["HiRes"]["Master"]["_ROIs"][0]
        assert roi["Color"] == "4278190335"

    def test_transformation_parsed(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        result = add_roi(lrp_file, "HiRes", ROI_POLYGON, verts,
                         rotation=45.0,
                         translation=(um(10), um(-20)),
                         scale=(2.0, 3.0))
        assert result is True

        parsed = parse_lrp(lrp_file)
        roi = parsed["jobs"]["HiRes"]["Master"]["_ROIs"][0]
        assert "_Transformation" in roi
        t = roi["_Transformation"]
        assert t["Rotation"] == "45.0"
        assert t["XScale"] == "2.0"
        assert t["YScale"] == "3.0"

    def test_auto_naming(self, lrp_file):
        verts = make_rectangle(um(50), um(50))
        add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        root = ET.parse(lrp_file).getroot()
        dc = root.find(".//Element[@Name='DCROISet']/Children")
        names = [el.get("Name") for el in dc]
        assert names == ["ROI 1", "ROI 2"]

    def test_element_has_uuid(self, lrp_file):
        verts = make_rectangle(um(50), um(50))
        add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        root = ET.parse(lrp_file).getroot()
        dc = root.find(".//Element[@Name='DCROISet']/Children")
        roi_el = list(dc)[0]
        assert roi_el.get("Visibility") == "2"
        assert roi_el.get("CopyOption") == "1"
        assert roi_el.get("UniqueID") is not None
        assert len(roi_el.get("UniqueID")) > 10

    def test_memory_block_unique(self, lrp_file):
        verts = make_rectangle(um(50), um(50))
        add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        root = ET.parse(lrp_file).getroot()
        dc = root.find(".//Element[@Name='DCROISet']/Children")
        mem_ids = [el.find("Memory").get("MemoryBlockID") for el in dc]
        assert len(set(mem_ids)) == 2  # unique

    def test_vertices_use_p_tag(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        root = ET.parse(lrp_file).getroot()
        rs = root.find(".//ROISingle")
        v_el = rs.find("Vertices")
        assert len(v_el.findall("P")) == 4
        assert len(v_el.findall("Item")) == 0

    def test_transformation_nested(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        add_roi(lrp_file, "HiRes", ROI_POLYGON, verts,
                translation=(um(5), um(10)), scale=(2.0, 3.0))

        root = ET.parse(lrp_file).getroot()
        rs = root.find(".//ROISingle")
        t = rs.find("Transformation")
        assert t is not None
        assert t.find("Scaling") is not None
        assert t.find("Scaling").get("XScale") == "2.0"
        assert t.find("Translation") is not None


# ── make_* shape helpers ─────────────────────────────────────────────

class TestMakeShapes:
    def test_rectangle(self):
        verts = make_rectangle(100, 60)
        assert len(verts) == 4
        # Corners around default centre (0, 0)
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        assert min(xs) == pytest.approx(-50)
        assert max(xs) == pytest.approx(50)
        assert min(ys) == pytest.approx(-30)
        assert max(ys) == pytest.approx(30)

    def test_rectangle_offset(self):
        verts = make_rectangle(20, 20, center_x=100, center_y=50)
        assert len(verts) == 4
        xs = [v[0] for v in verts]
        assert min(xs) == pytest.approx(90)
        assert max(xs) == pytest.approx(110)

    def test_ellipse(self):
        verts = make_ellipse(80, 40, n_points=36)
        assert len(verts) == 36
        # First point should be at (cx + rx, cy) = (80, 0)
        assert verts[0][0] == pytest.approx(80)
        assert verts[0][1] == pytest.approx(0)

    def test_ellipse_default_100_points(self):
        verts = make_ellipse(50, 50)
        assert len(verts) == 100

    def test_ellipse_n_points(self):
        for n in (4, 12, 72):
            verts = make_ellipse(10, 10, n_points=n)
            assert len(verts) == n

    def test_polygon_passthrough(self):
        pts = [(0.0, 0.0), (100.0, 0.0), (50.0, 100.0)]
        assert make_polygon(pts) == pts

    def test_star_default(self):
        verts = make_star()
        assert len(verts) == 10  # 5-pointed -> 10 vertices
        # First vertex is top (12 o'clock): (0, -um(5))
        assert verts[0][0] == pytest.approx(0.0, abs=1e-12)
        assert verts[0][1] == pytest.approx(-um(5))

    def test_star_explicit_radii(self):
        verts = make_star(outer_radius=um(10), inner_radius=um(4))
        # Vertex 0 (outer, top): (0, -um(10))
        assert verts[0][0] == pytest.approx(0.0, abs=1e-12)
        assert verts[0][1] == pytest.approx(um(-10), abs=1e-10)
        # Vertex 1 (inner, clockwise): r=um(4), angle = -pi/2 - pi/5
        assert verts[1][0] == pytest.approx(um(4) * -math.sin(math.pi/5), abs=1e-12)
        assert verts[1][1] == pytest.approx(um(4) * -math.cos(math.pi/5), abs=1e-12)

    def test_star_custom(self):
        verts = make_star(n_points=6, outer_radius=100, inner_radius=50)
        assert len(verts) == 12

    def test_star_add_roi(self, lrp_file):
        verts = make_star()
        result = add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        assert result is True
        assert verify_roi(lrp_file, "HiRes", 0, n_vertices=10)

    def test_line(self):
        verts = make_line(-100, 0, 100, 0)
        assert len(verts) == 2
        assert verts[0] == (-100, 0)
        assert verts[1] == (100, 0)


# ── Parser: real LAS X format roundtrip ──────────────────────────────

class TestParserRoundtrip:
    def test_parses_p_vertices(self, lrp_with_roi):
        parsed = parse_lrp(lrp_with_roi)
        roi = parsed["jobs"]["HiRes"]["Master"]["_ROIs"][0]
        assert len(roi["_Vertices"]) == 4
        # Fixture vertices are in metres (e.g. -1.5e-4 m = -150 um)
        assert roi["_Vertices"][0]["X"] == pytest.approx(0.0)
        assert roi["_Vertices"][0]["Y"] == pytest.approx(-1.5e-4, rel=1e-3)

    def test_parses_nested_transformation(self, lrp_with_roi):
        parsed = parse_lrp(lrp_with_roi)
        roi = parsed["jobs"]["HiRes"]["Master"]["_ROIs"][0]
        t = roi["_Transformation"]
        assert t["Rotation"] == "0"
        assert t["XScale"] == "1"
        assert t["YScale"] == "1"
        assert t["TranslationX"] == "0"
        assert t["TranslationY"] == "0"

    def test_writer_reader_roundtrip(self, lrp_file):
        """Verify that what add_roi writes, parse_lrp reads back."""
        verts = make_star()
        add_roi(lrp_file, "HiRes", ROI_POLYGON, verts,
                rotation=15.0, translation=(5.0, -10.0),
                scale=(1.5, 2.0))

        parsed = parse_lrp(lrp_file)
        roi = parsed["jobs"]["HiRes"]["Master"]["_ROIs"][0]
        assert roi["RoiType"] == "8"
        assert len(roi["_Vertices"]) == 10
        t = roi["_Transformation"]
        assert t["Rotation"] == "15.0"
        assert t["XScale"] == "1.5"
        assert t["YScale"] == "2.0"
        assert t["TranslationX"] == "5.0"
        assert t["TranslationY"] == "-10.0"


# ── verify_roi_count ─────────────────────────────────────────────────

class TestVerifyRoiCount:
    def test_empty(self, lrp_file):
        assert verify_roi_count(lrp_file, 0, "HiRes") is True

    def test_empty_wrong(self, lrp_file):
        assert verify_roi_count(lrp_file, 1, "HiRes") is False

    def test_one_roi(self, lrp_with_roi):
        assert verify_roi_count(lrp_with_roi, 1, "HiRes") is True

    def test_one_roi_wrong(self, lrp_with_roi):
        assert verify_roi_count(lrp_with_roi, 0, "HiRes") is False

    def test_missing_job(self, lrp_file):
        assert verify_roi_count(lrp_file, 0, "NoSuchJob") is True


# ── verify_roi ───────────────────────────────────────────────────────

class TestVerifyRoi:
    def test_correct(self, lrp_with_roi):
        assert verify_roi(lrp_with_roi, "HiRes", 0,
                          roi_type="8", n_vertices=4) is True

    def test_wrong_type(self, lrp_with_roi):
        assert verify_roi(lrp_with_roi, "HiRes", 0,
                          roi_type="99") is False

    def test_wrong_vertex_count(self, lrp_with_roi):
        assert verify_roi(lrp_with_roi, "HiRes", 0,
                          n_vertices=3) is False

    def test_index_out_of_range(self, lrp_with_roi):
        assert verify_roi(lrp_with_roi, "HiRes", 5) is False

    def test_missing_job(self, lrp_with_roi):
        assert verify_roi(lrp_with_roi, "NoSuchJob", 0) is False

    def test_partial_check(self, lrp_with_roi):
        # Check only type
        assert verify_roi(lrp_with_roi, "HiRes", 0, roi_type="8") is True
        # Check only vertices
        assert verify_roi(lrp_with_roi, "HiRes", 0,
                          n_vertices=4) is True
        # Check neither (just index existence)
        assert verify_roi(lrp_with_roi, "HiRes", 0) is True
