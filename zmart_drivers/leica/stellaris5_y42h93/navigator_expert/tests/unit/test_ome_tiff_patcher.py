"""
Unit tests for the binary OME-TIFF tag-270 reader/patcher (LS-21).
==================================================================
Direct struct-level tests for ``acquisition/ome.py`` using real tiny TIFFs
written with ``tifffile`` (both byte orders) plus one hand-crafted TIFF that
places the ImageDescription at end-of-file to reach the extend-in-place
branch. No mocks: these run the same code that repairs export files in place
in production (``materialize.py``).
"""

import struct
from pathlib import Path

import numpy as np
import pytest
import tifffile
from navigator_expert.acquisition.ome import (
    _read_tiff_tag_270,
    check_ome_tiff,
    check_ome_xml_bytes,
    check_ome_xml_file,
    extract_wavelength_from_id,
    fix_ome_tiff,
    fix_ome_xml_bytes,
    fix_ome_xml_file,
)

# The Leica STELLARIS schema violation this module detects and repairs:
# <Laser Wavelength="0"> (xsd:positiveInteger requires >= 1), with the true
# wavelength recoverable from the parent LightSource ID.
BAD_OME_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-09">'
    '<Instrument ID="Instrument:0">'
    '<LightSource ID="LightSource:499nm:SuperContVisible Light_0">'
    '<Laser Wavelength="0" LaserMedium="Other" Type="Other" />'
    "</LightSource>"
    "</Instrument>"
    '<Image ID="Image:0"><Pixels ID="Pixels:0" DimensionOrder="XYCZT"'
    ' Type="uint8" SizeX="8" SizeY="8" SizeC="1" SizeZ="1" SizeT="1"/>'
    "</Image></OME>"
)

# Variant whose LightSource ID carries no "NNNnm" hint: the fixer must fall
# back to *removing* the offending attribute (shorter XML -> in-place branch).
BAD_OME_XML_NO_HINT = BAD_OME_XML.replace(
    "LightSource:499nm:SuperContVisible Light_0", "LightSource:0"
)

GOOD_OME_XML = BAD_OME_XML.replace('Wavelength="0"', 'Wavelength="499"')

IMG = np.arange(64, dtype=np.uint8).reshape(8, 8)


def _write_tiff(path, description, byteorder="<"):
    tifffile.imwrite(path, IMG, description=description, byteorder=byteorder)
    return path


def _embedded_xml(path):
    xml, _, _, _, _ = _read_tiff_tag_270(Path(path).read_bytes())
    return xml


class TestExtractWavelengthFromId:
    def test_examples_from_docstring(self):
        assert extract_wavelength_from_id("LightSource:499nm:SuperContVisible Light_0") == 499
        assert extract_wavelength_from_id("LightSource:405nm:UV Light_0") == 405
        assert extract_wavelength_from_id("LightSource:0") is None

    def test_zero_nm_is_rejected(self):
        assert extract_wavelength_from_id("LightSource:0nm:Broken") is None


class TestReadTiffTag270:
    def test_reads_description_from_real_tiff(self, tmp_path):
        p = _write_tiff(tmp_path / "a.ome.tif", BAD_OME_XML)
        data = p.read_bytes()
        xml, offset, count, entry_pos, endian = _read_tiff_tag_270(data)
        assert xml.decode() == BAD_OME_XML
        assert endian == "<"
        # Offset/count point at the actual description bytes in the file.
        assert data[offset : offset + count].rstrip(b"\x00").decode() == BAD_OME_XML

    def test_big_endian_tiff(self, tmp_path):
        p = _write_tiff(tmp_path / "be.ome.tif", BAD_OME_XML, byteorder=">")
        data = p.read_bytes()
        assert data[:2] == b"MM"
        xml, _, _, _, endian = _read_tiff_tag_270(data)
        assert xml.decode() == BAD_OME_XML
        assert endian == ">"

    def test_error_strings_on_garbage(self, tmp_path):
        assert _read_tiff_tag_270(b"II")[4] == "File too small to be a TIFF"
        assert _read_tiff_tag_270(b"NOTATIFF" * 4)[4] == "Not a valid TIFF file"
        # Right byte order mark, wrong magic.
        bad_magic = b"II" + struct.pack("<H", 43) + struct.pack("<I", 8) + b"\x00" * 8
        assert _read_tiff_tag_270(bad_magic)[4].startswith("Not a standard TIFF")
        # Valid header, IFD offset pointing past EOF.
        bad_ifd = b"II" + struct.pack("<H", 42) + struct.pack("<I", 9999)
        assert _read_tiff_tag_270(bad_ifd)[4] == "IFD offset beyond file end"

    def test_no_description_tag(self, tmp_path):
        p = tmp_path / "nodesc.tif"
        tifffile.imwrite(p, IMG, metadata=None)
        assert _read_tiff_tag_270(p.read_bytes())[4] == "No ImageDescription tag found"


class TestCheckOmeXml:
    def test_detects_wavelength_zero(self):
        result = check_ome_xml_bytes(BAD_OME_XML.encode())
        assert result["corrupted"] is True
        assert result["violations"] == [
            {
                "lightsource_id": "LightSource:499nm:SuperContVisible Light_0",
                "attribute": "Wavelength",
                "value": "0",
            }
        ]

    def test_clean_xml_passes(self):
        assert check_ome_xml_bytes(GOOD_OME_XML.encode()) == {
            "corrupted": False,
            "violations": [],
        }

    def test_companion_xml_file(self, tmp_path):
        p = tmp_path / "meta.ome.xml"
        p.write_bytes(BAD_OME_XML.encode())
        result = check_ome_xml_file(str(p))
        assert result["corrupted"] is True and result["error"] is None
        missing = check_ome_xml_file(str(tmp_path / "nope.ome.xml"))
        assert missing["corrupted"] is False and "No such file" in missing["error"]


class TestCheckOmeTiff:
    def test_detects_violation_in_both_byte_orders(self, tmp_path):
        for name, order in (("le.ome.tif", "<"), ("be.ome.tif", ">")):
            p = _write_tiff(tmp_path / name, BAD_OME_XML, byteorder=order)
            result = check_ome_tiff(str(p))
            assert result["corrupted"] is True
            assert result["error"] is None
            assert len(result["violations"]) == 1

    def test_clean_tiff_passes(self, tmp_path):
        p = _write_tiff(tmp_path / "ok.ome.tif", GOOD_OME_XML)
        result = check_ome_tiff(str(p))
        assert result == {
            "path": str(p),
            "corrupted": False,
            "violations": [],
            "error": None,
        }

    def test_garbage_and_missing_files_report_error_not_corruption(self, tmp_path):
        g = tmp_path / "garbage.tif"
        g.write_bytes(b"NOTATIFF" * 4)
        result = check_ome_tiff(str(g))
        assert result["corrupted"] is False
        assert result["error"] == "Not a valid TIFF file"
        missing = check_ome_tiff(str(tmp_path / "nope.tif"))
        assert missing["corrupted"] is False and "No such file" in missing["error"]


class TestFixOmeXmlBytes:
    def test_infers_wavelength_from_lightsource_id(self):
        fixed, changes = fix_ome_xml_bytes(BAD_OME_XML.encode())
        assert fixed.decode() == GOOD_OME_XML
        assert len(changes) == 1 and 'Wavelength="499"' in changes[0]

    def test_removes_attribute_when_id_has_no_hint(self):
        fixed, changes = fix_ome_xml_bytes(BAD_OME_XML_NO_HINT.encode())
        assert b'Wavelength="0"' not in fixed
        assert b"<Laser" in fixed  # element kept, attribute dropped
        assert len(changes) == 1 and "removed" in changes[0]

    def test_clean_xml_returned_unchanged(self):
        fixed, changes = fix_ome_xml_bytes(GOOD_OME_XML.encode())
        assert fixed == GOOD_OME_XML.encode()
        assert changes == []


class TestFixOmeTiff:
    @pytest.mark.parametrize("byteorder", ["<", ">"], ids=["little-endian", "big-endian"])
    def test_repairs_in_place_with_pixels_intact(self, tmp_path, byteorder):
        p = _write_tiff(tmp_path / "img.ome.tif", BAD_OME_XML, byteorder=byteorder)
        pixels_before = tifffile.imread(p).copy()

        result = fix_ome_tiff(str(p))  # output_path=None -> in-place

        assert result["success"] is True and result["error"] is None
        assert len(result["changes"]) == 1
        # (a) description repaired
        assert b'Wavelength="499"' in _embedded_xml(p)
        assert check_ome_tiff(str(p))["corrupted"] is False
        # (b) pixel data byte-identical, (c) file still opens in tifffile
        assert np.array_equal(tifffile.imread(p), pixels_before)

    def test_longer_replacement_relocates_description_to_eof(self, tmp_path):
        # '0' -> '499' grows the XML; tifffile stores the description before
        # the pixel data, so the fixer must take the relocate-to-EOF branch.
        p = _write_tiff(tmp_path / "grow.ome.tif", BAD_OME_XML)
        data_before = p.read_bytes()
        _, old_offset, old_count, _, _ = _read_tiff_tag_270(data_before)
        assert old_offset + old_count < len(data_before)  # mid-file: precondition

        result = fix_ome_tiff(str(p))
        assert result["success"] is True

        data_after = p.read_bytes()
        xml, new_offset, new_count, _, _ = _read_tiff_tag_270(data_after)
        # Relocated: appended at previous EOF, IFD entry updated, old slot zeroed.
        assert new_offset == len(data_before)
        assert len(data_after) == len(data_before) + new_count
        assert data_after[old_offset : old_offset + old_count] == b"\x00" * old_count
        assert xml.decode() == GOOD_OME_XML
        assert np.array_equal(tifffile.imread(p), IMG)

    def test_shorter_replacement_patches_in_place(self, tmp_path):
        # Attribute removal shrinks the XML -> fits-in-place branch, padded
        # with NULs; file size and description offset are unchanged.
        p = _write_tiff(tmp_path / "shrink.ome.tif", BAD_OME_XML_NO_HINT)
        size_before = p.stat().st_size
        _, offset_before, count_before, _, _ = _read_tiff_tag_270(p.read_bytes())

        result = fix_ome_tiff(str(p))
        assert result["success"] is True and "removed" in result["changes"][0]

        data_after = p.read_bytes()
        xml, offset_after, count_after, _, _ = _read_tiff_tag_270(data_after)
        assert p.stat().st_size == size_before
        assert (offset_after, count_after) == (offset_before, count_before)
        assert b'Wavelength="0"' not in xml
        assert np.array_equal(tifffile.imread(p), IMG)

    def test_description_at_eof_extends_in_place(self, tmp_path):
        # Hand-crafted minimal TIFF: header + single-entry IFD + description
        # as the final bytes, reaching the extend-in-place branch.
        desc = (
            b'<OME><Instrument><LightSource ID="LightSource:405nm:UV Light_0">'
            b'<Laser Wavelength="0" /></LightSource></Instrument></OME>\x00'
        )
        header = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)
        entry = struct.pack("<HHII", 270, 2, len(desc), 26)
        ifd = struct.pack("<H", 1) + entry + struct.pack("<I", 0)
        p = tmp_path / "eof.tif"
        p.write_bytes(header + ifd + desc)
        assert check_ome_tiff(str(p))["corrupted"] is True

        result = fix_ome_tiff(str(p))
        assert result["success"] is True

        xml, offset, count, _, _ = _read_tiff_tag_270(p.read_bytes())
        assert offset == 26  # extended in place, not relocated
        assert b'Wavelength="405"' in xml
        assert p.stat().st_size == 26 + count
        assert check_ome_tiff(str(p))["corrupted"] is False

    def test_separate_output_path_leaves_input_untouched(self, tmp_path):
        src = _write_tiff(tmp_path / "src.ome.tif", BAD_OME_XML)
        dst = tmp_path / "dst.ome.tif"
        src_bytes = src.read_bytes()

        result = fix_ome_tiff(str(src), str(dst))

        assert result["success"] is True
        assert src.read_bytes() == src_bytes
        assert check_ome_tiff(str(dst))["corrupted"] is False
        assert np.array_equal(tifffile.imread(dst), IMG)

    def test_clean_tiff_copied_byte_identical_with_no_changes(self, tmp_path):
        p = _write_tiff(tmp_path / "clean.ome.tif", GOOD_OME_XML)
        original = p.read_bytes()
        result = fix_ome_tiff(str(p))
        assert result["success"] is True and result["changes"] == []
        assert p.read_bytes() == original

    def test_tiff_without_description_is_success_no_changes(self, tmp_path):
        p = tmp_path / "nodesc.tif"
        tifffile.imwrite(p, IMG, metadata=None)
        original = p.read_bytes()
        result = fix_ome_tiff(str(p))
        assert result["success"] is True and result["changes"] == []
        assert p.read_bytes() == original

    def test_fail_safe_on_garbage_truncated_and_missing(self, tmp_path):
        # Pin the fail-safe: non-TIFF input -> success=False with the parse
        # error, and the file is left byte-for-byte untouched.
        g = tmp_path / "garbage.tif"
        g.write_bytes(b"NOTATIFF" * 4)
        result = fix_ome_tiff(str(g))
        assert result["success"] is False
        assert result["error"] == "Not a valid TIFF file"
        assert g.read_bytes() == b"NOTATIFF" * 4

        t = tmp_path / "trunc.tif"
        t.write_bytes(b"II\x2a\x00")  # truncated before the IFD offset
        result = fix_ome_tiff(str(t))
        assert result["success"] is False
        assert result["error"] == "File too small to be a TIFF"

        result = fix_ome_tiff(str(tmp_path / "nope.tif"))
        assert result["success"] is False and "No such file" in result["error"]


class TestFixOmeXmlFile:
    def test_repairs_companion_xml_in_place(self, tmp_path):
        p = tmp_path / "meta.ome.xml"
        p.write_bytes(BAD_OME_XML.encode())
        result = fix_ome_xml_file(str(p))
        assert result["success"] is True and len(result["changes"]) == 1
        assert p.read_bytes() == GOOD_OME_XML.encode()

    def test_missing_file_reports_error(self, tmp_path):
        result = fix_ome_xml_file(str(tmp_path / "nope.ome.xml"))
        assert result["success"] is False and "No such file" in result["error"]
