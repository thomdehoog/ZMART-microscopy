"""
OME-TIFF / OME-XML schema validation and patching.
====================================================
Detect and fix known OME-XML schema violations in Leica STELLARIS
exports: OME-TIFF files (embedded XML in TIFF tag 270) and companion
OME-XML files in the ``metadata/`` directory.

Known violation addressed:
    ``<Laser Wavelength="0">`` violates the OME-XML 2008-09 schema
    (``xsd:positiveInteger`` requires >= 1).  The fix infers the correct
    wavelength from the parent ``<LightSource>`` ID attribute.

Fix strategy:
    Regex-based surgery preserving exact original formatting (no DOM
    re-serialisation which would alter whitespace, attribute order,
    namespace prefixes, etc.).

Dependency direction:
    - Imports: stdlib only (re, struct, logging).
    - Imported by: ``__init__`` (re-export).
"""

import logging
import re
import struct

log = logging.getLogger(__name__)

# ── TIFF constants ─────────────────────────────────────────────────
_TIFF_TAG_IMAGE_DESCRIPTION = 270
_TIFF_LITTLE_ENDIAN = b"II"
_TIFF_BIG_ENDIAN = b"MM"
_TIFF_MAGIC = 42

# ── Compiled regexes ──────────────────────────────────────────────
# Match a <LightSource ID="..."> ... </LightSource> block
_RE_LIGHTSOURCE_BLOCK = re.compile(
    r'(<LightSource\b[^>]*\bID="([^"]*)"[^>]*>)'
    r"(.*?)"
    r"(</LightSource>)",
    re.DOTALL,
)

# Match <Laser ... Wavelength="0" ... />
_RE_LASER_WAVELENGTH_ZERO = re.compile(r'(<Laser\b)([^/]*?)\bWavelength="0"([^/]*/\s*>)')

# Extract NNNnm from a LightSource ID string
_RE_WAVELENGTH_NM = re.compile(r"(\d+)\s*nm", re.IGNORECASE)


# ===================================================================
# Extraction helper
# ===================================================================


def extract_wavelength_from_id(lightsource_id):
    """Extract wavelength (nm) from a LightSource ID string.

    Examples::

        "LightSource:499nm:SuperContVisible Light_0"  ->  499
        "LightSource:405nm:UV Light_0"                 ->  405
        "LightSource:0"                                ->  None

    Returns:
        Positive integer wavelength in nm, or ``None`` if not found.
    """
    m = _RE_WAVELENGTH_NM.search(lightsource_id)
    if m:
        wl = int(m.group(1))
        if wl > 0:
            return wl
    return None


# ===================================================================
# TIFF parsing helper (shared by check and fix)
# ===================================================================


def _read_tiff_tag_270(data):
    """Locate ImageDescription (tag 270) in the first IFD of a TIFF.

    Args:
        data: Raw TIFF file content (bytes or bytearray).

    Returns:
        ``(xml_bytes, desc_offset, desc_count, desc_entry_pos, endian)``
        on success, or ``(None, None, None, None, error_string)`` on
        failure.
    """
    if len(data) < 8:
        return None, None, None, None, "File too small to be a TIFF"

    # Byte order
    if data[:2] == _TIFF_LITTLE_ENDIAN:
        endian = "<"
    elif data[:2] == _TIFF_BIG_ENDIAN:
        endian = ">"
    else:
        return None, None, None, None, "Not a valid TIFF file"

    # Magic number
    magic = struct.unpack_from(endian + "H", data, 2)[0]
    if magic != _TIFF_MAGIC:
        return None, None, None, None, f"Not a standard TIFF (magic={magic})"

    # First IFD
    ifd_offset = struct.unpack_from(endian + "I", data, 4)[0]
    if ifd_offset + 2 > len(data):
        return None, None, None, None, "IFD offset beyond file end"

    num_entries = struct.unpack_from(endian + "H", data, ifd_offset)[0]

    pos = ifd_offset + 2
    for _ in range(num_entries):
        if pos + 12 > len(data):
            break
        tag = struct.unpack_from(endian + "H", data, pos)[0]
        count = struct.unpack_from(endian + "I", data, pos + 4)[0]

        if tag == _TIFF_TAG_IMAGE_DESCRIPTION:
            if count <= 4:
                desc_offset = pos + 8
            else:
                desc_offset = struct.unpack_from(endian + "I", data, pos + 8)[0]

            xml_raw = bytes(data[desc_offset : desc_offset + count])
            xml_raw = xml_raw.rstrip(b"\x00")
            return xml_raw, desc_offset, count, pos, endian

        pos += 12

    return None, None, None, None, "No ImageDescription tag found"


# ===================================================================
# Check functions (requirement 1)
# ===================================================================


def check_ome_xml_bytes(xml_bytes):
    """Check raw OME-XML bytes for schema violations without modifying.

    Scans for ``Laser Wavelength="0"`` inside ``<LightSource>`` blocks.

    Args:
        xml_bytes: Raw UTF-8 encoded OME-XML content.

    Returns:
        ``{"corrupted": bool, "violations": [...]}``.  Each violation
        is ``{"lightsource_id": str, "attribute": "Wavelength",
        "value": "0"}``.
    """
    xml_str = xml_bytes.decode("utf-8")
    violations = []
    for m in _RE_LIGHTSOURCE_BLOCK.finditer(xml_str):
        ls_id = m.group(2)
        body = m.group(3)
        if _RE_LASER_WAVELENGTH_ZERO.search(body):
            violations.append(
                {
                    "lightsource_id": ls_id,
                    "attribute": "Wavelength",
                    "value": "0",
                }
            )
    return {"corrupted": len(violations) > 0, "violations": violations}


def check_ome_tiff(path):
    """Check an OME-TIFF file for embedded XML schema violations.

    Reads tag 270 (ImageDescription) from the first IFD without
    modifying the file.

    Args:
        path: Path to an ``.ome.tif`` / ``.ome.tiff`` file.

    Returns:
        ``{"path": str, "corrupted": bool, "violations": [...],
        "error": str | None}``.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return {"path": path, "corrupted": False, "violations": [], "error": str(e)}

    xml_raw, _, _, _, endian_or_err = _read_tiff_tag_270(data)
    if xml_raw is None:
        return {"path": path, "corrupted": False, "violations": [], "error": endian_or_err}

    try:
        result = check_ome_xml_bytes(xml_raw)
    except UnicodeDecodeError as e:
        return {"path": path, "corrupted": False, "violations": [], "error": str(e)}

    return {
        "path": path,
        "corrupted": result["corrupted"],
        "violations": result["violations"],
        "error": None,
    }


def check_ome_xml_file(path):
    """Check a companion OME-XML file for schema violations.

    Args:
        path: Path to an ``.ome.xml`` file.

    Returns:
        ``{"path": str, "corrupted": bool, "violations": [...],
        "error": str | None}``.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return {"path": path, "corrupted": False, "violations": [], "error": str(e)}

    try:
        result = check_ome_xml_bytes(raw)
    except UnicodeDecodeError as e:
        return {"path": path, "corrupted": False, "violations": [], "error": str(e)}

    return {
        "path": path,
        "corrupted": result["corrupted"],
        "violations": result["violations"],
        "error": None,
    }


# ===================================================================
# Fix functions (requirements 2 and 3)
# ===================================================================


def fix_ome_xml_bytes(xml_bytes):
    """Fix OME-XML schema violations in raw XML bytes.

    Uses regex-based surgery to preserve exact formatting.

    Args:
        xml_bytes: Raw UTF-8 OME-XML content.

    Returns:
        ``(fixed_xml_bytes, list_of_change_descriptions)``.
        If no violations found, returns the original bytes unchanged
        and an empty changes list.
    """
    xml_str = xml_bytes.decode("utf-8")
    changes = []

    def _fix_lightsource(m):
        open_tag = m.group(1)
        ls_id = m.group(2)
        body = m.group(3)
        close_tag = m.group(4)

        laser_m = _RE_LASER_WAVELENGTH_ZERO.search(body)
        if not laser_m:
            return m.group(0)

        inferred_wl = extract_wavelength_from_id(ls_id)
        if inferred_wl is not None:
            new_body = _RE_LASER_WAVELENGTH_ZERO.sub(rf'\1\2Wavelength="{inferred_wl}"\3', body)
            changes.append(
                f'LightSource "{ls_id}": '
                f'Laser Wavelength="0" -> Wavelength="{inferred_wl}" '
                f"(inferred from LightSource ID)"
            )
        else:
            new_body = _RE_LASER_WAVELENGTH_ZERO.sub(
                lambda lm: (
                    lm.group(1) + re.sub(r'\s*Wavelength="0"', "", lm.group(2)) + lm.group(3)
                ),
                body,
            )
            changes.append(
                f'LightSource "{ls_id}": '
                f'Laser Wavelength="0" removed '
                f"(could not infer value; attribute is optional)"
            )

        return open_tag + new_body + close_tag

    xml_str = _RE_LIGHTSOURCE_BLOCK.sub(_fix_lightsource, xml_str)
    return xml_str.encode("utf-8"), changes


def fix_ome_tiff(input_path, output_path=None):
    """Fix embedded OME-XML in an OME-TIFF file.

    Locates tag 270 (ImageDescription) in the first IFD, applies the
    XML fix, and patches the binary.  Handles size changes by appending
    the fixed XML at end-of-file and updating IFD pointers.

    Args:
        input_path: Source OME-TIFF file.
        output_path: Destination path.  ``None`` overwrites in-place.

    Returns:
        ``{"success": bool, "input_path": str, "output_path": str,
        "changes": [...], "error": str | None}``.
    """
    if output_path is None:
        output_path = input_path

    try:
        with open(input_path, "rb") as f:
            data = bytearray(f.read())
    except OSError as e:
        return {
            "success": False,
            "input_path": input_path,
            "output_path": output_path,
            "changes": [],
            "error": str(e),
        }

    xml_raw, desc_offset, desc_count, desc_entry_pos, endian_or_err = _read_tiff_tag_270(data)

    if xml_raw is None:
        # No tag 270 — nothing to fix, not an error
        if endian_or_err == "No ImageDescription tag found":
            log.info("%s: no ImageDescription tag — nothing to fix", input_path)
            with open(output_path, "wb") as f:
                f.write(data)
            return {
                "success": True,
                "input_path": input_path,
                "output_path": output_path,
                "changes": [],
                "error": None,
            }
        return {
            "success": False,
            "input_path": input_path,
            "output_path": output_path,
            "changes": [],
            "error": endian_or_err,
        }

    try:
        fixed_xml, changes = fix_ome_xml_bytes(xml_raw)
    except UnicodeDecodeError as e:
        return {
            "success": False,
            "input_path": input_path,
            "output_path": output_path,
            "changes": [],
            "error": str(e),
        }

    if not changes:
        log.debug("%s: no schema violations in embedded XML", input_path)
        with open(output_path, "wb") as f:
            f.write(data)
        return {
            "success": True,
            "input_path": input_path,
            "output_path": output_path,
            "changes": [],
            "error": None,
        }

    for c in changes:
        log.info("%s: %s", input_path, c)

    # Patch the fixed XML back into the TIFF binary.
    fixed_with_null = fixed_xml + b"\x00"
    new_len = len(fixed_with_null)

    if new_len <= desc_count:
        # Fits in place — pad with nulls
        padded = fixed_with_null + b"\x00" * (desc_count - new_len)
        data[desc_offset : desc_offset + desc_count] = padded
    elif desc_offset + desc_count >= len(data):
        # XML is at end of file — extend in place (no relocation)
        data[desc_offset:] = fixed_with_null
        struct.pack_into(endian_or_err + "I", data, desc_entry_pos + 4, new_len)
    else:
        # XML is in the middle — relocate to end of file
        data[desc_offset : desc_offset + desc_count] = b"\x00" * desc_count
        new_offset = len(data)
        data.extend(fixed_with_null)
        struct.pack_into(endian_or_err + "I", data, desc_entry_pos + 4, new_len)
        struct.pack_into(endian_or_err + "I", data, desc_entry_pos + 8, new_offset)

    with open(output_path, "wb") as f:
        f.write(data)
    log.info("%s: patched -> %s", input_path, output_path)

    return {
        "success": True,
        "input_path": input_path,
        "output_path": output_path,
        "changes": changes,
        "error": None,
    }


def fix_ome_xml_file(input_path, output_path=None):
    """Fix schema violations in a companion OME-XML file.

    Args:
        input_path: Source OME-XML file.
        output_path: Destination path.  ``None`` overwrites in-place.

    Returns:
        ``{"success": bool, "input_path": str, "output_path": str,
        "changes": [...], "error": str | None}``.
    """
    if output_path is None:
        output_path = input_path

    try:
        with open(input_path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return {
            "success": False,
            "input_path": input_path,
            "output_path": output_path,
            "changes": [],
            "error": str(e),
        }

    try:
        fixed, changes = fix_ome_xml_bytes(raw)
    except UnicodeDecodeError as e:
        return {
            "success": False,
            "input_path": input_path,
            "output_path": output_path,
            "changes": [],
            "error": str(e),
        }

    for c in changes:
        log.info("%s: %s", input_path, c)

    with open(output_path, "wb") as f:
        f.write(fixed)

    if changes:
        log.info("%s: fixed -> %s", input_path, output_path)
    else:
        log.debug("%s: no schema violations found", input_path)

    return {
        "success": True,
        "input_path": input_path,
        "output_path": output_path,
        "changes": changes,
        "error": None,
    }
