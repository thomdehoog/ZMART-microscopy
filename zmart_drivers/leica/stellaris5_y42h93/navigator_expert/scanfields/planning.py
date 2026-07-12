"""Tile planning from LAS X Navigator geometry.

LAS X does not always write one XML ``ScanFieldData`` entry per tile.
When scan fields are drawn but not associated with an acquisition job,
the XML may contain only unassigned placeholder fields while the real
region definitions live in the RGN geometry. This module turns those
geometries into the same acquisition-position structure produced by the
materialized XML parser.
"""

from __future__ import annotations

import math
import re
from typing import Any

UNASSIGNED_JOB = "(unassigned)"

_OVERLAP_TOL = 0.005


def plan_tiles_from_geometries(
    geometries: dict[str, dict[str, Any]],
    tile_size_um: float,
    *,
    base_grid: list[dict[str, float]] | None = None,
    overlap_pct: float = 5.0,
    job_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Generate acquisition regions from parsed RGN geometries.

    Args:
        geometries: Output from ``parse_rgn_geometries``.
        tile_size_um: Tile edge length from LAS X job settings.
        base_grid: Optional base-grid positions from ``parse_base_grid``.
        overlap_pct: Mosaic overlap percentage used by LAS X.
        job_name: Acquisition job assigned to planned regions.

    Returns:
        ``acquisition_positions``-shaped regions.
    """
    if tile_size_um <= 0:
        return {}

    job = job_name or UNASSIGNED_JOB
    planned = _generate_from_geometries(geometries, tile_size_um, overlap_pct)

    regions: dict[str, dict[str, Any]] = {}
    region_index = 0
    if base_grid:
        regions[str(region_index)] = _make_region(
            base_grid,
            tile_size_um,
            job,
            geometry_id=None,
            label="base grid",
            source="base_grid",
        )
        region_index += 1

    for geom_id, tiles in planned.items():
        geom = geometries.get(geom_id, {})
        if not tiles:
            continue
        regions[str(region_index)] = _make_region(
            tiles,
            tile_size_um,
            job,
            geometry_id=geom_id,
            label=geom.get("tag", ""),
            source="geometry_plan",
        )
        region_index += 1
    return regions


def infer_overlap_pct_from_geometry_counts(
    geometries: dict[str, dict[str, Any]],
    tile_size_um: float,
    *,
    fallback: float = 5.0,
) -> float:
    """Infer overlap from LAS X geometry labels when they carry counts.

    Navigator region tags commonly look like ``"R22 (19)"`` where the
    number in parentheses is the tile count LAS X computed for that
    geometry, not the overlap. When XML tiles are not job-associated,
    this metadata lets the planner choose the overlap that reproduces
    LAS X's tile counts instead of relying on a hardcoded default.
    """
    expected = [
        (geom_id, count)
        for geom_id, geom in geometries.items()
        if (count := _expected_tile_count(geom)) is not None
    ]
    if not expected or tile_size_um <= 0:
        return fallback

    exact: list[float] = []
    best_score: int | None = None
    best_overlap = fallback
    for step in range(0, 501):
        overlap = step / 10.0
        generated = _generate_from_geometries(geometries, tile_size_um, overlap)
        score = sum(abs(len(generated.get(geom_id, [])) - count) for geom_id, count in expected)
        if score == 0:
            exact.append(overlap)
        if best_score is None or score < best_score:
            best_score = score
            best_overlap = overlap

    if exact:
        # Several overlaps can produce the same count, especially for
        # clipped non-rectangular regions. Use the centre of the exact
        # range as the stable LAS X-compatible choice; fixture pairs
        # pin the concrete shapes we support.
        midpoint = exact[len(exact) // 2]
        integer_candidates = [value for value in exact if abs(value - round(value)) < 1e-9]
        if integer_candidates:
            return min(integer_candidates, key=lambda value: abs(value - midpoint))
        return midpoint
    return best_overlap


def has_lasx_tile_count_tags(geometries: dict[str, dict[str, Any]]) -> bool:
    """Return whether any geometry carries LAS X tile-count metadata."""
    return any(_tag_tile_count(geom) is not None for geom in geometries.values())


def _expected_tile_count(geom: dict[str, Any]) -> int | None:
    """Return tile count encoded in LAS X tag text, if present."""
    tag_count = _tag_tile_count(geom)
    if tag_count is not None:
        return tag_count
    if geom.get("type") == "Point":
        return 1
    return None


def _tag_tile_count(geom: dict[str, Any]) -> int | None:
    """Return parenthesized LAS X tile count from tag/label text."""
    for key in ("tag", "label"):
        value = geom.get(key)
        if not value:
            continue
        match = re.search(r"\((\d+)\)\s*$", str(value))
        if match:
            return int(match.group(1))
    return None


def _make_region(
    tile_positions: list[tuple[float, float]] | list[dict[str, float]],
    tile_size_um: float,
    job_name: str,
    *,
    geometry_id: str | None = None,
    label: str = "",
    source: str = "geometry_plan",
) -> dict[str, Any]:
    """Build one acquisition-position region."""
    positions = []
    for i, pt in enumerate(tile_positions):
        if isinstance(pt, dict):
            x_um = float(pt["x_um"])
            y_um = float(pt["y_um"])
        else:
            x_um = float(pt[0])
            y_um = float(pt[1])
        positions.append(
            {
                "acquisition_order": i,
                "row": 0,
                "col": i,
                "x_um": round(x_um, 4),
                "y_um": round(y_um, 4),
                "z_um": 0.0,
                "scan_order_original": i + 1,
                "rotation": 0.0,
                "source": source,
            }
        )

    return {
        "section_x": None,
        "section_y": None,
        "region_row": 0,
        "region_col": 0,
        "job_name": job_name,
        "tile_size_um": round(tile_size_um, 4),
        "num_tiles": len(positions),
        "num_rows": 1,
        "num_cols": len(positions),
        "geometry_id": geometry_id,
        "label": label,
        "source": source,
        "positions": positions,
    }


def _grid_count(dimension: float, tile_size: float, step: float, tol: float = 0.05) -> int:
    """Return tile count along one axis with LAS X-like tolerance."""
    raw = (dimension - tile_size) / step
    frac = raw - math.floor(raw)
    n = math.floor(raw) if frac < tol else math.ceil(raw)
    return max(1, n + 1)


def _generate_from_geometries(
    geometries: dict[str, dict[str, Any]],
    tile_size_um: float,
    overlap_pct: float,
) -> dict[str, list[tuple[float, float]]]:
    """Generate tile centres for each supported Navigator geometry."""
    step = tile_size_um * (1.0 - overlap_pct / 100.0)
    half = tile_size_um / 2.0
    tol_half = half * (1.0 + _OVERLAP_TOL)

    results: dict[str, list[tuple[float, float]]] = {}
    for geom_id, geom in geometries.items():
        gtype = geom.get("type", "")
        raw_verts = geom.get("vertices_um", [])
        verts = [(v["x_um"], v["y_um"]) for v in raw_verts]

        if gtype in ("FocusPoint", "AutoFocusPoint"):
            continue
        if gtype == "Point":
            if verts:
                results[geom_id] = [verts[0]]
            continue
        if len(verts) < 2:
            continue

        bbox = _geometry_bounds(gtype, verts)
        if bbox is None:
            continue
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min
        cx = (x_min + x_max) / 2.0
        cy = (y_min + y_max) / 2.0

        nx = _grid_count(width, tile_size_um, step)
        ny = _grid_count(height, tile_size_um, step)
        start_x = cx - (nx - 1) / 2.0 * step
        start_y = cy - (ny - 1) / 2.0 * step

        tiles = []
        for ix in range(nx):
            for iy in range(ny):
                tx = start_x + ix * step
                ty = start_y + iy * step
                if _tile_overlaps_geometry(
                    gtype,
                    verts,
                    tx,
                    ty,
                    tol_half,
                    bbox,
                ):
                    tiles.append((round(tx, 4), round(ty, 4)))
        results[geom_id] = tiles
    return results


def _geometry_bounds(
    gtype: str,
    verts: list[tuple[float, float]],
) -> tuple[float, float, float, float] | None:
    """Return ``x_min, y_min, x_max, y_max`` for a geometry."""
    if gtype == "CircleDiameter" and len(verts) >= 2:
        cx = (verts[0][0] + verts[1][0]) / 2.0
        cy = (verts[0][1] + verts[1][1]) / 2.0
        radius = (
            math.hypot(
                verts[1][0] - verts[0][0],
                verts[1][1] - verts[0][1],
            )
            / 2.0
        )
        return cx - radius, cy - radius, cx + radius, cy + radius
    if gtype in ("Ellipse", "Rectangle") and len(verts) >= 4:
        points = verts[:4]
    else:
        points = verts
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _tile_overlaps_geometry(
    gtype: str,
    verts: list[tuple[float, float]],
    tx: float,
    ty: float,
    half: float,
    bbox: tuple[float, float, float, float],
) -> bool:
    """Return whether a tile rectangle overlaps the geometry."""
    if gtype == "Rectangle":
        return True
    if gtype == "Ellipse" and len(verts) >= 4:
        xs = [p[0] for p in verts[:4]]
        ys = [p[1] for p in verts[:4]]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        semi_a = (max(xs) - min(xs)) / 2.0
        semi_b = (max(ys) - min(ys)) / 2.0
        return _rect_overlaps_ellipse(tx, ty, half, cx, cy, semi_a, semi_b)
    if gtype == "CircleDiameter" and len(verts) >= 2:
        cx = (verts[0][0] + verts[1][0]) / 2.0
        cy = (verts[0][1] + verts[1][1]) / 2.0
        radius = (
            math.hypot(
                verts[1][0] - verts[0][0],
                verts[1][1] - verts[0][1],
            )
            / 2.0
        )
        return _rect_overlaps_circle(tx, ty, half, cx, cy, radius)
    if gtype in ("AreaLine", "Polygon", "MagicWand"):
        return _rect_overlaps_polygon(tx, ty, half, verts)
    return True


def _rect_overlaps_ellipse(
    tx: float,
    ty: float,
    half: float,
    cx: float,
    cy: float,
    semi_a: float,
    semi_b: float,
) -> bool:
    """Clamp ellipse centre to tile rectangle and test ellipse equation."""
    if semi_a <= 0 or semi_b <= 0:
        return False
    nx = max(tx - half, min(cx, tx + half))
    ny = max(ty - half, min(cy, ty + half))
    return ((nx - cx) / semi_a) ** 2 + ((ny - cy) / semi_b) ** 2 <= 1.0


def _rect_overlaps_circle(
    tx: float,
    ty: float,
    half: float,
    cx: float,
    cy: float,
    radius: float,
) -> bool:
    """Clamp circle centre to tile rectangle and test radius."""
    nx = max(tx - half, min(cx, tx + half))
    ny = max(ty - half, min(cy, ty + half))
    return math.hypot(nx - cx, ny - cy) <= radius


def _rect_overlaps_polygon(
    tx: float,
    ty: float,
    half: float,
    verts: list[tuple[float, float]],
) -> bool:
    """Return whether a tile rectangle overlaps a polygon."""
    if _point_in_polygon(tx, ty, verts):
        return True

    for vx, vy in verts:
        if tx - half <= vx <= tx + half and ty - half <= vy <= ty + half:
            return True

    tile_edges = [
        (tx - half, ty - half, tx + half, ty - half),
        (tx + half, ty - half, tx + half, ty + half),
        (tx + half, ty + half, tx - half, ty + half),
        (tx - half, ty + half, tx - half, ty - half),
    ]
    for i, (ax, ay) in enumerate(verts):
        bx, by = verts[(i + 1) % len(verts)]
        for edge in tile_edges:
            if _segments_intersect(ax, ay, bx, by, *edge):
                return True
    return False


def _point_in_polygon(
    x: float,
    y: float,
    verts: list[tuple[float, float]],
) -> bool:
    """Ray-casting point-in-polygon test."""
    inside = False
    j = len(verts) - 1
    for i, (xi, yi) in enumerate(verts):
        xj, yj = verts[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _segments_intersect(
    ax1: float,
    ay1: float,
    ax2: float,
    ay2: float,
    bx1: float,
    by1: float,
    bx2: float,
    by2: float,
) -> bool:
    """Return whether two line segments intersect."""
    dx1 = ax2 - ax1
    dy1 = ay2 - ay1
    dx2 = bx2 - bx1
    dy2 = by2 - by1
    denom = dx1 * dy2 - dy1 * dx2
    if abs(denom) < 1e-10:
        return False
    t = ((bx1 - ax1) * dy2 - (by1 - ay1) * dx2) / denom
    u = ((bx1 - ax1) * dy1 - (by1 - ay1) * dx1) / denom
    return 0 <= t <= 1 and 0 <= u <= 1
