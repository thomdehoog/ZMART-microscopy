"""
Unit tests for the LRP job/hardware-settings parser (no LAS X needed).
======================================================================
Direct tests for ``scanfields/lrp.py`` (``parse_lrp``, ``_get_job_names``)
against every committed ``.lrp`` fixture, plus the offline-reachable parse
path of ``save_and_read_lrp`` (LS-01).

All expected values below were derived by parsing the committed fixtures
and pinning meaningful invariants of their real content — they are not
invented contracts.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from navigator_expert.scanfields import files as sf_files
from navigator_expert.scanfields.files import TEMPLATE_LRP, save_and_read_lrp
from navigator_expert.scanfields.lrp import _get_job_names, parse_lrp

TEST_DATA = Path(__file__).resolve().parents[1] / "data"
ALL_LRP_FIXTURES = sorted(TEST_DATA.rglob("*.lrp"))

# Every committed fixture is a LAS X export of the same 3-job "collecting
# pattern" sequence (AF Job + Overview + HiRes); only per-job settings differ.
EXPECTED_JOB_NAMES = ["AF Job", "Overview", "HiRes"]

# One fixture is additionally pinned in detail (settings-tree shape + values).
DETAILED_FIXTURE = TEST_DATA / "scanfield_parsing" / "_ScanningTemplate_Test1.lrp"


@pytest.fixture(params=ALL_LRP_FIXTURES, ids=lambda p: p.stem.strip("{}_"))
def lrp_fixture(request):
    return request.param


@pytest.mark.skipif(not ALL_LRP_FIXTURES, reason="no .lrp fixtures found")
class TestParseLrpAllFixtures:
    """Invariants that hold for every committed .lrp fixture."""

    def test_top_level_shape(self, lrp_fixture):
        result = parse_lrp(lrp_fixture)
        assert set(result.keys()) == {"sequence_name", "sequence_elements", "jobs"}
        assert result["sequence_name"] == "collecting pattern"
        # One LDM_Block_Sequence_Element per job, referencing a real BlockID.
        assert len(result["sequence_elements"]) == 3
        block_ids = {j["block_attrs"]["BlockID"] for j in result["jobs"].values()}
        for el in result["sequence_elements"]:
            assert el["BlockID"] in block_ids

    def test_job_names_match_get_job_names(self, lrp_fixture):
        result = parse_lrp(lrp_fixture)
        # parse_lrp's job filter is documented to match _get_job_names.
        assert list(result["jobs"].keys()) == EXPECTED_JOB_NAMES
        assert _get_job_names(lrp_fixture) == EXPECTED_JOB_NAMES

    def test_every_job_has_master_and_sequential_settings(self, lrp_fixture):
        result = parse_lrp(lrp_fixture)
        for name, job in result["jobs"].items():
            assert job["sequential_attrs"]["BlockName"] == name
            assert job["block_attrs"]["BlockType"] == "1"
            for section in ("Master", "Sequential"):
                setting = job[section]
                attrs = setting["attrs"]
                # Core scan settings every ATLConfocalSettingDefinition carries.
                assert float(attrs["Zoom"]) > 0
                assert float(attrs["ScanSpeed"]) > 0
                assert int(attrs["Magnification"]) == 10
                # Hardware sub-trees parsed into "_"-prefixed keys.
                assert len(setting["_Detectors"]) == 6
                assert [ls["LaserName"] for ls in setting["_Lasers"]] == [
                    "Laser 405",
                    "Laser 488",
                    "Laser 638",
                    "Laser 730",
                    "WLL",
                ]
                assert len(setting["_Aotfs"]) == 3
        # Only the AF job carries an AutoFocus settings block.
        assert "AutoFocus" in result["jobs"]["AF Job"]
        assert "AutoFocus" not in result["jobs"]["Overview"]
        assert "AutoFocus" not in result["jobs"]["HiRes"]

    def test_parse_is_deterministic(self, lrp_fixture):
        assert parse_lrp(lrp_fixture) == parse_lrp(lrp_fixture)

    def test_accepts_str_path(self, lrp_fixture):
        assert parse_lrp(str(lrp_fixture)) == parse_lrp(lrp_fixture)


@pytest.mark.skipif(not DETAILED_FIXTURE.is_file(), reason="fixture not found")
class TestParseLrpSettingsTree:
    """Pin the parsed settings tree of one known fixture in detail."""

    @pytest.fixture(scope="class")
    @staticmethod
    def parsed():
        return parse_lrp(DETAILED_FIXTURE)

    def test_per_job_scan_settings(self, parsed):
        # Zoom / scan speed differ per job in this template; pin them.
        expected = {
            "AF Job": ("0.75", "200"),
            "Overview": ("0.75", "600"),
            "HiRes": ("4", "200"),
        }
        for job_name, (zoom, speed) in expected.items():
            attrs = parsed["jobs"][job_name]["Master"]["attrs"]
            assert attrs["Zoom"] == zoom
            assert attrs["ScanSpeed"] == speed
            assert attrs["ObjectiveName"].strip() == "HC PL APO  CS    10x/0.40 DRY"

    def test_stack_fields(self, parsed):
        attrs = parsed["jobs"]["HiRes"]["Master"]["attrs"]
        # Z-stack extent and section count as exported by LAS X.
        assert float(attrs["Begin"]) == pytest.approx(-5.0e-05)
        assert float(attrs["End"]) == pytest.approx(4.9992728235071121e-05)
        assert attrs["Sections"] == "101"
        assert attrs["StackCalculationModeName"] == "Constant step size"

    def test_detector_subtree(self, parsed):
        det0 = parsed["jobs"]["HiRes"]["Master"]["_Detectors"][0]
        assert det0["Name"] == "HyD S 1"
        assert det0["Type"] == "SiPM"
        assert det0["Channel"] == "1"
        # Child elements parsed into "_"-prefixed sub-dicts.
        assert isinstance(det0["_BeamRoute"], list)
        assert {"BeamPositionLevel", "BeamPosition"} <= set(det0["_BeamRoute"][0])
        assert "_LutInfo" in det0

    def test_laser_and_aotf_subtrees(self, parsed):
        master = parsed["jobs"]["HiRes"]["Master"]
        laser405 = master["_Lasers"][0]
        assert laser405["Wavelength"] == "405"
        assert laser405["_BeamRoute"] == [{"BeamPositionLevel": "0", "BeamPosition": "30"}]
        aotf_uv = master["_Aotfs"][0]
        assert aotf_uv["LightSourceName"] == "UV"
        assert aotf_uv["_LaserLines"][0]["LaserLine"] == "405"

    def test_filter_wheel_and_luts(self, parsed):
        master = parsed["jobs"]["HiRes"]["Master"]
        wheels = master["_FilterWheel"]["_Wheels"]
        assert len(wheels) == 8
        assert "Galvo X Pan Center" in [n.strip() for n in wheels[0]["_WheelNames"]]
        assert master["_LUTs"][0]["LutName"] == "Gray"
        assert len(master["_LUTs"]) == 6

    def test_autofocus_config_only_on_af_capable_settings(self, parsed):
        af = parsed["jobs"]["AF Job"]["Master"]["_AutofocusConfig"]
        assert af["ZUseModeName"] == "z-galvo"
        assert af["AFSubsystemName"] == "ConfocalAF"
        # The Sequential setting carries no autofocus config.
        assert "_AutofocusConfig" not in parsed["jobs"]["AF Job"]["Sequential"]

    def test_additional_z_positions(self, parsed):
        zpos = parsed["jobs"]["AF Job"]["Master"]["_AdditionalZPositions"]
        assert [z["ZUseModeName"] for z in zpos] == ["z-galvo", "z-wide"]

    def test_spectral_windows(self, parsed):
        bands = parsed["jobs"]["HiRes"]["Master"]["_MultiBands"]
        assert len(bands) == 5
        assert bands[0]["ChannelName"] == "Channel 1"
        assert float(bands[0]["LeftWorld"]) < float(bands[0]["RightWorld"])


# The committed fixtures carry no ROIs, no duplicate job names, and no
# non-job blocks; those parser paths are pinned with a synthetic LRP instead.
SYNTHETIC_LRP = """\
<LDM_Block_Sequence BlockName="synthetic sequence">
  <LDM_Block_Sequence_Element_List>
    <LDM_Block_Sequence_Element BlockID="1" ElementID="1" />
  </LDM_Block_Sequence_Element_List>
  <LDM_Block_Sequence_Block BlockID="2" BlockType="1">
    <LDM_Block_Sequential BlockName="ROI Job" Marker="first" />
  </LDM_Block_Sequence_Block>
  <LDM_Block_Sequence_Block BlockID="1" BlockType="1">
    <LDM_Block_Sequential BlockName="ROI Job" Marker="second">
      <LDM_Block_Sequential_Master>
        <ATLConfocalSettingDefinition Zoom="2" ScanSpeed="100">
          <ROI>
            <Children>
              <ROISingle Identifier="roi-1" Type="Polygon">
                <Vertices>
                  <Vertex X="0.1" Y="0.2" />
                  <Vertex X="0.3" Y="not-a-number" />
                  <Vertex />
                </Vertices>
                <Transformation Rotation="90">
                  <Scaling XScale="1.5" YScale="2.5" />
                  <Translation X="5" Y="6" />
                </Transformation>
              </ROISingle>
            </Children>
          </ROI>
          <STED_DepletionLine Wavelength="775">
            <BeamRoute><BeamPosition BeamPositionLevel="0" BeamPosition="7" /></BeamRoute>
          </STED_DepletionLine>
          <AotfList>
            <Aotf LightSourceName="STED">
              <LaserLineSetting LaserLine="775">
                <BeamRoute><BeamPosition BeamPositionLevel="0" BeamPosition="2" /></BeamRoute>
              </LaserLineSetting>
            </Aotf>
          </AotfList>
        </ATLConfocalSettingDefinition>
      </LDM_Block_Sequential_Master>
    </LDM_Block_Sequential>
  </LDM_Block_Sequence_Block>
  <LDM_Block_Sequence_Block BlockID="3" BlockType="0">
    <LDM_Block_Sequential BlockName="Not A Job" />
  </LDM_Block_Sequence_Block>
  <LDM_Block_Sequence_Block BlockID="4" BlockType="1" />
</LDM_Block_Sequence>
"""


class TestParseLrpSyntheticEdgeCases:
    @pytest.fixture
    def synthetic(self, tmp_path):
        p = tmp_path / "synthetic.lrp"
        p.write_text(SYNTHETIC_LRP)
        return p

    def test_roi_vertices_and_transformation(self, synthetic):
        result = parse_lrp(synthetic)
        rois = result["jobs"]["ROI Job"]["Master"]["_ROIs"]
        assert len(rois) == 1
        roi = rois[0]
        assert roi["Identifier"] == "roi-1"
        # Non-numeric / missing vertex coordinates are dropped per-attribute.
        assert roi["_Vertices"] == [{"X": 0.1, "Y": 0.2}, {"X": 0.3}]
        assert roi["_Transformation"] == {
            "Rotation": "90",
            "XScale": "1.5",
            "YScale": "2.5",
            "TranslationX": "5",
            "TranslationY": "6",
        }

    def test_sted_and_laser_line_beam_routes(self, synthetic):
        master = parse_lrp(synthetic)["jobs"]["ROI Job"]["Master"]
        assert master["_STED"]["Wavelength"] == "775"
        assert master["_STED"]["_BeamRoute"] == [{"BeamPositionLevel": "0", "BeamPosition": "7"}]
        line = master["_Aotfs"][0]["_LaserLines"][0]
        assert line["_BeamRoute"] == [{"BeamPositionLevel": "0", "BeamPosition": "2"}]

    def test_duplicate_job_name_keeps_last_and_warns(self, synthetic, caplog):
        with caplog.at_level("WARNING", logger="navigator_expert.scanfields.lrp"):
            result = parse_lrp(synthetic)
        assert result["jobs"]["ROI Job"]["sequential_attrs"]["Marker"] == "second"
        assert any("duplicate job name 'ROI Job'" in r.message for r in caplog.records)

    def test_non_job_blocks_are_filtered(self, synthetic):
        # BlockType 0 and sequential-less blocks are skipped by both parsers.
        assert list(parse_lrp(synthetic)["jobs"].keys()) == ["ROI Job"]
        assert _get_job_names(synthetic) == ["ROI Job", "ROI Job"]


class TestParseLrpGarbageInput:
    """Pin the actual failure modes on bad input (they are exceptions)."""

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_lrp(tmp_path / "does_not_exist.lrp")
        with pytest.raises(FileNotFoundError):
            _get_job_names(tmp_path / "does_not_exist.lrp")

    def test_non_xml_raises_parse_error(self, tmp_path):
        bad = tmp_path / "garbage.lrp"
        bad.write_text("this is { not xml at all")
        with pytest.raises(ET.ParseError):
            parse_lrp(bad)
        with pytest.raises(ET.ParseError):
            _get_job_names(bad)

    @pytest.mark.skipif(not ALL_LRP_FIXTURES, reason="no .lrp fixtures found")
    def test_truncated_xml_raises_parse_error(self, tmp_path):
        content = ALL_LRP_FIXTURES[0].read_bytes()
        trunc = tmp_path / "truncated.lrp"
        trunc.write_bytes(content[: len(content) // 2])
        with pytest.raises(ET.ParseError):
            parse_lrp(trunc)

    def test_valid_xml_without_ldm_blocks_returns_empty_result(self, tmp_path):
        empty = tmp_path / "empty.lrp"
        empty.write_text("<NotAnLrp/>")
        assert parse_lrp(empty) == {
            "sequence_name": "",
            "sequence_elements": [],
            "jobs": {},
        }
        assert _get_job_names(empty) == []


@pytest.mark.skipif(not ALL_LRP_FIXTURES, reason="no .lrp fixtures found")
class TestSaveAndReadLrpParsePath:
    """Offline coverage of save_and_read_lrp's parse path.

    The CAM save itself needs a live client; here the template dir and the
    save call are stubbed so only the real path resolution + parse_lrp run.
    """

    @pytest.fixture
    def template_dir(self, tmp_path, monkeypatch):
        (tmp_path / TEMPLATE_LRP).write_bytes(ALL_LRP_FIXTURES[0].read_bytes())
        monkeypatch.setattr(sf_files, "find_scanning_templates_dir", lambda: str(tmp_path))
        return tmp_path

    def test_parses_saved_template(self, template_dir, monkeypatch):
        seen = {}

        def fake_save(client, name, tdir, timeout):
            seen["args"] = (client, name, str(tdir))
            return {"success": True}

        monkeypatch.setattr(sf_files, "save_experiment", fake_save)
        result = save_and_read_lrp(client="dummy-client", timeout=1.0)
        assert result == parse_lrp(ALL_LRP_FIXTURES[0])
        assert seen["args"] == ("dummy-client", sf_files.TEMPLATE_XML, str(template_dir))

    def test_returns_none_when_save_fails(self, template_dir, monkeypatch):
        monkeypatch.setattr(sf_files, "save_experiment", lambda *a, **k: None)
        assert save_and_read_lrp(client="dummy-client") is None

    def test_returns_none_when_parse_fails(self, template_dir, monkeypatch):
        (template_dir / TEMPLATE_LRP).write_text("not xml {")
        monkeypatch.setattr(sf_files, "save_experiment", lambda *a, **k: {"success": True})
        assert save_and_read_lrp(client="dummy-client") is None

    def test_returns_none_without_templates_dir(self, monkeypatch):
        monkeypatch.setattr(sf_files, "find_scanning_templates_dir", lambda: None)
        assert save_and_read_lrp(client="dummy-client") is None
