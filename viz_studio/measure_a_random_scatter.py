"""Ten thousand tiles wherever the microscope decided to look, opened and zoomed.

`measure_ten_thousand_linked.py` beside this file proves the linked view's
arithmetic at scale without a browser. This is the other half: the same size of
run, placed the way smart microscopy actually places tiles — at random over a
stage far larger than the tiles cover, fields of view overlapping wherever the
randomness lands them — opened in a real browser through the viewer's own
server, timed, and driven through a full ladder of zooms.

It answers three questions the grid cannot:

Does random placement cost anything to open?
    It should not: the browser is shown one image and asks by screen and piece
    size, never by tile count. Measured 2026-08-10 on this project's own piece
    size (256 voxels): 10,000 scattered positions, 5,693 of them overlapping
    another, fully loaded in 1.3 s and 71 pieces from a cold page — the same
    class as a single written canvas. The whole 29 mm stage fitted and settled
    in 2.2 s from cold, 82 pieces in total.

Do overlapping tiles draw as a picture rather than a fight?
    Where two tiles share ground, the view's map gives each piece of the
    picture to one of them whole, so edges land on piece boundaries and every
    piece drawn is really one tile's pixels. A sample of pointers is followed
    and each answering tile is made to prove it covers the piece it answered
    for — overlap included.

Does the pyramid hold up while zooming?
    The ladder crosses the seam between the pointed full-size picture (tile
    files handed over untouched) and the written zoomed-out copies, out to the
    whole stage and back. Measured on the same evening: every rung settled in
    ~0.3 s — the floor of the probe itself — with piece counts collapsing
    515, 367, 76, 8, 2 from full resolution out to the whole stage.

Run it with::

    python measure_a_random_scatter.py           # 10,000 positions
    python measure_a_random_scatter.py 2000      # fewer, if time is short
    python measure_a_random_scatter.py --headed  # reach the graphics card

The card is asked for first and the renderer that really drew is announced on
every run. On Windows, ``--headed`` is what makes the card reachable at all:
a headless Chromium draws in SwiftShader whatever arguments it is given, so a
headless run measures the processor however good the card is.

It writes about 6 GB under a temporary folder and removes it afterwards, and it
needs a browser (the same fallback the test suite uses). Building takes several
minutes: most of that is writing the ten thousand positions themselves, exactly
as an acquisition would, at well under a tenth of a second per position.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

import numpy as np
import zarr

VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(VIZ / "backend"))
sys.path.insert(0, str(VIZ.parent))
sys.path.insert(0, str(VIZ))
sys.path.insert(0, str(VIZ / "tests"))

import linking  # noqa: E402
from measure_the_frame_rate_of_a_linked_view import (  # noqa: E402
    another_browser,
    say_what_is_drawing,
)
from measure_the_overlapping_run import (  # noqa: E402
    SETTLED,
    _lit,
    _the_middle_of,
)

from zmart_storage.canvas import Channel, _declare_one  # noqa: E402
from zmart_storage.linked import PlacedTile, start_a_growing_view  # noqa: E402

# One position: 2 x 2 pieces of the size this project writes, so overlaps are
# partial rather than all-or-nothing. The tiles keep no copies of their own —
# the view points at full size and writes every zoom, which is the arrangement
# every tile written before pointing existed needs.
TILE = (1, 512, 512)
PIECE = 256
VIEW_LEVELS = 9
LATTICE = PIECE      # pointing one level deep asks only for whole pieces
ROOM = (1, 81920, 81920)
VOXEL_UM = (2.0, 0.35, 0.35)


def scatter(rng, count: int) -> list[tuple[int, int]]:
    """Random lattice positions across the stage, exact duplicates dropped.

    Tiles overlap one another freely — only two tiles at exactly the same place
    are dropped, since the second could never be seen at all.
    """
    seen: set[tuple[int, int]] = set()
    spots: list[tuple[int, int]] = []
    slots_y = (ROOM[1] - TILE[1]) // LATTICE
    slots_x = (ROOM[2] - TILE[2]) // LATTICE
    while len(spots) < count:
        y = int(rng.integers(0, slots_y + 1)) * LATTICE
        x = int(rng.integers(0, slots_x + 1)) * LATTICE
        if (y, x) not in seen:
            seen.add((y, x))
            spots.append((y, x))
    return spots


def _how_many_overlap(spots: list[tuple[int, int]]) -> int:
    """How many tiles share at least one piece of ground with another tile."""
    taken: dict[tuple[int, int], int] = {}
    touched: set[int] = set()
    for number, (y, x) in enumerate(spots):
        for down in range(TILE[1] // LATTICE):
            for across in range(TILE[2] // LATTICE):
                cell = (y // LATTICE + down, x // LATTICE + across)
                if cell in taken:
                    touched.add(taken[cell])
                    touched.add(number)
                else:
                    taken[cell] = number
    return len(touched)


def build(work: Path, spots: list[tuple[int, int]]) -> float:
    """Write every position and grow the view over them, as a run would."""
    positions = work / "positions"
    positions.mkdir(parents=True)
    view = None
    began = time.monotonic()
    for number, (y, x) in enumerate(spots):
        store = positions / f"pos{number:05d}.ome.zarr"
        arrays = _declare_one(
            store, canvas_shape=TILE, frames=1, channels=1, dtype="uint16",
            chunk=PIECE, levels=1, voxel_size_um=VOXEL_UM,
            origin_um=(0.0, y * VOXEL_UM[1], x * VOXEL_UM[2]),
            channel_blocks=[
                Channel("488", window=(0, len(spots))).described(65535)],
        )
        # Every voxel holds its own tile number, so a followed pointer can be
        # made to prove it resolved to a tile that covers the piece.
        arrays[0][0, 0] = np.full(TILE, np.uint16(number), dtype="uint16")
        lands = (0, y, x)
        if view is None:
            view = start_a_growing_view(
                work, like=PlacedTile(store=store, lands_at=lands),
                view_shape=ROOM, name="scatter", levels=VIEW_LEVELS,
                origin_um=(0.0, 0.0, 0.0))
        view.add(PlacedTile(store=store, lands_at=lands))
    assert view is not None
    view.finish()
    return time.monotonic() - began


def check_pointers(work: Path, spots: list[tuple[int, int]]) -> tuple[int, int]:
    """Follow random pointers; each answering tile must prove it covers the piece."""
    view = work / "scatter.ome.zarr"
    rng = np.random.default_rng(23)
    rows, columns = ROOM[1] // PIECE, ROOM[2] // PIECE
    followed = empty = 0
    for _ in range(3000):
        down = int(rng.integers(0, rows))
        across = int(rng.integers(0, columns))
        found = linking.the_bytes_behind(view, f"0/0/0/0/{down}/{across}")
        if found is None:
            empty += 1
            continue
        named = found.path.split("/")
        tile = zarr.open_group(str(work / named[0] / named[1]), mode="r")
        number = int(np.asarray(tile[named[2]])[0, 0].flat[0])
        y, x = spots[number]
        piece_y, piece_x = down * PIECE, across * PIECE
        assert (y <= piece_y < y + TILE[1] and x <= piece_x < x + TILE[2]), (
            f"piece {down},{across} was answered by tile {number} at ({y}, {x}), "
            "which does not cover it")
        followed += 1
    return followed, empty


def open_zoom_and_report(
    work: Path, spots: list[tuple[int, int]], headed: bool = False,
) -> None:
    from playwright.sync_api import sync_playwright
    from server import make_server

    httpd = make_server(port=0, data_dir=work,
                        site_dir=VIZ / "frontend" / "dist",
                        store="scatter.ome.zarr", live=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{httpd.server_address[1]}"
    asked: Counter = Counter()

    # Somewhere bright to zoom in on: a tile from the middle of the list, since
    # tile number is brightness and the first tiles are nearly black.
    aimed = len(spots) * 7 // 10
    target_y = spots[aimed][0] + TILE[1] // 2
    target_x = spots[aimed][1] + TILE[2] // 2

    with sync_playwright() as pw:
        # Launching twice in quick succession — the probe for Playwright's own
        # browser failing over to the machine's — sometimes fells Chromium at
        # startup. A moment's patience and a second try is all it needs.
        for attempt in range(3):
            try:
                browser = another_browser(pw, headed)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
        say_what_is_drawing(browser)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("request", lambda r: asked.update(
            pieces=1) if "/data/" in r.url else None)
        try:
            began = time.monotonic()
            page.goto(address, wait_until="domcontentloaded")
            page.wait_for_function(
                "() => window.zmartViewer !== undefined", timeout=600_000)
            page.wait_for_function(SETTLED, timeout=600_000)
            print(f"  fully loaded from a cold page   "
                  f"{time.monotonic() - began:6.2f} s   "
                  f"{asked['pieces']:>4} pieces")

            # The whole stage, then a ladder of zooms from a tile outwards.
            # Note the position is moved through the pose object directly:
            # rebuilding the whole state detaches the navigation objects a
            # later zoomBy would reach, and every step quietly stops working.
            page.click("text=Centre")
            page.wait_for_timeout(300)
            page.evaluate("window.zmartViewer.navigationState.zoomBy(100)")
            page.wait_for_timeout(300)
            page.wait_for_function(SETTLED, timeout=600_000)
            print(f"  whole stage fitted              "
                  f"{time.monotonic() - began:6.2f} s   "
                  f"{asked['pieces']:>4} pieces in total")

            page.evaluate(f"""() => {{
                const pos = window.zmartViewer.navigationState.pose.position;
                const v = pos.value;
                v[v.length - 1] = {target_x};
                v[v.length - 2] = {target_y};
                pos.changed.dispatch();
                window.zmartViewer.navigationState.zoomBy(1 / 100);
            }}""")
            where = _the_middle_of(page)
            print("  a ladder of zooms from that tile outwards:")
            for step, out in enumerate([1, 4, 4, 4, 4]):
                if out > 1:
                    page.evaluate(
                        f"window.zmartViewer.navigationState.zoomBy({out})")
                before = asked["pieces"]
                began = time.monotonic()
                page.wait_for_timeout(300)
                page.wait_for_function(SETTLED, timeout=600_000)
                took = time.monotonic() - began
                lit = _lit(page, where)
                print(f"    zoomed out {4 ** step:>4}x   settled "
                      f"{took:5.2f} s   {asked['pieces'] - before:>4} new "
                      f"pieces   middle {lit * 100:3.0f}% specimen")
        finally:
            page.close()
            browser.close()
            httpd.shutdown()
            thread.join(timeout=5)


def main() -> None:
    import argparse

    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument(
        "count", type=int, nargs="?", default=10_000,
        help="how many positions to scatter (default 10,000)",
    )
    parsing.add_argument(
        "--headed", action="store_true",
        help="open a visible window, which on Windows is the only way the "
             "browser reaches the graphics card — headless Chromium draws in "
             "SwiftShader whatever arguments it is given",
    )
    asked = parsing.parse_args()
    count = asked.count
    work = Path(tempfile.mkdtemp(prefix="scatter-"))
    try:
        spots = scatter(np.random.default_rng(11), count)
        overlapping = _how_many_overlap(spots)
        print(f"placing {count} positions at random over "
              f"{ROOM[1]} x {ROOM[2]} voxels, {overlapping} of them "
              "overlapping another ...")
        building = build(work, spots)
        print(f"  linked in {building:.1f} s, positions written included "
              f"({building * 1000 / count:.0f} ms each)")
        followed, empty = check_pointers(work, spots)
        print(f"  {followed} pointers followed and proven to cover their "
              f"piece; {empty} asks were empty ground")
        open_zoom_and_report(work, spots, asked.headed)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
