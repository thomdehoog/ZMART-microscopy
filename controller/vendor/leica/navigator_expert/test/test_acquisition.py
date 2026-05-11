"""Unit tests for driver/acquisition.py.

Mocks the LAS X-facing primitives (get_lasx_settings, acquire_frame,
read_relative_path, check_ome_*) with stdlib unittest.mock. Real
filesystem operations under tmp_path verify atomic save behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from _shared.output_layout import Naming, build_image_name, build_xml_name
import navigator_expert.driver as drv
from navigator_expert.driver import acquisition


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def fake_lasx_export(tmp_path: Path) -> dict:
    """Create a fake LAS X experiment folder under tmp_path with one
    image + companion XML. Returns dict with media_path, image_path,
    xml_path so individual tests can patch get_lasx_settings + acquire_frame.
    """
    media_path = tmp_path / "media"
    experiment_dir = media_path / "experiment--demo"
    metadata_dir = experiment_dir / "metadata"
    experiment_dir.mkdir(parents=True)
    metadata_dir.mkdir()

    # LAS X export: image--L0000--J08--E00--X00--Y00--T0000--Z00--C00.ome.tif
    image_name = "image--L0000--J08--E00--X00--Y00--T0000--Z00--C00.ome.tif"
    xml_name = "image--L0000--J08--E00--T0000.ome.xml"

    image_path = experiment_dir / image_name
    xml_path = metadata_dir / xml_name

    # Real bytes; not real OME-TIFF, but check_ome_tiff is mocked below.
    image_path.write_bytes(b"\xff\xd8" + b"fake_tiff_payload" * 100)
    xml_path.write_bytes(b"<?xml version='1.0'?><OME>fake</OME>")

    return {
        "media_path": media_path,
        "image_path": image_path,
        "xml_path": xml_path,
    }


@pytest.fixture
def patched_drv(fake_lasx_export):
    """Patch the driver-facing LAS X primitives so acquisition.py can run
    end-to-end without a real microscope."""
    fake_image = np.ones((16, 16), dtype=np.uint8)
    media_path = fake_lasx_export["media_path"]
    image_path = fake_lasx_export["image_path"]

    with patch.object(
        acquisition._readers, "get_lasx_settings",
        return_value={"export": {"media_path": str(media_path)}},
    ), patch.object(
        acquisition._fc, "read_relative_path", return_value="",
    ), patch.object(
        acquisition._acquire, "acquire_frame",
        return_value=(fake_image, image_path),
    ), patch.object(
        acquisition._ome, "check_ome_tiff",
        return_value={"path": "x", "corrupted": False, "violations": [], "error": None},
    ), patch.object(
        acquisition._ome, "check_ome_xml_file",
        return_value={"path": "x", "corrupted": False, "violations": [], "error": None},
    ):
        yield fake_lasx_export


# --- start_run --------------------------------------------------------------


class TestStartRun:
    def test_creates_run_dir_under_media_path_smart(self, patched_drv):
        run = drv.start_run(client=None, experiment="test-exp")
        smart = patched_drv["media_path"] / "smart"
        assert smart.is_dir()
        assert run.layout.run_dir.parent == smart
        assert run.layout.run_dir.name.startswith("test-exp_")

    def test_writes_summary_skeleton(self, patched_drv):
        run = drv.start_run(client=None, experiment="test-exp")
        summary_path = run.layout.run_dir / "summary.json"
        assert summary_path.is_file()
        data = json.loads(summary_path.read_text())
        assert data["experiment"] == "test-exp"
        assert data["hash6"] == run.layout.hash6
        assert data["acquisitions"] == []

    def test_caches_media_path(self, patched_drv):
        run = drv.start_run(client=None, experiment="test-exp")
        assert run.media_path == patched_drv["media_path"]

    def test_raises_on_missing_settings(self):
        with patch.object(
            acquisition._readers, "get_lasx_settings", return_value=None,
        ):
            with pytest.raises(RuntimeError, match="Could not read media_path"):
                drv.start_run(client=None, experiment="exp")

    def test_raises_on_missing_export_media_path(self):
        with patch.object(
            acquisition._readers, "get_lasx_settings",
            return_value={"export": {}},
        ):
            with pytest.raises(RuntimeError, match="media_path"):
                drv.start_run(client=None, experiment="exp")

    def test_path_length_sentinel_fires(self):
        # Test _check_path_budget directly with a synthetic LayoutPlan whose
        # output_root is so deep the worst-case canonical path exceeds the
        # 250-char budget. Can't use a real tmp_path here because Windows
        # itself can't create paths that long (the test setup would fail
        # before reaching the sentinel).
        from _shared.output_layout import LayoutPlan
        fake_root = Path("Z:/" + "a" * 200)  # not real; never touched
        layout = LayoutPlan(
            output_root=fake_root, experiment="exp",
            hash6="000000", start_time_utc=0.0,
        )
        with pytest.raises(ValueError, match="Worst projected path"):
            acquisition._check_path_budget(layout)

    def test_path_length_sentinel_accepts_shallow(self):
        from _shared.output_layout import LayoutPlan
        layout = LayoutPlan(
            output_root=Path("D:/LASX/smart"), experiment="exp",
            hash6="000000", start_time_utc=0.0,
        )
        # Should not raise
        acquisition._check_path_budget(layout)

    def test_unwritable_media_path_friendly_error(self, tmp_path, monkeypatch):
        """A PermissionError from build_layout becomes an actionable
        RuntimeError telling the operator which folder is the problem.
        Spec: operator should not have to interpret raw PermissionError."""
        unwritable = tmp_path / "blocked"
        unwritable.mkdir()

        with patch.object(
            acquisition._readers, "get_lasx_settings",
            return_value={"export": {"media_path": str(unwritable)}},
        ), patch.object(
            acquisition._fc, "read_relative_path", return_value="",
        ), patch.object(
            acquisition, "build_layout",
            side_effect=PermissionError("[WinError 5] Access is denied"),
        ):
            with pytest.raises(RuntimeError, match="is not writable"):
                drv.start_run(client=None, experiment="exp")


# --- acquire_and_save: happy path -------------------------------------------


class TestAcquireAndSaveHappy:
    def test_returns_saved_acquisition(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6, g=1, p=3,
        )
        result = drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming,
        )
        assert isinstance(result, drv.SavedAcquisition)
        assert result.naming == naming
        assert result.image.shape == (16, 16)

    def test_writes_image_to_canonical_path(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6, g=1, p=3,
        )
        result = drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming,
        )
        expected_name = build_image_name(naming)
        expected_path = run.layout.data_dir("overview-scan") / expected_name
        assert result.image_path == expected_path
        assert expected_path.is_file()

    def test_writes_xml_companion(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6, g=1, p=3,
        )
        drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming,
        )
        xml_dest = (
            run.layout.metadata_dir("overview-scan") / build_xml_name(naming)
        )
        assert xml_dest.is_file()

    def test_appends_summary_record(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6, g=1, p=3,
        )
        drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming,
        )
        data = json.loads((run.layout.run_dir / "summary.json").read_text())
        assert len(data["acquisitions"]) == 1
        rec = data["acquisitions"][0]
        assert rec["naming"]["acquisition_type"] == "overview-scan"
        assert rec["naming"]["p"] == 3
        assert rec["lineage"] is None
        assert "/data/" in rec["image_path"]
        assert "/metadata/" in rec["xml_path"]

    def test_lineage_passes_through(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="target-acquisition",
            hash6=run.layout.hash6, g=1, p=5,
        )
        lineage = {"source_tile_rid": 1, "row": 2, "col": 3, "label": 17}
        drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming, lineage=lineage,
        )
        data = json.loads((run.layout.run_dir / "summary.json").read_text())
        assert data["acquisitions"][0]["lineage"] == lineage

    def test_cleanup_source_removes_lasx_files(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6, p=0,
        )
        drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming,
            cleanup_source=True,
        )
        assert not patched_drv["image_path"].is_file()
        assert not patched_drv["xml_path"].is_file()

    def test_cleanup_source_false_leaves_lasx_files(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6, p=0,
        )
        drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming,
        )
        assert patched_drv["image_path"].is_file()
        assert patched_drv["xml_path"].is_file()


# --- acquire_and_save: failure modes ----------------------------------------


class TestAcquireAndSaveFailure:
    def test_missing_xml_raises(self, patched_drv):
        # Delete the XML before acquire_and_save runs.
        patched_drv["xml_path"].unlink()
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6,
        )
        with pytest.raises(RuntimeError, match="OME-XML companion not found"):
            drv.acquire_and_save(
                client=None, run=run, job="HiRes", naming=naming,
            )

    def test_corrupt_ome_tiff_raises(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6,
        )
        with patch.object(
            acquisition._ome, "check_ome_tiff",
            return_value={"path": "x", "corrupted": True,
                          "violations": ["bad"], "error": None},
        ):
            with pytest.raises(RuntimeError, match="OME-TIFF validation"):
                drv.acquire_and_save(
                    client=None, run=run, job="HiRes", naming=naming,
                )

    def test_ome_ok_strict_against_malformed_dict(self):
        """_ome_ok uses strict key access on the documented contract:
        missing 'corrupted' or 'error' must KeyError, not silently pass.

        This pins the lesson learned from the original validation bug —
        the wrong mock shape {"success": True} passed silently because
        the predicate used .get(). Strict access fails loud on the same
        malformed input, so future drift is caught immediately."""
        # Real shape: healthy
        assert acquisition._ome_ok(
            {"path": "x", "corrupted": False, "violations": [], "error": None}
        ) is True
        # Real shape: corrupted
        assert acquisition._ome_ok(
            {"path": "x", "corrupted": True, "violations": ["bad"], "error": None}
        ) is False
        # Real shape: read error
        assert acquisition._ome_ok(
            {"path": "x", "corrupted": False, "violations": [], "error": "I/O"}
        ) is False
        # Fictional shape (the old broken mock) — must fail loud
        with pytest.raises(KeyError):
            acquisition._ome_ok({"success": True})
        # Empty dict — same loud failure
        with pytest.raises(KeyError):
            acquisition._ome_ok({})

    def test_ome_read_error_raises(self, patched_drv):
        """check_ome_tiff returns error=<str> when the file can't be read;
        the driver must treat this as failure too (not just corrupted=True)."""
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6,
        )
        with patch.object(
            acquisition._ome, "check_ome_tiff",
            return_value={"path": "x", "corrupted": False,
                          "violations": [], "error": "I/O error"},
        ):
            with pytest.raises(RuntimeError, match="OME-TIFF validation"):
                drv.acquire_and_save(
                    client=None, run=run, job="HiRes", naming=naming,
                )

    def test_corrupt_ome_xml_raises(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6,
        )
        with patch.object(
            acquisition._ome, "check_ome_xml_file",
            return_value={"path": "x", "corrupted": True,
                          "violations": ["bad"], "error": None},
        ):
            with pytest.raises(RuntimeError, match="OME-XML validation"):
                drv.acquire_and_save(
                    client=None, run=run, job="HiRes", naming=naming,
                )

    def test_fix_ome_attempts_repair(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6,
        )
        # First check fails, after fix succeeds.
        check_results = [
            {"path": "x", "corrupted": True, "violations": ["bad"], "error": None},
            {"path": "x", "corrupted": False, "violations": [], "error": None},
        ]
        with patch.object(
            acquisition._ome, "check_ome_tiff",
            side_effect=check_results,
        ), patch.object(
            acquisition._ome, "fix_ome_tiff",
        ) as fix_call:
            drv.acquire_and_save(
                client=None, run=run, job="HiRes", naming=naming,
                fix_ome=True,
            )
            fix_call.assert_called_once()


# --- _save_atomic: 6-step contract ------------------------------------------


class TestSaveAtomic:
    def test_happy_path(self, tmp_path):
        src_img = tmp_path / "src_image.ome.tif"
        src_xml = tmp_path / "src_meta.ome.xml"
        src_img.write_bytes(b"image-bytes")
        src_xml.write_bytes(b"<xml/>")

        dest_img = tmp_path / "dest" / "out.ome.tiff"
        dest_xml = tmp_path / "dest" / "metadata" / "out.ome.xml"
        dest_img.parent.mkdir()
        dest_xml.parent.mkdir(parents=True)

        acquisition._save_atomic(src_img, dest_img, src_xml, dest_xml)

        assert dest_img.read_bytes() == b"image-bytes"
        assert dest_xml.read_bytes() == b"<xml/>"
        # No leftover .tmp files
        assert list(dest_img.parent.glob("*.tmp")) == []
        assert list(dest_xml.parent.glob("*.tmp")) == []

    def test_image_copy_failure_leaves_no_temps(self, tmp_path):
        src_img = tmp_path / "does_not_exist.ome.tif"  # missing
        src_xml = tmp_path / "src.ome.xml"
        src_xml.write_bytes(b"<xml/>")

        dest_img = tmp_path / "dest" / "out.ome.tiff"
        dest_xml = tmp_path / "dest" / "out.ome.xml"
        dest_img.parent.mkdir()

        with pytest.raises(FileNotFoundError):
            acquisition._save_atomic(src_img, dest_img, src_xml, dest_xml)

        assert not dest_img.exists()
        assert not dest_xml.exists()
        assert list(dest_img.parent.glob("*.tmp")) == []

    def test_xml_copy_failure_unlinks_image_tmp(self, tmp_path):
        src_img = tmp_path / "src.ome.tif"
        src_img.write_bytes(b"image-bytes")
        src_xml = tmp_path / "does_not_exist.ome.xml"

        dest_img = tmp_path / "dest" / "out.ome.tiff"
        dest_xml = tmp_path / "dest" / "out.ome.xml"
        dest_img.parent.mkdir()

        with pytest.raises(FileNotFoundError):
            acquisition._save_atomic(src_img, dest_img, src_xml, dest_xml)

        # Neither final dest nor .tmp should exist
        assert not dest_img.exists()
        assert not dest_xml.exists()
        assert list(dest_img.parent.glob("*.tmp")) == []

    def test_size_mismatch_raises_and_cleans_up(self, tmp_path, monkeypatch):
        """If copy2 produces a truncated .tmp (e.g. partial network copy),
        the size check catches it and the .tmp is removed."""
        src_img = tmp_path / "src.ome.tif"
        src_xml = tmp_path / "src.ome.xml"
        src_img.write_bytes(b"original-image-bytes-50-bytes-long-pad-pad-pad-pa")
        src_xml.write_bytes(b"<xml/>")

        dest_img = tmp_path / "dest" / "out.ome.tiff"
        dest_xml = tmp_path / "dest" / "out.ome.xml"
        dest_img.parent.mkdir()

        # Make copy2 produce a truncated copy for the image (smaller than src).
        def truncating_copy2(src, dst, *args, **kwargs):
            data = Path(str(src)).read_bytes()
            Path(str(dst)).write_bytes(data[:5])  # truncate to 5 bytes
            return dst

        monkeypatch.setattr(acquisition.shutil, "copy2", truncating_copy2)

        with pytest.raises(RuntimeError, match="size mismatch"):
            acquisition._save_atomic(src_img, dest_img, src_xml, dest_xml)

        assert not dest_img.exists()
        assert not dest_xml.exists()
        assert list(dest_img.parent.glob("*.tmp")) == []

    def test_partial_copy_mid_write_leaves_no_temps(self, tmp_path, monkeypatch):
        """If copy2 writes some bytes then raises (disk full, network blip),
        the partial .tmp must be unlinked even though copy2 raised."""
        src_img = tmp_path / "src.ome.tif"
        src_xml = tmp_path / "src.ome.xml"
        src_img.write_bytes(b"image-bytes")
        src_xml.write_bytes(b"<xml/>")

        dest_img = tmp_path / "dest" / "out.ome.tiff"
        dest_xml = tmp_path / "dest" / "out.ome.xml"
        dest_img.parent.mkdir()

        def failing_copy2(src, dst, *args, **kwargs):
            # Simulate partial write before failure
            Path(str(dst)).write_bytes(b"partial")
            raise OSError("simulated disk full mid-copy")

        monkeypatch.setattr(acquisition.shutil, "copy2", failing_copy2)

        with pytest.raises(OSError, match="simulated disk full"):
            acquisition._save_atomic(src_img, dest_img, src_xml, dest_xml)

        # Partial .tmp must be cleaned up despite copy2 raising before
        # any cleanup bookkeeping would have run.
        assert list(dest_img.parent.glob("*.tmp")) == []
        assert not dest_img.exists()
        assert not dest_xml.exists()


# --- _find_companion_xml ----------------------------------------------------


class TestFindCompanionXml:
    def test_finds_matching_xml(self, fake_lasx_export):
        found = acquisition._find_companion_xml(fake_lasx_export["image_path"])
        assert found == fake_lasx_export["xml_path"]

    def test_returns_none_when_no_metadata_dir(self, tmp_path):
        image = tmp_path / "image--L0000--J08--E00--X00--Y00--T0000--Z00--C00.ome.tif"
        image.write_bytes(b"x")
        assert acquisition._find_companion_xml(image) is None

    def test_returns_none_when_xml_missing(self, fake_lasx_export):
        fake_lasx_export["xml_path"].unlink()
        assert acquisition._find_companion_xml(fake_lasx_export["image_path"]) is None

    def test_returns_none_for_non_lasx_filename(self, tmp_path):
        image = tmp_path / "random.ome.tif"
        image.write_bytes(b"x")
        (tmp_path / "metadata").mkdir()
        assert acquisition._find_companion_xml(image) is None

    def test_finds_xml_with_repeat_suffix(self, tmp_path):
        """Repeat-acquisition exports have a --NNN suffix on both image
        and XML; _find_companion_xml must preserve it when reconstructing
        the XML name."""
        experiment_dir = tmp_path / "experiment--demo"
        metadata_dir = experiment_dir / "metadata"
        experiment_dir.mkdir()
        metadata_dir.mkdir()
        image_name = "image--L0000--J08--E00--X00--Y00--T0000--Z00--C00--001.ome.tif"
        xml_name = "image--L0000--J08--E00--T0000--001.ome.xml"
        image_path = experiment_dir / image_name
        xml_path = metadata_dir / xml_name
        image_path.write_bytes(b"x")
        xml_path.write_bytes(b"<xml/>")
        assert acquisition._find_companion_xml(image_path) == xml_path


# --- _refuse_path_reuse -----------------------------------------------------


class TestRefusePathReuse:
    def test_refuses_when_image_dest_exists(self, patched_drv):
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6, p=0,
        )
        # First call succeeds and creates files on disk + summary record.
        drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming,
        )
        # Second call with identical naming must refuse.
        with pytest.raises(RuntimeError, match="Refusing to reuse canonical path"):
            drv.acquire_and_save(
                client=None, run=run, job="HiRes", naming=naming,
            )

    def test_error_message_warns_against_delete_only(self, patched_drv):
        """Operator UX: error must say deleting the file alone won't help
        because the summary.json record stays. Prevents dead-end retry."""
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6, p=0,
        )
        drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming,
        )
        with pytest.raises(RuntimeError) as exc_info:
            drv.acquire_and_save(
                client=None, run=run, job="HiRes", naming=naming,
            )
        assert "deleting the file alone" in str(exc_info.value).lower() \
            or "deleting the file alone" in str(exc_info.value)

    def test_refuses_when_summary_records_path_but_file_deleted(self, patched_drv):
        """Even if operator deletes the canonical file, the original
        summary.json record remains. Refusing here catches the
        delete-then-retry footgun."""
        run = drv.start_run(client=None, experiment="exp")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6=run.layout.hash6, p=0,
        )
        result = drv.acquire_and_save(
            client=None, run=run, job="HiRes", naming=naming,
        )
        # Operator deletes the canonical files (simulating delete-then-retry).
        result.image_path.unlink()
        xml_dest = run.layout.metadata_dir("overview-scan") / build_xml_name(naming)
        xml_dest.unlink()
        # Files gone, but summary still records the canonical path.
        with pytest.raises(RuntimeError, match="already recorded in summary.json"):
            drv.acquire_and_save(
                client=None, run=run, job="HiRes", naming=naming,
            )


# --- _append_summary_atomic -------------------------------------------------


class TestAppendSummaryAtomic:
    def test_appends_record(self, tmp_path):
        summary = tmp_path / "summary.json"
        summary.write_text(json.dumps({"experiment": "x", "acquisitions": []}))
        acquisition._append_summary_atomic(summary, {"naming": {"p": 0}})
        data = json.loads(summary.read_text())
        assert len(data["acquisitions"]) == 1
        assert data["acquisitions"][0]["naming"]["p"] == 0

    def test_preserves_existing_records(self, tmp_path):
        summary = tmp_path / "summary.json"
        summary.write_text(json.dumps({
            "experiment": "x",
            "acquisitions": [{"naming": {"p": 0}}],
        }))
        acquisition._append_summary_atomic(summary, {"naming": {"p": 1}})
        data = json.loads(summary.read_text())
        assert [r["naming"]["p"] for r in data["acquisitions"]] == [0, 1]

    def test_raises_when_summary_missing(self, tmp_path):
        summary = tmp_path / "summary.json"  # does not exist
        with pytest.raises(RuntimeError, match="summary.json missing"):
            acquisition._append_summary_atomic(summary, {})

    def test_no_leftover_tmp(self, tmp_path):
        summary = tmp_path / "summary.json"
        summary.write_text(json.dumps({"acquisitions": []}))
        acquisition._append_summary_atomic(summary, {"r": 1})
        assert list(tmp_path.glob("*.tmp")) == []
