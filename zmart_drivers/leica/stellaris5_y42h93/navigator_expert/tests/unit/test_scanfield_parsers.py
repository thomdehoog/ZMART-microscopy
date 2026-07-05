"""
Unit tests for scan-field parsers (no LAS X connection needed).
=================================================================
Run with:
    python -m pytest tests/unit/test_scanfield_parsers.py -v
"""

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from navigator_expert.scanfields.parsers import (
    _get_raw_tiles,
    _parse_size_string,
    _tile_size_from_image_size_str,
    _to_float,
    _to_int,
    parse_acquisition_positions,
    parse_base_grid,
    parse_focus_points,
    parse_matrix_settings,
    parse_rgn_geometries,
    parse_rgn_tile_colors,
    parse_scan_positions,
)

# -- Sample data ---------------------------------------------------------

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

# -- Type conversion helpers ---------------------------------------------


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


# -- Tile size helpers ---------------------------------------------------


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


# -- Tile positions from XML ---------------------------------------------


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


class TestParseTemplatePositionsFromRgnGrid:
    def _write_grid_template(self, tmp_path, *, base="PythonInspect", tag=None):
        xml = """\
<ScanningTemplate>
  <ExperimentData>
    <Experiment>
      <ApplicationData>
        <MatrixData>
          <CountOfData IsEnabled="true" ScanFieldsX="3" ScanFieldsY="2"
                       SectionsX="1" SectionsY="1" RegionsX="0" RegionsY="0"
                       SamplesX="0" SamplesY="0" />
          <ConfocalData FieldRotation="0" />
        </MatrixData>
      </ApplicationData>
      <ScanFields />
    </Experiment>
  </ExperimentData>
</ScanningTemplate>
"""
        rgn = """\
<StageOverviewRegions>
  <Regions>
    <ShapeList>
      <Items>
        <Item0>
          <Type>Rectangle</Type>
          <Identifier>scan-field-1</Identifier>
          <Verticies><Items>
            <Item0><X>0.010</X><Y>0.020</Y></Item0>
            <Item1><X>0.012</X><Y>0.020</Y></Item1>
            <Item2><X>0.010</X><Y>0.021</Y></Item2>
            <Item3><X>0.012</X><Y>0.021</Y></Item3>
          </Items></Verticies>
        </Item0>
      </Items>
    </ShapeList>
  </Regions>
</StageOverviewRegions>
"""
        if tag is not None:
            rgn = rgn.replace(
                "          <Identifier>scan-field-1</Identifier>",
                f"          <Tag>{tag}</Tag>\n          <Identifier>scan-field-1</Identifier>",
            )
        (tmp_path / f"{base}.xml").write_text(xml, encoding="utf-8")
        (tmp_path / f"{base}.rgn").write_text(rgn, encoding="utf-8")
        return base

    def test_derives_grid_when_xml_scanfields_are_empty(self, tmp_path):
        base = self._write_grid_template(tmp_path)

        parsed = parse_scan_positions(
            tmp_path,
            base,
            tile_size_um=100.0,
            default_job_name="Overview",
        )

        regions = parsed["acquisition_positions"]
        assert len(regions) == 1
        region = regions["0"]
        assert region["source"] == "rgn_matrix"
        assert region["job_name"] == "Overview"
        assert region["num_rows"] == 2
        assert region["num_cols"] == 3
        assert region["num_tiles"] == 6
        assert [p["x_um"] for p in region["positions"][:3]] == [
            10000.0,
            11000.0,
            12000.0,
        ]
        assert [p["y_um"] for p in region["positions"][::3]] == [
            20000.0,
            21000.0,
        ]

    def test_default_job_name_is_queried_for_tile_size(
        self,
        tmp_path,
        monkeypatch,
    ):
        base = self._write_grid_template(tmp_path)

        from navigator_expert import readers as readers

        def fake_get_job_settings(_client, job_name, *, mode=None):
            assert job_name == "Overview"
            assert mode == "api"
            return {"imageSize": "1200.0 um x 1200.0 um"}

        monkeypatch.setattr(readers, "get_job_settings", fake_get_job_settings)

        parsed = parse_scan_positions(
            tmp_path,
            base,
            client=object(),
            default_job_name="Overview",
        )

        region = parsed["acquisition_positions"]["0"]
        assert region["tile_size_um"] == 1200.0
        assert "bounding_box" in region["positions"][0]

    def test_geometry_tile_count_wins_over_stale_matrix_grid(self, tmp_path):
        base = self._write_grid_template(tmp_path, tag="R1 (2)")

        parsed = parse_scan_positions(
            tmp_path,
            base,
            tile_size_um=1200.0,
            default_job_name="Overview",
        )

        regions = parsed["acquisition_positions"]
        assert len(regions) == 1
        region = regions["0"]
        assert region["source"] == "geometry_plan"
        assert region["label"] == "R1 (2)"
        assert region["job_name"] == "Overview"
        assert region["num_tiles"] == 2

    def test_materialized_xml_positions_win_over_rgn_grid(self, tmp_path):
        base = "PythonInspect"
        xml = SAMPLE_XML.replace(
            "</Experiment>",
            """
  <MatrixData>
    <CountOfData IsEnabled="true" ScanFieldsX="9" ScanFieldsY="9" />
  </MatrixData>
</Experiment>
""",
        )
        rgn = SAMPLE_RGN_GEOM
        (tmp_path / f"{base}.xml").write_text(xml, encoding="utf-8")
        (tmp_path / f"{base}.rgn").write_text(rgn, encoding="utf-8")

        parsed = parse_scan_positions(
            tmp_path,
            base,
            tile_size_um=100.0,
            default_job_name="Overview",
        )

        region = parsed["acquisition_positions"]["0"]
        assert region.get("source") != "rgn_matrix"
        assert region["num_tiles"] == 2

    def test_materialized_and_grid_spec_representations_match(self, tmp_path):
        materialized_dir = tmp_path / "materialized"
        grid_spec_dir = tmp_path / "grid_spec"
        materialized_dir.mkdir()
        grid_spec_dir.mkdir()
        base = "PythonInspect"

        rgn = """\
<StageOverviewRegions>
  <Regions>
    <ShapeList>
      <Items>
        <Item0>
          <Type>Rectangle</Type>
          <Identifier>same-field</Identifier>
          <Verticies><Items>
            <Item0><X>0.010</X><Y>0.020</Y></Item0>
            <Item1><X>0.012</X><Y>0.020</Y></Item1>
            <Item2><X>0.010</X><Y>0.021</Y></Item2>
            <Item3><X>0.012</X><Y>0.021</Y></Item3>
          </Items></Verticies>
        </Item0>
      </Items>
    </ShapeList>
  </Regions>
</StageOverviewRegions>
"""
        grid_spec_xml = """\
<ScanningTemplate>
  <ExperimentData>
    <Experiment>
      <ApplicationData>
        <MatrixData>
          <CountOfData IsEnabled="true" ScanFieldsX="3" ScanFieldsY="2" />
          <ConfocalData FieldRotation="0" />
        </MatrixData>
      </ApplicationData>
      <ScanFields />
    </Experiment>
  </ExperimentData>
</ScanningTemplate>
"""
        materialized_xml = """\
<ScanningTemplate>
  <ExperimentData>
    <Experiment>
      <ApplicationData>
        <MatrixData>
          <CountOfData IsEnabled="true" ScanFieldsX="3" ScanFieldsY="2" />
          <ConfocalData FieldRotation="0" />
        </MatrixData>
      </ApplicationData>
      <ScanFields>
        <ScanFieldData IsEnabled="true" UniqueID="1" ScanOrder="1" ScanRotationAngle="0">
          <MainJobData JobName="Overview" JobId="1" />
          <LogicalData SectionX="0" SectionY="0" FieldX="0" FieldY="0" />
          <PhysicalData XPosition="10000" YPosition="20000" ZPosition="0" />
        </ScanFieldData>
        <ScanFieldData IsEnabled="true" UniqueID="2" ScanOrder="2" ScanRotationAngle="0">
          <MainJobData JobName="Overview" JobId="1" />
          <LogicalData SectionX="0" SectionY="0" FieldX="1" FieldY="0" />
          <PhysicalData XPosition="11000" YPosition="20000" ZPosition="0" />
        </ScanFieldData>
        <ScanFieldData IsEnabled="true" UniqueID="3" ScanOrder="3" ScanRotationAngle="0">
          <MainJobData JobName="Overview" JobId="1" />
          <LogicalData SectionX="0" SectionY="0" FieldX="2" FieldY="0" />
          <PhysicalData XPosition="12000" YPosition="20000" ZPosition="0" />
        </ScanFieldData>
        <ScanFieldData IsEnabled="true" UniqueID="4" ScanOrder="4" ScanRotationAngle="0">
          <MainJobData JobName="Overview" JobId="1" />
          <LogicalData SectionX="0" SectionY="0" FieldX="0" FieldY="1" />
          <PhysicalData XPosition="10000" YPosition="21000" ZPosition="0" />
        </ScanFieldData>
        <ScanFieldData IsEnabled="true" UniqueID="5" ScanOrder="5" ScanRotationAngle="0">
          <MainJobData JobName="Overview" JobId="1" />
          <LogicalData SectionX="0" SectionY="0" FieldX="1" FieldY="1" />
          <PhysicalData XPosition="11000" YPosition="21000" ZPosition="0" />
        </ScanFieldData>
        <ScanFieldData IsEnabled="true" UniqueID="6" ScanOrder="6" ScanRotationAngle="0">
          <MainJobData JobName="Overview" JobId="1" />
          <LogicalData SectionX="0" SectionY="0" FieldX="2" FieldY="1" />
          <PhysicalData XPosition="12000" YPosition="21000" ZPosition="0" />
        </ScanFieldData>
      </ScanFields>
    </Experiment>
  </ExperimentData>
</ScanningTemplate>
"""
        (materialized_dir / f"{base}.xml").write_text(materialized_xml, encoding="utf-8")
        (grid_spec_dir / f"{base}.xml").write_text(grid_spec_xml, encoding="utf-8")
        for folder in (materialized_dir, grid_spec_dir):
            (folder / f"{base}.rgn").write_text(rgn, encoding="utf-8")

        materialized = parse_scan_positions(
            materialized_dir,
            base,
            tile_size_um=100.0,
            default_job_name="Overview",
        )
        grid_spec = parse_scan_positions(
            grid_spec_dir,
            base,
            tile_size_um=100.0,
            default_job_name="Overview",
        )

        materialized_positions = [
            (p["x_um"], p["y_um"]) for p in materialized["acquisition_positions"]["0"]["positions"]
        ]
        grid_spec_positions = [
            (p["x_um"], p["y_um"]) for p in grid_spec["acquisition_positions"]["0"]["positions"]
        ]
        assert materialized_positions == grid_spec_positions


# -- Base grid from RGN --------------------------------------------------


class TestParseBaseGrid:
    def test_extracts_am1_entries(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN, encoding="utf-8")
        grid = parse_base_grid(rgn)
        assert len(grid) == 1
        assert abs(grid[0]["x_um"] - 1000.0) < 0.1

    def test_missing_file(self, tmp_path):
        assert parse_base_grid(tmp_path / "nope.rgn") == []


# -- Focus points from RGN ----------------------------------------------


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


# =============================================================================
# Geometries from RGN
# =============================================================================

SAMPLE_RGN_GEOM = """\
<?xml version="1.0" encoding="utf-8"?>
<StageOverviewRegions>
  <Regions>
    <ShapeList>
      <Items>
        <Item0><Type>Rectangle</Type><Identifier>rect1</Identifier>
          <Name>{"AM":0,"JN":"Overview"}</Name>
          <LabelText>Overview</LabelText>
          <TileColor>R:200,G:130,B:89,A:100</TileColor>
          <Verticies><Items>
            <Item0><X>0.001</X><Y>0.002</Y></Item0>
            <Item1><X>0.003</X><Y>0.002</Y></Item1>
            <Item2><X>0.003</X><Y>0.004</Y></Item2>
            <Item3><X>0.001</X><Y>0.004</Y></Item3>
          </Items></Verticies>
        </Item0>
        <Item1><Type>Ellipse</Type><Identifier>ell1</Identifier>
          <Name>{"AM":0}</Name>
          <Verticies><Items>
            <Item0><X>0.005</X><Y>0.006</Y></Item0>
            <Item1><X>0.009</X><Y>0.006</Y></Item1>
            <Item2><X>0.007</X><Y>0.005</Y></Item2>
            <Item3><X>0.007</X><Y>0.007</Y></Item3>
          </Items></Verticies>
        </Item1>
        <Item2><Type>CircleDiameter</Type><Identifier>circ1</Identifier>
          <Name>{"AM":0}</Name>
          <Verticies><Items>
            <Item0><X>0.010</X><Y>0.010</Y></Item0>
            <Item1><X>0.014</X><Y>0.010</Y></Item1>
          </Items></Verticies>
        </Item2>
        <Item3><Type>Polygon</Type><Identifier>poly1</Identifier>
          <Name>{"AM":0}</Name>
          <Verticies><Items>
            <Item0><X>0.020</X><Y>0.020</Y></Item0>
            <Item1><X>0.024</X><Y>0.020</Y></Item1>
            <Item2><X>0.022</X><Y>0.024</Y></Item2>
          </Items></Verticies>
        </Item3>
        <Item4><Type>Point</Type><Identifier>pt1</Identifier>
          <Name>{"AM":0}</Name>
          <Verticies><Items>
            <Item0><X>0.030</X><Y>0.030</Y></Item0>
          </Items></Verticies>
        </Item4>
        <Item5><Type>ScanFieldArray</Type><Name>{"AM":1}</Name>
          <Verticies><Items><Item0><X>0.050</X><Y>0.050</Y></Item0></Items></Verticies>
        </Item5>
        <Item6><Type>FocusPoint</Type><Identifier>fp1</Identifier>
          <Verticies><Items><Item0><X>0.060</X><Y>0.060</Y></Item0></Items></Verticies>
        </Item6>
      </Items>
    </ShapeList>
  </Regions>
</StageOverviewRegions>
"""

SAMPLE_XML_MATRIX = """\
<?xml version="1.0" encoding="utf-8"?>
<ScanningTemplate>
  <MatrixData>
    <CountOfData IsEnabled="true" SectionsX="3" SectionsY="2"
                 ScanFieldsX="4" ScanFieldsY="4"
                 RegionsX="0" RegionsY="0"
                 SamplesX="0" SamplesY="0" />
    <DistanceData IsEnabled="true">
      <Origin IsEnabled="true" OriginX="50000" OriginY="30000" OriginZ="0" Units="Microns" />
      <Field IsEnabled="true" DistanceX="1600" DistanceY="1600" DistanceZ="0" Units="Microns" />
    </DistanceData>
    <CarrierData IsEnabled="true" Description1="Frost slide" Description2=""
                 RotationAngle="0" SlideTypeSelected="true" SelectedGlassTypeIndex="0" />
    <AutofocusData ZUseMode="z-galvo" AFForecastMode="1" />
    <ConfocalData FieldRotation="45.0" />
  </MatrixData>
</ScanningTemplate>
"""


class TestParseRgnGeometries:
    def test_extracts_all_shape_types(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN_GEOM, encoding="utf-8")
        geoms = parse_rgn_geometries(rgn)
        types = {g["type"] for g in geoms.values()}
        assert "Rectangle" in types
        assert "Ellipse" in types
        assert "CircleDiameter" in types
        assert "Polygon" in types
        assert "Point" in types

    def test_excludes_am1_and_focus(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN_GEOM, encoding="utf-8")
        geoms = parse_rgn_geometries(rgn)
        assert len(geoms) == 5
        types = {g["type"] for g in geoms.values()}
        assert "ScanFieldArray" not in types
        assert "FocusPoint" not in types

    def test_rectangle_center_and_bbox(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN_GEOM, encoding="utf-8")
        rect = parse_rgn_geometries(rgn)["rect1"]
        assert abs(rect["center_um"]["x_um"] - 2000.0) < 0.1
        assert abs(rect["center_um"]["y_um"] - 3000.0) < 0.1
        bb = rect["bounding_box_um"]
        assert abs(bb["width_um"] - 2000.0) < 0.1
        assert abs(bb["height_um"] - 2000.0) < 0.1

    def test_ellipse_semi_axes(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN_GEOM, encoding="utf-8")
        ell = parse_rgn_geometries(rgn)["ell1"]
        assert abs(ell["center_um"]["x_um"] - 7000.0) < 0.1
        assert ell["semi_axis_a_um"] > 0
        assert ell["semi_axis_b_um"] > 0

    def test_circle_radius(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN_GEOM, encoding="utf-8")
        circ = parse_rgn_geometries(rgn)["circ1"]
        assert abs(circ["center_um"]["x_um"] - 12000.0) < 0.1
        assert abs(circ["radius_um"] - 2000.0) < 0.1

    def test_polygon_centroid_and_bbox(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN_GEOM, encoding="utf-8")
        poly = parse_rgn_geometries(rgn)["poly1"]
        assert "centroid_um" in poly
        assert "bounding_box_um" in poly
        assert len(poly["vertices_um"]) == 3

    def test_point_center(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN_GEOM, encoding="utf-8")
        pt = parse_rgn_geometries(rgn)["pt1"]
        assert abs(pt["center_um"]["x_um"] - 30000.0) < 0.1

    def test_missing_file(self, tmp_path):
        assert parse_rgn_geometries(tmp_path / "nope.rgn") == {}


# =============================================================================
# Tile colors from RGN
# =============================================================================


class TestParseRgnTileColors:
    def test_extracts_rgba(self, tmp_path):
        rgn = tmp_path / "test.rgn"
        rgn.write_text(SAMPLE_RGN_GEOM, encoding="utf-8")
        colors = parse_rgn_tile_colors(rgn)
        assert "Overview" in colors
        r, g, b, a = colors["Overview"]
        assert abs(r - 200 / 255.0) < 0.01
        assert abs(g - 130 / 255.0) < 0.01
        assert abs(a - 1.0) < 0.01

    def test_missing_file(self, tmp_path):
        assert parse_rgn_tile_colors(tmp_path / "nope.rgn") == {}


# =============================================================================
# Matrix settings from XML
# =============================================================================


class TestParseMatrixSettings:
    def test_count(self):
        root = ET.fromstring(SAMPLE_XML_MATRIX)
        ms = parse_matrix_settings(root)
        assert ms["count"]["sectionsX"] == 3
        assert ms["count"]["scanFieldsY"] == 4

    def test_distances(self):
        root = ET.fromstring(SAMPLE_XML_MATRIX)
        ms = parse_matrix_settings(root)
        assert ms["distances"]["origin"]["x_um"] == 50000.0
        assert ms["distances"]["field"]["distanceX_um"] == 1600.0

    def test_carrier(self):
        root = ET.fromstring(SAMPLE_XML_MATRIX)
        ms = parse_matrix_settings(root)
        assert ms["carrier"]["type"] == "Slide"

    def test_autofocus(self):
        root = ET.fromstring(SAMPLE_XML_MATRIX)
        ms = parse_matrix_settings(root)
        assert ms["autofocus"]["zUseMode"] == "z-galvo"

    def test_field_rotation(self):
        root = ET.fromstring(SAMPLE_XML_MATRIX)
        ms = parse_matrix_settings(root)
        assert ms["fieldRotation"] == 45.0

    def test_empty_xml(self):
        root = ET.fromstring("<Experiment/>")
        assert parse_matrix_settings(root) == {}

    def test_none_root(self):
        assert parse_matrix_settings(None) == {}


# =============================================================================
# Real template data tests
# =============================================================================

TEST_DATA = Path(__file__).resolve().parents[1] / "data" / "scanfield_parsing"
GENERAL_WORKFLOW_DATA = Path(__file__).resolve().parents[1] / "data" / "general_workflow"


@pytest.mark.skipif(not TEST_DATA.is_dir(), reason="test data not found")
class TestRealWorkflowFiles:
    @pytest.fixture(params=sorted(TEST_DATA.glob("*.xml")), ids=lambda p: p.stem)
    def template(self, request):
        xml_path = request.param
        base = xml_path.stem
        return TEST_DATA, base

    def test_geometries_not_empty(self, template):
        tdir, base = template
        geoms = parse_rgn_geometries(tdir / (base + ".rgn"))
        assert len(geoms) > 0, f"No geometries in {base}"

    def test_geometry_types_valid(self, template):
        tdir, base = template
        valid = {
            "Rectangle",
            "Ellipse",
            "CircleDiameter",
            "Polygon",
            "AreaLine",
            "MagicWand",
            "Point",
        }
        for g in parse_rgn_geometries(tdir / (base + ".rgn")).values():
            assert g["type"] in valid

    def test_focus_points_not_empty(self, template):
        tdir, base = template
        focus, _ = parse_focus_points(tdir / (base + ".rgn"))
        assert len(focus) > 0

    def test_matrix_settings_present(self, template):
        tdir, base = template
        xml_root = ET.parse(tdir / (base + ".xml")).getroot()
        ms = parse_matrix_settings(xml_root)
        assert "count" in ms or "carrier" in ms


@pytest.mark.skipif(
    not GENERAL_WORKFLOW_DATA.is_dir(), reason="general workflow test data not found"
)
class TestGeneralWorkflowGridSpec:
    def test_geometry_tile_count_tag_wins_over_stale_matrix_count(self):
        parsed = parse_scan_positions(
            GENERAL_WORKFLOW_DATA,
            "{ScanningTemplate}test_hardware_workflow",
            tile_size_um=1200.0,
            default_job_name="Overview",
        )

        regions = parsed["acquisition_positions"]
        assert len(regions) == 1
        region = regions["0"]
        assert region["source"] == "geometry_plan"
        assert region["label"] == "R1 (15)"
        assert region["job_name"] == "Overview"
        assert region["num_tiles"] == 15


def _tile_centers(parsed):
    centers = []
    for region in parsed["acquisition_positions"].values():
        centers.extend((position["x_um"], position["y_um"]) for position in region["positions"])
    return sorted(centers)


def _assert_centers_close(actual, expected, *, tolerance_um=0.05):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected, strict=False):
        assert math.hypot(got[0] - want[0], got[1] - want[1]) <= tolerance_um


@pytest.mark.skipif(not TEST_DATA.is_dir(), reason="test data not found")
class TestAssociatedAndUnassociatedRepresentations:
    @pytest.mark.parametrize(
        ("unassociated", "associated"),
        [
            ("_ScanningTemplate_test2", "_ScanningTemplate_test3"),
            ("_ScanningTemplate_test4", "_ScanningTemplate_test5"),
        ],
    )
    def test_unassociated_geometry_matches_associated_tile_materialization(
        self,
        unassociated,
        associated,
    ):
        """Same RGN geometry should parse like the associated XML ground truth."""
        inferred = parse_scan_positions(
            TEST_DATA,
            unassociated,
            tile_size_um=1550.0,
            default_job_name="Overview",
        )
        ground_truth = parse_scan_positions(
            TEST_DATA,
            associated,
            tile_size_um=1550.0,
            default_job_name="Overview",
        )

        assert {r["job_name"] for r in inferred["acquisition_positions"].values()} == {
            "Overview",
        }
        _assert_centers_close(
            _tile_centers(inferred),
            _tile_centers(ground_truth),
        )
