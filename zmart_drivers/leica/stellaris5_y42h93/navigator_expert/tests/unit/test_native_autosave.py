"""Unit tests for LAS X native AutoSave collection and persistence."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

import navigator_expert as drv
import numpy as np
import pytest
import tifffile
from navigator_expert.acquisition import capture, materialize
from navigator_expert.acquisition import lasx_native_autosave as native
from navigator_expert.acquisition import save as acquisition

from shared.output_layout import Naming


@pytest.fixture
def naming() -> Naming:
    return Naming(
        acquisition_type="overview-scan",
        hash6="000001",
        position_label="000003",
    )


@pytest.fixture
def successful_acq() -> capture.AcquisitionResult:
    return capture.AcquisitionResult(
        job="Overview",
        started_at=time.time() - 1,
        finished_at=time.time(),
        command_result={"success": True, "message": "ok"},
    )


def _native_lcf(tmp_path: Path, root: Path) -> Path:
    path = tmp_path / "UserDataNavigatorExpert.lcf"
    path.write_text(
        (
            f'<Config AutoSaveBaseFolder="{str(root)}" DoUseAutoSave="True" '
            'DoStoreInSeparateFolders="True" />'
        ),
        encoding="utf-8",
    )
    return path


def _native_project(root: Path, name: str = "Project001") -> Path:
    project = root / f"2026_06_01_15_33_09--{name}"
    metadata = project / "Metadata"
    metadata.mkdir(parents=True)
    (metadata / "IOManagerConfiguation.xlif").write_text(
        (
            "<Root>"
            '<Element Name="ImageFormat" Value="OME-TIF" />'
            '<Element Name="WritePyramids" Value="0" />'
            "</Root>"
        ),
        encoding="utf-8",
    )
    (project / f"{name}.xlef").write_text("<Root />", encoding="utf-8")
    return project


def _write_native_ome_tiff(path: Path, data: np.ndarray, axes: str = "TZCYX") -> Path:
    tifffile.imwrite(str(path), data, ome=True, metadata={"axes": axes})
    now = time.time()
    os.utime(path, (now, now))
    return path


def _native_data() -> np.ndarray:
    data = np.zeros((2, 2, 3, 8, 8), dtype=np.uint8)
    for t in range(2):
        for z in range(2):
            for c in range(3):
                data[t, z, c, :, :] = 100 * t + 10 * z + c
    return data


def _native_data_single_t() -> np.ndarray:
    """Single-timepoint variant: the flat name keys only c and z (no t)."""
    data = np.zeros((1, 2, 3, 8, 8), dtype=np.uint8)
    for z in range(2):
        for c in range(3):
            data[0, z, c, :, :] = 10 * z + c
    return data


class TestCollectNativeAutoSave:
    def test_collect_maps_native_multipage_tiff_by_axes(
        self,
        tmp_path,
        successful_acq,
    ):
        root = tmp_path / "native-root"
        project = _native_project(root)
        tiff = _write_native_ome_tiff(project / "Overview001.ome.tif", _native_data())
        with (
            patch.object(native._files, "read_relative_path", return_value=""),
            patch.object(
                native._files,
                "wait_all_stable",
                return_value={"success": True},
            ) as wait_all_stable,
        ):
            exported = native.collect_lasx_native_autosave(
                None,
                successful_acq,
                autosave_root=root,
                lcf_path=_native_lcf(tmp_path, root),
                export_completion_timeout=0.01,
            )

        assert exported.source_exporter == "lasx_native_autosave"
        assert exported.cleanup_source_supported is False
        assert exported.image_files == [tiff]
        assert any(src.data for src in exported.vendor_metadata_sources)
        assert exported.metadata.size_t == 2
        assert exported.metadata.size_z == 2
        assert exported.metadata.size_c == 3
        assert [pos.t for pos in exported.positions] == [0, 1]
        wait_all_stable.assert_called_once_with(
            [tiff],
            timeout=native.DEFAULT_FILE_STABILITY_TIMEOUT_S,
        )

        with tifffile.TiffFile(str(tiff)) as tif:
            for pos in exported.positions:
                for idx, source in pos.planes.items():
                    assert source.path == tiff
                    assert source.page_index is not None
                    value = tif.pages[source.page_index].asarray()[0, 0]
                    assert value == 100 * idx.t + 10 * idx.z + idx.c

    def test_relative_path_anchors_native_when_multiple_fresh_files_exist(
        self,
        tmp_path,
        successful_acq,
    ):
        root = tmp_path / "native-root"
        project = _native_project(root)
        other = _write_native_ome_tiff(
            project / "Overview001.ome.tif",
            _native_data(),
        )
        target = _write_native_ome_tiff(
            project / "Overview002.ome.tif",
            _native_data() + 1,
        )
        with (
            patch.object(
                native._files,
                "read_relative_path",
                return_value=target.name,
            ),
            patch.object(
                native._files,
                "wait_all_stable",
                return_value={"success": True},
            ),
        ):
            exported = native.collect_lasx_native_autosave(
                None,
                successful_acq,
                autosave_root=root,
                lcf_path=_native_lcf(tmp_path, root),
            )

        assert exported.method == "lasx_native_autosave:relative_path"
        assert exported.image_files == [target]
        assert other not in exported.source_files

    def test_multiple_fresh_native_candidates_fail_closed(
        self,
        tmp_path,
        successful_acq,
    ):
        root = tmp_path / "native-root"
        project = _native_project(root)
        _write_native_ome_tiff(project / "Overview001.ome.tif", _native_data())
        _write_native_ome_tiff(project / "Overview002.ome.tif", _native_data() + 1)
        with patch.object(native._files, "read_relative_path", return_value=""):
            with pytest.raises(RuntimeError, match="Multiple fresh"):
                native.collect_lasx_native_autosave(
                    None,
                    successful_acq,
                    autosave_root=root,
                    lcf_path=_native_lcf(tmp_path, root),
                    export_completion_timeout=0.01,
                )

    def test_autosave_off_produces_actionable_warning(self, tmp_path, successful_acq):
        """.lcf reports AutoSave enabled but the live session has it off: the
        scan completes and nothing is written. Fail with a clear, actionable
        message naming the disabled session -- not the generic 'no file found'.
        """
        root = tmp_path / "native-root"
        root.mkdir()
        with patch.object(native._files, "read_relative_path", return_value=""):
            with pytest.raises(RuntimeError, match="disabled in the running LAS X"):
                native.collect_lasx_native_autosave(
                    None,
                    successful_acq,
                    autosave_root=root,
                    lcf_path=_native_lcf(tmp_path, root),
                    export_completion_timeout=0.0,
                    export_completion_poll_interval=0.001,
                )

    def test_slow_autosave_file_is_awaited_past_the_detection_window(
        self,
        tmp_path,
        successful_acq,
    ):
        """Once a fresh project exists (AutoSave engaged), the OME-TIFF is
        awaited with no premature timeout: a file that only appears after the
        detection deadline still resolves, rather than failing closed."""
        root = tmp_path / "native-root"
        project = _native_project(root)  # fresh project dir => AutoSave engaged
        tiff = project / "Overview001.ome.tif"
        real_fresh = native._fresh_native_tiffs
        calls = {"n": 0}

        def delayed_fresh(base, acq):
            calls["n"] += 1
            if calls["n"] <= 3:
                return []  # file not flushed yet
            _write_native_ome_tiff(tiff, _native_data())
            return real_fresh(base, acq)

        with (
            patch.object(native, "_fresh_native_tiffs", side_effect=delayed_fresh),
            patch.object(native._files, "read_relative_path", return_value=""),
            patch.object(
                native._files,
                "wait_all_stable",
                return_value={"success": True},
            ),
        ):
            exported = native.collect_lasx_native_autosave(
                None,
                successful_acq,
                autosave_root=root,
                lcf_path=_native_lcf(tmp_path, root),
                export_completion_timeout=0.0,  # detection deadline already passed
                export_completion_poll_interval=0.001,
            )

        assert exported.image_files == [tiff]
        assert calls["n"] >= 4  # kept polling past the detection deadline

    def test_native_project_config_is_optional_when_tiff_is_valid(
        self,
        tmp_path,
        successful_acq,
    ):
        root = tmp_path / "native-root"
        project = root / "2026_06_01_15_33_09--Project001"
        project.mkdir(parents=True)
        (project / "Project001.xlef").write_text("<Root />", encoding="utf-8")
        tiff = _write_native_ome_tiff(project / "Overview001.ome.tif", _native_data())

        with (
            patch.object(native._files, "read_relative_path", return_value=""),
            patch.object(
                native._files,
                "wait_all_stable",
                return_value={"success": True},
            ),
        ):
            exported = native.collect_lasx_native_autosave(
                None,
                successful_acq,
                autosave_root=root,
                lcf_path=_native_lcf(tmp_path, root),
                export_completion_timeout=0.01,
            )

        assert exported.image_files == [tiff]

    def test_vendor_metadata_keeps_current_xlif_not_stale_project_history(
        self,
        tmp_path,
    ):
        root = tmp_path / "native-root"
        project = _native_project(root)
        metadata = project / "Metadata"
        (metadata / "Overview001.xlif").write_text(
            "<Old />",
            encoding="utf-8",
        )
        current_xlif = metadata / "Overview002.xlif"
        current_xlif.write_text("<Current />", encoding="utf-8")
        tiff = _write_native_ome_tiff(project / "Overview002.ome.tif", _native_data())

        sources = native._vendor_metadata_sources(project, tiff)
        source_names = {src.name for src in sources}

        assert "source_embedded.ome.xml" in source_names
        assert "Project001.xlef" in source_names
        assert "metadata_Overview002.xlif" in source_names
        assert "metadata_IOManagerConfiguation.xlif" in source_names
        assert "metadata_Overview001.xlif" not in source_names

    def test_bad_native_axes_fail_closed(self, tmp_path):
        tiff = tmp_path / "bad.ome.tif"
        tifffile.imwrite(
            str(tiff),
            np.zeros((2, 8, 8), dtype=np.uint8),
            ome=True,
            metadata={"axes": "QYX"},
        )
        with pytest.raises(RuntimeError, match="Unsupported native AutoSave axes"):
            native._plane_sources_from_tiff(tiff)


class TestNativeSave:
    def test_default_save_source_root_uses_native_autosave_base(
        self,
        tmp_path,
        monkeypatch,
    ):
        root = tmp_path / "native-root"
        monkeypatch.setattr(acquisition, "native_autosave_enabled", lambda: True)
        monkeypatch.setattr(
            acquisition,
            "native_autosave_base_folder",
            lambda: root,
        )

        assert drv.save_source_root() == root

    def test_save_source_root_requires_native_autosave_enabled(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(acquisition, "native_autosave_enabled", lambda: False)

        with pytest.raises(RuntimeError, match="native AutoSave is not enabled"):
            drv.save_source_root()

    def test_save_materializes_native_multipage_tiff_to_flat_output(
        self,
        tmp_path,
        successful_acq,
        naming,
        monkeypatch,
    ):
        root = tmp_path / "native-root"
        project = _native_project(root)
        tiff = _write_native_ome_tiff(project / "Overview001.ome.tif", _native_data_single_t())
        exported = native.ExportedAcquisition(
            source_root=root,
            source_dir=project,
            positions=native._positions_from_native_tiff(tiff),
            metadata=native._metadata_from_native_tiff(
                tiff,
                native._positions_from_native_tiff(tiff),
            ),
            method="test",
            source_exporter="lasx_native_autosave",
            cleanup_source_supported=False,
            vendor_metadata_sources=native._vendor_metadata_sources(project, tiff),
        )

        collect = Mock(return_value=exported)
        monkeypatch.setattr(acquisition, "collect_lasx_native_autosave", collect)
        saved = drv.save(
            None,
            successful_acq,
            tmp_path / "run_000001",
            naming,
        )

        collect.assert_called_once()
        # Flat: one 2-D plane per (c, z); no sidecar XML.
        assert len(saved.image_paths) == 6
        assert saved.xml_paths == {}
        run_dir = tmp_path / "run_000001"
        for idx, image_path in saved.image_paths.items():
            # Flat write directly under the acquisition-type folder.
            assert image_path.parent == run_dir / "overview-scan"
            arr = tifffile.imread(str(image_path))
            assert arr.shape == (8, 8)
            assert arr[0, 0] == 10 * idx.z + idx.c

        summary = json.loads((run_dir / "summary.json").read_text())
        assert len(summary["acquisitions"]) == 6
        assert {r["source_exporter"] for r in summary["acquisitions"]} == {"lasx_native_autosave"}
        assert all(r["canonical_metadata"] is True for r in summary["acquisitions"])
        assert all(r["vendor_metadata"] for r in summary["acquisitions"])

    def test_cleanup_source_rejected_for_native_project_container(
        self,
        tmp_path,
        successful_acq,
        naming,
        monkeypatch,
    ):
        root = tmp_path / "native-root"
        project = _native_project(root)
        tiff = _write_native_ome_tiff(project / "Overview001.ome.tif", _native_data())
        exported = native.ExportedAcquisition(
            source_root=root,
            source_dir=project,
            positions=native._positions_from_native_tiff(tiff),
            metadata=native._metadata_from_native_tiff(
                tiff,
                native._positions_from_native_tiff(tiff),
            ),
            method="test",
            source_exporter="lasx_native_autosave",
            cleanup_source_supported=False,
            vendor_metadata_sources=native._vendor_metadata_sources(project, tiff),
        )

        monkeypatch.setattr(
            acquisition,
            "collect_lasx_native_autosave",
            Mock(return_value=exported),
        )
        with pytest.raises(RuntimeError, match="cleanup_source"):
            drv.save(
                None,
                successful_acq,
                tmp_path / "run_000001",
                naming,
                cleanup_source=True,
            )
        assert tiff.is_file()
        assert not (tmp_path / "run_000001").exists()

    def test_embedded_ome_xml_extraction_falls_back_for_bigtiff(
        self,
        tmp_path,
        monkeypatch,
    ):
        tiff = _write_native_ome_tiff(tmp_path / "native.ome.tif", _native_data())
        monkeypatch.setattr(
            materialize._ome,
            "_read_tiff_tag_270",
            lambda _data: (None, None, None, None, "Not a standard TIFF (magic=43)"),
        )

        raw = materialize.extract_embedded_ome_xml(tiff)

        assert b"<OME" in raw

    def test_embedded_ome_xml_preserved_as_vendor_metadata(self, tmp_path):
        tiff = tmp_path / "native.ome.tif"
        vendor_dest = tmp_path / "vendor" / "source_embedded.ome.xml"
        vendor_dest.parent.mkdir()
        embedded = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<OME><Instrument><LightSource ID="LightSource:499nm">'
            '<Laser Wavelength="0"/></LightSource></Instrument></OME>'
        )
        tifffile.imwrite(
            str(tiff),
            np.zeros((4, 4), dtype=np.uint8),
            description=embedded,
        )
        source_before = tiff.read_bytes()

        materialize.save_vendor_metadata_atomic(
            drv.VendorMetadataSource(
                name="source_embedded.ome.xml",
                data=materialize.extract_embedded_ome_xml(tiff),
            ),
            vendor_dest,
        )

        assert tiff.read_bytes() == source_before
        assert b'Wavelength="0"' in vendor_dest.read_bytes()
