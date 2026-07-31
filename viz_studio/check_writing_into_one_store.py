"""Can a run write straight into one OME-Zarr while the viewer is watching it?

This answers a question about how a smart-microscopy run might lay its data out, and
the answer turns out to be yes with one condition attached. It is worth understanding
before building anything on top of it.

**The question.** Today a run writes one small OME-Zarr per position, and the viewer is
given all of them. Everything that makes a large run heavy is a cost *per store*: the
browser's limit on how many things it will fetch at once, the engine reworking where
everything sits in space each time a store is read, and three drawing layers created for
every position. A single image standing for the whole specimen avoids all of that — one
store, whatever the size of the specimen. Copying a finished folder into one afterwards
would be one way to get there, and it is not the way taken here, because it means reading
every tile and writing several hundred gigabytes out again.

The better way is to have the benefit without the copy: have the run write each tile
straight into its place in a single OME-Zarr that was created empty at the start. Then
the tile is written once rather than twice, and the viewer holds one store from the very
first moment. The measurements in `measure_one_stitched_store.py` say what that is worth:
one store describing about a hundred and thirty-seven gigabytes reaches the screen in 1.4
seconds on 38 requests, where three hundred separate positions — a far smaller specimen —
take 2.4 seconds on 1 125 requests and then draw at a quarter of the rate.

**The catch, and it is a real one.** The drawing engine remembers every piece of image it
has decoded, including the pieces it found to be empty, and there is no time limit on
that memory. So a tile written into a place the viewer has already looked at is simply
not noticed: it keeps showing the emptiness it decided on earlier and never goes back to
the disk. This script demonstrates exactly that — nothing appears, and not one request is
made.

**The condition, which the viewer now handles.** The engine offers a way to be told to
let go of the pieces it has decoded, and the viewer uses it: when a run announces with
``{"wrote_image_in_place": true}``, the viewer drops what it has decoded and fetches
again, and the tile appears. The cost is small and — importantly — does not grow with the
specimen: only the pieces actually on screen are fetched again, which in this script is
nine requests whether the store describes a gigabyte or a terabyte.

**The run has to say so, and only the run can.** That flag is off by default and it has
to be, because for the ordinary layout of one store per position it is not true — a
viewer letting go on every announcement would spend a long run refetching image it
already had, which is exactly the waste all of this exists to avoid. Nothing on disk
distinguishes the two cases: the store is the same store, the same size, with the same
name. So the writer, which is the only one that knows, says which it did.

This script runs the experiment the other way round — it announces *without* the flag
first, to show what happens when nothing is said, and then asks the sources to let go
directly to show that the mechanism is what makes the difference.

Run it with::

    python check_writing_into_one_store.py

It needs the viewer page built and a browser, the same as the tests. It writes a
throwaway store under a temporary folder and removes it afterwards.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(VIZ / "backend"))
sys.path.insert(0, str(VIZ / "tests"))

from server import make_server  # noqa: E402

SIDE, CHUNK, LEVELS = 2048, 512, 3
VOXEL_UM = (2.0, 0.35, 0.35)


def plane(value_from: int) -> bytes:
    import numpy as np

    y, x = np.mgrid[0:CHUNK, 0:CHUNK]
    return (value_from + (y + x) * 2).astype("<u2").tobytes()


def write_store(store: Path, *, filled: bool) -> None:
    store.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    datasets = []
    for level in range(LEVELS):
        side = SIDE >> level
        folder = store / str(level)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".zarray").write_text(
            json.dumps({
                "zarr_format": 2,
                "shape": [1, side, side, side],
                "chunks": [1, 1, CHUNK, CHUNK],
                "dtype": "<u2", "compressor": None, "fill_value": 0,
                "order": "C", "filters": None, "dimension_separator": ".",
            }), encoding="utf-8")
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, VOXEL_UM[0] * 2**level,
                                            VOXEL_UM[1] * 2**level,
                                            VOXEL_UM[2] * 2**level]}],
        })
        if filled:
            fill_middle(store, level)
    (store / ".zattrs").write_text(
        json.dumps({
            "multiscales": [{
                "version": "0.4",
                "axes": [
                    {"name": "c", "type": "channel"},
                    {"name": "z", "type": "space", "unit": "micrometer"},
                    {"name": "y", "type": "space", "unit": "micrometer"},
                    {"name": "x", "type": "space", "unit": "micrometer"},
                ],
                "datasets": datasets,
            }],
            "omero": {"channels": [{"label": "ch0", "color": "FFFFFF",
                                    "window": {"min": 0, "max": 65535,
                                               "start": 0, "end": 4000}}]},
        }), encoding="utf-8")


def fill_middle(store: Path, level: int) -> None:
    """Write the pieces under the middle of the view, which is where the viewer looks."""
    side = SIDE >> level
    folder = store / str(level)
    middle = side // 2
    across = max(1, side // CHUNK)
    centre = across // 2
    for row in range(max(0, centre - 1), min(across, centre + 2)):
        for column in range(max(0, centre - 1), min(across, centre + 2)):
            (folder / f"0.{middle}.{row}.{column}").write_bytes(plane(600))


ANNOUNCE = """async () => {
  const response = await fetch('/api/announce', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: 'a tile was written'}),
  });
  return (await response.json()).told;
}"""


def run() -> None:
    from playwright.sync_api import sync_playwright
    from pixels import colour_spread, image_middle

    root = Path(tempfile.mkdtemp(prefix="zmart-latechunk-"))
    try:
        store = root / "overview_whole.ome.zarr"
        write_store(store, filled=False)
        # Live, as during a run: nothing is kept by the browser's own cache, so anything
        # that fails to appear failed inside the engine rather than in the browser.
        httpd = make_server(port=0, data_dir=root, site_dir=VIZ / "frontend" / "dist",
                            store=["overview_whole.ome.zarr"], live=True)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
            page = browser.new_page(viewport={"width": 1100, "height": 800})
            chunks: list[str] = []
            page.on("request", lambda r: chunks.append(r.url)
                    if "/data/" in r.url and not r.url.endswith((".zarray", ".zattrs", ".zgroup"))
                    else None)
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
                page.wait_for_timeout(4000)
                empty = colour_spread(image_middle(page))
                asked_before = len(chunks)
                print(f"before the tile is written: {empty}")
                print(f"  pieces asked for so far: {asked_before}")

                # The run writes a tile into the store that is already open, and says so.
                for level in range(LEVELS):
                    fill_middle(store, level)
                told = page.evaluate(ANNOUNCE)
                print(f"  announced to {told} listener(s)")

                page.wait_for_timeout(6000)
                after = colour_spread(image_middle(page))
                print(f"after the tile is written:  {after}")
                print(f"  pieces asked for since:  {len(chunks) - asked_before}")

                appeared = after["distinct"] > 2 and after["dominant_fraction"] < 0.99
                print()
                if appeared:
                    print("The piece written later DID appear on its own.")
                    return
                print("The piece written later did NOT appear on its own: the engine "
                      "answers from what it already decided was empty.")

                # Now ask the engine to let go of the pieces it has decoded, which is a
                # thing it offers -- ChunkSource.invalidateCache tells the worker holding
                # them to drop them. If the tile appears after this, the mechanism for a
                # run writing into one open store exists and is supported.
                asked_before = len(chunks)
                dropped = page.evaluate("""() => {
                  const objects = window.zmartViewer.chunkManager.rpc.objects;
                  let dropped = 0;
                  for (const [, held] of objects) {
                    if (held && typeof held.invalidateCache === 'function') {
                      held.invalidateCache();
                      dropped += 1;
                    }
                  }
                  return dropped;
                }""")
                print(f"\nasked {dropped} source(s) to let go of what they had decoded")
                page.wait_for_timeout(6000)
                forced = colour_spread(image_middle(page))
                print(f"after letting go:           {forced}")
                print(f"  pieces asked for since:  {len(chunks) - asked_before}")
                print()
                if forced["distinct"] > 2 and forced["dominant_fraction"] < 0.99:
                    print("It appeared. So a run CAN write into one open store, provided "
                          "the viewer is told to let go of the pieces it has decoded when "
                          "the run announces. That is a supported call, not a patch.")
                else:
                    print("Still nothing. Letting go of the decoded pieces is not enough "
                          "on its own, so this needs more thought before the idea can be "
                          "relied on.")
            finally:
                page.close()
                browser.close()
                httpd.shutdown()
                thread.join(timeout=5)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    run()
