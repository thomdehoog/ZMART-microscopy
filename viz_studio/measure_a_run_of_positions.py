"""How a run of positions draws, as the number of positions climbs.

This measures the arrangement :mod:`zmart_storage.positions` writes: one zarr per
run, the positions inside it each with their own zoomed-out copies, and a map in
the picture's description saying which piece of the picture is which piece of
which position. Nothing is copied, and the picture the viewer opens holds no
full-size voxels of its own.

The question it answers is the one the whole arrangement exists for. Neuroglancer
builds a drawing layer for every image it is handed, so a run given to it as a
folder of positions gets slower with every position and eventually does not open
at all. Handed a single picture it should not care what is underneath — and
"should not" is a claim, so here it is measured instead.

Run it like this, from the top of the repository::

    python viz_studio/measure_a_run_of_positions.py
    python viz_studio/measure_a_run_of_positions.py --steps 1,10,100,400

**Read the ``lit`` column before any of the others.** It says how much of the
screen actually had specimen on it. An empty panel redraws beautifully, so a frame
rate without it can look excellent and mean nothing — which is not a hypothetical:
the first run of this measurement reported a healthy thirty-five frames a second
with ``lit`` at nought, over a completely black screen. The picture was being
served correctly and drawn at about five per cent of its brightness. Every table
carries the column for that reason.

**And absolute numbers are worth nothing off the machine that made them.** A
sandbox with no graphics card draws in software and is slow whatever it is given.
What carries from one machine to another is the *shape*: whether the middle frame
holds steady as positions are added, and whether the requests stop climbing. If
your figures disagree with any quoted in the repository, yours are the real ones.
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
sys.path.insert(0, str(_VIZ.parent))
sys.path.insert(0, str(_VIZ))
sys.path.insert(0, str(_VIZ / "backend"))
sys.path.insert(0, str(_VIZ / "tests"))

from measure_the_frame_rate_of_a_linked_view import (  # noqa: E402
    COUNT_FRAMES,
    HELD,
    KEEP_MOVING,
    SAMPLE_SECONDS,
    a_browser,
)
from pixels import fraction_lit  # noqa: E402
from server import make_server  # noqa: E402

from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.positions import start_a_run  # noqa: E402

# One position, and how its picture is cut up. Five hundred and twelve voxels
# across is small for a real camera and large enough that a position carries its
# own zoomed-out copies, which is the case worth measuring: with them the picture
# writes nothing at any zoom.
TILE = (1, 512, 512)
PIECE = 128
VOXEL_UM = (2.0, 0.325, 0.325)

# How bright the specimen is asked to be shown. It sits well inside a sixteen-bit
# camera's range on purpose, because that gap is exactly what makes a picture open
# black when the window is not read from the store.
SHOWN_BETWEEN = (400, 3800)

STEPS = (1, 10, 50, 100, 200, 400)


def a_specimen(seed: int) -> np.ndarray:
    """One position's picture, with structure in it rather than flat noise.

    Structure matters here for two reasons. A flat block compresses to almost
    nothing, which would flatter every reading that involves fetching; and it gives
    ``lit`` nothing to be sure about, since a flat field either covers the screen
    or does not.
    """
    rng = np.random.default_rng(seed)
    _, y, x = np.indices(TILE, dtype=np.float32)
    picture = 600 + 60 * rng.standard_normal(TILE)
    for _ in range(30):
        at_y, at_x = rng.uniform(0, TILE[1]), rng.uniform(0, TILE[2])
        spread = rng.uniform(20, 70)
        near = ((y - at_y) ** 2 + (x - at_x) ** 2) / (2 * spread ** 2)
        picture = np.maximum(picture, rng.uniform(2200, 3900) * np.exp(-near))
    return picture.clip(0, 4000).astype("uint16")


def a_run_of(count: int, folder: Path) -> Path:
    """Write ``count`` positions as a squarish mosaic and hand back the picture.

    A mosaic rather than a row, and it matters more than it sounds. Laid out in a
    line, four hundred positions are a picture two hundred thousand voxels wide and
    five hundred tall — a hair on the screen. Almost nothing would be drawn, and
    the rate being measured would mostly be the cost of drawing an empty panel.
    """
    across = int(np.ceil(np.sqrt(count)))
    with start_a_run(
        folder, name="experiment",
        room=(TILE[0], across * TILE[1], across * TILE[2]),
        tile_shape=TILE, voxel_size_um=VOXEL_UM,
        channels=[Channel("488", window=SHOWN_BETWEEN)], piece=PIECE,
    ) as run:
        for index in range(count):
            run.write(a_specimen(index),
                      at=(0, (index // across) * TILE[1], (index % across) * TILE[2]))
        return run.path


def how_it_drew(browser, built: Path, folder: Path, store: str) -> dict:
    """Open the picture, wait until it has settled, then watch it draw.

    The waiting is measured separately rather than folded in. Counting frames while
    the picture is still arriving would measure the *opening*, which is a different
    question and, at these sizes, a much shorter one.
    """
    server = make_server(port=0, data_dir=folder, site_dir=built, store=store,
                         live=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})

    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url))
    try:
        began = time.time()
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(f"{HELD} >= 1", timeout=300_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                               timeout=300_000)
        opened = time.time() - began

        page.wait_for_timeout(2500)
        # Requests for picture rather than for the page itself. This is the number
        # that says whether the browser is fetching the run or fetching the screen:
        # it should climb while the picture is smaller than the window and then
        # stop, however many positions are added afterwards.
        for_the_picture = len([one for one in asked if "/data/" in one])

        page.evaluate(KEEP_MOVING)
        page.evaluate(COUNT_FRAMES)
        page.evaluate("() => { window.__drawn = 0; window.__at = []; }")
        page.wait_for_timeout(int(SAMPLE_SECONDS * 1000))
        drawn = int(page.evaluate("() => window.__drawn"))
        at = [float(n) for n in page.evaluate("() => window.__at")]
        page.evaluate("() => clearInterval(window.__nudge)")

        # The *middle* frame says the rate the viewer is really holding; the
        # *worst* says the longest an operator ever watched the picture sit still,
        # which is what makes a viewer feel broken even when the average looks
        # respectable.
        gaps = sorted(later - earlier for earlier, later in zip(at, at[1:]))
        return {
            "lit": fraction_lit(page),
            "opened": opened,
            "requests": for_the_picture,
            "fps": drawn / SAMPLE_SECONDS,
            "usual_ms": gaps[len(gaps) // 2] if gaps else 0.0,
            "worst_ms": gaps[-1] if gaps else 0.0,
        }
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _how_big(folder: Path) -> tuple[int, int]:
    """How many bytes the picture and the positions take, in that order."""
    picture = folder / "experiment.ome.zarr"
    inside = picture / "positions"
    positions = sum(one.stat().st_size for one in inside.rglob("*") if one.is_file())
    everything = sum(one.stat().st_size for one in picture.rglob("*") if one.is_file())
    return everything - positions, positions


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument(
        "--steps", type=str, default=None,
        help="position counts to climb through, comma separated "
             f"(default {','.join(str(n) for n in STEPS)})",
    )
    parsing.add_argument(
        "--keep", action="store_true",
        help="leave the runs on disk afterwards instead of deleting them",
    )
    asked = parsing.parse_args()
    steps = sorted(int(n) for n in (asked.steps.split(",") if asked.steps
                                    else [str(n) for n in STEPS]))

    built = _VIZ / "frontend" / "dist"
    if not (built / "index.html").is_file():
        raise SystemExit(
            f"the viewer page has not been built ({built} holds no index.html), so "
            "there is nothing for a browser to open. Build it with:\n"
            "  npm --prefix viz_studio/frontend install\n"
            "  npm --prefix viz_studio/frontend run build"
        )

    work = Path(tempfile.mkdtemp(prefix="a-run-of-positions-"))
    started, browser = a_browser()
    rows = []
    try:
        for count in steps:
            writing = time.time()
            folder = work / f"n{count}"
            picture = a_run_of(count, folder)
            written = time.time() - writing
            drew = how_it_drew(browser, built, folder, picture.name)
            small, large = _how_big(folder)
            drew.update(positions=count, picture_bytes=small, position_bytes=large)
            rows.append(drew)
            print(f"  {count:>4} positions written in {written:>5.0f}s   "
                  f"lit {drew['lit']:.3f}  fps {drew['fps']:.1f}", flush=True)
    finally:
        browser.close()
        started.stop()
        if not asked.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"\nthe runs were left in {work}")

    print()
    print("| positions | lit | fps | middle frame | worst frame | opening | "
          "requests | the picture | the positions |")
    print("|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['positions']} | {row['lit']:.3f} | {row['fps']:.1f} | "
              f"{row['usual_ms']:.0f} ms | {row['worst_ms']:.0f} ms | "
              f"{row['opened']:.1f} s | {row['requests']} | "
              f"{row['picture_bytes'] / 1e6:.1f} MB | "
              f"{row['position_bytes'] / 1e6:.0f} MB |")
    print()
    print("The middle frame holding steady as positions are added is the whole "
          "claim; the picture staying small beside the positions is the other "
          "half of it. Check 'lit' is well above nought on every row before "
          "believing any of the rest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
