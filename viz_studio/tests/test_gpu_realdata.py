"""Tests for a real machine: a graphics card, and a real OME-Zarr store.

The rest of the suite runs anywhere, on software rendering and synthetic data.
These two things it cannot honestly check on the sandbox used for the other
tests — that there is a GPU actually drawing the volume, and that a real
acquisition opens and streams — so they live here and **skip cleanly** where
those are absent. On the microscope PC (or any workstation with a graphics card
and a store to point at) they come alive. See ``TESTING.md`` for how to run
them.

- The GPU test skips when WebGL is running in software (no card present).
- The real-data tests skip unless ``ZMART_TEST_STORE`` names an OME-Zarr store.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

import pytest

from server import make_server
from stores import discover

REAL_STORE_ENV = "ZMART_TEST_STORE"

# Substrings that mark a *software* WebGL backend rather than a real GPU.
_SOFTWARE_RENDERERS = ("swiftshader", "llvmpipe", "software", "microsoft basic")

# Ask the page which renderer WebGL is actually using.
_RENDERER_JS = """() => {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl2') || c.getContext('webgl');
  if (!gl) return null;
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
}"""

# Per-layer chunk progress, the same signal the demo acceptance test uses:
# "chunks available, and demand met" is what tells a real render from a page
# that merely loaded.
_PROGRESS_JS = """() => {
  const v = window.zmartViewer;
  let needed = 0, available = 0, layers = 0, loadError = null;
  for (const managed of v.layerManager.managedLayers) {
    layers += 1;
    const ds = managed.layer && managed.layer.dataSources && managed.layer.dataSources[0];
    if (ds && ds.loadState && ds.loadState.error) {
      loadError = String(ds.loadState.error.message || ds.loadState.error);
    }
    for (const rl of (managed.layer && managed.layer.renderLayers) || []) {
      const p = rl.layerChunkProgressInfo;
      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
    }
  }
  return { layers, needed, available, loadError };
}"""


# --------------------------------------------------------------------------
# GPU acceleration   (gpu_browser fixture lives in conftest.py)
# --------------------------------------------------------------------------

def test_webgl_is_hardware_accelerated(gpu_browser):
    """WebGL is driven by a real GPU, not a software rasteriser.

    Skips (rather than fails) on a machine without a card, so this same test is
    quiet in CI and meaningful on the microscope PC.
    """
    page = gpu_browser.new_page()
    try:
        page.set_content("<canvas></canvas>")
        renderer = page.evaluate(_RENDERER_JS)
    finally:
        page.close()
    if not renderer:
        pytest.skip("WebGL is unavailable in this browser")
    if any(s in renderer.lower() for s in _SOFTWARE_RENDERERS):
        pytest.skip(f"software WebGL renderer ({renderer}) — no GPU on this machine")
    print(f"\nWebGL renderer: {renderer}")   # visible with `pytest -s`
    assert renderer, "the GPU reported an empty renderer string"


# --------------------------------------------------------------------------
# A real OME-Zarr store
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_store() -> Path:
    """The store named by ``ZMART_TEST_STORE``, or skip if it is not set."""
    raw = os.environ.get(REAL_STORE_ENV)
    if not raw:
        pytest.skip(f"set {REAL_STORE_ENV}=/path/to/acquisition.ome.zarr to run the real-data tests")
    path = Path(raw)
    if not path.exists():
        pytest.skip(f"{REAL_STORE_ENV} points at a path that does not exist: {path}")
    return path


@pytest.fixture(scope="module")
def real_server(real_store: Path, built_dist: Path):
    """The viewer's server over the real store, on a free port."""
    parent, names = discover(real_store)
    if not names:
        pytest.skip(f"no OME-Zarr stores found under {real_store}")
    server = make_server(port=0, data_dir=parent, site_dir=built_dist, store=names)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", names
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_real_store_channels_become_layers(real_server):
    """Every channel found in the store, and only those, becomes a layer."""
    url, names = real_server
    host = urlparse(url)
    conn = http.client.HTTPConnection(host.hostname, host.port, timeout=15)
    try:
        conn.request("GET", "/api/config")
        config = json.loads(conn.getresponse().read())
    finally:
        conn.close()
    assert len(config["layers"]) == len(names)
    for layer in config["layers"]:
        assert layer["window"]["low"] < layer["window"]["high"]   # a usable window, measured from the data


def test_real_store_renders(real_server, browser):
    """The real acquisition streams and actually reaches the renderer.

    Uses the shared (software-GL) browser so it proves *streaming and rendering*
    on any machine that has the data; whether a GPU accelerates it is the
    separate test above. Real data streams over disk or the network, so the
    wait is generous.
    """
    url, _ = real_server
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(
            "() => { const p = (%s)(); return p.available > 0 && p.available >= p.needed; }" % _PROGRESS_JS.strip(),
            timeout=180_000,
        )
        progress = page.evaluate(_PROGRESS_JS)
    finally:
        page.close()
    assert progress["loadError"] is None, progress["loadError"]
    assert progress["layers"] >= 1
    assert progress["available"] > 0, "no image chunks reached the renderer"
