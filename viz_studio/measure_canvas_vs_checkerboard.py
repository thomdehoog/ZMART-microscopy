"""What a tiled run costs, written into one image versus a few.

Two arrangements are compared, on the same run, with the same tiles:

  **One image.** Every tile written into a single OME-Zarr. Wherever two tiles
  overlap, the second one to arrive replaces the first, so the shared strip is
  gone. Simplest possible thing to read afterwards.

  **A few images.** Tiles dealt out so that neighbours never land in the same
  one, which means nothing is ever written over and the whole of every tile
  survives. The viewer draws them together and the specimen looks the same.

What is measured, for each:

  1. **Writing a tile** — how long one acquired tile takes to land, split into
     the full-resolution write and the smaller copies that go with it. This is
     the number that says whether the storage can keep up with the camera.
  2. **Opening the run** — how long until the viewer has the whole thing, and
     how many small description files it had to read to get there.
  3. **Keeping up while tiles land** — how smoothly the page runs while writing
     continues underneath it, measured as how often the browser manages to come
     round and draw. A page that stays near its natural rate is one an operator
     can still steer; one that drops is a page that feels stuck.
  4. **What the overlap cost** — how many of the acquired voxels were overwritten
     and are no longer anywhere on disk.

Run it with no arguments for the standard run, or pass a grid size:

    python viz_studio/measure_canvas_vs_checkerboard.py 9
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIZ = ROOT / "viz_studio"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(VIZ / "backend"))

from playwright.sync_api import sync_playwright  # noqa: E402
from server import make_server  # noqa: E402

from zmart_storage.canvas import Channel, TileCanvases  # noqa: E402

# A tile a quarter of a camera frame across, overlapping its neighbours by an
# eighth -- a little more than a real acquisition, so the effect is visible
# without the run taking all afternoon. Four planes deep, one colour.
TILE = (4, 256, 256)
STEP = (4, 224, 224)
CHUNK = 128
LEVELS = 3

# How often the browser is asked to come round and draw. A page with nothing to
# do manages roughly this; the number is only meaningful next to itself, since a
# machine without a graphics card draws more slowly whatever the data.
FPS_SAMPLE_SECONDS = 3.0

# Started once and only once: calling it twice would leave two loops running and
# both counting, which reads as the page having doubled its rate.
COUNT_FRAMES = """() => {
  if (window.__counting) return;
  window.__counting = true;
  window.__drawn = 0;
  const tick = () => { window.__drawn += 1; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}"""
RESET_COUNT = "() => { window.__drawn = 0; }"

SOURCES = """() => window.zmartViewer.layerManager.managedLayers
              .filter((m) => m.layer && m.layer.type === 'image')
              .reduce((n, m) => n + m.layer.dataSources.length, 0)"""


def _tiles(grid: int):
    """Where each tile of a square raster sits, and what to call it."""
    for row in range(grid):
        for col in range(grid):
            yield row, col, (0, row * STEP[1], col * STEP[2])


def write_run(folder: Path, grid: int, *, single: bool) -> dict:
    """Write the whole run one tile at a time, timing each one.

    The tiles carry a distinct flat value each, so that afterwards it is possible
    to say which tile any voxel came from, and therefore how much was lost.
    """
    side = (grid - 1) * STEP[1] + TILE[1]
    canvases = TileCanvases.create(
        folder,
        canvas_shape=(TILE[0], side, side),
        tile_shape=TILE,
        tile_step=STEP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488", window=(0, 4000))],
        chunk=CHUNK,
        levels=LEVELS,
        slots=(1, 1, 1) if single else None,
    )

    # The same picture every time, so that what is being timed is the writing
    # rather than the making up of data.
    tile = np.random.default_rng(0).integers(
        800, 3000, size=TILE, dtype=np.uint16
    )

    per_tile = []
    for row, col, origin in _tiles(grid):
        value = np.uint16(1000 + row * grid + col)
        this = np.full(TILE, value, dtype="uint16")
        this[:, 8:, 8:] = tile[:, 8:, 8:]  # a corner that identifies the tile
        began = time.perf_counter()
        canvases.write(this, origin=origin, tile_index=(0, row, col))
        per_tile.append(time.perf_counter() - began)

    return {
        "canvases": len(canvases.paths),
        "tiles": len(per_tile),
        "median_ms": float(np.median(per_tile) * 1000),
        "worst_ms": float(np.max(per_tile) * 1000),
        "total_s": float(np.sum(per_tile)),
    }


def measure_pyramid_share(folder: Path, grid: int) -> float:
    """How much of a tile's writing time goes on the smaller copies.

    Worth separating because it is the part that could be dropped or deferred if
    writing ever turned out to be the thing that could not keep up -- at the cost
    of a zoomed-out view that lags behind the run.
    """
    side = (grid - 1) * STEP[1] + TILE[1]
    tile = np.full(TILE, 2000, dtype="uint16")

    timings = {}
    for levels in (1, LEVELS):
        here = folder / f"levels{levels}"
        canvases = TileCanvases.create(
            here,
            canvas_shape=(TILE[0], side, side),
            tile_shape=TILE, tile_step=STEP,
            voxel_size_um=(2.0, 0.35, 0.35),
            channels=[Channel("488")],
            chunk=CHUNK, levels=levels,
        )
        began = time.perf_counter()
        for row, col, origin in _tiles(grid):
            canvases.write(tile, origin=origin, tile_index=(0, row, col))
        timings[levels] = time.perf_counter() - began
        shutil.rmtree(here, ignore_errors=True)

    if timings[LEVELS] <= 0:
        return 0.0
    return 100.0 * (timings[LEVELS] - timings[1]) / timings[LEVELS]


def what_the_overlap_cost(folder: Path, grid: int, *, single: bool) -> float:
    """The share of acquired voxels no longer anywhere on disk, as a percentage.

    Written as its own pass, with every tile a single flat value of its own, so
    that any voxel can be traced back to the tile it came from. A voxel that no
    longer carries its tile's value anywhere was overwritten by a neighbour, and
    nothing can recover it.
    """
    import zarr

    side = (grid - 1) * STEP[1] + TILE[1]
    canvases = TileCanvases.create(
        folder,
        canvas_shape=(TILE[0], side, side),
        tile_shape=TILE, tile_step=STEP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")],
        chunk=CHUNK, levels=1,
        slots=(1, 1, 1) if single else None,
    )
    for row, col, origin in _tiles(grid):
        canvases.write(np.full(TILE, 1000 + row * grid + col, dtype="uint16"),
                       origin=origin, tile_index=(0, row, col))

    levels = [np.asarray(zarr.open_group(str(p), mode="r")["0"][0, 0])
              for p in canvases.paths]

    kept = 0
    for row, col, (_, y0, x0) in _tiles(grid):
        value = 1000 + row * grid + col
        # A voxel survives if *any* of the images still holds this tile's value
        # there. Counting the union is what makes the two arrangements
        # comparable: one image has only itself to look in, several have all of
        # them, which is exactly the difference being measured.
        survives = np.zeros(TILE, dtype=bool)
        for level in levels:
            survives |= level[:, y0:y0 + TILE[1], x0:x0 + TILE[2]] == value
        kept += int(survives.sum())

    acquired = grid * grid * int(np.prod(TILE))
    return 100.0 * (acquired - kept) / acquired


def watch_the_viewer(folder: Path, grid: int) -> dict:
    """Open the viewer on the run and see how it behaves while tiles land."""
    stores = sorted(p.name for p in folder.glob("canvas*.ome.zarr"))
    server = make_server(port=0, data_dir=folder,
                         site_dir=VIZ / "frontend" / "dist", store=stores[0])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    side = (grid - 1) * STEP[1] + TILE[1]
    canvases = TileCanvases.create(
        folder / "arriving",
        canvas_shape=(TILE[0], side, side),
        tile_shape=TILE, tile_step=STEP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")],
        chunk=CHUNK, levels=LEVELS,
        slots=(1, 1, 1) if len(stores) == 1 else None,
    )

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=[
                "--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist",
            ])
            page = browser.new_page(viewport={"width": 900, "height": 700})
            described: list[str] = []
            page.on("request", lambda r: described.append(r.url)
                    if r.url.endswith((".zarray", ".zattrs")) else None)
            try:
                began = time.perf_counter()
                page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                          wait_until="domcontentloaded")
                page.wait_for_function("() => window.zmartViewer !== undefined",
                                       timeout=120_000)
                page.wait_for_function(f"{SOURCES} >= {len(stores)}", timeout=300_000)
                cold = time.perf_counter() - began
                requests_to_open = len(described)
                page.wait_for_timeout(1500)

                # How fast the page comes round to draw with nothing happening.
                page.evaluate(COUNT_FRAMES)
                page.wait_for_timeout(int(FPS_SAMPLE_SECONDS * 1000))
                idle_fps = page.evaluate("() => window.__drawn") / FPS_SAMPLE_SECONDS

                # And again, with tiles landing underneath it the whole time.
                stop = threading.Event()

                def keep_writing():
                    tile = np.full(TILE, 2500, dtype="uint16")
                    n = 0
                    while not stop.is_set():
                        row, col = (n // grid) % grid, n % grid
                        canvases.write(tile,
                                       origin=(0, row * STEP[1], col * STEP[2]),
                                       tile_index=(0, row, col))
                        n += 1

                writer = threading.Thread(target=keep_writing, daemon=True)
                page.evaluate(RESET_COUNT)
                writer.start()
                page.wait_for_timeout(int(FPS_SAMPLE_SECONDS * 1000))
                busy_fps = page.evaluate("() => window.__drawn") / FPS_SAMPLE_SECONDS
                stop.set()
                writer.join(timeout=10)
                requests_while_writing = len(described) - requests_to_open
            finally:
                page.close()
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)

    return {
        "sources": len(stores),
        "cold_s": cold,
        "open_requests": requests_to_open,
        "idle_fps": idle_fps,
        "busy_fps": busy_fps,
        "writing_requests": requests_while_writing,
    }


def main(grid: int) -> None:
    holding = tempfile.TemporaryDirectory(prefix="zmart-canvas-vs-checkerboard-")
    root = Path(holding.name)

    print(f"\nA {grid} x {grid} raster of {TILE[1]}-voxel tiles, "
          f"stepped {STEP[1]} -- so neighbours share "
          f"{100 * (TILE[1] - STEP[1]) / TILE[1]:.0f}% of their width.\n")

    results = {}
    for label, single in (("one image", True), ("a few images", False)):
        folder = root / label.replace(" ", "_")
        written = write_run(folder, grid, single=single)
        lost = what_the_overlap_cost(root / f"loss_{single}", grid, single=single)
        watched = watch_the_viewer(folder, grid)
        results[label] = {**written, "lost_pct": lost, **watched}

    share = measure_pyramid_share(root / "pyramid", grid)

    head = f"{'':<26}" + "".join(f"{label:>16}" for label in results)
    print(head)
    print("-" * len(head))
    rows = [
        ("images written into", "canvases", "{:d}"),
        ("writing one tile, median", "median_ms", "{:.1f} ms"),
        ("writing one tile, worst", "worst_ms", "{:.1f} ms"),
        (f"writing all {grid * grid} tiles", "total_s", "{:.1f} s"),
        ("acquired data overwritten", "lost_pct", "{:.1f}%"),
        ("", None, None),
        ("sources the viewer opens", "sources", "{:d}"),
        ("opening the run", "cold_s", "{:.1f} s"),
        ("description files read", "open_requests", "{:d}"),
        ("draws per second, idle", "idle_fps", "{:.0f}"),
        ("draws per second, writing", "busy_fps", "{:.0f}"),
        ("description files, writing", "writing_requests", "{:d}"),
    ]
    for title, key, fmt in rows:
        if key is None:
            print()
            continue
        cells = "".join(fmt.format(results[label][key]).rjust(16) for label in results)
        print(f"{title:<26}{cells}")

    print(f"\nOf the time spent writing a tile, {share:.0f}% goes on the smaller "
          "copies\nthat make the zoomed-out view work.\n")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 9)
