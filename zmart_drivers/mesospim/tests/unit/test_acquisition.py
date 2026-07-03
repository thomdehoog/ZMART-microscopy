"""Capture + save against the mock server (writes real synthetic frames)."""

from __future__ import annotations

import json

import pytest
import tifffile
from mesospim import acquisition as acq
from mesospim import readers


def test_build_acquisition_from_state(client):
    state = readers.get_state(client)
    a = acq.build_acquisition(state)
    assert a["planes"] == 1
    assert a["laser"] == state["laser"]
    assert a["zoom"] == state["zoom"]


def test_build_acquisition_stack_plane_count(client):
    state = readers.get_state(client)
    a = acq.build_acquisition(state, {"z_start": 0.0, "z_end": 10.0, "z_step": 2.0})
    assert a["planes"] == 6  # 0,2,4,6,8,10


def test_snap_single_frame(client):
    result = acq.snap(client)
    assert result.planes == 1
    assert len(result.files) == 1
    assert result.files[0].exists()


def test_acquire_stack_is_single_multipage_stack(client):
    # The default mesoSPIM Tiff writer produces ONE multi-page stack per
    # acquisition (not one file per plane), so a 5-plane stack is 1 file.
    result = acq.acquire(client, "prescan", options={"z_start": 0, "z_end": 4, "z_step": 1})
    assert result.planes == 5
    assert len(result.files) == 1
    assert tifffile.imread(str(result.files[0])).shape == (5, 64, 64)


def test_metadata_populated(client):
    result = acq.snap(client)
    meta = result.metadata
    assert meta.size_x == 64 and meta.size_y == 64
    assert meta.channels[0].laser == "488 nm"
    assert meta.channels[0].wavelength_nm == 488


def test_save_single_frame(client, tmp_path):
    result = acq.snap(client)
    saved = acq.save(result, tmp_path / "run", position_label="A1")
    assert len(saved.image_paths) == 1
    img = saved.image_paths[0]
    assert img.exists() and img.parent.name == "data"
    assert "A1" in img.name
    # sidecar metadata
    assert saved.metadata_path.exists()
    payload = json.loads(saved.metadata_path.read_text())
    assert payload["position_label"] == "A1"
    # the frame is a readable TIFF
    assert tifffile.imread(str(img)).shape == (64, 64)


def test_save_stack_single_file(client, tmp_path):
    # One multi-page stack in -> one file out, named by the canonical stem.
    result = acq.acquire(client, "stack", options={"z_start": 0, "z_end": 2, "z_step": 1})
    saved = acq.save(result, tmp_path / "run", position_label="B2")
    assert len(saved.image_paths) == 1
    img = saved.image_paths[0]
    assert "B2" in img.name and img.parent.name == "data"
    assert tifffile.imread(str(img)).shape == (3, 64, 64)


def test_save_multiple_source_files_get_plane_suffixes(tmp_path):
    # If a writer ever returns one file per plane, save() names them in order.
    # (Covers the multi-file naming branch directly, without the mock.)
    import numpy as np
    from mesospim.acquisition.product import (
        AcquisitionMetadata,
        AcquisitionResult,
        ChannelMetadata,
    )

    src = tmp_path / "src"
    src.mkdir()
    sources = []
    for i in range(3):
        p = src / f"frame_{i}.tiff"
        tifffile.imwrite(str(p), np.zeros((8, 8), dtype="uint16"))
        sources.append(p)
    result = AcquisitionResult(
        acquisition_type="stack",
        acquisition={},
        started_at=0.0,
        finished_at=1.0,
        files=tuple(sources),
        planes=3,
        metadata=AcquisitionMetadata(size_x=8, size_y=8, size_z=3, channels=(ChannelMetadata(0),)),
    )
    saved = acq.save(result, tmp_path / "run", position_label="C1")
    assert len(saved.image_paths) == 3
    names = sorted(p.name for p in saved.image_paths)
    assert names[0].endswith("_z0000.tiff")


def _result_from(files, planes=1):
    from mesospim.acquisition.product import (
        AcquisitionMetadata,
        AcquisitionResult,
        ChannelMetadata,
    )

    return AcquisitionResult(
        acquisition_type="snap",
        acquisition={},
        started_at=0.0,
        finished_at=1.0,
        files=tuple(files),
        planes=planes,
        metadata=AcquisitionMetadata(size_x=8, size_y=8, size_z=planes, channels=(ChannelMetadata(0),)),
    )


def test_save_missing_source_raises_before_copying_any(tmp_path):
    import numpy as np

    src = tmp_path / "src"
    src.mkdir()
    good = src / "good.tiff"
    tifffile.imwrite(str(good), np.zeros((8, 8), dtype="uint16"))
    missing = src / "missing.tiff"
    result = _result_from([good, missing], planes=2)
    with pytest.raises(FileNotFoundError):
        acq.save(result, tmp_path / "run", position_label="A1")
    # nothing was copied: the data dir must be empty (no partial dataset).
    data_dir = tmp_path / "run" / "data"
    assert not data_dir.exists() or not any(data_dir.iterdir())


def test_save_same_label_gets_unique_stem(tmp_path):
    import numpy as np

    src = tmp_path / "src"
    src.mkdir()
    frame = src / "f.tiff"
    tifffile.imwrite(str(frame), np.zeros((8, 8), dtype="uint16"))
    s1 = acq.save(_result_from([frame]), tmp_path / "run", position_label="A1")
    s2 = acq.save(_result_from([frame]), tmp_path / "run", position_label="A1")
    assert s1.image_paths[0] != s2.image_paths[0]
    assert s1.metadata_path != s2.metadata_path
    assert s1.image_paths[0].exists() and s2.image_paths[0].exists()


def test_acquire_no_frames_raises(client, monkeypatch):
    # Force the server reply to carry no files.
    real = client.request

    def fake(cmd, **args):
        reply = real(cmd, **args)
        if cmd == "acquire_start":
            object.__setattr__(reply, "data", {"files": [], "planes": 0})
        return reply

    monkeypatch.setattr(client, "request", fake)
    with pytest.raises(RuntimeError):
        acq.acquire(client, "snap")


def test_acquire_restores_operator_acq_list(client, server):
    sentinel = ["operator-list"]
    server.core.state["acq_list"] = sentinel
    acq.snap(client)
    assert server.core.state["acq_list"] is sentinel


def test_acquire_timeout_raises_and_restores(client, server, monkeypatch):
    # A run that never writes its stack must FAIL loudly at the acquisition
    # deadline -- never report success with paths to files that do not exist --
    # and must still hand the operator's acquisition list back. Completion is
    # judged from the file on disk (state is unusable over the bridge -- it always
    # reads 'running_script'), so "never finishes" here means "never writes".
    from dataclasses import replace

    from mesospim.acquisition import capture

    def never_writes(row=0):
        pass  # fire the run but never produce the stack file

    monkeypatch.setattr(server.core, "start", never_writes)
    monkeypatch.setattr(
        capture,
        "ACQUISITION",
        replace(capture.ACQUISITION, acquire_timeout_s=0.3, acquire_poll_s=0.02),
    )
    sentinel = ["operator-list"]
    server.core.state["acq_list"] = sentinel
    with pytest.raises(RuntimeError, match="did not produce a stable stack"):
        acq.acquire(client, "snap")
    assert server.core.state["acq_list"] is sentinel


def test_run_acquisition_list(client):
    state = readers.get_state(client)
    a1 = acq.build_acquisition(state, {"x_pos": 0})
    a2 = acq.build_acquisition(state, {"x_pos": 100})
    data = acq.run_acquisition_list(client, [a1, a2])
    assert len(data["files"]) == 2
