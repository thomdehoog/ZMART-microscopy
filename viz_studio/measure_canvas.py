"""Measure the cost of the storage layout `DATA_LAYOUT.md` decides on.

That document argues for one OME-Zarr per acquisition type, holding all of that
type's positions in a single stage-sized canvas. Two claims carry the argument,
and both are about cost, so both should be checked rather than believed:

  1. A canvas sized for the whole stage is affordable, because a piece of image
     nobody wrote does not exist on disk.
  2. Because the shrunk-down copies (the "pyramid") cover the whole mosaic,
     looking at all of it at once is as cheap as looking at one tile close up.

This script builds such a store, reports what it weighs, then opens it in the
real viewer and counts exactly which files the engine asks for when zoomed out
and when zoomed in. Run it with::

    python measure_canvas.py

It needs the viewer page built (``npm --prefix frontend run build``) and a
browser for the automated check, the same as the tests. Nothing here touches your
data: it writes a throwaway store under a temporary folder.

Re-run it when the data grows or the engine is upgraded. If the numbers move a
long way from the ones quoted in `DATA_LAYOUT.md`, the reasoning there deserves
another look.
"""

from __future__ import annotations

import collections
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import zarr

sys.path.insert(0, "/home/user/ZMART-microscopy/viz_studio/backend")
from server import make_server  # noqa: E402

# A canvas sized for the stage, not for what we happened to image.
CANVAS = 8192          # y and x, in pixels
DEPTH = 4              # z planes
CHANNELS = 2
TILE = 512             # each acquisition writes a tile this big
CHUNK = 256
LEVELS = 6             # 8192 -> 4096 -> 2048 -> 1024 -> 512 -> 256
VOXEL_UM = (2.0, 0.35, 0.35)   # z, y, x

# Nine tiles in a 3x3 arrangement, spread across the canvas and chunk-aligned so
# each one is an independent write with no read-modify-write on its edges.
TILE_ORIGINS = [(2048 * r, 2048 * c) for r in range(3) for c in range(3)]


def build(root: Path) -> Path:
    store = root / "overview.ome.zarr"
    group = zarr.open_group(str(store), mode="w", zarr_format=2)

    for level in range(LEVELS):
        factor = 2**level
        side = CANVAS // factor
        arr = group.create_array(
            str(level),
            shape=(1, CHANNELS, DEPTH, side, side),
            chunks=(1, 1, 1, min(CHUNK, side), min(CHUNK, side)),
            dtype="uint16",
        )
        size = max(TILE // factor, 1)
        # One tile's worth of signal, downsampled for this level. Averaging is not
        # needed for a flat patch, but the shape must shrink with the level.
        for index, (y0, x0) in enumerate(TILE_ORIGINS):
            rng = np.random.default_rng(index)
            # Noise, not a flat fill: real microscope pixels barely compress, and a
            # constant patch would shrink ~18x and flatter the disk figure.
            patch = (800 + rng.integers(0, 16000, size=(1, CHANNELS, DEPTH, size, size))).astype(np.uint16)
            y, x = y0 // factor, x0 // factor
            arr[:, :, :, y : y + size, x : x + size] = patch

    axes = [
        {"name": "t", "type": "time", "unit": "second"},
        {"name": "c", "type": "channel"},
        {"name": "z", "type": "space", "unit": "micrometer"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]
    datasets = []
    for level in range(LEVELS):
        f = 2**level
        vz, vy, vx = VOXEL_UM
        datasets.append(
            {
                "path": str(level),
                # Only y and x shrink down the pyramid; z spacing is unchanged,
                # which is the usual arrangement for a mosaic.
                "coordinateTransformations": [
                    {"type": "scale", "scale": [1.0, 1.0, vz, vy * f, vx * f]}
                ],
            }
        )
    (store / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [{"version": "0.4", "axes": axes, "datasets": datasets}],
                "omero": {
                    "channels": [
                        {"label": "structure", "color": "FFFFFF",
                         "window": {"min": 0, "max": 65535, "start": 800, "end": 16000}},
                        {"label": "marker-a", "color": "00FF66",
                         "window": {"min": 0, "max": 65535, "start": 800, "end": 16000}},
                    ]
                },
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return store


def measure(store: Path, dist: Path):
    from playwright.sync_api import sync_playwright

    server = make_server(port=0, data_dir=store.parent, site_dir=dist, store=store.name)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    fetched: collections.Counter = collections.Counter()

    def note(request):
        path = request.url.replace(base, "")
        if path.startswith("/data/"):
            parts = path.split("/")
            # /data/overview.ome.zarr/<level>/<chunk>
            if len(parts) >= 5 and parts[3].isdigit():
                fetched[parts[3]] += 1

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]
        )
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.on("request", note)
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)

        def settle(seconds=14):
            page.wait_for_timeout(seconds * 1000)

        def chunk_state():
            return page.evaluate(
                """() => {
                  const v = window.zmartViewer;
                  let needed = 0, available = 0;
                  const levels = new Set();
                  for (const m of v.layerManager.managedLayers) {
                    for (const rl of (m.layer?.renderLayers) || []) {
                      const p = rl.layerChunkProgressInfo;
                      if (p) { needed += p.numVisibleChunksNeeded;
                               available += p.numVisibleChunksAvailable; }
                    }
                  }
                  return {needed, available,
                          scale: v.navigationState.zoomFactor?.value ?? null};
                }"""
            )

        def look(cross_section_scale, label, fresh=False):
            nonlocal page
            if fresh:
                # A brand-new page with a cleared cache: otherwise the second
                # measurement is answered from what the first one already loaded,
                # and reads as "no data needed" when it means "already had it".
                page.close()
                context = browser.new_context()
                context.clear_cookies()
                page = context.new_page()
                page.set_viewport_size({"width": 1200, "height": 900})
                page.on("request", note)
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
                page.wait_for_timeout(2000)
            fetched.clear()
            page.evaluate(
                """(scale) => {
                  const v = window.zmartViewer;
                  v.navigationState.zoomFactor.value = scale;
                }""",
                cross_section_scale,
            )
            settle()
            state = chunk_state()
            per_level = ", ".join(f"level {k}: {v}" for k, v in sorted(fetched.items()))
            print(f"\n  {label}")
            print(f"    chunk files fetched : {sum(fetched.values())}   ({per_level or 'none'})")
            print(f"    engine reports      : {state['available']}/{state['needed']} visible chunks ready")

        settle()
        print("\n=== what Neuroglancer fetches, by pyramid level ===")
        # Zoomed right out: the whole 8192 canvas across ~900 screen pixels.
        look(CANVAS * 0.35 / 900 * 1e-6, "ZOOMED OUT — whole mosaic on screen")
        # Zoomed in: one screen pixel per image pixel.
        look(0.35e-6, "ZOOMED IN — one screen pixel per image pixel (fresh page, no cache)", fresh=True)

        browser.close()
    server.shutdown()


def main() -> int:
    root = Path("/tmp/sparse_canvas_test")
    subprocess.run(["rm", "-rf", str(root)], check=False)
    root.mkdir(parents=True)

    print("Building one acquisition-type store with a sparse canvas...")
    t0 = time.time()
    store = build(root)
    build_seconds = time.time() - t0

    declared = 1 * CHANNELS * DEPTH * CANVAS * CANVAS * 2
    on_disk_kb = int(
        subprocess.run(["du", "-sk", str(store)], capture_output=True, text=True).stdout.split()[0]
    )
    written = len(TILE_ORIGINS) * CHANNELS * DEPTH * TILE * TILE * 2

    print("\n=== what the canvas costs ===")
    print(f"  canvas declared      : {CANVAS} x {CANVAS} px, {DEPTH} z, {CHANNELS} c"
          f"  = {declared / 1024**3:.2f} GiB at full resolution")
    print(f"  tiles actually imaged: {len(TILE_ORIGINS)} x {TILE}x{TILE}"
          f"  = {written / 1024**2:.0f} MiB of pixels")
    print(f"  on disk (all {LEVELS} pyramid levels): {on_disk_kb / 1024:.0f} MiB")
    print(f"  fraction of the declared canvas: {on_disk_kb * 1024 / declared:.1%}")
    print(f"  built in {build_seconds:.0f}s")

    dist = Path("/home/user/ZMART-microscopy/viz_studio/frontend/dist")
    if not (dist / "index.html").exists():
        print("frontend/dist is not built; cannot measure fetches")
        return 1
    measure(store, dist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
