"""
Scan-field parsers.
===================
Parse LAS X scanning template files (.xml, .rgn, .lrp) into
structured Python dicts.

Three file types, three parser groups:

    **XML** — ``parse_acquisition_positions`` extracts tile positions
    from ``<ScanFieldData>`` elements, grouped by region.
    ``parse_matrix_settings`` extracts grid, carrier, and time-lapse
    configuration from ``<MatrixData>``.

    **RGN** — ``parse_base_grid`` extracts base grid positions
    (``AM=1`` entries).  ``parse_focus_points`` extracts focus,
    autofocus, and point markers from ``ShapeList`` items and
    ``FocusMap`` elements.  ``parse_rgn_geometries`` extracts all
    user-drawn shapes (Rectangle, Ellipse, CircleDiameter, Polygon,
    AreaLine, MagicWand, Point) with computed visualization
    properties (centers, bounding boxes, radii, semi-axes).
    ``parse_rgn_tile_colors`` extracts per-job RGBA color mappings.

    **LRP** — ``parse_lrp`` parses the full job settings tree
    (detectors, lasers, AOTFs, shutters, spectral windows, filter
    wheels, light sources, LUTs, autofocus config, z-positions, ROIs).

``parse_scan_positions`` is the main entry point that combines all
parsers into a single result dict. LAS X may store tile centres in
``<ScanFieldData>`` or store only a region shape plus grid counts. The
parser handles both canonical representations. When XML has no
job-associated tile centres, LAS X per-geometry tile-count tags are
preferred over global MatrixData counts; MatrixData is a fallback for
templates without geometry counts.

All functions are pure (no side effects, no API calls except the
optional ``client`` parameter in ``parse_scan_positions`` for tile size
resolution).

Dependency direction:
    - Imports: stdlib only (+ optional ``readers`` for tile sizes).
    - Imported by: ``__init__`` (re-export).
"""

import json
import logging
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from .planning import (
    has_lasx_tile_count_tags,
    infer_overlap_pct_from_geometry_counts,
    plan_tiles_from_geometries,
)

log = logging.getLogger(__name__)


# =============================================================================
# Type conversion helpers
# =============================================================================

UNASSIGNED_JOB = "(unassigned)"


def _to_float(s: str | None) -> float | None:
    """Convert string to float, returning None on failure."""
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(s: str | None) -> int | None:
    """Convert string to int (via float), returning None on failure."""
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


# =============================================================================
# Tile size helpers
# =============================================================================


def _parse_size_string(size_str):
    """Parse size strings like ``'290.63 um x 290.63 um'``.

    Handles micron (um), millimetre (mm), and nanometre (nm) units.

    Returns:
        Dict ``{x, y, unit}`` or None on failure.
    """
    if not size_str:
        return None
    try:
        size_str = size_str.replace("\u00c2\u00b5m", "um").replace("\u00b5m", "um")
        parts = size_str.lower().split("x")
        if len(parts) != 2:
            return None
        x_val = float("".join(c for c in parts[0].strip() if c.isdigit() or c == "."))
        y_val = float("".join(c for c in parts[1].strip() if c.isdigit() or c == "."))
        lowered = size_str.lower()
        if "nm" in lowered:
            unit = "nm"
        elif "mm" in lowered:
            unit = "mm"
        else:
            unit = "um"
        return {"x": x_val, "y": y_val, "unit": unit}
    except Exception:
        return None


def _tile_size_from_image_size_str(image_size_str):
    """Extract tile size in um from an imageSize string returned by the API."""
    info = _parse_size_string(image_size_str)
    if info is None:
        return None
    avg = (info["x"] + info["y"]) / 2.0
    if info["unit"] == "mm":
        return round(avg * 1000.0, 4)
    return round(avg, 4)


def _get_tile_sizes_from_api(client, job_names):
    """Query LAS X API for tile sizes of the given jobs.

    Args:
        client: Live LAS X CAM client.
        job_names: Iterable of job names to query.

    Returns:
        Dict ``{job_name: tile_size_um}``.
    """
    from ..readers import get_job_settings

    sizes = {}
    for jn in job_names:
        settings = get_job_settings(client, jn, mode="api")
        if settings and "imageSize" in settings:
            ts = _tile_size_from_image_size_str(settings["imageSize"])
            if ts is not None:
                sizes[jn] = ts
                log.debug("_get_tile_sizes_from_api: %s = %.1f um", jn, ts)
    return sizes


# =============================================================================
# Job names from LRP
# =============================================================================


def _get_job_names(lrp_path):
    """Extract acquisition job names from an LRP file.

    Returns a list of job names (``BlockType='1'`` blocks only).
    """
    root = ET.parse(lrp_path).getroot()
    names = []
    for block in root.findall(".//LDM_Block_Sequence_Block"):
        if block.get("BlockType") != "1":
            continue
        seq = block.find(".//LDM_Block_Sequential")
        if seq is not None:
            name = seq.get("BlockName")
            if name:
                names.append(name)
    return names


# =============================================================================
# Tile positions from XML
# =============================================================================


def _get_raw_tiles(xml_root, skip_jobs=None):
    """Extract raw tile positions from an XML root element.

    Tiles whose MainJobData has ``JobName='?'`` or ``JobId`` in
    ``(None, '-1')`` are kept but labelled with ``UNASSIGNED_JOB``.
    """
    if skip_jobs is None:
        skip_jobs = set()

    tiles = []
    for sf in xml_root.findall(".//ScanFieldData"):
        if sf.get("IsEnabled") != "true":
            continue
        mj = sf.find(".//MainJobData")
        if mj is None:
            continue

        jn = mj.get("JobName")
        jid = mj.get("JobId")
        has_job = jn and jn != "?" and jid not in (None, "-1")
        effective_job = jn if has_job else UNASSIGNED_JOB

        if has_job and jn in skip_jobs:
            continue

        ld = sf.find("LogicalData")
        ph = sf.find("PhysicalData")
        if ld is None or ph is None:
            continue

        x = _to_float(ph.get("XPosition"))
        y = _to_float(ph.get("YPosition"))
        if x is None or y is None:
            continue

        tiles.append(
            {
                "unique_id": sf.get("UniqueID"),
                "job_name": effective_job,
                "scan_order": _to_int(sf.get("ScanOrder")),
                "section_x": _to_int(ld.get("SectionX")),
                "section_y": _to_int(ld.get("SectionY")),
                "field_x": _to_int(ld.get("FieldX")),
                "field_y": _to_int(ld.get("FieldY")),
                "x_um": x,
                "y_um": y,
                "z_um": _to_float(ph.get("ZPosition")) or 0.0,
                "rotation": _to_float(sf.get("ScanRotationAngle")),
            }
        )

    return tiles


def parse_acquisition_positions(xml_root, job_tile_sizes, skip_jobs=None):
    """Parse tile positions from XML and group into regions.

    Groups tiles by ``(section_x, section_y)`` and attaches tile size
    and bounding box information when available.

    Args:
        xml_root: Parsed XML root element.
        job_tile_sizes: Dict ``{job_name: tile_size_um}``.
        skip_jobs: Optional set of job names to exclude.

    Returns:
        Dict of region dicts keyed by string index, each with::

            section_x, section_y, region_row, region_col,
            job_name, tile_size_um, num_tiles, num_rows, num_cols,
            positions (list of tile dicts)
    """
    tiles_raw = _get_raw_tiles(xml_root, skip_jobs)

    regions_raw = defaultdict(list)
    for t in tiles_raw:
        regions_raw[(t["section_x"], t["section_y"])].append(t)

    sorted_keys = sorted(regions_raw.keys(), key=lambda k: (k[1], k[0]))
    section_xs = sorted(set(k[0] for k in sorted_keys))
    section_ys = sorted(set(k[1] for k in sorted_keys))

    regions_out = {}
    for gi, key in enumerate(sorted_keys):
        sx, sy = key
        tiles = regions_raw[key]
        jn = tiles[0]["job_name"]
        ts = job_tile_sizes.get(jn)
        h = ts / 2.0 if ts is not None else 0.0

        fx_vals = sorted(set(t["field_x"] for t in tiles if t["field_x"] is not None))
        fy_vals = sorted(set(t["field_y"] for t in tiles if t["field_y"] is not None))
        ax = [t["x_um"] for t in tiles]
        ay = [t["y_um"] for t in tiles]

        tiles_sorted = sorted(tiles, key=lambda t: (t["field_y"] or 0, t["field_x"] or 0))
        positions = []
        for ao, t in enumerate(tiles_sorted):
            tr = fy_vals.index(t["field_y"]) if t["field_y"] in fy_vals else 0
            tc = fx_vals.index(t["field_x"]) if t["field_x"] in fx_vals else 0
            pos_entry = {
                "acquisition_order": ao,
                "row": tr,
                "col": tc,
                "x_um": round(t["x_um"], 4),
                "y_um": round(t["y_um"], 4),
                "z_um": round(t["z_um"], 4),
                "scan_order_original": t["scan_order"],
                "rotation": t["rotation"],
            }
            if ts is not None:
                pos_entry["bounding_box"] = {
                    "x_min_um": round(t["x_um"] - h, 4),
                    "y_min_um": round(t["y_um"] - h, 4),
                    "x_max_um": round(t["x_um"] + h, 4),
                    "y_max_um": round(t["y_um"] + h, 4),
                }
            positions.append(pos_entry)

        region_entry = {
            "section_x": sx,
            "section_y": sy,
            "region_row": section_ys.index(sy),
            "region_col": section_xs.index(sx),
            "job_name": jn,
            "tile_size_um": round(ts, 4) if ts is not None else None,
            "num_tiles": len(positions),
            "num_rows": len(fy_vals),
            "num_cols": len(fx_vals),
            "positions": positions,
        }
        if ts is not None:
            region_entry["region_bounding_box"] = {
                "x_min_um": round(min(ax) - h, 4),
                "y_min_um": round(min(ay) - h, 4),
                "x_max_um": round(max(ax) + h, 4),
                "y_max_um": round(max(ay) + h, 4),
            }
        regions_out[str(gi)] = region_entry

    return regions_out


# =============================================================================
# Tile positions from RGN geometry + MatrixData
# =============================================================================


def _axis_grid(min_um, max_um, count):
    """Return evenly spaced coordinates including both bounds."""
    if count <= 0:
        return []
    if count == 1:
        return [round((min_um + max_um) / 2.0, 4)]
    step = (max_um - min_um) / (count - 1)
    return [round(min_um + i * step, 4) for i in range(count)]


def _geometry_bbox(geom):
    """Return ``(x_min, y_min, x_max, y_max)`` for a parsed geometry."""
    bb = geom.get("bounding_box_um")
    if bb:
        return (
            bb["x_min_um"],
            bb["y_min_um"],
            bb["x_max_um"],
            bb["y_max_um"],
        )

    vertices = geom.get("vertices_um", [])
    if not vertices:
        return None
    xs = [v["x_um"] for v in vertices]
    ys = [v["y_um"] for v in vertices]
    return min(xs), min(ys), max(xs), max(ys)


def _region_job_name(geom, job_tile_sizes, default_job_name):
    """Choose the job label for a geometry-derived region."""
    candidates = [
        geom.get("label"),
        geom.get("tag"),
        default_job_name,
        UNASSIGNED_JOB,
    ]
    for candidate in candidates:
        if candidate and candidate in job_tile_sizes:
            return candidate
    return default_job_name or UNASSIGNED_JOB


def _derive_positions_from_geometry_grid(
    geometries,
    matrix_settings,
    job_tile_sizes,
    *,
    default_job_name=None,
):
    """Derive tile centres from LAS X region geometry and grid counts.

    Matrix Screener can persist a rectangular scan field as an RGN geometry plus
    ``MatrixData/CountOfData`` without writing individual
    ``<ScanFieldData>`` entries. In that shape the RGN/XML pair is the
    authoritative source: the region geometry gives the envelope and
    ``ScanFieldsX/Y`` gives the grid cardinality.
    """
    count = matrix_settings.get("count") or {}
    n_cols = count.get("scanFieldsX")
    n_rows = count.get("scanFieldsY")
    if not n_cols or not n_rows:
        return {}

    regions = {}
    region_index = 0
    for geom_id, geom in geometries.items():
        if geom.get("type") != "Rectangle":
            log.debug(
                "Skipping non-Rectangle geometry %r (type=%s); only "
                "Rectangle scan-field derivation is supported",
                geom_id,
                geom.get("type"),
            )
            continue

        bbox = _geometry_bbox(geom)
        if bbox is None:
            continue
        x_min, y_min, x_max, y_max = bbox
        xs = _axis_grid(float(x_min), float(x_max), int(n_cols))
        ys = _axis_grid(float(y_min), float(y_max), int(n_rows))
        if not xs or not ys:
            continue

        job_name = _region_job_name(geom, job_tile_sizes, default_job_name)
        tile_size = job_tile_sizes.get(job_name)
        half = tile_size / 2.0 if tile_size is not None else 0.0

        positions = []
        for row, y_um in enumerate(ys):
            for col, x_um in enumerate(xs):
                order = row * len(xs) + col
                entry = {
                    "acquisition_order": order,
                    "row": row,
                    "col": col,
                    "x_um": x_um,
                    "y_um": y_um,
                    "z_um": 0.0,
                    "scan_order_original": order + 1,
                    "rotation": matrix_settings.get("fieldRotation"),
                    "source": "rgn_matrix",
                }
                if tile_size is not None:
                    entry["bounding_box"] = {
                        "x_min_um": round(x_um - half, 4),
                        "y_min_um": round(y_um - half, 4),
                        "x_max_um": round(x_um + half, 4),
                        "y_max_um": round(y_um + half, 4),
                    }
                positions.append(entry)

        region = {
            "section_x": 0,
            "section_y": region_index,
            "region_row": region_index,
            "region_col": 0,
            "job_name": job_name,
            "tile_size_um": round(tile_size, 4) if tile_size is not None else None,
            "num_tiles": len(positions),
            "num_rows": len(ys),
            "num_cols": len(xs),
            "geometry_id": geom_id,
            "source": "rgn_matrix",
            "positions": positions,
        }
        if tile_size is not None:
            ax = [p["x_um"] for p in positions]
            ay = [p["y_um"] for p in positions]
            region["region_bounding_box"] = {
                "x_min_um": round(min(ax) - half, 4),
                "y_min_um": round(min(ay) - half, 4),
                "x_max_um": round(max(ax) + half, 4),
                "y_max_um": round(max(ay) + half, 4),
            }
        regions[str(region_index)] = region
        region_index += 1

    return regions


# =============================================================================
# Base grid positions from RGN
# =============================================================================


def parse_base_grid(rgn_path):
    """Parse base grid tile positions from an RGN file.

    These are ``ScanFieldArray`` positions (``AM=1`` in the JSON
    ``Name`` field) that exist regardless of geometry shapes.

    Args:
        rgn_path: Path to the ``.rgn`` file.

    Returns:
        List of ``{x_um, y_um}`` dicts (deduplicated).
    """
    rgn_path = Path(rgn_path)
    if not rgn_path.is_file():
        return []

    root = ET.parse(rgn_path).getroot()
    grid = []
    seen = set()

    for item in root.findall(".//ShapeList/Items/*"):
        name_text = item.findtext("Name") or item.findtext("n") or ""
        if not name_text.startswith("{"):
            continue
        try:
            meta = json.loads(name_text)
        except (json.JSONDecodeError, ValueError):
            continue
        if meta.get("AM") != 1:
            continue

        v0 = item.find("Verticies/Items/Item0")
        if v0 is not None:
            x = _to_float(v0.findtext("X"))
            y = _to_float(v0.findtext("Y"))
            if x is not None and y is not None:
                x_um = round(x * 1e6, 4)
                y_um = round(y * 1e6, 4)
                key = (round(x_um, 1), round(y_um, 1))
                if key not in seen:
                    seen.add(key)
                    grid.append({"x_um": x_um, "y_um": y_um})

    return grid


# =============================================================================
# Focus points from RGN
# =============================================================================


def parse_focus_points(rgn_path):
    """Parse focus points and autofocus points from an RGN file.

    Reads both ``ShapeList/Items`` entries (``Type`` = FocusPoint or
    AutoFocusPoint) and ``FocusMap/FocusPoint`` elements.

    Args:
        rgn_path: Path to the ``.rgn`` file.

    Returns:
        ``(focus_points, autofocus_points)`` — each a list of dicts::

            identifier, tag, type,
            x_um, y_um, z_um, enabled
    """
    rgn_path = Path(rgn_path)
    if not rgn_path.is_file():
        return [], []

    root = ET.parse(rgn_path).getroot()
    focus_points = []
    autofocus_points = []
    seen_ids = set()

    for item in root.findall(".//ShapeList/Items/*"):
        type_elem = item.find("Type")
        if type_elem is None:
            continue
        shape_type = type_elem.text
        if shape_type not in ("FocusPoint", "AutoFocusPoint"):
            continue

        ident = (item.findtext("Identifier") or "").strip()
        if not ident or ident in seen_ids:
            continue
        seen_ids.add(ident)

        tag = item.findtext("Tag") or ""
        verts = item.find(".//Verticies/Items")
        if verts is None:
            continue
        v0 = verts.find("Item0")
        if v0 is None:
            continue

        x = _to_float(v0.findtext("X"))
        y = _to_float(v0.findtext("Y"))
        z = _to_float(v0.findtext("Z")) or 0.0
        if x is None or y is None:
            continue

        point = {
            "identifier": ident,
            "tag": tag,
            "type": shape_type,
            "x_um": round(x * 1e6, 4),
            "y_um": round(y * 1e6, 4),
            "z_um": round(z * 1e6, 4),
            "enabled": True,
        }
        if shape_type == "AutoFocusPoint":
            autofocus_points.append(point)
        else:
            focus_points.append(point)

    for fp_elem in root.findall(".//FocusMap/FocusPoint"):
        ident = fp_elem.get("Identifier")
        if not ident or ident in seen_ids:
            continue
        seen_ids.add(ident)

        x = _to_float(fp_elem.get("X"))
        y = _to_float(fp_elem.get("Y"))
        z = _to_float(fp_elem.get("Z")) or 0.0
        enabled = fp_elem.get("Enabled", "true").lower() == "true"
        if x is None or y is None:
            continue

        focus_points.append(
            {
                "identifier": ident,
                "tag": "",
                "type": "FocusPoint",
                "x_um": round(x * 1e6, 4),
                "y_um": round(y * 1e6, 4),
                "z_um": round(z * 1e6, 4),
                "enabled": enabled,
            }
        )

    return focus_points, autofocus_points


# =============================================================================
# Geometries from RGN
# =============================================================================


def parse_rgn_geometries(rgn_path):
    """Parse user-drawn geometry shapes from an RGN file.

    Extracts all ``AM=0`` shapes from ``ShapeList/Items`` (these are
    the user-drawn regions in Navigator Expert).  ``AM=1`` entries
    (base grid) and ``FocusPoint``/``AutoFocusPoint`` items are
    excluded — those are handled by ``parse_base_grid`` and
    ``parse_focus_points`` respectively.

    Each geometry includes raw vertices (in um) plus shape-specific
    derived properties for visualization:

    - **Ellipse**: ``center_um``, ``semi_axis_a_um``, ``semi_axis_b_um``
    - **CircleDiameter**: ``center_um``, ``radius_um``
    - **Rectangle**: ``center_um``, ``bounding_box_um``
    - **Polygon / AreaLine / MagicWand**: ``centroid_um``, ``bounding_box_um``
    - **Point**: ``center_um``

    Args:
        rgn_path: Path to the ``.rgn`` file.

    Returns:
        Dict keyed by shape identifier, each value a geometry dict.
    """
    rgn_path = Path(rgn_path)
    if not rgn_path.is_file():
        return {}

    root = ET.parse(rgn_path).getroot()
    geometries = {}

    for item in root.findall(".//ShapeList/Items/*"):
        type_elem = item.find("Type")
        if type_elem is None:
            continue
        stype = type_elem.text
        if stype in ("FocusPoint", "AutoFocusPoint"):
            continue

        # Only AM=0 entries are actual geometries.
        # AM=1 entries are base grid (ScanFieldArray) tile positions.
        name_text = item.findtext("Name") or item.findtext("n") or ""
        if name_text.startswith("{"):
            try:
                meta = json.loads(name_text)
                if meta.get("AM") != 0:
                    continue
            except (json.JSONDecodeError, ValueError):
                pass

        ident = (item.findtext("Identifier") or "").strip()
        if not ident:
            continue

        vertices = []
        vert_items = item.find(".//Verticies/Items")
        if vert_items is not None:
            for vi in vert_items:
                x = _to_float(vi.findtext("X"))
                y = _to_float(vi.findtext("Y"))
                if x is not None and y is not None:
                    vertices.append(
                        {
                            "x_um": round(x * 1e6, 4),
                            "y_um": round(y * 1e6, 4),
                        }
                    )

        geom = {
            "type": stype,
            "vertices_um": vertices,
            "label": item.findtext("LabelText"),
            "tag": item.findtext("Tag"),
            "tile_color_raw": item.findtext("TileColor"),
        }

        if stype == "Ellipse" and len(vertices) >= 4:
            x0, y0 = vertices[0]["x_um"], vertices[0]["y_um"]
            x1, y1 = vertices[1]["x_um"], vertices[1]["y_um"]
            x2, y2 = vertices[2]["x_um"], vertices[2]["y_um"]
            x3, y3 = vertices[3]["x_um"], vertices[3]["y_um"]
            geom["center_um"] = {
                "x_um": round((x0 + x1) / 2, 4),
                "y_um": round((y0 + y1) / 2, 4),
            }
            geom["semi_axis_a_um"] = round(math.hypot(x1 - x0, y1 - y0) / 2, 4)
            geom["semi_axis_b_um"] = round(math.hypot(x2 - x3, y2 - y3) / 2, 4)

        elif stype == "CircleDiameter" and len(vertices) >= 2:
            x0, y0 = vertices[0]["x_um"], vertices[0]["y_um"]
            x1, y1 = vertices[1]["x_um"], vertices[1]["y_um"]
            geom["center_um"] = {
                "x_um": round((x0 + x1) / 2, 4),
                "y_um": round((y0 + y1) / 2, 4),
            }
            geom["radius_um"] = round(math.hypot(x1 - x0, y1 - y0) / 2, 4)

        elif stype == "Rectangle" and len(vertices) >= 4:
            xs = [v["x_um"] for v in vertices[:4]]
            ys = [v["y_um"] for v in vertices[:4]]
            geom["bounding_box_um"] = {
                "x_min_um": round(min(xs), 4),
                "y_min_um": round(min(ys), 4),
                "x_max_um": round(max(xs), 4),
                "y_max_um": round(max(ys), 4),
                "width_um": round(max(xs) - min(xs), 4),
                "height_um": round(max(ys) - min(ys), 4),
            }
            geom["center_um"] = {
                "x_um": round((min(xs) + max(xs)) / 2, 4),
                "y_um": round((min(ys) + max(ys)) / 2, 4),
            }

        elif stype in ("AreaLine", "Polygon", "MagicWand") and len(vertices) >= 3:
            xs = [v["x_um"] for v in vertices]
            ys = [v["y_um"] for v in vertices]
            geom["bounding_box_um"] = {
                "x_min_um": round(min(xs), 4),
                "y_min_um": round(min(ys), 4),
                "x_max_um": round(max(xs), 4),
                "y_max_um": round(max(ys), 4),
            }
            geom["centroid_um"] = {
                "x_um": round(sum(xs) / len(xs), 4),
                "y_um": round(sum(ys) / len(ys), 4),
            }

        elif stype == "Point" and len(vertices) >= 1:
            geom["center_um"] = {
                "x_um": vertices[0]["x_um"],
                "y_um": vertices[0]["y_um"],
            }

        geometries[ident] = geom

    return geometries


# =============================================================================
# Tile colors from RGN
# =============================================================================


def parse_rgn_tile_colors(rgn_path):
    """Extract per-job tile colors from an RGN file.

    Parses the ``TileColor`` field (``R:255,G:128,B:64,A:100``
    format) and associates it with the job name from the JSON
    ``Name`` metadata (``JN`` key) or the ``LabelText`` fallback.

    Args:
        rgn_path: Path to the ``.rgn`` file.

    Returns:
        Dict ``{job_name: (r, g, b, a)}`` with values normalised
        to 0.0–1.0.
    """
    rgn_path = Path(rgn_path)
    if not rgn_path.is_file():
        return {}

    root = ET.parse(rgn_path).getroot()
    job_colors = {}

    for item in root.findall(".//ShapeList/Items/*"):
        name_text = item.findtext("n") or ""
        tile_color = item.findtext("TileColor") or ""
        label_text = item.findtext("LabelText") or ""

        jn = None
        if name_text.startswith("{"):
            try:
                nd = json.loads(name_text)
                jn = nd.get("JN", "")
            except (json.JSONDecodeError, ValueError):
                pass

        if not jn and label_text:
            jn = label_text

        if jn and tile_color and jn not in job_colors:
            try:
                parts = {}
                for part in tile_color.split(","):
                    part = part.strip()
                    if ":" in part:
                        k, v = part.split(":", 1)
                        parts[k.strip()] = int(v.strip())
                r = parts.get("R", 128)
                g = parts.get("G", 128)
                b = parts.get("B", 128)
                a = parts.get("A", 100)
                job_colors[jn] = (r / 255.0, g / 255.0, b / 255.0, a / 100.0)
            except (ValueError, TypeError):
                pass

    return job_colors


# =============================================================================
# Matrix settings from XML
# =============================================================================


def parse_matrix_settings(xml_root):
    """Parse matrix configuration from the XML ``<MatrixData>`` element.

    Extracts grid counts, distance/spacing data, carrier type,
    time-lapse settings, autofocus mode, and field rotation.

    Args:
        xml_root: Parsed XML root element.

    Returns:
        Dict with optional keys: ``count``, ``distances``,
        ``carrier``, ``timeLapse``, ``autofocus``, ``fieldRotation``.
        Empty dict if no ``<MatrixData>`` element exists.
    """
    md = xml_root.find(".//MatrixData") if xml_root is not None else None
    if md is None:
        return {}

    result = {}

    cod = md.find("CountOfData")
    if cod is not None and cod.get("IsEnabled") == "true":
        result["count"] = {
            "sectionsX": _to_int(cod.get("SectionsX")),
            "sectionsY": _to_int(cod.get("SectionsY")),
            "scanFieldsX": _to_int(cod.get("ScanFieldsX")),
            "scanFieldsY": _to_int(cod.get("ScanFieldsY")),
            "regionsX": _to_int(cod.get("RegionsX")),
            "regionsY": _to_int(cod.get("RegionsY")),
            "samplesX": _to_int(cod.get("SamplesX")),
            "samplesY": _to_int(cod.get("SamplesY")),
        }

    dd = md.find("DistanceData")
    if dd is not None and dd.get("IsEnabled") == "true":
        dist = {}
        origin = dd.find("Origin")
        if origin is not None and origin.get("IsEnabled") == "true":
            dist["origin"] = {
                "x_um": _to_float(origin.get("OriginX")),
                "y_um": _to_float(origin.get("OriginY")),
                "z_um": _to_float(origin.get("OriginZ")),
                "unit": origin.get("Units", "Microns"),
            }
        for name in ("Section", "Field", "Region", "Sample"):
            elem = dd.find(name)
            if elem is not None and elem.get("IsEnabled") == "true":
                dist[name.lower()] = {
                    "distanceX_um": _to_float(elem.get("DistanceX")),
                    "distanceY_um": _to_float(elem.get("DistanceY")),
                    "distanceZ_um": _to_float(elem.get("DistanceZ")),
                    "unit": elem.get("Units", "Microns"),
                }
        result["distances"] = dist

    cd = md.find("CarrierData")
    if cd is not None and cd.get("IsEnabled") == "true":
        carrier = {
            "description1": cd.get("Description1", ""),
            "description2": cd.get("Description2", ""),
            "rotationAngle": _to_float(cd.get("RotationAngle")),
        }
        carrier_types = {
            "WellPlateTypeSelected": ("WellPlate", "SelectedWellplateTypeIndex"),
            "SlideTypeSelected": ("Slide", "SelectedGlassTypeIndex"),
            "DishTypeSelected": ("Dish", "SelectedDishTypeIndex"),
            "ChamberSlideTypeSelected": ("ChamberSlide", "SelectedChamberSlideTypeIndex"),
            "SingleGridCartridgeTypeSelected": ("SingleGridCartridge", "SelectedGridTypeIndex"),
            "AutoGridCartridgeTypeSelected": ("AutoGridCartridge", "SelectedGridTypeIndex"),
        }
        for attr, (ctype, idx_attr) in carrier_types.items():
            if cd.get(attr) == "true":
                carrier["type"] = ctype
                carrier["selectedIndex"] = _to_int(cd.get(idx_attr))
                break
        result["carrier"] = carrier

    tld = md.find("TimeLapseData")
    if tld is not None and tld.get("IsEnabled") == "true":
        result["timeLapse"] = {
            "repeatLoops": _to_int(tld.get("RepeatLoops")),
            "repeatTimeDays": _to_int(tld.get("RepeatTimeDays")),
            "repeatTimeHours": _to_int(tld.get("RepeatTimeHours")),
            "repeatTimeMinutes": _to_int(tld.get("RepeatTimeMinutes")),
            "runTime": tld.get("RunTime", ""),
        }

    afd = md.find("AutofocusData")
    if afd is not None:
        result["autofocus"] = {
            "zUseMode": afd.get("ZUseMode", ""),
            "forecastMode": _to_int(afd.get("AFForecastMode")),
        }

    cfd = md.find("ConfocalData")
    if cfd is not None:
        rot = _to_float(cfd.get("FieldRotation"))
        if rot is not None:
            result["fieldRotation"] = rot

    overlap = xml_root.find(".//ArrayFilledRandom/FilledData/MosaicOverlapInPercent")
    if overlap is not None:
        value = _to_float(overlap.text)
        if value is not None:
            result["mosaicOverlapPct"] = value

    return result


# =============================================================================
# Combined template position parser
# =============================================================================


def parse_scan_positions(
    templates_dir,
    template_base,
    *,
    client=None,
    tile_size_um=None,
    default_job_name=None,
    overlap_pct=None,
):
    """Parse all position data from a scanning template.

    Tile sizes are resolved in priority order:

    1. **API** — if ``client`` is provided, query LAS X for each job's
       ``imageSize``.
    2. **Manual** — ``tile_size_um`` fills in any jobs not resolved by
       the API and is used for unassigned tiles.
    3. **Fallback** — unassigned tiles get the first available tile
       size (from API or manual).

    Args:
        templates_dir: Path to the ScanningTemplates folder.
        template_base: Base name without extension
            (e.g. ``"{ScanningTemplate}_PythonInspect"``).
        client: Optional live LAS X CAM client for tile size queries.
        tile_size_um: Optional manual tile size in um.
        default_job_name: Job to use for geometry-derived scan fields
            when the XML contains only unassigned placeholders.
        overlap_pct: Optional manual overlap for geometry-derived scan
            fields. If omitted, LAS X geometry count labels are used to
            infer the overlap when possible.

    Returns:
        Dict with::

            acquisition_positions — dict of regions
            base_grid             — list of grid positions
            focus_points          — list of focus/point markers
            autofocus_points      — list of autofocus points
            geometries            — dict of user-drawn shapes
            matrix_settings       — grid/carrier/time-lapse config
            visualization_data    — tile colors, job tile sizes
    """
    d = Path(templates_dir)
    xml_path = d / (template_base + ".xml")
    lrp_path = d / (template_base + ".lrp")
    rgn_path = d / (template_base + ".rgn")

    xml_root = ET.parse(xml_path).getroot() if xml_path.is_file() else None

    job_names = _get_job_names(lrp_path) if lrp_path.is_file() else []
    if default_job_name is not None and default_job_name not in job_names:
        job_names.append(default_job_name)

    job_tile_sizes = {}

    if client is not None:
        api_sizes = _get_tile_sizes_from_api(client, job_names)
        job_tile_sizes.update(api_sizes)

    if tile_size_um is not None:
        for jn in job_names:
            if jn not in job_tile_sizes:
                job_tile_sizes[jn] = tile_size_um
        if default_job_name is not None and default_job_name not in job_tile_sizes:
            job_tile_sizes[default_job_name] = tile_size_um
        if UNASSIGNED_JOB not in job_tile_sizes:
            job_tile_sizes[UNASSIGNED_JOB] = tile_size_um

    if UNASSIGNED_JOB not in job_tile_sizes and job_tile_sizes:
        job_tile_sizes[UNASSIGNED_JOB] = next(iter(job_tile_sizes.values()))

    base_grid = parse_base_grid(rgn_path) if rgn_path.is_file() else []
    focus_points, autofocus_points = (
        parse_focus_points(rgn_path) if rgn_path.is_file() else ([], [])
    )
    geometries = parse_rgn_geometries(rgn_path) if rgn_path.is_file() else {}
    tile_colors = parse_rgn_tile_colors(rgn_path) if rgn_path.is_file() else {}
    matrix_settings = parse_matrix_settings(xml_root) if xml_root is not None else {}

    acquisition_positions = {}
    if xml_root is not None:
        acquisition_positions = parse_acquisition_positions(xml_root, job_tile_sizes)
    only_unassigned = _only_unassigned_positions(acquisition_positions)

    if not acquisition_positions or only_unassigned:
        acquisition_positions = _derive_missing_acquisition_positions(
            geometries,
            base_grid,
            matrix_settings,
            job_tile_sizes,
            default_job_name=default_job_name,
            overlap_pct=overlap_pct,
        )

    return {
        "acquisition_positions": acquisition_positions,
        "base_grid": base_grid,
        "focus_points": focus_points,
        "autofocus_points": autofocus_points,
        "geometries": geometries,
        "matrix_settings": matrix_settings,
        "visualization_data": {
            "tile_colors": tile_colors,
            "job_tile_sizes": job_tile_sizes,
        },
    }


def _only_unassigned_positions(acquisition_positions):
    """Return whether parsed XML positions are all unassigned placeholders."""
    if not acquisition_positions:
        return False
    return all(
        region.get("job_name") == UNASSIGNED_JOB for region in acquisition_positions.values()
    )


def _derive_missing_acquisition_positions(
    geometries,
    base_grid,
    matrix_settings,
    job_tile_sizes,
    *,
    default_job_name,
    overlap_pct=None,
):
    """Derive positions when XML lacks job-associated scan fields."""
    if default_job_name is not None and has_lasx_tile_count_tags(geometries):
        return _plan_positions_from_geometries(
            geometries,
            base_grid,
            matrix_settings,
            job_tile_sizes,
            default_job_name=default_job_name,
            overlap_pct=overlap_pct,
        )

    matrix_positions = _derive_positions_from_geometry_grid(
        geometries,
        matrix_settings,
        job_tile_sizes,
        default_job_name=default_job_name,
    )
    if matrix_positions:
        return matrix_positions

    if default_job_name is not None:
        return _plan_positions_from_geometries(
            geometries,
            base_grid,
            matrix_settings,
            job_tile_sizes,
            default_job_name=default_job_name,
            overlap_pct=overlap_pct,
        )
    return {}


def _plan_positions_from_geometries(
    geometries,
    base_grid,
    matrix_settings,
    job_tile_sizes,
    *,
    default_job_name,
    overlap_pct=None,
):
    """Plan acquisition positions from RGN geometry for one job."""
    tile_size = job_tile_sizes.get(default_job_name)
    if tile_size is None and job_tile_sizes:
        tile_size = next(iter(job_tile_sizes.values()))
    if tile_size is None:
        return {}

    fallback_overlap = matrix_settings.get("mosaicOverlapPct", 5.0)
    overlap = (
        float(overlap_pct)
        if overlap_pct is not None
        else infer_overlap_pct_from_geometry_counts(
            geometries,
            tile_size,
            fallback=fallback_overlap,
        )
    )
    return plan_tiles_from_geometries(
        geometries,
        tile_size,
        base_grid=base_grid,
        overlap_pct=overlap,
        job_name=default_job_name,
    )


# =============================================================================
# LRP parser — ATLConfocalSettingDefinition children
# =============================================================================


def _parse_beam_route(el):
    """Extract BeamRoute positions from an element.

    Returns list of ``{BeamPositionLevel, BeamPosition}`` dicts,
    or None if no BeamRoute child exists.
    """
    br = el.find("BeamRoute")
    if br is None:
        return None
    positions = []
    for bp in br.findall("BeamPosition"):
        positions.append(dict(bp.attrib))
    return positions or None


def _parse_detector(det_el):
    """Parse a Detector element with all children."""
    d = dict(det_el.attrib)
    beam = _parse_beam_route(det_el)
    if beam is not None:
        d["_BeamRoute"] = beam
    ica = det_el.find("ImageChannelArray")
    if ica is not None:
        channels = []
        for ic in ica:
            channels.append(dict(ic.attrib))
        if channels:
            d["_ImageChannels"] = channels
    tau = det_el.find("TauScanDef")
    if tau is not None:
        d["_TauScanDef"] = dict(tau.attrib)
    drl = det_el.find("DetectionReferenceLine")
    if drl is not None:
        d["_DetectionReferenceLine"] = dict(drl.attrib)
    lut = det_el.find("LutInfo")
    if lut is not None:
        d["_LutInfo"] = dict(lut.attrib)
    return d


def _parse_laser(laser_el):
    """Parse a Laser element with BeamRoute."""
    d = dict(laser_el.attrib)
    beam = _parse_beam_route(laser_el)
    if beam is not None:
        d["_BeamRoute"] = beam
    return d


def _parse_aotf(aotf_el):
    """Parse an Aotf element with BeamRoute and LaserLineSettings."""
    d = dict(aotf_el.attrib)
    beam = _parse_beam_route(aotf_el)
    if beam is not None:
        d["_BeamRoute"] = beam
    lines = []
    for lls in aotf_el.findall("LaserLineSetting"):
        ld = dict(lls.attrib)
        lbeam = _parse_beam_route(lls)
        if lbeam is not None:
            ld["_BeamRoute"] = lbeam
        lines.append(ld)
    if lines:
        d["_LaserLines"] = lines
    return d


def _parse_shutter(shutter_el):
    """Parse a Shutter element with BeamRoute."""
    d = dict(shutter_el.attrib)
    beam = _parse_beam_route(shutter_el)
    if beam is not None:
        d["_BeamRoute"] = beam
    return d


def _parse_multiband(mb_el):
    """Parse a MultiBand (spectral window) element with BeamRoute."""
    d = dict(mb_el.attrib)
    beam = _parse_beam_route(mb_el)
    if beam is not None:
        d["_BeamRoute"] = beam
    return d


def _parse_filter_wheel(fw_el):
    """Parse FilterWheel with Wheel children, BeamRoutes, and WheelNames."""
    d = dict(fw_el.attrib)
    wheels = []
    for w in fw_el.findall("Wheel"):
        wd = dict(w.attrib)
        beam = _parse_beam_route(w)
        if beam is not None:
            wd["_BeamRoute"] = beam
        names = [wn.get("FilterName", "") for wn in w.findall("WheelName")]
        if names:
            wd["_WheelNames"] = names
        wheels.append(wd)
    if wheels:
        d["_Wheels"] = wheels
    return d


def _parse_light_source(ls_el):
    """Parse a LightSourceSetting element with children."""
    d = dict(ls_el.attrib)
    beam = _parse_beam_route(ls_el)
    if beam is not None:
        d["_BeamRoute"] = beam
    lbd = ls_el.find("LinesBlockedForDyeAssistant")
    if lbd is not None:
        blocked = []
        for lb in lbd.findall("LineBlocked"):
            blocked.append(dict(lb.attrib))
        if blocked:
            d["_LinesBlocked"] = blocked
    return d


def _parse_lut(lut_el):
    """Parse a LUT element with BeamRoute."""
    d = dict(lut_el.attrib)
    beam = _parse_beam_route(lut_el)
    if beam is not None:
        d["_BeamRoute"] = beam
    return d


def _parse_setting(setting_el):
    """Parse an ATLConfocalSettingDefinition and all children.

    Child dicts that represent parsed sub-elements are prefixed with
    ``_`` to distinguish them from XML attributes.
    """
    result = {"attrs": dict(setting_el.attrib)}

    det_list = setting_el.find("DetectorList")
    if det_list is not None:
        result["_DetectorList_attrs"] = dict(det_list.attrib)
        detectors = []
        for det in det_list.findall("Detector"):
            detectors.append(_parse_detector(det))
        if detectors:
            result["_Detectors"] = detectors

    la = setting_el.find("LaserArray")
    if la is not None:
        lasers = []
        for laser in la.findall("Laser"):
            lasers.append(_parse_laser(laser))
        if lasers:
            result["_Lasers"] = lasers

    al = setting_el.find("AotfList")
    if al is not None:
        aotfs = []
        for aotf in al.findall("Aotf"):
            aotfs.append(_parse_aotf(aotf))
        if aotfs:
            result["_Aotfs"] = aotfs

    sl = setting_el.find("ShutterList")
    if sl is not None:
        shutters = []
        for sh in sl.findall("Shutter"):
            shutters.append(_parse_shutter(sh))
        if shutters:
            result["_Shutters"] = shutters

    spectro = setting_el.find("Spectro")
    if spectro is not None:
        multibands = []
        for mb in spectro.findall("MultiBand"):
            multibands.append(_parse_multiband(mb))
        if multibands:
            result["_MultiBands"] = multibands

    fw = setting_el.find("FilterWheel")
    if fw is not None:
        result["_FilterWheel"] = _parse_filter_wheel(fw)

    lsl = setting_el.find("LightSourceList")
    if lsl is not None:
        sources = []
        for ls in lsl.findall("LightSourceSetting"):
            sources.append(_parse_light_source(ls))
        if sources:
            result["_LightSources"] = sources

    lut_list = setting_el.find("LUT_List")
    if lut_list is not None:
        luts = []
        for lut in lut_list.findall("LUT"):
            luts.append(_parse_lut(lut))
        if luts:
            result["_LUTs"] = luts

    af = setting_el.find("Autofocus-config")
    if af is not None:
        result["_AutofocusConfig"] = dict(af.attrib)

    azpl = setting_el.find("AdditionalZPositionList")
    if azpl is not None:
        zpositions = []
        for azp in azpl.findall("AdditionalZPosition"):
            zpositions.append(dict(azp.attrib))
        if zpositions:
            result["_AdditionalZPositions"] = zpositions

    roi = setting_el.find("ROI")
    if roi is not None:
        roi_singles = []
        for rs in roi.findall(".//ROISingle"):
            rd = dict(rs.attrib)
            vertices = []
            verts_el = rs.find("Vertices")
            if verts_el is not None:
                # LAS X exports ROI vertices as child elements with X/Y attrs.
                for v in verts_el:
                    vd = {}
                    vx = _to_float(v.get("X"))
                    vy = _to_float(v.get("Y"))
                    if vx is not None:
                        vd["X"] = vx
                    if vy is not None:
                        vd["Y"] = vy
                    if vd:
                        vertices.append(vd)
            if vertices:
                rd["_Vertices"] = vertices
            transform = rs.find("Transformation")
            if transform is not None:
                td = dict(transform.attrib)
                scaling = transform.find("Scaling")
                if scaling is not None:
                    td.update(dict(scaling.attrib))
                translation = transform.find("Translation")
                if translation is not None:
                    td["TranslationX"] = translation.get("X", "0")
                    td["TranslationY"] = translation.get("Y", "0")
                rd["_Transformation"] = td
            roi_singles.append(rd)
        if roi_singles:
            result["_ROIs"] = roi_singles

    ods = setting_el.find("OnlineDyeSeparation")
    if ods is not None:
        result["_OnlineDyeSeparation"] = dict(ods.attrib)

    sted = setting_el.find("STED_DepletionLine")
    if sted is not None:
        d = dict(sted.attrib)
        beam = _parse_beam_route(sted)
        if beam is not None:
            d["_BeamRoute"] = beam
        result["_STED"] = d

    gsp = setting_el.find("GalvoSwitchParameter")
    if gsp is not None:
        result["_GalvoSwitch"] = dict(gsp.attrib)

    spim = setting_el.find("SpimCACompensationParameter")
    if spim is not None:
        result["_SpimCA"] = dict(spim.attrib)

    vbe = setting_el.find("VariableBeamExpanderFactors")
    if vbe is not None:
        result["_BeamExpander"] = dict(vbe.attrib)

    return result


def _parse_sequence_element(el):
    """Parse an LDM_Block_Sequence_Element (execution order entry)."""
    return dict(el.attrib)


# =============================================================================
# LRP full parser
# =============================================================================


def parse_lrp(lrp_path):
    """Parse an LRP file into a structured dict organized by job.

    Returns::

        {
            "sequence_name": str,
            "sequence_elements": [...],
            "jobs": {
                "AF Job": {
                    "block_attrs": {...},
                    "sequential_attrs": {...},
                    "Master":     { "attrs": {...}, "_Detectors": [...], ... },
                    "Sequential": { "attrs": {...}, "_Detectors": [...], ... },
                    "AutoFocus":  { "attrs": {...}, "_Detectors": [...], ... },
                },
                ...
            }
        }

    Parsed sub-element keys are prefixed with ``_`` (e.g. ``_Detectors``,
    ``_Lasers``) to distinguish them from raw XML attribute dicts.
    """
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()

    seq_root = root if root.tag == "LDM_Block_Sequence" else root.find(".//LDM_Block_Sequence")
    sequence_name = seq_root.get("BlockName", "") if seq_root is not None else ""

    seq_elements = []
    el_list = root.find(".//LDM_Block_Sequence_Element_List")
    if el_list is not None:
        for el in el_list:
            seq_elements.append(_parse_sequence_element(el))

    result = {
        "sequence_name": sequence_name,
        "sequence_elements": seq_elements,
        "jobs": {},
    }

    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is None:
            continue
        job_name = seq.get("BlockName", "?")

        job = {
            "block_attrs": dict(b.attrib),
            "sequential_attrs": dict(seq.attrib),
        }

        master = b.find(".//LDM_Block_Sequential_Master/ATLConfocalSettingDefinition")
        if master is not None:
            job["Master"] = _parse_setting(master)

        sequential = b.find(".//LDM_Block_Sequential_List/ATLConfocalSettingDefinition")
        if sequential is not None:
            job["Sequential"] = _parse_setting(sequential)

        af_setting = b.find(".//Block_Sequential_AutoFocus//ATLConfocalSettingDefinition")
        if af_setting is not None:
            job["AutoFocus"] = _parse_setting(af_setting)

        result["jobs"][job_name] = job

    return result
