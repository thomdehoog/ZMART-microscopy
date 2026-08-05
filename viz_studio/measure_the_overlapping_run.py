"""What an overlapping run costs, from one tile to ten thousand.

`zmart_storage/cropped.py` writes an acquisition whose tiles overlap twice over:
every tile whole, in a small image of its own, and every tile trimmed where it
meets its neighbours into one canvas for the viewer. The point of the arrangement
is that nothing the camera recorded is thrown away and the viewer still has a
single picture to draw, however many tiles the run gathers.

Both halves of that are claims about cost, so both are measured here rather than
believed.

What it reports, at each size
-----------------------------

``tiles``
    How many tiles actually arrived. The sizes asked for are rounded to a square
    raster, so this is the honest number rather than the one requested.
``voxels lost``
    How many of the voxels the camera recorded could not be read back out of the
    archive afterwards. **This must be nought.** Keeping the overlap is the entire
    reason the arrangement exists, so any loss at all makes it pointless — and a
    loss here would be silent, because the canvas would still look perfectly
    ordinary.
``first pixel``
    How long from opening the page until there is something of the specimen on
    screen. This is the wait an operator actually feels.
``requests``
    How many pieces of image the browser asked the server for while opening. This
    is the number that used to grow with the size of the run and made large runs
    slow to open.
``flat frames``
    How many frames the viewer manages in five seconds in the everyday view, with
    the specimen open and everything loaded. Below about fifty, panning and moving
    the contrast handles feel heavy.
``contrast``
    How long one nudge of a brightness slider takes. This is the number felt most
    directly, because judging a specimen means moving that slider.
``volume frames``
    The same frame count with the volume drawn instead of a plane, **and it is
    reported as a share of the flat rate rather than on its own.** This machine has
    no graphics card and draws through software, so an absolute figure for a volume
    means nothing and would need re-tuning on every machine. What holds anywhere is
    how much of its own rate the viewer keeps when asked for the harder view, and
    whether that share changes as the run grows — which is the question this is
    here to answer.
``on disk``
    What the two artefacts together weigh, and what share of it is the archive. The
    overlap is stored twice by design, and it is worth seeing the price.

Running it
----------

    python measure_the_overlapping_run.py

That sweeps one, four, a hundred and about five hundred tiles, which takes a few
minutes. The two large sizes — about two thousand and ten thousand tiles — are
opt-in, because ten thousand tiles takes several minutes to write and about a
gigabyte of disk while it runs::

    ZMART_THE_WHOLE_SWEEP=1 python measure_the_overlapping_run.py

Or choose the sizes yourself::

    python measure_the_overlapping_run.py 100,2000

Everything is written under a temporary folder and removed as soon as each size
has been measured, so none of your own data is touched and the disk never holds
more than one size at a time. It needs the viewer page built
(``npm --prefix frontend run build``) and a browser, the same as the tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

import numpy as np

VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(VIZ / "backend"))
sys.path.insert(0, str(VIZ.parent))

from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.cropped import TilesAndCanvas  # noqa: E402

# One acquired tile, and how far the stage steps between them. The difference is
# the overlap: a quarter of a tile, which is more than most runs use and therefore
# the harder case to carry.
#
# Deliberately small. What is being measured is how the arrangement behaves as the
# number of tiles grows, and that has nothing to do with how large each tile is —
# so ten thousand of these come to about a gigabyte where ten thousand real ones
# would come to a terabyte and could not be measured on an ordinary machine at all.
TILE = (2, 128, 128)
STEP = (2, 96, 96)

# How large a piece of the canvas is. Ninety-six is exactly what a trimmed tile
# comes to, which is the rule `zmart_storage.cropped` refuses a run for breaking.
CHUNK = 96

VOXEL_UM = (2.0, 0.35, 0.35)

# The brightness window the canvas declares, so the viewer opens on a sensible
# picture instead of measuring one. That keeps this measurement about the drawing
# rather than about how the brightness is judged.
WINDOW = (0, 4000)

# The sizes swept unless told otherwise, in tiles, and the two that have to be
# asked for. The large ones are opt-in because writing ten thousand tiles takes
# several minutes and about a gigabyte of disk — the same arrangement the rest of
# this repository uses for its expensive measurements.
SIZES_BY_DEFAULT = (1, 4, 100, 500)
SIZES_IF_ASKED = (2000, 10000)
THE_WHOLE_SWEEP = "ZMART_THE_WHOLE_SWEEP"

# Software rendering, so this gives the same answer on a machine without a graphics
# card as on one with. The frame counts will be better on a real card; the counts
# of voxels lost and requests made will not change, and those are the point.
BROWSER_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]

# How many different tiles to make up and then reuse. Making a fresh one for every
# tile of a ten-thousand-tile run would spend more time inventing pictures than
# measuring anything, and reusing them changes nothing that is being measured: the
# pieces of a zarr image are compressed one at a time, so two identical tiles are no
# cheaper to store than two different ones.
HOW_MANY_DIFFERENT_TILES = 16


# -- making up a specimen ------------------------------------------------------


def _a_tile(seed: int) -> np.ndarray:
    """One tile of something that looks like a specimen: dim background, bright blobs.

    Two things about the shape of this matter for the measurement.

    It is **not smooth**, because there is a layer of noise over it. Real microscope
    pixels barely compress, and a picture made of clean gradients would shrink to a
    fraction of its size and make the figures for disk space a fiction.

    And it has **no flat plateau at the top of its range**. A volume is shown over a
    brightness window starting near the very top of the distribution, so that
    background does not accumulate into fog along every ray — which means a specimen
    made of blocks of one bright value collapses that window to nothing and the
    volume opens completely empty. That is a property of the fixture rather than of
    anything being measured, and it is easy to walk into.
    """
    depth, height, width = TILE
    rng = np.random.default_rng(seed)
    z, y, x = np.indices(TILE, dtype=np.float32)
    picture = 500 + 180 * (y / height) + rng.normal(0, 60, size=TILE)
    for _ in range(8):
        at_y, at_x = rng.uniform(12, height - 12), rng.uniform(12, width - 12)
        lean_y, lean_x = rng.uniform(-3, 3), rng.uniform(-3, 3)
        spread = rng.uniform(7, 16)
        along = (
            (y - (at_y + lean_y * z)) ** 2 + (x - (at_x + lean_x * z)) ** 2
        ) / (2 * spread ** 2)
        picture = np.maximum(picture, brightness_of(rng) * np.exp(-along))
    return np.clip(picture, 0, 4000).astype("uint16")


def brightness_of(rng) -> float:
    """How bright one object is. Spread out, so the distribution has no step in it."""
    return float(rng.uniform(1600, 3500))


def _how_the_raster_comes_out(size: int) -> tuple[int, int, int]:
    """A square raster, with colours and moments, coming to about ``size`` tiles.

    Returns how many tiles across the raster is, how many colours it records and how
    many moments. The smallest size is a single tile of a single colour at a single
    moment, because that is the degenerate case worth measuring; everything larger
    records two colours at two moments, which is the arrangement where a writer that
    confused one recording of a field with another would show it.
    """
    if size <= 1:
        return 1, 1, 1
    channels = frames = 2
    across = max(1, round((size / (channels * frames)) ** 0.5))
    return across, channels, frames


# -- writing a run, and checking nothing was lost ------------------------------


def write_the_run(folder: Path, size: int) -> dict:
    """Write one overlapping run of about ``size`` tiles, both artefacts.

    Returns what it cost and how large the run came out, so the caller can report
    the honest number of tiles rather than the number asked for.
    """
    across, channels, frames = _how_the_raster_comes_out(size)
    extent = tuple((across - 1) * STEP[axis] + TILE[axis] for axis in (1, 2))

    run = TilesAndCanvas.create(
        folder,
        name="overview",
        canvas_shape=(TILE[0], extent[0], extent[1]),
        tile_shape=TILE,
        tile_step=STEP,
        # The shape of the raster, which is what lets the tiles around the outside
        # keep their outer edges instead of losing a border off the whole run.
        tile_grid=(1, across, across),
        voxel_size_um=VOXEL_UM,
        channels=[Channel(name, window=WINDOW)
                  for name in ("488", "561")[:channels]],
        frames=frames,
        chunk=CHUNK,
    )

    library = [_a_tile(seed) for seed in range(HOW_MANY_DIFFERENT_TILES)]
    began = time.monotonic()
    tiles = 0
    for frame in range(frames):
        for channel in range(channels):
            for row in range(across):
                for column in range(across):
                    run.write(
                        library[_which_tile(across, row, column, channel, frame)],
                        origin=(0, row * STEP[1], column * STEP[2]),
                        channel=channel,
                        frame=frame,
                        tile_index=(0, row, column),
                    )
                    tiles += 1
    run.close()
    return {
        "tiles": tiles,
        "across": across,
        "channels": channels,
        "frames": frames,
        "writing": time.monotonic() - began,
        "canvas": run.canvas_path,
        "archive": run.tiles_folder,
    }


def _which_tile(across: int, row: int, column: int, channel: int, frame: int) -> int:
    """Which of the made-up tiles this position, colour and moment was given.

    Worked out rather than remembered, so that checking the run afterwards can ask
    the same question and get the same answer without a list of ten thousand
    entries having to be kept.
    """
    return (
        (row * across + column) + channel * 5 + frame * 7
    ) % HOW_MANY_DIFFERENT_TILES


def count_what_was_lost(folder: Path, shape: dict) -> dict:
    """Read every whole tile back and count the voxels that do not match.

    This is the promise the whole arrangement rests on, so it is counted rather than
    sampled: every voxel handed to the writer is read back out of the archive and
    compared with what went in.
    """
    import json

    import zarr

    across, channels, frames = shape["across"], shape["channels"], shape["frames"]
    library = [_a_tile(seed) for seed in range(HOW_MANY_DIFFERENT_TILES)]

    began = time.monotonic()
    lost = 0
    recorded = 0
    found = 0
    for store in sorted(folder.glob("*.ome.zarr")):
        moved = json.loads((store / ".zattrs").read_text(encoding="utf-8"))[
            "multiscales"][0]["coordinateTransformations"][0]["translation"]
        row = round(moved[3] / VOXEL_UM[1]) // STEP[1]
        column = round(moved[4] / VOXEL_UM[2]) // STEP[2]
        whole = np.asarray(zarr.open_group(str(store), mode="r")["0"][:])
        found += 1
        for frame in range(frames):
            for channel in range(channels):
                want = library[_which_tile(across, row, column, channel, frame)]
                recorded += want.size
                lost += int((whole[frame, channel] != want).sum())
    return {
        "voxelsRecorded": recorded,
        "voxelsLost": lost,
        "positions": found,
        "checking": time.monotonic() - began,
    }


def what_it_weighs(canvas: Path, archive: Path) -> dict:
    """How much disk the two artefacts take, in megabytes."""
    def kilobytes(path: Path) -> int:
        answered = subprocess.run(
            ["du", "-sk", str(path)], capture_output=True, text=True, check=False
        ).stdout.split()
        return int(answered[0]) if answered else 0

    return {
        "canvasMB": kilobytes(canvas) / 1024,
        "archiveMB": kilobytes(archive) / 1024,
    }


# -- what the viewer makes of it -----------------------------------------------

# How many frames the viewer manages in a given time, asking it to redraw
# continuously. This is what panning and dragging a slider have to compete with.
# Taken from `check_scale.py`, so the two measurements can be read side by side.
HOW_FAST_IT_DRAWS = """
async ({ seconds }) => {
  const viewer = window.zmartViewer;
  const until = performance.now() + seconds * 1000;
  let frames = 0;
  while (performance.now() < until) {
    viewer.display.scheduleRedraw();
    await new Promise((resolve) => requestAnimationFrame(() => resolve()));
    frames += 1;
  }
  return frames;
}
"""

# What one nudge of a brightness slider costs. The window is written straight onto
# the layer, which is what the panel does when the operator drags the handle.
ONE_CONTRAST_STEP = """
({ high }) => {
  const viewer = window.zmartViewer;
  const managed = viewer.layerManager.managedLayers.find(
    (m) => m.layer && m.layer.type === "image");
  const started = performance.now();
  managed.layer.shaderControlState.restoreState(
    { normalized: { range: [0, high] } });
  viewer.display.draw();
  return performance.now() - started;
}
"""

# Everything the first view needs having been fetched and decoded. This is as close
# as the engine comes to saying "I have finished drawing for now", and it is trusted
# for *when* to look and for nothing else — a piece of canvas nobody has written is
# decoded and counted exactly like a written one, so it says nothing at all about
# whether there is a picture.
SETTLED = """() => {
  let layers = 0, needed = 0, available = 0;
  for (const m of window.zmartViewer.layerManager.managedLayers)
    for (const rl of (m.layer?.renderLayers) || []) {
      layers += 1;
      const p = rl.layerChunkProgressInfo;
      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
    }
  return layers > 0 && available > 0 && available >= needed;
}"""

HOW_MANY_IMAGES = """() => window.zmartViewer.layerManager.managedLayers
     .filter((m) => m.layer && m.layer.type === 'image')
     .reduce((n, m) => n + m.layer.dataSources.length, 0)"""

# How long to count frames for, and how long to allow a size to open in.
SAMPLE_SECONDS = 5
PATIENCE_SECONDS = 600


def _lit(page, where) -> float:
    """How much of the middle of the picture is showing specimen rather than nothing.

    A photograph, not a number the engine reports about itself. The two have come
    apart before: the viewer once held every piece of image it needed and drew the
    specimen a ten-thousandth of a pixel wide, with the engine perfectly content.
    """
    import io

    from PIL import Image

    shot = page.screenshot(clip=where)
    pixels = np.array(Image.open(io.BytesIO(shot)).convert("RGB"))
    return float((pixels.max(axis=2) > 40).mean())


def _the_middle_of(page) -> dict:
    """Where to photograph: the middle half of the drawing surface.

    The middle rather than the whole of it, because the viewer's own controls sit in
    the corners on top of the image and would supply variety of their own.
    """
    box = page.locator("canvas").first.bounding_box()
    return {
        "x": box["x"] + box["width"] * 0.25,
        "y": box["y"] + box["height"] * 0.25,
        "width": box["width"] * 0.5,
        "height": box["height"] * 0.5,
    }


def look_at_it(folder: Path) -> dict:
    """Open the viewer on the run's canvas and measure what it costs to work in."""
    from playwright.sync_api import sync_playwright
    from server import make_server

    result: dict = {}
    httpd = make_server(
        port=0,
        data_dir=folder,
        site_dir=VIZ / "frontend" / "dist",
        store="overview.ome.zarr",
        live=False,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{httpd.server_address[1]}"

    asked_for: Counter = Counter()

    def note(request):
        if "/data/" in request.url:
            asked_for["pieces"] += 1

    with sync_playwright() as pw:
        browser = _a_browser(pw)
        page = browser.new_page(viewport={"width": 1100, "height": 800})
        page.on("request", note)
        try:
            began = time.monotonic()
            page.goto(address, wait_until="domcontentloaded")
            page.wait_for_function(
                "() => window.zmartViewer !== undefined",
                timeout=PATIENCE_SECONDS * 1000,
            )

            # When the first of the specimen appeared. Measured by photographing the
            # picture every so often, so the answer is only good to about a fifth of
            # a second — which is far finer than the difference this is looking for.
            where = _the_middle_of(page)
            first_pixel = None
            while time.monotonic() - began < PATIENCE_SECONDS:
                if _lit(page, where) > 0.005:
                    first_pixel = time.monotonic() - began
                    break
                page.wait_for_timeout(100)
            result["firstPixel"] = first_pixel

            page.wait_for_function(SETTLED, timeout=PATIENCE_SECONDS * 1000)
            page.wait_for_timeout(2000)
            result["opened"] = time.monotonic() - began
            result["requests"] = asked_for["pieces"]
            result["sources"] = page.evaluate(HOW_MANY_IMAGES)
            result["lit"] = _lit(page, where)

            result["flatFrames"] = page.evaluate(
                HOW_FAST_IT_DRAWS, {"seconds": SAMPLE_SECONDS}
            )
            result["contrastMs"] = round(
                page.evaluate(ONE_CONTRAST_STEP, {"high": 3500}), 1
            )

            # And the same again with the volume drawn instead of a plane. The
            # absolute figure means nothing on a machine drawing through software,
            # so what is kept is its share of the flat rate.
            page.click("text=3D")
            page.wait_for_timeout(6000)
            result["volumeFrames"] = page.evaluate(
                HOW_FAST_IT_DRAWS, {"seconds": SAMPLE_SECONDS}
            )
            result["volumeLit"] = _lit(page, where)
        finally:
            page.close()
            browser.close()
            httpd.shutdown()
            thread.join(timeout=5)
    return result


def _a_browser(pw):
    """A Chromium, Playwright's own if it has one and this machine's if not.

    The same fallback the test suite makes, for the same reason: a machine that has
    a perfectly good browser of a slightly different build should measure something
    rather than report nothing.
    """
    try:
        return pw.chromium.launch(args=BROWSER_ARGS)
    except Exception:
        sys.path.insert(0, str(VIZ / "tests"))
        from conftest import find_a_chromium

        already_here = find_a_chromium()
        if already_here is None:
            raise
        return pw.chromium.launch(
            executable_path=str(already_here), args=BROWSER_ARGS
        )


# -- one size, and the table ---------------------------------------------------


def measure(size: int) -> dict:
    """Write a run of about ``size`` tiles, check it, look at it, and clear it away."""
    work = Path(tempfile.mkdtemp(prefix=f"zmart-overlapping-{size}-"))
    try:
        run = work / "run"
        shape = write_the_run(run, size)
        checked = count_what_was_lost(shape["archive"], shape)
        weighed = what_it_weighs(shape["canvas"], shape["archive"])
        drawn = look_at_it(run)
        return {"asked": size, **shape, **checked, **weighed, **drawn}
    finally:
        # Cleared away before the next size is written, so the disk never holds two.
        shutil.rmtree(work, ignore_errors=True)


def report(rows: list[dict]) -> None:
    """Print the table, and then say in words what it means."""
    print()
    print(
        f"{'tiles':>7} {'voxels lost':>12} {'first pixel':>12} {'requests':>9} "
        f"{'flat frames':>12} {'contrast':>9} {'volume':>8} {'on disk':>9}"
    )
    print("-" * 88)
    for row in rows:
        first = "-" if row["firstPixel"] is None else f"{row['firstPixel']:.1f} s"
        share = (
            "-" if not row["flatFrames"]
            else f"{row['volumeFrames'] / row['flatFrames']:.0%}"
        )
        weight = row["canvasMB"] + row["archiveMB"]
        print(
            f"{row['tiles']:>7} {row['voxelsLost']:>12} {first:>12} "
            f"{row['requests']:>9} {row['flatFrames']:>12} "
            f"{row['contrastMs']:>7} ms {share:>8} {weight:>7.0f} MB"
        )

    print()
    lost = [row for row in rows if row["voxelsLost"]]
    if lost:
        print(
            "SOMETHING WAS LOST. The archive is meant to hold every voxel the camera\n"
            f"recorded, and at {lost[0]['tiles']} tiles it did not: "
            f"{lost[0]['voxelsLost']} voxels could not be read\n"
            "back. That makes the whole arrangement pointless, because keeping the\n"
            "overlap is the only reason to write the run twice."
        )
    else:
        print(
            "Not one voxel was lost at any size. Every reading the camera made is\n"
            "still readable from the tiles, which is what a stitcher will need."
        )

    # One source per colour of the one canvas, however many tiles the run holds. The
    # colours are counted because each becomes a row of its own on screen; what must
    # not happen is the count following the number of tiles, which is the cost the
    # canvas exists to remove.
    many = [row for row in rows if row["sources"] != row["channels"]]
    if many:
        print(
            f"\nAt {many[0]['tiles']} tiles the viewer opened {many[0]['sources']} "
            f"images where the run records\n{many[0]['channels']} colours, so "
            "something beyond the canvas is being picked up — most\nlikely the folder "
            "of whole tiles, which would put back the whole cost this\narrangement "
            "exists to remove."
        )
    else:
        print(
            "\nThe viewer opened one image per colour at every size, however many tiles\n"
            "the run held. That is the property the canvas is for: what the engine has\n"
            "to hold does not grow with the acquisition."
        )

    print(
        "\nThe volume column is a share of the flat rate rather than a number of\n"
        "frames, and deliberately so: this machine draws through software, so an\n"
        "absolute figure for a volume says more about the machine than about the\n"
        "run. What is worth watching is whether that share falls as the run grows."
    )

    slow = [row for row in rows if row["flatFrames"] < 50]
    if slow:
        print(
            f"\nNote that at {slow[0]['tiles']} tiles the viewer managed only "
            f"{slow[0]['flatFrames']} frames in five seconds\nand one nudge of a "
            f"brightness slider took {slow[0]['contrastMs']} ms. A run that size is "
            "heavy to\nwork with even where nothing is lost."
        )


def main() -> None:
    chosen = [
        part for argument in sys.argv[1:] for part in argument.split(",") if part
    ]
    if chosen:
        sizes = [int(part) for part in chosen]
    elif os.environ.get(THE_WHOLE_SWEEP):
        sizes = [*SIZES_BY_DEFAULT, *SIZES_IF_ASKED]
    else:
        sizes = list(SIZES_BY_DEFAULT)
        print(
            f"Sweeping {', '.join(str(size) for size in sizes)} tiles. The two large "
            f"sizes ({', '.join(str(size) for size in SIZES_IF_ASKED)}) are not part "
            f"of an\nordinary run, because ten thousand tiles takes several minutes "
            f"to write and\nabout a gigabyte of disk. Set {THE_WHOLE_SWEEP}=1 to "
            "include them."
        )

    if not (VIZ / "frontend" / "dist" / "index.html").exists():
        print(
            "The viewer page has not been built, so there is nothing to open. Build "
            "it first:\n\n    npm --prefix frontend run build\n"
        )
        raise SystemExit(1)

    rows = []
    for size in sizes:
        print(f"\n  about {size} tiles ...", flush=True)
        row = measure(size)
        rows.append(row)
        print(
            f"    wrote {row['tiles']} tiles into {row['positions']} positions in "
            f"{row['writing']:.0f} s, checked in {row['checking']:.0f} s"
        )
    report(rows)


if __name__ == "__main__":
    main()
