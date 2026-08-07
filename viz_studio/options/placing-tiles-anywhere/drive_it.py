"""Open the composed picture in the real viewer and photograph what it drew.

Nothing here is a mock. The page is the viewer's own harness, the drawing engine
is the one the viewer ships with, and the only thing it is given is the address
of the composing server — which holds no picture and makes every piece as it is
asked for.
"""

from __future__ import annotations

import json
import shutil
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/home/user/ZMART-microscopy")
for extra in (REPO, REPO / "viz_studio" / "options" / "measure", REPO / "viz_studio"):
    sys.path.insert(0, str(extra))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import drive
from acquisitions import write_the_square
from many_sources import which_engine_is_drawing, lit_share, _the_page_can_open_a_viewer

import geometry as g
from compose_server import serve, STORE

HERE = Path(__file__).resolve().parent
POSITIONS = HERE / "run" / "anywhere.ome.zarr" / "positions"
DATA, OUT = HERE / "page-data", HERE / "frames"

# Where to look and how closely. The whole canvas is 640 voxels of half a
# micrometre, so 320 micrometres across; the window is 700 pixels tall, and a
# little under half a micrometre to the pixel puts all of it comfortably inside.
CANVAS_UM = g.CANVAS * 0.5
VIEW = {"centre": {"x": CANVAS_UM / 2, "y": CANVAS_UM / 2}, "zoom": 0.46}


def main() -> None:
    server, address, ledger = serve(POSITIONS, g.PLACES)
    store_url = f"{address}/{STORE}/|zarr3:"
    print(f"the composing server is on {address}, serving {STORE}")

    # The harness page needs a run of its own to start on — it cuts a hole in the
    # operator's drawing around imaged ground and refuses to boot without a
    # record of where that is. Ours is opened afterwards, by address, so the
    # square below is only what the page stands on while it starts.
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    write_the_square(DATA)
    OUT.mkdir(parents=True, exist_ok=True)

    acquisitions = [{
        "url": store_url,
        "name": "anywhere",
        "channels": [{"name": "probe", "colour": [1, 1, 1],
                      "window": {"low": 0, "high": 4095}}],
    }]

    with drive.Harness(DATA, OUT, option="neuroglancer-under") as harness:
        harness.open(store="square", draw="none")
        _the_page_can_open_a_viewer(harness)

        # Nothing has been asked of the composing server yet; from here on,
        # everything it is asked for is the viewer asking.
        before = dict(ledger, compose_ms=list(ledger["compose_ms"]))
        started = time.perf_counter()
        harness.page.evaluate(
            "([acquisitions, view]) => window.manySources.open(acquisitions, view)",
            [acquisitions, VIEW],
        )

        # Time to first pixel, read off the screen rather than asked of the
        # engine: the first photograph in which anything of the specimen is lit.
        first_pixel = None
        while time.perf_counter() - started < 120:
            if lit_share(harness.photograph()) > 0.01:
                first_pixel = time.perf_counter() - started
                break
        harness.settle(tries=40)
        shot = harness.photograph()
        saved = harness.save_frame(shot, "composed-anywhere")

        print(f"\ntime to first pixel on screen : "
              f"{first_pixel:.2f} s" if first_pixel is not None
              else "\nnothing was ever lit on screen")
        print(f"share of the window lit       : {lit_share(shot)}")
        print(f"screenshot                    : {OUT / saved}")

        # And a second look, close in on the corner where four positions meet.
        # That corner is at voxel 179 in both directions, which is nothing like a
        # multiple of the 128-voxel piece — so this one photograph holds both the
        # seam between overlapping positions and, invisible, the boundaries
        # between the pieces the server assembled.
        harness.page.evaluate(
            "(view) => window.harness.viewer.setView(view)",
            {"centre": {"x": g.STEP * 0.5, "y": g.STEP * 0.5}, "zoom": 0.1},
        )
        harness.settle(tries=40)
        close = harness.photograph()
        closely = harness.save_frame(close, "composed-anywhere-close")
        print(f"screenshot, close in on a seam: {OUT / closely}")

        asked = ledger["pieces"] - before["pieces"]
        composed = ledger["compose_ms"][before["pieces"]:]
        print(f"\npieces the viewer asked for   : {asked}")
        print(f"descriptions it read          : "
              f"{ledger['descriptions'] - before['descriptions']}")
        if composed:
            print(f"composing one, median         : "
                  f"{statistics.median(composed):.3f} ms")
            print(f"composing one, worst          : {max(composed):.3f} ms")
            print(f"composing all of them         : {sum(composed):.1f} ms")
        if ledger["refused"]:
            print(f"asked for and not there       : "
                  f"{sorted(set(ledger['refused']))[:10]}")

        print("\nwhich engine drew this, asked of the page:")
        for key, value in which_engine_is_drawing(harness).items():
            print(f"   {key}: {value}")

        failed = harness.page.evaluate("() => window.manySources.failed")
        if failed:
            print(f"\nthe viewer reported a failure:\n{failed}")
        noisy = [line for line in harness.console
                 if "error" in line.lower() or "warn" in line.lower()]
        if noisy:
            print("\nwhat the page said:")
            for line in noisy[:20]:
                print(f"   {line}")

    server.shutdown()


if __name__ == "__main__":
    main()
