#!/usr/bin/env python3
"""
lasx_parser.py

Parser for LAS X template files (.xml, .lrp, .rgn).
Outputs self-contained JSON suitable for visualization.

Usage:
    from vendors.lasx.parser import parse_template
    result = parse_template(xml_path, lrp_path, rgn_path)
"""

import xml.etree.ElementTree as ET
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple


# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def to_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None

def to_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None

def parse_bool(s: Optional[str]) -> Optional[bool]:
    if s is None:
        return None
    return str(s).strip().lower() in ("true", "1", "yes")

def beam_route_str(elem) -> str:
    """Extract beam route as semicolon-separated string from BeamPosition elements."""
    bps = elem.findall(".//BeamRoute/BeamPosition")
    if not bps:
        bps = elem.findall(".//BeamPosition")
    if not bps:
        return ""
    return ";".join(bp.get("BeamPosition", "") for bp in bps)

def beam_route_level(elem, level: int) -> Optional[str]:
    """Get beam position at a specific level."""
    for bp in elem.findall(".//BeamPosition"):
        if bp.get("BeamPositionLevel") == str(level):
            return bp.get("BeamPosition")
    return None


# â”€â”€â”€ Tile Size Derivation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_raw_tiles(xml_root, skip_jobs=None):
    """Extract raw tile positions from XML."""
    if skip_jobs is None:
        skip_jobs = set()
    
    tiles_raw = []
    for sf in xml_root.findall(".//ScanFieldData"):
        if sf.get("IsEnabled") != "true":
            continue
        mj = sf.find(".//MainJobData")
        if mj is None:
            continue
        jn = mj.get("JobName")
        jid = mj.get("JobId")
        if not jn or jn == "?" or jid in (None, "-1"):
            continue
        if jn in skip_jobs:
            continue
        ld = sf.find("LogicalData")
        ph = sf.find("PhysicalData")
        if ld is None or ph is None:
            continue
        x = to_float(ph.get("XPosition"))
        y = to_float(ph.get("YPosition"))
        if x is None or y is None:
            continue
        tiles_raw.append({
            "unique_id": sf.get("UniqueID"), "job_name": jn,
            "scan_order": to_int(sf.get("ScanOrder")),
            "section_x": to_int(ld.get("SectionX")), "section_y": to_int(ld.get("SectionY")),
            "field_x": to_int(ld.get("FieldX")), "field_y": to_int(ld.get("FieldY")),
            "x_um": x, "y_um": y, "z_um": to_float(ph.get("ZPosition")) or 0.0,
            "rotation": to_float(sf.get("ScanRotationAngle")),
        })
    return tiles_raw


def _compute_spacing_for_group(tiles):
    """Compute minimum adjacent tile spacing for a group of tiles."""
    spacings = []
    
    by_row = defaultdict(list)
    for t in tiles:
        if t["field_y"] is not None:
            by_row[t["field_y"]].append(t)
    
    for fy, row_tiles in by_row.items():
        row_sorted = sorted(row_tiles, key=lambda t: (t["field_x"] or 0))
        for i in range(len(row_sorted) - 1):
            fx1 = row_sorted[i]["field_x"]
            fx2 = row_sorted[i+1]["field_x"]
            if fx1 is not None and fx2 is not None and fx2 - fx1 == 1:
                dx = abs(row_sorted[i+1]["x_um"] - row_sorted[i]["x_um"])
                if dx > 0:
                    spacings.append(dx)
    
    by_col = defaultdict(list)
    for t in tiles:
        if t["field_x"] is not None:
            by_col[t["field_x"]].append(t)
    
    for fx, col_tiles in by_col.items():
        col_sorted = sorted(col_tiles, key=lambda t: (t["field_y"] or 0))
        for i in range(len(col_sorted) - 1):
            fy1 = col_sorted[i]["field_y"]
            fy2 = col_sorted[i+1]["field_y"]
            if fy1 is not None and fy2 is not None and fy2 - fy1 == 1:
                dy = abs(col_sorted[i+1]["y_um"] - col_sorted[i]["y_um"])
                if dy > 0:
                    spacings.append(dy)
    
    return min(spacings) if spacings else None


def derive_tile_sizes_from_positions(tiles_raw, dist_data, mosaic_overlap_pct):
    """Derive tile sizes for each job from actual tile positions."""
    overlap_fraction = mosaic_overlap_pct / 100.0
    
    by_job_section = defaultdict(list)
    for t in tiles_raw:
        key = (t["job_name"], t["section_x"], t["section_y"])
        by_job_section[key].append(t)
    
    job_geometry_spacings = defaultdict(list)
    
    for (job, sx, sy), group in by_job_section.items():
        if len(group) < 2:
            continue
        
        spacing = _compute_spacing_for_group(group)
        if spacing is None:
            continue
        
        # Filter: only include spacings smaller than field pitch (mosaic tiles)
        if dist_data is not None:
            if spacing < dist_data * 0.98:
                job_geometry_spacings[job].append(spacing)
        else:
            # Without DistanceData, include all computed spacings
            job_geometry_spacings[job].append(spacing)
    
    all_jobs = set(t["job_name"] for t in tiles_raw)
    job_tile_sizes = {}
    
    for job in all_jobs:
        geometry_spacings = job_geometry_spacings.get(job, [])
        
        if geometry_spacings:
            min_spacing = min(geometry_spacings)
            if overlap_fraction < 1.0:
                tile_size = min_spacing / (1.0 - overlap_fraction)
            else:
                tile_size = min_spacing
            job_tile_sizes[job] = tile_size
        # No fallback - tile size must come from API if it can't be derived from positions
    
    return job_tile_sizes


# â”€â”€â”€ Hardware Settings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_hardware_settings(lrp_root: ET.Element) -> Dict[str, Any]:
    """Parse hardware settings from LRP."""
    first_setting = lrp_root.find(".//ATLConfocalSettingDefinition")
    if first_setting is None:
        return {}

    serial_number = first_setting.get("SystemSerialNumber", "")
    system_type_raw = lrp_root.get("SystemType", "")

    # FilterWheels
    filter_wheels = []
    fw_elem = first_setting.find(".//FilterWheel")
    if fw_elem is not None:
        wheels_by_q: Dict[int, Dict] = {}
        for wheel in fw_elem.findall("Wheel"):
            q = to_int(wheel.get("Qualifier"))
            name = wheel.get("FilterWheelName", "")
            idx = to_int(wheel.get("FilterIndex"))
            fname = wheel.get("FilterName", "")
            disp = wheel.get("FilterDisplayName", "")
            if q not in wheels_by_q:
                wheels_by_q[q] = {
                    "Name": name, "Qualifier": q, "BeamRoute": "",
                    "CanDoSpectrum": False, "FilterNames": [],
                    "CurrentFilterIndex": idx, "CurrentFilterName": fname,
                }
            wheels_by_q[q]["FilterNames"].append(disp.strip() if disp else fname.strip())
        filter_wheels = list(wheels_by_q.values())

    # LightSources
    light_sources = []
    for aotf in first_setting.findall(".//AotfList/*"):
        src_name = aotf.get("LightSourceName", "")
        br = beam_route_str(aotf)
        min_dist = to_int(aotf.get("MinDistanceBetweenLines"))

        laser_lines = []
        for i, lls in enumerate(aotf.findall("LaserLineSetting")):
            la = lls.attrib
            line_index = to_int(la.get("LineIndex"))
            wl = to_float(la.get("LaserLine"))

            matching_laser = None
            for laser in first_setting.findall(".//LaserArray/Laser"):
                if laser.get("LightSourceName") == src_name:
                    l_wl = to_float(laser.get("Wavelength"))
                    if wl and l_wl and abs(l_wl - wl) < 0.5:
                        matching_laser = laser
                        break
                    elif laser.get("LaserName") == "WLL" and src_name.startswith("SuperCont"):
                        matching_laser = laser
                        break

            laser_name = ""
            can_change_output = False
            can_pulsing = False
            is_tuneable = False
            min_wl, max_wl = wl, wl
            min_power, max_power, power_unit = None, None, None

            if matching_laser is not None:
                laser_name = matching_laser.get("LaserName", "")
                can_change_output = parse_bool(matching_laser.get("CanDoLinearOutputPower")) or False
                can_pulsing = parse_bool(matching_laser.get("CanDoPulsing")) or False
                is_tuneable = parse_bool(matching_laser.get("CanDoChangeWavelength")) or False
                if is_tuneable or src_name.startswith("SuperCont"):
                    is_tuneable = True
                    can_change_output = True
                    can_pulsing = True
                    min_wl, max_wl = 440.0, 790.0
                    min_power, max_power, power_unit = 0.0, 100.0, "%"
            else:
                if wl:
                    laser_name = f"Laser {int(wl)}"

            line_entry: Dict[str, Any] = {
                "CanDoChangeOutputPower": can_change_output,
                "CanDoPulsing": can_pulsing,
                "Index": line_index if line_index is not None else i,
                "IsTuneable": is_tuneable,
                "LaserName": laser_name if laser_name else src_name,
                "MaxWavelength": max_wl,
                "MinWavelength": min_wl,
            }
            if min_power is not None:
                line_entry["MaxOutputPower"] = max_power
                line_entry["MinOutputPower"] = min_power
                line_entry["OutputPowerUnit"] = power_unit
            laser_lines.append(line_entry)

        is_aobs = src_name in ("Visible Light", "SuperContVisible Light")
        light_sources.append({
            "AotfType": "Regular AOTF", "BeamRoute": br, "IsAobsCoupling": is_aobs,
            "LaserLines": laser_lines, "MinDistanceBetweenLines": min_dist or 1, "name": src_name,
        })

    # LightSinks
    sinks_grouped: Dict[str, Dict] = {}
    seen_dets = set()
    for det in first_setting.findall(".//DetectorList/Detector"):
        name = det.get("Name")
        if name in seen_dets:
            continue
        seen_dets.add(name)
        a = det.attrib
        br_full = beam_route_str(det)
        level0 = beam_route_level(det, 0)
        group_key = level0 if level0 else "unknown"
        scan_type = a.get("ScanType", "")

        det_entry: Dict[str, Any] = {
            "BeamRoute": br_full,
            "CanDoPhotonCounting": parse_bool(a.get("CanDoPhotonCounting")) or False,
            "Name": name, "Type": a.get("Type", ""),
        }
        if scan_type == "Internal":
            det_entry["WaveLengthMinMargin"] = 5.0

        if group_key not in sinks_grouped:
            if scan_type == "Internal":
                sink_name, has_var, spec_type = "LightSink Internal", True, "Variable"
            elif scan_type == "TLD":
                sink_name, has_var, spec_type = "LightSink TLD Trans", False, "Fix"
            else:
                sink_name, has_var, spec_type = f"LightSink {group_key}", False, "Fix"

            sink_entry: Dict[str, Any] = {
                "BeamRoute": group_key, "DetectionUnits": [],
                "HasVariableSpectrum": has_var, "SpectrophotometerType": spec_type, "name": sink_name,
            }
            if has_var:
                sink_entry["SpectrumMaxWavelength"] = 850.0
                sink_entry["SpectrumMinWavelength"] = 410.0
            sinks_grouped[group_key] = sink_entry

        sinks_grouped[group_key]["DetectionUnits"].append(det_entry)

    light_sinks = list(sinks_grouped.values())

    # Microscope
    objectives_seen = set()
    objectives = []
    for setting in lrp_root.findall(".//ATLConfocalSettingDefinition"):
        obj_name = setting.get("ObjectiveName", "").strip()
        obj_num = setting.get("ObjectiveNumber", "")
        key = (obj_name, obj_num)
        if key in objectives_seen:
            continue
        objectives_seen.add(key)
        if obj_name:
            objectives.append({
                "Immersion": setting.get("Immersion", ""),
                "Magnification": to_float(setting.get("Magnification")),
                "NumericalAperture": to_float(setting.get("NumericalAperture")),
                "ObjectiveNumber": to_int(obj_num) if obj_num else None,
                "name": obj_name,
                "slotIndex": to_int(setting.get("ObjectivePos")),
            })

    microscope = {
        "AfcInstalled": parse_bool(first_setting.get("IsAutofocusActive")) or False,
        "name": first_setting.get("MicroscopeModel", ""),
        "objectives": objectives,
    }

    # ScanSpeed
    speeds = []
    resonant_speed = None
    for setting in lrp_root.findall(".//ATLConfocalSettingDefinition"):
        spd = to_float(setting.get("ScanSpeed"))
        if spd:
            speeds.append(spd)
        if parse_bool(setting.get("IsResonantScanner")):
            resonant_speed = 12000
    scan_speed: Dict[str, Any] = {
        "Max": int(max(speeds)) if speeds else None,
        "Min": int(min(speeds)) if speeds else None,
    }
    if resonant_speed:
        scan_speed["ResonantSpeed"] = resonant_speed

    return {
        "FilterWheels": filter_wheels, "LightSinks": light_sinks, "LightSources": light_sources,
        "Microscope": microscope, "ScanSpeed": scan_speed, "SerialNumber": serial_number,
        "SystemType": system_type_raw if system_type_raw and system_type_raw != "-1" else serial_number,
    }


# â”€â”€â”€ Acquisition Jobs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_acquisition_jobs(lrp_root: ET.Element) -> List[Dict[str, Any]]:
    """Parse acquisition jobs from LRP."""
    jobs = []

    for block in lrp_root.findall(".//LDM_Block_Sequence_Block"):
        if block.get("BlockType") != "1":
            continue

        seq = block.find(".//LDM_Block_Sequential")
        job_name = seq.get("BlockName") if seq is not None else None
        if not job_name:
            continue

        all_settings = block.findall(".//ATLConfocalSettingDefinition")
        if not all_settings:
            continue

        main_setting = all_settings[0]
        a = main_setting.attrib
        zoom = to_float(a.get("Zoom"))
        lines = to_int(a.get("Lines")) or 512
        in_dim = to_int(a.get("InDimension")) or lines
        out_dim = to_int(a.get("OutDimension")) or lines

        # Build activeSettings
        active_settings = []
        sub_settings = all_settings[1:] or [main_setting]

        for idx, sub_s in enumerate(sub_settings):
            sub_a = sub_s.attrib
            setting_name = sub_a.get("UserSettingName", f"Setting {idx + 1}")

            # Active detectors
            active_detectors = []
            for det in sub_s.findall(".//DetectorList/Detector"):
                if det.get("IsActive") != "1":
                    continue
                d_a = det.attrib
                br = beam_route_str(det)
                det_begin = to_float(d_a.get("DetectionRangeBegin"))
                det_end = to_float(d_a.get("DetectionRangeEnd"))
                gain_val = to_float(d_a.get("Gain"))

                ref_laser, ref_wl = None, None
                for aotf in sub_s.findall(".//AotfList/*"):
                    for lls in aotf.findall("LaserLineSetting"):
                        intensity = to_float(lls.get("IntensityDev"))
                        if intensity and intensity > 0:
                            ref_laser = f"Laser ({aotf.get('LightSourceName', '')})"
                            ref_wl = to_float(lls.get("LaserLine"))
                            break
                    if ref_laser:
                        break

                det_entry: Dict[str, Any] = {
                    "beamRoute": br, "detectionBegin": det_begin, "detectionEnd": det_end,
                    "detectionUnit": "nm", "dye": d_a.get("DyeName", "") or None,
                    "gain": {"max": gain_val, "min": gain_val, "value": gain_val},
                    "name": d_a.get("Name", ""),
                }
                if ref_laser and ref_wl:
                    det_entry["referenceLine"] = {"laser": ref_laser, "wavelength": ref_wl}
                active_detectors.append(det_entry)

            # Active laser lines
            active_laser_lines = []
            for aotf in sub_s.findall(".//AotfList/*"):
                src_name = aotf.get("LightSourceName", "")
                aotf_br = beam_route_str(aotf)

                shutter_open = False
                for sh in sub_s.findall(".//ShutterList/Shutter"):
                    if sh.get("LightSourceName") == src_name:
                        shutter_open = parse_bool(sh.get("IsActive")) or False
                        break

                for lls in aotf.findall("LaserLineSetting"):
                    intensity = to_float(lls.get("IntensityDev"))
                    if not intensity or intensity <= 0:
                        continue
                    wl = to_float(lls.get("LaserLine"))
                    line_idx = to_int(lls.get("LineIndex"))

                    active_laser_lines.append({
                        "beamRoute": aotf_br,
                        "intensity": {"background": 0.0, "max": 100.0, "min": 0.0, "value": intensity},
                        "laser": {"hasSecondShutter": False, "name": f"Laser ({src_name})"},
                        "lightSourceType": f"Light Source {src_name}",
                        "lineIndex": line_idx, "shutterOpen": shutter_open,
                        "wavelength": wl, "wavelengthUnit": "nm",
                    })

            pa = to_float(sub_a.get("PinholeAiry"))
            pinhole_entry = {"max": 7.07, "min": 0.24, "value": round(pa, 2)} if pa is not None else None

            setting_entry: Dict[str, Any] = {
                "activeDetectors": active_detectors, "activeLaserLines": active_laser_lines,
                "frameAccumulation": to_int(sub_a.get("FrameAccumulation")) or 1,
                "frameAverage": to_int(sub_a.get("FrameAverage")) or 1,
                "id": idx + 1, "index": idx,
                "lineAccumulation": to_int(sub_a.get("Line_Accumulation")) or 1,
                "lineAverage": to_int(sub_a.get("LineAverage")) or 1,
                "name": setting_name,
            }
            if pinhole_entry:
                setting_entry["pinholeAiry"] = pinhole_entry
            active_settings.append(setting_entry)

        # Job-level fields
        na_val = to_float(a.get("NumericalAperture"))
        mag_val = to_float(a.get("Magnification"))
        mot_corr = to_float(a.get("MotCorrPosition"))
        stage_x = to_float(a.get("StagePosX"))
        stage_y = to_float(a.get("StagePosY"))
        z_pos_m = to_float(a.get("ZPosition"))
        z_use_mode = to_int(a.get("ZUseMode"))
        z_use_name = a.get("ZUseModeName", "")
        rot_angle = to_float(a.get("RotatorAngle")) or 0.0
        scan_speed_val = to_float(a.get("ScanSpeed"))
        is_resonant = parse_bool(a.get("IsResonantScanner")) or False
        zoom_min = to_float(a.get("BaseZoom")) or 0.75
        seq_mode_int = to_int(seq.get("SequentialMode")) if seq is not None else 0
        seq_mode_names = {0: "Line", 1: "Frame", 2: "Stack"}

        z_um_str = f"{z_pos_m * 1e6:.2f}" if z_pos_m else "0.00"
        if z_use_mode == 1 or z_use_name == "z-galvo":
            z_position = {
                "z-galvo": {"id": 1, "position": z_um_str, "unit": "Âµm"},
                "z-wide": {"id": 2, "position": "8000.00", "unit": "Âµm"},
            }
        elif z_use_mode == 2 or z_use_name == "z-wide":
            z_position = {
                "z-galvo": {"id": 1, "position": "0.00", "unit": "Âµm"},
                "z-wide": {"id": 2, "position": z_um_str, "unit": "Âµm"},
            }
        else:
            z_position = {
                "z-galvo": {"id": 1, "position": z_um_str, "unit": "Âµm"},
                "z-wide": {"id": 2, "position": "8000.00", "unit": "Âµm"},
            }

        job_entry: Dict[str, Any] = {
            "activeSettings": active_settings,
            "autoFocus": {"isActive": parse_bool(a.get("IsAutofocusActive")) or False},
            "format": f"{in_dim} x {out_dim}",
            "id": to_int(block.get("BlockID")),
            "imageSize": None,  # Must be obtained from API connection
            "jobName": job_name,
            "objective": {
                "NA": na_val, "isMotCorr": (mot_corr is not None and mot_corr != 0),
                "magnification": mag_val, "name": a.get("ObjectiveName", ""),
            },
            "pixelSize": None,  # Must be obtained from API connection
            "scanFieldRotation": {"max": 100.0, "min": -100.0, "value": rot_angle},
            "scanMode": a.get("ScanMode", "xyz"),
            "scanSpeed": {"isResonant": is_resonant, "unit": "Hz", "value": int(scan_speed_val) if scan_speed_val else None},
            "sequentialMode": seq_mode_names.get(seq_mode_int, "Line"),
            "xyStage": {
                "posX": f"{stage_x * 1e6:.2f}" if stage_x else "0.00",
                "posY": f"{stage_y * 1e6:.2f}" if stage_y else "0.00",
                "unit": "Âµm",
            },
            "zPosition": z_position,
            "zoom": {"current": zoom, "max": 48.0, "min": zoom_min},
            "_tileSize_um": None,  # Must be obtained from API connection
        }
        jobs.append(job_entry)

    return jobs


# â”€â”€â”€ Matrix Settings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_matrix_settings(xml_root: ET.Element) -> Dict[str, Any]:
    """Parse MatrixData from XML."""
    md = xml_root.find(".//MatrixData")
    if md is None:
        return {}

    result: Dict[str, Any] = {}

    cod = md.find("CountOfData")
    if cod is not None and cod.get("IsEnabled") == "true":
        result["count"] = {
            "sectionsX": to_int(cod.get("SectionsX")), "sectionsY": to_int(cod.get("SectionsY")),
            "scanFieldsX": to_int(cod.get("ScanFieldsX")), "scanFieldsY": to_int(cod.get("ScanFieldsY")),
            "regionsX": to_int(cod.get("RegionsX")), "regionsY": to_int(cod.get("RegionsY")),
            "samplesX": to_int(cod.get("SamplesX")), "samplesY": to_int(cod.get("SamplesY")),
        }

    dd = md.find("DistanceData")
    if dd is not None and dd.get("IsEnabled") == "true":
        dist: Dict[str, Any] = {}
        origin = dd.find("Origin")
        if origin is not None and origin.get("IsEnabled") == "true":
            dist["origin"] = {
                "x_um": to_float(origin.get("OriginX")), "y_um": to_float(origin.get("OriginY")),
                "z_um": to_float(origin.get("OriginZ")), "unit": origin.get("Units", "Microns"),
            }
        for name in ("Section", "Field", "Region", "Sample"):
            elem = dd.find(name)
            if elem is not None and elem.get("IsEnabled") == "true":
                dist[name.lower()] = {
                    "distanceX_um": to_float(elem.get("DistanceX")),
                    "distanceY_um": to_float(elem.get("DistanceY")),
                    "distanceZ_um": to_float(elem.get("DistanceZ")),
                    "unit": elem.get("Units", "Microns"),
                }
        result["distances"] = dist

    cd = md.find("CarrierData")
    if cd is not None and cd.get("IsEnabled") == "true":
        carrier: Dict[str, Any] = {
            "description1": cd.get("Description1", ""),
            "description2": cd.get("Description2", ""),
            "rotationAngle": to_float(cd.get("RotationAngle")),
        }
        if cd.get("WellPlateTypeSelected") == "true":
            carrier["type"] = "WellPlate"
            carrier["selectedIndex"] = to_int(cd.get("SelectedWellplateTypeIndex"))
            carrier["carrierSize_um"] = {"width_um": 127760.0, "height_um": 85480.0, "note": "Standard SBS microplate footprint"}
        elif cd.get("SlideTypeSelected") == "true":
            carrier["type"] = "Slide"
            carrier["selectedIndex"] = to_int(cd.get("SelectedGlassTypeIndex"))
            carrier["carrierSize_um"] = {"width_um": 75000.0, "height_um": 25000.0, "note": "Standard microscope slide"}
        elif cd.get("DishTypeSelected") == "true":
            carrier["type"] = "Dish"
            carrier["selectedIndex"] = to_int(cd.get("SelectedDishTypeIndex"))
        elif cd.get("ChamberSlideTypeSelected") == "true":
            carrier["type"] = "ChamberSlide"
            carrier["selectedIndex"] = to_int(cd.get("SelectedChamberSlideTypeIndex"))
        elif cd.get("SingleGridCartridgeTypeSelected") == "true":
            carrier["type"] = "SingleGridCartridge"
            carrier["selectedIndex"] = to_int(cd.get("SelectedGridTypeIndex"))
        elif cd.get("AutoGridCartridgeTypeSelected") == "true":
            carrier["type"] = "AutoGridCartridge"
            carrier["selectedIndex"] = to_int(cd.get("SelectedGridTypeIndex"))
        result["carrier"] = carrier

    tld = md.find("TimeLapseData")
    if tld is not None and tld.get("IsEnabled") == "true":
        result["timeLapse"] = {
            "repeatLoops": to_int(tld.get("RepeatLoops")),
            "repeatTimeDays": to_int(tld.get("RepeatTimeDays")),
            "repeatTimeHours": to_int(tld.get("RepeatTimeHours")),
            "repeatTimeMinutes": to_int(tld.get("RepeatTimeMinutes")),
            "runTime": tld.get("RunTime", ""),
        }

    afd = md.find("AutofocusData")
    if afd is not None:
        result["autofocus"] = {"zUseMode": afd.get("ZUseMode", ""), "forecastMode": to_int(afd.get("AFForecastMode"))}

    cfd = md.find("ConfocalData")
    if cfd is not None:
        rot = to_float(cfd.get("FieldRotation"))
        if rot is not None:
            result["fieldRotation"] = rot

    return result


# â”€â”€â”€ Focus Points from RGN â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_focus_points_from_rgn(rgn_path: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse focus points and autofocus points from RGN file."""
    if not rgn_path or not Path(rgn_path).exists():
        return [], []
    
    try:
        rgn_root = ET.parse(rgn_path).getroot()
    except Exception:
        return [], []
    
    focus_points, autofocus_points = [], []
    seen_ids = set()

    for item in rgn_root.findall(".//ShapeList/Items/*"):
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
        if verts is not None:
            v0 = verts.find("Item0")
            if v0 is not None:
                x = to_float(v0.findtext("X"))
                y = to_float(v0.findtext("Y"))
                z = to_float(v0.findtext("Z")) or 0.0
                if x is not None and y is not None:
                    point_data = {
                        "identifier": ident, "tag": tag, "type": shape_type,
                        "x_um": round(x * 1e6, 4), "y_um": round(y * 1e6, 4),
                        "z_um": round(z * 1e6, 4), "enabled": True,
                    }
                    if shape_type == "AutoFocusPoint":
                        autofocus_points.append(point_data)
                    else:
                        focus_points.append(point_data)

    for fp_elem in rgn_root.findall(".//FocusMap/FocusPoint"):
        ident = fp_elem.get("Identifier")
        if not ident or ident in seen_ids:
            continue
        x = to_float(fp_elem.get("X"))
        y = to_float(fp_elem.get("Y"))
        z = to_float(fp_elem.get("Z")) or 0.0
        enabled = fp_elem.get("Enabled", "true").lower() == "true"
        if x is not None and y is not None:
            focus_points.append({
                "identifier": ident, "tag": "", "type": "FocusPoint",
                "x_um": round(x * 1e6, 4), "y_um": round(y * 1e6, 4),
                "z_um": round(z * 1e6, 4), "enabled": enabled,
            })
            seen_ids.add(ident)
    
    return focus_points, autofocus_points


# â”€â”€â”€ Geometries from RGN â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_rgn_geometries(rgn_path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """Parse geometry information from RGN file with visualization properties."""
    if not rgn_path or not Path(rgn_path).exists():
        return {}
    
    try:
        rgn_root = ET.parse(rgn_path).getroot()
    except Exception:
        return {}
    
    regions: Dict[str, Dict[str, Any]] = {}
    
    for item in rgn_root.findall(".//ShapeList/Items/*"):
        type_elem = item.find("Type")
        if type_elem is None:
            continue
        stype = type_elem.text
        if stype in ("FocusPoint", "AutoFocusPoint", "Point"):
            continue
        
        ident = (item.findtext("Identifier") or "").strip()
        if not ident:
            continue
        
        vertices = []
        vert_items = item.find(".//Verticies/Items")
        if vert_items is not None:
            for vi in vert_items:
                x = to_float(vi.findtext("X"))
                y = to_float(vi.findtext("Y"))
                if x is not None and y is not None:
                    vertices.append({"x_um": round(x * 1e6, 4), "y_um": round(y * 1e6, 4)})
        
        geom: Dict[str, Any] = {
            "type": stype,
            "vertices_um": vertices,
            "label": item.findtext("LabelText"),
            "tag": item.findtext("Tag"),
            "tile_color_raw": item.findtext("TileColor"),
        }
        
        # Compute visualization properties
        if stype == "Ellipse" and len(vertices) >= 4:
            x0, y0 = vertices[0]["x_um"], vertices[0]["y_um"]
            x1, y1 = vertices[1]["x_um"], vertices[1]["y_um"]
            x2, y2 = vertices[2]["x_um"], vertices[2]["y_um"]
            x3, y3 = vertices[3]["x_um"], vertices[3]["y_um"]
            geom["center_um"] = {"x_um": round((x0 + x1) / 2, 4), "y_um": round((y0 + y1) / 2, 4)}
            geom["semi_axis_a_um"] = round(math.hypot(x1 - x0, y1 - y0) / 2, 4)
            geom["semi_axis_b_um"] = round(math.hypot(x2 - x3, y2 - y3) / 2, 4)
        
        elif stype == "CircleDiameter" and len(vertices) >= 2:
            x0, y0 = vertices[0]["x_um"], vertices[0]["y_um"]
            x1, y1 = vertices[1]["x_um"], vertices[1]["y_um"]
            geom["center_um"] = {"x_um": round((x0 + x1) / 2, 4), "y_um": round((y0 + y1) / 2, 4)}
            geom["radius_um"] = round(math.hypot(x1 - x0, y1 - y0) / 2, 4)
        
        elif stype == "Rectangle" and len(vertices) >= 4:
            xs = [v["x_um"] for v in vertices[:4]]
            ys = [v["y_um"] for v in vertices[:4]]
            geom["bounding_box_um"] = {
                "x_min_um": round(min(xs), 4), "y_min_um": round(min(ys), 4),
                "x_max_um": round(max(xs), 4), "y_max_um": round(max(ys), 4),
                "width_um": round(max(xs) - min(xs), 4), "height_um": round(max(ys) - min(ys), 4),
            }
            geom["center_um"] = {"x_um": round((min(xs) + max(xs)) / 2, 4), "y_um": round((min(ys) + max(ys)) / 2, 4)}
        
        elif stype in ("AreaLine", "Polygon", "MagicWand") and len(vertices) >= 3:
            xs = [v["x_um"] for v in vertices]
            ys = [v["y_um"] for v in vertices]
            geom["bounding_box_um"] = {
                "x_min_um": round(min(xs), 4), "y_min_um": round(min(ys), 4),
                "x_max_um": round(max(xs), 4), "y_max_um": round(max(ys), 4),
            }
            geom["centroid_um"] = {"x_um": round(sum(xs) / len(xs), 4), "y_um": round(sum(ys) / len(ys), 4)}
        
        regions[ident] = geom
    
    return regions


def parse_rgn_tile_colors(rgn_path: Optional[str]) -> Dict[str, Tuple[float, float, float, float]]:
    """Extract tile colors per job name from RGN."""
    if not rgn_path or not Path(rgn_path).exists():
        return {}
    
    try:
        rgn_root = ET.parse(rgn_path).getroot()
    except Exception:
        return {}
    
    job_colors: Dict[str, Tuple[float, float, float, float]] = {}
    
    for item in rgn_root.findall(".//ShapeList/Items/*"):
        name_text = item.findtext("n") or ""
        tile_color = item.findtext("TileColor") or ""
        label_text = item.findtext("LabelText") or ""
        
        jn = None
        if name_text.startswith("{"):
            try:
                nd = json.loads(name_text)
                jn = nd.get("JN", "")
            except:
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
                r, g, b, a = parts.get("R", 128), parts.get("G", 128), parts.get("B", 128), parts.get("A", 100)
                job_colors[jn] = (r / 255.0, g / 255.0, b / 255.0, a / 100.0)
            except:
                pass
    
    return job_colors


# â”€â”€â”€ Pattern & Lightning Jobs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_pattern_sequences(lrp_root: ET.Element) -> Dict[str, str]:
    """Parse pattern sequences from LRP."""
    block_id_to_name = {}
    for block in lrp_root.findall(".//LDM_Block_Sequence_Block"):
        if block.get("BlockType") != "1":
            continue
        block_id = block.get("BlockID")
        seq = block.find(".//LDM_Block_Sequential")
        if seq is not None and block_id:
            block_id_to_name[block_id] = seq.get("BlockName")
    
    patterns = {}
    for seq in lrp_root.findall(".//LDM_Block_Sequence"):
        pattern_name = seq.get("BlockName")
        if not pattern_name:
            continue
        elements = seq.findall(".//LDM_Block_Sequence_Element")
        if not elements:
            continue
        job_refs = [block_id_to_name[elem.get("BlockID")] for elem in elements 
                    if elem.get("BlockID") in block_id_to_name]
        if job_refs:
            patterns[pattern_name] = job_refs[-1]
    
    return patterns


def parse_lightning_jobs(lrp_root: ET.Element) -> set:
    """Find Lightning/THUNDER jobs (BlockType=22) to skip."""
    lightning_jobs = set()
    for block in lrp_root.findall(".//LDM_Block_Sequence_Block"):
        if block.get("BlockType") == "22":
            seq = block.find(".//LDM_Block_Sequential")
            if seq is not None:
                job_name = seq.get("BlockName")
                if job_name:
                    lightning_jobs.add(job_name)
    return lightning_jobs



# ——— Geometry Clipping ————————————————————————————————————————————————————

def _point_inside_geometry(x: float, y: float, geom: Dict[str, Any]) -> bool:
    """
    Check if a point (tile center) is inside a geometry shape.

    LAS X generates a bounding rectangle of tiles for every geometry,
    but only acquires/displays tiles whose centers fall inside the shape.
    This function replicates that clipping behaviour.
    """
    gtype = geom.get("type", "")

    if gtype == "Ellipse":
        center = geom.get("center_um")
        sa = geom.get("semi_axis_a_um", 0)
        sb = geom.get("semi_axis_b_um", 0)
        if center and sa > 0 and sb > 0:
            dx = (x - center["x_um"]) / sa
            dy = (y - center["y_um"]) / sb
            return (dx * dx + dy * dy) <= 1.0
        return True  # can't clip without geometry data

    elif gtype == "CircleDiameter":
        center = geom.get("center_um")
        radius = geom.get("radius_um", 0)
        if center and radius > 0:
            return math.hypot(x - center["x_um"], y - center["y_um"]) <= radius
        return True

    elif gtype in ("AreaLine", "Polygon", "MagicWand"):
        verts = geom.get("vertices_um", [])
        if len(verts) < 3:
            return True
        # Ray-casting point-in-polygon
        n = len(verts)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = verts[i]["x_um"], verts[i]["y_um"]
            xj, yj = verts[j]["x_um"], verts[j]["y_um"]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    # Rectangle or unknown — no clipping needed
    return True


# â”€â”€â”€ Acquisition Positions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_acquisition_positions(xml_root, rgn_geometries, job_tile_sizes, skip_jobs=None):
    """Parse tile positions from XML and group them."""
    tiles_raw = _get_raw_tiles(xml_root, skip_jobs)
    
    groups_raw = defaultdict(list)
    for t in tiles_raw:
        groups_raw[(t["section_x"], t["section_y"])].append(t)

    sorted_keys = sorted(groups_raw.keys(), key=lambda k: (k[1], k[0]))
    section_xs = sorted(set(k[0] for k in sorted_keys))
    section_ys = sorted(set(k[1] for k in sorted_keys))

    groups_out = {}
    for gi, key in enumerate(sorted_keys):
        sx, sy = key
        tiles = groups_raw[key]
        jn = tiles[0]["job_name"]
        ts = job_tile_sizes.get(jn)  # None if not derivable from positions (API must provide)
        h = ts / 2.0 if ts is not None else 0.0

        # Determine geometry for this group
        uids = set(t["unique_id"] for t in tiles)
        geom_id = next((uid for uid in uids if uid in rgn_geometries), None)

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
                "acquisition_order": ao, "row": tr, "col": tc,
                "x_um": round(t["x_um"], 4), "y_um": round(t["y_um"], 4),
                "z_um": round(t["z_um"], 4), "scan_order_original": t["scan_order"],
                "rotation": t["rotation"],
            }
            if ts is not None:
                pos_entry["bounding_box"] = {
                    "x_min_um": round(t["x_um"] - h, 4), "y_min_um": round(t["y_um"] - h, 4),
                    "x_max_um": round(t["x_um"] + h, 4), "y_max_um": round(t["y_um"] + h, 4),
                }
            positions.append(pos_entry)

        group_entry = {
            "section_x": sx, "section_y": sy,
            "group_row": section_ys.index(sy), "group_col": section_xs.index(sx),
            "job_name": jn, "tile_size_um": round(ts, 4) if ts is not None else None,
            "num_tiles": len(positions), "num_rows": len(fy_vals), "num_cols": len(fx_vals),
            "geometry_id": geom_id,
            "positions": positions,
        }
        if ts is not None:
            group_entry["group_bounding_box"] = {
                "x_min_um": round(min(ax) - h, 4), "y_min_um": round(min(ay) - h, 4),
                "x_max_um": round(max(ax) + h, 4), "y_max_um": round(max(ay) + h, 4),
            }
        groups_out[str(gi)] = group_entry
    return groups_out


# â"€â"€â"€ Focus Point Assignment â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

from ...utils.acquisition_path_planning import assign_focus_points_to_groups  # noqa: F401


# â”€â”€â”€ Main Parser Function â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_template(xml_path, lrp_path, rgn_path=None):
    """
    Parse LAS X template files.
    
    Args:
        xml_path: Path to .xml file
        lrp_path: Path to .lrp file
        rgn_path: Optional path to .rgn file
    
    Returns:
        Dict with parsed data (self-contained for visualization)
    """
    xml_root = ET.parse(xml_path).getroot()
    lrp_root = ET.parse(lrp_path).getroot()

    # Get DistanceData (field pitch from XML, used for spacing analysis)
    dist_data = xml_root.find(".//DistanceData")
    base_field_pitch_um = None
    if dist_data is not None:
        field = dist_data.find(".//Field[@IsEnabled='true']")
        if field is not None:
            fx = to_float(field.get("DistanceX"))
            fy = to_float(field.get("DistanceY"))
            if fx and fy:
                base_field_pitch_um = (fx + fy) / 2.0

    # Parse MosaicOverlapInPercent
    mosaic_overlap_pct = 5.0
    overlap_elem = xml_root.find(".//MosaicOverlapInPercent")
    if overlap_elem is not None and overlap_elem.text:
        mosaic_overlap_pct = to_float(overlap_elem.text) or 5.0

    # Find Lightning jobs to skip
    lightning_jobs = parse_lightning_jobs(lrp_root)

    # Get raw tiles and derive tile sizes
    tiles_raw = _get_raw_tiles(xml_root, skip_jobs=lightning_jobs)
    job_tile_sizes = derive_tile_sizes_from_positions(tiles_raw, base_field_pitch_um, mosaic_overlap_pct)

    # Map patterns to jobs
    pattern_map = parse_pattern_sequences(lrp_root)
    for pattern_name, last_job_name in pattern_map.items():
        if last_job_name in job_tile_sizes and pattern_name not in job_tile_sizes:
            job_tile_sizes[pattern_name] = job_tile_sizes[last_job_name]

    # Parse components
    hw = parse_hardware_settings(lrp_root)
    jobs_list = parse_acquisition_jobs(lrp_root)

    # Extract tile sizes and build jobs dict
    for j in jobs_list:
        jn = j["jobName"]
        j.pop("_tileSize_um", None)  # Remove placeholder
        ts = job_tile_sizes.get(jn)  # From position derivation only, None if unavailable
        j["tileSize_um"] = round(ts, 4) if ts is not None else None
        if ts is not None:
            job_tile_sizes[jn] = ts

    jobs_dict = {j["jobName"]: j for j in jobs_list}

    # Parse RGN data
    rgn_geometries = parse_rgn_geometries(rgn_path)
    focus_points, autofocus_points = parse_focus_points_from_rgn(rgn_path)
    tile_colors = parse_rgn_tile_colors(rgn_path)

    # Parse positions
    positions = parse_acquisition_positions(xml_root, rgn_geometries, job_tile_sizes, skip_jobs=lightning_jobs)

    # Assign focus points to groups
    fpa = assign_focus_points_to_groups(focus_points, positions)
    for gid, g in positions.items():
        g["focus_points"] = fpa.get(gid, [])

    afpa = assign_focus_points_to_groups(autofocus_points, positions)
    for gid, g in positions.items():
        g["autofocus_points"] = afpa.get(gid, [])

    # Parse matrix settings
    matrix = parse_matrix_settings(xml_root)

    # Build visualization data
    tile_colors_serializable = {k: list(v) for k, v in tile_colors.items()}
    viz_data = {
        "tile_colors": tile_colors_serializable,
        "distance_data_um": base_field_pitch_um,
        "mosaic_overlap_pct": mosaic_overlap_pct,
        "job_tile_sizes": {k: round(v, 4) for k, v in job_tile_sizes.items()},
    }

    return {
        "hardware_settings": hw,
        "acquisition_jobs": jobs_dict,
        "matrix_settings": matrix,
        "acquisition_positions": positions,
        "focus_points": focus_points,
        "autofocus_points": autofocus_points,
        "geometries": rgn_geometries,
        "visualization_data": viz_data,
    }


# â”€â”€â”€ CLI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python lasx_parser.py <xml_path> <lrp_path> [rgn_path] [output.json]")
        sys.exit(1)
    
    xml_path = sys.argv[1]
    lrp_path = sys.argv[2]
    rgn_path = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].endswith('.json') else None
    output_path = sys.argv[-1] if sys.argv[-1].endswith('.json') else "lasx_output.json"
    
    result = parse_template(xml_path, lrp_path, rgn_path)
    
    # Print summary
    n_jobs = len(result["acquisition_jobs"])
    n_groups = len(result["acquisition_positions"])
    n_tiles = sum(len(g["positions"]) for g in result["acquisition_positions"].values())
    n_fps = len(result["focus_points"])
    n_afps = len(result["autofocus_points"])
    n_geoms = len(result["geometries"])
    
    print(f"âœ“ Parsed successfully:")
    print(f"  {n_jobs} acquisition job(s): {', '.join(result['acquisition_jobs'].keys())}")
    print(f"  {n_groups} position group(s) with {n_tiles} total tiles")
    print(f"  {n_fps} focus point(s), {n_afps} autofocus point(s)")
    print(f"  {n_geoms} geometr(y/ies)")
    
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"âœ“ JSON saved to {output_path}")
