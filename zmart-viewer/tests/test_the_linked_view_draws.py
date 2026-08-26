"""Does a picture that was never written down actually appear on screen?

:mod:`zmart_storage.linked` presents a folder of tiles to the viewer as one image
without copying any of the full-size picture into it. Its companion test file,
``test_the_linked_view_matches_the_canvas.py``, compares the two arrangements voxel
by voxel and is the stricter check by a long way. What it cannot say is whether the
viewer draws the result, and that is a separate question with its own ways of going
wrong: a description the engine will not accept, a position that puts the picture
somewhere off screen, a store the viewer opens as several images instead of one.

So these tests open the real browser on both arrangements over the same tiles and
photograph what appears. The picture is looked at rather than the engine asked
about itself, for the reason ``pixels.py`` sets out: a piece of picture nobody
wrote is fetched, decoded and counted as "available" exactly like a written one.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import numpy as np
from pixels import assert_something_was_drawn, image_middle
from server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.cropped import TilesAndCanvas  # noqa: E402
from zmart_storage.linked import PlacedTile, link_the_tiles  # noqa: E402

# A raster whose tiles butt up, deep enough to be worth looking at and small enough
# to write and open twice inside a test.
TILE = (4, 128, 128)
GRID = 4
CHUNK = 128
VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (0.0, 12.0, 9.0)
WINDOW = (0, 4000)

_FIRST_DRAW_IS_DONE = """() => {
  let layers = 0, needed = 0, available = 0;
  for (const m of window.zmartViewer.layerManager.managedLayers)
    for (const rl of (m.layer?.renderLayers) || []) {
      layers += 1;
      const p = rl.layerChunkProgressInfo;
      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
    }
  return layers > 0 && available > 0 && available >= needed;
}"""

_HOW_MANY_IMAGES = """() => window.zmartViewer.layerManager.managedLayers
     .filter((m) => m.layer && m.layer.type === 'image')
     .reduce((n, m) => n + m.layer.dataSources.length, 0)"""


def _a_tile(seed: int) -> np.ndarray:
    """One tile of something that looks like a specimen: dim background, bright blobs."""
    rng = np.random.default_rng(seed)
    depth, height, width = TILE
    z, y, x = np.indices(TILE, dtype=np.float32)
    picture = 500 + 180 * (y / height) + rng.normal(0, 40, size=TILE)
    for _ in range(8):
        at_y, at_x = rng.uniform(12, height - 12), rng.uniform(12, width - 12)
        lean_y, lean_x = rng.uniform(-3, 3), rng.uniform(-3, 3)
        spread = rng.uniform(7, 16)
        along = (
            (y - (at_y + lean_y * z)) ** 2 + (x - (at_x + lean_x * z)) ** 2
        ) / (2 * spread ** 2)
        picture = np.maximum(picture, rng.uniform(1600, 3500) * np.exp(-along))
    return np.clip(picture, 0, 4000).astype("uint16")


def _both_arrangements(folder: Path) -> None:
    """Write the raster as a canvas, and point at the same tiles as a second image."""
    run = TilesAndCanvas.create(
        folder,
        name="written",
        canvas_shape=(TILE[0], GRID * TILE[1], GRID * TILE[2]),
        tile_shape=TILE,
        tile_step=TILE,
        tile_grid=(1, GRID, GRID),
        voxel_size_um=VOXEL_UM,
        origin_um=ORIGIN_UM,
        channels=[Channel("488", window=WINDOW)],
        chunk=CHUNK,
    )
    placed = []
    for row in range(GRID):
        for column in range(GRID):
            where = run.write(
                _a_tile(row * GRID + column),
                origin=(0, row * TILE[1], column * TILE[2]),
                tile_index=(0, row, column),
            )
            placed.append(PlacedTile(
                store=where, lands_at=(0, row * TILE[1], column * TILE[2])
            ))
    run.close()
    link_the_tiles(
        folder, name="pointed", tiles=placed,
        view_shape=(TILE[0], GRID * TILE[1], GRID * TILE[2]),
    )


def _photograph(browser, built_dist, folder: Path, image: str):
    """Open the viewer on one image and hand back the picture and how many images."""
    server = make_server(
        port=0, data_dir=folder, site_dir=built_dist, store=image, live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(_FIRST_DRAW_IS_DONE, timeout=90_000)
        # Holding the pieces is a step ahead of having painted with them, and the
        # painting happens on the engine's own schedule rather than ours.
        page.wait_for_timeout(1500)
        assert_something_was_drawn(page, f"the {image} view")
        return image_middle(page), page.evaluate(_HOW_MANY_IMAGES)
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_pointed_at_view_draws_the_same_picture_as_the_canvas(
    browser, built_dist, tmp_path
):
    """Two arrangements of one set of tiles, photographed, and compared.

    The two stores hold the same picture at the same place on the stage and are
    opened by the same viewer in the same window, so the pixels that come back
    should be the same pixels. They are compared with a little room for the
    engine's own rounding rather than demanded exactly equal — what would fail here
    is a picture drawn in the wrong place, at the wrong brightness, or not at all,
    and any of those move a great many pixels a long way.
    """
    run = tmp_path / "run"
    _both_arrangements(run)

    written, _ = _photograph(browser, built_dist, run, "written.ome.zarr")
    pointed, _ = _photograph(browser, built_dist, run, "pointed.ome.zarr")

    assert pointed.shape == written.shape
    apart = np.abs(pointed.astype(int) - written.astype(int))
    disagreeing = float((apart.max(axis=2) > 8).mean())
    print(
        f"\n  the two pictures differ by at most {int(apart.max())} of 255 in any "
        f"one pixel, and {disagreeing:.2%} of them differ at all"
    )
    assert disagreeing < 0.01, (
        f"{disagreeing:.1%} of the window differs between the canvas and the "
        "pointed-at view of the same tiles. They are the same picture in the same "
        "place, so a difference this large is one of them being drawn wrongly."
    )


def test_the_pointed_at_view_is_one_image_however_many_tiles(
    browser, built_dist, tmp_path
):
    """The engine is handed one image, not one per tile.

    This is the whole reason for building a view at all. The folder of whole tiles
    sits beside it in the run's folder, and if the viewer picked those up instead,
    a run of ten thousand tiles would cost exactly what the view was built to save.
    """
    run = tmp_path / "run"
    _both_arrangements(run)
    _, images = _photograph(browser, built_dist, run, "pointed.ome.zarr")
    assert images == 1, (
        f"the engine was handed {images} images for a pointed-at view of "
        f"{GRID * GRID} tiles, and it should have been handed one"
    )
