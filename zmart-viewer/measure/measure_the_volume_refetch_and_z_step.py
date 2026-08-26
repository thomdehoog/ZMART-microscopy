"""Stage 0, instruments 1 and 4: what the volume view and a z-step really cost.

Two questions, one synthetic deep picture, counted at the page's own network:

1. **The held-volume refetch bill.** With the 3-D view held, one
   whole-source announcement arrives. How many chunk requests, how many
   bytes, over how long, before the page is quiet again? This is the number
   both depth reviews said decides the volume view's refresh design.
2. **The z-step cost.** On a finished picture, step the plane slider by one.
   One plane's pieces should be fetched; the bench observation
   (2026-08-17) suspects far more. This measures it.

The picture is the Thy1 one-source trick made synthetic: one small deep
tile, every plane stamped with its own brightness step, laid out as a grid
of link-blocks and declared as one built picture. Everything is small on
purpose (test economics); the shape, not the size, drives the numbers.

Screenshots are saved at every stage, because the standing habit is to LOOK:
a counter on a page that never actually drew the volume counts nothing.

Run: python measure_the_volume_refetch_and_z_step.py [--across 3] [--keep]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

_BUILDING = Path(__file__).resolve().parents[1] / "app" / "picture"
sys.path.insert(0, str(_BUILDING))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import measure_a_governed_run_at_scale as harness  # noqa: E402,F401
import numpy as np  # noqa: E402
import zarr  # noqa: E402
from declare import declare_a_built_picture  # noqa: E402
from server import make_server  # noqa: E402

DEPTH = 13          # ragged on purpose
TILE_SIDE = 512
LEVELS = 3
STAMP_STEP = 400    # plane k is a flat field near 600 + k * STAMP_STEP
WINDOW = (400.0, 600.0 + STAMP_STEP * DEPTH)


def write_the_deep_tile(folder: Path) -> Path:
    """One synthetic deep tile: stamped planes, three levels, plain zarr v3."""
    tile = folder / "tile.ome.zarr"
    datasets = []
    for level in range(LEVELS):
        factor = 2 ** level
        side = TILE_SIDE // factor
        planes = np.empty((DEPTH, side, side), dtype="uint16")
        for plane in range(DEPTH):
            value = 600 + plane * STAMP_STEP
            planes[plane] = value
            # A dark grid so misplacement is visible to an eye, not only to
            # arithmetic: every 64th row and column dimmed.
            planes[plane, ::64 // factor or 1, :] = value // 2
            planes[plane, :, ::64 // factor or 1] = value // 2
        stored = zarr.create_array(
            store=str(tile / str(level)), shape=planes.shape,
            chunks=(1, side, side), dtype="uint16", fill_value=0,
            overwrite=True)
        stored[:] = planes
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, float(factor), float(factor)]},
                {"type": "translation", "translation": [0.0, 0.0, 0.0]},
            ],
        })
    described = {
        "zarr_format": 3, "node_type": "group",
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "axes": [
                {"name": "z", "type": "space", "unit": "micrometer"},
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"},
            ],
            "datasets": datasets,
        }]}},
    }
    (tile / "zarr.json").write_text(json.dumps(described, indent=2))
    return tile


def place_the_blocks(folder: Path, tile: Path, across: int) -> Path:
    """A grid of link-blocks over the one tile, each slid to its place."""
    blocks = folder / "blocks"
    described = json.loads((tile / "zarr.json").read_text())
    for row in range(across):
        for column in range(across):
            store = blocks / f"Block_r{row}c{column}.ome.zarr"
            store.mkdir(parents=True)
            moved = json.loads(json.dumps(described))
            for dataset in moved["attributes"]["ome"]["multiscales"][0]["datasets"]:
                for change in dataset["coordinateTransformations"]:
                    if change["type"] == "translation":
                        change["translation"] = [
                            0.0, float(row * TILE_SIDE), float(column * TILE_SIDE)]
            (store / "zarr.json").write_text(json.dumps(moved, indent=2))
            for level in range(LEVELS):
                (store / str(level)).symlink_to(tile / str(level),
                                               target_is_directory=True)
    return blocks


class Counter:
    """Chunk requests and bytes seen by the page, resettable between phases."""

    def __init__(self, page) -> None:
        self.requests: list[str] = []
        self.bytes = 0
        self._lock = threading.Lock()
        page.on("request", self._asked)
        page.on("response", self._answered)

    def _asked(self, request) -> None:
        if "/data/" in request.url and "/c/" in request.url:
            with self._lock:
                self.requests.append(request.url.split("/data/")[-1])

    def _answered(self, response) -> None:
        if "/data/" in response.url and "/c/" in response.url:
            try:
                length = int(response.headers.get("content-length") or 0)
            except (TypeError, ValueError):
                length = 0
            with self._lock:
                self.bytes += length

    def reset(self) -> None:
        with self._lock:
            self.requests = []
            self.bytes = 0

    def snapshot(self) -> tuple[int, int]:
        with self._lock:
            return len(self.requests), self.bytes


def until_quiet(counter: Counter, page, *, quiet_s: float = 4.0,
                ceiling_s: float = 180.0) -> float:
    """Wait until no new chunk request for ``quiet_s``; return seconds waited."""
    began = time.perf_counter()
    last_count = counter.snapshot()[0]
    last_change = began
    while True:
        page.wait_for_timeout(500)
        now = time.perf_counter()
        count = counter.snapshot()[0]
        if count != last_count:
            last_count = count
            last_change = now
        if now - last_change >= quiet_s:
            return now - began - quiet_s
        if now - began >= ceiling_s:
            print("  (ceiling reached while still fetching -- reported as-is)")
            return now - began


def announce(port: int) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/announce",
        data=json.dumps({"wrote_image_in_place": True}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30):
        pass


def main() -> int:
    parsing = argparse.ArgumentParser()
    parsing.add_argument("--across", type=int, default=3)
    parsing.add_argument("--keep", action="store_true")
    asked = parsing.parse_args()

    folder = Path(tempfile.mkdtemp(prefix="volume-refetch-"))
    shots = folder / "shots"
    shots.mkdir()
    print(f"fixture and screenshots in {folder}")

    tile = write_the_deep_tile(folder)
    blocks = place_the_blocks(folder, tile, asked.across)
    shown = folder / "shown"
    store = declare_a_built_picture(shown, blocks, name="deep")
    print(f"declared {store}")

    server = make_server(port=0, data_dir=shown, site_dir=_BUILDING.parent / "app" / "page" / "dist",
                         store=[store.name], window=WINDOW, live=True)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    port = server.server_address[1]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True, args=["--use-gl=angle", "--use-angle=swiftshader",
                                     "--ignore-gpu-blocklist"])
        except Exception:
            browser = p.chromium.launch(
                executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
                headless=True, args=["--use-gl=angle", "--use-angle=swiftshader",
                                     "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1000, "height": 780})
        counter = Counter(page)

        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                               timeout=90_000)
        page.wait_for_timeout(2_000)
        page.screenshot(path=str(shots / "1_flat_settled.png"))

        # ---- instrument 4: the z-step, flat view, finished picture ----
        counter.reset()
        page.evaluate("""() => {
          const position = window.zmartViewer.navigationState.position;
          const space = position.coordinateSpace.value;
          const moved = Float32Array.from(position.value);
          const axis = space.names.indexOf('z');
          moved[axis] += 1;
          position.value = moved;
        }""")
        waited = until_quiet(counter, page)
        stepped = counter.snapshot()
        page.screenshot(path=str(shots / "2_after_z_step.png"))
        print(f"Z-STEP: {stepped[0]} chunk requests, {stepped[1]/1e6:.2f} MB, "
              f"settled in {waited:.1f}s")
        counter.reset()
        page.evaluate("""() => {
          const position = window.zmartViewer.navigationState.position;
          const space = position.coordinateSpace.value;
          const moved = Float32Array.from(position.value);
          moved[space.names.indexOf('z')] += 1;
          position.value = moved;
        }""")
        waited = until_quiet(counter, page)
        stepped2 = counter.snapshot()
        print(f"Z-STEP again: {stepped2[0]} requests, {stepped2[1]/1e6:.2f} MB, "
              f"settled in {waited:.1f}s")

        # ---- instrument 1: the held-volume refetch bill ----
        page.click("text=3D")
        page.wait_for_timeout(6_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                               timeout=120_000)
        page.wait_for_timeout(4_000)
        page.screenshot(path=str(shots / "3_volume_settled.png"))

        counter.reset()
        announce(port)
        waited = until_quiet(counter, page, quiet_s=5.0, ceiling_s=300.0)
        refetched = counter.snapshot()
        page.screenshot(path=str(shots / "4_volume_after_announce.png"))
        print(f"HELD-VOLUME REFETCH: {refetched[0]} chunk requests, "
              f"{refetched[1]/1e6:.2f} MB, settled in {waited:.1f}s")

        # For the record: what the volume was drawing from.
        census = page.evaluate("""() => {
          const out = [];
          for (const managed of window.zmartViewer.layerManager.managedLayers) {
            for (const rl of (managed.layer?.renderLayers || [])) {
              const p = rl.layerChunkProgressInfo;
              if (p) out.push([p.numVisibleChunksNeeded,
                               p.numVisibleChunksAvailable]);
            }
          }
          return out;
        }""")
        print(f"volume progress (needed, available) per layer: {census}")
        browser.close()

    server.shutdown()
    if not asked.keep:
        print(f"(fixture kept at {folder} -- pass nothing to keep, "
              "it is in /tmp and small)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
