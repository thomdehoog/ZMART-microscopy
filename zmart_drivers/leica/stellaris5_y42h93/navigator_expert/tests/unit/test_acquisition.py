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
from navigator_expert.acquisition.naming import Naming, build_image_name, parse_image_name
from navigator_expert.acquisition.product import (
    ExportedAcquisition,
    ExportedPosition,
)
from navigator_expert.orientation import Orientation, reorient_array
from navigator_expert.readers import router as readers_router


@pytest.fixture(autouse=True)
def _identity_rig_orientation(monkeypatch):
    monkeypatch.setattr("navigator_expert.orientation.rig_orientation", Orientation)


@pytest.fixture
def naming() -> Naming:
    return Naming(
        acquisition_type="overview-scan",
        hash6="000001",
        position_label="000003",
    )


def test_leica_private_naming_round_trips_time_channel_and_z():
    naming = Naming(
        acquisition_type="overview",
        hash6="abc123",
        position_label="K00_M000000_G000000_P000000_V00",
        t=12,
        c=2,
        z=34,
    )
    assert build_image_name(naming).endswith("_T000012_C02_Z00034.ome.tiff")
    assert parse_image_name(build_image_name(naming)) == naming


@pytest.mark.parametrize(("field", "value"), [("t", 1_000_000), ("c", 100), ("z", -1)])
def test_leica_private_naming_rejects_unrepresentable_plane_indices(field, value):
    with pytest.raises(ValueError, match=field):
        Naming(
            acquisition_type="overview",
            hash6="abc123",
            position_label="P0",
            **{field: value},
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
        vendor_metadata_sources=(drv.VendorMetadataSource(name="source.ome.xml", path=xml_path),),
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
            readers_router,
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
                readers_router,
                "get_job_settings",
                return_value=settings,
            ),
            patch.object(
                ome_canonical._parsing,
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
            readers_router,
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
            readers_router,
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
    def test_save_applies_the_active_rig_orientation_by_default(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
        monkeypatch,
    ):
        orientation = Orientation(rotate_deg=90, mirrored=True)
        monkeypatch.setattr(
            "navigator_expert.orientation.rig_orientation",
            lambda: orientation,
        )

        saved = drv.save(None, successful_acq, tmp_path / "out", naming)

        for index, source_path in patched_export["plane_paths"].items():
            source = tifffile.imread(source_path)
            written = tifffile.imread(saved.image_paths[index])
            assert np.array_equal(written, reorient_array(source, orientation))

    def test_timepoints_have_distinct_six_digit_T_names(
        self, successful_acq, tmp_path, naming, monkeypatch
    ):
        source_root = tmp_path / "source"
        source_root.mkdir()
        planes = {}
        positions = []
        for t in (0, 1):
            index = drv.PlaneIndex(t=t, z=0, c=0)
            source = source_root / f"time-{t}.tiff"
            tifffile.imwrite(source, np.full((16, 16), t, dtype=np.uint8))
            plane = drv.PlaneSource(path=source)
            planes[index] = plane
            positions.append(ExportedPosition(t=t, planes={index: plane}))
        metadata = replace(_metadata(), size_t=2)
        exported = ExportedAcquisition(
            source_root=source_root,
            source_dir=source_root,
            positions=positions,
            metadata=metadata,
            method="test",
        )
        monkeypatch.setattr(acquisition, "collect_lasx_native_autosave", lambda *a, **k: exported)

        saved = drv.save(None, successful_acq, tmp_path / "out", naming)

        assert len(saved.image_paths) == 2
        assert saved.image_paths[drv.PlaneIndex(t=0, z=0, c=0)].name.endswith(
            "_T000000_C00_Z00000.ome.tiff"
        )
        assert saved.image_paths[drv.PlaneIndex(t=1, z=0, c=0)].name.endswith(
            "_T000001_C00_Z00000.ome.tiff"
        )
        assert len({path.name for path in saved.image_paths.values()}) == 2

    def test_save_persists_image_and_summary_flat(
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

        # Flat: one 2-D plane per file directly under the acquisition folder,
        # no sidecar XML.
        expected_image = output_root / "overview-scan" / build_image_name(naming)
        assert isinstance(result, drv.SavedAcquisition)
        assert set(result.image_paths) == set(patched_export["plane_paths"])
        assert result.image_paths[drv.PlaneIndex(t=0, z=0, c=0)] == expected_image
        assert result.xml_paths == {}
        assert tifffile.imread(expected_image).shape == (16, 16)
        assert all(p.is_file() for p in result.image_paths.values())

        summary = json.loads((output_root / "summary.json").read_text())
        assert len(summary["acquisitions"]) == 4
        rec = next(
            r for r in summary["acquisitions"] if r["naming"]["c"] == 0 and r["naming"]["z"] == 0
        )
        assert rec["image_path"] == ("overview-scan/" + build_image_name(naming))
        assert "xml_path" not in rec
        assert rec["source_exporter"] == "lasx_native_autosave"
        assert rec["naming"]["position_label"] == "000003"

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

    def test_save_embeds_state_in_plane_ome_xml_when_provided(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        state = {
            "software": {"driver_version": "6.0.0"},
            "hardware": {"Microscope": {"name": "DM Manual-6"}},
            "provenance": {
                "acquisition_type": "overview-scan",
                "position_label": "000003",
                "acquisition_hash": "9k2m4p",
                "session_hash6": "000abc",
                "exported_at": "2026-07-07T00:00:00+00:00",
            },
        }

        saved = drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
            state=state,
        )

        for image_path in saved.image_paths.values():
            embedded = tifffile.TiffFile(str(image_path)).pages[0].description
            assert "StructuredAnnotations" in embedded
            assert 'ID="Annotation:zmart-state-map"' in embedded
            assert 'ID="Annotation:zmart-state-json"' in embedded
            assert 'Namespace="https://zmart-microscopy/state"' in embedded
            # the flat JSON highlights and the full JSON dump are both present
            assert 'K="position_label"' in embedded
            assert '"driver_version": "6.0.0"' in embedded

    def test_save_omits_state_annotations_when_not_provided(
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
        for image_path in saved.image_paths.values():
            embedded = tifffile.TiffFile(str(image_path)).pages[0].description
            assert "StructuredAnnotations" not in embedded

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

    def test_save_preserves_caller_owned_position_label(
        self,
        patched_export,
        successful_acq,
        tmp_path,
    ):
        naming = Naming(
            acquisition_type="overview-scan",
            hash6="000001",
            position_label="well_B7",
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
            assert parsed.acquisition_type == "overview-scan"
            assert parsed.hash6 == "000001"
            assert parsed.position_label == "well_B7"
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

        out_img = next((tmp_path / "out" / "overview-scan").glob("*.ome.tiff"))
        assert image_path.read_bytes() == source_before
        assert b'Wavelength="0"' not in out_img.read_bytes()
        assert fix_ome_tiff.call_count == 0
        assert fix_ome_xml_file.call_count == 0

    def test_embedded_plane_ome_references_its_own_filename(
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

        for image_path in saved.image_paths.values():
            embedded = tifffile.TiffFile(str(image_path)).pages[0].description
            assert f'FileName="{image_path.name}"' in embedded
            assert "image--L0000" not in embedded

    def test_canonical_output_is_valid_under_ome_types(
        self,
        patched_export,
        successful_acq,
        tmp_path,
        naming,
    ):
        # ome-types + lxml are firm dependencies (environment.yml /
        # requirements.txt / requirements-dev.txt): the driver's OME-TIFF
        # output — including the embedded machine-state block — MUST validate
        # against the OME schema, so this gate never silently skips.
        from ome_types import from_tiff

        state = {
            "software": {"driver_version": "6.0.0"},
            "provenance": {"acquisition_type": "overview-scan", "position_label": "000003"},
        }
        saved = drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
            state=state,
        )

        # The embedded per-plane OME (with the StructuredAnnotations block)
        # must validate against the OME schema.
        for image_path in saved.image_paths.values():
            from_tiff(str(image_path), validate=True)

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
