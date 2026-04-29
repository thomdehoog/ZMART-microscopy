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
    lrp_enable_roi_scan, lrp_verify_roi_scan,
    lrp_clear_rois, lrp_add_roi,
    lrp_verify_roi_count, lrp_verify_roi,
    make_rectangle, make_ellipse, make_polygon, make_star, make_line,
    roi_translation_to_pan, roi_to_absolute_um,
    absolute_um_to_roi_translation,
    pixel_to_absolute_um, bbox_to_zoom, mask_contour_to_roi,
)
from lasx.scanning_template_parsers import parse_lrp


# Unit-test fixture for pan_scale_um derived from the real helper with
# a fictitious base FOV (600 um, midway between 20x and 10x). Result is
# pan_scale_um = 600 * 0.667 / 0.00775 ≈ 51 639 um/unit — NOT 100 000,
# so any test that accidentally relied on the old hardcoded legacy
# default would fail visibly. Real callers call
# pan_scale_um_from_base_fov with the current objective's base FOV.
from lasx.utils import pan_scale_um_from_base_fov as _pan_scale_helper
_TEST_PAN_SCALE_UM = _pan_scale_helper(600.0)


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


# ── lrp_enable_roi_scan / lrp_verify_roi_scan ────────────────────────────────

class TestEnableRoiScan:
    def test_enable(self, lrp_file):
        count = lrp_enable_roi_scan(lrp_file, True, "HiRes")
        assert count == 2  # Master + Sequential

        root = ET.parse(lrp_file).getroot()
        for el in root.findall(".//ATLConfocalSettingDefinition"):
            assert el.get("IsRoiScanEnable") == "1"

    def test_disable(self, lrp_with_roi):
        count = lrp_enable_roi_scan(lrp_with_roi, False, "HiRes")
        assert count == 2

        root = ET.parse(lrp_with_roi).getroot()
        for el in root.findall(".//ATLConfocalSettingDefinition"):
            assert el.get("IsRoiScanEnable") == "0"

    def test_already_disabled(self, lrp_file):
        count = lrp_enable_roi_scan(lrp_file, False, "HiRes")
        assert count == 0

    def test_missing_job(self, lrp_file):
        count = lrp_enable_roi_scan(lrp_file, True, "NoSuchJob")
        assert count == 0

    def test_roundtrip(self, lrp_file):
        for enable in (True, False, True):
            lrp_enable_roi_scan(lrp_file, enable, "HiRes")
            assert lrp_verify_roi_scan(lrp_file, enable, "HiRes")


class TestVerifyRoiScan:
    def test_correct_disabled(self, lrp_file):
        assert lrp_verify_roi_scan(lrp_file, False, "HiRes") is True

    def test_correct_enabled(self, lrp_with_roi):
        assert lrp_verify_roi_scan(lrp_with_roi, True, "HiRes") is True

    def test_wrong_value(self, lrp_file):
        assert lrp_verify_roi_scan(lrp_file, True, "HiRes") is False

    def test_missing_job(self, lrp_file):
        assert lrp_verify_roi_scan(lrp_file, False, "NoSuchJob") is False


# ── lrp_clear_rois ───────────────────────────────────────────────────────

class TestClearRois:
    def test_removes_existing(self, lrp_with_roi):
        count = lrp_clear_rois(lrp_with_roi, "HiRes")
        assert count == 1

        # DCROISet/Children should now be empty
        root = ET.parse(lrp_with_roi).getroot()
        dc = root.find(".//Element[@Name='DCROISet']/Children")
        assert dc is not None
        assert len(list(dc)) == 0

    def test_noop_on_empty(self, lrp_file):
        count = lrp_clear_rois(lrp_file, "HiRes")
        assert count == 0

    def test_missing_job(self, lrp_file):
        count = lrp_clear_rois(lrp_file, "NoSuchJob")
        assert count == 0


# ── lrp_add_roi ──────────────────────────────────────────────────────────

class TestAddRoi:
    def test_add_polygon(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        result = lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
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
            lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        assert lrp_verify_roi_count(lrp_file, 3, "HiRes")

    def test_add_ellipse(self, lrp_file):
        verts = make_ellipse(um(80), um(40), n_points=12)
        result = lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        assert result is True
        assert lrp_verify_roi(lrp_file, "HiRes", 0, roi_type=ROI_POLYGON,
                          n_vertices=13)  # 12 + closing vertex

    def test_add_line(self, lrp_file):
        verts = make_line(um(-100), 0, um(100), 0)
        result = lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        assert result is True
        assert lrp_verify_roi(lrp_file, "HiRes", 0, n_vertices=2)

    def test_missing_job(self, lrp_file):
        result = lrp_add_roi(lrp_file, "NoSuchJob", ROI_POLYGON,
                         [(0.0, 0.0), (um(100), um(100))])
        assert result is False

    def test_clear_then_add(self, lrp_with_roi):
        lrp_clear_rois(lrp_with_roi, "HiRes")
        assert lrp_verify_roi_count(lrp_with_roi, 0, "HiRes")

        verts = make_rectangle(um(80), um(80))
        lrp_add_roi(lrp_with_roi, "HiRes", ROI_POLYGON, verts)
        assert lrp_verify_roi_count(lrp_with_roi, 1, "HiRes")

    def test_custom_color(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        result = lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts,
                         color=COLOR_BLUE)
        assert result is True

        parsed = parse_lrp(lrp_file)
        roi = parsed["jobs"]["HiRes"]["Master"]["_ROIs"][0]
        assert roi["Color"] == "4278190335"

    def test_transformation_parsed(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        result = lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts,
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
        lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        root = ET.parse(lrp_file).getroot()
        dc = root.find(".//Element[@Name='DCROISet']/Children")
        names = [el.get("Name") for el in dc]
        assert names == ["ROI 1", "ROI 2"]

    def test_element_has_uuid(self, lrp_file):
        verts = make_rectangle(um(50), um(50))
        lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        root = ET.parse(lrp_file).getroot()
        dc = root.find(".//Element[@Name='DCROISet']/Children")
        roi_el = list(dc)[0]
        assert roi_el.get("Visibility") == "2"
        assert roi_el.get("CopyOption") == "1"
        assert roi_el.get("UniqueID") is not None
        assert len(roi_el.get("UniqueID")) > 10

    def test_memory_block_unique(self, lrp_file):
        verts = make_rectangle(um(50), um(50))
        lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        root = ET.parse(lrp_file).getroot()
        dc = root.find(".//Element[@Name='DCROISet']/Children")
        mem_ids = [el.find("Memory").get("MemoryBlockID") for el in dc]
        assert len(set(mem_ids)) == 2  # unique

    def test_vertices_use_p_tag(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)

        root = ET.parse(lrp_file).getroot()
        rs = root.find(".//ROISingle")
        v_el = rs.find("Vertices")
        assert len(v_el.findall("P")) == 4
        assert len(v_el.findall("Item")) == 0

    def test_transformation_nested(self, lrp_file):
        verts = make_rectangle(um(100), um(100))
        lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts,
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
        assert len(verts) == 37  # 36 + closing vertex
        # First point should be at (cx + rx, cy) = (80, 0)
        assert verts[0][0] == pytest.approx(80)
        assert verts[0][1] == pytest.approx(0)

    def test_ellipse_default_100_points(self):
        verts = make_ellipse(50, 50)
        assert len(verts) == 101  # 100 + closing vertex

    def test_ellipse_n_points(self):
        for n in (4, 12, 72):
            verts = make_ellipse(10, 10, n_points=n)
            assert len(verts) == n + 1  # + closing vertex

    def test_polygon_passthrough(self):
        pts = [(0.0, 0.0), (100.0, 0.0), (50.0, 100.0)]
        assert make_polygon(pts) == pts

    def test_star_default(self):
        verts = make_star()
        assert len(verts) == 11  # 5-pointed -> 10 + closing vertex
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
        assert len(verts) == 13  # 12 + closing vertex

    def test_star_lrp_add_roi(self, lrp_file):
        verts = make_star()
        result = lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts)
        assert result is True
        assert lrp_verify_roi(lrp_file, "HiRes", 0, n_vertices=11)

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
        """Verify that what lrp_add_roi writes, parse_lrp reads back."""
        verts = make_star()
        lrp_add_roi(lrp_file, "HiRes", ROI_POLYGON, verts,
                rotation=15.0, translation=(5.0, -10.0),
                scale=(1.5, 2.0))

        parsed = parse_lrp(lrp_file)
        roi = parsed["jobs"]["HiRes"]["Master"]["_ROIs"][0]
        assert roi["RoiType"] == "8"
        assert len(roi["_Vertices"]) == 11  # 10 + closing vertex
        t = roi["_Transformation"]
        assert t["Rotation"] == "15.0"
        assert t["XScale"] == "1.5"
        assert t["YScale"] == "2.0"
        assert t["TranslationX"] == "5.0"
        assert t["TranslationY"] == "-10.0"


# ── lrp_verify_roi_count ─────────────────────────────────────────────────

class TestVerifyRoiCount:
    def test_empty(self, lrp_file):
        assert lrp_verify_roi_count(lrp_file, 0, "HiRes") is True

    def test_empty_wrong(self, lrp_file):
        assert lrp_verify_roi_count(lrp_file, 1, "HiRes") is False

    def test_one_roi(self, lrp_with_roi):
        assert lrp_verify_roi_count(lrp_with_roi, 1, "HiRes") is True

    def test_one_roi_wrong(self, lrp_with_roi):
        assert lrp_verify_roi_count(lrp_with_roi, 0, "HiRes") is False

    def test_missing_job(self, lrp_file):
        assert lrp_verify_roi_count(lrp_file, 0, "NoSuchJob") is True


# ── lrp_verify_roi ───────────────────────────────────────────────────────

class TestVerifyRoi:
    def test_correct(self, lrp_with_roi):
        assert lrp_verify_roi(lrp_with_roi, "HiRes", 0,
                          roi_type="8", n_vertices=4) is True

    def test_wrong_type(self, lrp_with_roi):
        assert lrp_verify_roi(lrp_with_roi, "HiRes", 0,
                          roi_type="99") is False

    def test_wrong_vertex_count(self, lrp_with_roi):
        assert lrp_verify_roi(lrp_with_roi, "HiRes", 0,
                          n_vertices=3) is False

    def test_index_out_of_range(self, lrp_with_roi):
        assert lrp_verify_roi(lrp_with_roi, "HiRes", 5) is False

    def test_missing_job(self, lrp_with_roi):
        assert lrp_verify_roi(lrp_with_roi, "NoSuchJob", 0) is False

    def test_partial_check(self, lrp_with_roi):
        # Check only type
        assert lrp_verify_roi(lrp_with_roi, "HiRes", 0, roi_type="8") is True
        # Check only vertices
        assert lrp_verify_roi(lrp_with_roi, "HiRes", 0,
                          n_vertices=4) is True
        # Check neither (just index existence)
        assert lrp_verify_roi(lrp_with_roi, "HiRes", 0) is True


# =============================================================================
# ROI Translation coordinate helpers
# =============================================================================

class TestRoiTranslationToPan:
    """Test roi_translation_to_pan."""

    def test_zero(self):
        pan_x, pan_y = roi_translation_to_pan(
            0.0, 0.0, pan_scale_um=_TEST_PAN_SCALE_UM)
        assert pan_x == 0.0
        assert pan_y == 0.0

    def test_positive_translation(self):
        # tx = +100 um → pan_x = -100/_TEST_PAN_SCALE_UM (X negated)
        # ty = +200 um → pan_y = +200/_TEST_PAN_SCALE_UM
        tx_m, ty_m = 0.0001, 0.0002
        pan_x, pan_y = roi_translation_to_pan(
            tx_m, ty_m, pan_scale_um=_TEST_PAN_SCALE_UM)
        assert pan_x == pytest.approx(-tx_m * 1e6 / _TEST_PAN_SCALE_UM)
        assert pan_y == pytest.approx(ty_m * 1e6 / _TEST_PAN_SCALE_UM)

    def test_negative_translation(self):
        tx_m, ty_m = -123e-6, 35e-6
        pan_x, pan_y = roi_translation_to_pan(
            tx_m, ty_m, pan_scale_um=_TEST_PAN_SCALE_UM)
        assert pan_x == pytest.approx(-tx_m * 1e6 / _TEST_PAN_SCALE_UM)
        assert pan_y == pytest.approx(ty_m * 1e6 / _TEST_PAN_SCALE_UM)

    def test_x_negated(self):
        """X axis is negated between translation and pan."""
        pan_x, _ = roi_translation_to_pan(
            50e-6, 0, pan_scale_um=_TEST_PAN_SCALE_UM)
        assert pan_x < 0
        pan_x, _ = roi_translation_to_pan(
            -50e-6, 0, pan_scale_um=_TEST_PAN_SCALE_UM)
        assert pan_x > 0

    def test_y_direct(self):
        """Y axis is direct between translation and pan."""
        _, pan_y = roi_translation_to_pan(
            0, 50e-6, pan_scale_um=_TEST_PAN_SCALE_UM)
        assert pan_y > 0
        _, pan_y = roi_translation_to_pan(
            0, -50e-6, pan_scale_um=_TEST_PAN_SCALE_UM)
        assert pan_y < 0


class TestRoiToAbsoluteUm:
    """Test roi_to_absolute_um."""

    def test_zero_translation(self):
        x, y = roi_to_absolute_um(0, 0, 50000, 50000)
        assert x == 50000
        assert y == 50000

    def test_known_values(self):
        # tx = -123 um → abs_x = stage_x - (-123) = stage_x + 123
        # ty = +35 um → abs_y = stage_y + 35
        x, y = roi_to_absolute_um(-123e-6, 35e-6, 22313, 19216)
        assert x == pytest.approx(22436, abs=1)
        assert y == pytest.approx(19251, abs=1)

    def test_roundtrip(self):
        """roi_to_absolute_um → absolute_um_to_roi_translation round-trip."""
        tx_m, ty_m = -82e-6, -348e-6
        stage_x, stage_y = 22313, 19216
        abs_x, abs_y = roi_to_absolute_um(tx_m, ty_m, stage_x, stage_y)
        tx_back, ty_back = absolute_um_to_roi_translation(
            abs_x, abs_y, stage_x, stage_y)
        assert tx_back == pytest.approx(tx_m, abs=1e-12)
        assert ty_back == pytest.approx(ty_m, abs=1e-12)


class TestAbsoluteUmToRoiTranslation:
    """Test absolute_um_to_roi_translation."""

    def test_at_stage_center(self):
        tx, ty = absolute_um_to_roi_translation(50000, 50000, 50000, 50000)
        assert tx == 0.0
        assert ty == 0.0

    def test_offset_right(self):
        # Target 100 um right of stage → tx = stage - target = -100 um
        tx, ty = absolute_um_to_roi_translation(50100, 50000, 50000, 50000)
        assert tx == pytest.approx(-100e-6)
        assert ty == pytest.approx(0)

    def test_offset_up(self):
        # Target 50 um above stage → ty = target - stage = +50 um
        tx, ty = absolute_um_to_roi_translation(50000, 50050, 50000, 50000)
        assert tx == pytest.approx(0)
        assert ty == pytest.approx(50e-6)


# =============================================================================
# Image coordinate helpers
# =============================================================================

class TestPixelToAbsoluteUm:
    """Test pixel_to_absolute_um."""

    def test_center_pixel_at_zero_pan(self):
        """Center pixel maps to stage position when pan is zero."""
        x, y = pixel_to_absolute_um(256, 256, 50000, 50000, 0, 0,
                                     pixel_size_um=2.0,
                                     pan_scale_um=_TEST_PAN_SCALE_UM)
        assert x == pytest.approx(50000)
        assert y == pytest.approx(50000)

    def test_center_pixel_with_pan(self):
        """Center pixel maps to stage + pan * pan_scale_um."""
        stage_x, stage_y = 50000, 50000
        pan_x, pan_y = 0.001, -0.002
        x, y = pixel_to_absolute_um(256, 256, stage_x, stage_y,
                                     pan_x, pan_y, pixel_size_um=2.0,
                                     pan_scale_um=_TEST_PAN_SCALE_UM)
        assert x == pytest.approx(stage_x + pan_x * _TEST_PAN_SCALE_UM)
        assert y == pytest.approx(stage_y + pan_y * _TEST_PAN_SCALE_UM)

    def test_x_inverted(self):
        """Pixel left of center → higher stage X (X inverted)."""
        x_left, _ = pixel_to_absolute_um(100, 256, 50000, 50000, 0, 0,
                                          pixel_size_um=2.0,
                                          pan_scale_um=_TEST_PAN_SCALE_UM)
        x_right, _ = pixel_to_absolute_um(400, 256, 50000, 50000, 0, 0,
                                           pixel_size_um=2.0,
                                           pan_scale_um=_TEST_PAN_SCALE_UM)
        assert x_left > 50000
        assert x_right < 50000

    def test_y_cartesian(self):
        """Cartesian Y: top pixel → higher Y, bottom pixel → lower Y."""
        _, y_top = pixel_to_absolute_um(256, 100, 50000, 50000, 0, 0,
                                         pixel_size_um=2.0,
                                         pan_scale_um=_TEST_PAN_SCALE_UM)
        _, y_bot = pixel_to_absolute_um(256, 400, 50000, 50000, 0, 0,
                                         pixel_size_um=2.0,
                                         pan_scale_um=_TEST_PAN_SCALE_UM)
        assert y_top > 50000  # top pixel → positive Y (Cartesian up)
        assert y_bot < 50000  # bottom pixel → negative Y (Cartesian down)

    def test_pixel_size_scales_offset(self):
        """Larger pixel size → larger physical offset per pixel."""
        x_big, _ = pixel_to_absolute_um(0, 256, 50000, 50000, 0, 0,
                                         pixel_size_um=2.0,
                                         pan_scale_um=_TEST_PAN_SCALE_UM)
        x_small, _ = pixel_to_absolute_um(0, 256, 50000, 50000, 0, 0,
                                           pixel_size_um=0.2,
                                           pan_scale_um=_TEST_PAN_SCALE_UM)
        offset_big = abs(x_big - 50000)
        offset_small = abs(x_small - 50000)
        assert offset_big == pytest.approx(offset_small * 10, rel=0.01)

    def test_custom_image_size(self):
        x, y = pixel_to_absolute_um(512, 512, 50000, 50000, 0, 0,
                                     pixel_size_um=1.0, image_size=1024,
                                     pan_scale_um=_TEST_PAN_SCALE_UM)
        assert x == pytest.approx(50000)
        assert y == pytest.approx(50000)


class TestBboxToZoom:
    """Test bbox_to_zoom."""

    # Use 1000 um as a round FOV at zoom 1 for easy test math
    FOV1 = 1000.0

    def test_large_bbox(self):
        assert bbox_to_zoom(1000, 500, self.FOV1) == 1

    def test_small_bbox(self):
        z = bbox_to_zoom(20, 10, self.FOV1)
        assert z >= 40

    def test_square_bbox(self):
        z = bbox_to_zoom(100, 100, self.FOV1)
        fov = self.FOV1 / z
        assert fov >= 100  # must fit the bbox

    def test_margin(self):
        z_tight = bbox_to_zoom(100, 100, self.FOV1, margin=1.0)
        z_loose = bbox_to_zoom(100, 100, self.FOV1, margin=1.5)
        assert z_tight >= z_loose

    def test_clamp_max(self):
        assert bbox_to_zoom(1, 1, self.FOV1) == 48

    def test_clamp_min(self):
        assert bbox_to_zoom(5000, 5000, self.FOV1) == 1

    def test_zero_size(self):
        assert bbox_to_zoom(0, 0, self.FOV1) == 48


class TestMaskContourToRoi:
    """Test mask_contour_to_roi."""

    PS = 0.2  # arbitrary pixel size in um

    def test_basic_contour(self):
        contour = [(100, 200), (150, 200), (150, 250), (100, 250)]
        verts, trans = mask_contour_to_roi(
            contour, 50000, 50000, 0, 0, pixel_size_um=self.PS,
            pan_scale_um=_TEST_PAN_SCALE_UM)
        assert len(verts) == 4
        assert len(trans) == 2

    def test_vertices_centred(self):
        """Vertices should be centred around (0, 0)."""
        contour = [(100, 200), (200, 200), (200, 300), (100, 300)]
        verts, _ = mask_contour_to_roi(
            contour, 50000, 50000, 0, 0, pixel_size_um=self.PS,
            pan_scale_um=_TEST_PAN_SCALE_UM)
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        assert sum(xs) == pytest.approx(0, abs=1e-12)
        assert sum(ys) == pytest.approx(0, abs=1e-12)

    def test_vertices_in_metres(self):
        """Vertices should be in metres (small values)."""
        contour = [(200, 200), (300, 200), (300, 300), (200, 300)]
        verts, _ = mask_contour_to_roi(
            contour, 50000, 50000, 0, 0, pixel_size_um=self.PS,
            pan_scale_um=_TEST_PAN_SCALE_UM)
        for x, y in verts:
            assert abs(x) < 0.001  # less than 1 mm
            assert abs(y) < 0.001

    def test_translation_is_metres(self):
        """Translation should be in metres."""
        contour = [(200, 200), (300, 300)]
        _, trans = mask_contour_to_roi(
            contour, 50000, 50000, 0, 0, pixel_size_um=self.PS,
            pan_scale_um=_TEST_PAN_SCALE_UM)
        tx, ty = trans
        assert abs(tx) < 1  # reasonable metre-scale values
        assert abs(ty) < 1

    def test_roundtrip_position(self):
        """Centroid of contour should match roi_to_absolute_um of translation."""
        contour = [(100, 200), (200, 200), (200, 300), (100, 300)]
        stage_x, stage_y = 50000, 50000
        verts, (tx, ty) = mask_contour_to_roi(
            contour, stage_x, stage_y, 0, 0, pixel_size_um=self.PS,
            pan_scale_um=_TEST_PAN_SCALE_UM)

        # Recover absolute position from translation
        abs_x, abs_y = roi_to_absolute_um(tx, ty, stage_x, stage_y)

        # Compute expected centroid from pixel conversion
        abs_points = [pixel_to_absolute_um(px, py, stage_x, stage_y,
                                           0, 0, pixel_size_um=self.PS,
                                           pan_scale_um=_TEST_PAN_SCALE_UM)
                      for px, py in contour]
        expected_x = sum(p[0] for p in abs_points) / len(abs_points)
        expected_y = sum(p[1] for p in abs_points) / len(abs_points)

        assert abs_x == pytest.approx(expected_x, abs=0.01)
        assert abs_y == pytest.approx(expected_y, abs=0.01)
