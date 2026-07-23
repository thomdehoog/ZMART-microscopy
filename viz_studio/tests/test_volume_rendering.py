"""Volume rendering is on and reaching the engine, not just requested.

``volumeRendering`` is a layer property neuroglancer accepts silently: a
misspelling, or a shader that emits no alpha, leaves the 3-D panel showing the
usual cross-section planes and nothing complains. These check the engine's own
state, and that the volume actually draws.
"""

from __future__ import annotations

import threading

import pytest
from server import make_server

_LAYER_STATE = """() => {
  const v = window.zmartViewer;
  const managed = v.layerManager.managedLayers[0];
  const layer = managed.layer;
  return {
    mode: layer.volumeRenderingMode ? layer.volumeRenderingMode.value : null,
    shader: (layer.fragmentMain && layer.fragmentMain.value) || '',
    configVolumetric: window.zmartConfig.layers[0].volumetric,
  };
}"""


@pytest.fixture
def volumetric_page(browser, built_dist, demo_store):
    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist, volumetric=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_function(
            "() => window.zmartViewer.layerManager.managedLayers.length > 0", timeout=30_000
        )
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_engine_reports_volume_rendering_on(volumetric_page):
    """Mode 1 is ON in neuroglancer's enum; 0 would mean the flag never landed."""
    state = volumetric_page.evaluate(_LAYER_STATE)
    assert state["configVolumetric"] is True
    assert state["mode"] == 1


def test_the_volumetric_shader_emits_alpha(volumetric_page):
    """Without alpha the volume renders as an opaque block."""
    assert "emitRGBA" in volumetric_page.evaluate(_LAYER_STATE)["shader"]


def test_sections_stay_the_default(viewer_page):
    """The flat viewer must be unaffected — volume rendering is opt-in."""
    state = viewer_page.evaluate(_LAYER_STATE)
    assert state["configVolumetric"] is False
    assert state["mode"] == 0


def test_the_volume_still_renders_its_chunks(volumetric_page):
    volumetric_page.wait_for_function(
        """() => {
          const v = window.zmartViewer;
          let available = 0;
          for (const m of v.layerManager.managedLayers)
            for (const rl of (m.layer && m.layer.renderLayers) || []) {
              const p = rl.layerChunkProgressInfo;
              if (p) available += p.numVisibleChunksAvailable;
            }
          return available > 0;
        }""",
        timeout=60_000,
    )
