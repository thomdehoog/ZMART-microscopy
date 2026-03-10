"""
Template parser.
================
Parse and modify LAS X scanning template files (.xml, .rgn, .lrp).

Parsing closely follows the reference ``lasx_parser.py`` (Jürgen
meeting lib), trimmed to positions and focus data only.

Modification functions work on raw file text (string replacement)
to preserve the original single-line XML format exactly.

Dependency direction:
    - Imports: stdlib only (+ optional ``readers`` for tile sizes).
    - Imported by: ``__init__`` (re-export).
"""

import json
import logging
import re
import time
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


# ---------------------------------------------------------------------------
#  LRP parser: full job settings extraction
# ---------------------------------------------------------------------------

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

    # Detectors
    det_list = setting_el.find("DetectorList")
    if det_list is not None:
        result["_DetectorList_attrs"] = dict(det_list.attrib)
        detectors = []
        for det in det_list.findall("Detector"):
            detectors.append(_parse_detector(det))
        if detectors:
            result["_Detectors"] = detectors

    # Lasers
    la = setting_el.find("LaserArray")
    if la is not None:
        lasers = []
        for laser in la.findall("Laser"):
            lasers.append(_parse_laser(laser))
        if lasers:
            result["_Lasers"] = lasers

    # AOTFs
    al = setting_el.find("AotfList")
    if al is not None:
        aotfs = []
        for aotf in al.findall("Aotf"):
            aotfs.append(_parse_aotf(aotf))
        if aotfs:
            result["_Aotfs"] = aotfs

    # Shutters
    sl = setting_el.find("ShutterList")
    if sl is not None:
        shutters = []
        for sh in sl.findall("Shutter"):
            shutters.append(_parse_shutter(sh))
        if shutters:
            result["_Shutters"] = shutters

    # Spectral windows (MultiBand)
    spectro = setting_el.find("Spectro")
    if spectro is not None:
        multibands = []
        for mb in spectro.findall("MultiBand"):
            multibands.append(_parse_multiband(mb))
        if multibands:
            result["_MultiBands"] = multibands

    # Filter wheel
    fw = setting_el.find("FilterWheel")
    if fw is not None:
        result["_FilterWheel"] = _parse_filter_wheel(fw)

    # Light sources
    lsl = setting_el.find("LightSourceList")
    if lsl is not None:
        sources = []
        for ls in lsl.findall("LightSourceSetting"):
            sources.append(_parse_light_source(ls))
        if sources:
            result["_LightSources"] = sources

    # LUT list
    lut_list = setting_el.find("LUT_List")
    if lut_list is not None:
        luts = []
        for lut in lut_list.findall("LUT"):
            luts.append(_parse_lut(lut))
        if luts:
            result["_LUTs"] = luts

    # Autofocus config
    af = setting_el.find("Autofocus-config")
    if af is not None:
        result["_AutofocusConfig"] = dict(af.attrib)

    # Additional Z positions
    azpl = setting_el.find("AdditionalZPositionList")
    if azpl is not None:
        zpositions = []
        for azp in azpl.findall("AdditionalZPosition"):
            zpositions.append(dict(azp.attrib))
        if zpositions:
            result["_AdditionalZPositions"] = zpositions

    # ROI
    roi = setting_el.find("ROI")
    if roi is not None:
        roi_singles = []
        for rs in roi.findall(".//ROISingle"):
            roi_singles.append(dict(rs.attrib))
        if roi_singles:
            result["_ROIs"] = roi_singles

    # Online dye separation
    ods = setting_el.find("OnlineDyeSeparation")
    if ods is not None:
        result["_OnlineDyeSeparation"] = dict(ods.attrib)

    # STED depletion line
    sted = setting_el.find("STED_DepletionLine")
    if sted is not None:
        d = dict(sted.attrib)
        beam = _parse_beam_route(sted)
        if beam is not None:
            d["_BeamRoute"] = beam
        result["_STED"] = d

    # Galvo switch
    gsp = setting_el.find("GalvoSwitchParameter")
    if gsp is not None:
        result["_GalvoSwitch"] = dict(gsp.attrib)

    # SPIM CA compensation
    spim = setting_el.find("SpimCACompensationParameter")
    if spim is not None:
        result["_SpimCA"] = dict(spim.attrib)

    # Variable beam expander
    vbe = setting_el.find("VariableBeamExpanderFactors")
    if vbe is not None:
        result["_BeamExpander"] = dict(vbe.attrib)

    return result


def _parse_sequence_element(el):
    """Parse an LDM_Block_Sequence_Element (execution order entry)."""
    return dict(el.attrib)


def parse_lrp(lrp_path):
    """Parse an LRP file into a structured dict organized by job.

    Returns::

        {
            "sequence_name": str,          # top-level BlockName
            "sequence_elements": [...],    # execution order entries
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

    # Top-level sequence metadata
    seq_root = root if root.tag == "LDM_Block_Sequence" else \
        root.find(".//LDM_Block_Sequence")
    sequence_name = seq_root.get("BlockName", "") if seq_root is not None \
        else ""

    # Execution order elements
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

        # Master
        master = b.find(".//LDM_Block_Sequential_Master/"
                        "ATLConfocalSettingDefinition")
        if master is not None:
            job["Master"] = _parse_setting(master)

        # Sequential (the active setting)
        sequential = b.find(".//LDM_Block_Sequential_List/"
                            "ATLConfocalSettingDefinition")
        if sequential is not None:
            job["Sequential"] = _parse_setting(sequential)

        # AutoFocus
        af_setting = b.find(".//Block_Sequential_AutoFocus//"
                            "ATLConfocalSettingDefinition")
        if af_setting is not None:
            job["AutoFocus"] = _parse_setting(af_setting)

        result["jobs"][job_name] = job

    return result


def diff_lrp(parsed_a, parsed_b, ignore_keys=None):
    """Compare two parsed LRP structures and return differences.

    Args:
        parsed_a: First parsed LRP (from ``parse_lrp``).
        parsed_b: Second parsed LRP (from ``parse_lrp``).
        ignore_keys: Set of attribute names to ignore (e.g.
            ``{"UserSettingName", "BlockID"}``).

    Returns:
        List of diff dicts, each with::

            path  — dotted path (e.g. "AF Job.Sequential.attrs.LineAverage")
            a     — value in parsed_a (None if missing)
            b     — value in parsed_b (None if missing)
    """
    if ignore_keys is None:
        ignore_keys = {"UserSettingName", "BlockID", "MemoryBlockID",
                       "UniqueID", "ID"}

    diffs = []

    def _compare(obj_a, obj_b, path=""):
        if isinstance(obj_a, dict) and isinstance(obj_b, dict):
            all_keys = sorted(set(obj_a.keys()) | set(obj_b.keys()))
            for k in all_keys:
                if k in ignore_keys:
                    continue
                va = obj_a.get(k)
                vb = obj_b.get(k)
                _compare(va, vb, f"{path}.{k}" if path else k)
        elif isinstance(obj_a, list) and isinstance(obj_b, list):
            for i in range(max(len(obj_a), len(obj_b))):
                va = obj_a[i] if i < len(obj_a) else None
                vb = obj_b[i] if i < len(obj_b) else None
                _compare(va, vb, f"{path}[{i}]")
        else:
            if obj_a != obj_b:
                diffs.append({"path": path, "a": obj_a, "b": obj_b})

    _compare(parsed_a, parsed_b)
    return diffs


# ---------------------------------------------------------------------------
#  LRP modification: job ordering
# ---------------------------------------------------------------------------

def reorder_jobs(lrp_path, first_job):
    """Move a job to first position in the LRP.

    LAS X selects the first job after loading a template, so this
    controls which job is active in the GUI after a reload.

    Reorders both the ``LDM_Block_Sequence_Element_List`` and the
    ``LDM_Block_Sequence_Block_List``.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        first_job: Name of the job to move to first position.

    Returns:
        True if the job was moved (or was already first), False on error.
    """
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()

    el_list = root.find(".//LDM_Block_Sequence_Element_List")
    block_list = root.find(".//LDM_Block_Sequence_Block_List")
    if el_list is None or block_list is None:
        log.error("reorder_jobs: missing element/block list")
        return False

    # Map BlockID -> job name
    block_to_job = {}
    for b in block_list:
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None:
            block_to_job[b.get("BlockID")] = seq.get("BlockName")

    # Index elements and blocks by job name
    el_by_job = {}
    for e in el_list:
        job = block_to_job.get(e.get("BlockID"))
        if job:
            el_by_job[job] = e

    block_by_job = {}
    for b in block_list:
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None:
            block_by_job[seq.get("BlockName")] = b

    if first_job not in block_by_job:
        log.error("reorder_jobs: job '%s' not found", first_job)
        return False

    # Build new order: first_job first, rest unchanged
    current_order = [block_to_job[e.get("BlockID")] for e in el_list
                     if e.get("BlockID") in block_to_job]

    if current_order and current_order[0] == first_job:
        log.debug("reorder_jobs: '%s' already first", first_job)
        return True

    new_order = [first_job] + [j for j in current_order if j != first_job]

    # Clear and re-add in new order
    for e in list(el_list):
        el_list.remove(e)
    for b in list(block_list):
        block_list.remove(b)

    for job_name in new_order:
        el_list.append(el_by_job[job_name])
        block_list.append(block_by_job[job_name])

    ET.ElementTree(root).write(str(lrp_path), encoding="unicode",
                               xml_declaration=False)
    log.info("reorder_jobs: moved '%s' to first position", first_job)
    return True


# ---------------------------------------------------------------------------
#  LRP modification: Z-stack calculation mode
# ---------------------------------------------------------------------------

STACK_MODES = {
    0: "Constant steps",
    1: "Constant step size",
    2: "System optimized step size",
}


def set_stack_calculation_mode(lrp_path, mode, job_name):
    """Set the Z-stack calculation mode for a specific job.

    Uses string replacement on the ``ATLConfocalSettingDefinition``
    inside ``LDM_Block_Sequential_Master`` (the authoritative element).

    Args:
        lrp_path: Path to the ``.lrp`` file.
        mode: Target mode — ``0`` (Constant steps),
            ``1`` (Constant step size), or
            ``2`` (System optimized step size).
        job_name: Name of the job to modify (e.g. ``"AF Job"``).

    Returns:
        Number of attributes changed (0, 1, or 2).
    """
    if mode not in STACK_MODES:
        log.error("set_stack_calculation_mode: invalid mode %r "
                  "(expected 0, 1, or 2)", mode)
        return 0

    lrp_path = Path(lrp_path)
    text = lrp_path.read_text(encoding="utf-8")

    # Find the job block by locating BlockName="<job_name>"
    marker = f'BlockName="{job_name}"'
    job_pos = text.find(marker)
    if job_pos == -1:
        log.error("set_stack_calculation_mode: job '%s' not found", job_name)
        return 0

    # Find the LDM_Block_Sequential_Master after the job marker
    master_tag = "LDM_Block_Sequential_Master"
    master_pos = text.find(master_tag, job_pos)
    if master_pos == -1:
        log.error("set_stack_calculation_mode: no Sequential_Master "
                  "found for job '%s'", job_name)
        return 0

    # Find the ATLConfocalSettingDefinition within the master
    setting_tag = "ATLConfocalSettingDefinition"
    setting_pos = text.find(setting_tag, master_pos)
    if setting_pos == -1:
        log.error("set_stack_calculation_mode: no setting found in "
                  "Sequential_Master for job '%s'", job_name)
        return 0

    # Find the end of this element (next ">")
    end_pos = text.find(">", setting_pos)
    if end_pos == -1:
        return 0

    # Extract just this element's text and replace both attributes
    element_text = text[setting_pos:end_pos + 1]
    new_element = element_text
    count = 0

    # Replace StackCalculationMode value
    m = re.search(r'StackCalculationMode="(\d+)"', new_element)
    if m and m.group(1) != str(mode):
        new_element = new_element.replace(
            m.group(0), f'StackCalculationMode="{mode}"')
        count += 1

    # Replace StackCalculationModeName value
    target_name = STACK_MODES[mode]
    m = re.search(r'StackCalculationModeName="([^"]*)"', new_element)
    if m and m.group(1) != target_name:
        new_element = new_element.replace(
            m.group(0), f'StackCalculationModeName="{target_name}"')
        count += 1

    if count > 0:
        text = text[:setting_pos] + new_element + text[end_pos + 1:]
        lrp_path.write_text(text, encoding="utf-8")

    log.info("set_stack_calculation_mode: job='%s', mode=%d (%s), "
             "%d attributes changed", job_name, mode, STACK_MODES[mode],
             count)
    return count


def apply_lrp_change(client, xml_name, lrp_edit_fn, *args,
                     verify_fn=None, active_job=None,
                     confirm_delays=(0.5, 1, 2, 4, 8), **kwargs):
    """Apply an LRP edit with save + edit + load + save + verify.

    1. Save to flush LAS X state to disk (ensures file is current).
    2. Edit the LRP file on disk.
    3. Optionally reorder jobs so ``active_job`` is first (and thus
       selected in LAS X after reload).
    4. Load the template so LAS X picks up the change.
    5. Save again so LAS X writes its state back to disk.
    6. Verify the target attribute(s) in the saved file.

    The ``verify_fn`` should only check the specific attributes that
    were edited — LAS X regenerates many internal IDs on every save.

    Args:
        client: Live LAS X CAM client.
        xml_name: Template XML filename (e.g. ``TEMPLATE_XML`` or
            ``STRIPPED_XML``).
        lrp_edit_fn: Callable that modifies the LRP file.
            Called as ``lrp_edit_fn(lrp_path, *args, **kwargs)``.
        *args: Forwarded to *lrp_edit_fn*.
        verify_fn: Optional callable ``verify_fn(lrp_path) -> bool``
            that checks the saved file. Should only verify the target
            attributes. If None, success is assumed after save.
        active_job: Optional job name to move to first position so
            LAS X selects it after reload.
        confirm_delays: Sequence of delays (seconds) for confirm save
            attempts. Length determines number of attempts.
        **kwargs: Forwarded to *lrp_edit_fn*.

    Returns:
        dict with success, edit_result, attempts, or None on failure.
    """
    from .template_operations import (
        find_scanning_templates_dir, load_experiment, save_experiment,
    )

    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        log.error("apply_lrp_change: cannot find ScanningTemplates dir")
        return None

    lrp_path = Path(templates_dir) / xml_name.replace(".xml", ".lrp")

    # Step 1: Save (flush current LAS X state to disk)
    r = save_experiment(client, xml_name, templates_dir)
    if r is None:
        log.error("apply_lrp_change: initial save failed")
        return None

    # Step 2: Edit
    edit_result = lrp_edit_fn(lrp_path, *args, **kwargs)

    # Step 3: Reorder jobs (if requested)
    if active_job is not None:
        reorder_jobs(lrp_path, active_job)

    # Step 4: Load
    r = load_experiment(client, xml_name)
    if r is None:
        log.error("apply_lrp_change: load failed")
        return None

    # Step 5: Save + verify loop
    for attempt, save_timeout in enumerate(confirm_delays, 1):
        r = save_experiment(client, xml_name, templates_dir,
                            timeout=save_timeout)
        if r is None:
            log.warning("apply_lrp_change: confirm save timed out "
                        "(attempt %d, timeout=%.1fs)", attempt, save_timeout)
            continue

        if verify_fn is None or verify_fn(lrp_path):
            log.info("apply_lrp_change: verified after %d attempt(s)",
                     attempt)
            return {
                "success": True,
                "edit_result": edit_result,
                "attempts": attempt,
            }

        log.warning("apply_lrp_change: verification failed (attempt %d)",
                    attempt)

    log.error("apply_lrp_change: failed after %d attempts",
              len(confirm_delays))
    return None


def verify_stack_calculation_mode(lrp_path, mode, job_name):
    """Verify the Z-stack calculation mode on the Master element.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        mode: Expected mode (0, 1, or 2).
        job_name: Name of the job to verify.

    Returns:
        True if ``StackCalculationMode`` matches the expected value.
    """
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            el = b.find(".//LDM_Block_Sequential_Master/"
                        "ATLConfocalSettingDefinition")
            if el is None:
                return False
            return el.get("StackCalculationMode") == str(mode)
    return False
