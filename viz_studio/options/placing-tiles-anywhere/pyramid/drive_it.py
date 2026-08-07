"""Open the composed pyramid in the real viewer and photograph it at four zooms.

Nothing here is a mock. The page is the viewer's own harness, the drawing engine
is the one the viewer ships with, and the only thing it is given is the address of
the composing server — which holds no picture and makes every piece, at whichever
size, as it is asked for.

The point of looking four times is to make the engine choose a different size each
time. Which size it chose is not guessed at from the photograph: the server keeps
a note of which size each piece it was asked for belonged to, so the answer comes
from the traffic rather than from an impression of how blurry the picture looks.
"""

from __future__ import annotations

import shutil
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/home/user/ZMART-microscopy")
for extra in (REPO, REPO / "viz_studio" / "options" / "measure", REPO / "viz_studio"):
    sys.path.insert(0, str(extra))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import drive
from acquisitions import write_the_square
from many_sources import which_engine_is_drawing, lit_share, _the_page_can_open_a_viewer

import geometry as g
from compose_server import serve, STORE

HERE = Path(__file__).resolve().parent
POSITIONS = HERE / "run" / "pyramid.ome.zarr" / "positions"
DATA, OUT = HERE / "page-data", HERE / "frames"

# Where to look. The imaged ground is 972 by 435 voxels of half a micrometre, so
# 486 by 218 micrometres, and the middle of that is where the view is centred every
# time. Only the closeness changes.
CENTRE = {"x": g.SPAN_X * g.VOXEL_UM / 2, "y": g.SPAN_Y * g.VOXEL_UM / 2}

# How close to look, in micrometres to the screen pixel. A full-size voxel is half
# a micrometre, so at 0.4 the engine has roughly one full-size voxel per pixel and
# should draw the full-size picture; each doubling should move it one size down the
# pyramid. Should, rather than will — the engine decides, and what it decided is
# read back from the server afterwards.
ZOOMS = [
    ("closest", 0.4),
    ("one step out", 1.0),
    ("two steps out", 2.0),
    ("furthest out", 4.0),
]

# How many lit pixels count as "something of the specimen is on the screen". A
# count rather than a share, because zoomed all the way out the specimen honestly
# occupies only about a hundredth of the window, and a share-based test would be
# measuring its own threshold rather than the engine.
ENOUGH_LIT = 500
LONGEST_WAIT_S = 120.0


def lit_pixels(picture) -> int:
    return int((np.asarray(picture).astype(int).max(axis=2) > 60).sum())


def main() -> None:
    server, address, ledger = serve(POSITIONS, g.PLACES)
    store_url = f"{address}/{STORE}/|zarr3:"
    print(f"the composing server is on {address}, serving {STORE} "
          f"at {g.LEVELS} sizes")

    # The harness page needs a run of its own to start on — it cuts a hole in the
    # operator's drawing around imaged ground and refuses to boot without a record
    # of where that is. Ours is opened afterwards, by address, so the square below
    # is only what the page stands on while it starts.
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    write_the_square(DATA)
    OUT.mkdir(parents=True, exist_ok=True)

    acquisitions = [{
        "url": store_url,
        "name": "pyramid",
        "channels": [{"name": "probe", "colour": [1, 1, 1],
                      "window": {"low": 0, "high": 4095}}],
    }]

    results = []
    with drive.Harness(DATA, OUT, option="neuroglancer-under") as harness:
        harness.open(store="square", draw="none")
        _the_page_can_open_a_viewer(harness)

        for name, zoom in ZOOMS:
            # A fresh viewer each time, so that what is being timed is a picture
            # arriving from nothing rather than one the engine still had in hand.
            before = {level: ledger["pieces"][level] for level in range(g.LEVELS)}
            before_ms = {level: len(ledger["compose_ms"][level])
                         for level in range(g.LEVELS)}
            before_order = len(ledger["order"])
            started = time.perf_counter()
            harness.page.evaluate(
                "([acquisitions, view]) => window.manySources.open(acquisitions, view)",
                [acquisitions, {"centre": CENTRE, "zoom": zoom}],
            )

            # Time to first pixel, read off the screen rather than asked of the
            # engine: the first photograph in which anything of the specimen is lit.
            first_pixel = None
            lit_at = None
            while time.perf_counter() - started < LONGEST_WAIT_S:
                if lit_pixels(harness.photograph()) > ENOUGH_LIT:
                    lit_at = time.perf_counter()
                    first_pixel = lit_at - started
                    break
            harness.settle(tries=40)
            shot = harness.photograph()
            saved = harness.save_frame(shot, f"pyramid-{name.replace(' ', '-')}")

            asked = {level: ledger["pieces"][level] - before[level]
                     for level in range(g.LEVELS)}
            composed = {level: ledger["compose_ms"][level][before_ms[level]:]
                        for level in range(g.LEVELS)}
            work = {level: ledger["work_ms"][level][before_ms[level]:]
                    for level in range(g.LEVELS)}
            drew = [level for level in range(g.LEVELS) if asked[level]]

            # Which size the engine reached for first, and which sizes it had
            # actually been given by the time something appeared on the screen.
            # The picture on screen at that moment can only have been drawn out of
            # pieces already delivered, so this is the evidence for which size was
            # drawn — the engine goes on to fetch the whole pyramid of this small
            # picture whatever the zoom, so simply counting what arrived says
            # nothing at all.
            sequence = ledger["order"][before_order:]
            reached_for_first = [level for _, _, level, _, _ in sequence[:6]]
            by_first_pixel = {level: 0 for level in range(g.LEVELS)}
            if lit_at is not None:
                for _, finished, level, _, _ in sequence:
                    if finished <= lit_at:
                        by_first_pixel[level] += 1

            results.append({
                "name": name, "zoom": zoom, "first_pixel": first_pixel,
                "lit": lit_share(shot), "asked": asked, "drew": drew,
                "composed": composed, "frame": saved,
                "first_six": reached_for_first, "by_first_pixel": by_first_pixel,
            })
            print(f"\n{name} — {zoom} micrometres to the pixel")
            print(f"   time to first pixel on screen : "
                  + (f"{first_pixel:.2f} s" if first_pixel is not None
                     else "nothing was ever lit"))
            print(f"   share of the window lit       : {lit_share(shot)}")
            print(f"   pieces asked for, by size     : "
                  + ", ".join(f"level {level}: {asked[level]}"
                              for level in range(g.LEVELS)))
            print(f"   the first six it asked for    : sizes "
                  f"{reached_for_first}")
            print(f"   served before anything was lit: "
                  + ", ".join(f"level {level}: {by_first_pixel[level]}"
                              for level in range(g.LEVELS)))
            for level in drew:
                print(f"      composing one level-{level} piece, median "
                      f"{statistics.median(composed[level]):.1f} ms (of which "
                      f"{statistics.median(work[level]):.1f} ms was the work "
                      f"itself, the rest waiting its turn), "
                      f"worst {max(composed[level]):.1f} ms, "
                      f"all of them {sum(composed[level]):.0f} ms")
            print(f"   screenshot                    : {OUT / saved}")

        print("\nwhich engine drew this, asked of the page:")
        for key, value in which_engine_is_drawing(harness).items():
            print(f"   {key}: {value}")

        failed = harness.page.evaluate("() => window.manySources.failed")
        if failed:
            print(f"\nthe viewer reported a failure:\n{failed}")
        if ledger["refused"]:
            print(f"\nasked for and not there       : "
                  f"{sorted(set(ledger['refused']))[:10]}")
        noisy = [line for line in harness.console
                 if "error" in line.lower() or "warn" in line.lower()]
        if noisy:
            print("\nwhat the page said:")
            for line in noisy[:20]:
                print(f"   {line}")

    print("\nsummary")
    print(f"{'zoom (um/px)':>13}  {'first six asked for':>21}  "
          f"{'served by first pixel':>34}  {'pieces in all':>13}  "
          f"{'first pixel s':>13}  {'window lit':>10}")
    for one in results:
        served = ", ".join(f"L{level}: {count}"
                           for level, count in one["by_first_pixel"].items())
        print(f"{one['zoom']:>13}  "
              f"{str(one['first_six']):>21}  {served:>34}  "
              f"{sum(one['asked'].values()):>13}  "
              + (f"{one['first_pixel']:>13.2f}" if one['first_pixel'] is not None
                 else f"{'never':>13}")
              + f"  {one['lit']:>10}")

    server.shutdown()


if __name__ == "__main__":
    main()
