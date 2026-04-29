"""
Tests for OME-TIFF / OME-XML validation and patching.
=======================================================
Offline tests — no hardware or real TIFF files required.

All test data (XML strings, synthetic TIFF binaries) is constructed
inline.  Tests cover the three public API layers:

    1. extract_wavelength_from_id — wavelength extraction from IDs
    2. check_* functions — corruption detection without modification
    3. fix_* functions — corruption repair

Usage::

    python -m pytest test_ome_tiff.py -v
"""

import os
import struct
import tempfile
import unittest

from navigator_expert.driver.ome_tiff import (
    extract_wavelength_from_id,
    check_ome_xml_bytes,
    check_ome_tiff,
    check_ome_xml_file,
    fix_ome_xml_bytes,
    fix_ome_tiff,
    fix_ome_xml_file,
    update_ome_tiff_filename,
    update_ome_xml_filename,
)


# ── Test XML fixtures ─────────────────────────────────────────────

_CLEAN_XML = b"""\
<OME><Instrument><LightSource ID="LightSource:499nm:Vis_0">\
<Laser Wavelength="499" LaserMedium="Other"/>\
</LightSource></Instrument></OME>"""

_CORRUPTED_XML = b"""\
<OME><Instrument><LightSource ID="LightSource:499nm:Vis_0">\
<Laser Wavelength="0" LaserMedium="Other"/>\
</LightSource></Instrument></OME>"""

_CORRUPTED_NO_INFERENCE_XML = b"""\
<OME><Instrument><LightSource ID="LightSource:0">\
<Laser Wavelength="0" LaserMedium="Other"/>\
</LightSource></Instrument></OME>"""

_MULTI_CORRUPTED_XML = b"""\
<OME><Instrument>\
<LightSource ID="LightSource:495nm:SuperCont_0">\
<Laser Wavelength="0" LaserMedium="Unknown" Type="Unknown"/>\
</LightSource>\
<LightSource ID="LightSource:405nm:UV_0">\
<Laser Wavelength="405" LaserMedium="Other"/>\
</LightSource>\
<LightSource ID="LightSource:633nm:HeNe_0">\
<Laser Wavelength="0" LaserMedium="Unknown"/>\
</LightSource>\
</Instrument></OME>"""

_NO_LIGHTSOURCE_XML = b"""\
<OME><Image Name="test"><Pixels SizeX="512"/></Image></OME>"""

_LASER_NO_WAVELENGTH_XML = b"""\
<OME><Instrument><LightSource ID="LightSource:488nm:Argon_0">\
<Laser LaserMedium="Other"/>\
</LightSource></Instrument></OME>"""

_ABS_PATH_XML = b"""\
<OME><Image ID="Image:0" \
Name="Z:\\zmbstaff\\10374\\Experiments\\image--L0000--C00.ome.tif" \
DefaultPixels="Pixels:0">\
<Description>Z:\\zmbstaff\\10374\\Experiments\\image--L0000--C00.ome.tif\
</Description>\
<Pixels SizeX="512"/></Image></OME>"""

_BARE_NAME_XML = b"""\
<OME><Image ID="Image:0" Name="sample.ome.tif" DefaultPixels="Pixels:0">\
<Description>sample.ome.tif</Description>\
<Pixels SizeX="512"/></Image></OME>"""


# ── Synthetic TIFF builder ────────────────────────────────────────

def _make_tiff(xml_bytes, endian='<'):
    """Build a minimal valid TIFF containing only tag 270."""
    bo = b'II' if endian == '<' else b'MM'
    num_entries = 1
    ifd_offset = 8
    xml_with_null = xml_bytes + b'\x00'
    xml_offset = ifd_offset + 2 + 12 * num_entries + 4

    header = struct.pack(endian + 'HI', 42, ifd_offset)
    ifd = struct.pack(endian + 'H', num_entries)
    entry = struct.pack(endian + 'HHII',
                        270, 2, len(xml_with_null), xml_offset)
    next_ifd = struct.pack(endian + 'I', 0)

    return bo + header + ifd + entry + next_ifd + xml_with_null


# ===================================================================
# Tests
# ===================================================================

class TestExtractWavelength(unittest.TestCase):

    def test_standard_nm(self):
        self.assertEqual(
            extract_wavelength_from_id("LightSource:499nm:SuperContVisible Light_0"),
            499)

    def test_uv_nm(self):
        self.assertEqual(
            extract_wavelength_from_id("LightSource:405nm:UV Light_0"),
            405)

    def test_case_insensitive(self):
        self.assertEqual(
            extract_wavelength_from_id("LightSource:633NM:HeNe"),
            633)

    def test_no_wavelength(self):
        self.assertIsNone(
            extract_wavelength_from_id("LightSource:0"))

    def test_zero_nm(self):
        self.assertIsNone(
            extract_wavelength_from_id("LightSource:0nm:Something"))

    def test_space_before_nm(self):
        self.assertEqual(
            extract_wavelength_from_id("LightSource:488 nm:Argon"),
            488)


class TestCheckOmeXmlBytes(unittest.TestCase):

    def test_clean_xml(self):
        result = check_ome_xml_bytes(_CLEAN_XML)
        self.assertFalse(result["corrupted"])
        self.assertEqual(result["violations"], [])

    def test_corrupted_single(self):
        result = check_ome_xml_bytes(_CORRUPTED_XML)
        self.assertTrue(result["corrupted"])
        self.assertEqual(len(result["violations"]), 1)
        self.assertEqual(result["violations"][0]["lightsource_id"],
                         "LightSource:499nm:Vis_0")
        self.assertEqual(result["violations"][0]["value"], "0")

    def test_corrupted_multiple(self):
        result = check_ome_xml_bytes(_MULTI_CORRUPTED_XML)
        self.assertTrue(result["corrupted"])
        self.assertEqual(len(result["violations"]), 2)
        ids = {v["lightsource_id"] for v in result["violations"]}
        self.assertIn("LightSource:495nm:SuperCont_0", ids)
        self.assertIn("LightSource:633nm:HeNe_0", ids)

    def test_no_lightsource(self):
        result = check_ome_xml_bytes(_NO_LIGHTSOURCE_XML)
        self.assertFalse(result["corrupted"])

    def test_laser_without_wavelength(self):
        result = check_ome_xml_bytes(_LASER_NO_WAVELENGTH_XML)
        self.assertFalse(result["corrupted"])


class TestFixOmeXmlBytes(unittest.TestCase):

    def test_fix_infers_wavelength(self):
        fixed, changes = fix_ome_xml_bytes(_CORRUPTED_XML)
        self.assertEqual(len(changes), 1)
        self.assertIn('Wavelength="499"', changes[0])
        self.assertIn(b'Wavelength="499"', fixed)
        self.assertNotIn(b'Wavelength="0"', fixed)

    def test_fix_removes_when_no_inference(self):
        fixed, changes = fix_ome_xml_bytes(_CORRUPTED_NO_INFERENCE_XML)
        self.assertEqual(len(changes), 1)
        self.assertIn("removed", changes[0])
        self.assertNotIn(b'Wavelength="0"', fixed)
        self.assertNotIn(b'Wavelength=', fixed)

    def test_no_changes_when_clean(self):
        fixed, changes = fix_ome_xml_bytes(_CLEAN_XML)
        self.assertEqual(changes, [])
        self.assertEqual(fixed, _CLEAN_XML)

    def test_preserves_formatting(self):
        fixed, _ = fix_ome_xml_bytes(_CORRUPTED_XML)
        self.assertIn(b'LaserMedium="Other"', fixed)

    def test_multiple_lightsources(self):
        fixed, changes = fix_ome_xml_bytes(_MULTI_CORRUPTED_XML)
        self.assertEqual(len(changes), 2)
        self.assertIn(b'Wavelength="495"', fixed)
        self.assertIn(b'Wavelength="633"', fixed)
        # The clean one (405) should be untouched
        self.assertIn(b'Wavelength="405"', fixed)

    def test_bytes_roundtrip(self):
        fixed, _ = fix_ome_xml_bytes(_CORRUPTED_XML)
        # Should be valid UTF-8
        fixed.decode('utf-8')


class TestCheckOmeTiff(unittest.TestCase):

    def test_check_clean_tiff(self):
        tiff = _make_tiff(_CLEAN_XML)
        with tempfile.NamedTemporaryFile(suffix='.ome.tif', delete=False) as f:
            f.write(tiff)
            path = f.name
        try:
            result = check_ome_tiff(path)
            self.assertFalse(result["corrupted"])
            self.assertIsNone(result["error"])
        finally:
            os.unlink(path)

    def test_check_corrupted_tiff(self):
        tiff = _make_tiff(_CORRUPTED_XML)
        with tempfile.NamedTemporaryFile(suffix='.ome.tif', delete=False) as f:
            f.write(tiff)
            path = f.name
        try:
            result = check_ome_tiff(path)
            self.assertTrue(result["corrupted"])
            self.assertEqual(len(result["violations"]), 1)
            self.assertIsNone(result["error"])
        finally:
            os.unlink(path)

    def test_check_invalid_tiff(self):
        with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as f:
            f.write(b'NOT A TIFF FILE')
            path = f.name
        try:
            result = check_ome_tiff(path)
            self.assertFalse(result["corrupted"])
            self.assertIsNotNone(result["error"])
        finally:
            os.unlink(path)

    def test_check_big_endian(self):
        tiff = _make_tiff(_CORRUPTED_XML, endian='>')
        with tempfile.NamedTemporaryFile(suffix='.ome.tif', delete=False) as f:
            f.write(tiff)
            path = f.name
        try:
            result = check_ome_tiff(path)
            self.assertTrue(result["corrupted"])
        finally:
            os.unlink(path)


class TestFixOmeTiff(unittest.TestCase):

    def test_fix_corrupted_tiff(self):
        tiff = _make_tiff(_CORRUPTED_XML)
        with tempfile.NamedTemporaryFile(suffix='.ome.tif', delete=False) as f:
            f.write(tiff)
            in_path = f.name
        out_path = in_path + '.fixed.tif'
        try:
            result = fix_ome_tiff(in_path, out_path)
            self.assertTrue(result["success"])
            self.assertEqual(len(result["changes"]), 1)
            self.assertIsNone(result["error"])
            # Verify the output TIFF has fixed XML
            verify = check_ome_tiff(out_path)
            self.assertFalse(verify["corrupted"])
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_fix_clean_tiff_no_changes(self):
        tiff = _make_tiff(_CLEAN_XML)
        with tempfile.NamedTemporaryFile(suffix='.ome.tif', delete=False) as f:
            f.write(tiff)
            in_path = f.name
        out_path = in_path + '.fixed.tif'
        try:
            result = fix_ome_tiff(in_path, out_path)
            self.assertTrue(result["success"])
            self.assertEqual(result["changes"], [])
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_fix_in_place(self):
        tiff = _make_tiff(_CORRUPTED_XML)
        with tempfile.NamedTemporaryFile(suffix='.ome.tif', delete=False) as f:
            f.write(tiff)
            path = f.name
        try:
            result = fix_ome_tiff(path)
            self.assertTrue(result["success"])
            self.assertEqual(result["output_path"], path)
            verify = check_ome_tiff(path)
            self.assertFalse(verify["corrupted"])
        finally:
            os.unlink(path)

    def test_fix_xml_grew(self):
        """When fixed XML is longer (e.g. Wavelength='0' -> '1064'),
        verify the append-at-end strategy works."""
        xml = b"""\
<OME><Instrument><LightSource ID="LightSource:1064nm:Nd_0">\
<Laser Wavelength="0" LaserMedium="Other"/>\
</LightSource></Instrument></OME>"""
        tiff = _make_tiff(xml)
        with tempfile.NamedTemporaryFile(suffix='.ome.tif', delete=False) as f:
            f.write(tiff)
            path = f.name
        try:
            result = fix_ome_tiff(path)
            self.assertTrue(result["success"])
            self.assertIn('1064', result["changes"][0])
            verify = check_ome_tiff(path)
            self.assertFalse(verify["corrupted"])
        finally:
            os.unlink(path)

    def test_fix_invalid_tiff(self):
        with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as f:
            f.write(b'NOT A TIFF')
            path = f.name
        try:
            result = fix_ome_tiff(path)
            self.assertFalse(result["success"])
            self.assertIsNotNone(result["error"])
        finally:
            os.unlink(path)


class TestCheckOmeXmlFile(unittest.TestCase):

    def test_check_clean_file(self):
        with tempfile.NamedTemporaryFile(suffix='.ome.xml', delete=False) as f:
            f.write(_CLEAN_XML)
            path = f.name
        try:
            result = check_ome_xml_file(path)
            self.assertFalse(result["corrupted"])
            self.assertIsNone(result["error"])
        finally:
            os.unlink(path)

    def test_check_corrupted_file(self):
        with tempfile.NamedTemporaryFile(suffix='.ome.xml', delete=False) as f:
            f.write(_CORRUPTED_XML)
            path = f.name
        try:
            result = check_ome_xml_file(path)
            self.assertTrue(result["corrupted"])
            self.assertEqual(len(result["violations"]), 1)
        finally:
            os.unlink(path)


class TestFixOmeXmlFile(unittest.TestCase):

    def test_fix_corrupted_file(self):
        with tempfile.NamedTemporaryFile(suffix='.ome.xml', delete=False) as f:
            f.write(_CORRUPTED_XML)
            in_path = f.name
        out_path = in_path + '.fixed.xml'
        try:
            result = fix_ome_xml_file(in_path, out_path)
            self.assertTrue(result["success"])
            self.assertEqual(len(result["changes"]), 1)
            with open(out_path, 'rb') as f:
                fixed = f.read()
            self.assertIn(b'Wavelength="499"', fixed)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_fix_in_place(self):
        with tempfile.NamedTemporaryFile(suffix='.ome.xml', delete=False) as f:
            f.write(_CORRUPTED_XML)
            path = f.name
        try:
            result = fix_ome_xml_file(path)
            self.assertTrue(result["success"])
            self.assertEqual(result["output_path"], path)
            with open(path, 'rb') as f:
                fixed = f.read()
            self.assertIn(b'Wavelength="499"', fixed)
        finally:
            os.unlink(path)

    def test_fix_clean_file(self):
        with tempfile.NamedTemporaryFile(suffix='.ome.xml', delete=False) as f:
            f.write(_CLEAN_XML)
            path = f.name
        try:
            result = fix_ome_xml_file(path)
            self.assertTrue(result["success"])
            self.assertEqual(result["changes"], [])
        finally:
            os.unlink(path)


class TestUpdateOmeTiffFilename(unittest.TestCase):

    def test_updates_filename_keeps_directory(self):
        tiff = _make_tiff(_ABS_PATH_XML)
        with tempfile.NamedTemporaryFile(
            suffix='.ome.tif', prefix='renamed-', delete=False
        ) as f:
            f.write(tiff)
            path = f.name
        try:
            result = update_ome_tiff_filename(path)
            self.assertTrue(result["success"])
            self.assertTrue(len(result["changes"]) > 0)
            # Verify: directory is preserved, filename is updated
            with open(path, 'rb') as f:
                data = f.read()
            basename = os.path.basename(path)
            self.assertIn(basename.encode(), data)
            # The directory part should still be there
            self.assertIn(b'zmbstaff', data)
            # But the old filename should be gone
            self.assertNotIn(b'image--L0000--C00.ome.tif', data)
        finally:
            os.unlink(path)

    def test_no_changes_when_filename_matches(self):
        """If the filename in the path already matches, no changes."""
        xml = (b'<OME><Image ID="Image:0" '
               b'Name="Z:\\data\\target.ome.tif">'
               b'<Description>Z:\\data\\target.ome.tif</Description>'
               b'</Image></OME>')
        tiff = _make_tiff(xml)
        path = os.path.join(tempfile.gettempdir(), 'target.ome.tif')
        with open(path, 'wb') as f:
            f.write(tiff)
        try:
            result = update_ome_tiff_filename(path)
            self.assertTrue(result["success"])
            self.assertEqual(result["changes"], [])
        finally:
            os.unlink(path)

    def test_tiff_remains_valid(self):
        tiff = _make_tiff(_ABS_PATH_XML)
        with tempfile.NamedTemporaryFile(
            suffix='.ome.tif', prefix='x-', delete=False
        ) as f:
            f.write(tiff)
            path = f.name
        try:
            update_ome_tiff_filename(path)
            check = check_ome_tiff(path)
            self.assertIsNone(check["error"])
        finally:
            os.unlink(path)


class TestUpdateOmeXmlFilename(unittest.TestCase):

    def test_updates_filename_keeps_directory(self):
        with tempfile.NamedTemporaryFile(
            suffix='.ome.xml', prefix='renamed-', delete=False
        ) as f:
            f.write(_ABS_PATH_XML)
            path = f.name
        try:
            result = update_ome_xml_filename(path)
            self.assertTrue(result["success"])
            self.assertTrue(len(result["changes"]) > 0)
            with open(path, 'rb') as f:
                updated = f.read()
            basename = os.path.basename(path)
            self.assertIn(basename.encode(), updated)
            # Directory preserved
            self.assertIn(b'zmbstaff', updated)
            # Old filename gone
            self.assertNotIn(b'image--L0000--C00.ome.tif', updated)
        finally:
            os.unlink(path)

    def test_no_changes_when_filename_matches(self):
        xml = (b'<OME><Image ID="Image:0" '
               b'Name="Z:\\data\\test.ome.xml">'
               b'<Description>Z:\\data\\test.ome.xml</Description>'
               b'</Image></OME>')
        path = os.path.join(tempfile.gettempdir(), 'test.ome.xml')
        with open(path, 'wb') as f:
            f.write(xml)
        try:
            result = update_ome_xml_filename(path)
            self.assertTrue(result["success"])
            self.assertEqual(result["changes"], [])
        finally:
            os.unlink(path)

    def test_updates_both_name_and_description(self):
        with tempfile.NamedTemporaryFile(
            suffix='.ome.xml', prefix='new-', delete=False
        ) as f:
            f.write(_ABS_PATH_XML)
            path = f.name
        try:
            result = update_ome_xml_filename(path)
            name_changes = [c for c in result["changes"] if "Image Name" in c]
            desc_changes = [c for c in result["changes"] if "Description" in c]
            self.assertEqual(len(name_changes), 1)
            self.assertEqual(len(desc_changes), 1)
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
