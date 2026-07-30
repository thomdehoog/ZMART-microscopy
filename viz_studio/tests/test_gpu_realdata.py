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
from stores import declared_channels, discover

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

# Draw something with WebGL 2 and read back what was drawn.
#
# This is what makes the test below able to fail. Asking the card for its name
# only proves a name was reported; it says nothing about whether the card can
# actually draw, and a machine whose driver is broken or whose WebGL 2 has been
# blocked answers that question just as cheerfully as a healthy one. Clearing to
# a known colour and reading the pixel back proves the whole path works, and
# WebGL 2 specifically, which is what the engine requires.
_DRAWS_JS = """() => {
  const c = document.createElement('canvas');
  c.width = 8; c.height = 8;
  const gl = c.getContext('webgl2');
  if (!gl) return {ok: false, why: 'WebGL 2 is not available'};
  gl.clearColor(0, 1, 0, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  const pixel = new Uint8Array(4);
  gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
  if (gl.isContextLost()) return {ok: false, why: 'the WebGL context was lost'};
  return {ok: true, pixel: Array.from(pixel)};
}"""


def test_webgl_is_hardware_accelerated(gpu_browser):
    """WebGL is driven by a real GPU, and that GPU can actually draw.

    Skips (rather than fails) on a machine without a card, so this same test is
    quiet in CI and meaningful on the microscope PC.

    The second half is what makes this worth running. It used to skip when the
    renderer was missing and then assert that the renderer was present — so it
    could only skip or pass, whatever the machine did, while ``TESTING.md``
    advertised it as the clearest single check that the GPU is in use. Now the
    card is asked to draw and the result is read back, which a card that reports a
    name but cannot render will fail.
    """
    page = gpu_browser.new_page()
    try:
        page.set_content("<canvas></canvas>")
        renderer = page.evaluate(_RENDERER_JS)
        if not renderer:
            pytest.skip("WebGL is unavailable in this browser")
        if any(s in renderer.lower() for s in _SOFTWARE_RENDERERS):
            pytest.skip(f"software WebGL renderer ({renderer}) — no GPU on this machine")
        drew = page.evaluate(_DRAWS_JS)
    finally:
        page.close()

    print(f"\nWebGL renderer: {renderer}")   # visible with `pytest -s`
    assert drew["ok"], f"{renderer} reports a GPU but cannot draw: {drew.get('why')}"
    assert drew["pixel"] == [0, 255, 0, 255], (
        f"{renderer} drew {drew['pixel']} where a plain green fill was asked for, "
        "so what reaches the screen is not what the viewer asked to be drawn"
    )


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
        yield f"http://127.0.0.1:{server.server_address[1]}", parent, names
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_real_store_channels_become_layers(real_server):
    """Every channel found in the store, and only those, becomes a layer.

    A layer is a *channel*, not a store, and the two are only the same number
    when each store holds one channel — which is what a mesoSPIM transfer writes
    and what this test used to assume. A fused acquisition puts its channels on a
    ``c`` axis inside one store, so one store there is two layers.
    """
    url, parent, names = real_server
    expected = sum(len(declared_channels(parent / name) or [None]) for name in names)
    host = urlparse(url)
    conn = http.client.HTTPConnection(host.hostname, host.port, timeout=15)
    try:
        conn.request("GET", "/api/config")
        config = json.loads(conn.getresponse().read())
    finally:
        conn.close()
    assert len(config["layers"]) == expected
    for layer in config["layers"]:
        assert layer["window"]["low"] < layer["window"]["high"]   # a usable window, measured from the data


def test_real_store_renders(real_server, browser):
    """The real acquisition streams and actually reaches the renderer.

    Uses the shared (software-GL) browser so it proves *streaming and rendering*
    on any machine that has the data; whether a GPU accelerates it is the
    separate test above. Real data streams over disk or the network, so the
    wait is generous.
    """
    url, _, _ = real_server
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
