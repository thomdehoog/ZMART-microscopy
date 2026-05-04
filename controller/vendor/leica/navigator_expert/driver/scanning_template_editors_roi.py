"""
ROI scanning template editors.
================================
Editors for scan-ROI manipulation: enable/disable ROI scanning,
clear existing ROIs, add new ROI shapes (polygon, rectangle, ellipse,
line), and verify ROI state.

Writing strategy: ROI editors use ``ET.parse`` + ``tree.write()``
because adding/removing elements is structural XML manipulation (not
simple attribute replacement).  ``apply_lrp_change`` does
save → edit → load → save, so LAS X rewrites the file anyway — the
verify step checks the LAS X-saved version.

Coordinate systems
------------------

**Vertex coordinates** are in **metres relative to the scan field
centre** (origin at (0, 0)), matching the LAS X internal format.
Use ``um(x)`` to convert from micrometres.

In the display frame:

- **Positive X = right** on screen.
- **Positive Y = down** on screen.

**Pixel → vertex mapping** (for segmentation contours etc.)::

    vx = (col - image_center) * pixel_size_m
    vy = (row - image_center) * pixel_size_m

This mapping requires **ImageTransformation = TOPLEFT** (or
``EnableImageTransformation = false``) in the LAS X MatrixScreener
settings (Advanced Settings > Calibration Of Orientation).  With
any other orientation (e.g. RIGHTTOP) the saved TIFF is rotated
relative to the display and the mapping breaks.

``RotatorAngle``, ``FlipX``, and ``FlipY`` from the LRP describe the
*physical* scan direction on the sample but do **not** affect the
pixel ↔ ROI vertex relationship — both live in the same display frame.

Check the setting at runtime via::

    s = get_lasx_settings()  # from lasx.readers
    orient = s["image_orientation"]
    # orient["enable_transform"]  → bool
    # orient["transformation"]    → "TOPLEFT", "RIGHTTOP", etc.

**ROI Translation** coordinate system (solved 2026-03-15):

    Translation is the ROI position as an offset from the **stage
    centre** (not the scan field centre), with the X axis negated::

        roi_abs_x = stage_x_um - translation_x_um
        roi_abs_y = stage_y_um + translation_y_um
        pan_x     = -translation_x_um / pan_scale_um
        pan_y     = +translation_y_um / pan_scale_um

    where ``pan_scale_um`` is objective-dependent (see ``utils.py``:
    ``pan_scale_um = base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT``).

    Use ``roi_translation_to_pan()`` and ``roi_to_absolute_um()``
    for conversions — the former takes ``pan_scale_um`` as a required
    kwarg.

**Critical ordering rule** (solved 2026-04-23): when applying pan via
``apply_lrp_change`` + ``lrp_set_pan``, call ``set_zoom(target_zoom)``
FIRST and write the pan AFTER. If zoom is changed after the pan write,
LAS X silently re-clamps pan during the zoom transition (observed on
40× DRY: target pan_y = 0.00431 trimmed to 0.00194). The manual GUI
arrow buttons take a different path and do not clamp — so this is an
API-path issue, not a hardware limit. No error is raised; only the
readback reveals the clamp. See ``feedback_pan_then_zoom_clamps.md``.

**Important:** ROI sizes must match the current scan field (FOV).
Use ``get_fov()`` from ``readers`` to query the FOV in metres,
then size shapes as a fraction of it::

    from lasx.readers import get_fov
    from lasx.scanning_template_editors_roi import make_star, lrp_add_roi, um

    fov_w, fov_h = get_fov(client, "HiRes")   # e.g. (2.9e-5, 2.9e-5)
    verts = make_star(outer_radius=fov_w * 0.4,
                      inner_radius=fov_w * 0.16)
    lrp_add_roi(lrp_path, "HiRes", ROI_POLYGON, verts)

RoiType values: ``8`` = polygon, ``16`` = rectangle, ``32`` = ellipse,
``64`` = line.

Dependency direction:
    - Imports: ``scanning_template_editors`` (helpers),
      ``scanning_template_parsers`` (parse_lrp), stdlib.
    - Imported by: ``__init__`` (re-export).
"""

import copy
import logging
import math
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .scanning_template_editors import (
    _set_job_attr,
    _verify_job_attr,
)
from .scanning_template_parsers import parse_lrp

log = logging.getLogger(__name__)

# Unit conversion
def um(value):
    """Convert micrometres to metres (LAS X coordinate unit)."""
    return value * 1e-6


# RoiType constants
ROI_POLYGON = "8"
ROI_RECTANGLE = "16"
ROI_ELLIPSE = "32"
ROI_LINE = "64"


# =============================================================================
# Color helper
# =============================================================================

def argb_color(r, g, b, a=255):
    """Convert RGBA components (0–255) to a LAS X uint32 color string.

    LAS X stores colors as ARGB uint32 decimal strings.

    Returns:
        String like ``"4294901760"`` (red).
    """
    return str((a << 24) | (r << 16) | (g << 8) | b)


# Well-known colors
COLOR_RED = argb_color(255, 0, 0)        # "4294901760"
COLOR_GREEN = argb_color(0, 255, 0)      # "4278255360"
COLOR_BLUE = argb_color(0, 0, 255)       # "4278190335"
COLOR_YELLOW = argb_color(255, 255, 0)   # "4294967040"


# =============================================================================
# Enable / disable ROI scanning
# =============================================================================

def lrp_enable_roi_scan(lrp_path, enable, job_name):
    """Enable or disable ROI scanning for a job.

    Sets ``IsRoiScanEnable`` on all ``ATLConfocalSettingDefinition``
    elements in the job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        enable: ``True`` to enable, ``False`` to disable.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    val = "1" if enable else "0"
    return _set_job_attr(lrp_path, "IsRoiScanEnable", val, job_name,
                         "lrp_enable_roi_scan")


def disable_roi_scan(client, job_name):
    """Atomic LRP edit: turn ROI scan off for *job_name*.

    Required before any pan/zoom that should illuminate the full FOV
    — when ROI scan is on the scanner only paints inside the ROI
    polygons, so a panned-but-still-roi-scanning frame appears black
    where the cells used to be. Verifies the change before returning.
    """
    from .scanning_templates import TEMPLATE_XML, apply_lrp_change
    apply_lrp_change(
        client, TEMPLATE_XML,
        lambda p: lrp_enable_roi_scan(p, False, job_name),
        verify_fn=lambda p: lrp_verify_roi_scan(p, False, job_name),
    )


def lrp_verify_roi_scan(lrp_path, enable, job_name):
    """Verify IsRoiScanEnable for a job (exact match)."""
    val = "1" if enable else "0"
    return _verify_job_attr(lrp_path, "IsRoiScanEnable", val, job_name)


# =============================================================================
# XML tree helpers
# =============================================================================

def _find_job_block(root, job_name):
    """Find the LDM_Block_Sequence_Block for a job name."""
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            return b
    return None


def _find_master_setting(block):
    """Find the Master ATLConfocalSettingDefinition in a block."""
    return block.find(".//LDM_Block_Sequential_Master/"
                      "ATLConfocalSettingDefinition")


def _find_dcroiset_children(setting_el):
    """Find or create the DCROISet/Children element.

    Returns the Children element, or None if the ROI structure is
    missing entirely.
    """
    roi = setting_el.find("ROI")
    if roi is None:
        return None
    header = roi.find("LMSDataContainerHeader")
    if header is None:
        return None
    for elem in header.findall("Element"):
        if elem.get("Name") == "DCROISet":
            children = elem.find("Children")
            if children is None:
                children = ET.SubElement(elem, "Children")
            return children
    return None


def lrp_find_aotf_template(root):
    """Find an existing AOTF Attachment element to copy into new ROIs.

    Searches all existing ROISingle elements for an ``<Attachment>``
    with ``Name="AOTF_SETTING"`` and returns a deep copy.  Returns
    None if no AOTF attachment is found.
    """
    for rs in root.findall(".//ROISingle"):
        for att in rs.findall("Attachment"):
            if att.get("Name") == "AOTF_SETTING":
                return copy.deepcopy(att)
    return None


# =============================================================================
# Clear ROIs
# =============================================================================

def lrp_clear_rois(lrp_path, job_name):
    """Remove all ROI Elements from DCROISet/Children in Master.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        job_name: Name of the job to modify.

    Returns:
        Number of ROI elements removed.
    """
    lrp_path = Path(lrp_path)
    tree = ET.parse(lrp_path)
    root = tree.getroot()

    block = _find_job_block(root, job_name)
    if block is None:
        log.error("lrp_clear_rois: job '%s' not found", job_name)
        return 0

    setting = _find_master_setting(block)
    if setting is None:
        log.error("lrp_clear_rois: no Master setting for job '%s'", job_name)
        return 0

    children = _find_dcroiset_children(setting)
    if children is None:
        log.warning("lrp_clear_rois: no DCROISet/Children for job '%s'", job_name)
        return 0

    elements = list(children)
    count = len(elements)
    for el in elements:
        children.remove(el)

    if count > 0:
        tree.write(lrp_path, encoding="utf-8", xml_declaration=True)

    log.info("lrp_clear_rois: job='%s', removed %d ROI element(s)",
             job_name, count)
    return count


# =============================================================================
# Shape helpers
# =============================================================================

def make_rectangle(width, height, center_x=0.0, center_y=0.0):
    """Generate vertices for a rectangle.

    Coordinates are in metres.  Size relative to the FOV using
    ``get_fov()``::

        fov_w, fov_h = get_fov(client, job_name)
        verts = make_rectangle(fov_w * 0.5, fov_h * 0.5)

    Args:
        width: Width in metres.
        height: Height in metres.
        center_x: Centre X in metres (default 0).
        center_y: Centre Y in metres (default 0).

    Returns:
        List of ``(x, y)`` tuples (4 corners, clockwise from top-left).
    """
    hw = width / 2.0
    hh = height / 2.0
    return [
        (center_x - hw, center_y - hh),
        (center_x + hw, center_y - hh),
        (center_x + hw, center_y + hh),
        (center_x - hw, center_y + hh),
    ]


def make_ellipse(radius_x, radius_y, center_x=0.0, center_y=0.0,
                 n_points=100):
    """Generate vertices approximating an ellipse.

    Coordinates are in metres (use ``um()`` to convert).

    Args:
        radius_x: Semi-axis X in metres.
        radius_y: Semi-axis Y in metres.
        center_x: Centre X in metres (default 0).
        center_y: Centre Y in metres (default 0).
        n_points: Number of polygon vertices (default 100).

    Returns:
        List of ``(x, y)`` tuples.
    """
    verts = []
    for i in range(n_points):
        angle = 2.0 * math.pi * i / n_points
        verts.append((center_x + radius_x * math.cos(angle),
                      center_y + radius_y * math.sin(angle)))
    # Close the polygon by repeating the first vertex
    verts.append(verts[0])
    return verts


def make_polygon(vertices):
    """Pass through a list of ``(x, y)`` tuples as-is.

    This is a convenience wrapper that validates the input format.

    Args:
        vertices: List of ``(x, y)`` tuples in metres.

    Returns:
        The same list.
    """
    return list(vertices)


def make_star(n_points=5, outer_radius=None, inner_radius=None,
              center_x=0.0, center_y=0.0):
    """Generate vertices for an *n*-pointed star.

    Alternates between outer and inner radii, starting from the top
    (12 o'clock), clockwise — matching LAS X ROI vertex order.

    Coordinates are in **metres**.  Size relative to the FOV using
    ``get_fov()``::

        fov_w, _ = get_fov(client, job_name)
        verts = make_star(outer_radius=fov_w * 0.4,
                          inner_radius=fov_w * 0.16)

    Defaults to ``um(5)`` / ``um(2)`` which is only visible at
    high zoom (~40x).

    Args:
        n_points: Number of star points (default 5).
        outer_radius: Outer radius in metres (default ``um(5)``).
        inner_radius: Inner radius in metres (default ``um(2)``).
        center_x: Centre X in metres (default 0).
        center_y: Centre Y in metres (default 0).

    Returns:
        List of ``(x, y)`` tuples (``2 * n_points + 1`` vertices,
        last repeats first to close the polygon).
    """
    if outer_radius is None:
        outer_radius = um(5)
    if inner_radius is None:
        inner_radius = um(2)
    verts = []
    total = 2 * n_points
    for i in range(total):
        # Clockwise from top (negative angle direction)
        angle = -math.pi / 2 - 2.0 * math.pi * i / total
        r = outer_radius if i % 2 == 0 else inner_radius
        verts.append((center_x + r * math.cos(angle),
                      center_y + r * math.sin(angle)))
    # Close the polygon by repeating the first vertex
    verts.append(verts[0])
    return verts


def make_line(x1, y1, x2, y2):
    """Generate vertices for a line (two endpoints).

    Coordinates are in metres (use ``um()`` to convert).

    Args:
        x1, y1: Start point in metres.
        x2, y2: End point in metres.

    Returns:
        List of two ``(x, y)`` tuples.
    """
    return [(x1, y1), (x2, y2)]


# =============================================================================
# Vertex centring
# =============================================================================

def center_vertices(vertices):
    """Re-centre vertices around their centroid.

    LAS X requires the ROI position to be stored in the Translation
    field, with vertices relative to the centroid.  Without this,
    ROI scan only illuminates one ROI instead of all.

    Args:
        vertices: List of ``(x, y)`` tuples in metres.

    Returns:
        ``(centered_vertices, (cx, cy))`` — vertices shifted so
        their centroid is ``(0, 0)``, and the centroid as a tuple
        suitable for the ``translation`` parameter of ``lrp_add_roi``.
    """
    n = len(vertices)
    cx = sum(v[0] for v in vertices) / n
    cy = sum(v[1] for v in vertices) / n
    centered = [(v[0] - cx, v[1] - cy) for v in vertices]
    return centered, (cx, cy)


def pixels_to_roi(contour, image_center, pixel_size_m, close=True):
    """Convert pixel contour to centred ROI vertices + translation.

    Converts a contour from pixel coordinates (e.g. from
    ``skimage.measure.find_contours``) to the format needed by
    ``lrp_add_roi``: vertices in metres centred on the shape
    centroid, plus a translation that positions the shape in the
    scan field.

    Requires **ImageTransformation = TOPLEFT** (or
    ``EnableImageTransformation = false``) in LAS X settings.

    Args:
        contour: Array-like of ``(row, col)`` pixel coordinates
            (the format returned by ``find_contours``).
        image_center: Image centre in pixels (typically ``width / 2``).
        pixel_size_m: Pixel size in metres.
        close: If ``True`` (default), append the first vertex to
            close the polygon when the gap exceeds half a pixel.

    Returns:
        ``(vertices_m, translation_m)`` — centred vertices in metres
        and ``(tx, ty)`` translation for ``lrp_add_roi``.
    """
    # Pixel → scan field coordinates
    abs_verts = [
        ((c[1] - image_center) * pixel_size_m,
         (c[0] - image_center) * pixel_size_m)
        for c in contour
    ]

    # Centre and extract translation
    vertices_m, translation_m = center_vertices(abs_verts)

    # Close polygon if needed
    if close and len(vertices_m) >= 3:
        d = ((vertices_m[0][0] - vertices_m[-1][0]) ** 2 +
             (vertices_m[0][1] - vertices_m[-1][1]) ** 2) ** 0.5
        if d > pixel_size_m * 0.5:
            vertices_m.append(vertices_m[0])

    return vertices_m, translation_m


# =============================================================================
# Add ROI
# =============================================================================

def lrp_add_roi(lrp_path, job_name, roi_type, vertices, *,
                name=None, color=None, rotation=0.0,
                translation=(0.0, 0.0), scale=(1.0, 1.0)):
    """Append an ROI Element to DCROISet/Children in Master.

    Coordinates are in **metres relative to the scan field centre**
    (matching the LAS X internal format).  Use ``um()`` to convert
    from micrometres.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        job_name: Name of the job to modify.
        roi_type: ROI type string — ``"8"`` (polygon),
            ``"16"`` (rectangle), ``"32"`` (ellipse), ``"64"`` (line).
        vertices: List of ``(x, y)`` tuples in metres from centre.
        name: Element name (default auto-numbered ``"ROI 1"`` etc.).
        color: Colour as uint32 string (default ``COLOR_RED``).
        rotation: Rotation in **degrees** (default ``0.0``).
        translation: ``(tx, ty)`` tuple in **metres** — offset from
            stage centre with X negated (default ``(0.0, 0.0)``
            places the ROI at the stage centre).  Use
            ``absolute_um_to_roi_translation()`` to convert from
            absolute stage coordinates.
        scale: ``(sx, sy)`` tuple (default ``(1.0, 1.0)``).

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    if color is None:
        color = COLOR_RED

    lrp_path = Path(lrp_path)
    tree = ET.parse(lrp_path)
    root = tree.getroot()

    block = _find_job_block(root, job_name)
    if block is None:
        log.error("lrp_add_roi: job '%s' not found", job_name)
        return False

    setting = _find_master_setting(block)
    if setting is None:
        log.error("lrp_add_roi: no Master setting for job '%s'", job_name)
        return False

    children = _find_dcroiset_children(setting)
    if children is None:
        log.error("lrp_add_roi: no DCROISet/Children for job '%s'", job_name)
        return False

    # Auto-number: "ROI 1", "ROI 2", ...
    if name is None:
        existing = len(list(children))
        name = f"ROI {existing + 1}"

    # Build the ROI Element wrapper (issue 6)
    roi_el = ET.SubElement(children, "Element",
                           Name=name,
                           Visibility="2",
                           CopyOption="1",
                           UniqueID=str(uuid.uuid4()))

    # Data — ROISingle with full LAS X attribute set (issue 1)
    data_el = ET.SubElement(roi_el, "Data")
    roi_single = ET.SubElement(
        data_el, "ROISingle",
        RoiType=str(roi_type),
        RoiAction="65535",
        TransformationType="65535",
        Color=str(color),
        FontName="Arial",
        FontSize="10000",
        FontStyle="0",
        IsClosed="1",
        Inverted="0",
        VisibleLabel="1",
        Visible="1",
        LineWidth="2",
        AnnotationText="",
    )

    # AOTF attachment — inside ROISingle, before Vertices (issue 5)
    aotf = lrp_find_aotf_template(root)
    if aotf is not None:
        roi_single.append(aotf)

    # Vertices — use <P> elements, not <Item> (issue 3)
    verts_el = ET.SubElement(roi_single, "Vertices")
    for x, y in vertices:
        ET.SubElement(verts_el, "P", X=str(x), Y=str(y))

    # Transformation — nested structure (issue 4, issue 10)
    transform_el = ET.SubElement(roi_single, "Transformation",
                                 Rotation=str(rotation))
    sx, sy = scale
    ET.SubElement(transform_el, "Scaling",
                  XScale=str(sx), YScale=str(sy))
    tx, ty = translation
    ET.SubElement(transform_el, "Translation",
                  X=str(tx), Y=str(ty))

    # Memory with unique MemoryBlockID (issue 7)
    mem_id = f"MemBlock_{uuid.uuid4().int % 100000}"
    ET.SubElement(roi_el, "Memory", Size="0", MemoryBlockID=mem_id)

    # Children placeholder
    ET.SubElement(roi_el, "Children")

    tree.write(lrp_path, encoding="utf-8", xml_declaration=True)
    log.info("lrp_add_roi: job='%s', type=%s, %d vertices",
             job_name, roi_type, len(vertices))
    return True


# =============================================================================
# Verify helpers
# =============================================================================

def lrp_verify_roi_count(lrp_path, expected_count, job_name):
    """Verify the number of ROIs for a job via ``parse_lrp``.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        expected_count: Expected number of ROIs.
        job_name: Name of the job to check.

    Returns:
        ``True`` if the count matches, ``False`` otherwise.
    """
    parsed = parse_lrp(lrp_path)
    job = parsed["jobs"].get(job_name)
    if job is None:
        log.error("lrp_verify_roi_count: job '%s' not found", job_name)
        return expected_count == 0
    master = job.get("Master", {})
    rois = master.get("_ROIs", [])
    actual = len(rois)
    if actual != expected_count:
        log.warning("lrp_verify_roi_count: job='%s', expected %d, got %d",
                    job_name, expected_count, actual)
        return False
    return True


def lrp_verify_roi(lrp_path, job_name, index, roi_type=None, n_vertices=None):
    """Verify attributes of a specific ROI by index.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        job_name: Name of the job to check.
        index: Zero-based ROI index.
        roi_type: Expected ROI type string (optional).
        n_vertices: Expected vertex count (optional).

    Returns:
        ``True`` if all specified checks pass, ``False`` otherwise.
    """
    parsed = parse_lrp(lrp_path)
    job = parsed["jobs"].get(job_name)
    if job is None:
        log.error("lrp_verify_roi: job '%s' not found", job_name)
        return False
    master = job.get("Master", {})
    rois = master.get("_ROIs", [])
    if index >= len(rois):
        log.error("lrp_verify_roi: index %d out of range (have %d ROIs)",
                  index, len(rois))
        return False

    roi = rois[index]
    if roi_type is not None:
        # LAS X uses "RoiType"; accept either casing for robustness
        actual_type = roi.get("RoiType") or roi.get("ROIType")
        if actual_type != str(roi_type):
            log.warning("lrp_verify_roi: RoiType mismatch: expected %s, got %s",
                        roi_type, actual_type)
            return False
    if n_vertices is not None:
        actual = len(roi.get("_Vertices", []))
        if actual != n_vertices:
            log.warning("lrp_verify_roi: vertex count mismatch: "
                        "expected %d, got %d", n_vertices, actual)
            return False
    return True


# =============================================================================
# ROI Translation coordinate helpers
# =============================================================================


def roi_translation_to_pan(translation_x_m, translation_y_m, *,
                           pan_scale_um):
    """Convert ROI Translation (metres) to galvo pan values.

    ROI Translation is the offset from stage centre with X negated.

    **PAN_SCALE is objective-dependent**: um-per-pan-unit scales with
    the objective's base FOV via
    ``pan_scale_um = base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT``
    (see ``lasx/utils.py`` and :func:`pan_scale_um_from_base_fov`).
    ``pan_scale_um`` is required — the caller must resolve it from the
    current objective's base FOV.

    Args:
        translation_x_m: Translation X from the ROI ``_Transformation``
            dict (in metres).
        translation_y_m: Translation Y (in metres).
        pan_scale_um: um displacement per unit of pan for the current
            objective. Required.

    Returns:
        ``(pan_x, pan_y)`` tuple suitable for ``lrp_set_pan``.
    """
    tx_um = float(translation_x_m) * 1e6
    ty_um = float(translation_y_m) * 1e6
    return (-tx_um / pan_scale_um, ty_um / pan_scale_um)


def roi_to_absolute_um(translation_x_m, translation_y_m, stage_x_um, stage_y_um):
    """Convert ROI Translation to absolute stage coordinates in um.

    Args:
        translation_x_m: Translation X (metres).
        translation_y_m: Translation Y (metres).
        stage_x_um: Current stage X position in um (from ``get_xy``).
        stage_y_um: Current stage Y position in um.

    Returns:
        ``(x_um, y_um)`` — absolute position of the ROI centre.
    """
    tx_um = float(translation_x_m) * 1e6
    ty_um = float(translation_y_m) * 1e6
    return (stage_x_um - tx_um, stage_y_um + ty_um)


def absolute_um_to_roi_translation(x_um, y_um, stage_x_um, stage_y_um):
    """Convert absolute stage coordinates to ROI Translation (metres).

    Inverse of ``roi_to_absolute_um``.

    Args:
        x_um: Target X position in um.
        y_um: Target Y position in um.
        stage_x_um: Current stage X position in um.
        stage_y_um: Current stage Y position in um.

    Returns:
        ``(tx_m, ty_m)`` — Translation values in metres, suitable for
        the ``translation`` parameter of ``lrp_add_roi``.
    """
    tx_um = stage_x_um - x_um
    ty_um = y_um - stage_y_um
    return (tx_um * 1e-6, ty_um * 1e-6)


# =============================================================================
# Image coordinate helpers
# =============================================================================

def pixel_to_absolute_um(px, py, stage_x_um, stage_y_um,
                         pan_x, pan_y, pixel_size_um, image_size=512, *,
                         pan_scale_um):
    """Convert image pixel coordinates to absolute stage coordinates.

    Uses a Cartesian coordinate system (right = +X, up = +Y).
    Pixel (0, 0) is the top-left of the image.

    **PAN_SCALE is objective-dependent** when pan_x/pan_y are non-zero:
    the contribution of pan to image centre scales with the objective's
    base FOV via
    ``pan_scale_um = base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT``
    (see :func:`pan_scale_um_from_base_fov`). ``pan_scale_um`` is
    required. For pan=(0, 0) the value is multiplied by zero and so
    has no effect; you can pass any positive number in that case (but
    the resolved value is the principled choice).

    .. note::

       This converts to **absolute stage coordinates** (Cartesian),
       which is a different coordinate system from ROI vertex
       coordinates (display frame, +X = right, +Y = down).
       For pixel → ROI vertex mapping, use the simpler formula::

           vx = (col - center) * pixel_size_m
           vy = (row - center) * pixel_size_m

       See module docstring for details.

    Args:
        px, py: Pixel coordinates (can be float).
        stage_x_um, stage_y_um: Stage position in um (from ``get_xy``).
        pan_x, pan_y: Current pan values.
        pixel_size_um: Size of one pixel in um (from
            ``parse_tile_geometry`` → ``pixel_w_um``).
        image_size: Image dimension in pixels (default 512).
        pan_scale_um: um per unit pan for the current objective. Required.

    Returns:
        ``(x_um, y_um)`` — absolute position in um (Cartesian).
    """
    center = image_size / 2.0

    # Image center in absolute coords (Cartesian)
    cx = stage_x_um + pan_x * pan_scale_um
    cy = stage_y_um + pan_y * pan_scale_um

    # Image X is inverted vs Cartesian X (left pixel = higher stage X)
    # Image Y is inverted vs Cartesian Y (top pixel = higher stage Y)
    x_um = cx + (center - px) * pixel_size_um
    y_um = cy + (center - py) * pixel_size_um
    return (x_um, y_um)


def bbox_to_zoom(width_um, height_um, fov_at_zoom1_um, margin=1.15):
    """Calculate the optimal zoom to frame a bounding box.

    Args:
        width_um: Bounding box width in um.
        height_um: Bounding box height in um.
        fov_at_zoom1_um: FOV at zoom 1 in um for the current objective
            (e.g. ``get_fov`` at zoom 1, or ``pixel_w_um * pixels_x``).
        margin: Extra margin factor (default 1.15 = 15%).

    Returns:
        Integer zoom level, clamped to [1, 48].
    """
    max_dim = max(width_um, height_um)
    if max_dim <= 0:
        return 48
    optimal = fov_at_zoom1_um / (max_dim * margin)
    return min(48, max(1, round(optimal)))


def roi_geometry(roi):
    """Extract centroid, bounding box, and effective translation from a parsed ROI.

    Args:
        roi: A single ROI dict from ``parse_lrp``
            (i.e. ``parsed["jobs"][job]["Master"]["_ROIs"][i]``).

    Returns:
        dict with keys::

            vertices        — list of (X, Y) tuples in metres (local coords)
            centroid_m      — (cx, cy) vertex centroid in metres (local)
            bbox_um         — (width, height) bounding box in µm
            translation_m   — (tx, ty) raw ROI translation in metres
            effective_translation_m — (tx + cx, ty + cy) in metres
                (accounts for vertex centroid offset)
            type            — ROI type string (e.g. "8" for polygon)
            color           — LAS X ARGB color string
            rotation        — rotation angle (radians)
            scale           — (x_scale, y_scale)
    """
    verts = [(v["X"], v["Y"]) for v in roi.get("_Vertices", [])]
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]

    cx = sum(xs) / len(xs) if xs else 0.0
    cy = sum(ys) / len(ys) if ys else 0.0

    t = roi.get("_Transformation", {})
    tx = float(t.get("TranslationX", 0))
    ty = float(t.get("TranslationY", 0))

    return {
        "vertices": verts,
        "centroid_m": (cx, cy),
        "bbox_um": ((max(xs) - min(xs)) * 1e6 if xs else 0.0,
                    (max(ys) - min(ys)) * 1e6 if ys else 0.0),
        "translation_m": (tx, ty),
        "effective_translation_m": (tx + cx, ty + cy),
        "type": roi.get("RoiType", "8"),
        "color": roi.get("Color", "4294901760"),
        "rotation": float(t.get("Rotation", 0)),
        "scale": (float(t.get("XScale", 1)), float(t.get("YScale", 1))),
    }


def roi_to_pan_zoom(roi, fov_at_zoom1_um, margin=1.15):
    """Compute pan and zoom values to frame an ROI.

    Combines :func:`roi_geometry`, :func:`roi_translation_to_pan`, and
    :func:`bbox_to_zoom` into a single call.

    Internally resolves the objective-dependent ``pan_scale_um`` from
    ``fov_at_zoom1_um`` via :func:`pan_scale_um_from_base_fov`
    (``pan_scale_um = base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT``,
    see ``lasx/utils.py``). Callers that already pass the correct base
    FOV (e.g. from :func:`get_base_fov`) get correct pan values on any
    objective — no caller changes needed after the PAN_SCALE refactor.

    Args:
        roi: A single ROI dict from ``parse_lrp``.
        fov_at_zoom1_um: Objective FOV at zoom 1 in µm
            (from ``get_base_fov``).
        margin: Extra margin factor passed to ``bbox_to_zoom``.

    Returns:
        ``(pan_x, pan_y, zoom)`` tuple.
    """
    from .utils import pan_scale_um_from_base_fov
    pan_scale_um = pan_scale_um_from_base_fov(fov_at_zoom1_um)
    geo = roi_geometry(roi)
    eff_tx, eff_ty = geo["effective_translation_m"]
    pan_x, pan_y = roi_translation_to_pan(eff_tx, eff_ty,
                                          pan_scale_um=pan_scale_um)
    w_um, h_um = geo["bbox_um"]
    zoom = bbox_to_zoom(w_um, h_um, fov_at_zoom1_um, margin=margin)
    return (pan_x, pan_y, zoom)


def mask_contour_to_roi(contour_pixels, stage_x_um, stage_y_um,
                        pan_x, pan_y, pixel_size_um, image_size=512, *,
                        pan_scale_um):
    """Convert a segmentation mask contour to ROI vertices + translation.

    Takes a list of pixel coordinates from a segmentation mask contour
    and converts them into the format needed by ``lrp_add_roi``:
    vertices in metres relative to the shape centroid, plus a
    translation that positions the shape at the correct absolute
    location.

    **PAN_SCALE is objective-dependent** when pan_x/pan_y are non-zero.
    Pass ``pan_scale_um`` resolved from the current objective's base FOV
    via :func:`pan_scale_um_from_base_fov`. Required.

    Args:
        contour_pixels: List of ``(px, py)`` pixel coordinates tracing
            the mask boundary.
        stage_x_um, stage_y_um: Stage position in um.
        pan_x, pan_y: Pan values when the image was taken.
        pixel_size_um: Size of one pixel in um.
        image_size: Image dimension in pixels (default 512).
        pan_scale_um: um per unit pan for the current objective. Required.

    Returns:
        ``(vertices_m, translation_m)`` tuple:
            - ``vertices_m``: list of ``(x_m, y_m)`` in metres,
              centred on ``(0, 0)``.
            - ``translation_m``: ``(tx_m, ty_m)`` for ``lrp_add_roi``.
    """
    # Convert all contour pixels to absolute um
    abs_points = [
        pixel_to_absolute_um(px, py, stage_x_um, stage_y_um,
                             pan_x, pan_y, pixel_size_um, image_size,
                             pan_scale_um=pan_scale_um)
        for px, py in contour_pixels
    ]

    # Centroid
    n = len(abs_points)
    centroid_x = sum(p[0] for p in abs_points) / n
    centroid_y = sum(p[1] for p in abs_points) / n

    # Vertices relative to centroid, in metres
    vertices_m = [
        ((p[0] - centroid_x) * 1e-6, (p[1] - centroid_y) * 1e-6)
        for p in abs_points
    ]

    # Translation from centroid absolute position
    translation_m = absolute_um_to_roi_translation(
        centroid_x, centroid_y, stage_x_um, stage_y_um
    )

    return (vertices_m, translation_m)
