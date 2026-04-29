"""
Scanning template tile synthesis.
==================================
Generate tile positions from parsed geometry shapes and assign
focus points to acquisition regions.

This module operates on the output of ``parse_template_positions``
(or ``parse_rgn_geometries``) — it does not read template files
directly.

Main entry points:

    ``synthesize_tiles`` — generate tile centre coordinates for
    every geometry shape and the base grid, writing them into the
    ``acquisition_positions`` dict.

    ``assign_focus_points_to_regions`` — link each focus point to
    its nearest containing acquisition region.

Dependency direction:
    - Imports: ``math`` only (stdlib).
    - Imported by: ``__init__`` (re-export).
"""

import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Constants
# =============================================================================

# LAS X keeps tiles within ~0.5 % of the geometry boundary.
_OVERLAP_TOL = 0.005

UNASSIGNED_JOB = "(unassigned)"


# =============================================================================
# Public API — tile synthesis
# =============================================================================

def synthesize_tiles(data, tile_size_um, overlap_pct=None, job_name=None):
    """Generate tile positions from geometries and base grid.

    Takes the dict produced by ``parse_template_positions`` and
    writes computed tile centre coordinates into
    ``data["acquisition_positions"]``.

    Args:
        data: Output of ``parse_template_positions``.  Must contain
            at least ``geometries`` and ``base_grid``.
        tile_size_um: Tile edge length in um (from microscope Image
            Size setting, not from template files).
        overlap_pct: Mosaic overlap percentage.  If *None*, defaults
            to 5.0.
        job_name: Job name to assign to generated regions.  If
            *None*, uses ``"(unassigned)"``.

    Returns:
        The same *data* dict, with ``acquisition_positions`` populated.
    """
    geometries = data.get("geometries", {})
    base_grid = data.get("base_grid", [])

    if overlap_pct is None:
        viz = data.get("visualization_data", {})
        overlap_pct = viz.get("mosaic_overlap_pct", 5.0)

    if job_name is None:
        job_name = UNASSIGNED_JOB

    generated = _generate_from_geometries(geometries, tile_size_um,
                                          overlap_pct)

    positions = {}
    idx = 0

    if base_grid:
        positions[str(idx)] = _make_region(
            base_grid, tile_size_um, job_name,
            geometry_id=None, label="base grid")
        idx += 1

    for geom_id, tiles in generated.items():
        geom = geometries.get(geom_id, {})
        positions[str(idx)] = _make_region(
            tiles, tile_size_um, job_name,
            geometry_id=geom_id, label=geom.get("tag", ""))
        idx += 1

    data["acquisition_positions"] = positions
    return data


# =============================================================================
# Public API — focus point assignment
# =============================================================================

def assign_focus_points_to_regions(focus_points, regions):
    """Assign focus points to their nearest containing region.

    First checks if a focus point falls inside a region's bounding
    box.  If not, falls back to nearest region by centroid distance.

    Args:
        focus_points: List of focus point dicts (``x_um``, ``y_um``).
        regions: ``data["acquisition_positions"]`` dict.

    Returns:
        Dict ``{region_id: [focus_point_dicts]}`` — each point gets
        an ``assigned_region`` key added.
    """
    assignments = defaultdict(list)

    for fp in focus_points:
        fx, fy = fp["x_um"], fp["y_um"]
        best_rid, best_dist = None, float("inf")

        # Pass 1: prefer regions whose bounding box contains the point
        for rid, region in regions.items():
            bb = region.get("region_bounding_box")
            if bb:
                inside = (bb["x_min_um"] <= fx <= bb["x_max_um"]
                          and bb["y_min_um"] <= fy <= bb["y_max_um"])
                if inside:
                    cx = (bb["x_min_um"] + bb["x_max_um"]) / 2
                    cy = (bb["y_min_um"] + bb["y_max_um"]) / 2
                    d = math.hypot(fx - cx, fy - cy)
                    if d < best_dist:
                        best_rid, best_dist = rid, d
            else:
                positions = region.get("positions", [])
                if positions:
                    cx = sum(p["x_um"] for p in positions) / len(positions)
                    cy = sum(p["y_um"] for p in positions) / len(positions)
                    d = math.hypot(fx - cx, fy - cy)
                    if d < best_dist:
                        best_rid, best_dist = rid, d

        # Pass 2: fallback to nearest centroid if not inside any box
        if best_rid is None:
            for rid, region in regions.items():
                bb = region.get("region_bounding_box")
                if bb:
                    cx = (bb["x_min_um"] + bb["x_max_um"]) / 2
                    cy = (bb["y_min_um"] + bb["y_max_um"]) / 2
                else:
                    positions = region.get("positions", [])
                    if not positions:
                        continue
                    cx = sum(p["x_um"] for p in positions) / len(positions)
                    cy = sum(p["y_um"] for p in positions) / len(positions)
                d = math.hypot(fx - cx, fy - cy)
                if d < best_dist:
                    best_rid, best_dist = rid, d

        if best_rid is not None:
            fp_copy = fp.copy()
            fp_copy["assigned_region"] = best_rid
            assignments[best_rid].append(fp_copy)

    return dict(assignments)


# =============================================================================
# Region builder
# =============================================================================

def _make_region(tile_positions, tile_size_um, job_name, *,
                 geometry_id=None, label=""):
    """Build one ``acquisition_positions`` region entry.

    Accepts tiles as ``(x, y)`` tuples or ``{x_um, y_um}`` dicts.
    """
    h = tile_size_um / 2.0

    positions = []
    all_x, all_y = [], []
    for i, pt in enumerate(tile_positions):
        if isinstance(pt, dict):
            x, y = pt["x_um"], pt["y_um"]
        else:
            x, y = pt[0], pt[1]
        positions.append({
            "acquisition_order": i,
            "row": 0, "col": i,
            "x_um": round(x, 4), "y_um": round(y, 4), "z_um": 0.0,
            "scan_order_original": i + 1,
            "rotation": 0.0,
            "bounding_box": {
                "x_min_um": round(x - h, 4), "y_min_um": round(y - h, 4),
                "x_max_um": round(x + h, 4), "y_max_um": round(y + h, 4),
            },
        })
        all_x.append(x)
        all_y.append(y)

    region = {
        "section_x": None, "section_y": None,
        "region_row": 0, "region_col": 0,
        "job_name": job_name,
        "tile_size_um": round(tile_size_um, 4),
        "num_tiles": len(positions),
        "num_rows": 1, "num_cols": len(positions),
        "geometry_id": geometry_id,
        "positions": positions,
    }
    if all_x:
        region["region_bounding_box"] = {
            "x_min_um": round(min(all_x) - h, 4),
            "y_min_um": round(min(all_y) - h, 4),
            "x_max_um": round(max(all_x) + h, 4),
            "y_max_um": round(max(all_y) + h, 4),
        }
    return region


# =============================================================================
# Core tiling algorithm
# =============================================================================

def _grid_count(dimension, tile_size, step, tol=0.05):
    """Tiles along one axis with near-integer tolerance.

    ``ceil((dimension - tile_size) / step) + 1``, but near-integer
    values (e.g. 7.005) are rounded down to avoid an extra tile.
    """
    raw = (dimension - tile_size) / step
    frac = raw - math.floor(raw)
    n = math.floor(raw) if frac < tol else math.ceil(raw)
    return max(1, n + 1)


def _generate_from_geometries(geometries, tile_size_um, overlap_pct):
    """Generate tile centre coordinates for every geometry.

    Algorithm per geometry:
        1. Bounding box (shape-specific vertex handling).
        2. Grid count with near-integer tolerance.
        3. Centre the grid on the bounding-box centre.
        4. For non-rectangular shapes, keep tiles whose rectangle
           overlaps the geometry (with 0.5 % tolerance).

    Returns:
        Dict ``{geometry_id: [(x_um, y_um), ...]}``.
    """
    step = tile_size_um * (1.0 - overlap_pct / 100.0)
    half = tile_size_um / 2.0
    tol_half = half * (1.0 + _OVERLAP_TOL)

    results = {}

    for gid, geom in geometries.items():
        gtype = geom.get("type", "")
        raw_verts = geom.get("vertices_um", [])
        verts = [(v["x_um"], v["y_um"]) for v in raw_verts]

        if gtype in ("FocusPoint", "AutoFocusPoint"):
            continue

        if gtype == "Point":
            if verts:
                results[gid] = [verts[0]]
            continue

        if len(verts) < 2:
            continue

        # ── Bounding box ─────────────────────────────────────────
        if gtype == "CircleDiameter" and len(verts) >= 2:
            ccx = (verts[0][0] + verts[1][0]) / 2.0
            ccy = (verts[0][1] + verts[1][1]) / 2.0
            cr = math.hypot(verts[1][0] - verts[0][0],
                            verts[1][1] - verts[0][1]) / 2.0
            bb_xmin, bb_xmax = ccx - cr, ccx + cr
            bb_ymin, bb_ymax = ccy - cr, ccy + cr

        elif gtype == "Ellipse" and len(verts) >= 4:
            av = verts[:4]
            xs = [v[0] for v in av]
            ys = [v[1] for v in av]
            bb_xmin, bb_xmax = min(xs), max(xs)
            bb_ymin, bb_ymax = min(ys), max(ys)

        elif gtype == "Rectangle":
            cv = verts[:4]
            xs = [v[0] for v in cv]
            ys = [v[1] for v in cv]
            bb_xmin, bb_xmax = min(xs), max(xs)
            bb_ymin, bb_ymax = min(ys), max(ys)

        else:  # AreaLine, Polygon, MagicWand
            xs = [v[0] for v in verts]
            ys = [v[1] for v in verts]
            bb_xmin, bb_xmax = min(xs), max(xs)
            bb_ymin, bb_ymax = min(ys), max(ys)

        w = bb_xmax - bb_xmin
        h_ = bb_ymax - bb_ymin
        cx = (bb_xmin + bb_xmax) / 2.0
        cy = (bb_ymin + bb_ymax) / 2.0

        # ── Grid ─────────────────────────────────────────────────
        nx = _grid_count(w, tile_size_um, step)
        ny = _grid_count(h_, tile_size_um, step)
        start_x = cx - (nx - 1) / 2.0 * step
        start_y = cy - (ny - 1) / 2.0 * step

        # ── Fill & clip ──────────────────────────────────────────
        tiles = []
        for ix in range(nx):
            for iy in range(ny):
                tx = start_x + ix * step
                ty = start_y + iy * step

                if gtype == "Rectangle":
                    keep = True
                elif gtype == "Ellipse":
                    av = verts[:4]
                    evx = [v[0] for v in av]
                    evy = [v[1] for v in av]
                    ecx = (min(evx) + max(evx)) / 2.0
                    ecy = (min(evy) + max(evy)) / 2.0
                    esa = (max(evx) - min(evx)) / 2.0
                    esb = (max(evy) - min(evy)) / 2.0
                    keep = _rect_overlaps_ellipse(
                        tx, ty, tol_half, ecx, ecy, esa, esb)
                elif gtype == "CircleDiameter":
                    keep = _rect_overlaps_circle(
                        tx, ty, tol_half, ccx, ccy, cr)
                elif gtype in ("AreaLine", "Polygon", "MagicWand"):
                    keep = _rect_overlaps_polygon(
                        tx, ty, tol_half, verts)
                else:
                    keep = True

                if keep:
                    tiles.append((round(tx, 4), round(ty, 4)))

        results[gid] = tiles

    return results


# =============================================================================
# Geometry–rectangle overlap tests
# =============================================================================

def _rect_overlaps_ellipse(tx, ty, half, cx, cy, sa, sb):
    """Clamp ellipse centre to tile rectangle, test ellipse equation."""
    nx = max(tx - half, min(cx, tx + half))
    ny = max(ty - half, min(cy, ty + half))
    return ((nx - cx) / sa) ** 2 + ((ny - cy) / sb) ** 2 <= 1.0


def _rect_overlaps_circle(tx, ty, half, cx, cy, r):
    """Clamp circle centre to tile rectangle, test radius."""
    nx = max(tx - half, min(cx, tx + half))
    ny = max(ty - half, min(cy, ty + half))
    return math.hypot(nx - cx, ny - cy) <= r


def _rect_overlaps_polygon(tx, ty, half, verts):
    """Tile overlaps polygon: centre inside, vertex inside, or edge crossing."""
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
    n = len(verts)
    for i in range(n):
        j = (i + 1) % n
        for te in tile_edges:
            if _segments_intersect(
                    verts[i][0], verts[i][1],
                    verts[j][0], verts[j][1], *te):
                return True
    return False


def _point_in_polygon(x, y, verts):
    """Ray-casting point-in-polygon test."""
    n = len(verts)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = verts[i]
        xj, yj = verts[j]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _segments_intersect(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
    """Test whether two line segments intersect."""
    dx1, dy1 = ax2 - ax1, ay2 - ay1
    dx2, dy2 = bx2 - bx1, by2 - by1
    denom = dx1 * dy2 - dy1 * dx2
    if abs(denom) < 1e-10:
        return False
    t = ((bx1 - ax1) * dy2 - (by1 - ay1) * dx2) / denom
    u = ((bx1 - ax1) * dy1 - (by1 - ay1) * dx1) / denom
    return 0 <= t <= 1 and 0 <= u <= 1
