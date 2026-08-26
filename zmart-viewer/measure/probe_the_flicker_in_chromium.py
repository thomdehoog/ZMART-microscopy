"""Drive the operator's exact road in headless Chromium and watch every frame.

The road: open the viewer, sequential tab, ``test_stores/test_grid_16``,
Open — sixteen positions landing one after another while the page watches.

This probe watches the picture **once per drawn frame**, by hanging a
recorder off ``requestAnimationFrame`` inside the page. That is the lesson
of 2026-08-23, learned the hard way: an earlier version of this probe
sampled ten times a second and reported three clean runs while the picture
was going fully black for 100–300 ms at every landing — the flash simply
fell between its samples. A frame is the honest smallest unit: a frame that
was drawn was seen, and a frame that was not drawn was not.

Run it from ``zmart-viewer/`` with the frontend built (``npm --prefix
frontend run build``)::

    python probe_the_flicker_in_chromium.py

It opens its own server on a free port, drives the road, and prints every
downward step the picture ever took. A healthy run prints none: the picture
only grows as the positions land. It exits 0 when clean and 1 when it saw
the picture lose ground, so it can stand in a script.
"""

import sys
import threading
from pathlib import Path

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "app" / "server"))
sys.path.insert(0, str(_VIZ / "tests"))

from server import make_server            # noqa: E402
from conftest import find_a_chromium      # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# Reading pixels back out of a WebGL surface only works when the browser is
# told, before the page runs, to keep the drawn frame around. Same override,
# for the same reason, as in tests/test_the_screen_never_goes_black.py.
_KEEP_THE_DRAWN_PIXELS_READABLE = """(() => {
  const makeContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (kind, asked) {
    if (kind === 'webgl2' || kind === 'webgl' || kind === 'experimental-webgl') {
      asked = Object.assign({}, asked || {}, { preserveDrawingBuffer: true });
    }
    return makeContext.call(this, kind, asked);
  };
})();"""

# The per-frame recorder: how much of the middle of the picture is lit, how
# many drawing layers the engine holds, and where the camera is, written down
# once per drawn frame. The camera matters because the viewer deliberately
# flies to a freshly opened acquisition (see lookAtWhatOpened in engine.js),
# and while it flies the lit fraction legitimately plunges — the specimen is
# moving out from under the measured middle. Only a drop with the camera
# holding still is flicker.
_WATCH_EVERY_FRAME = """([grid, middleShare, litFloor]) => {
  const drawn = document.querySelector('canvas');
  if (!drawn) return { started: false };
  const small = document.createElement('canvas');
  small.width = grid; small.height = grid;
  const flat = small.getContext('2d', { willReadFrequently: true });
  const watch = { frames: [], stop: false };
  window.zmartFlickerWatch = watch;
  const onFrame = (t) => {
    if (watch.stop) return;
    let lit = null;
    try {
      const margin = (1 - middleShare) / 2;
      flat.fillStyle = '#000000';
      flat.fillRect(0, 0, grid, grid);
      flat.drawImage(drawn,
        drawn.width * margin, drawn.height * margin,
        drawn.width * middleShare, drawn.height * middleShare,
        0, 0, grid, grid);
      const seen = flat.getImageData(0, 0, grid, grid).data;
      let counted = 0;
      for (let at = 0; at < seen.length; at += 4) {
        if (Math.max(seen[at], seen[at + 1], seen[at + 2]) > litFloor) counted += 1;
      }
      lit = counted / (grid * grid);
    } catch (problem) { /* an unreadable frame is recorded as null */ }
    let layers = 0;
    let camera = null;
    const viewer = window.zmartViewer;
    if (viewer) {
      for (const managed of viewer.layerManager.managedLayers) {
        for (const rl of (managed.layer && managed.layer.renderLayers) || []) {
          if (rl.layerChunkProgressInfo) layers += 1;
        }
      }
      camera = [...viewer.navigationState.position.value,
                viewer.navigationState.zoomFactor.value].join(",");
    }
    watch.frames.push({ t, lit, layers, camera });
    requestAnimationFrame(onFrame);
  };
  requestAnimationFrame(onFrame);
  return { started: true };
}"""

B = _VIZ / "testdata"
server = make_server(0, store="demo.zarr")
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

with sync_playwright() as p:
    already_here = find_a_chromium()
    browser = p.chromium.launch(
        executable_path=str(already_here) if already_here else None,
    )
    page = browser.new_page(viewport={"width": 1200, "height": 800})
    page.add_init_script(_KEEP_THE_DRAWN_PIXELS_READABLE)
    page.goto(f"http://127.0.0.1:{port}", wait_until="networkidle")
    page.wait_for_timeout(3500)
    # The operator's exact road: sequential tab, the grid, Open.
    page.get_by_role("button", name="open images").click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="open positions sequentially").click()
    page.wait_for_timeout(400)
    page.get_by_label("folder path").fill(str(B / "test_stores" / "test_grid_16"))
    page.keyboard.press("Enter")
    page.wait_for_timeout(600)
    page.get_by_role("button", name="open as a live run").click()
    page.get_by_role("dialog", name="load data").wait_for(state="detached")
    # Let the first position land before watching, so arrival is never
    # mistaken for flicker -- the ghost this file once chased.
    page.wait_for_timeout(3000)
    page.evaluate(_WATCH_EVERY_FRAME, [96, 0.5, 40])
    # Sixteen landings at roughly two and a half seconds each, plus slack.
    page.wait_for_timeout(45_000)
    recording = page.evaluate(
        "() => { const w = window.zmartFlickerWatch; w.stop = true; return w.frames; }")
    browser.close()
server.shutdown()

frames = [one for one in recording if one["lit"] is not None]
lits = [one["lit"] for one in frames]
print(f"{len(frames)} frames watched; lit went {lits[0]:.2f} -> {lits[-1]:.2f} "
      f"(min {min(lits):.2f}, max {max(lits):.2f})")

# The verdicts: with the camera holding still, the picture must only ever
# grow while positions land, and the engine must never tear its drawing
# layers down. A drop while the camera moved is the view being steered --
# the deliberate flight to a freshly opened acquisition, a jump to the
# first plane, or an operator's own pan -- and is not counted. The camera
# has to have been still for a couple of frames BEFORE the drop as well,
# because the recorder reads the picture with a one-frame lag (see the
# note in test_the_screen_never_goes_black.py): the dark frame a camera
# jump causes is written down one frame after the jump itself, when the
# two poses already read as equal.
def _camera_was_still(at: int, span: int = 3) -> bool:
    poses = {frames[i]["camera"] for i in range(max(0, at - span), at + 1)}
    return len(poses) == 1

steps = [(a, b) for at, (a, b) in enumerate(zip(frames, frames[1:]))
         if b["lit"] < a["lit"] - 0.05 and _camera_was_still(at + 1)]
teardowns = [(a, b) for a, b in zip(frames, frames[1:]) if b["layers"] < a["layers"]]
for a, b in steps[:20]:
    print(f"  DOWNWARD STEP at t={b['t']:.0f} ms: {a['lit']:.2f} -> {b['lit']:.2f} lit")
for a, b in teardowns[:20]:
    print(f"  LAYERS TORN DOWN at t={b['t']:.0f} ms: {a['layers']} -> {b['layers']}")
if steps or teardowns:
    print("THE PICTURE FLICKERED.")
    sys.exit(1)
print("clean: the picture only grew, and no drawing layer was torn down")
