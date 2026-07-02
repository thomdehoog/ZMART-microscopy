"""
Unit tests for the LRP text-edit primitives and job reordering.
=================================================================
Regression coverage for the driver-cleanup review findings: sibling-attribute
corruption in the text-replace primitives, locale/prolog loss in
``reorder_jobs``, silent deletion of unmappable blocks, vacuous attribute
verification, and cross-job Sequential_Master edits.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from navigator_expert.experimental.lrp_edits._primitives import (
    _set_job_attr,
    _verify_job_attr,
    _verify_job_attr_float,
)
from navigator_expert.experimental.lrp_edits.focus import lrp_set_stack_calculation_mode
from navigator_expert.scanfields.transaction import reorder_jobs

PROLOG = (
    '<?xml version="1.0"?>'
    "<!--Leica Application Suite X (LAS X)-->"
    "<!--Leica Microsystems CMS GmbH-->"
)


def _write_lrp(tmp_path, body, name="{ScanningTemplate}test.lrp"):
    path = tmp_path / name
    path.write_text(PROLOG + body, encoding="utf-8")
    return path


def _job_block(name, block_id, settings='<ATLConfocalSettingDefinition Zoom="1" />'):
    return (
        f'<LDM_Block_Sequence_Block BlockID="{block_id}" BlockType="1">'
        f'<LDM_Block_Sequential BlockName="{name}">'
        f"<LDM_Block_Sequential_List>{settings}</LDM_Block_Sequential_List>"
        f"</LDM_Block_Sequential></LDM_Block_Sequence_Block>"
    )


def _template(elements, blocks):
    return (
        '<Configuration Type="7"><LDM_Block_Sequence BlockName="root">'
        f"<LDM_Block_Sequence_Element_List>{elements}</LDM_Block_Sequence_Element_List>"
        f"<LDM_Block_Sequence_Block_List>{blocks}</LDM_Block_Sequence_Block_List>"
        "</LDM_Block_Sequence></Configuration>"
    )


class TestSetJobAttrSiblingSafety:
    def test_suffix_colliding_sibling_untouched(self, tmp_path):
        # Zoom and BaseZoom coincide: editing Zoom must not rewrite BaseZoom.
        settings = '<ATLConfocalSettingDefinition BaseZoom="1" Zoom="1" />'
        path = _write_lrp(tmp_path, _template("", _job_block("Job A", 1, settings)))
        changed = _set_job_attr(path, "Zoom", "2.5", "Job A", "test")
        assert changed == 1
        el = ET.parse(path).getroot().find(".//ATLConfocalSettingDefinition")
        assert el.get("Zoom") == "2.5"
        assert el.get("BaseZoom") == "1"

    def test_sibling_serialized_first_is_not_edited(self, tmp_path):
        # BaseZoom before Zoom: the unanchored regex used to match inside it.
        settings = '<ATLConfocalSettingDefinition BaseZoom="0.75" Zoom="1" />'
        path = _write_lrp(tmp_path, _template("", _job_block("Job A", 1, settings)))
        changed = _set_job_attr(path, "Zoom", "2.5", "Job A", "test")
        assert changed == 1
        el = ET.parse(path).getroot().find(".//ATLConfocalSettingDefinition")
        assert el.get("Zoom") == "2.5"
        assert el.get("BaseZoom") == "0.75"


class TestVerifyJobAttr:
    def test_absent_attribute_fails_verification(self, tmp_path):
        # _set_job_attr never adds attributes; absent must not verify as True.
        settings = '<ATLConfocalSettingDefinition Zoom="1" />'
        path = _write_lrp(tmp_path, _template("", _job_block("Job A", 1, settings)))
        assert _verify_job_attr(path, "PanFirstDim", "5.0", "Job A") is False
        assert _verify_job_attr_float(path, "PanFirstDim", 5.0, "Job A", 0.001) is False

    def test_present_attribute_verifies(self, tmp_path):
        settings = '<ATLConfocalSettingDefinition Zoom="2.5" />'
        path = _write_lrp(tmp_path, _template("", _job_block("Job A", 1, settings)))
        assert _verify_job_attr(path, "Zoom", "2.5", "Job A") is True
        assert _verify_job_attr_float(path, "Zoom", 2.5, "Job A", 0.001) is True


class TestReorderJobs:
    def _elements(self):
        return (
            '<LDM_Block_Sequence_Element BlockID="1" BlockType="1" />'
            '<LDM_Block_Sequence_Element BlockID="2" BlockType="1" />'
            '<LDM_Block_Sequence_Element BlockID="9" BlockType="0" />'
        )

    def _blocks(self):
        # BlockID 9 has no LDM_Block_Sequential (non-job block type).
        return (
            _job_block("Job A", 1)
            + _job_block("Job B", 2)
            + '<LDM_Block_Sequence_Block BlockID="9" BlockType="0" />'
        )

    def test_moves_job_first_and_keeps_unmappable_entries(self, tmp_path):
        path = _write_lrp(tmp_path, _template(self._elements(), self._blocks()))
        assert reorder_jobs(path, "Job B") is True
        root = ET.parse(path).getroot()
        el_ids = [e.get("BlockID") for e in root.find(".//LDM_Block_Sequence_Element_List")]
        block_ids = [b.get("BlockID") for b in root.find(".//LDM_Block_Sequence_Block_List")]
        assert el_ids == ["2", "1", "9"]  # moved first; unmappable "9" survives
        assert block_ids == ["2", "1", "9"]

    def test_preserves_prolog_and_writes_utf8(self, tmp_path):
        blocks = _job_block("Übersicht µ", 1) + _job_block("Job B", 2)
        elements = (
            '<LDM_Block_Sequence_Element BlockID="1" /><LDM_Block_Sequence_Element BlockID="2" />'
        )
        path = _write_lrp(tmp_path, _template(elements, blocks))
        assert reorder_jobs(path, "Job B") is True
        raw = path.read_bytes()
        text = raw.decode("utf-8")  # must be valid UTF-8, not a locale encoding
        assert text.startswith('<?xml version="1.0"?>')
        assert "<!--Leica Application Suite X (LAS X)-->" in text
        root = ET.fromstring(text)
        names = [s.get("BlockName") for s in root.findall(".//LDM_Block_Sequential")]
        assert names == ["Job B", "Übersicht µ"]

    def test_missing_sequence_element_fails_cleanly(self, tmp_path):
        # Job B has a block but no sequence element: used to raise KeyError.
        elements = '<LDM_Block_Sequence_Element BlockID="1" />'
        path = _write_lrp(tmp_path, _template(elements, self._blocks()))
        assert reorder_jobs(path, "Job B") is False


class TestStackCalculationModeBounded:
    def test_job_without_master_does_not_edit_next_job(self, tmp_path):
        master = (
            "<LDM_Block_Sequential_Master>"
            '<ATLConfocalSettingDefinition StackCalculationMode="0" '
            'StackCalculationModeName="Constant steps" />'
            "</LDM_Block_Sequential_Master>"
        )
        blocks = _job_block("No Master", 1) + (
            f'<LDM_Block_Sequence_Block BlockID="2" BlockType="1">'
            f'<LDM_Block_Sequential BlockName="Has Master">{master}'
            f"</LDM_Block_Sequential></LDM_Block_Sequence_Block>"
        )
        path = _write_lrp(tmp_path, _template("", blocks))
        assert lrp_set_stack_calculation_mode(path, 1, "No Master") == 0
        root = ET.parse(path).getroot()
        el = root.find(".//ATLConfocalSettingDefinition[@StackCalculationMode]")
        assert el.get("StackCalculationMode") == "0"  # the next job's Master untouched
