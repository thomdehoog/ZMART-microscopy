"""What one announcement costs while a run is going, and whether it grows.

This measures the thing an operator actually feels during an experiment: the moment
between the microscope finishing something and it appearing on screen. It asks one
question about that moment, and it is the question that decides whether a viewer stays
usable for a long run —

    does the cost of noticing one new thing depend on how much is already open?

If it does, a run gets slower the longer it goes on, which is the worst shape a cost can
have: it is invisible in a short test and unbearable by the end of a real acquisition. If
it does not, a run of forty thousand positions costs the same per position as a run of
ten, and the viewer can be left running.

Two layouts are measured, because they behave quite differently and the choice between
them is the most consequential one a run makes.

**One store per position** is what the controller writes today. A position finishing
means a new OME-Zarr appearing beside the others; the viewer notices it, reads its
description, and adds it to the row it belongs to.

**One store for the whole run** is the alternative: a single OME-Zarr created empty at
the start, with each tile written straight into its place. Nothing new appears — the
image simply fills in. The viewer cannot see that by reading the disk, so the run says so
by announcing with ``wrote_image_in_place``, and the viewer then drops the image it has
already decoded and fetches what is on screen again.

Run it with::

    python measure_the_live_path.py

It needs the viewer page built and a browser, the same as the tests. Everything is
written under a temporary folder and removed afterwards.

What it reports, for each layout and each amount already open:

``requests``
    how many things the browser asked for because of one announcement. This is the
    number to watch: if it climbs with the column to its left, the cost grows with the
    run.
``seconds``
    how long from announcing to the viewer having taken it on.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "app" / "server"))
sys.path.insert(0, str(HERE / "tests"))

from server import make_server  # noqa: E402

# How much is already open when the new thing arrives. The point is the *shape* of the
# curve rather than any single figure, so these span from "just started" to "a decent
# way into a run".
ALREADY_OPEN = (10, 100, 400)

SIDE, CHUNK = 256, 256
VOXEL_UM = (2.0, 0.35, 0.35)

# The single store's declared extent: large enough that tiles have somewhere to go, and
# costing nothing on disk because only the written tiles exist.
WHOLE = 2048
LEVELS = 2


def tile(brightness: int = 600) -> bytes:
    import numpy as np

    y, x = np.mgrid[0:CHUNK, 0:CHUNK]
    return (brightness + (y + x) * 4).astype("<u2").tobytes()


def _zarray(shape, chunks) -> str:
    return json.dumps({
        "zarr_format": 2, "shape": list(shape), "chunks": list(chunks),
        "dtype": "<u2", "compressor": None, "fill_value": 0,
        "order": "C", "filters": None, "dimension_separator": ".",
    })


def _attrs(datasets) -> str:
    return json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [
                {"name": "c", "type": "channel"},
                {"name": "z", "type": "space", "unit": "micrometer"},
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"},
            ],
            "datasets": datasets,
        }],
        "omero": {"channels": [{"label": "ch0", "color": "FFFFFF",
                                "window": {"min": 0, "max": 65535,
                                           "start": 0, "end": 4000}}]},
    })


def write_position(store: Path, index: int, across: int) -> None:
    """One position as its own store, laid out on a grid — the layout used today."""
    level = store / "0"
    level.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (level / ".zarray").write_text(_zarray((1, 1, SIDE, SIDE), (1, 1, SIDE, SIDE)),
                                   encoding="utf-8")
    (level / "0.0.0.0").write_bytes(tile())
    row, column = divmod(index, across)
    step = SIDE * VOXEL_UM[2]
    (store / ".zattrs").write_text(
        _attrs([{
            "path": "0",
            "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, *VOXEL_UM]},
                {"type": "translation",
                 "translation": [0.0, 0.0, row * step, column * step]},
            ],
        }]),
        encoding="utf-8",
    )


def declare_one_store(store: Path) -> None:
    """One store standing for the whole run, created empty with its extent declared."""
    store.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    datasets = []
    for level in range(LEVELS):
        side = WHOLE >> level
        folder = store / str(level)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".zarray").write_text(
            _zarray((1, side, side, side), (1, 1, CHUNK, CHUNK)), encoding="utf-8")
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale",
                 "scale": [1.0, *(unit * 2**level for unit in VOXEL_UM)]}],
        })
    (store / ".zattrs").write_text(_attrs(datasets), encoding="utf-8")


def write_tiles_into(store: Path, *, how_many: int, brightness: int = 600) -> None:
    """Fill in some tiles of the single store, at every level of the pyramid."""
    for level in range(LEVELS):
        side = WHOLE >> level
        folder = store / str(level)
        middle = side // 2
        across = max(1, side // CHUNK)
        for index in range(min(how_many, across * across)):
            row, column = divmod(index, across)
            (folder / f"0.{middle}.{row}.{column}").write_bytes(tile(brightness))


ANNOUNCE = """async ({ inPlace }) => {
  const response = await fetch('/api/announce', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: 'measuring', wrote_image_in_place: inPlace}),
  });
  return (await response.json()).told;
}"""

HELD = """() => window.zmartViewer.layerManager.managedLayers
           .filter((m) => m.layer && m.layer.type === 'image')
           .reduce((n, m) => n + m.layer.dataSources.length, 0)"""


def open_on(pw, root: Path, names, live: bool = True):
    httpd = make_server(port=0, data_dir=root, site_dir=HERE / "app" / "page" / "dist",
                        store=names, live=live)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    browser = pw.chromium.launch(
        args=["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": 1100, "height": 800})
    page.goto(f"http://127.0.0.1:{httpd.server_address[1]}", wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=300_000)
    return httpd, thread, browser, page


def one_position_arriving(pw, already: int) -> dict:
    """The layout used today: a new store appears beside the ones already open."""
    root = Path(tempfile.mkdtemp(prefix=f"zmart-live-many-{already}-"))
    try:
        across = max(1, int((already + 1) ** 0.5))
        for index in range(already):
            write_position(root / f"overview_pos{index:05d}.ome.zarr", index, across)
        names = sorted(path.name for path in root.glob("*.ome.zarr"))
        httpd, thread, browser, page = open_on(pw, root, names)
        asked: list[str] = []
        page.on("request", lambda request: asked.append(request.url))
        try:
            page.wait_for_function(f"{HELD} === {already}", timeout=300_000)
            page.wait_for_timeout(2500)
            mark = len(asked)
            started = time.monotonic()

            write_position(root / f"overview_pos{already:05d}.ome.zarr", already, across)
            page.evaluate(ANNOUNCE, {"inPlace": False})
            page.wait_for_function(f"{HELD} === {already + 1}", timeout=300_000)
            took = time.monotonic() - started
            page.wait_for_timeout(1500)
            return {"already": already, "requests": len(asked) - mark,
                    "seconds": round(took, 2)}
        finally:
            page.close()
            browser.close()
            httpd.shutdown()
            thread.join(timeout=5)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def one_tile_landing(pw, already: int) -> dict:
    """The alternative: image filling in inside one store that is already open."""
    root = Path(tempfile.mkdtemp(prefix=f"zmart-live-one-{already}-"))
    try:
        store = root / "overview_whole.ome.zarr"
        declare_one_store(store)
        write_tiles_into(store, how_many=already)
        httpd, thread, browser, page = open_on(pw, root, [store.name])
        asked: list[str] = []
        page.on("request", lambda request: asked.append(request.url))
        try:
            page.wait_for_timeout(4000)
            mark = len(asked)
            started = time.monotonic()

            # One more tile, and the run says it went in where the viewer already looked.
            write_tiles_into(store, how_many=already + 1, brightness=900)
            page.evaluate(ANNOUNCE, {"inPlace": True})
            # There is no count to wait for here -- nothing is added, the image simply
            # changes -- so wait until the fetching it set off has died down.
            quiet_since = time.monotonic()
            settled = len(asked)
            while time.monotonic() - started < 120:
                page.wait_for_timeout(250)
                if len(asked) != settled:
                    settled = len(asked)
                    quiet_since = time.monotonic()
                elif time.monotonic() - quiet_since > 2.0:
                    break
            took = quiet_since - started
            return {"already": already, "requests": len(asked) - mark,
                    "seconds": round(max(took, 0.0), 2)}
        finally:
            page.close()
            browser.close()
            httpd.shutdown()
            thread.join(timeout=5)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    if not (HERE / "app" / "page" / "dist" / "index.html").exists():
        print("Build the viewer page first: npm --prefix app/page run build")
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed, so the page cannot be opened.")
        return 2

    many, one = [], []
    with sync_playwright() as pw:
        for already in ALREADY_OPEN:
            print(f"one store per position, {already} already open …", flush=True)
            many.append(one_position_arriving(pw, already))
            print(f"one store for the whole run, {already} tiles in …", flush=True)
            one.append(one_tile_landing(pw, already))

    print()
    print(f"{'already open':>13} {'a position arriving':>32} {'a tile landing in one store':>32}")
    print(f"{'':>13} {'requests':>16} {'seconds':>15} {'requests':>16} {'seconds':>15}")
    for left, right in zip(many, one, strict=True):
        print(f"{left['already']:>13} {left['requests']:>16} {left['seconds']:>14}s "
              f"{right['requests']:>16} {right['seconds']:>14}s")
    print()
    print(
        "Read down the columns rather than across. If the requests for a layout climb\n"
        "as more is already open, then a run of that shape gets slower the longer it\n"
        "goes on -- which is the shape that is invisible in a short test and painful by\n"
        "the end of a real acquisition. If they stay level, the viewer can be left\n"
        "running for as long as the experiment lasts."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
