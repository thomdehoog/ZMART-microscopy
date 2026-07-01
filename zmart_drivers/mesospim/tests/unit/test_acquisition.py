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


def test_acquire_stack_multiple_frames(client):
    result = acq.acquire(client, "prescan", options={"z_start": 0, "z_end": 4, "z_step": 1})
    assert result.planes == 5
    assert len(result.files) == 5


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


def test_save_multiplane_names(client, tmp_path):
    result = acq.acquire(client, "stack", options={"z_start": 0, "z_end": 2, "z_step": 1})
    saved = acq.save(result, tmp_path / "run", position_label="B2")
    assert len(saved.image_paths) == 3
    names = sorted(p.name for p in saved.image_paths)
    assert names[0].endswith("_z0000.tiff")


def test_acquire_no_frames_raises(client, monkeypatch):
    # Force the server reply to carry no files.
    real = client.request

    def fake(cmd, **args):
        reply = real(cmd, **args)
        if cmd == "acquire":
            object.__setattr__(reply, "data", {"files": [], "planes": 0})
        return reply

    monkeypatch.setattr(client, "request", fake)
    with pytest.raises(RuntimeError):
        acq.acquire(client, "snap")


def test_run_acquisition_list(client):
    state = readers.get_state(client)
    a1 = acq.build_acquisition(state, {"x_pos": 0})
    a2 = acq.build_acquisition(state, {"x_pos": 100})
    data = acq.run_acquisition_list(client, [a1, a2])
    assert len(data["files"]) == 2
