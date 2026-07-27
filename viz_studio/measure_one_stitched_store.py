"""What does one stitched image cost to open, next to the same data as separate tiles?

The viewer can be pointed at a specimen in two shapes. Today it is given one store per
position — one small OME-Zarr for every place the microscope visited — and every one of
them has to be read before the picture is complete. The alternative, for data that is
finished, is to fuse them into a single OME-Zarr with its own pyramid: one store that
stands for the whole specimen.

`NEXT_STEPS.md` records the case for the second as a decision, and records that nobody
had measured it. This measures the *viewing* half of it. The making half — how long
stitching takes and how much disk it needs — is a separate question and is not answered
here.

The comparison is deliberately unfair in the stitched image's favour, and that is the
point. The mosaic is a few hundred tiny positions; the stitched store declares itself to
be a specimen of eight by eight by eight tiles, which at the sizes people actually
acquire is several hundred gigabytes. If the large one still opens faster than the small
one, the cost has nothing to do with how much data there is and everything to do with how
many separate stores it is spread across.

Run it with::

    python measure_one_stitched_store.py

It needs the viewer page built and a browser, the same as the tests. Both folders are
written sparsely — the small files that describe the data are complete and truthful, and
only the handful of pieces the viewer actually looks at are written. That is not a
shortcut: what is being timed is the reading of descriptions and the fetching of what is
on screen, and neither depends on the parts of the specimen nobody is looking at.
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

# The specimen being described: eight tiles in each direction, each tile 512 voxels
# cubed. That is a volume of 4 096 voxels a side, which at two bytes a voxel is about
# 137 GB -- the scale this viewer is meant for, and far more than would fit on a laptop
# if it were all written out.
TILES, TILE = 8, 512
FULL = TILES * TILE

# How the fused store is cut up. Chunks that are one plane thick are what a slice viewer
# wants: showing one plane reads only that plane, rather than dragging in a cube of
# depth that will not be shown. The pyramid halves in each direction until the whole
# specimen is a handful of chunks, which is what makes zooming out cheap.
CHUNK = 512
LEVELS = 6

VOXEL_UM = (2.0, 0.35, 0.35)

# The mosaic to compare against: the same specimen as separate positions, one store each.
# Three hundred rather than five hundred and twelve, purely so this finishes in a
# reasonable time -- and note that it is therefore the *easier* of the two cases.
MOSAIC_POSITIONS = 300
MOSAIC_SIDE = 128


def _plane(side: int) -> bytes:
    """One plane of image: a gradient, so it is recognisable as a picture rather than a
    flat colour that a blank panel could not be told apart from."""
    import numpy as np

    y, x = np.mgrid[0:side, 0:side]
    return (500 + (y + x) * (3000 // (2 * side))).astype("<u2").tobytes()


def _zarray(shape, chunks) -> str:
    return json.dumps(
        {
            "zarr_format": 2,
            "shape": list(shape),
            "chunks": list(chunks),
            "dtype": "<u2",
            "compressor": None,
            "fill_value": 0,
            "order": "C",
            "filters": None,
            "dimension_separator": ".",
        }
    )


def _omero(label: str = "ch0") -> dict:
    return {
        "channels": [
            {
                "label": label,
                "color": "FFFFFF",
                "window": {"min": 0, "max": 65535, "start": 0, "end": 4000},
            }
        ]
    }


def write_stitched(store: Path) -> None:
    """One OME-Zarr standing for the whole specimen, with a pyramid.

    Written sparsely: every level's description is complete and honest about how large
    the specimen is, and only the pieces under the middle of the view are actually on
    disk. A zarr reader treats a missing piece as empty, which is the ordinary case for
    a specimen that does not fill its bounding box.
    """
    store.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    datasets = []
    for level in range(LEVELS):
        side = FULL >> level
        depth = side
        folder = store / str(level)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".zarray").write_text(
            _zarray((1, depth, side, side), (1, 1, CHUNK, CHUNK)), encoding="utf-8"
        )
        # The view opens in the middle of the volume, so the middle plane is the one that
        # has to be there. A few pieces around the centre of that plane are written.
        middle = depth // 2
        across = max(1, side // CHUNK)
        centre = across // 2
        for row in range(max(0, centre - 1), min(across, centre + 2)):
            for column in range(max(0, centre - 1), min(across, centre + 2)):
                (folder / f"0.{middle}.{row}.{column}").write_bytes(_plane(CHUNK))
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [
                    {
                        "type": "scale",
                        "scale": [
                            1.0,
                            VOXEL_UM[0] * 2**level,
                            VOXEL_UM[1] * 2**level,
                            VOXEL_UM[2] * 2**level,
                        ],
                    }
                ],
            }
        )
    (store / ".zattrs").write_text(
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
                        "datasets": datasets,
                    }
                ],
                "omero": _omero(),
            }
        ),
        encoding="utf-8",
    )


def write_mosaic_position(store: Path, index: int, across: int) -> None:
    """One position of the unstitched mosaic: a single small plane, laid out on a grid."""
    level = store / "0"
    level.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (level / ".zarray").write_text(
        _zarray((1, 1, MOSAIC_SIDE, MOSAIC_SIDE), (1, 1, MOSAIC_SIDE, MOSAIC_SIDE)),
        encoding="utf-8",
    )
    (level / "0.0.0.0").write_bytes(_plane(MOSAIC_SIDE))
    row, column = divmod(index, across)
    step = MOSAIC_SIDE * VOXEL_UM[2]
    (store / ".zattrs").write_text(
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
                                        "translation": [0.0, 0.0, row * step,
                                                        column * step],
                                    },
                                ],
                            }
                        ],
                    }
                ],
                "omero": _omero(),
            }
        ),
        encoding="utf-8",
    )


HELD = """() => window.zmartViewer.layerManager.managedLayers
           .filter((m) => m.layer && m.layer.type === 'image')
           .reduce((n, m) => n + m.layer.dataSources.length, 0)"""

DRAWING_LAYERS = """() => window.zmartViewer.layerManager.managedLayers
                      .reduce((n, m) => n + ((m.layer && m.layer.renderLayers) || []).length, 0)"""

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


def look(pw, root: Path, names, label: str, budget: int = 600) -> dict:
    from pixels import colour_spread, image_middle

    httpd = make_server(port=0, data_dir=root, site_dir=HERE / "frontend" / "dist",
                        store=names, live=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    browser = pw.chromium.launch(
        args=["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": 1100, "height": 800})
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url))
    try:
        started = time.monotonic()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined",
                               timeout=budget * 1000)
        described = time.monotonic() - started

        drawn = None
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            spread = colour_spread(image_middle(page))
            if spread["distinct"] > 2 and spread["dominant_fraction"] < 0.99:
                drawn = time.monotonic() - started
                break
            time.sleep(0.25)

        # Then wait until nothing more is being handed over, so "settled" means the same
        # thing for both shapes -- otherwise the mosaic would look good simply by having
        # drawn its first few tiles.
        while time.monotonic() < deadline:
            if page.evaluate("() => !window.zmartSourcesWaiting "
                             "|| window.zmartSourcesWaiting() === 0"):
                break
            time.sleep(0.25)
        settled = time.monotonic() - started

        return {
            "what": label,
            "config_s": round(described, 1),
            "first_pixel_s": round(drawn, 1) if drawn else None,
            "settled_s": round(settled, 1),
            "requests": len(asked),
            "stores": page.evaluate(HELD),
            "drawingLayers": page.evaluate(DRAWING_LAYERS),
            "frames": page.evaluate(HOW_FAST_IT_DRAWS, {"seconds": 5}),
        }
    finally:
        page.close()
        browser.close()
        httpd.shutdown()
        thread.join(timeout=5)


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
        one = Path(tempfile.mkdtemp(prefix="zmart-stitched-"))
        try:
            write_stitched(one / "overview_whole.ome.zarr")
            rows.append(look(pw, one, ["overview_whole.ome.zarr"],
                             f"one stitched store, {FULL}³ voxels"))
        finally:
            shutil.rmtree(one, ignore_errors=True)

        many = Path(tempfile.mkdtemp(prefix="zmart-mosaic-"))
        try:
            across = max(1, int(MOSAIC_POSITIONS**0.5))
            for index in range(MOSAIC_POSITIONS):
                write_mosaic_position(many / f"overview_pos{index:05d}.ome.zarr",
                                      index, across)
            rows.append(look(pw, many,
                             sorted(p.name for p in many.glob("*.ome.zarr")),
                             f"{MOSAIC_POSITIONS} separate positions"))
        finally:
            shutil.rmtree(many, ignore_errors=True)

    print()
    print(f"{'what':>34} {'config':>8} {'1st pixel':>11} {'settled':>9} "
          f"{'requests':>9} {'stores':>7} {'draw layers':>12} {'frames/5s':>10}")
    for row in rows:
        pixel = f"{row['first_pixel_s']}s" if row["first_pixel_s"] else "never"
        print(f"{row['what']:>34} {row['config_s']:>7}s {pixel:>11} "
              f"{row['settled_s']:>8}s {row['requests']:>9} {row['stores']:>7} "
              f"{row['drawingLayers']:>12} {row['frames']:>10}")
    print()
    print(
        "The stitched store describes a far larger specimen than the mosaic and is\n"
        "expected to open faster all the same. What costs the viewer is the number of\n"
        "separate stores, not the amount of data behind them."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
