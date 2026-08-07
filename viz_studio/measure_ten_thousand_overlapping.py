"""Ten thousand overlapping tiles as one picture. Does it stay flat?

Every claim that this arrangement opens ten thousand positions in under a second
rests on a ladder whose tiles **abutted**. Overlap is the case a real acquisition
produces, and it has never been measured at that size. If the picture bends here,
nothing else outstanding matters.

The prediction, written before the numbers: **flat**. `_tile_covering` does not scan
the tile list -- rows are indexed, the search across a row is a bisect, and the
walk-back stops after one tile width -- so overlap makes it visit perhaps two tiles
where it visited one. What genuinely grows is once-per-open: the map's own size, its
parse, and the browser fetching that one document. So those are reported separately
from the opening rather than buried in it.

**And the holes are checked, not assumed.** Ten thousand ownerships computed by hand
is ten thousand chances to leave a strip nobody supplies, and unsupplied ground draws
as black rather than raising anything. Coverage is verified against the geometry
before the browser is ever opened: every piece owned exactly once, no piece owned
twice, none left out.

Tiles are deliberately tiny -- what is being measured is how many things there are,
not how much picture.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from pathlib import Path

import numpy as np

VIZ = Path(r"C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_hw_test\viz_studio")
sys.path.insert(0, str(VIZ.parent))
sys.path.insert(0, str(VIZ))
sys.path.insert(0, str(VIZ / "backend"))
sys.path.insert(0, str(VIZ / "tests"))

from server import make_server  # noqa: E402
from measure_the_frame_rate_of_a_linked_view import a_browser  # noqa: E402
from zmart_storage.canvas import Channel, _declare_one  # noqa: E402
from zmart_storage.linked import PlacedTile, link_the_tiles  # noqa: E402

TILE = 64          # voxels across one tile
PIECE = 32         # and how it is cut up: two pieces to a tile
STEP = 32          # so neighbours share exactly one piece -- the seam is chunk-aligned
VOXEL_UM = (2.0, 0.325, 0.325)

ACROSS = {400: 20, 2500: 50, 10_000: 100}

ALL_RESOLVED = """() => {
  const sources = window.zmartViewer.layerManager.managedLayers
    .filter((m) => m.layer && m.layer.type === 'image')
    .flatMap((m) => m.layer.dataSources);
  return sources.length > 0 && sources.every((s) => s.loadState !== undefined);
}"""


def write_the_tiles(run: Path, across: int) -> list[PlacedTile]:
    """Write the tiles and say which ground each of them owns.

    Neighbours overlap by exactly one piece, so a tile owns the single piece its
    successor does not reach, and the last in each direction owns the two it ends
    on. That is the ownership rule, in the smallest form it takes.
    """
    run.mkdir(parents=True, exist_ok=True)
    picture = np.linspace(600, 3600, TILE * TILE, dtype=np.float32).reshape(TILE, TILE)
    placed = []
    for row in range(across):
        for column in range(across):
            index = row * across + column
            store = run / f"tile{index:05d}.ome.zarr"
            arrays = _declare_one(
                store,
                canvas_shape=(1, TILE, TILE),
                frames=1, channels=1, dtype="uint16", chunk=PIECE, levels=1,
                voxel_size_um=VOXEL_UM,
                origin_um=(0.0, row * STEP * VOXEL_UM[1], column * STEP * VOXEL_UM[2]),
                channel_blocks=[Channel("488", window=(400, 3800)).described(65535)],
            )
            arrays[0][0, 0, :, :, :] = picture.astype("uint16")[None, :, :]
            placed.append(PlacedTile(
                store=store,
                lands_at=(0, row * STEP, column * STEP),
                taken_from=(0, 0, 0),
                size=(1,
                      TILE if row == across - 1 else STEP,
                      TILE if column == across - 1 else STEP),
            ))
        if (row + 1) % 10 == 0:
            print(f"    {(row + 1) * across} tiles written", flush=True)
    return placed


def coverage_is_sound(placed: list[PlacedTile], across: int) -> tuple[bool, str]:
    """Every piece of the picture owned exactly once. Checked, not assumed."""
    wide = (across - 1) * STEP + TILE
    pieces = wide // PIECE
    owned = np.zeros((pieces, pieces), dtype=np.int32)
    for tile in placed:
        y0, x0 = tile.lands_at[1] // PIECE, tile.lands_at[2] // PIECE
        y1 = (tile.lands_at[1] + tile.size[1]) // PIECE
        x1 = (tile.lands_at[2] + tile.size[2]) // PIECE
        owned[y0:y1, x0:x1] += 1
    holes = int((owned == 0).sum())
    doubled = int((owned > 1).sum())
    return (holes == 0 and doubled == 0,
            f"{pieces}x{pieces} pieces, {holes} with nothing behind them, "
            f"{doubled} owned twice")


def main() -> int:
    scratch = Path(sys.argv[1])
    counts = [int(n) for n in sys.argv[2].split(",")] if len(sys.argv) > 2 else [400, 2500, 10_000]

    built = {}
    for count in counts:
        run = scratch / f"overlapping{count}"
        if (run / "many.ome.zarr").exists():
            print(f"  {count}: already written", flush=True)
        else:
            if run.exists():
                shutil.rmtree(run)
            print(f"  {count} tiles, {ACROSS[count]} across...", flush=True)
            placed = write_the_tiles(run, ACROSS[count])
            sound, how = coverage_is_sound(placed, ACROSS[count])
            print(f"    coverage: {how}", flush=True)
            assert sound, f"the ownership is wrong at {count}: {how}"
            wide = (ACROSS[count] - 1) * STEP + TILE
            link_the_tiles(run, name="many", tiles=placed, view_shape=(1, wide, wide))
        described = run / "many.ome.zarr" / "zarr.json"
        if not described.exists():
            described = run / "many.ome.zarr" / ".zattrs"
        raw = described.read_bytes()
        began = time.perf_counter()
        json.loads(raw)
        built[count] = (run, len(raw), (time.perf_counter() - began) * 1000)
        print(f"    map {len(raw)/1e6:.2f} MB, parses in {built[count][2]:.0f} ms",
              flush=True)

    print("\nopening each through the real server...", flush=True)
    started, browser = a_browser(headed=False)
    rows = []
    try:
        for count in counts:
            run, size, parse = built[count]
            server = make_server(port=0, data_dir=run, site_dir=VIZ / "frontend" / "dist",
                                 store="many.ome.zarr", live=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            best = 9e9
            try:
                for _ in range(2):
                    page = browser.new_page(viewport={"width": 900, "height": 700})
                    try:
                        began = time.perf_counter()
                        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                                  wait_until="domcontentloaded")
                        page.wait_for_function("() => window.zmartViewer !== undefined",
                                               timeout=120_000)
                        page.wait_for_function(ALL_RESOLVED, timeout=600_000)
                        best = min(best, time.perf_counter() - began)
                    finally:
                        page.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
            rows.append((count, size, parse, best))
            print(f"  {count:6d} tiles: opened in {best:5.2f} s "
                  f"(map {size/1e6:.2f} MB, parse {parse:.0f} ms)", flush=True)
    finally:
        browser.close()
        started.stop()

    print("\n| tiles | map | parse | opening |")
    print("|---|---|---|---|")
    for count, size, parse, seconds in rows:
        print(f"| {count} | {size/1e6:.2f} MB | {parse:.0f} ms | {seconds:.2f} s |")
    if len(rows) >= 2:
        low, high = rows[0], rows[-1]
        print(f"\n{low[0]} -> {high[0]} tiles is x{high[3]/low[3]:.1f} "
              f"for x{high[0]/low[0]:.0f} the tiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
