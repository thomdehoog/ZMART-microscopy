"""What a timelapse spread over many positions costs the viewer.

Two numbers, both at a few sizes:

  1. Opening a folder cold -- how long until every position is on the row.
  2. One position gaining a frame -- how many small requests that sets off, and
     how long before the slider can reach the new frame.

The second is the one this is really for. The frame count belongs to the row and
is the highest across its positions, so one position advancing moves the row and
every store on it is read again. This says by how much.

The stores are deliberately tiny. The cost being measured is a count of round
trips for the small files describing each store, and that count depends on how
many positions and channels there are, not on how big the image is -- so a
sparse store measures the same thing a 400 GB one would, and fits on disk.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import zarr

VIZ = Path("/home/user/ZMART-microscopy/viz_studio")
sys.path.insert(0, str(VIZ / "backend"))

from playwright.sync_api import sync_playwright  # noqa: E402
from server import make_server  # noqa: E402

CHANNELS, DEPTH, SIDE, CHUNK, LEVELS = 2, 1, 64, 64, 2

SOURCES = """() => window.zmartViewer.layerManager.managedLayers
              .filter((m) => m.layer && m.layer.type === 'image')
              .reduce((n, m) => n + m.layer.dataSources.length, 0)"""

TIME_REACH = """() => {
  const space = window.zmartViewer.navigationState.position.coordinateSpace.value;
  if (!space || !space.valid) return null;
  const at = space.names.indexOf('t');
  if (at < 0) return null;
  return Math.round(space.bounds.upperBounds[at]);
}"""

ANNOUNCE = """async () => {
  const r = await fetch('/api/announce', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: 'a frame landed'}),
  });
  return (await r.json()).told;
}"""


def write_timelapse(folder: Path, name: str, *, frames: int, column: int) -> Path:
    store = folder / f"{name}.ome.zarr"
    store.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    datasets = []
    for level in range(LEVELS):
        side = SIDE >> level
        array = group.create_array(
            str(level),
            shape=(frames, CHANNELS, DEPTH, side, side),
            chunks=(1, 1, 1, CHUNK, CHUNK),
            dtype="uint16",
            chunk_key_encoding={"name": "v2", "separator": "/"},
        )
        # Every frame gets at least one piece on disk, because that is how the
        # server counts how far the run has got. Without it there is nothing to
        # count and the row never reports a frame at all.
        array[:] = 3000
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale", "scale": [30.0, 1.0, 2.0, 0.35 * 2**level, 0.35 * 2**level]}
            ],
        })
    (store / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [
                {"name": "t", "type": "time", "unit": "second"},
                {"name": "c", "type": "channel"},
                {"name": "z", "type": "space", "unit": "micrometer"},
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": datasets,
            "coordinateTransformations": [
                {"type": "translation",
                 "translation": [0.0, 0.0, 0.0, 0.0, column * SIDE * 0.35]}],
        }],
        "omero": {"channels": [
            {"label": f"ch{i}", "color": "FFFFFF",
             "window": {"min": 0, "max": 65535, "start": 700, "end": 8700}}
            for i in range(CHANNELS)]},
    }), encoding="utf-8")
    return store


def grow(store: Path, frames: int) -> None:
    group = zarr.open_group(str(store), mode="a", zarr_format=2)
    for level in range(LEVELS):
        side = SIDE >> level
        array = group[str(level)]
        array.resize((frames, CHANNELS, DEPTH, side, side))
        array[frames - 1] = np.uint16(5000)


def measure(positions: int, root: Path) -> dict:
    folder = root / f"n{positions}"
    folder.mkdir(parents=True, exist_ok=True)
    built = time.perf_counter()
    first = None
    for index in range(positions):
        store = write_timelapse(folder, f"overview_pos{index + 1:04d}",
                                frames=2, column=index)
        if index == 0:
            first = store
    wrote = time.perf_counter() - built

    server = make_server(port=0, data_dir=folder, site_dir=VIZ / "frontend" / "dist",
                         store="overview_pos0001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 900, "height": 700})
        described: list[str] = []
        page.on("request", lambda r: described.append(r.url)
                if r.url.endswith((".zarray", ".zattrs")) else None)
        try:
            opened = time.perf_counter()
            page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                      wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartViewer !== undefined", timeout=120_000)
            page.wait_for_function(f"{SOURCES} === {positions * CHANNELS}", timeout=300_000)
            cold = time.perf_counter() - opened
            cold_requests = len(described)
            page.wait_for_function(f"() => ({TIME_REACH})() === 2", timeout=120_000)
            page.wait_for_timeout(2000)

            settled = len(described)
            grow(first, 3)
            began = time.perf_counter()
            page.evaluate(ANNOUNCE)
            page.wait_for_function(f"() => ({TIME_REACH})() === 3", timeout=300_000)
            noticed = time.perf_counter() - began
            page.wait_for_timeout(2000)
            on_growth = len(described) - settled
        finally:
            page.close()
            browser.close()
            server.shutdown()
            thread.join(timeout=5)

    return {
        "positions": positions,
        "wrote_s": wrote,
        "cold_s": cold,
        "cold_requests": cold_requests,
        "growth_requests": on_growth,
        "growth_s": noticed,
    }


if __name__ == "__main__":
    sizes = [int(a) for a in sys.argv[1:]] or [25, 100, 400]
    # The stores are written somewhere temporary and thrown away afterwards: a
    # thousand of them is a lot of small files to leave lying beside the code.
    holding = tempfile.TemporaryDirectory(prefix="zmart-many-positions-")
    root = Path(holding.name)
    print(f"{'positions':>9} {'cold open':>10} {'descr. reqs':>12} "
          f"{'one frame lands':>16} {'descr. reqs':>12}")
    for size in sizes:
        row = measure(size, root)
        print(f"{row['positions']:>9} {row['cold_s']:>9.1f}s {row['cold_requests']:>12} "
              f"{row['growth_s']:>15.1f}s {row['growth_requests']:>12}")
