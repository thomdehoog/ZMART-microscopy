"""Overview centres the picture in the room the viewer's controls leave.

The depth slider is drawn on top of the drawing area rather than beside it,
so the area the engine believes it has is wider than the area an operator can
actually see into. Centred on the whole of it, the picture sits partly behind
the slider and noticeably off to the right of where the eye expects it. The
operator asked for the framing to ignore that strip (2026-08-22).

Only the depth slider is treated this way, because it is the one control that
stands in the picture's way along a whole edge. The 2-D/3-D toggle and the
scale bar sit in corners the picture rarely reaches.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
import zarr
from PIL import Image
from server import make_server

# How far off centre the picture may be before an operator would see it.
NEAR_ENOUGH = 8


def _a_stack(path, *, planes=6):
    """A bright block through several planes, so the run gets a depth slider."""
    path.mkdir(parents=True)
    block = np.zeros((1, planes, 96, 96), "uint16")
    block[0, :, 16:80, 16:80] = 5000
    zarr.open_group(str(path), mode="w", zarr_format=2).create_array(
        "0", shape=block.shape, chunks=(1, 1, 96, 96), dtype="uint16")[:] = block
    (path / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "c", "type": "channel"},
                     {"name": "z", "type": "space", "unit": "micrometer"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 2.0, 0.5, 0.5]}]}],
        }],
        "omero": {"channels": [{
            "label": "ch0", "color": "00FF66",
            "window": {"min": 0, "max": 65535, "start": 500, "end": 5200}}]},
    }), encoding="utf-8")
    return path


@pytest.fixture
def stack_page(browser, built_dist, tmp_path):
    data = tmp_path / "stack"
    data.mkdir()
    _a_stack(data / "stack_pos001.ome.zarr")
    server = make_server(port=0, data_dir=data, site_dir=built_dist,
                         store="stack_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_timeout(4500)
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_overview_centres_beside_the_depth_slider(stack_page, tmp_path):
    """The picture's middle lands in the middle of what is left, not of the canvas."""
    page = stack_page
    page.get_by_role("button", name="Overview", exact=True).click()
    page.wait_for_timeout(2500)

    room = page.evaluate("""() => {
      const canvas = document.querySelector("canvas").getBoundingClientRect();
      const slider = document.querySelector("[data-beside-the-picture]")
        ?.getBoundingClientRect();
      return {
        left: canvas.left, right: canvas.right,
        sliderLeft: slider && slider.width ? slider.left : null,
      };
    }""")
    assert room["sliderLeft"] is not None, (
        "this run has several planes, so it should have a depth slider; "
        "without one there is nothing here to make room for"
    )

    saved = tmp_path / "centred_beside_the_slider.png"
    page.screenshot(path=str(saved), clip={
        "x": 0, "y": 0, "width": int(room["right"]), "height": 1000})
    shot = np.array(Image.open(saved).convert("RGB")).astype(int)
    shot[:60, :260] = 0                       # the 2D / 3D / Overview toggle
    shot[:45, 860:] = 0                       # the scale bar
    shot[:, int(room["sliderLeft"]):] = 0     # the slider itself
    tinted = ((shot[:, :, 1] > shot[:, :, 0]) & (shot[:, :, 1] > shot[:, :, 2])
              & (shot[:, :, 1] > 60))
    _rows, columns = np.where(tinted)
    assert columns.size, "nothing was drawn at all"

    middle = (columns.min() + columns.max()) / 2
    wanted = (room["left"] + room["sliderLeft"]) / 2
    whole = (room["left"] + room["right"]) / 2
    assert abs(middle - wanted) < NEAR_ENOUGH, (
        f"the picture's middle is at {middle:.0f}. The room beside the slider "
        f"has its middle at {wanted:.0f}, and the whole canvas at {whole:.0f} "
        "-- so the picture is still being centred behind the slider"
    )
