"""Pixels must actually arrive on screen, not merely into the engine.

There are two quite different questions here, and for a long time only the first
was being asked.

The first is whether the data reached the graphics card. Neuroglancer reports,
per layer, how many pieces of image the current view needs and how many it has,
and that is a useful thing to know: it separates a volume that failed to load
from one that loaded.

The second is whether anything was *drawn*. It turns out the first question can
be answered yes while the panel shows nothing at all — which is precisely what
happened. Every piece of image arrived, the engine was satisfied, and the viewer
showed a flat grey rectangle, because the magnification had been settled before
the images had said how big they were and the specimen was being drawn about a
ten-thousandth of a pixel wide. Nothing in three hundred tests noticed, because
nothing looked at the picture.

So these tests look at the picture. The last one deliberately breaks it again, to
prove the looking works.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from pixels import assert_something_was_drawn, colour_spread, image_middle

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


def test_the_demo_volume_reaches_the_graphics_card(viewer_page):
    progress = viewer_page.evaluate(_PROGRESS)
    assert progress["loadError"] is None
    assert progress["layers"] >= 1
    assert progress["canvasHeight"] > 0
    assert progress["available"] > 0, "no image chunks reached the GPU"
    assert progress["available"] >= progress["needed"]


def test_the_demo_volume_is_actually_drawn(viewer_page):
    """The panel has a picture in it, not just a background."""
    assert_something_was_drawn(viewer_page, "the slice view")


# What the engine says about the switch to the volume view: how many drawing layers
# it is running, and how much of what they need has arrived. Both halves are needed.
#
# Switching to 3-D does not replace the drawing layers, it *adds* to them: the demo
# has eleven while showing slices and fourteen while showing a volume, one extra for
# each image on screen. So asking only "has everything arrived?" the instant after the
# click would be answered by the slice layers, which are still loaded and still
# satisfied, and the test would photograph the panel before the volume existed.
# Waiting for the count to grow first is what makes the second half mean the volume.
_RENDER_LAYERS = """() => {
  let layers = 0;
  for (const m of window.zmartViewer.layerManager.managedLayers)
    for (const _ of (m.layer?.renderLayers) || []) layers += 1;
  return layers;
}"""

_VOLUME_READY = """(before) => {
  let layers = 0, needed = 0, available = 0;
  for (const m of window.zmartViewer.layerManager.managedLayers)
    for (const rl of (m.layer?.renderLayers) || []) {
      layers += 1;
      const p = rl.layerChunkProgressInfo;
      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
    }
  return layers > before && available > 0 && available >= needed;
}"""


def test_the_volume_view_is_actually_drawn(viewer_page):
    """The same, for the 3-D view, which had the same fault for the same reason.

    Its background is black rather than grey, so a failure here reads as an empty
    black panel — indistinguishable by eye from a specimen that simply has
    nothing in view, which is why it is worth a test of its own.

    The waiting here is worth a word, because it used to be a fixed four seconds
    and that was the wrong shape of promise. Four seconds is far longer than this
    needs on a quiet machine — the volume is ready in about a quarter of a second —
    and not necessarily long enough on a busy one, so the test was slow when it
    passed and untrustworthy when it failed. It now waits for the engine's own
    account of what it has loaded, which is the same thing the timelapse fixture
    waits for, and then looks at the picture. That takes as long as it takes.
    """
    before = viewer_page.evaluate(_RENDER_LAYERS)
    viewer_page.click("text=3D")
    viewer_page.wait_for_function(_VOLUME_READY, arg=before, timeout=60_000)
    assert_something_was_drawn(viewer_page, "the volume view")


def test_a_blank_panel_would_be_noticed(viewer_page):
    """The positive control: prove the check above can fail.

    A test that asserts "something is on screen" is only worth having if it would
    notice when nothing is. So this reproduces the original fault exactly — it
    sets the magnification to the value the engine used to settle on before it
    knew how big a voxel was, one metre to a pixel — and checks that the panel
    goes blank *and* that our measurement says so.

    Without this, the test above could quietly stop working (by measuring our own
    buttons, say, instead of the image) and nobody would find out.
    """
    before = colour_spread(image_middle(viewer_page))
    assert before["distinct"] > 2, f"nothing was drawn to begin with: {before}"

    # 1 / 3.5e-7 is one metre per screen pixel, expressed in voxels of the demo
    # volume: the exact magnification the fault produced.
    viewer_page.evaluate("() => { window.zmartViewer.navigationState.zoomFactor.value = 1/3.5e-7; }")
    viewer_page.wait_for_timeout(2500)

    blanked = colour_spread(image_middle(viewer_page))
    assert blanked["distinct"] <= 2, f"the panel should have gone blank, but: {blanked}"
    assert blanked["dominant_fraction"] > 0.99
    with pytest.raises(AssertionError):
        assert_something_was_drawn(viewer_page)


def test_the_shipped_check_script_still_passes(viz_root, built_dist):
    """Exit 0 = rendered, 1 = did not, 2 = could not run here."""
    result = subprocess.run(
        [sys.executable, "tests/browsercheck.py"],
        cwd=viz_root,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode == 2:
        pytest.skip(f"render check could not run: {result.stdout.strip()[-200:]}")
    assert result.returncode == 0, result.stdout
    assert "RESULT: PASS" in result.stdout
