"""Realistic simulator pixels, focus scoring and preview share one source."""
import hashlib

import numpy as np
import pytest
from PIL import Image

from application.parts.microscope import focus_score
from application.parts.microscope.simulator_pixels import KidneyPixels
from application.parts.storage.test_zarr_positions import a_z_stack
from application.parts.storage.zarr_positions import position_store_from_record
from application.parts.storage import jpeg_tiles


def test_kidney_overlap_and_focus_are_independent_of_capture_order():
    pixels = KidneyPixels(focus_z_um=8)
    plane = dict(x_um=512, y_um=512, z_um=8, c=0)
    sharp = pixels((256, 256), np.uint16, plane=plane, pixel_um=(2, 2))
    right = pixels((256, 256), np.uint16, plane={**plane, "x_um": 768}, pixel_um=(2, 2))
    np.testing.assert_array_equal(sharp[:, 128:], right[:, :128])
    for z in (0, 16):
        blurred = pixels((256, 256), np.uint16, plane={**plane, "z_um": z}, pixel_um=(2, 2))
        gradient = lambda a: np.square(np.diff(a.astype(float), axis=1)).mean()
        assert gradient(sharp) > gradient(blurred) * 2
        overlap = pixels((256, 256), np.uint16, plane={**plane, "x_um":768, "z_um":z}, pixel_um=(2, 2))
        np.testing.assert_array_equal(blurred[:, 128:], overlap[:, :128])
    np.testing.assert_array_equal(sharp, pixels((256,256), np.uint16, plane=plane, pixel_um=(2,2)))


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("focus", [8, 420])
def test_focus_and_preview_use_canonical_kidney_not_vendor_tiffs(tmp_path, monkeypatch, reverse, focus):
    heights = list(range(focus - 16, focus + 17, 2))
    record = a_z_stack(tmp_path, heights=heights[::-1] if reverse else heights, acquisition_type="focussing")
    vendor = tmp_path / "vendor.xlif"
    vendor.write_text('<Image SystemTypeName="SIMULATOR"/>')
    record["vendor_metadata"] = [str(vendor)]
    for plane in record["planes"]:
        plane.update(x_um=512, y_um=512)
    from pathlib import Path
    hashes = {p["path"]:hashlib.sha256(Path(p["path"]).read_bytes()).hexdigest() for p in record["planes"]}
    record["zarr"] = str(position_store_from_record(record, tmp_path / "positions", pixel_provider=KidneyPixels(focus_z_um=focus)))
    assert focus_score.what_was_captured(record) == {"image_path":record["zarr"]}
    found = focus_score.in_process(skip_ends=1)(record)
    assert found["z_um"] == pytest.approx(focus, abs=1)
    assert len(set(p["s"] for p in found["traces"]["brenner"]["samples"])) > 5
    # Forbid a vendor TIFF read after canonical ingestion.
    import tifffile
    monkeypatch.setattr(tifffile, "imread", lambda *a, **k: pytest.fail("preview read vendor TIFF"))
    previews = jpeg_tiles.make_slice_copies(tmp_path / "preview", record["planes"],
                                            store=record["zarr"], z_shift_um=3)
    assert [p["z_um"] for p in previews] == pytest.approx([z+3 for z in heights])
    with Image.open(tmp_path / "preview" / previews[8]["name"]) as image:
        assert np.asarray(image).std() > 1
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p,h in hashes.items())


def test_failed_canonical_ingestion_never_scores_vendor_pixels():
    with pytest.raises(RuntimeError, match="canonical"):
        focus_score.what_was_captured({"zarr_error":"incomplete", "planes":[{"path":"vendor.tif"}]})


@pytest.mark.parametrize("enabled", [False, True])
def test_operator_anchors_once_per_connection_not_per_capture(tmp_path, monkeypatch, enabled):
    import json
    from application.framework import bridge

    class Session:
        context = {}
        height = 420.0
        reads = 0

        def get_info(self):
            return {"output_root": str(tmp_path)}

        def get_xyz(self):
            self.reads += 1
            return {"z": {"value": self.height, "unit": "um"}}

    session = Session()
    monkeypatch.setattr(bridge.zmart_controller, "set_instrument", lambda _: session)
    monkeypatch.setattr(bridge.viewer_service, "start", lambda *a, **k: None)
    monkeypatch.setattr(bridge.viewer_service, "stop", lambda: None)
    monkeypatch.setattr(bridge, "_simulator_pixels_enabled", enabled)
    for name in ("_session", "_run", "_pixel_provider"):
        monkeypatch.setattr(bridge, name, None)
    for name in ("_context", "_records", "_view_built", "_displayed_pictures", "_scan", "_focus", "_targets"):
        monkeypatch.setattr(bridge, name, {})
    bridge._connect({"connection": {"vendor": "test"}})
    first = bridge._pixel_provider
    if enabled:
        assert first.focus_z_um == 420
        assert json.loads((bridge._run / "synthetic-specimen.json").read_text())["focus_z_um"] == 420
        near = first((64,64), np.uint8, plane={"x_um":512,"y_um":512,"z_um":420,"c":0}, pixel_um=(2,2))
        assert len(np.unique(near)) > 2  # user's failed case had only values 3 and 4
        session.height = 435
        first((64,64), np.uint8, plane={"x_um":512,"y_um":512,"z_um":435,"c":0}, pixel_um=(2,2))
        assert first.focus_z_um == 420 and session.reads == 1
    else:
        assert first is None and session.reads == 0
        session.height = 435
    bridge._connect({"connection": {"vendor": "test"}})
    if enabled:
        assert bridge._pixel_provider.focus_z_um == 435
        assert first.focus_z_um == 420
        assert session.reads == 2
    else:
        assert session.reads == 0


def test_focus_reference_translation_does_not_change_pixels():
    low, high = KidneyPixels(focus_z_um=8), KidneyPixels(focus_z_um=420)
    for offset in (-12, 0, 9):
        for dtype in (np.uint8, np.uint16):
            plane = {"x_um": -32000, "y_um": -14000, "c": 0}
            a = low((128,128), dtype, plane={**plane,"z_um":8+offset}, pixel_um=(2,2))
            b = high((128,128), dtype, plane={**plane,"z_um":420+offset}, pixel_um=(2,2))
            np.testing.assert_array_equal(a,b)
