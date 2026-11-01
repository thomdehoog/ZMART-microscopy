"""Exercise the operator's real canonical reader, without analysis workers.

Missing runtime dependencies must fail these tests, never silently skip them.
The HTTP requests use an isolated bridge with synthetic stores and no instrument.
"""

import io
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pytest
from PIL import Image

from zmart_interface.framework.bridge import server, workflows

from ..bridge import pictures, state
from .images import declare_image
from .jpeg_tiles import make_slice_copies


@pytest.fixture
def canonical_store(tmp_path):
    store = tmp_path / "position.ome.zarr"
    arrays = declare_image(
        store, canvas_shape=(3, 32, 32), frames=1, channels=2,
        dtype="uint16", chunk=32, levels=1,
        voxel_size_um=(2, 1, 1), first_voxel_um=(10, 20, 30),
        channel_blocks=[
            {"label": label, "color": color,
             "window": {"start": 0, "end": 2000, "min": 0, "max": 65535}}
            for label, color in (("green", "00FF00"), ("magenta", "FF00FF"))
        ],
        ome_zarr_version="0.5",
    )
    # Blank end planes are real data, not failed previews. Each channel peaks
    # in the central plane, so the displayed MIP has a known colour.
    arrays[0][0, 0, 1, :, :] = 1000
    arrays[0][0, 1, 1, :, :] = 500
    return store


@pytest.fixture
def preview_server(monkeypatch, tmp_path, canonical_store):
    record = {
        "position_label": "P0", "zarr": str(canonical_store),
        # Deliberately nonexistent vendor paths: previews must use the store.
        "planes": [{"t": 0, "c": c, "path": "missing-vendor.tif"} for c in range(2)],
    }
    monkeypatch.setattr(state, "run", tmp_path)
    monkeypatch.setattr(state, "records", {k: [record] for k in ("overview", "targets")})
    monkeypatch.setattr(state, "displayed_pictures", {})
    monkeypatch.setattr(server, "ROUTES", {})
    monkeypatch.setattr(server, "PREFIX_ROUTES", {})
    workflows.load_halves(server.add_route)
    bridge_server = ThreadingHTTPServer(("127.0.0.1", 0), server.Bridge)
    thread = threading.Thread(target=bridge_server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{bridge_server.server_port}"
    finally:
        bridge_server.shutdown()
        bridge_server.server_close()
        thread.join(timeout=5)


def _get_jpeg(url):
    with urlopen(url, timeout=10) as response:
        assert response.status == 200
        assert response.headers.get_content_type() == "image/jpeg"
        assert response.headers["Cache-Control"] == "no-store"
        image = Image.open(io.BytesIO(response.read())).convert("RGB")
        return np.asarray(image)


@pytest.mark.parametrize("kind", ["overview", "targets"])
def test_displayed_preview_endpoint_reads_canonical_mip(preview_server, kind):
    display = [
        {"c": 0, "visible": True, "window": [0, 2000], "color": "#00ff00"},
        {"c": 1, "visible": True, "window": [0, 2000], "color": "#ff00ff"},
    ]
    address = f"{preview_server}/api/target_acquisition/view/{kind}/P0.jpg?"
    pixels = _get_jpeg(address + urlencode({"display": json.dumps(display)}))
    np.testing.assert_allclose(pixels[16, 16], [64, 128, 64], atol=3)
    display[1]["visible"] = False
    pixels = _get_jpeg(address + urlencode({"display": json.dumps(display)}))
    np.testing.assert_allclose(pixels[16, 16], [0, 128, 0], atol=3)


def test_focus_slices_are_generated_and_served_at_physical_heights(
    canonical_store, preview_server,
):
    slices = make_slice_copies(
        pictures.view_of("focussing"), [], store=canonical_store,
    )
    assert [entry["z_um"] for entry in slices] == [10, 12, 14]
    pixels = [
        _get_jpeg(f"{preview_server}/api/target_acquisition/view/focussing/{entry['name']}")
        for entry in slices
    ]
    assert pixels[0].max() == 0
    assert pixels[1].max() > 200
    assert pixels[2].max() == 0


def test_refocussing_a_point_gives_its_slices_new_names(canonical_store, tmp_path):
    """The page keeps a slice it has loaded by its name, so a refocussed point
    whose store was rewritten in place must not reuse the old run's names --
    or the side view shows the old run's cells beside (or instead of) the new."""
    into = tmp_path / "slices"
    before = make_slice_copies(into, [], store=canonical_store)
    same = make_slice_copies(into, [], store=canonical_store)
    assert [s["name"] for s in same] == [s["name"] for s in before]

    arrays = declare_image(
        canonical_store, canvas_shape=(3, 32, 32), frames=1, channels=2,
        dtype="uint16", chunk=32, levels=1,
        voxel_size_um=(2, 1, 1), first_voxel_um=(10, 20, 30),
        channel_blocks=[
            {"label": label, "color": color,
             "window": {"start": 0, "end": 2000, "min": 0, "max": 65535}}
            for label, color in (("green", "00FF00"), ("magenta", "FF00FF"))
        ],
        ome_zarr_version="0.5",
    )
    arrays[0][0, 0, 2, :, :] = 1000   # the layer now sits in the top plane
    after = make_slice_copies(into, [], store=canonical_store)
    assert not {s["name"] for s in after} & {s["name"] for s in before}
