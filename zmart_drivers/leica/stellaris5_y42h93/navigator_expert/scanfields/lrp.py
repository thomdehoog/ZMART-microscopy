"""LRP job/hardware-settings parsers — the LAS X ``.lrp`` job settings tree.

Parses a LAS X ``.lrp`` file into a structured dict organized by job
(detectors, lasers, AOTFs, shutters, spectral windows, filter wheels,
light sources, LUTs, autofocus config, z-positions, ROIs, STED).

Dependency direction:
    - Imports: stdlib + ``_convert`` (shared converters).
    - Imported by: ``parsers`` (``_get_job_names``), ``files``,
      ``__init__`` (re-export).
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from ._convert import _to_float


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


def _parse_with_beam_route(el):
    """Parse an element's attributes plus its optional BeamRoute.

    Shared by the LRP element kinds whose only structure is attributes and
    an optional ``BeamRoute`` (lasers, shutters, spectral windows, LUTs).
    """
    d = dict(el.attrib)
    beam = _parse_beam_route(el)
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
            lasers.append(_parse_with_beam_route(laser))
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
            shutters.append(_parse_with_beam_route(sh))
        if shutters:
            result["_Shutters"] = shutters

    spectro = setting_el.find("Spectro")
    if spectro is not None:
        multibands = []
        for mb in spectro.findall("MultiBand"):
            multibands.append(_parse_with_beam_route(mb))
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
            luts.append(_parse_with_beam_route(lut))
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
