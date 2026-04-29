"""
Unit tests for scanning_templates orchestration functions.
===========================================================
Covers: reorder_jobs, save_experiment, load_experiment, apply_lrp_change,
        strip_template, restore_template.

No LAS X connection needed — all API calls are mocked.

Run with: python -m pytest test_scanning_templates_orchestration_unit.py -v
"""

import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lasx.scanning_templates import (
    reorder_jobs,
    save_experiment,
    load_experiment,
    apply_lrp_change,
    strip_template,
    restore_template,
    find_scanning_templates_dir,
    _count_objects,
    _strip_xml,
    _strip_rgn,
    _wait_file_stable,
    TEMPLATE_XML, TEMPLATE_RGN, TEMPLATE_LRP,
    STRIPPED_XML, STRIPPED_RGN, STRIPPED_LRP,
    TEMPLATE_BASE,
)


# ═══════════════════════════════════════════════════════════════════════
# Sample LRP with two jobs
# ═══════════════════════════════════════════════════════════════════════

TWO_JOB_LRP = """\
<?xml version="1.0" encoding="utf-8"?>
<LDM_Block_Sequence BlockName="MySequence">
  <LDM_Block_Sequence_Element_List>
    <LDM_Block_Sequence_Element BlockID="b1" />
    <LDM_Block_Sequence_Element BlockID="b2" />
  </LDM_Block_Sequence_Element_List>
  <LDM_Block_Sequence_Block_List>
    <LDM_Block_Sequence_Block BlockID="b1" BlockType="1">
      <LDM_Block_Sequential BlockName="HiRes">
        <LDM_Block_Sequential_Master>
          <ATLConfocalSettingDefinition StackCalculationMode="1" />
        </LDM_Block_Sequential_Master>
      </LDM_Block_Sequential>
    </LDM_Block_Sequence_Block>
    <LDM_Block_Sequence_Block BlockID="b2" BlockType="1">
      <LDM_Block_Sequential BlockName="Overview">
        <LDM_Block_Sequential_Master>
          <ATLConfocalSettingDefinition StackCalculationMode="0" />
        </LDM_Block_Sequential_Master>
      </LDM_Block_Sequential>
    </LDM_Block_Sequence_Block>
  </LDM_Block_Sequence_Block_List>
</LDM_Block_Sequence>
"""

THREE_JOB_LRP = """\
<?xml version="1.0" encoding="utf-8"?>
<LDM_Block_Sequence BlockName="MySequence">
  <LDM_Block_Sequence_Element_List>
    <LDM_Block_Sequence_Element BlockID="b1" />
    <LDM_Block_Sequence_Element BlockID="b2" />
    <LDM_Block_Sequence_Element BlockID="b3" />
  </LDM_Block_Sequence_Element_List>
  <LDM_Block_Sequence_Block_List>
    <LDM_Block_Sequence_Block BlockID="b1" BlockType="1">
      <LDM_Block_Sequential BlockName="HiRes">
        <LDM_Block_Sequential_Master />
      </LDM_Block_Sequential>
    </LDM_Block_Sequence_Block>
    <LDM_Block_Sequence_Block BlockID="b2" BlockType="1">
      <LDM_Block_Sequential BlockName="Overview">
        <LDM_Block_Sequential_Master />
      </LDM_Block_Sequential>
    </LDM_Block_Sequence_Block>
    <LDM_Block_Sequence_Block BlockID="b3" BlockType="1">
      <LDM_Block_Sequential BlockName="Timelapse">
        <LDM_Block_Sequential_Master />
      </LDM_Block_Sequential>
    </LDM_Block_Sequence_Block>
  </LDM_Block_Sequence_Block_List>
</LDM_Block_Sequence>
"""


@pytest.fixture
def lrp_two_jobs(tmp_path):
    lrp = tmp_path / "test.lrp"
    lrp.write_text(TWO_JOB_LRP, encoding="utf-8")
    return lrp


@pytest.fixture
def lrp_three_jobs(tmp_path):
    lrp = tmp_path / "test.lrp"
    lrp.write_text(THREE_JOB_LRP, encoding="utf-8")
    return lrp


def _get_job_order(lrp_path):
    """Read job order from an LRP's element list."""
    root = ET.parse(lrp_path).getroot()
    block_list = root.find(".//LDM_Block_Sequence_Block_List")
    block_to_job = {}
    for b in block_list:
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None:
            block_to_job[b.get("BlockID")] = seq.get("BlockName")
    el_list = root.find(".//LDM_Block_Sequence_Element_List")
    return [block_to_job[e.get("BlockID")] for e in el_list
            if e.get("BlockID") in block_to_job]


def _get_block_order(lrp_path):
    """Read block order from an LRP's block list."""
    root = ET.parse(lrp_path).getroot()
    block_list = root.find(".//LDM_Block_Sequence_Block_List")
    order = []
    for b in block_list:
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None:
            order.append(seq.get("BlockName"))
    return order


# ═══════════════════════════════════════════════════════════════════════
# reorder_jobs
# ═══════════════════════════════════════════════════════════════════════

class TestReorderJobs:
    def test_moves_job_to_first(self, lrp_two_jobs):
        assert reorder_jobs(lrp_two_jobs, "Overview") is True
        assert _get_job_order(lrp_two_jobs) == ["Overview", "HiRes"]
        assert _get_block_order(lrp_two_jobs) == ["Overview", "HiRes"]

    def test_already_first_is_noop(self, lrp_two_jobs):
        assert reorder_jobs(lrp_two_jobs, "HiRes") is True
        assert _get_job_order(lrp_two_jobs) == ["HiRes", "Overview"]

    def test_missing_job_returns_false(self, lrp_two_jobs):
        assert reorder_jobs(lrp_two_jobs, "NoSuchJob") is False

    def test_all_jobs_preserved_after_reorder(self, lrp_three_jobs):
        reorder_jobs(lrp_three_jobs, "Timelapse")
        order = _get_job_order(lrp_three_jobs)
        assert set(order) == {"HiRes", "Overview", "Timelapse"}
        assert order[0] == "Timelapse"
        assert _get_block_order(lrp_three_jobs)[0] == "Timelapse"

    def test_three_jobs_middle_to_first(self, lrp_three_jobs):
        reorder_jobs(lrp_three_jobs, "Overview")
        order = _get_job_order(lrp_three_jobs)
        assert order == ["Overview", "HiRes", "Timelapse"]

    def test_missing_element_list_returns_false(self, tmp_path):
        lrp = tmp_path / "bad.lrp"
        lrp.write_text(
            '<LDM_Block_Sequence>'
            '<LDM_Block_Sequence_Block_List>'
            '<LDM_Block_Sequence_Block BlockID="b1" BlockType="1">'
            '<LDM_Block_Sequential BlockName="J1" />'
            '</LDM_Block_Sequence_Block>'
            '</LDM_Block_Sequence_Block_List>'
            '</LDM_Block_Sequence>',
            encoding="utf-8",
        )
        assert reorder_jobs(lrp, "J1") is False

    def test_missing_block_list_returns_false(self, tmp_path):
        lrp = tmp_path / "bad.lrp"
        lrp.write_text(
            '<LDM_Block_Sequence>'
            '<LDM_Block_Sequence_Element_List>'
            '<LDM_Block_Sequence_Element BlockID="b1" />'
            '</LDM_Block_Sequence_Element_List>'
            '</LDM_Block_Sequence>',
            encoding="utf-8",
        )
        assert reorder_jobs(lrp, "J1") is False


# ═══════════════════════════════════════════════════════════════════════
# Mock client fixture
# ═══════════════════════════════════════════════════════════════════════

class _MockModel:
    def __init__(self):
        self.ExperimentName = ""

class _MockApi:
    def __init__(self, succeed=True):
        self.Model = _MockModel()
        self._succeed = succeed
        self._call_count = 0

    def UpdateAwaitReceipt(self, timeout):
        self._call_count += 1
        return self._succeed


def make_mock_client(save_ok=True, load_ok=True):
    client = MagicMock()
    client.PyApiSaveExperiment = _MockApi(succeed=save_ok)
    client.PyApiLoadExperiment = _MockApi(succeed=load_ok)
    return client


# ═══════════════════════════════════════════════════════════════════════
# save_experiment
# ═══════════════════════════════════════════════════════════════════════

class TestSaveExperiment:
    def test_success_file_stable(self, tmp_path):
        """Save succeeds when file exists, gets new mtime, and stabilises."""
        watch = tmp_path / "test.xml"
        watch.write_text("<old/>", encoding="utf-8")
        old_mtime = watch.stat().st_mtime

        client = make_mock_client()

        # Simulate LAS X writing a new file after receipt
        orig_receipt = client.PyApiSaveExperiment.UpdateAwaitReceipt
        def _receipt_and_write(timeout):
            result = orig_receipt(timeout)
            time.sleep(0.02)  # ensure mtime advances
            watch.write_text("<new/>", encoding="utf-8")
            return result
        client.PyApiSaveExperiment.UpdateAwaitReceipt = _receipt_and_write

        r = save_experiment(client, "test.xml", tmp_path,
                            timeout=5, poll_interval=0.01)
        assert r is not None
        assert r["success"] is True
        assert r["confirmed"] is True
        assert "timing" in r

    def test_receipt_failure_twice_returns_none(self, tmp_path):
        watch = tmp_path / "test.xml"
        watch.write_text("<x/>", encoding="utf-8")
        client = make_mock_client(save_ok=False)
        r = save_experiment(client, "test.xml", tmp_path, timeout=1)
        assert r is None

    def test_receipt_retries_once_on_first_failure(self, tmp_path):
        watch = tmp_path / "test.xml"
        watch.write_text("<x/>", encoding="utf-8")

        client = make_mock_client()
        call_count = [0]
        def _fail_then_succeed(timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                return False
            # Write new file on second call
            time.sleep(0.02)
            watch.write_text("<new/>", encoding="utf-8")
            return True
        client.PyApiSaveExperiment.UpdateAwaitReceipt = _fail_then_succeed

        r = save_experiment(client, "test.xml", tmp_path,
                            timeout=5, poll_interval=0.01)
        assert r is not None
        assert r["success"] is True
        assert call_count[0] == 2

    def test_timeout_returns_none(self, tmp_path):
        """If file never appears, returns None."""
        watch = tmp_path / "test.xml"
        watch.write_text("<old/>", encoding="utf-8")
        client = make_mock_client()
        # Receipt succeeds but file never changes → timeout
        r = save_experiment(client, "test.xml", tmp_path,
                            timeout=0.1, poll_interval=0.01)
        assert r is None

    def test_custom_confirm_path(self, tmp_path):
        xml_path = tmp_path / "test.xml"
        rgn_path = tmp_path / "test.rgn"
        xml_path.write_text("<xml/>", encoding="utf-8")
        rgn_path.write_text("<rgn/>", encoding="utf-8")

        client = make_mock_client()
        orig = client.PyApiSaveExperiment.UpdateAwaitReceipt
        def _receipt_and_write(timeout):
            result = orig(timeout)
            time.sleep(0.02)
            rgn_path.write_text("<rgn-new/>", encoding="utf-8")
            return result
        client.PyApiSaveExperiment.UpdateAwaitReceipt = _receipt_and_write

        r = save_experiment(client, "test.xml", tmp_path,
                            timeout=5, poll_interval=0.01,
                            confirm_path=rgn_path)
        assert r is not None
        assert r["success"] is True

    def test_result_dict_shape(self, tmp_path):
        watch = tmp_path / "test.xml"
        watch.write_text("<old/>", encoding="utf-8")

        client = make_mock_client()
        orig = client.PyApiSaveExperiment.UpdateAwaitReceipt
        def _receipt_and_write(timeout):
            result = orig(timeout)
            time.sleep(0.02)
            watch.write_text("<new/>", encoding="utf-8")
            return result
        client.PyApiSaveExperiment.UpdateAwaitReceipt = _receipt_and_write

        r = save_experiment(client, "test.xml", tmp_path,
                            timeout=5, poll_interval=0.01)
        assert set(r.keys()) == {"success", "confirmed", "message", "timing",
                                  "logs"}
        timing = r["timing"]
        assert "fire_s" in timing
        assert "confirm_s" in timing
        assert "total_s" in timing
        assert timing["method"] == "async"


# ═══════════════════════════════════════════════════════════════════════
# load_experiment
# ═══════════════════════════════════════════════════════════════════════

class TestLoadExperiment:
    def test_success(self):
        client = make_mock_client()
        r = load_experiment(client, "test.xml")
        assert r is not None
        assert r["success"] is True
        assert r["confirmed"] is False  # load is receipt-only

    def test_receipt_failure_twice_returns_none(self):
        client = make_mock_client(load_ok=False)
        r = load_experiment(client, "test.xml")
        assert r is None

    def test_receipt_retries_once_on_first_failure(self):
        client = make_mock_client()
        call_count = [0]
        def _fail_then_succeed(timeout):
            call_count[0] += 1
            return call_count[0] > 1
        client.PyApiLoadExperiment.UpdateAwaitReceipt = _fail_then_succeed
        r = load_experiment(client, "test.xml")
        assert r is not None
        assert call_count[0] == 2

    def test_result_dict_shape(self):
        client = make_mock_client()
        r = load_experiment(client, "test.xml")
        assert set(r.keys()) == {"success", "confirmed", "message", "timing",
                                  "logs"}
        assert "LoadExperiment" in r["message"]


# ═══════════════════════════════════════════════════════════════════════
# apply_lrp_change
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Experiment>
  <ScanFields>
    <ScanFieldData IsEnabled="true" UniqueID="1" />
  </ScanFields>
</Experiment>
"""

SAMPLE_RGN = """\
<?xml version="1.0" encoding="utf-8"?>
<StageOverviewRegions>
  <Regions><ShapeList><Items /><FillMaskMode>None</FillMaskMode>
  <VertexUnitMode>Pixels</VertexUnitMode></ShapeList></Regions>
  <FocusMap ZMode="1" />
</StageOverviewRegions>
"""


def _make_templates_dir(tmp_path):
    """Create a fake ScanningTemplates dir with template files."""
    td = tmp_path / "ScanningTemplates"
    td.mkdir()
    (td / TEMPLATE_XML).write_text(SAMPLE_XML, encoding="utf-8")
    (td / TEMPLATE_RGN).write_text(SAMPLE_RGN, encoding="utf-8")
    (td / TEMPLATE_LRP).write_text(TWO_JOB_LRP, encoding="utf-8")
    return td


def _save_that_touches_file(templates_dir, xml_name):
    """Return a side_effect for save_experiment that updates the file mtime."""
    def _fake_save(client, name, tdir, **kwargs):
        p = Path(tdir) / name
        if p.is_file():
            time.sleep(0.01)
            p.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        return {
            "success": True, "confirmed": True,
            "message": f"SaveExperiment '{name}'",
            "timing": {"fire_s": 0, "confirm_s": 0, "total_s": 0,
                        "attempts": 1, "method": "async"},
            "logs": [],
        }
    return _fake_save


def _fake_load(client, name):
    return {
        "success": True, "confirmed": False,
        "message": f"LoadExperiment '{name}'",
        "timing": {"fire_s": 0, "total_s": 0, "attempts": 1,
                    "method": "async"},
        "logs": [],
    }


class TestApplyLrpChange:
    """Tests for the generic LRP edit backbone."""

    def _patch_infra(self, tmp_path):
        """Return a context manager that patches find_dir, save, load, get_job."""
        td = _make_templates_dir(tmp_path)
        patches = {
            "find": patch(
                "lasx.scanning_templates.find_scanning_templates_dir",
                return_value=td),
            "save": patch(
                "lasx.scanning_templates.save_experiment",
                side_effect=_save_that_touches_file(td, TEMPLATE_XML)),
            "load": patch(
                "lasx.scanning_templates.load_experiment",
                side_effect=_fake_load),
            "job": patch(
                "lasx.scanning_templates.get_selected_job",
                return_value={"Name": "HiRes", "IsSelected": True}),
        }
        return td, patches

    def test_success_path(self, tmp_path):
        td, patches = self._patch_infra(tmp_path)
        edit_fn = MagicMock(return_value=42)
        with patches["find"], patches["save"], patches["load"], patches["job"]:
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, edit_fn,
                                 confirm_delays=(0.5,))
        assert r is not None
        assert r["success"] is True
        assert r["edit_result"] == 42
        assert r["attempts"] == 1
        edit_fn.assert_called_once()

    def test_initial_save_failure_returns_none(self, tmp_path):
        td, patches = self._patch_infra(tmp_path)
        # First save returns None (failure)
        save_calls = [0]
        def _save_fail_first(client, name, tdir, **kwargs):
            save_calls[0] += 1
            if save_calls[0] == 1:
                return None
            return _save_that_touches_file(td, name)(client, name, tdir,
                                                      **kwargs)
        patches["save"] = patch(
            "lasx.scanning_templates.save_experiment",
            side_effect=_save_fail_first)
        with patches["find"], patches["save"], patches["load"], patches["job"]:
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, MagicMock(),
                                 confirm_delays=(0.5,))
        assert r is None

    def test_load_failure_returns_none(self, tmp_path):
        td, patches = self._patch_infra(tmp_path)
        patches["load"] = patch(
            "lasx.scanning_templates.load_experiment",
            return_value=None)
        with patches["find"], patches["save"], patches["load"], patches["job"]:
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, MagicMock(),
                                 confirm_delays=(0.5,))
        assert r is None

    def test_retries_on_verify_failure(self, tmp_path):
        td, patches = self._patch_infra(tmp_path)
        verify_fn = MagicMock(return_value=False)
        with patches["find"], patches["save"], patches["load"], patches["job"]:
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, MagicMock(),
                                 verify_fn=verify_fn,
                                 confirm_delays=(0.1, 0.1, 0.1))
        assert r is None
        assert verify_fn.call_count == 3

    def test_succeeds_on_second_verify_attempt(self, tmp_path):
        td, patches = self._patch_infra(tmp_path)
        verify_calls = [0]
        def _verify(path):
            verify_calls[0] += 1
            return verify_calls[0] >= 2
        with patches["find"], patches["save"], patches["load"], patches["job"]:
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, MagicMock(),
                                 verify_fn=_verify,
                                 confirm_delays=(0.1, 0.1, 0.1))
        assert r is not None
        assert r["success"] is True
        assert r["attempts"] == 2

    def test_no_verify_fn_assumes_success(self, tmp_path):
        td, patches = self._patch_infra(tmp_path)
        with patches["find"], patches["save"], patches["load"], patches["job"]:
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, MagicMock(),
                                 verify_fn=None, confirm_delays=(0.5,))
        assert r is not None
        assert r["success"] is True

    def test_edit_fn_result_in_return_dict(self, tmp_path):
        td, patches = self._patch_infra(tmp_path)
        edit_fn = MagicMock(return_value={"changed": 3})
        with patches["find"], patches["save"], patches["load"], patches["job"]:
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, edit_fn,
                                 confirm_delays=(0.5,))
        assert r["edit_result"] == {"changed": 3}

    def test_active_job_preserved_via_reorder(self, tmp_path):
        td, patches = self._patch_infra(tmp_path)
        # Patch get_selected_job to return "Overview" (second job)
        patches["job"] = patch(
            "lasx.scanning_templates.get_selected_job",
            return_value={"Name": "Overview", "IsSelected": True})
        with patches["find"], patches["save"], patches["load"], \
             patches["job"], \
             patch("lasx.scanning_templates.reorder_jobs") as mock_reorder:
            mock_reorder.return_value = True
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, MagicMock(),
                                 confirm_delays=(0.5,))
        mock_reorder.assert_called_once()
        assert mock_reorder.call_args[0][1] == "Overview"

    def test_no_active_job_skips_reorder(self, tmp_path):
        td, patches = self._patch_infra(tmp_path)
        patches["job"] = patch(
            "lasx.scanning_templates.get_selected_job",
            return_value=None)
        with patches["find"], patches["save"], patches["load"], \
             patches["job"], \
             patch("lasx.scanning_templates.reorder_jobs") as mock_reorder:
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, MagicMock(),
                                 confirm_delays=(0.5,))
        mock_reorder.assert_not_called()

    def test_no_templates_dir_returns_none(self):
        with patch("lasx.scanning_templates.find_scanning_templates_dir",
                   return_value=None):
            r = apply_lrp_change(MagicMock(), TEMPLATE_XML, MagicMock())
        assert r is None


# ═══════════════════════════════════════════════════════════════════════
# strip_template
# ═══════════════════════════════════════════════════════════════════════

class TestStripTemplate:
    def _setup(self, tmp_path):
        td = _make_templates_dir(tmp_path)
        p_find = patch(
            "lasx.scanning_templates.find_scanning_templates_dir",
            return_value=td)
        return td, p_find

    def _mock_save(self, td):
        """Return a save mock that touches the confirm_path file."""
        def _save(client, name, tdir, **kwargs):
            confirm = kwargs.get("confirm_path")
            if confirm and Path(confirm).is_file():
                time.sleep(0.01)
                Path(confirm).write_text(
                    Path(confirm).read_text(encoding="utf-8"),
                    encoding="utf-8")
            elif (Path(tdir) / name).is_file():
                time.sleep(0.01)
                p = Path(tdir) / name
                p.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            return {
                "success": True, "confirmed": True,
                "message": f"SaveExperiment '{name}'",
                "timing": {"fire_s": 0, "confirm_s": 0, "total_s": 0,
                            "attempts": 1, "method": "async"},
                "logs": [],
            }
        return patch("lasx.scanning_templates.save_experiment",
                      side_effect=_save)

    def test_creates_stripped_files(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        with p_find, self._mock_save(td), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load):
            r = strip_template(MagicMock())
        assert r is not None
        assert r["success"] is True
        assert (td / STRIPPED_XML).is_file()
        assert (td / STRIPPED_RGN).is_file()
        assert (td / STRIPPED_LRP).is_file()

    def test_result_contains_original_counts(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        with p_find, self._mock_save(td), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load):
            r = strip_template(MagicMock())
        assert r["original_fields"] == 1
        assert r["original_items"] == 0  # SAMPLE_XML has 1 ScanFieldData
        assert "total_s" in r

    def test_initial_save_failure_returns_none(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        with p_find, \
             patch("lasx.scanning_templates.save_experiment",
                   return_value=None), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load):
            r = strip_template(MagicMock())
        assert r is None

    def test_load_failure_returns_none(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        with p_find, self._mock_save(td), \
             patch("lasx.scanning_templates.load_experiment",
                   return_value=None):
            r = strip_template(MagicMock())
        assert r is None

    def test_confirm_save_failure_returns_none(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        save_calls = [0]
        def _save_fail_second(client, name, tdir, **kwargs):
            save_calls[0] += 1
            if save_calls[0] == 1:
                # First save (initial) succeeds
                return {
                    "success": True, "confirmed": True,
                    "message": "ok", "timing": {}, "logs": [],
                }
            # Second save (confirm stripped) fails
            return None
        with p_find, \
             patch("lasx.scanning_templates.save_experiment",
                   side_effect=_save_fail_second), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load):
            r = strip_template(MagicMock())
        assert r is None

    def test_no_templates_dir_returns_none(self):
        with patch("lasx.scanning_templates.find_scanning_templates_dir",
                   return_value=None):
            r = strip_template(MagicMock())
        assert r is None

    def test_lrp_copied_to_stripped(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        with p_find, self._mock_save(td), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load):
            strip_template(MagicMock())
        orig_lrp = (td / TEMPLATE_LRP).read_text(encoding="utf-8")
        stripped_lrp = (td / STRIPPED_LRP).read_text(encoding="utf-8")
        assert stripped_lrp == orig_lrp


# ═══════════════════════════════════════════════════════════════════════
# restore_template
# ═══════════════════════════════════════════════════════════════════════

class TestRestoreTemplate:
    def _setup(self, tmp_path):
        """Create templates dir with original + stripped files."""
        td = _make_templates_dir(tmp_path)
        # Create stripped files (as if strip_template ran)
        _strip_xml(td / TEMPLATE_XML, td / STRIPPED_XML)
        _strip_rgn(td / TEMPLATE_RGN, td / STRIPPED_RGN)
        # Stripped LRP has modified content (simulates user edits)
        (td / STRIPPED_LRP).write_text(
            TWO_JOB_LRP.replace("MySequence", "ModifiedSequence"),
            encoding="utf-8")
        p_find = patch(
            "lasx.scanning_templates.find_scanning_templates_dir",
            return_value=td)
        return td, p_find

    def _mock_save_ok(self, td):
        """Save mock that touches the confirm_path and preserves files."""
        def _save(client, name, tdir, **kwargs):
            confirm = kwargs.get("confirm_path")
            target = Path(confirm) if confirm else Path(tdir) / name
            if target.is_file():
                time.sleep(0.01)
                target.write_text(
                    target.read_text(encoding="utf-8"), encoding="utf-8")
            return {
                "success": True, "confirmed": True,
                "message": f"SaveExperiment '{name}'",
                "timing": {}, "logs": [],
            }
        return patch("lasx.scanning_templates.save_experiment",
                      side_effect=_save)

    def test_success_restores_object_counts(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        with p_find, self._mock_save_ok(td), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load), \
             patch("lasx.scanning_templates._wait_file_stable",
                   return_value=True):
            r = restore_template(MagicMock())
        assert r is not None
        assert r["success"] is True
        assert r["attempts"] == 1

    def test_modified_lrp_copied_back(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        with p_find, self._mock_save_ok(td), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load), \
             patch("lasx.scanning_templates._wait_file_stable",
                   return_value=True):
            restore_template(MagicMock())
        lrp_text = (td / TEMPLATE_LRP).read_text(encoding="utf-8")
        assert "ModifiedSequence" in lrp_text

    def test_stripped_files_cleaned_up(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        with p_find, self._mock_save_ok(td), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load), \
             patch("lasx.scanning_templates._wait_file_stable",
                   return_value=True):
            restore_template(MagicMock())
        assert not (td / STRIPPED_XML).exists()
        assert not (td / STRIPPED_RGN).exists()
        assert not (td / STRIPPED_LRP).exists()

    def test_retries_on_count_mismatch(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        save_calls = [0]
        def _save_with_delayed_objects(client, name, tdir, **kwargs):
            save_calls[0] += 1
            confirm = kwargs.get("confirm_path")
            target = Path(confirm) if confirm else Path(tdir) / name
            if target.is_file():
                time.sleep(0.01)
                if save_calls[0] <= 1:
                    # First attempt: write a stripped XML (no ScanFieldData)
                    (td / TEMPLATE_XML).write_text(
                        "<Experiment><ScanFields /></Experiment>",
                        encoding="utf-8")
                    (td / TEMPLATE_RGN).write_text(SAMPLE_RGN,
                                                     encoding="utf-8")
                else:
                    # Second attempt: restore proper XML
                    (td / TEMPLATE_XML).write_text(SAMPLE_XML,
                                                     encoding="utf-8")
                    (td / TEMPLATE_RGN).write_text(SAMPLE_RGN,
                                                     encoding="utf-8")
                target.write_text(
                    target.read_text(encoding="utf-8"), encoding="utf-8")
            return {
                "success": True, "confirmed": True,
                "message": "ok", "timing": {}, "logs": [],
            }
        with p_find, \
             patch("lasx.scanning_templates.save_experiment",
                   side_effect=_save_with_delayed_objects), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load), \
             patch("lasx.scanning_templates._wait_file_stable",
                   return_value=True):
            r = restore_template(MagicMock())
        assert r is not None
        assert r["attempts"] >= 2

    def test_exhausted_attempts_returns_none(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        # Save always produces empty objects → count never matches
        def _save_empty(client, name, tdir, **kwargs):
            (td / TEMPLATE_XML).write_text(
                "<Experiment><ScanFields /></Experiment>", encoding="utf-8")
            confirm = kwargs.get("confirm_path")
            target = Path(confirm) if confirm else Path(tdir) / name
            if target.is_file():
                time.sleep(0.01)
                target.write_text(
                    target.read_text(encoding="utf-8"), encoding="utf-8")
            return {
                "success": True, "confirmed": True,
                "message": "ok", "timing": {}, "logs": [],
            }
        with p_find, \
             patch("lasx.scanning_templates.save_experiment",
                   side_effect=_save_empty), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load), \
             patch("lasx.scanning_templates._wait_file_stable",
                   return_value=True):
            r = restore_template(MagicMock())
        assert r is None

    def test_save_timeout_restores_backup(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        # Save always returns None (timeout)
        with p_find, \
             patch("lasx.scanning_templates.save_experiment",
                   return_value=None), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load), \
             patch("lasx.scanning_templates._wait_file_stable",
                   return_value=True):
            r = restore_template(MagicMock())
        assert r is None

    def test_no_templates_dir_returns_none(self):
        with patch("lasx.scanning_templates.find_scanning_templates_dir",
                   return_value=None):
            r = restore_template(MagicMock())
        assert r is None

    def test_no_stripped_lrp_skips_backup(self, tmp_path):
        td, p_find = self._setup(tmp_path)
        # Remove stripped LRP — should still work, just no LRP copy-back
        (td / STRIPPED_LRP).unlink()
        with p_find, self._mock_save_ok(td), \
             patch("lasx.scanning_templates.load_experiment",
                   side_effect=_fake_load), \
             patch("lasx.scanning_templates._wait_file_stable",
                   return_value=True):
            r = restore_template(MagicMock())
        assert r is not None
        assert r["success"] is True
