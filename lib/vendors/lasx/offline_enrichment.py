#!/usr/bin/env python3
"""
lasx_offline_enrichment.py

Offline enrichment of parsed LAS X template data using OME-TIFF / OME-XML
files found in neighboring experiment folders.

When the LAS X API is not available (offline use), pixel size and image size
can still be recovered from the OME metadata embedded in acquired TIFF files
or their companion XML files.

Expected folder layout
======================
    experiment_root/
    â”œâ”€â”€ metadata/                     â† template files live here
    â”‚   â”œâ”€â”€ _ScanningTemplate.xml
    â”‚   â”œâ”€â”€ _ScanningTemplate.lrp
    â”‚   â””â”€â”€ _ScanningTemplate.rgn
    â”œâ”€â”€ slide--S00/
    â”‚   â””â”€â”€ chamber--U04--V03/
    â”‚       â””â”€â”€ field--X00--Y00/
    â”‚           â”œâ”€â”€ image--â€¦--J30--â€¦--C00.ome.tif
    â”‚           â”œâ”€â”€ image--â€¦--J30--â€¦--C01.ome.tif
    â”‚           â””â”€â”€ image--â€¦--T0000_ome.xml
    â””â”€â”€ â€¦

The module walks *up* from the template folder, then recursively scans
sibling folders for ``*.ome.tif`` and ``*_ome.xml`` files.  Each file's
OME metadata is parsed to extract pixel size, image dimensions, objective
info, and more.  The ``J##`` token in the filename maps to the job ``id``
produced by ``lasx_parser.parse_template()``.

Usage
=====
    from vendors.lasx.parser import parse_template
    from vendors.lasx.offline_enrichment import enrich_offline

    result = parse_template(xml_path, lrp_path, rgn_path)
    result = enrich_offline(result, template_dir=xml_path)

    # Or point directly at the experiment root:
    result = enrich_offline(result, experiment_root="/path/to/experiment")
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# â”€â”€ Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Regex to pull J## from LAS X filenames
_JOB_ID_RE = re.compile(r"--J(\d+)--")

# OME namespace (may vary between LAS X versions)
_OME_NS_PATTERN = re.compile(r"\{(.+?)\}")

# File globs
_OME_TIFF_GLOBS = ["*.ome.tif", "*.ome.tiff"]
_OME_XML_GLOBS = ["*_ome.xml"]


# â”€â”€ OME Metadata Extraction â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _detect_ome_namespace(root: ET.Element) -> str:
    """Return the OME namespace URI from the root element's tag."""
    m = _OME_NS_PATTERN.match(root.tag)
    return m.group(1) if m else ""


def _parse_ome_xml_string(xml_str: str) -> Optional[Dict[str, Any]]:
    """
    Parse an OME-XML string and extract imaging metadata.

    Returns a dict with:
        pixel_size_um   â€“ {"x": float, "y": float}
        image_size_px   â€“ {"x": int,   "y": int}
        image_size_um   â€“ {"x": float, "y": float}   (from DimensionDescription or computed)
        objective_name  â€“ str
        zoom            â€“ float
        base_zoom       â€“ float
        scan_mode       â€“ str
        stage_position  â€“ {"x_m": float, "y_m": float, "z_m": float}
        n_channels      â€“ int   (from SizeC or counted from channel filenames)
        bit_depth       â€“ str   (e.g. "uint16")
        image_name      â€“ str   (full path embedded by LAS X)
    """
    if not xml_str or not xml_str.strip():
        return None

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    ns = _detect_ome_namespace(root)
    ns_map = {"ome": ns} if ns else {}

    def _find(tag):
        return root.find(f".//{{{ns}}}{tag}") if ns else root.find(f".//{tag}")

    def _findall(tag):
        return root.findall(f".//{{{ns}}}{tag}") if ns else root.findall(f".//{tag}")

    result: Dict[str, Any] = {}

    # â”€â”€ Image element â”€â”€
    img_elem = _find("Image")
    if img_elem is not None:
        result["image_name"] = img_elem.get("Name", "")

    # â”€â”€ Pixels element â”€â”€
    pixels = _find("Pixels")
    if pixels is None:
        return None

    pa = pixels.attrib
    phys_x = _safe_float(pa.get("PhysicalSizeX"))
    phys_y = _safe_float(pa.get("PhysicalSizeY"))
    size_x = _safe_int(pa.get("SizeX"))
    size_y = _safe_int(pa.get("SizeY"))
    size_c = _safe_int(pa.get("SizeC")) or 1
    size_z = _safe_int(pa.get("SizeZ")) or 1

    if phys_x is not None and phys_y is not None:
        result["pixel_size_um"] = {
            "x": round(phys_x, 6),
            "y": round(phys_y, 6),
        }
    if size_x is not None and size_y is not None:
        result["image_size_px"] = {"x": size_x, "y": size_y}

    result["n_channels"] = size_c
    result["n_z_slices"] = size_z
    result["bit_depth"] = pa.get("PixelType", "uint16")

    # â”€â”€ Image physical size from DimensionDescription (more accurate) â”€â”€
    # LAS X stores DimensionDescription in OriginalMetadata with DimID 1 (X)
    # and DimID 2 (Y). The "Length" field is in metres.
    dim_lengths = {}  # DimID -> length_m
    dim_counts = {}   # DimID -> number of elements

    # LAS X writes DimensionDescription blocks sequentially in OriginalMetadata.
    # Each block starts with DimID, followed by NumberOfElements, Length, etc.
    # We track the current DimID as we iterate.
    ca_ns = "http://www.openmicroscopy.org/Schemas/CA/2008-09"
    _current_dim_id: Optional[int] = None
    for om in root.iter(f"{{{ca_ns}}}OriginalMetadata"):
        name = om.get("Name", "")
        value = om.get("Value", "")
        if "DimensionDescription" in name:
            if name.endswith("DimID"):
                _current_dim_id = _safe_int(value)
            elif name.endswith("Length") and _current_dim_id is not None:
                dim_lengths[_current_dim_id] = _safe_float(value)
            elif name.endswith("NumberOfElements") and _current_dim_id is not None:
                dim_counts[_current_dim_id] = _safe_int(value)

    # DimID 1 = X, DimID 2 = Y (LAS X convention)
    len_x_m = dim_lengths.get(1)
    len_y_m = dim_lengths.get(2)
    if len_x_m is not None and len_y_m is not None:
        result["image_size_um"] = {
            "x": round(len_x_m * 1e6, 4),
            "y": round(len_y_m * 1e6, 4),
        }
    elif phys_x is not None and phys_y is not None and size_x and size_y:
        # Fallback: compute from pixel size Ã— number of pixels
        result["image_size_um"] = {
            "x": round(phys_x * size_x, 4),
            "y": round(phys_y * size_y, 4),
        }

    # â”€â”€ Objective, Zoom, ScanMode from OriginalMetadata â”€â”€
    for om in root.iter(f"{{{ca_ns}}}OriginalMetadata"):
        name = om.get("Name", "")
        value = om.get("Value", "")
        # Only take top-level ATLConfocalSettingDefinition (not inside Sequential)
        if "LDM_Block_Sequential" in name:
            continue
        if name.endswith("ObjectiveName"):
            result["objective_name"] = value.strip()
        elif name.endswith("Zoom") and "BaseZoom" not in name:
            result["zoom"] = _safe_float(value)
        elif name.endswith("BaseZoom"):
            result["base_zoom"] = _safe_float(value)
        elif name.endswith("ScanMode"):
            result["scan_mode"] = value

    # â”€â”€ Objective from OME Instrument â”€â”€
    obj = _find("Objective")
    if obj is not None:
        if "objective_name" not in result:
            result["objective_name"] = obj.get("Model", "")
        result["objective_serial"] = obj.get("SerialNumber", "")
        result["objective_manufacturer"] = obj.get("Manufacturer", "")

    # â”€â”€ Stage position â”€â”€
    stage = _find("StagePosition")
    if stage is not None:
        result["stage_position"] = {
            "x_m": _safe_float(stage.get("PositionX")),
            "y_m": _safe_float(stage.get("PositionY")),
            "z_m": _safe_float(stage.get("PositionZ")),
        }

    return result


def _safe_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _safe_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


# â”€â”€ File Discovery â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _extract_job_id_from_filename(filename: str) -> Optional[int]:
    """Extract the job ID (J##) from a LAS X image filename."""
    m = _JOB_ID_RE.search(filename)
    return int(m.group(1)) if m else None


def _read_ome_xml_from_tiff(tiff_path: Path) -> Optional[str]:
    """
    Read OME-XML from a TIFF's ImageDescription tag.

    Uses tifffile if available, otherwise falls back to manual IFD parsing.
    """
    try:
        import tifffile
        with tifffile.TiffFile(str(tiff_path)) as tif:
            if tif.ome_metadata:
                return tif.ome_metadata
            # Fallback to ImageDescription
            page = tif.pages[0]
            desc_tag = page.tags.get("ImageDescription")
            if desc_tag and "<?xml" in str(desc_tag.value):
                return str(desc_tag.value)
    except ImportError:
        # Manual fallback: read ImageDescription from first IFD
        try:
            return _read_image_description_manual(tiff_path)
        except Exception:
            pass
    except Exception:
        pass
    return None


def _read_image_description_manual(tiff_path: Path) -> Optional[str]:
    """Manually read the ImageDescription tag from a TIFF (tag 270)."""
    import struct

    with open(tiff_path, "rb") as fh:
        header = fh.read(8)
        if len(header) < 8:
            return None
        byte_order = "<" if header[:2] == b"II" else ">"
        magic = struct.unpack(f"{byte_order}H", header[2:4])[0]
        if magic != 42:
            return None
        ifd_offset = struct.unpack(f"{byte_order}I", header[4:8])[0]

        fh.seek(ifd_offset)
        num_entries = struct.unpack(f"{byte_order}H", fh.read(2))[0]
        for _ in range(num_entries):
            entry = fh.read(12)
            tag = struct.unpack(f"{byte_order}H", entry[0:2])[0]
            dtype = struct.unpack(f"{byte_order}H", entry[2:4])[0]
            count = struct.unpack(f"{byte_order}I", entry[4:8])[0]
            if tag == 270:  # ImageDescription
                if dtype == 2:  # ASCII
                    if count <= 4:
                        data = entry[8:8 + count]
                    else:
                        offset = struct.unpack(f"{byte_order}I", entry[8:12])[0]
                        fh.seek(offset)
                        data = fh.read(count)
                    text = data.decode("utf-8", errors="replace").rstrip("\x00")
                    if "<?xml" in text:
                        return text
    return None


def discover_ome_files(
    experiment_root: Path,
    max_depth: int = 6,
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    """
    Recursively discover OME-TIFF and OME-XML files under *experiment_root*.

    Returns a list of dicts, each containing:
        path      â€“ Path to the file
        job_id    â€“ int extracted from J## in filename (or None)
        source    â€“ "ome_tiff" or "ome_xml"
    """
    found: List[Dict[str, Any]] = []
    seen_stems: set = set()

    experiment_root = Path(experiment_root)
    if not experiment_root.is_dir():
        return found

    for dirpath, dirnames, filenames in os.walk(str(experiment_root)):
        # Limit recursion depth
        rel = Path(dirpath).relative_to(experiment_root)
        if len(rel.parts) > max_depth:
            dirnames.clear()
            continue

        for fn in filenames:
            fp = Path(dirpath) / fn
            fn_lower = fn.lower()
            job_id = _extract_job_id_from_filename(fn)

            if fn_lower.endswith(".ome.tif") or fn_lower.endswith(".ome.tiff"):
                # Prefer one file per (job_id, field) â€“ use the stem without channel
                stem_key = re.sub(r"--C\d+", "", fn)
                if stem_key not in seen_stems:
                    seen_stems.add(stem_key)
                    found.append({"path": fp, "job_id": job_id, "source": "ome_tiff"})
            elif fn_lower.endswith("_ome.xml"):
                found.append({"path": fp, "job_id": job_id, "source": "ome_xml"})

    if verbose:
        print(f"  Discovered {len(found)} OME file(s) under {experiment_root}")
    return found


def _resolve_experiment_root(
    template_dir: Optional[str | Path] = None,
    experiment_root: Optional[str | Path] = None,
) -> Path:
    """
    Determine the experiment root directory.

    If *experiment_root* is given, use it directly.
    Otherwise go one level up from *template_dir* (the folder containing
    the template XML/LRP/RGN files).
    """
    if experiment_root is not None:
        return Path(experiment_root)
    if template_dir is not None:
        td = Path(template_dir)
        if td.is_file():
            td = td.parent
        return td.parent  # go up one level
    raise ValueError("Provide either template_dir or experiment_root")


# â”€â”€ Metadata Aggregation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def extract_metadata_by_job(
    experiment_root: Path,
    verbose: bool = False,
) -> Dict[int, Dict[str, Any]]:
    """
    Discover OME files and aggregate metadata *per job ID*.

    Returns:
        {job_id: {pixel_size_um, image_size_px, image_size_um, ...}}

    When multiple files exist for the same job, values are taken from the
    first successfully parsed file (XML preferred over TIFF for speed).
    """
    files = discover_ome_files(experiment_root, verbose=verbose)

    # Sort: XMLs first (faster to parse), then TIFFs
    files.sort(key=lambda f: (0 if f["source"] == "ome_xml" else 1))

    by_job: Dict[int, Dict[str, Any]] = {}

    for entry in files:
        jid = entry["job_id"]
        if jid is None:
            continue
        if jid in by_job:
            continue  # already have metadata for this job

        fp = entry["path"]
        xml_str = None

        if entry["source"] == "ome_xml":
            try:
                xml_str = fp.read_text(encoding="utf-8")
            except Exception:
                continue
        else:
            xml_str = _read_ome_xml_from_tiff(fp)

        if xml_str is None:
            continue

        meta = _parse_ome_xml_string(xml_str)
        if meta is not None:
            meta["_source_file"] = str(fp)
            by_job[jid] = meta
            if verbose:
                px = meta.get("pixel_size_um", {})
                im = meta.get("image_size_um", {})
                print(
                    f"    J{jid:02d}: pixel={px.get('x','?')}Ã—{px.get('y','?')} Âµm, "
                    f"image={im.get('x','?')}Ã—{im.get('y','?')} Âµm  "
                    f"({entry['source']}: {fp.name})"
                )

    return by_job


# â”€â”€ Job ID â†’ Job Name Mapping â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _build_job_id_to_name(parsed: Dict[str, Any]) -> Dict[int, str]:
    """Map job ``id`` (BlockID = J## in filenames) â†’ job name."""
    mapping: Dict[int, str] = {}
    for job_name, job_data in parsed.get("acquisition_jobs", {}).items():
        jid = job_data.get("id")
        if jid is not None:
            mapping[jid] = job_name
    return mapping


# â”€â”€ Enrichment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def enrich_offline(
    parsed: Dict[str, Any],
    template_dir: Optional[str | Path] = None,
    experiment_root: Optional[str | Path] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Enrich parsed template data with offline OME metadata.

    This is the offline counterpart of ``enrich_with_api_data()`` from
    ``lasx_api_enrichment.py``.  It fills in the same fields:

    Per job (in ``acquisition_jobs``):
        - ``pixelSize_um``   â€“ {"x": â€¦, "y": â€¦}
        - ``imageSize_um``   â€“ {"x": â€¦, "y": â€¦}
        - ``tileSize_um``    â€“ float (average of x, y)
        - ``format``         â€“ "1024 x 1024"
        - ``pixelSize_raw``  â€“ human-readable string

    Per position group (in ``acquisition_positions``):
        - ``tile_size_um``   â€“ propagated from the job
        - per-tile ``bounding_box``

    Parameters
    ----------
    parsed : dict
        Output of ``lasx_parser.parse_template()``.
    template_dir : path-like, optional
        Path to the template file (or folder containing it).
        The module goes one level up to find the experiment root.
    experiment_root : path-like, optional
        Direct path to the experiment root.  Takes precedence over
        *template_dir*.
    verbose : bool
        Print progress to stdout.

    Returns
    -------
    dict
        Enriched copy of *parsed* (same structure, filled-in values).
    """
    root = _resolve_experiment_root(template_dir, experiment_root)

    if verbose:
        print(f"  â®ž Offline enrichment from: {root}")

    # 1. Discover & parse OME files â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    meta_by_job_id = extract_metadata_by_job(root, verbose=verbose)
    if not meta_by_job_id:
        if verbose:
            print("  âš  No OME metadata files found â€“ enrichment skipped")
        parsed["_offline_enrichment"] = {"success": False, "reason": "no_ome_files"}
        return parsed

    # 2. Map job IDs â†’ job names â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    id_to_name = _build_job_id_to_name(parsed)

    enriched = _deep_copy_dict(parsed)
    jobs_enriched: List[str] = []

    for job_id, meta in meta_by_job_id.items():
        job_name = id_to_name.get(job_id)
        if job_name is None:
            if verbose:
                print(f"    âš  J{job_id:02d} not matched to any parsed job â€“ skipped")
            continue
        if job_name not in enriched.get("acquisition_jobs", {}):
            continue

        job = enriched["acquisition_jobs"][job_name]

        # â”€â”€ Pixel size â”€â”€
        px = meta.get("pixel_size_um")
        if px:
            job["pixelSize_um"] = px
            job["pixelSize_raw"] = (
                f"{px['x']*1000:.2f} nm x {px['y']*1000:.2f} nm"
                if px["x"] < 1.0
                else f"{px['x']:.4f} Âµm x {px['y']:.4f} Âµm"
            )
            job["pixelSize"] = job["pixelSize_raw"]  # compat with visualizer

        # â”€â”€ Image / tile size â”€â”€
        im = meta.get("image_size_um")
        if im:
            job["imageSize_um"] = im
            tile = round((im["x"] + im["y"]) / 2.0, 4)
            job["tileSize_um"] = tile
            job["imageSize_raw"] = f"{im['x']:.2f} Âµm x {im['y']:.2f} Âµm"
            job["imageSize"] = job["imageSize_raw"]

        # â”€â”€ Format (resolution) â”€â”€
        sz = meta.get("image_size_px")
        if sz:
            job["format"] = f"{sz['x']} x {sz['y']}"

        # â”€â”€ Objective (enrich if missing) â”€â”€
        obj_name = meta.get("objective_name")
        if obj_name and "objective" in job:
            if not job["objective"].get("name"):
                job["objective"]["name"] = obj_name

        # â”€â”€ Zoom â”€â”€
        zoom_val = meta.get("zoom")
        if zoom_val is not None and "zoom" in job:
            job["zoom"]["current"] = zoom_val

        jobs_enriched.append(job_name)

        if verbose:
            print(
                f"    âœ” {job_name} (J{job_id:02d}): "
                f"pixel={job.get('pixelSize_raw', '?')}, "
                f"tile={job.get('tileSize_um', '?')} Âµm"
            )

    # 3. Update visualization_data tile sizes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    viz = enriched.get("visualization_data", {})
    job_tile_sizes = viz.get("job_tile_sizes", {})
    for jn in jobs_enriched:
        ts = enriched["acquisition_jobs"][jn].get("tileSize_um")
        if ts is not None:
            job_tile_sizes[jn] = ts
    viz["job_tile_sizes"] = job_tile_sizes

    # 4. Propagate tile sizes to position groups â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    positions = enriched.get("acquisition_positions", {})
    for gid, group in positions.items():
        jn = group.get("job_name")
        if jn and jn in enriched.get("acquisition_jobs", {}):
            ts = enriched["acquisition_jobs"][jn].get("tileSize_um")
            if ts is not None:
                group["tile_size_um"] = ts
                h = ts / 2.0
                for pos in group.get("positions", []):
                    pos["bounding_box"] = {
                        "x_min_um": round(pos["x_um"] - h, 4),
                        "y_min_um": round(pos["y_um"] - h, 4),
                        "x_max_um": round(pos["x_um"] + h, 4),
                        "y_max_um": round(pos["y_um"] + h, 4),
                    }

    # 5. Metadata stamp â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    enriched["_offline_enrichment"] = {
        "success": True,
        "jobs_enriched": jobs_enriched,
        "experiment_root": str(root),
        "ome_files_found": len(meta_by_job_id),
    }

    if verbose:
        not_enriched = [
            jn for jn in enriched.get("acquisition_jobs", {})
            if jn not in jobs_enriched
        ]
        if not_enriched:
            print(f"  âš  Jobs without offline metadata: {not_enriched}")
        print("  âœ” Offline enrichment complete")

    return enriched


# â”€â”€ Convenience helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _deep_copy_dict(d: Dict) -> Dict:
    """Simple recursive dict copy (avoids importing copy for portability)."""
    import copy
    return copy.deepcopy(d)


def get_ome_summary(
    experiment_root: str | Path,
    verbose: bool = True,
) -> Dict[int, Dict[str, Any]]:
    """
    Stand-alone helper: scan an experiment folder and print what OME
    metadata is available, without needing a parsed template.
    """
    root = Path(experiment_root)
    meta = extract_metadata_by_job(root, verbose=verbose)

    if verbose and meta:
        print(f"\n  Summary: found metadata for {len(meta)} job(s)")
        for jid, m in sorted(meta.items()):
            px = m.get("pixel_size_um", {})
            im = m.get("image_size_um", {})
            sz = m.get("image_size_px", {})
            obj = m.get("objective_name", "?")
            print(
                f"    J{jid:02d}: {sz.get('x','?')}Ã—{sz.get('y','?')} px, "
                f"pixel {px.get('x','?')}Ã—{px.get('y','?')} Âµm, "
                f"FOV {im.get('x','?')}Ã—{im.get('y','?')} Âµm, "
                f"obj={obj}"
            )
    return meta


# â”€â”€ CLI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python lasx_offline_enrichment.py <experiment_root>")
        print("       python lasx_offline_enrichment.py <experiment_root> <template.xml> <template.lrp> [template.rgn]")
        sys.exit(1)

    exp_root = sys.argv[1]
    print(f"Scanning: {exp_root}\n")
    meta = get_ome_summary(exp_root, verbose=True)

    if len(sys.argv) >= 4:
        from .parser import parse_template

        xml_path = sys.argv[2]
        lrp_path = sys.argv[3]
        rgn_path = sys.argv[4] if len(sys.argv) > 4 else None

        print(f"\n{'='*60}")
        print("Parsing template + offline enrichmentâ€¦")
        parsed = parse_template(xml_path, lrp_path, rgn_path)
        enriched = enrich_offline(parsed, experiment_root=exp_root)

        import json
        out = exp_root.rstrip("/\\") + "_offline_enriched.json"
        with open(out, "w") as f:
            json.dump(enriched, f, indent=2)
        print(f"\nâœ” Saved to {out}")
