"""Measure what a great many positions cost before the first pixel appears.

`NEXT_STEPS.md` proposes two ways to stop a large finished folder being slow to
open: hand the engine only the positions currently in view and extend as the
operator moves, or prefer a single stitched image over thousands of separate
ones. Both are real work, and neither should be started before we know how big
the problem actually is.

The concern is specific. A row in the panel is drawn from every position of its
acquisition type at once, and the engine resolves each one when it is added —
roughly four small metadata requests apiece — through a browser that will only
open six connections to one address. At a few hundred positions that is nothing.
At several thousand it is thousands of round trips before anything is on screen.

During a live run the cost is invisible, because positions arrive one at a time
and each is paid for as it appears. The case that hurts is opening a large
*finished* folder cold, which is what this measures.

Run it with::

    python measure_sources.py

It needs the viewer page built (``npm --prefix frontend run build``) and a
browser, the same as the tests. It writes throwaway stores under a temporary
folder and removes them afterwards; nothing here touches your data.

What it reports, for each number of positions:

``config``
    how long the server takes to describe the folder — our own code.
``first pixel``
    how long from opening the page until something is actually drawn. This is
    the number that matters, and it is the one we could not measure before there
    was a way to look at the picture.
``requests``
    how many things the browser asked for on the way, which is where the
    round-trip cost shows up.

If ``first pixel`` grows roughly in step with the number of positions, the
concern is real and one of the two answers is worth building. If it flattens out,
it is not, and the effort belongs elsewhere.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "backend"))
sys.path.insert(0, str(HERE / "tests"))

from server import make_server  # noqa: E402

# How many positions to try. The interesting question is the shape of the curve
# rather than any single number, so these span from "an ordinary run" to "more
# positions than anyone has yet asked for".
# One position first, as a control. If even that never draws, the fault is in
# this script's synthetic data rather than in the number of positions, and
# reporting "never" four times would hide that -- which it did once already.
COUNTS = (1, 50, 200, 800, 2000)

# Each position is a tiny image. The point is the *number* of stores, not their
# size -- a position that is one chunk costs the same handful of metadata
# requests as one that is a hundred gigabytes, and it is those requests we are
# counting.
SIDE = 128
# One plane, and this matters. The view opens in the middle of the volume, so a
# store two planes deep is shown at plane one -- and if only plane zero has been
# written, the panel is legitimately empty and the measurement reads "never" for
# reasons that have nothing to do with how many positions there are.
DEPTH = 1
CHANNELS = 1

VOXEL_UM = (2.0, 0.35, 0.35)

# Where each position sits on the stage, in micrometres. Laid out in a rough
# square, stepped by exactly one image width so the positions tile edge to edge
# as a real mosaic does. Stepping by less would overlap them and stepping by more
# would leave gaps, and a gap under the middle of the view is enough to make
# "nothing is drawn yet" and "nothing is there" look the same.
STEP_UM = SIDE * VOXEL_UM[2]


def write_position(path: Path, index: int, across: int) -> None:
    """Write one position: the small files that describe it, and one chunk.

    Written by hand rather than through zarr. Two thousand stores through the
    library takes minutes and would make this too tedious to re-run, and what is
    being measured is the reading rather than the writing.
    """
    level = path / "0"
    level.mkdir(parents=True, exist_ok=True)
    (path / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (level / ".zarray").write_text(
        json.dumps(
            {
                "zarr_format": 2,
                "shape": [CHANNELS, DEPTH, SIDE, SIDE],
                "chunks": [1, 1, SIDE, SIDE],
                "dtype": "<u2",
                "compressor": None,
                "fill_value": 0,
                "order": "C",
                "filters": None,
                "dimension_separator": ".",
            }
        ),
        encoding="utf-8",
    )
    # One written chunk, so there is genuinely something to draw. The rest of the
    # image is absent, which is the ordinary sparse case and costs nothing.
    #
    # A gradient rather than one flat value, because the thing being timed is
    # "has a picture appeared", and a picture is told from an empty panel by
    # having more than one colour in it. A uniform square would be drawn
    # perfectly and still read as blank.
    (level / "0.0.0.0").write_bytes(_one_plane())
    row, column = divmod(index, across)
    (path / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, *VOXEL_UM]},
                                    {
                                        "type": "translation",
                                        "translation": [
                                            0.0,
                                            0.0,
                                            row * STEP_UM,
                                            column * STEP_UM,
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                ],
                "omero": {
                    "channels": [
                        {
                            "label": "ch0",
                            "color": "FFFFFF",
                            "window": {"min": 0, "max": 65535, "start": 0, "end": 4000},
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def _one_plane() -> bytes:
    """One plane of image: a gradient, so it is recognisable as a picture."""
    import numpy as np

    y, x = np.mgrid[0:SIDE, 0:SIDE]
    plane = (500 + (y + x) * (3000 // (2 * SIDE))).astype("<u2")
    return plane.tobytes()


def build_folder(root: Path, count: int) -> None:
    across = max(1, int(count**0.5))
    for index in range(count):
        write_position(root / f"overview_pos{index:05d}.ome.zarr", index, across)


def measure(pw, count: int) -> dict:
    from pixels import colour_spread, image_middle

    root = Path(tempfile.mkdtemp(prefix=f"zmart-{count}-"))
    try:
        started = time.monotonic()
        build_folder(root, count)
        written = time.monotonic() - started

        # Static mode: this is the "opening a finished folder" case, and it is
        # also the mode that does no watching, so nothing else is competing.
        server = make_server(
            port=0,
            data_dir=root,
            site_dir=HERE / "frontend" / "dist",
            store=sorted(p.name for p in root.glob("*.ome.zarr")),
            live=False,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}"

        browser = pw.chromium.launch(
            args=["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]
        )
        page = browser.new_page(viewport={"width": 1100, "height": 800})
        asked = []
        page.on("request", lambda r: asked.append(r.url))
        try:
            # How long our own side takes to describe the folder, asked before the
            # page is opened so the two costs do not overlap.
            config_started = time.monotonic()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartConfig !== undefined", timeout=300_000)
            described = time.monotonic() - config_started

            # Then wait for a picture rather than for the engine to say it is
            # satisfied. This is the whole point: the engine can hold everything
            # it needs and still have drawn nothing.
            drawn = None
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                spread = colour_spread(image_middle(page))
                if spread["distinct"] > 2 and spread["dominant_fraction"] < 0.99:
                    drawn = time.monotonic() - config_started
                    break
                time.sleep(0.25)

            return {
                "positions": count,
                "written_s": written,
                "config_s": described,
                "first_pixel_s": drawn,
                "requests": len(asked),
            }
        finally:
            page.close()
            browser.close()
            server.shutdown()
            thread.join(timeout=5)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    if not (HERE / "frontend" / "dist" / "index.html").exists():
        print("Build the viewer page first: npm --prefix frontend run build")
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed, so the page cannot be opened.")
        return 2

    rows = []
    with sync_playwright() as pw:
        for count in COUNTS:
            print(f"measuring {count} positions …", flush=True)
            row = measure(pw, count)
            rows.append(row)
            if count == COUNTS[0] and row["first_pixel_s"] is None:
                print(
                    "\nThe single-position control never drew anything, so the stores\n"
                    "this script writes are wrong and the timings below would mean\n"
                    "nothing. Fix that before reading any further."
                )
                break

    print()
    print(f"{'positions':>10} {'config':>9} {'first pixel':>12} {'requests':>10}")
    for row in rows:
        drawn = f"{row['first_pixel_s']:.1f}s" if row["first_pixel_s"] else "never"
        print(
            f"{row['positions']:>10} {row['config_s']:>8.1f}s {drawn:>12} {row['requests']:>10}"
        )
    print()
    print(
        "If first pixel grows roughly in step with the number of positions, the\n"
        "concern in NEXT_STEPS.md is real. If it flattens, it is not."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
