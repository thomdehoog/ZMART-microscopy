"""discover_targets: submit overviews, turn the object table into targets.

The analysis engine is stubbed synchronously (the real one needs cellpose).
The stub places its objects with the same helper the real analysis uses, so
these tests still hold the frame coordinates to a real number rather than to
whatever the stub felt like returning.
"""

from __future__ import annotations

import numpy as np
import pytest
import tifffile
from application.parts.microscope.simulation import image_point_to_stage_xy

from application.workflows.target_acquisition.steps.discover_targets.discovery import (
    build_overview_inputs,
    discover_targets,
    read_overview_geometry,
)


class _FakeEngine:
    """Synchronous stand-in: returns a canned object table per submitted job."""

    def __init__(self, picks_by_index):
        self.picks_by_index = picks_by_index
        self.jobs = []
        self._results = []

    def submit(self, queue, job):
        self.jobs.append(job)
        self._results.append(
            {"input": job, "object_analysis": {"objects": _table(
                self.picks_by_index.get(job["naming_p"], []), job)}}
        )

    def status(self, queue):
        return {"pending": 0, "running": 0, "failed": 0, "failures": []}

    def results(self, queue):
        out, self._results = self._results, []
        return out


def _table(picks, job):
    """The picks as the object table object_analysis publishes.

    Stage coordinates come from the real helper, given the job's own geometry
    -- the same call the analysis makes -- so a test asserting a frame
    position is asserting the conversion, not the fixture.
    """
    rows = []
    for index, pick in enumerate(picks, start=1):
        col, row = pick["centroid_col_row_px"]
        stage_x_um, stage_y_um = image_point_to_stage_xy(
            centroid_row_px=row,
            centroid_col_px=col,
            image_size_px=job["source_image_size_px"],
            pixel_size_um=job["source_pixel_size_um"],
            tile_stage_xy_um=job["tile_stage_xy_um"],
            image_to_stage=job["image_to_stage"],
        )
        rows.append({
            "label": index,
            "centroid_row_px": float(row),
            "centroid_col_px": float(col),
            "stage_x_um": float(stage_x_um),
            "stage_y_um": float(stage_y_um),
            "area": float(pick.get("area_px", 1.0)),
            "eccentricity": float(pick.get("eccentricity", 0.0)),
            "intensity_mean": float(pick.get("mean_intensity", 0.0)),
        })
    properties = {name: [row[name] for row in rows] for name in (rows[0] if rows else {})}
    return {"properties": properties, "n_objects": len(rows)}


def _ov(image_path, center, pixel_size, shape_hw):
    return {
        "image_path": image_path,
        "center_frame_um": center,
        "pixel_size_um": pixel_size,
        "image_size_px": shape_hw,
    }


def test_single_cell_centroid_maps_to_frame():
    engine = _FakeEngine(
        {
            0: [
                {
                    "centroid_col_row_px": (110, 70),
                    "area_px": 50,
                    "eccentricity": 0.25,
                    "mean_intensity": 12.0,
                }
            ]
        }
    )
    overviews = [_ov("ov0.tif", (1000.0, 2000.0), 0.5, (100, 200))]  # (H, W)

    targets = discover_targets(engine, overviews)

    assert len(targets) == 1
    # (110-100)*0.5 = +5 ; (70-50)*0.5 = +10
    assert targets[0]["x"] == pytest.approx(1005.0)
    assert targets[0]["y"] == pytest.approx(2010.0)
    assert targets[0]["source"]["area"] == 50
    assert targets[0]["source"]["eccentricity"] == pytest.approx(0.25)
    # engine fed a valid segmentation job
    assert engine.jobs[0]["image_path"] == "ov0.tif"
    assert engine.jobs[0]["source_pixel_size_um"] == (0.5, 0.5)
    assert engine.jobs[0]["source_image_size_px"] == (200, 100)
    assert engine.jobs[0]["image_to_stage"] == [[1.0, 0.0], [0.0, 1.0]]
    assert engine.jobs[0]["tile_id"] == ("overview", 0, 0)


def test_multiple_overviews_and_cells():
    engine = _FakeEngine(
        {
            0: [{"centroid_col_row_px": (100, 50)}],
            1: [{"centroid_col_row_px": (100, 50)}, {"centroid_col_row_px": (150, 50)}],
        }
    )
    overviews = [
        _ov("a", (0.0, 0.0), 1.0, (100, 200)),
        _ov("b", (500.0, 0.0), 1.0, (100, 200)),
    ]

    targets = discover_targets(engine, overviews)

    assert sorted(t["x"] for t in targets) == [0.0, 500.0, 550.0]
    assert all(t["y"] == 0.0 for t in targets)


def test_no_cells_returns_empty():
    engine = _FakeEngine({0: []})
    assert discover_targets(engine, [_ov("a", (0.0, 0.0), 1.0, (100, 200))]) == []


def test_engine_failure_is_not_silently_returned_as_no_targets():
    class FailedEngine(_FakeEngine):
        def status(self, queue):
            return {
                "pending": 0,
                "running": 0,
                "failed": 1,
                "failures": [{"step": "segment_tile", "error": "cellpose unavailable"}],
            }

    with pytest.raises(RuntimeError, match="segment_tile: cellpose unavailable"):
        discover_targets(FailedEngine({}), [_ov("a", (0.0, 0.0), 1.0, (100, 200))])


# --- read_overview_geometry + auto-read bridge ----------------------------


def _ome_desc(*, size_x, size_y, phys_x, phys_y, unit_attr=""):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        f'<Image ID="Image:0"><Pixels ID="Pixels:0" DimensionOrder="XYCZT" '
        f'Type="uint16" SizeX="{size_x}" SizeY="{size_y}" SizeC="1" SizeZ="1" '
        f'SizeT="1" PhysicalSizeX="{phys_x}" PhysicalSizeY="{phys_y}"{unit_attr}/>'
        "</Image></OME>"
    )


def _write_geom_tiff(path, *, h, w, phys_x, phys_y, unit_attr=""):
    desc = _ome_desc(size_x=w, size_y=h, phys_x=phys_x, phys_y=phys_y, unit_attr=unit_attr)
    tifffile.imwrite(
        path, np.zeros((h, w), np.uint16), description=desc, ome=False, photometric="minisblack"
    )


def test_read_geometry_pixel_size_and_shape(tmp_path):
    img = tmp_path / "ov.ome.tiff"
    _write_geom_tiff(img, h=100, w=200, phys_x=0.5, phys_y=0.5)
    geo = read_overview_geometry(img)
    assert geo["pixel_size_um"] == pytest.approx(0.5)
    assert geo["image_size_px"] == (100, 200)  # (H, W)


def test_read_geometry_converts_nm_unit(tmp_path):
    img = tmp_path / "ov.ome.tiff"
    _write_geom_tiff(
        img,
        h=8,
        w=8,
        phys_x=500,
        phys_y=500,
        unit_attr=' PhysicalSizeXUnit="nm" PhysicalSizeYUnit="nm"',
    )
    assert read_overview_geometry(img)["pixel_size_um"] == pytest.approx(0.5)


def test_read_geometry_anisotropic_raises(tmp_path):
    img = tmp_path / "ov.ome.tiff"
    _write_geom_tiff(img, h=8, w=8, phys_x=0.5, phys_y=0.6)
    with pytest.raises(ValueError, match="anisotropic"):
        read_overview_geometry(img)


def test_read_geometry_missing_physical_size_raises(tmp_path):
    img = tmp_path / "ov.ome.tiff"
    desc = (
        '<?xml version="1.0"?>'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        '<Image ID="Image:0"><Pixels ID="Pixels:0" DimensionOrder="XYCZT" '
        'Type="uint16" SizeX="8" SizeY="8" SizeC="1" SizeZ="1" SizeT="1"/></Image></OME>'
    )
    tifffile.imwrite(
        img, np.zeros((8, 8), np.uint16), description=desc, ome=False, photometric="minisblack"
    )
    with pytest.raises(ValueError, match="PhysicalSizeX/Y missing"):
        read_overview_geometry(img)


def test_build_overview_inputs_auto_reads_geometry(tmp_path):
    a = tmp_path / "a.ome.tiff"
    b = tmp_path / "b.ome.tiff"
    _write_geom_tiff(a, h=100, w=200, phys_x=0.5, phys_y=0.5)
    _write_geom_tiff(b, h=100, w=200, phys_x=0.5, phys_y=0.5)
    placed = [{"x": 0.0, "y": 0.0}, {"x": 100.0, "y": 0.0}]

    overviews = build_overview_inputs(placed, [a, b])  # no geometry passed

    assert overviews[0]["pixel_size_um"] == pytest.approx(0.5)
    assert overviews[0]["image_size_px"] == (100, 200)
    assert overviews[1]["center_frame_um"] == (100.0, 0.0)


def test_build_overview_inputs_explicit_geometry_skips_read(tmp_path):
    # Nonexistent paths would blow up read_overview_geometry; explicit geometry
    # must bypass the read entirely.
    placed = [{"x": 1.0, "y": 2.0}]
    overviews = build_overview_inputs(
        placed, ["does-not-exist.tiff"], pixel_size_um=0.25, image_size_px=(64, 64)
    )
    assert overviews[0]["pixel_size_um"] == 0.25
    assert overviews[0]["image_size_px"] == (64, 64)
