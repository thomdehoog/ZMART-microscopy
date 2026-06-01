"""Unit tests for the explicit acquire() -> save() workflow."""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import tifffile

import navigator_expert as drv
from navigator_expert.acquisition import capture
from navigator_expert.acquisition import navigator_expert_export as exporter
from navigator_expert.acquisition import save as acquisition
from shared.output_layout import (
    Naming,
    build_image_name,
    build_xml_name,
    parse_image_name,
)


@pytest.fixture
def naming() -> Naming:
    return Naming(
        acquisition_type="overview-scan",
        hash6="000001",
        g=1,
        p=3,
    )


@pytest.fixture
def fake_lasx_export(tmp_path: Path) -> dict:
    """Create one realistic flat Navigator Expert plane grid."""
    media_path = tmp_path / "media"
    experiment_dir = media_path / "experiment--demo"
    metadata_dir = experiment_dir / "metadata"
    experiment_dir.mkdir(parents=True)
    metadata_dir.mkdir()

    xml_name = "image--L0000--J08--E00--T0000.ome.xml"
    xml_path = metadata_dir / xml_name

    plane_paths = {}
    for z in range(2):
        for c in range(2):
            idx = exporter.PlaneIndex(t=0, z=z, c=c)
            image_name = (
                f"image--L0000--J08--E00--X00--Y00"
                f"--T0000--Z{z:02d}--C{c:02d}.ome.tif"
            )
            image_path = experiment_dir / image_name
            tifffile.imwrite(
                str(image_path),
                np.full((16, 16), 10 * z + c, dtype=np.uint8),
            )
            plane_paths[idx] = image_path

    xml_path.write_bytes(
        b'<?xml version="1.0"?>'
        b'<OME><Image><Pixels SizeC="2" SizeZ="2" SizeT="1"/></Image></OME>'
    )
    now = time.time()
    for image_path in plane_paths.values():
        os.utime(image_path, (now, now))
    os.utime(xml_path, (now, now))
    first_image = plane_paths[exporter.PlaneIndex(t=0, z=0, c=0)]

    return {
        "media_path": media_path,
        "relative_path": f"experiment--demo/{first_image.name}",
        "image_path": first_image,
        "plane_paths": plane_paths,
        "image_paths": [p for _idx, p in sorted(plane_paths.items())],
        "xml_path": xml_path,
    }


@pytest.fixture
def successful_acq() -> capture.AcquisitionResult:
    return capture.AcquisitionResult(
        job="HiRes",
        started_at=time.time() - 1,
        finished_at=time.time(),
        command_result={"success": True, "message": "ok"},
    )


@pytest.fixture
def patched_export(fake_lasx_export):
    """Patch LAS X-facing reads; keep real filesystem persistence."""
    healthy = {
        "path": "x",
        "corrupted": False,
        "violations": [],
        "error": None,
    }
    with patch.object(
        exporter._readers,
        "get_lasx_settings",
        return_value={
            "export": {"media_path": str(fake_lasx_export["media_path"])}
        },
    ), patch.object(
        exporter._files,
        "read_relative_path",
        return_value=fake_lasx_export["relative_path"],
    ), patch.object(
        exporter._files,
        "wait_all_stable",
        return_value={"success": True},
    ) as wait_all_stable, patch.object(
        acquisition._ome,
        "check_ome_tiff",
        return_value=healthy,
    ), patch.object(
        acquisition._ome,
        "check_ome_xml_file",
        return_value=healthy,
    ) as check_ome_xml_file:
        yield {
            **fake_lasx_export,
            "wait_all_stable": wait_all_stable,
            "check_ome_xml_file": check_ome_xml_file,
        }


class TestAcquire:
    def test_acquire_returns_save_agnostic_token(self):
        with patch.object(
            capture._commands,
            "acquire",
            return_value={"success": True, "receipt": "ok"},
        ) as command:
            result = drv.acquire("client", "HiRes")

        command.assert_called_once_with(
            "client",
            "HiRes",
            poll_interval=None,
            poll_timeout=None,
            heartbeat_interval=None,
            start_timeout=None,
            pre_check_timeout=None,
        )
        assert isinstance(result, drv.AcquisitionResult)
        assert result.job == "HiRes"
        assert result.command_result == {"success": True, "receipt": "ok"}
        assert result.started_at <= result.finished_at

    def test_acquire_raises_on_command_failure(self):
        with patch.object(
            capture._commands,
            "acquire",
            return_value={"success": False, "error": "blocked"},
        ):
            with pytest.raises(RuntimeError, match="acquire failed"):
                drv.acquire("client", "HiRes")

    def test_acquire_has_no_file_or_save_side_effects(self):
        with patch.object(
            capture._commands,
            "acquire",
            return_value={"success": True},
        ), patch.object(
            exporter._files,
            "read_relative_path",
        ) as read_relative_path, patch.object(
            acquisition,
            "_persist_export",
        ) as persist:
            drv.acquire("client", "HiRes")

        read_relative_path.assert_not_called()
        persist.assert_not_called()


class TestSave:
    def test_save_persists_image_xml_and_summary(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        output_root = tmp_path / "run_000001"

        result = drv.save(None, successful_acq, output_root, naming)

        expected_image = (
            output_root / "overview-scan" / "data" / build_image_name(naming)
        )
        expected_xml = (
            output_root / "overview-scan" / "data" / "metadata"
            / build_xml_name(naming)
        )
        assert isinstance(result, drv.SavedAcquisition)
        assert set(result.image_paths) == set(patched_export["plane_paths"])
        assert result.image_paths[drv.PlaneIndex(t=0, z=0, c=0)] == expected_image
        assert result.xml_paths == {drv.PositionIndex(t=0, v=0): expected_xml}
        assert tifffile.imread(expected_image).shape == (16, 16)
        assert all(p.is_file() for p in result.image_paths.values())
        assert expected_xml.is_file()

        summary = json.loads((output_root / "summary.json").read_text())
        assert len(summary["acquisitions"]) == 4
        rec = next(
            r for r in summary["acquisitions"]
            if r["naming"]["c"] == 0 and r["naming"]["z"] == 0
        )
        assert rec["image_path"] == (
            "overview-scan/data/" + build_image_name(naming)
        )
        assert rec["xml_path"] == (
            "overview-scan/data/metadata/" + build_xml_name(naming)
        )
        assert rec["source_exporter"] == "navigator_expert_exporter"
        assert rec["naming"]["p"] == 3

    def test_save_does_not_issue_microscope_acquire(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        with patch.object(capture._commands, "acquire") as command:
            drv.save(None, successful_acq, tmp_path / "run_000001", naming)
        command.assert_not_called()

    def test_save_plumbs_export_completion_timeout(
        self,
        successful_acq,
        tmp_path,
        naming,
    ):
        with patch.object(
            acquisition,
            "collect_navigator_expert_export",
        ) as collect:
            collect.side_effect = RuntimeError("stop after kwargs")
            with pytest.raises(RuntimeError, match="stop after kwargs"):
                drv.save(
                    None,
                    successful_acq,
                    tmp_path / "run_000001",
                    naming,
                    export_completion_timeout_s=12.0,
                    export_completion_poll_interval_s=0.25,
                )

        assert collect.call_args.kwargs["export_completion_timeout"] == 12.0
        assert (
            collect.call_args.kwargs["export_completion_poll_interval"] == 0.25
        )

    def test_navigator_export_waits_for_source_files(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        drv.save(None, successful_acq, tmp_path / "run_000001", naming)
        waited = patched_export["wait_all_stable"].call_args.args[0]
        for image_path in patched_export["image_paths"]:
            assert image_path in waited
        assert patched_export["xml_path"] in waited
        assert patched_export["check_ome_xml_file"].call_count == 1

    def test_lineage_passes_through(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        lineage = {"source_tile_rid": 1, "row": 2, "col": 3}
        output_root = tmp_path / "run_000001"
        drv.save(None, successful_acq, output_root, naming, lineage=lineage)
        summary = json.loads((output_root / "summary.json").read_text())
        assert summary["acquisitions"][0]["lineage"] == lineage

    def test_cleanup_source_removes_lasx_product(
        self,
        patched_export,
        tmp_path,
        successful_acq,
        naming,
    ):
        drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
            cleanup_source=True,
        )
        assert all(not p.is_file() for p in patched_export["image_paths"])
        assert not patched_export["xml_path"].is_file()

    def test_save_preserves_caller_owned_view_slot(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        naming = replace(naming, v=5)

        saved = drv.save(None, successful_acq, tmp_path / "run_000001", naming)

        assert saved.xml_paths == {
            drv.PositionIndex(t=0, v=5):
            tmp_path / "run_000001" / "overview-scan" / "data" / "metadata"
            / build_xml_name(replace(naming, t=0))
        }
        for idx, path in saved.image_paths.items():
            parsed = parse_image_name(path.name)
            assert parsed is not None
            assert parsed.v == 5
            assert parsed.t == idx.t
            assert parsed.z == idx.z
            assert parsed.c == idx.c

    def test_save_has_no_channel_selector(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        with pytest.raises(TypeError, match="channel"):
            drv.save(
                None,
                successful_acq,
                tmp_path / "run_000001",
                naming,
                channel=0,
            )

    def test_save_persists_flat_z_planes_separately(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        saved = drv.save(None, successful_acq, tmp_path / "run_000001", naming)
        z0 = saved.image_paths[drv.PlaneIndex(t=0, z=0, c=0)]
        z1 = saved.image_paths[drv.PlaneIndex(t=0, z=1, c=0)]
        assert z0 != z1
        assert tifffile.imread(z0).shape == (16, 16)
        assert tifffile.imread(z1).shape == (16, 16)

    def test_save_preserves_caller_owned_position_slots(
        self,
        patched_export,
        successful_acq,
        tmp_path,
    ):
        naming = Naming(
            acquisition_type="overview-scan",
            hash6="000001",
            k=7,
            m=8,
            g=9,
            p=10,
        )

        saved = drv.save(None, successful_acq, tmp_path / "run_000001", naming)

        for idx, path in saved.image_paths.items():
            parsed = parse_image_name(path.name)
            assert parsed is not None
            assert parsed.k == 7
            assert parsed.m == 8
            assert parsed.g == 9
            assert parsed.p == 10
            assert parsed.t == idx.t
            assert parsed.z == idx.z
            assert parsed.c == idx.c

    def test_missing_xml_raises(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        patched_export["xml_path"].unlink()
        with pytest.raises(RuntimeError, match="OME-XML companion not found"):
            drv.save(None, successful_acq, tmp_path / "run_000001", naming)

    def test_corrupt_ome_tiff_raises(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        with patch.object(
            acquisition._ome,
            "check_ome_tiff",
            return_value={
                "path": "x",
                "corrupted": True,
                "violations": ["bad"],
                "error": None,
            },
        ):
            with pytest.raises(RuntimeError, match="OME-TIFF validation"):
                drv.save(None, successful_acq, tmp_path / "run_000001", naming)

    def test_fix_ome_attempts_repair(
        self,
        tmp_path,
        naming,
    ):
        source_dir = tmp_path / "source"
        metadata_dir = source_dir / "metadata"
        metadata_dir.mkdir(parents=True)
        image_path = (
            source_dir
            / "image--L0000--J08--E00--X00--Y00--T0000--Z00--C00.ome.tif"
        )
        xml_path = metadata_dir / "image--L0000--J08--E00--T0000.ome.xml"
        image_path.write_bytes(b"image")
        xml_path.write_bytes(b"<xml/>")
        exported = exporter.ExportedAcquisition(
            media_path=tmp_path,
            source_dir=source_dir,
            positions=[
                exporter.ExportedPosition(
                    t=0,
                    xml_path=xml_path,
                    planes={drv.PlaneIndex(t=0, z=0, c=0): image_path},
                )
            ],
            method="test",
        )
        check_results = [
            {
                "path": "x",
                "corrupted": True,
                "violations": ["bad"],
                "error": None,
            },
            {
                "path": "x",
                "corrupted": False,
                "violations": [],
                "error": None,
            },
        ]
        with patch.object(
            acquisition._ome,
            "check_ome_tiff",
            side_effect=check_results,
        ), patch.object(
            acquisition._ome,
            "check_ome_xml_file",
            return_value={
                "path": "x",
                "corrupted": False,
                "violations": [],
                "error": None,
            },
        ), patch.object(acquisition._ome, "fix_ome_tiff") as fix_ome:
            acquisition._persist_export(
                exported,
                tmp_path / "out",
                naming,
                lineage=None,
                fix_ome=True,
                cleanup_source=False,
            )
        fix_ome.assert_called_once()
        repaired_path = fix_ome.call_args.args[0]
        assert repaired_path != image_path
        assert repaired_path.name.endswith(".tmp")

    def test_repeated_save_replaces_summary_record(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        output_root = tmp_path / "run_000001"
        drv.save(None, successful_acq, output_root, naming)
        drv.save(None, successful_acq, output_root, naming)
        summary = json.loads((output_root / "summary.json").read_text())
        assert len(summary["acquisitions"]) == 4


class TestCollectNavigatorExpertExport:
    def test_uses_mtime_fallback_when_relative_path_is_empty(
        self,
        fake_lasx_export,
        successful_acq,
    ):
        with patch.object(
            exporter._readers,
            "get_lasx_settings",
            return_value={
                "export": {"media_path": str(fake_lasx_export["media_path"])}
            },
        ), patch.object(
            exporter._files,
            "read_relative_path",
            return_value="",
        ), patch.object(
            exporter._files,
            "wait_all_stable",
            return_value={"success": True},
        ):
            exported = exporter.collect_navigator_expert_export(
                None,
                successful_acq,
                mtime_poll_timeout=0.1,
            )

        assert exported.method == "mtime"
        assert exported.image_files == fake_lasx_export["image_paths"]

    def test_relative_path_before_acquisition_falls_back_to_mtime(
        self,
        fake_lasx_export,
        successful_acq,
    ):
        old = successful_acq.started_at - 10
        for image_path in fake_lasx_export["image_paths"]:
            os.utime(image_path, (old, old))
        os.utime(fake_lasx_export["xml_path"], (time.time(), time.time()))
        with patch.object(
            exporter._readers,
            "get_lasx_settings",
            return_value={
                "export": {"media_path": str(fake_lasx_export["media_path"])}
            },
        ), patch.object(
            exporter._files,
            "read_relative_path",
            return_value=fake_lasx_export["relative_path"],
        ), patch.object(
            exporter._files,
            "wait_all_stable",
            return_value={"success": True},
        ):
            with pytest.raises(RuntimeError, match="No Navigator Expert"):
                exporter.collect_navigator_expert_export(
                    None,
                    successful_acq,
                    path_poll_timeout=0.01,
                    path_poll_interval=0.001,
                    mtime_poll_timeout=0.01,
                )

    def test_mixed_repeat_suffixes_in_one_fresh_grid_are_collected(
        self,
        fake_lasx_export,
        successful_acq,
    ):
        renamed = {}
        suffixes = {
            drv.PlaneIndex(t=0, z=0, c=0): "--003",
            drv.PlaneIndex(t=0, z=0, c=1): "--003",
            drv.PlaneIndex(t=0, z=1, c=0): "--001",
            drv.PlaneIndex(t=0, z=1, c=1): "--001",
        }
        for idx, old in fake_lasx_export["plane_paths"].items():
            new = old.with_name(old.name.replace(".ome.tif", f"{suffixes[idx]}.ome.tif"))
            old.rename(new)
            renamed[idx] = new
        fake_lasx_export["plane_paths"] = renamed
        fake_lasx_export["image_paths"] = [p for _idx, p in sorted(renamed.items())]
        fake_lasx_export["relative_path"] = (
            f"experiment--demo/{renamed[drv.PlaneIndex(t=0, z=0, c=0)].name}"
        )

        with patch.object(
            exporter._readers,
            "get_lasx_settings",
            return_value={
                "export": {"media_path": str(fake_lasx_export["media_path"])}
            },
        ), patch.object(
            exporter._files,
            "read_relative_path",
            return_value=fake_lasx_export["relative_path"],
        ), patch.object(
            exporter._files,
            "wait_all_stable",
            return_value={"success": True},
        ):
            exported = exporter.collect_navigator_expert_export(
                None,
                successful_acq,
            )

        assert exported.image_files == fake_lasx_export["image_paths"]

    def test_incomplete_fresh_grid_fails_closed(
        self,
        fake_lasx_export,
        successful_acq,
    ):
        stale = successful_acq.started_at - 10
        os.utime(
            fake_lasx_export["plane_paths"][drv.PlaneIndex(t=0, z=1, c=1)],
            (stale, stale),
        )
        with patch.object(
            exporter._readers,
            "get_lasx_settings",
            return_value={
                "export": {"media_path": str(fake_lasx_export["media_path"])}
            },
        ), patch.object(
            exporter._files,
            "read_relative_path",
            return_value=fake_lasx_export["relative_path"],
        ), patch.object(
            exporter._files,
            "wait_all_stable",
            return_value={"success": True},
        ):
            with pytest.raises(RuntimeError, match="incomplete LAS X export grid"):
                exporter.collect_navigator_expert_export(
                    None,
                    successful_acq,
                    export_completion_timeout=0.01,
                    export_completion_poll_interval=0.001,
                )

    def test_xml_declared_grid_catches_missing_whole_channel(
        self,
        fake_lasx_export,
        successful_acq,
    ):
        stale = successful_acq.started_at - 10
        for idx in (
            drv.PlaneIndex(t=0, z=0, c=1),
            drv.PlaneIndex(t=0, z=1, c=1),
        ):
            os.utime(fake_lasx_export["plane_paths"][idx], (stale, stale))
        with patch.object(
            exporter._readers,
            "get_lasx_settings",
            return_value={
                "export": {"media_path": str(fake_lasx_export["media_path"])}
            },
        ), patch.object(
            exporter._files,
            "read_relative_path",
            return_value=fake_lasx_export["relative_path"],
        ), patch.object(
            exporter._files,
            "wait_all_stable",
            return_value={"success": True},
        ):
            with pytest.raises(
                RuntimeError,
                match="incomplete LAS X export grid",
            ):
                exporter.collect_navigator_expert_export(
                    None,
                    successful_acq,
                    export_completion_timeout=0.01,
                    export_completion_poll_interval=0.001,
                )

    def test_xml_declared_sizet_catches_missing_timepoint(
        self,
        fake_lasx_export,
        successful_acq,
    ):
        fake_lasx_export["xml_path"].write_bytes(
            b'<?xml version="1.0"?>'
            b'<OME><Image><Pixels SizeC="2" SizeZ="2" SizeT="2"/></Image></OME>'
        )
        with patch.object(
            exporter._readers,
            "get_lasx_settings",
            return_value={
                "export": {"media_path": str(fake_lasx_export["media_path"])}
            },
        ), patch.object(
            exporter._files,
            "read_relative_path",
            return_value=fake_lasx_export["relative_path"],
        ), patch.object(
            exporter._files,
            "wait_all_stable",
            return_value={"success": True},
        ):
            with pytest.raises(
                RuntimeError,
                match="incomplete LAS X export timepoints",
            ):
                exporter.collect_navigator_expert_export(
                    None,
                    successful_acq,
                    export_completion_timeout=0.01,
                    export_completion_poll_interval=0.001,
                )

    def test_multiple_source_xy_groups_fail_closed(
        self,
        fake_lasx_export,
        successful_acq,
    ):
        extra = (
            fake_lasx_export["image_path"].parent
            / "image--L0000--J08--E00--X01--Y00--T0000--Z00--C00.ome.tif"
        )
        tifffile.imwrite(str(extra), np.ones((16, 16), dtype=np.uint8))
        now = time.time()
        os.utime(extra, (now, now))

        with patch.object(
            exporter._readers,
            "get_lasx_settings",
            return_value={
                "export": {"media_path": str(fake_lasx_export["media_path"])}
            },
        ), patch.object(
            exporter._files,
            "read_relative_path",
            return_value=fake_lasx_export["relative_path"],
        ), patch.object(
            exporter._files,
            "wait_all_stable",
            return_value={"success": True},
        ):
            with pytest.raises(RuntimeError, match="multiple source X/Y"):
                exporter.collect_navigator_expert_export(None, successful_acq)


class TestHelpers:
    def test_ome_ok_is_strict_about_contract_shape(self):
        assert acquisition._ome_ok(
            {"path": "x", "corrupted": False, "violations": [], "error": None}
        ) is True
        assert acquisition._ome_ok(
            {"path": "x", "corrupted": True, "violations": ["bad"], "error": None}
        ) is False
        assert acquisition._ome_ok(
            {"path": "x", "corrupted": False, "violations": [], "error": "I/O"}
        ) is False
        with pytest.raises(KeyError):
            acquisition._ome_ok({"success": True})

    def test_find_companion_xml_with_repeat_suffix(self, tmp_path):
        experiment_dir = tmp_path / "experiment--demo"
        metadata_dir = experiment_dir / "metadata"
        experiment_dir.mkdir()
        metadata_dir.mkdir()
        image_path = (
            experiment_dir
            / "image--L0000--J08--E00--X00--Y00--T0000--Z00--C00--001.ome.tif"
        )
        xml_path = metadata_dir / "image--L0000--J08--E00--T0000--001.ome.xml"
        image_path.write_bytes(b"x")
        xml_path.write_bytes(b"<xml/>")
        parsed = exporter._files.parse_lasx_filename(image_path.name)
        acq = capture.AcquisitionResult(
            job="HiRes",
            started_at=time.time() - 1,
            finished_at=time.time(),
            command_result={"success": True},
        )
        assert exporter._find_companion_xml(experiment_dir, parsed, 0, acq) == xml_path

    def test_save_atomic_cleans_tmp_on_copy_failure(self, tmp_path, monkeypatch):
        src_img = tmp_path / "src.ome.tif"
        src_xml = tmp_path / "src.ome.xml"
        src_img.write_bytes(b"image-bytes")
        src_xml.write_bytes(b"<xml/>")
        dest_img = tmp_path / "dest" / "out.ome.tiff"
        dest_xml = tmp_path / "dest" / "metadata" / "out.ome.xml"
        dest_img.parent.mkdir()
        dest_xml.parent.mkdir(parents=True)

        def failing_copy2(src, dst, *args, **kwargs):
            Path(str(dst)).write_bytes(b"partial")
            raise OSError("simulated disk full")

        monkeypatch.setattr(acquisition.shutil, "copy2", failing_copy2)

        with pytest.raises(OSError, match="simulated disk full"):
            acquisition._save_atomic(src_img, dest_img, src_xml, dest_xml)

        assert not dest_img.exists()
        assert not dest_xml.exists()
        assert list(dest_img.parent.glob("*.tmp")) == []
        assert list(dest_xml.parent.glob("*.tmp")) == []

    def test_append_summary_creates_file_and_replaces_same_image_path(self, tmp_path):
        summary = tmp_path / "summary.json"
        acquisition._append_summary_atomic(
            summary,
            {"image_path": "a/b.tif", "v": 1},
        )
        acquisition._append_summary_atomic(
            summary,
            {"image_path": "a/b.tif", "v": 2},
        )
        data = json.loads(summary.read_text())
        assert data["acquisitions"] == [{"image_path": "a/b.tif", "v": 2}]


def test_old_public_workflow_helpers_are_not_exported():
    assert not hasattr(drv, "start_run")
    assert not hasattr(drv, "acquire_and_save")
    assert not hasattr(drv, "RunHandle")
    assert not hasattr(drv, "acquire_frame")
    assert not hasattr(drv, "acquire_stack")
    assert not hasattr(drv, "acquire_single_image")
    assert not hasattr(drv, "detect_new_files")
    assert not hasattr(drv, "validate_files")
    assert not hasattr(drv, "confirm_arrival")
