"""
Template parser.
================
Parse tile positions, focus points, and autofocus points from
LAS X scanning template files (.xml, .rgn).

Read-only companion to ``template_operations`` which handles
save/load/strip/restore via the API.  This module works entirely
on files — except for the optional ``client`` parameter which
queries tile sizes from the LAS X API.

Closely follows the parsing logic in the reference ``lasx_parser.py``
(Jürgen meeting lib), trimmed to positions and focus data only.

Dependency direction:
    - Imports: stdlib only (+ optional ``readers`` for tile sizes).
    - Imported by: ``__init__`` (re-export).
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

UNASSIGNED_JOB = "(unassigned)"


def _to_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
#  Tile size helpers
# ---------------------------------------------------------------------------

def _parse_size_string(size_str):
    """Parse size strings like '290.63 µm x 290.63 µm' or '1.16 mm x 1.16 mm'."""
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
    """Extract tile size in µm from an imageSize string returned by the API."""
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
        dict ``{job_name: tile_size_um}`` — only jobs where the query
        succeeded.
    """
    from .readers import get_job_settings

    sizes = {}
    for jn in job_names:
        settings = get_job_settings(client, jn)
        if settings and "imageSize" in settings:
            ts = _tile_size_from_image_size_str(settings["imageSize"])
            if ts is not None:
                sizes[jn] = ts
                log.debug("_get_tile_sizes_from_api: %s = %.1f um", jn, ts)
    return sizes


# ---------------------------------------------------------------------------
#  Job names from LRP  (BlockType=1 acquisition blocks)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
#  Tile positions from XML
# ---------------------------------------------------------------------------

def _get_raw_tiles(xml_root, skip_jobs=None):
    """Extract raw tile positions from an XML root element.

    Tiles whose MainJobData has JobName='?' or JobId in (None, '-1')
    are kept but labelled with the sentinel UNASSIGNED_JOB.
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

        tiles.append({
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
        })

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

        fx_vals = sorted(set(
            t["field_x"] for t in tiles if t["field_x"] is not None))
        fy_vals = sorted(set(
            t["field_y"] for t in tiles if t["field_y"] is not None))
        ax = [t["x_um"] for t in tiles]
        ay = [t["y_um"] for t in tiles]

        tiles_sorted = sorted(
            tiles, key=lambda t: (t["field_y"] or 0, t["field_x"] or 0))
        positions = []
        for ao, t in enumerate(tiles_sorted):
            tr = (fy_vals.index(t["field_y"])
                  if t["field_y"] in fy_vals else 0)
            tc = (fx_vals.index(t["field_x"])
                  if t["field_x"] in fx_vals else 0)
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


# ---------------------------------------------------------------------------
#  Base grid positions from RGN  (AM=1 entries)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
#  Focus points and autofocus points from RGN
# ---------------------------------------------------------------------------

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

    # ShapeList entries
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

    # FocusMap entries
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

        focus_points.append({
            "identifier": ident,
            "tag": "",
            "type": "FocusPoint",
            "x_um": round(x * 1e6, 4),
            "y_um": round(y * 1e6, 4),
            "z_um": round(z * 1e6, 4),
            "enabled": enabled,
        })

    return focus_points, autofocus_points


# ---------------------------------------------------------------------------
#  Main entry point
# ---------------------------------------------------------------------------

def parse_template_positions(templates_dir, template_base, *,
                             client=None, tile_size_um=None):
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
        tile_size_um: Optional manual tile size in µm.

    Returns:
        Dict with::

            acquisition_positions — dict of regions (from parse_acquisition_positions)
            base_grid             — list from parse_base_grid
            focus_points          — list from parse_focus_points
            autofocus_points      — list from parse_focus_points
    """
    d = Path(templates_dir)
    xml_path = d / (template_base + ".xml")
    lrp_path = d / (template_base + ".lrp")
    rgn_path = d / (template_base + ".rgn")

    # --- Parse XML
    xml_root = ET.parse(xml_path).getroot() if xml_path.is_file() else None

    # --- Get job names from LRP
    job_names = _get_job_names(lrp_path) if lrp_path.is_file() else []

    # --- Resolve tile sizes  (API > manual > None)
    job_tile_sizes = {}

    if client is not None:
        api_sizes = _get_tile_sizes_from_api(client, job_names)
        job_tile_sizes.update(api_sizes)

    if tile_size_um is not None:
        # Manual fallback for jobs not resolved by API
        for jn in job_names:
            if jn not in job_tile_sizes:
                job_tile_sizes[jn] = tile_size_um
        if UNASSIGNED_JOB not in job_tile_sizes:
            job_tile_sizes[UNASSIGNED_JOB] = tile_size_um

    # Fallback for unassigned: use first available tile size
    if UNASSIGNED_JOB not in job_tile_sizes and job_tile_sizes:
        job_tile_sizes[UNASSIGNED_JOB] = next(iter(job_tile_sizes.values()))

    # --- Parse positions
    acquisition_positions = {}
    if xml_root is not None:
        acquisition_positions = parse_acquisition_positions(
            xml_root, job_tile_sizes)

    # --- Parse RGN data
    base_grid = parse_base_grid(rgn_path) if rgn_path.is_file() else []
    focus_points, autofocus_points = (
        parse_focus_points(rgn_path) if rgn_path.is_file() else ([], []))

    return {
        "acquisition_positions": acquisition_positions,
        "base_grid": base_grid,
        "focus_points": focus_points,
        "autofocus_points": autofocus_points,
    }
