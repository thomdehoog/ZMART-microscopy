"""One growing picture of real specimen: the Thy1 spiral as a single source.

The earlier attempt (``show_thy1_spiralling.py``) put each block on screen as
its own image, and forty-nine images is the arrangement this project measured
its way out of: the drawing engine pays for every source on every frame. This
one shows the same spiral the way ZMART means a survey to be shown — as **one
picture**, composed on request from the blocks' own files, none of them copied.

The pieces:

- The blocks are junction-stores: each a tiny description of where it sits,
  with its zoom levels pointing back at one real Thy1 tile. Made by
  ``show_thy1_spiralling.py --prepare`` / its ``_place_a_block``.
- ``declare_a_built_picture`` writes the description of the one picture over
  whatever blocks exist right now. The composer builds each piece as the
  browser asks, in all three dimensions — the picture keeps the tiles' full
  pyramid, depth included, so the flat view, the volume view and every zoom
  work exactly as they do on the original acquisition.
- When a block lands, the picture is declared again (its extent has grown)
  and the viewer is told something changed in place. The page re-reads the
  description and lets go of what it had decoded; only what is on screen is
  fetched again.

Run it with::

    python show_thy1_one_source.py --across 7 --every 1.0 \
        --blocks "D:/OMEzarr data/zmart-thy1-spiral" --shown D:/zmart-thy1-onesource
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

_VIZ = Path(__file__).resolve().parents[1]
_BUILDING = _VIZ / "app" / "picture"
sys.path.insert(0, str(_BUILDING))
sys.path.insert(0, str(_VIZ / "measure"))

import measure_a_governed_run_at_scale as harness  # noqa: E402,F401  (puts the backend on the path)
from declare import declare_a_built_picture  # noqa: E402
from server import make_server  # noqa: E402
from show_thy1_spiralling import _place_a_block, _spiral, _the_tile_we_borrow  # noqa: E402

# The display window measured from the tile itself: background just under 400,
# ninety-nine percent of the specimen below about 2,100.
WINDOW = (400.0, 2500.0)


def _announce(port: int) -> str:
    """Tell every open page that the picture changed under it.

    The answer says how many pages heard, and it is returned rather than
    swallowed: a run of this show once went an entire spiral with nobody
    hearing a word, and the silence read as a viewer bug for half an evening.
    """
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/announce",
            data=json.dumps({"wrote_image_in_place": True}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as answer:
            return f"told {json.load(answer).get('told', 0)}"
    except OSError as wrong:
        return f"announce failed: {wrong}"


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument("--blocks", required=True,
                         help="the folder the junction blocks are made in")
    parsing.add_argument("--shown", required=True,
                         help="the folder the picture's description lives in")
    parsing.add_argument("--across", type=int, default=7)
    parsing.add_argument("--every", type=float, default=1.0)
    parsing.add_argument("--port", type=int, default=8862)
    asked = parsing.parse_args()

    blocks, shown = Path(asked.blocks), Path(asked.shown)
    for folder in (blocks, shown):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)

    tile, described, levels, apart = _the_tile_we_borrow()
    cells = _spiral(asked.across)

    # The centre block, and the two far corners. The corners are there to pin
    # the picture's extent: the declared shape is derived from the blocks that
    # exist, so with the opposite corners down from the start the canvas covers
    # the whole survey and no later landing ever changes its shape. That
    # matters because the page's in-place refresh re-reads pixels, not the
    # description -- a picture that keeps its shape grows on screen, where one
    # that grows its shape only grows after a reload.
    pinned = [cells[0], (0, 0), (asked.across - 1, asked.across - 1)]
    for number, (row, column) in enumerate(pinned):
        _place_a_block(blocks, number, row, column, described, levels, tile,
                       apart)
    picture = declare_a_built_picture(shown, blocks, name="spiral")
    print(f"declared over {len(pinned)} blocks (centre + corners): {picture}",
          flush=True)

    dist = _VIZ / "app" / "page" / "dist"
    server = make_server(port=asked.port, data_dir=shown, site_dir=dist,
                         store=[picture.name], window=WINDOW, live=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f"http://127.0.0.1:{asked.port}"
    print(f"\n=== {address} — one picture, growing ===\n", flush=True)
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Start-Process chrome '{address}'"],
                   check=False, timeout=30)
    time.sleep(6.0)

    already = set(pinned)
    landed = len(pinned)
    for number, (row, column) in enumerate(cells[1:], start=len(pinned)):
        if (row, column) in already:
            continue
        _place_a_block(blocks, number, row, column, described, levels, tile,
                       apart)
        declare_a_built_picture(shown, blocks, name="spiral")
        heard = _announce(asked.port)
        landed += 1
        print(f"  block {landed}/{len(cells)} at row {row} column {column}"
              f"  ({heard})", flush=True)
        time.sleep(asked.every)

    print("\nthe survey is complete; still serving. Ctrl+C to stop.", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
