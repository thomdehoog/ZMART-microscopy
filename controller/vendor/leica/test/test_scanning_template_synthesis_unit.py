"""
Unit tests for scanning_template_synthesis (no LAS X connection needed).
========================================================================
Run with: python -m pytest test_scanning_template_synthesis_unit.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lasx.scanning_template_synthesis import (
    synthesize_tiles,
    assign_focus_points_to_regions,
    _grid_count,
    _point_in_polygon,
    _segments_intersect,
    _rect_overlaps_ellipse,
    _rect_overlaps_circle,
    _rect_overlaps_polygon,
    _generate_from_geometries,
    _make_region,
)


# =============================================================================
# Grid count
# =============================================================================

class TestGridCount:
    def test_single_tile(self):
        assert _grid_count(100, 200, 190) == 1

    def test_exact_fit(self):
        # 1000 um, tile=200, step=190 → (1000-200)/190 = 4.21 → 6 tiles
        assert _grid_count(1000, 200, 190) == 6

    def test_near_integer_rounds_down(self):
        # Fractional part < tol (0.05) should round down
        step = 100.0
        tile = 100.0
        # dimension chosen so raw = 5.004 → frac=0.004 < 0.05 → floor → 6
        dim = tile + 5.004 * step
        assert _grid_count(dim, tile, step) == 6

    def test_minimum_one(self):
        assert _grid_count(10, 1000, 950) == 1


# =============================================================================
# Point-in-polygon
# =============================================================================

class TestPointInPolygon:
    def test_inside_triangle(self):
        tri = [(0, 0), (10, 0), (5, 10)]
        assert _point_in_polygon(5, 3, tri) is True

    def test_outside_triangle(self):
        tri = [(0, 0), (10, 0), (5, 10)]
        assert _point_in_polygon(20, 20, tri) is False

    def test_inside_square(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
        assert _point_in_polygon(5, 5, sq) is True

    def test_outside_square(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
        assert _point_in_polygon(15, 5, sq) is False


# =============================================================================
# Segment intersection
# =============================================================================

class TestSegmentsIntersect:
    def test_crossing(self):
        assert _segments_intersect(0, 0, 10, 10, 0, 10, 10, 0) is True

    def test_parallel(self):
        assert _segments_intersect(0, 0, 10, 0, 0, 1, 10, 1) is False

    def test_non_touching(self):
        assert _segments_intersect(0, 0, 5, 5, 6, 0, 10, 0) is False


# =============================================================================
# Rectangle–shape overlap
# =============================================================================

class TestRectOverlapsEllipse:
    def test_inside(self):
        assert _rect_overlaps_ellipse(0, 0, 50, 0, 0, 100, 80) is True

    def test_outside(self):
        assert _rect_overlaps_ellipse(500, 500, 50, 0, 0, 100, 80) is False

    def test_edge_overlap(self):
        # tile at edge of ellipse
        assert _rect_overlaps_ellipse(90, 0, 50, 0, 0, 100, 80) is True


class TestRectOverlapsCircle:
    def test_inside(self):
        assert _rect_overlaps_circle(0, 0, 50, 0, 0, 100) is True

    def test_outside(self):
        assert _rect_overlaps_circle(200, 200, 50, 0, 0, 100) is False


class TestRectOverlapsPolygon:
    def test_inside(self):
        sq = [(0, 0), (100, 0), (100, 100), (0, 100)]
        assert _rect_overlaps_polygon(50, 50, 10, sq) is True

    def test_outside(self):
        sq = [(0, 0), (100, 0), (100, 100), (0, 100)]
        assert _rect_overlaps_polygon(200, 200, 10, sq) is False

    def test_edge_crossing(self):
        sq = [(0, 0), (100, 0), (100, 100), (0, 100)]
        # tile straddles the edge
        assert _rect_overlaps_polygon(95, 50, 10, sq) is True


# =============================================================================
# Tile generation from geometries
# =============================================================================

class TestGenerateFromGeometries:
    def test_rectangle(self):
        geoms = {
            "r1": {
                "type": "Rectangle",
                "vertices_um": [
                    {"x_um": 0, "y_um": 0},
                    {"x_um": 1000, "y_um": 0},
                    {"x_um": 1000, "y_um": 1000},
                    {"x_um": 0, "y_um": 1000},
                ],
            }
        }
        tiles = _generate_from_geometries(geoms, tile_size_um=500, overlap_pct=0)
        assert len(tiles["r1"]) == 4  # 2x2 grid

    def test_circle(self):
        geoms = {
            "c1": {
                "type": "CircleDiameter",
                "vertices_um": [
                    {"x_um": 0, "y_um": 500},
                    {"x_um": 1000, "y_um": 500},
                ],
            }
        }
        tiles = _generate_from_geometries(geoms, tile_size_um=500, overlap_pct=0)
        # Circle r=500: tiles clipped to circle, fewer than full grid
        assert len(tiles["c1"]) > 0
        # Full 2x2 grid would be 4; circle clips corners
        assert len(tiles["c1"]) <= 4

    def test_point_single_tile(self):
        geoms = {
            "p1": {
                "type": "Point",
                "vertices_um": [{"x_um": 5000, "y_um": 3000}],
            }
        }
        tiles = _generate_from_geometries(geoms, tile_size_um=500, overlap_pct=0)
        assert len(tiles["p1"]) == 1
        assert tiles["p1"][0] == (5000, 3000)

    def test_skips_focus_points(self):
        geoms = {
            "fp": {"type": "FocusPoint", "vertices_um": [{"x_um": 0, "y_um": 0}]},
            "af": {"type": "AutoFocusPoint", "vertices_um": [{"x_um": 0, "y_um": 0}]},
        }
        tiles = _generate_from_geometries(geoms, tile_size_um=500, overlap_pct=0)
        assert len(tiles) == 0


# =============================================================================
# Make region
# =============================================================================

class TestMakeRegion:
    def test_from_tuples(self):
        region = _make_region(
            [(100, 200), (300, 400)], 500, "TestJob")
        assert region["num_tiles"] == 2
        assert region["job_name"] == "TestJob"
        assert region["tile_size_um"] == 500
        assert len(region["positions"]) == 2
        assert "bounding_box" in region["positions"][0]

    def test_from_dicts(self):
        region = _make_region(
            [{"x_um": 100, "y_um": 200}], 500, "TestJob")
        assert region["num_tiles"] == 1

    def test_bounding_box(self):
        region = _make_region(
            [(0, 0), (1000, 1000)], 500, "TestJob")
        bb = region["region_bounding_box"]
        assert bb["x_min_um"] == -250
        assert bb["x_max_um"] == 1250


# =============================================================================
# Synthesize tiles (integration)
# =============================================================================

class TestSynthesizeTiles:
    def test_basic(self):
        data = {
            "geometries": {
                "r1": {
                    "type": "Rectangle",
                    "vertices_um": [
                        {"x_um": 0, "y_um": 0},
                        {"x_um": 2000, "y_um": 0},
                        {"x_um": 2000, "y_um": 2000},
                        {"x_um": 0, "y_um": 2000},
                    ],
                }
            },
            "base_grid": [],
        }
        result = synthesize_tiles(data, tile_size_um=1000, overlap_pct=0)
        assert "acquisition_positions" in result
        assert len(result["acquisition_positions"]) == 1
        region = result["acquisition_positions"]["0"]
        assert region["num_tiles"] == 4  # 2x2

    def test_with_base_grid(self):
        data = {
            "geometries": {},
            "base_grid": [{"x_um": 100, "y_um": 200}],
        }
        result = synthesize_tiles(data, tile_size_um=500)
        assert len(result["acquisition_positions"]) == 1
        assert result["acquisition_positions"]["0"]["num_tiles"] == 1


# =============================================================================
# Focus point assignment
# =============================================================================

class TestAssignFocusPointsToRegions:
    def test_assigns_to_containing_region(self):
        regions = {
            "0": {
                "region_bounding_box": {
                    "x_min_um": 0, "y_min_um": 0,
                    "x_max_um": 1000, "y_max_um": 1000,
                },
                "positions": [{"x_um": 500, "y_um": 500}],
            },
            "1": {
                "region_bounding_box": {
                    "x_min_um": 2000, "y_min_um": 2000,
                    "x_max_um": 3000, "y_max_um": 3000,
                },
                "positions": [{"x_um": 2500, "y_um": 2500}],
            },
        }
        fps = [{"x_um": 500, "y_um": 500, "type": "FocusPoint"}]
        assignments = assign_focus_points_to_regions(fps, regions)
        assert "0" in assignments
        assert len(assignments["0"]) == 1

    def test_fallback_to_nearest(self):
        regions = {
            "0": {
                "region_bounding_box": {
                    "x_min_um": 0, "y_min_um": 0,
                    "x_max_um": 100, "y_max_um": 100,
                },
                "positions": [{"x_um": 50, "y_um": 50}],
            },
        }
        # Point outside all bounding boxes
        fps = [{"x_um": 5000, "y_um": 5000, "type": "FocusPoint"}]
        assignments = assign_focus_points_to_regions(fps, regions)
        assert "0" in assignments

    def test_empty_inputs(self):
        assert assign_focus_points_to_regions([], {}) == {}


# =============================================================================
# Real workflow file integration
# =============================================================================

TEST_DATA = Path(__file__).resolve().parent / "test_data" / "templates"


@pytest.mark.skipif(not TEST_DATA.is_dir(), reason="test data not found")
class TestRealWorkflowSynthesis:
    """Test tile synthesis against real workflow files."""

    def test_synthesis_produces_tiles(self):
        from lasx.scanning_template_parsers import (
            parse_rgn_geometries, parse_base_grid,
        )
        rgn = TEST_DATA / "_ScanningTemplate_Test1.rgn"
        geoms = parse_rgn_geometries(rgn)
        grid = parse_base_grid(rgn)
        data = {"geometries": geoms, "base_grid": grid}
        result = synthesize_tiles(data, tile_size_um=1550.0, overlap_pct=5.0)
        total = sum(r["num_tiles"]
                    for r in result["acquisition_positions"].values())
        assert total > 0, "No tiles generated"

    def test_focus_assignment_covers_all(self):
        from lasx.scanning_template_parsers import (
            parse_template_positions,
        )
        data = parse_template_positions(TEST_DATA, "_ScanningTemplate_Test1")
        if not data["acquisition_positions"]:
            pytest.skip("No acquisition positions in Test1")
        assignments = assign_focus_points_to_regions(
            data["focus_points"], data["acquisition_positions"])
        assigned = sum(len(v) for v in assignments.values())
        assert assigned > 0, "No focus points assigned"
