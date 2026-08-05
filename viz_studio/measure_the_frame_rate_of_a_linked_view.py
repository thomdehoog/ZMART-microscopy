"""Does showing a run as one picture keep the viewer's drawing rate up?

What this is asking
-------------------

``viz_studio/tests/test_the_drawing_keeps_up.py`` records the fault this measures
against, and it is the worst one the project has found. With a thousand positions
open the viewer managed **24 frames in five seconds** where a hundred positions
managed 302. Three drawing layers are made for every position and each one takes
part in every frame, so the cost is paid on every draw for as long as the run is
open. Slow *loading* ends; this does not. `NEXT_STEPS.md` calls the fix
architectural: the engine has to be holding fewer positions.

A linked view — :mod:`zmart_storage.linked` — hands the viewer **one** store no
matter how many tiles are underneath it. If the cost really is paid per position,
then a run shown that way should keep its drawing rate whatever its size, and the
architectural fix is a thing that already exists.

That is a claim about how the viewer builds its layers, and until this script was
written nobody had measured it. So this measures it: the *same* tiles, opened both
ways, frames counted in a real browser.

How it goes about it
--------------------

It climbs. One tile, then a few, then more, and it prints each row as soon as that
row is done — so a run that is taking too long can be stopped at any point and
everything measured so far is already on screen. Before starting a step it works
out roughly what that step will cost from what the last one actually cost, and
stops rather than begin one that would run past the time allowed. A measurement
that has to be babysat does not get run.

**Everything here is a comparison, never an absolute number.** A machine with no
graphics card draws slowly whatever it is given, so "so many frames per second"
would mean nothing and would need retuning for every machine. What is reported is
how the two arrangements compare *on the machine you are sitting at*, which holds
anywhere.

Running it
----------

::

    python viz_studio/measure_the_frame_rate_of_a_linked_view.py
    python viz_studio/measure_the_frame_rate_of_a_linked_view.py --budget 900
    python viz_studio/measure_the_frame_rate_of_a_linked_view.py --steps 1,5,20,50

It needs the viewer page to have been built (``npm --prefix viz_studio/frontend run
build``) and a Chromium it can drive. It writes tiny tiles into a temporary folder
and removes them afterwards.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

_VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(_VIZ / "backend"))
sys.path.insert(0, str(_VIZ / "tests"))
sys.path.insert(0, str(_VIZ.parent))

from server import make_server  # noqa: E402

from zmart_storage.canvas import Channel, _declare_one  # noqa: E402
from zmart_storage.linked import PlacedTile, link_the_tiles  # noqa: E402

# Deliberately tiny. What is being measured is the cost of *how many* things are
# open, not how much picture there is, and small tiles keep the writing quick
# enough that the climb can reach interesting numbers.
TILE = (1, 64, 64)
PIECE = 64
VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (11.0, 5.5, 7.25)

# How long to count frames for, at each size, for each arrangement. Long enough to
# average over a slow patch, short enough that the climb stays affordable.
SAMPLE_SECONDS = 3.0

# How far to climb unless told otherwise. Each step is a few times the one before,
# because the fault being looked for shows up as an *order of magnitude* rather
# than a few per cent.
STEPS = (1, 5, 20, 50, 100, 200, 400, 800, 1600)

# Counting frames the way the browser really draws them. Started once and only
# once: two loops would both count and read as the page having doubled its rate.
COUNT_FRAMES = """() => {
  if (window.__counting) return;
  window.__counting = true;
  window.__drawn = 0;
  const tick = () => { window.__drawn += 1; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}"""

# Keep the view moving while frames are counted. A page with nothing to redraw is
# not being asked the question: the cost being looked for is paid per frame, so
# there have to be frames.
KEEP_MOVING = """() => {
  if (window.__nudging) return;
  window.__nudging = true;
  let forward = true;
  window.__nudge = setInterval(() => {
    const nav = window.zmartViewer.navigationState;
    const at = Float32Array.from(nav.position.value);
    at[at.length - 1] += forward ? 0.5 : -0.5;
    forward = !forward;
    nav.position.value = at;
  }, 16);
}"""

# How many pictures the viewer is actually holding. Counted from the engine rather
# than from what we asked for, so a store that failed to load is not counted as
# though it had.
HELD = """() => window.zmartViewer.layerManager.managedLayers
           .filter((managed) => managed.layer && managed.layer.type === 'image')
           .reduce((total, managed) => total + managed.layer.dataSources.length, 0)"""


def a_row_of_tiles(folder: Path, count: int) -> list[PlacedTile]:
    """Write ``count`` tiles side by side, each landing on a whole piece boundary.

    They butt up against one another rather than overlapping, which is the
    arrangement a linked view can always take, so that what is being compared is
    the number of things open and nothing else.
    """
    folder.mkdir(parents=True, exist_ok=True)
    placed = []
    for index in range(count):
        lands_x = index * TILE[2]
        store = folder / f"tile{index:05d}.ome.zarr"
        arrays = _declare_one(
            store,
            canvas_shape=TILE,
            frames=1,
            channels=1,
            dtype="uint16",
            chunk=PIECE,
            levels=1,
            voxel_size_um=VOXEL_UM,
            origin_um=(ORIGIN_UM[0], ORIGIN_UM[1],
                       ORIGIN_UM[2] + lands_x * VOXEL_UM[2]),
            channel_blocks=[Channel("488", window=(0, 4000)).described(65535)],
        )
        # Something with structure in it, so the picture is not one flat value that
        # compresses to nothing and draws unrealistically fast.
        y, x = np.indices(TILE[1:], dtype=np.float32)
        across = (
            400 + 200 * np.sin(y / 7) + 200 * np.cos((x + lands_x) / 9)
        ).astype("uint16")
        arrays[0][0, 0] = np.broadcast_to(across, TILE)
        placed.append(PlacedTile(store=store, lands_at=(0, 0, lands_x)))
    return placed


def frames_counted(browser, built_dist: Path, folder: Path, store, expect: int) -> int:
    """Open what ``store`` names, wait until it has all arrived, then count frames.

    Waiting matters. Counting while stores are still being fetched would measure
    the loading, which is a different question with its own measurement.
    """
    server = make_server(
        port=0, data_dir=folder, site_dir=built_dist, store=store, live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})
    try:
        page.goto(
            f"http://127.0.0.1:{server.server_address[1]}",
            wait_until="domcontentloaded",
        )
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(f"{HELD} >= {expect}", timeout=300_000)
        page.wait_for_function(
            "() => window.zmartSourcesWaiting() === 0", timeout=300_000
        )
        page.wait_for_timeout(3000)
        page.evaluate(KEEP_MOVING)
        page.evaluate(COUNT_FRAMES)
        page.evaluate("() => { window.__drawn = 0; }")
        page.wait_for_timeout(int(SAMPLE_SECONDS * 1000))
        drawn = int(page.evaluate("() => window.__drawn"))
        page.evaluate("() => clearInterval(window.__nudge)")
        return drawn
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def a_browser():
    """A headless Chromium with software drawing, or a plain explanation of why not.

    Software drawing is needed because the engine wants WebGL2 and most machines
    running this have no graphics card. A machine whose policy blocks the browser
    that was downloaded is offered the one it already has.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "playwright is not installed, so no browser could be driven. "
            "Install it with `pip install playwright`."
        )
    started = sync_playwright().start()
    args = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]
    try:
        return started, started.chromium.launch(args=args)
    except Exception:
        from conftest import find_a_chromium
        already_here = find_a_chromium()
        if already_here is None:
            started.stop()
            raise SystemExit(
                "no Chromium on this machine that could be driven, so frames "
                "cannot be counted here."
            )
        return started, started.chromium.launch(
            executable_path=str(already_here), args=args
        )


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument(
        "--budget", type=float, default=1800.0,
        help="how many seconds to spend in total before stopping (default 1800)",
    )
    parsing.add_argument(
        "--steps", type=str, default=None,
        help="tile counts to climb through, comma separated",
    )
    asked = parsing.parse_args()
    steps = (
        [int(n) for n in asked.steps.split(",")] if asked.steps else list(STEPS)
    )

    built = _VIZ / "frontend" / "dist"
    if not (built / "index.html").is_file():
        raise SystemExit(
            f"the viewer page has not been built ({built} holds no index.html), so "
            "there is nothing for a browser to open. Build it with:\n"
            "  npm --prefix viz_studio/frontend install\n"
            "  npm --prefix viz_studio/frontend run build"
        )

    started, browser = a_browser()
    work = Path(tempfile.mkdtemp(prefix="frame-rate-"))
    began = time.time()
    print()
    print("Frames drawn in "
          f"{SAMPLE_SECONDS:.0f} seconds of moving through the specimen.")
    print("Separate = one store per tile.  Linked = the same tiles as one picture.")
    print()
    print(f"{'tiles':>7}  {'separate':>9}  {'linked':>7}  {'linked keeps':>13}  "
          f"{'step took':>10}")
    print("-" * 58)

    took_last = 0.0
    last_count = 0
    try:
        for count in steps:
            spent = time.time() - began
            # What this step will cost, guessed from the last one. The work grows
            # with the number of tiles, so scaling the last measurement by how much
            # bigger this step is gets close enough to decide by.
            likely = (
                took_last * (count / last_count) if last_count else 90.0
            )
            if spent + likely > asked.budget:
                print(f"\nStopping before {count} tiles: it would likely take "
                      f"{likely:.0f}s and only {asked.budget - spent:.0f}s of the "
                      f"budget is left. Everything above is measured.")
                break

            step_began = time.time()
            folder = work / f"run{count:05d}"
            placed = a_row_of_tiles(folder, count)
            link_the_tiles(
                folder, name="linked", tiles=placed,
                view_shape=(TILE[0], TILE[1], count * TILE[2]),
            )
            names = sorted(p.name for p in folder.glob("tile*.ome.zarr"))

            try:
                separate = frames_counted(browser, built, folder, names, count)
            except Exception as why:
                separate = -1
                print(f"  ({count} separate stores did not finish: "
                      f"{type(why).__name__})")
            try:
                linked = frames_counted(
                    browser, built, folder, "linked.ome.zarr", 1
                )
            except Exception as why:
                linked = -1
                print(f"  (the linked view did not finish: {type(why).__name__})")

            took_last = time.time() - step_began
            last_count = count
            keeps = (
                f"{linked / separate:>12.2f}x" if separate > 0 and linked > 0
                else f"{'—':>13}"
            )
            print(f"{count:>7}  {separate:>9}  {linked:>7}  {keeps}  "
                  f"{took_last:>9.0f}s")
            # Each size is written fresh, and at the top of the climb that is a lot
            # of small files. Letting them go as we climb keeps the disk flat.
            shutil.rmtree(folder, ignore_errors=True)
    except KeyboardInterrupt:
        print("\nStopped. Everything above is measured.")
    finally:
        browser.close()
        started.stop()
        shutil.rmtree(work, ignore_errors=True)

    print()
    print("A linked view hands the viewer one store however many tiles are under")
    print("it, so if the drawing cost is paid per position the last column should")
    print("climb with the first. If it stays near 1, the cost is somewhere else.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
