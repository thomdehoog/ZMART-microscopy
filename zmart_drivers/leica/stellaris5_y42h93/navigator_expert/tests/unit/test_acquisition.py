"""Unit tests for the explicit acquire() -> save() workflow."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import navigator_expert as drv
import numpy as np
import pytest
import tifffile
from navigator_expert.acquisition import capture, materialize, ome_canonical
from navigator_expert.acquisition import save as acquisition
from navigator_expert.acquisition.product import (
    ExportedAcquisition,
    ExportedPosition,
)

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


def _metadata() -> drv.AcquisitionMetadata:
    return drv.AcquisitionMetadata(
        size_x=16,
        size_y=16,
        size_t=1,
        size_z=1,
        size_c=1,
        pixel_type="uint8",
        physical_size_x_um=1.0,
        physical_size_y_um=1.0,
        channels=(drv.ChannelMetadata(index=0, name="C0"),),
    )


def _grid_metadata() -> drv.AcquisitionMetadata:
    return drv.AcquisitionMetadata(
        size_x=16,
        size_y=16,
        size_t=1,
        size_z=2,
        size_c=2,
        pixel_type="uint8",
        physical_size_x_um=1.0,
        physical_size_y_um=1.0,
        channels=(
            drv.ChannelMetadata(index=0, name="C0"),
            drv.ChannelMetadata(index=1, name="C1"),
        ),
    )


def _job_settings(
    *,
    pixel_size: str = "2.27 um x 2.28 um",
    stack: dict | None = None,
) -> dict:
    return {
        "zoom": {},
        "scanSpeed": {},
        "activeSettings": [],
        "scanMode": "xyz" if stack is not None else "xy",
        "imageSize": "1160 um x 1160 um",
        "pixelSize": pixel_size,
        "format": "512 x 512",
        "xyStage": {},
        "stack": stack,
    }


@pytest.fixture
def fake_export(tmp_path: Path) -> dict:
    """One realistic flat plane grid mapped to a writer-agnostic product."""
    source_root = tmp_path / "media"
    source_dir = source_root / "experiment--demo"
    metadata_dir = source_dir / "metadata"
    source_dir.mkdir(parents=True)
    metadata_dir.mkdir()

    xml_path = metadata_dir / "source.ome.xml"
    xml_path.write_bytes(b"<OME/>")

    plane_paths = {}
    for z in range(2):
        for c in range(2):
            idx = drv.PlaneIndex(t=0, z=z, c=c)
            image_path = source_dir / f"image--Z{z:02d}--C{c:02d}.ome.tif"
            tifffile.imwrite(
                str(image_path),
                np.full((16, 16), 10 * z + c, dtype=np.uint8),
            )
            plane_paths[idx] = image_path

    exported = ExportedAcquisition(
        source_root=source_root,
        source_dir=source_dir,
        positions=[
            ExportedPosition(
                t=0,
                planes={idx: drv.PlaneSource(path=p) for idx, p in plane_paths.items()},
            )
        ],
        metadata=_grid_metadata(),
        method="test",
        source_exporter="lasx_native_autosave",
        vendor_metadata_sources=(
            drv.VendorMetadataSource(name="source.ome.xml", path=xml_path),
        ),
    )

    return {
        "source_root": source_root,
        "image_path": plane_paths[drv.PlaneIndex(t=0, z=0, c=0)],
        "plane_paths": plane_paths,
        "image_paths": [p for _idx, p in sorted(plane_paths.items())],
        "xml_path": xml_path,
        "exported": exported,
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
def patched_export(fake_export, monkeypatch):
    """Mock the LAS X collector; keep real filesystem persistence."""
    healthy = {
        "path": "x",
        "corrupted": False,
        "violations": [],
        "error": None,
    }
    collect = Mock(return_value=fake_export["exported"])
    monkeypatch.setattr(acquisition, "collect_lasx_native_autosave", collect)
    with (
        patch.object(
            materialize._ome,
            "check_ome_tiff",
            return_value=healthy,
        ),
        patch.object(
            materialize._ome,
            "check_ome_xml_file",
            return_value=healthy,
        ),
    ):
        yield {
            **fake_export,
            "collect": collect,
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
        with (
            patch.object(
                capture._commands,
                "acquire",
                return_value={"success": True},
            ),
            patch.object(
                acquisition._files,
                "read_relative_path",
            ) as read_relative_path,
            patch.object(
                acquisition,
                "_persist_export",
            ) as persist,
        ):
            drv.acquire("client", "HiRes")

        read_relative_path.assert_not_called()
        persist.assert_not_called()


class TestCanonicalPhysicalMetadataAuthority:
    def test_job_settings_override_vendor_physical_sizes(self):
        metadata = replace(
            _metadata(),
            physical_size_x_um=9.0,
            physical_size_y_um=9.0,
            physical_size_z_um=1.606305,
        )
        settings = _job_settings(
            stack={"begin": -0.0, "end": 4.82, "sections": 3},
        )

        with patch.object(
            ome_canonical._readers,
            "get_job_settings",
            return_value=settings,
        ) as read_settings:
            out = ome_canonical.metadata_with_job_physical_sizes(
                metadata,
                "client",
                "Overview",
            )

        assert read_settings.call_args.kwargs["mode"] == "api"
        assert out.physical_size_x_um == pytest.approx(2.27)
        assert out.physical_size_y_um == pytest.approx(2.28)
        assert out.physical_size_z_um == pytest.approx(2.41)

    def test_z_spacing_uses_raw_stack_when_normalized_stack_is_partial(self):
        metadata = replace(_metadata(), physical_size_z_um=1.0)
        settings = _job_settings(
            stack={"begin": 95.0, "end": 105.0, "sections": 3},
        )

        with (
            patch.object(
                ome_canonical._readers,
                "get_job_settings",
                return_value=settings,
            ),
            patch.object(
                ome_canonical._core_settings,
                "make_changeable_copy",
                return_value={"stack": {"begin": 95.0, "end": None, "sections": None}},
            ),
        ):
            out = ome_canonical.metadata_with_job_physical_sizes(
                metadata,
                "client",
                "Overview",
            )

        assert out.physical_size_z_um == pytest.approx(5.0)

    def test_single_section_stack_overrides_vendor_z_to_none(self):
        metadata = replace(_metadata(), physical_size_z_um=1.0)
        settings = _job_settings(
            stack={"begin": 10.0, "end": 10.0, "sections": 1},
        )

        with patch.object(
            ome_canonical._readers,
            "get_job_settings",
            return_value=settings,
        ):
            out = ome_canonical.metadata_with_job_physical_sizes(
                metadata,
                "client",
                "Overview",
            )

        assert out.physical_size_z_um is None

    def test_job_settings_read_timeout_falls_back_to_vendor_metadata(self):
        metadata = replace(
            _metadata(),
            physical_size_x_um=9.0,
            physical_size_y_um=9.0,
            physical_size_z_um=9.0,
        )

        def _slow_settings(*_args, **_kwargs):
            time.sleep(0.2)
            return _job_settings(
                stack={"begin": 0.0, "end": 4.0, "sections": 3},
            )

        with patch.object(
            ome_canonical._readers,
            "get_job_settings",
            side_effect=_slow_settings,
        ):
            start = time.perf_counter()
            out = ome_canonical.metadata_with_job_physical_sizes(
                metadata,
                "client",
                "Overview",
                read_timeout_s=0.01,
            )

        assert time.perf_counter() - start < 0.15
        assert out == metadata


class TestSave:
    def test_save_persists_image_xml_and_summary(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        output_root = tmp_path / "run_000001"

        result = drv.save(
            None,
            successful_acq,
            output_root,
            naming,
        )

        expected_image = output_root / "overview-scan" / "data" / build_image_name(naming)
        expected_xml = output_root / "overview-scan" / "data" / "metadata" / build_xml_name(naming)
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
            r for r in summary["acquisitions"] if r["naming"]["c"] == 0 and r["naming"]["z"] == 0
        )
        assert rec["image_path"] == ("overview-scan/data/" + build_image_name(naming))
        assert rec["xml_path"] == ("overview-scan/data/metadata/" + build_xml_name(naming))
        assert rec["source_exporter"] == "lasx_native_autosave"
        assert rec["naming"]["p"] == 3

    def test_save_does_not_issue_microscope_acquire(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        with patch.object(capture._commands, "acquire") as command:
            drv.save(
                None,
                successful_acq,
                tmp_path / "run_000001",
                naming,
            )
        command.assert_not_called()

    def test_save_plumbs_export_completion_timeout(
        self,
        successful_acq,
        tmp_path,
        naming,
        monkeypatch,
    ):
        collect = Mock(side_effect=RuntimeError("stop after kwargs"))
        monkeypatch.setattr(acquisition, "collect_lasx_native_autosave", collect)
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
        assert collect.call_args.kwargs["export_completion_poll_interval"] == 0.25

    def test_lineage_passes_through(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        lineage = {"source_tile_rid": 1, "row": 2, "col": 3}
        output_root = tmp_path / "run_000001"
        drv.save(
            None,
            successful_acq,
            output_root,
            naming,
            lineage=lineage,
        )
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

        saved = drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
        )

        assert saved.xml_paths == {
            drv.PositionIndex(t=0, v=5): tmp_path
            / "run_000001"
            / "overview-scan"
            / "data"
            / "metadata"
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
        saved = drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
        )
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

        saved = drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
        )

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

    def test_corrupt_ome_tiff_raises(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        with patch.object(
            materialize._ome,
            "check_ome_tiff",
            return_value={
                "path": "x",
                "corrupted": True,
                "violations": ["bad"],
                "error": None,
            },
        ):
            with pytest.raises(RuntimeError, match="OME-TIFF validation"):
                drv.save(
                    None,
                    successful_acq,
                    tmp_path / "run_000001",
                    naming,
                )

    def test_save_generates_canonical_ome_and_preserves_source(
        self,
        tmp_path,
        naming,
    ):
        source_dir = tmp_path / "source"
        metadata_dir = source_dir / "metadata"
        metadata_dir.mkdir(parents=True)
        image_path = source_dir / "image--Z00--C00.ome.tif"
        xml_path = metadata_dir / "source.ome.xml"
        tifffile.imwrite(
            str(image_path),
            np.zeros((16, 16), dtype=np.uint8),
            description='<OME><Laser Wavelength="0"/></OME>',
        )
        source_before = image_path.read_bytes()
        xml_path.write_bytes(b'<OME><Laser Wavelength="0"/></OME>')
        exported = ExportedAcquisition(
            source_root=tmp_path,
            source_dir=source_dir,
            positions=[
                ExportedPosition(
                    t=0,
                    planes={drv.PlaneIndex(t=0, z=0, c=0): drv.PlaneSource(path=image_path)},
                )
            ],
            metadata=_metadata(),
            method="test",
            vendor_metadata_sources=(
                drv.VendorMetadataSource(name="source.ome.xml", path=xml_path),
            ),
        )
        with (
            patch.object(
                materialize._ome,
                "fix_ome_tiff",
            ) as fix_ome_tiff,
            patch.object(
                materialize._ome,
                "fix_ome_xml_file",
            ) as fix_ome_xml_file,
        ):
            acquisition._persist_export(
                exported,
                tmp_path / "out",
                naming,
                lineage=None,
                fix_ome=True,
                cleanup_source=False,
            )

        out_img = next((tmp_path / "out" / "overview-scan" / "data").glob("*.ome.tiff"))
        out_xml = next((tmp_path / "out" / "overview-scan" / "data" / "metadata").glob("*.ome.xml"))
        assert image_path.read_bytes() == source_before
        assert b'Wavelength="0"' not in out_img.read_bytes()
        assert b'Wavelength="0"' not in out_xml.read_bytes()
        assert fix_ome_tiff.call_count == 0
        assert fix_ome_xml_file.call_count == 0

    def test_canonical_output_references_canonical_filenames(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        saved = drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
        )

        xml = next(iter(saved.xml_paths.values())).read_text(encoding="utf-8")
        for image_path in saved.image_paths.values():
            assert f'FileName="{image_path.name}"' in xml
        assert "image--L0000" not in xml

    def test_canonical_output_is_valid_under_ome_types(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        pytest.importorskip("ome_types")
        from ome_types import from_tiff, from_xml

        saved = drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
        )

        for image_path in saved.image_paths.values():
            from_tiff(str(image_path), validate=True)
        for xml_path in saved.xml_paths.values():
            from_xml(xml_path.read_text(encoding="utf-8"), validate=True)

    def test_canonical_output_preserves_pixels(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        saved = drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
        )

        for idx, src in patched_export["plane_paths"].items():
            assert np.array_equal(
                tifffile.imread(str(src)),
                tifffile.imread(str(saved.image_paths[idx])),
            )

    def test_vendor_metadata_is_preserved_as_provenance(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        output_root = tmp_path / "run_000001"
        drv.save(
            None,
            successful_acq,
            output_root,
            naming,
        )
        summary = json.loads((output_root / "summary.json").read_text())
        rec = summary["acquisitions"][0]

        assert rec["canonical_metadata"] is True
        assert rec["vendor_metadata"]
        for item in rec["vendor_metadata"]:
            assert (output_root / item["path"]).is_file()
            assert item["sha256"]

    def test_repeated_save_replaces_summary_record(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        output_root = tmp_path / "run_000001"
        drv.save(
            None,
            successful_acq,
            output_root,
            naming,
        )
        drv.save(
            None,
            successful_acq,
            output_root,
            naming,
        )
        summary = json.loads((output_root / "summary.json").read_text())
        assert len(summary["acquisitions"]) == 4


class TestHelpers:
    def test_ome_ok_is_strict_about_contract_shape(self):
        assert (
            materialize.ome_ok({"path": "x", "corrupted": False, "violations": [], "error": None})
            is True
        )
        assert (
            materialize.ome_ok(
                {"path": "x", "corrupted": True, "violations": ["bad"], "error": None}
            )
            is False
        )
        assert (
            materialize.ome_ok({"path": "x", "corrupted": False, "violations": [], "error": "I/O"})
            is False
        )
        with pytest.raises(KeyError):
            materialize.ome_ok({"success": True})

    def test_image_source_materialization_cleans_tmp_on_copy_failure(
        self,
        tmp_path,
        monkeypatch,
    ):
        src_img = tmp_path / "src.ome.tif"
        tifffile.imwrite(str(src_img), np.zeros((16, 16), dtype=np.uint8))
        dest_img = tmp_path / "dest" / "out.ome.tiff"
        dest_img.parent.mkdir()

        def failing_imwrite(path, *args, **kwargs):
            Path(str(path)).write_bytes(b"partial")
            raise OSError("simulated disk full")

        monkeypatch.setattr(tifffile, "imwrite", failing_imwrite)

        with pytest.raises(OSError, match="simulated disk full"):
            materialize.save_image_source_atomic(
                drv.PlaneSource(path=src_img),
                dest_img,
                metadata=_metadata(),
                index=drv.PlaneIndex(t=0, z=0, c=0),
            )

        assert not dest_img.exists()
        assert list(dest_img.parent.glob("*.tmp")) == []

    def test_exported_acquisition_source_files_are_deduplicated(self, tmp_path):
        tiff = tmp_path / "native.ome.tif"
        xml = tmp_path / "source.ome.xml"
        xml.write_bytes(b"<OME/>")
        exported = ExportedAcquisition(
            source_root=tmp_path,
            source_dir=tmp_path,
            positions=[
                ExportedPosition(
                    t=0,
                    planes={
                        drv.PlaneIndex(t=0, z=0, c=0): drv.PlaneSource(path=tiff, page_index=0),
                        drv.PlaneIndex(t=0, z=0, c=1): drv.PlaneSource(path=tiff, page_index=1),
                    },
                )
            ],
            metadata=drv.AcquisitionMetadata(
                size_x=8,
                size_y=8,
                size_t=1,
                size_z=1,
                size_c=2,
                pixel_type="uint8",
            ),
            method="test",
            vendor_metadata_sources=(drv.VendorMetadataSource(name="source.ome.xml", path=xml),),
        )

        assert exported.image_files == [tiff]
        assert exported.metadata_files == [xml]
        assert exported.source_files == [tiff, xml]
