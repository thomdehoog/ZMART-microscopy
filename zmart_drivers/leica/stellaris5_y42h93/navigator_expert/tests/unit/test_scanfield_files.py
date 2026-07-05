"""Unit tests for scan-field file I/O (``scanfields/files.py``).

Covers the offline-testable surface: ScanningTemplates discovery via
``%APPDATA%``, template state detection from files on disk, the
mtime-bump + stable-size confirm logic of ``save_experiment``, the
receipt-retry ladder of ``load_experiment``, and the fail-closed
contract of ``save_and_read_lrp`` (a failed save must never hand the
caller a stale on-disk parse).

All file I/O is real (tmp_path); LAS X is replaced by a minimal fake
client whose receipt callback optionally performs the on-disk write
that LAS X would do.
"""

from __future__ import annotations

import os
import shutil
from types import SimpleNamespace

import pytest
from limits_fixtures import install_permissive_limits
from navigator_expert.scanfields import files
from navigator_expert.utils import RECEIPT_TIMEOUT

# Content with no operator objects: no ScanFieldData in the XML, empty
# Items/FocusMap in the RGN.
_EMPTY_XML = "<Root><ScanFields /></Root>"
_EMPTY_RGN = (
    "<StageOverviewRegions><Regions><ShapeList><Items />"
    "</ShapeList></Regions><FocusMap /></StageOverviewRegions>"
)


def _install_bundle(source_dir, templates_dir):
    """Copy one source XML/RGN/LRP bundle to the driver's canonical names."""
    source_xml = next(source_dir.glob("*.xml"))
    base = source_xml.stem
    for suffix, target_name in (
        (".xml", files.TEMPLATE_XML),
        (".rgn", files.TEMPLATE_RGN),
        (".lrp", files.TEMPLATE_LRP),
    ):
        shutil.copy2(source_dir / f"{base}{suffix}", templates_dir / target_name)


class _SaveClient:
    """Fake CAM client: scripted receipt results + optional on-disk write.

    ``receipts`` is consumed one entry per ``UpdateAwaitReceipt`` call;
    an ``Exception`` entry is raised instead of returned. ``on_receipt``
    runs after each successful receipt — that is where the fake "LAS X"
    writes the watched file.
    """

    def __init__(self, receipts=(True,), on_receipt=None):
        self._receipts = list(receipts)
        self._on_receipt = on_receipt
        install_permissive_limits(self)
        self.receipt_calls = 0
        self.receipt_timeouts = []
        self.PyApiSaveExperiment = SimpleNamespace(
            Model=SimpleNamespace(ExperimentName=None),
            UpdateAwaitReceipt=self._update,
        )

    def _update(self, timeout):
        self.receipt_calls += 1
        self.receipt_timeouts.append(timeout)
        result = self._receipts.pop(0) if self._receipts else True
        if isinstance(result, Exception):
            raise result
        if result and self._on_receipt is not None:
            self._on_receipt()
        return result


class _LoadClient:
    """Fake CAM client for ``load_experiment`` (receipt only)."""

    def __init__(self, receipts=(True,)):
        install_permissive_limits(self)
        self._receipts = list(receipts)
        self.receipt_calls = 0
        self.PyApiLoadExperiment = SimpleNamespace(
            Model=SimpleNamespace(ExperimentName=None),
            UpdateAwaitReceipt=self._update,
        )

    def _update(self, _timeout):
        self.receipt_calls += 1
        result = self._receipts.pop(0) if self._receipts else True
        if isinstance(result, Exception):
            raise result
        return result


# =============================================================================
# find_scanning_templates_dir
# =============================================================================


class TestFindScanningTemplatesDir:
    def _make_profile(self, appdata, user="User_A", with_templates=True):
        base = appdata / "Leica Microsystems" / "LAS X" / "MatrixScreener6"
        user_dir = base / user
        target = user_dir / "ScanningTemplates" if with_templates else user_dir
        target.mkdir(parents=True)
        return user_dir / "ScanningTemplates"

    def test_no_appdata_env_returns_none(self, monkeypatch):
        monkeypatch.delenv("APPDATA", raising=False)
        assert files.find_scanning_templates_dir() is None

    def test_missing_matrixscreener_dir_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert files.find_scanning_templates_dir() is None

    def test_no_user_dirs_returns_none(self, tmp_path, monkeypatch):
        (tmp_path / "Leica Microsystems" / "LAS X" / "MatrixScreener6").mkdir(parents=True)
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert files.find_scanning_templates_dir() is None

    def test_single_user_returns_templates_dir(self, tmp_path, monkeypatch):
        expected = self._make_profile(tmp_path)
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert files.find_scanning_templates_dir() == expected

    def test_single_user_without_templates_dir_returns_none(self, tmp_path, monkeypatch):
        self._make_profile(tmp_path, with_templates=False)
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert files.find_scanning_templates_dir() is None

    def test_multiple_user_profiles_refuses_to_guess(self, tmp_path, monkeypatch):
        # Guessing alphabetically could edit another user's templates.
        self._make_profile(tmp_path, user="User_A")
        self._make_profile(tmp_path, user="User_B")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert files.find_scanning_templates_dir() is None


# =============================================================================
# get_template_state / _count_objects
# =============================================================================


class TestGetTemplateState:
    def _write_empty_canonical(self, templates_dir):
        (templates_dir / files.TEMPLATE_XML).write_text(_EMPTY_XML, encoding="utf-8")
        (templates_dir / files.TEMPLATE_RGN).write_text(_EMPTY_RGN, encoding="utf-8")

    def test_no_templates_dir_found_is_fresh(self, monkeypatch):
        monkeypatch.setattr(files, "find_scanning_templates_dir", lambda: None)
        assert files.get_template_state() == "fresh"

    def test_empty_dir_is_fresh(self, tmp_path):
        assert files.get_template_state(tmp_path) == "fresh"

    def test_canonical_with_objects_and_no_sidecar_is_unstripped(self, general_workflow_data):
        _install_bundle(general_workflow_data, general_workflow_data)
        assert files.get_template_state(general_workflow_data) == "unstripped"

    def test_canonical_without_objects_is_stripped(self, tmp_path):
        self._write_empty_canonical(tmp_path)
        assert files.get_template_state(tmp_path) == "stripped"

    def test_newer_sidecar_wins_over_object_bearing_canonical(self, general_workflow_data):
        _install_bundle(general_workflow_data, general_workflow_data)
        xml_path = general_workflow_data / files.TEMPLATE_XML
        sidecar = general_workflow_data / files.STRIPPED_XML
        sidecar.write_text(_EMPTY_XML, encoding="utf-8")
        os.utime(xml_path, (1000, 1000))
        os.utime(sidecar, (2000, 2000))
        assert files.get_template_state(general_workflow_data) == "stripped"

    def test_older_sidecar_defers_to_canonical_objects(self, general_workflow_data):
        _install_bundle(general_workflow_data, general_workflow_data)
        xml_path = general_workflow_data / files.TEMPLATE_XML
        sidecar = general_workflow_data / files.STRIPPED_XML
        sidecar.write_text(_EMPTY_XML, encoding="utf-8")
        os.utime(xml_path, (2000, 2000))
        os.utime(sidecar, (1000, 1000))
        assert files.get_template_state(general_workflow_data) == "unstripped"

    def test_corrupt_rgn_is_unreadable_not_stripped(self, tmp_path):
        # A corrupt template must not masquerade as "stripped" and invite
        # a workflow to proceed as if stripping succeeded.
        (tmp_path / files.TEMPLATE_XML).write_text(_EMPTY_XML, encoding="utf-8")
        (tmp_path / files.TEMPLATE_RGN).write_text("not xml at all <", encoding="utf-8")
        assert files.get_template_state(tmp_path) == "unreadable"

    def test_missing_rgn_is_unreadable(self, tmp_path):
        (tmp_path / files.TEMPLATE_XML).write_text(_EMPTY_XML, encoding="utf-8")
        assert files.get_template_state(tmp_path) == "unreadable"

    def test_count_objects_unreadable_counts_zero(self, tmp_path):
        counts = files._count_objects(
            tmp_path / "missing.xml",
            tmp_path / "missing.rgn",
        )
        assert counts == (0, 0, 0)


# =============================================================================
# save_experiment
# =============================================================================


class TestSaveExperiment:
    def test_confirms_on_mtime_bump_and_stable_size(self, tmp_path):
        watch = tmp_path / files.TEMPLATE_XML
        watch.write_text("<old />", encoding="utf-8")
        os.utime(watch, (1000, 1000))

        def deliver():
            watch.write_text("<new content />", encoding="utf-8")
            os.utime(watch, (2000, 2000))

        client = _SaveClient(on_receipt=deliver)
        result = files.save_experiment(
            client, files.TEMPLATE_XML, tmp_path, timeout=2, poll_interval=0.01
        )

        assert result is not None
        assert result["success"] is True
        assert result["confirmed"] is True
        assert result["message"] == f"SaveExperiment '{files.TEMPLATE_XML}'"
        assert client.PyApiSaveExperiment.Model.ExperimentName == files.TEMPLATE_XML
        assert client.receipt_timeouts == [RECEIPT_TIMEOUT]

    def test_confirms_creation_of_previously_missing_file(self, tmp_path):
        watch = tmp_path / files.TEMPLATE_XML

        def deliver():
            watch.write_text("<created />", encoding="utf-8")
            os.utime(watch, (2000, 2000))

        client = _SaveClient(on_receipt=deliver)
        result = files.save_experiment(
            client, files.TEMPLATE_XML, tmp_path, timeout=2, poll_interval=0.01
        )
        assert result is not None and result["confirmed"] is True

    def test_watches_explicit_confirm_path_not_the_named_file(self, tmp_path):
        # Callers watch the RGN while saving the XML: only the confirm_path
        # write may confirm the save.
        rgn = tmp_path / files.TEMPLATE_RGN
        rgn.write_text("<old />", encoding="utf-8")
        os.utime(rgn, (1000, 1000))

        def deliver():
            rgn.write_text("<new />", encoding="utf-8")
            os.utime(rgn, (2000, 2000))

        client = _SaveClient(on_receipt=deliver)
        result = files.save_experiment(
            client,
            files.TEMPLATE_XML,
            tmp_path,
            timeout=2,
            poll_interval=0.01,
            confirm_path=rgn,
        )
        assert result is not None and result["confirmed"] is True
        # The named XML was never written; only the confirm_path was polled.
        assert not (tmp_path / files.TEMPLATE_XML).exists()

    def test_unchanged_file_times_out_to_none(self, tmp_path):
        watch = tmp_path / files.TEMPLATE_XML
        watch.write_text("<stale />", encoding="utf-8")
        os.utime(watch, (1000, 1000))
        client = _SaveClient()  # receipt ok, but nothing ever writes the file
        result = files.save_experiment(
            client, files.TEMPLATE_XML, tmp_path, timeout=0.05, poll_interval=0.01
        )
        assert result is None

    def test_receipt_retry_once_then_success(self, tmp_path):
        watch = tmp_path / files.TEMPLATE_XML

        def deliver():
            watch.write_text("<created />", encoding="utf-8")
            os.utime(watch, (2000, 2000))

        client = _SaveClient(receipts=(False, True), on_receipt=deliver)
        result = files.save_experiment(
            client, files.TEMPLATE_XML, tmp_path, timeout=2, poll_interval=0.01
        )
        assert result is not None and result["success"] is True
        assert client.receipt_calls == 2

    def test_receipt_fails_twice_returns_none(self, tmp_path):
        client = _SaveClient(receipts=(False, False))
        result = files.save_experiment(
            client, files.TEMPLATE_XML, tmp_path, timeout=1, poll_interval=0.01
        )
        assert result is None
        assert client.receipt_calls == 2

    def test_client_exception_returns_none(self, tmp_path):
        client = _SaveClient(receipts=(RuntimeError("COM fault"),))
        result = files.save_experiment(
            client, files.TEMPLATE_XML, tmp_path, timeout=1, poll_interval=0.01
        )
        assert result is None


# =============================================================================
# load_experiment
# =============================================================================


class TestLoadExperiment:
    def test_success_is_receipt_only_never_confirmed(self):
        client = _LoadClient()
        result = files.load_experiment(client, files.TEMPLATE_XML)
        assert result is not None
        assert result["success"] is True
        assert result["confirmed"] is False  # no on-disk confirmation exists
        assert result["message"] == f"LoadExperiment '{files.TEMPLATE_XML}'"
        assert client.PyApiLoadExperiment.Model.ExperimentName == files.TEMPLATE_XML

    def test_receipt_retry_once_then_success(self):
        client = _LoadClient(receipts=(False, True))
        result = files.load_experiment(client, files.TEMPLATE_XML)
        assert result is not None and result["success"] is True
        assert client.receipt_calls == 2

    def test_receipt_fails_twice_returns_none(self):
        client = _LoadClient(receipts=(False, False))
        assert files.load_experiment(client, files.TEMPLATE_XML) is None
        assert client.receipt_calls == 2

    def test_client_exception_returns_none(self):
        client = _LoadClient(receipts=(RuntimeError("COM fault"),))
        assert files.load_experiment(client, files.TEMPLATE_XML) is None


# =============================================================================
# save_and_read_lrp
# =============================================================================


class TestSaveAndReadLrp:
    @pytest.fixture
    def lrp_dir(self, general_workflow_data):
        _install_bundle(general_workflow_data, general_workflow_data)
        return general_workflow_data

    def test_no_templates_dir_returns_none(self, monkeypatch):
        monkeypatch.setattr(files, "find_scanning_templates_dir", lambda: None)
        assert files.save_and_read_lrp(object()) is None

    def test_save_success_returns_parsed_lrp(self, lrp_dir, monkeypatch):
        monkeypatch.setattr(files, "find_scanning_templates_dir", lambda: lrp_dir)
        monkeypatch.setattr(files, "save_experiment", lambda *a, **k: {"success": True})
        parsed = files.save_and_read_lrp(object(), timeout=0.1)
        assert parsed is not None
        assert {"AF Job", "Overview", "HiRes"} <= set(parsed["jobs"])

    def test_failed_save_never_returns_stale_parse(self, lrp_dir, monkeypatch):
        # The on-disk LRP is perfectly parseable, but it predates the failed
        # save: returning it would claim stale hardware settings are current.
        monkeypatch.setattr(files, "find_scanning_templates_dir", lambda: lrp_dir)
        monkeypatch.setattr(files, "save_experiment", lambda *a, **k: None)
        assert files.save_and_read_lrp(object(), timeout=0.1) is None

    def test_unparseable_lrp_returns_none(self, lrp_dir, monkeypatch):
        monkeypatch.setattr(files, "find_scanning_templates_dir", lambda: lrp_dir)
        monkeypatch.setattr(files, "save_experiment", lambda *a, **k: {"success": True})
        (lrp_dir / files.TEMPLATE_LRP).write_text("definitely not xml <", encoding="utf-8")
        assert files.save_and_read_lrp(object(), timeout=0.1) is None
