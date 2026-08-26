"""Pressing 3D on flat data shows what was already there.

A dataset of one plane has no depth to look into, so the volume view has
nothing to add: what it draws is the same picture from the same place. If it
arrives at a different size, or somewhere else on screen, the operator has to
find their specimen again every time they press the button -- and, worse, has
no way to tell whether what they are now looking at is the same thing.

It does not have to be pixel-perfect. The volume is drawn with a perspective
camera and the flat view is not, so the two arithmetics differ slightly and
always will; the operator asked for the same size and the same place, roughly
(2026-08-22), and explicitly did NOT ask for the volume to be drawn without
perspective. A dataset with real depth is a different matter entirely: seen
from an angle it cannot look like a slice, and nothing here asks it to.

The specimen is a bright block on black rather than a gradient, so that its
edges are equally crisp in both views. A gradient's dim end fades below any
threshold, and it fades by a different amount in the volume -- which makes
the two pictures look different sizes when they are not.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
import zarr
from PIL import Image
from server import make_server

# How far apart the two views may be before an operator would notice. A few
# per cent of the size, and a handful of pixels of the place: the difference
# between "the same picture" and "the picture jumped".
SAME_SIZE_WITHIN = 0.05
SAME_PLACE_WITHIN = 20


def _one_bright_plane(path):
    """A single-plane image: a bright block with black around it."""
    path.mkdir(parents=True)
    data = np.zeros((1, 1, 96, 96), "uint16")
    data[0, 0, 16:80, 16:80] = 5000
    zarr.open_group(str(path), mode="w", zarr_format=2).create_array(
        "0", shape=data.shape, chunks=(1, 1, 96, 96), dtype="uint16")[:] = data
    (path / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "c", "type": "channel"},
                     {"name": "z", "type": "space", "unit": "micrometer"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0, 0.5, 0.5]}]}],
        }],
        "omero": {"channels": [{
            "label": "ch0", "color": "00FF66",
            "window": {"min": 0, "max": 65535, "start": 500, "end": 5200}}]},
    }), encoding="utf-8")
    return path


@pytest.fixture
def flat_page(browser, built_dist, tmp_path):
    """A viewer showing one plane, framed by the Overview button."""
    data = tmp_path / "flat"
    data.mkdir()
    _one_bright_plane(data / "flat_pos001.ome.zarr")
    server = make_server(port=0, data_dir=data, site_dir=built_dist,
                         store="flat_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_timeout(4000)
        page.get_by_role("button", name="Overview", exact=True).click()
        page.wait_for_timeout(2500)
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _where_the_block_is(page, saved):
    """The block's box on screen, with the viewer's own controls masked out.

    The toggle, the scale bar and the depth slider are drawn over the canvas
    and would otherwise be measured as though they were specimen.
    """
    import io

    page.screenshot(path=str(saved),
                    clip={"x": 0, "y": 0, "width": 1020, "height": 1000})
    shot = np.array(Image.open(saved).convert("RGB")).astype(int)
    shot[:60, :260] = 0      # the 2D / 3D / Overview toggle
    shot[:45, 860:] = 0      # the scale bar
    shot[:, 955:] = 0        # the depth slider
    tinted = ((shot[:, :, 1] > shot[:, :, 0]) & (shot[:, :, 1] > shot[:, :, 2])
              & (shot[:, :, 1] > 60))
    rows, columns = np.where(tinted)
    assert rows.size, f"nothing was drawn at all in {saved.name}"
    return {
        "width": int(columns.max() - columns.min() + 1),
        "height": int(rows.max() - rows.min() + 1),
        "centre": ((columns.min() + columns.max()) / 2,
                   (rows.min() + rows.max()) / 2),
    }


def test_pressing_three_d_on_one_plane_shows_the_same_picture(flat_page, tmp_path):
    """Same size, same place."""
    page = flat_page
    flat = _where_the_block_is(page, tmp_path / "1_flat.png")
    page.click("text=3D")
    page.wait_for_timeout(4000)
    volume = _where_the_block_is(page, tmp_path / "2_volume.png")

    for side in ("width", "height"):
        apart = abs(volume[side] - flat[side]) / flat[side]
        assert apart < SAME_SIZE_WITHIN, (
            f"the block is {flat[side]} pixels {side} in the flat view and "
            f"{volume[side]} in the volume, {apart:.0%} apart -- pressing 3D "
            "resized the specimen"
        )
    moved = max(abs(volume["centre"][0] - flat["centre"][0]),
                abs(volume["centre"][1] - flat["centre"][1]))
    assert moved < SAME_PLACE_WITHIN, (
        f"the block sits at {flat['centre']} in the flat view and "
        f"{volume['centre']} in the volume, {moved:.0f} pixels away -- "
        "pressing 3D moved the specimen"
    )


def test_the_settings_come_back_untouched_from_the_volume(flat_page):
    """Brightness, contrast and where you are survive the round trip.

    Switching rebuilds the shaders, which is exactly when a window can be
    quietly lost. What an operator set has to still be set when they come
    back.
    """
    page = flat_page
    reading = """() => {
      const v = window.zmartViewer;
      const layer = v.state.toJSON().layers[0];
      return {
        position: Array.from(v.navigationState.position.value)
          .map((one) => Math.round(one * 100) / 100),
        zoom: Math.round(v.navigationState.zoomFactor.value * 1e6) / 1e6,
        window: (layer.shaderControls || {}).normalized.range,
        opacity: layer.opacity ?? 1,
      };
    }"""
    page.locator("[aria-label='min ch0']").evaluate("""(slider) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype, 'value').set;
      setter.call(slider, String(Number(slider.min) + (Number(slider.max) - Number(slider.min)) * 0.3));
      slider.dispatchEvent(new Event('input', { bubbles: true }));
      slider.dispatchEvent(new Event('change', { bubbles: true }));
    }""")
    page.wait_for_timeout(800)
    before = page.evaluate(reading)
    page.click("text=3D")
    page.wait_for_timeout(3000)
    page.click("text=2D")
    page.wait_for_timeout(3000)
    assert page.evaluate(reading) == before, (
        "something the operator set did not survive going to the volume and "
        f"back: was {before}, now {page.evaluate(reading)}"
    )
