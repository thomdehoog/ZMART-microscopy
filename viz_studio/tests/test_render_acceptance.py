"""Pixels must actually arrive, not merely the page load.

Two angles on the same guarantee. The first asserts it in-process against the
live viewer: neuroglancer reports, per layer, how many image chunks the current
view needs and how many it has, and "available and demand met" is what separates
a rendered volume from the correct-looking grey rectangle an early build showed.
The second runs ``backend/browsercheck.py`` exactly as the README tells an
operator to, so the shipped script itself stays working.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_PROGRESS = """() => {
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
  const canvas = document.querySelector('canvas');
  return { layers, needed, available, loadError, canvasHeight: canvas ? canvas.height : 0 };
}"""


def test_the_demo_volume_renders(viewer_page):
    progress = viewer_page.evaluate(_PROGRESS)
    assert progress["loadError"] is None
    assert progress["layers"] >= 1
    assert progress["canvasHeight"] > 0
    assert progress["available"] > 0, "no image chunks reached the GPU"
    assert progress["available"] >= progress["needed"]


def test_the_shipped_check_script_still_passes(viz_root, built_dist):
    """Exit 0 = rendered, 1 = did not, 2 = could not run here."""
    result = subprocess.run(
        [sys.executable, "backend/browsercheck.py"],
        cwd=viz_root,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode == 2:
        pytest.skip(f"render check could not run: {result.stdout.strip()[-200:]}")
    assert result.returncode == 0, result.stdout
    assert "RESULT: PASS" in result.stdout
