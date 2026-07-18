"""Tests for the driver-only adaptive XY limits notebook support."""

from __future__ import annotations

from pathlib import Path

import pytest

from navigator_expert.limits import adaptive


POINTS = [
    {"x_um": 10_000.0, "y_um": 20_000.0},
    {"x_um": 30_000.0, "y_um": 20_100.0},
    {"x_um": 29_900.0, "y_um": 40_000.0},
    {"x_um": 10_100.0, "y_um": 39_900.0},
]


def _parsed(points=POINTS):
    return {
        "geometries": {
            f"P{index}": {"type": "Point", "center_um": point}
            for index, point in enumerate(points, start=1)
        },
        "acquisition_positions": {},
        "focus_points": [],
        "autofocus_points": [],
    }


def test_boundary_points_require_exactly_four_clean_point_markers():
    points = adaptive.boundary_points_from_template(_parsed())
    assert len(points) == 4
    assert points[0] == {"x_um": 10_000.0, "y_um": 20_000.0}

    with pytest.raises(RuntimeError, match="exactly 4"):
        adaptive.boundary_points_from_template(_parsed(POINTS[:3]))


def test_boundary_points_refuse_other_template_content_before_strip():
    parsed = _parsed()
    parsed["geometries"]["scan"] = {
        "type": "Rectangle",
        "center_um": {"x_um": 20_000.0, "y_um": 30_000.0},
    }
    with pytest.raises(RuntimeError, match="clean template"):
        adaptive.boundary_points_from_template(parsed)


def test_xy_limits_are_the_four_point_bounding_box():
    assert adaptive.xy_limits_from_points(POINTS) == {
        "x_um": {"range": [10_000.0, 30_000.0]},
        "y_um": {"range": [20_000.0, 40_000.0]},
    }


def test_xy_limits_allow_points_below_the_conservative_default_margin():
    measured = [dict(point) for point in POINTS]
    measured[0]["y_um"] = 964.8553

    limits = adaptive.xy_limits_from_points(measured)

    assert limits["y_um"] == {"range": [964.8553, 40_000.0]}


def test_xy_limits_refuse_points_outside_the_maximum_stage_envelope():
    outside = [dict(point) for point in POINTS]
    outside[0]["x_um"] = -1.0
    with pytest.raises(RuntimeError, match="maximum stage envelope"):
        adaptive.xy_limits_from_points(outside)


def test_capture_uses_driver_save_parse_and_strip(monkeypatch, tmp_path):
    calls = []
    client = object()
    for filename in (
        adaptive.TEMPLATE_XML,
        adaptive.TEMPLATE_RGN,
        adaptive.TEMPLATE_LRP,
    ):
        (tmp_path / filename).write_text(filename, encoding="utf-8")
    monkeypatch.setattr(adaptive, "find_scanning_templates_dir", lambda: tmp_path)
    monkeypatch.setattr(
        adaptive,
        "save_experiment",
        lambda *args, **kwargs: calls.append(("save", args, kwargs)) or {"success": True},
    )
    monkeypatch.setattr(
        adaptive,
        "parse_scan_positions",
        lambda *args, **kwargs: calls.append(("parse", args, kwargs)) or _parsed(),
    )
    monkeypatch.setattr(
        adaptive,
        "strip_template_in_place",
        lambda *args, **kwargs: calls.append(("strip", args, kwargs)) or {"success": True},
    )

    captured = adaptive.capture_adaptive_xy_limits(client)
    try:
        assert captured["limits"]["x_um"]["range"] == [10_000.0, 30_000.0]
        assert captured["markers_removed"] is True
        assert [name for name, _args, _kwargs in calls] == ["save", "parse", "strip"]
        assert calls[0][1][0] is client
        assert calls[1][2]["client"] is client
        archived = [Path(path) for path in captured["template_paths"]]
        assert {path.suffix for path in archived} == {".xml", ".rgn", ".lrp"}
        assert all(path.read_text(encoding="utf-8") == path.name for path in archived)
    finally:
        captured["_template_archive"].cleanup()
