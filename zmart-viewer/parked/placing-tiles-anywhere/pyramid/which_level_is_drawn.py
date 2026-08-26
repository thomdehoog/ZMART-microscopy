"""Ask the photograph, rather than the traffic, which size of the picture was drawn.

Counting what the server was asked for turns out to settle nothing. This picture
is small, and the engine fetches every piece of every size at every zoom — it
reaches for the eighth-size ones first and works its way down, which is how it
gets something on screen quickly, but by the time the picture has settled it holds
all four sizes. So the traffic cannot say which one is on the screen.

This settles it by making the sizes tell themselves apart. The same composing
server runs, but each size paints one small rectangle of the picture — always the
same rectangle of real ground, so it lands in the same place on screen at every
zoom — in a brightness of its own. Then the photograph is read at that spot. The
brightness found there names the size that was drawn, and nothing has to be
assumed about how the engine chooses.

This is a diagnostic and it deliberately spoils the picture, which is why it is a
separate run from the photographs in `drive_it.py` and from the voxel-by-voxel
checking in `check.py`. Neither of those is affected by it.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

REPO = Path("/home/user/ZMART-microscopy")
for extra in (REPO, REPO / "viz_studio" / "options" / "measure", REPO / "viz_studio"):
    sys.path.insert(0, str(extra))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import drive
import geometry as g
import numpy as np
from acquisitions import write_the_square
from compose import Composer
from compose_server import STORE, serve
from many_sources import _the_page_can_open_a_viewer

HERE = Path(__file__).resolve().parent
POSITIONS = HERE / "run" / "pyramid.ome.zarr" / "positions"
DATA, OUT = HERE / "page-data", HERE / "frames"

# The patch of real ground each size paints in its own brightness, in full-size
# voxels. Both edges are multiples of 64, so the patch divides exactly at every
# size and never lands half on a voxel.
MARK = (192, 320, 448, 576)          # y from, y to, x from, x to
# What each size paints there. Far enough apart in brightness that no two could be
# confused, and clear of the ten brightnesses the tiles themselves use.
MARK_VALUE = {0: 500, 1: 1500, 2: 2500, 3: 3500}
WINDOW_HIGH = 4095                   # what the channel maps to full white

CENTRE = {"x": g.SPAN_X * g.VOXEL_UM / 2, "y": g.SPAN_Y * g.VOXEL_UM / 2}
ZOOMS = [0.4, 1.0, 2.0, 4.0]


class Marked(Composer):
    """The ordinary composer, with each size painting its own name on the picture."""

    def compose(self, level: int, cy: int, cx: int) -> np.ndarray:
        piece = super().compose(level, cy, cx)
        factor = 2 ** level
        y0, y1, x0, x1 = (edge // factor for edge in MARK)
        # Where the patch and this piece overlap, in this size's own voxels.
        py, px = cy * g.CHUNK, cx * g.CHUNK
        ay, by = max(y0, py), min(y1, py + g.CHUNK)
        ax, bx = max(x0, px), min(x1, px + g.CHUNK)
        if ay < by and ax < bx:
            piece[ay - py:by - py, ax - px:bx - px] = MARK_VALUE[level]
        return piece


def expected_greys() -> dict[int, float]:
    """What brightness each size's patch should come out as in a photograph.

    The channel is shown from black at zero to white at 4095, with nothing in
    between but a straight line, so the arithmetic is simply a proportion.
    """
    return {level: value / WINDOW_HIGH * 255 for level, value in MARK_VALUE.items()}


def main() -> None:
    composer = Marked(POSITIONS, g.PLACES)
    server, address, ledger = serve(POSITIONS, g.PLACES, composer=composer)
    print(f"the marking server is on {address}")
    print("each size paints the same patch of ground in its own brightness:")
    for level, grey in expected_greys().items():
        print(f"   level {level}: value {MARK_VALUE[level]} — "
              f"grey {grey:.0f} out of 255")

    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    write_the_square(DATA)
    OUT.mkdir(parents=True, exist_ok=True)

    acquisitions = [{
        "url": f"{address}/{STORE}/|zarr3:",
        "name": "marked",
        "channels": [{"name": "probe", "colour": [1, 1, 1],
                      "window": {"low": 0, "high": WINDOW_HIGH}}],
    }]

    found = []
    with drive.Harness(DATA, OUT, option="neuroglancer-under") as harness:
        harness.open(store="square", draw="none")
        _the_page_can_open_a_viewer(harness)
        box = harness.page.evaluate(
            "() => { const r = document.getElementById('viewer')"
            ".getBoundingClientRect();"
            " return {left: r.left, top: r.top, width: r.width, height: r.height}; }")

        for zoom in ZOOMS:
            harness.page.evaluate(
                "([acquisitions, view]) => window.manySources.open(acquisitions, view)",
                [acquisitions, {"centre": CENTRE, "zoom": zoom}],
            )
            time.sleep(1.0)
            harness.settle(tries=60)
            shot = harness.photograph()
            harness.save_frame(shot, f"marked-{zoom}")
            grey = shot.astype(float).mean(axis=2)

            # Where the marked patch should be on the screen, worked out from the
            # geometry and the view rather than hunted for.
            middle_y = (MARK[0] + MARK[1]) / 2 * g.VOXEL_UM
            middle_x = (MARK[2] + MARK[3]) / 2 * g.VOXEL_UM
            reach = (MARK[1] - MARK[0]) / 2 * g.VOXEL_UM / zoom   # half its width
            screen_y = box["top"] + box["height"] / 2 + \
                (middle_y - CENTRE["y"]) / zoom
            screen_x = box["left"] + box["width"] / 2 + \
                (middle_x - CENTRE["x"]) / zoom
            half = max(2, int(reach * 0.4))
            patch = grey[int(screen_y) - half:int(screen_y) + half,
                         int(screen_x) - half:int(screen_x) + half]
            here = float(patch.mean())
            spread = float(patch.std())
            nearest = min(expected_greys(), key=lambda one: abs(expected_greys()[one] - here))

            # And the same answer a second way, without trusting the arithmetic
            # above: how much of the whole window is within a hair of each size's
            # own brightness. Only the size that was drawn should show a large area.
            areas = {level: int((np.abs(grey - value) < 3).sum())
                     for level, value in expected_greys().items()}

            found.append((zoom, here, spread, nearest, areas))
            print(f"\n{zoom} micrometres to the pixel")
            print(f"   the patch is {2 * half} by {2 * half} screen pixels, "
                  f"centred at ({screen_x:.0f}, {screen_y:.0f})")
            print(f"   brightness found there : {here:.1f} "
                  f"(evenness: spread {spread:.2f})")
            print(f"   which names size       : level {nearest}")
            print("   pixels in the whole window at each size's brightness: "
                  + ", ".join(f"level {level}: {count}"
                              for level, count in areas.items()))

    print("\nsummary — which size of the picture reached the screen")
    print(f"{'zoom (um/px)':>13}  {'brightness at the patch':>23}  "
          f"{'size that names':>15}  {'largest area':>13}")
    for zoom, here, _spread, nearest, areas in found:
        biggest = max(areas, key=lambda one: areas[one])
        print(f"{zoom:>13}  {here:>23.1f}  {f'level {nearest}':>15}  "
              f"{f'level {biggest} ({areas[biggest]} px)':>13}")

    server.shutdown()


if __name__ == "__main__":
    main()
