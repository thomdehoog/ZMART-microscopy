"""The layer list: napari's shape, driving neuroglancer's state.

Hiding a layer and recolouring it are the two things anyone does within seconds
of opening a multi-channel acquisition. Both are silently ignorable by the
engine if wired wrongly -- a layer can be marked hidden in our own state and
still draw -- so these assert what the engine ended up with, not what the panel
believes.
"""

from __future__ import annotations

import threading

import pytest
from server import make_server

_ENGINE_LAYERS = """() => window.zmartViewer.state.toJSON().layers.map(l => ({
  name: l.name,
  visible: l.visible !== false,
  opacity: l.opacity ?? 1,
  shader: l.shader || '',
}))"""


@pytest.fixture
def two_channel_page(browser, built_dist, tmp_path_factory):
    """Two stores, so colours are assigned and the list has something to show."""
    data = tmp_path_factory.mktemp("channels")
    from demo_data import write_demo_zarr

    for name in ("Tile0_Ch488_FltEmpty.ome.zarr", "Tile0_Ch647_FltEmpty.ome.zarr"):
        write_demo_zarr(data / name)

    server = make_server(
        port=0,
        data_dir=data,
        site_dir=built_dist,
        store=["Tile0_Ch488_FltEmpty.ome.zarr", "Tile0_Ch647_FltEmpty.ome.zarr"],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_function(
            "() => window.zmartViewer.layerManager.managedLayers.length === 2", timeout=30_000
        )
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_panel_lists_every_layer(two_channel_page):
    assert two_channel_page.locator("text=Tile0_Ch488").count() == 1
    assert two_channel_page.locator("text=Tile0_Ch647").count() == 1


def test_channels_arrive_green_and_magenta(two_channel_page):
    shaders = [layer["shader"] for layer in two_channel_page.evaluate(_ENGINE_LAYERS)]
    assert "vec3(0, 1, 0.4)" in shaders[0], "488 should be green"
    assert "vec3(1, 0.2, 1)" in shaders[1], "647 should be magenta"


def test_hiding_a_layer_hides_it_in_the_engine(two_channel_page):
    two_channel_page.click("[aria-label='toggle Tile0_Ch488']")
    two_channel_page.wait_for_timeout(800)
    layers = two_channel_page.evaluate(_ENGINE_LAYERS)
    assert layers[0]["visible"] is False
    assert layers[1]["visible"] is True, "hiding one layer must not affect the other"


def test_showing_it_again_restores_it(two_channel_page):
    two_channel_page.click("[aria-label='toggle Tile0_Ch488']")
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("[aria-label='toggle Tile0_Ch488']")
    two_channel_page.wait_for_timeout(800)
    assert two_channel_page.evaluate(_ENGINE_LAYERS)[0]["visible"] is True


def test_recolouring_a_layer_reaches_the_shader(two_channel_page):
    two_channel_page.click("[aria-label='colour Tile0_Ch488']")
    two_channel_page.click("[aria-label='cyan for Tile0_Ch488']")
    two_channel_page.wait_for_timeout(800)
    shader = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert "vec3(0.2, 0.8, 1)" in shader


def test_colour_survives_the_three_d_toggle(two_channel_page):
    """Mode switching rebuilds the shaders; a chosen colour must not be lost."""
    two_channel_page.click("[aria-label='colour Tile0_Ch488']")
    two_channel_page.click("[aria-label='cyan for Tile0_Ch488']")
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("text=3D")
    two_channel_page.wait_for_timeout(1500)
    shader = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert "emitRGBA" in shader
    assert "0.2, 0.8, 1" in shader


def test_visibility_survives_the_three_d_toggle(two_channel_page):
    two_channel_page.click("[aria-label='toggle Tile0_Ch647']")
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("text=3D")
    two_channel_page.wait_for_timeout(1500)
    assert two_channel_page.evaluate(_ENGINE_LAYERS)[1]["visible"] is False


def _set_range(page, label: str, value: float) -> None:
    page.locator(f"[aria-label='{label}']").evaluate(
        """(element, value) => {
          // React tracks controlled input values by installing an own-property
          // setter. Use the platform setter, as a real range-thumb movement
          // does, so the subsequent input event is observed as a change.
          const setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, 'value'
          ).set;
          setter.call(element, String(value));
          element.dispatchEvent(new Event('input', { bubbles: true }));
        }""",
        value,
    )


def test_contrast_handles_rewrite_the_engine_shader(two_channel_page):
    _set_range(two_channel_page, "black Tile0_Ch488", 1200)
    _set_range(two_channel_page, "white Tile0_Ch488", 9000)
    two_channel_page.wait_for_timeout(800)
    shader = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert "range=[1200, 9000]" in shader


def test_contrast_survives_the_three_d_toggle(two_channel_page):
    _set_range(two_channel_page, "black Tile0_Ch488", 1500)
    _set_range(two_channel_page, "white Tile0_Ch488", 8000)
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("text=3D")
    two_channel_page.wait_for_timeout(1500)
    shader = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert "range=[1500, 8000]" in shader
    assert "emitRGBA" in shader


def test_opacity_reaches_the_plane_layer(two_channel_page):
    _set_range(two_channel_page, "opacity Tile0_Ch488", 0.37)
    two_channel_page.wait_for_timeout(800)
    opacity = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["opacity"]
    assert opacity == pytest.approx(0.37)


def test_opacity_survives_the_three_d_toggle(two_channel_page):
    _set_range(two_channel_page, "opacity Tile0_Ch488", 0.42)
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("text=3D")
    two_channel_page.wait_for_timeout(1500)
    shader = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert "default=0.42" in shader
    assert "normalized() * opacity" in shader
