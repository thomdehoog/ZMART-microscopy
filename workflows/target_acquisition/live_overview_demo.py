"""A stand-in overview scan, so the operator page has something real to draw.

The operator page can show the overview being built while it is being acquired,
tile by tile. To do that it needs a run to watch, and on a developer machine
there is no microscope to make one. This script is that missing half: it writes
a run the way a real acquisition writes it, one tile at a time, and serves it
over HTTP so the page in the browser can read it.

Two things about it are deliberate and worth knowing before you change anything.

**The run is written by the project's own writer**, :mod:`zmart_storage.canvas`,
with the same calls a real acquisition makes. Nothing here imitates the format.
That is the whole point of the exercise: a picture that draws a lookalike store
proves very little, whereas a picture that draws what our microscope actually
leaves on disk proves the thing we care about.

**The images are declared once, before any tile exists**, and the tiles are
written into that already-declared room afterwards. This is how the writer is
meant to be used, and it is what lets a viewer watch a run: the description of
the images never changes, so the page can open them straight away and simply
find more picture inside them as the scan goes on.

Running it
----------

.. code-block:: console

    python workflows/target_acquisition/live_overview_demo.py

It prints the address of the store and then writes one tile every second or so.
Give that address to the operator page and watch the overview fill in::

    http://127.0.0.1:5174/?overview=http://127.0.0.1:8788/overview.ome.zarr

Pass ``--interval 0`` to hold the tiles back until something asks for them, which
is what the browser test does so that it can decide exactly when a tile lands.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn

import numpy as np

# The writer lives at the top of the repository, three folders up from here.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from zmart_storage import Channel, TileCanvases  # noqa: E402

# The shape of the pretend scan. A five by five block of tiles is small enough to
# finish while somebody is watching and large enough that the picture visibly
# grows rather than appearing all at once.
TILES_ACROSS = 5
TILE = 512

# How large one piece of stored image is, and how many progressively smaller
# copies to keep beside the full-size one. The smaller copies are what the page
# draws when the whole overview is on screen at once, so a run with only one copy
# would look empty until you zoomed in. A tile of 512 voxels is a whole number of
# pieces at every level (128 x 2 x 2 = 512), which is what lets tiles be written
# without waiting for each other.
CHUNK = 128
LEVELS = 3

# Roughly what a 5x objective gives, which is the magnification an overview is
# taken at. It only affects the scale bar and any measurement made on the
# picture, but writing something truthful costs nothing.
VOXEL_UM = 1.3


def one_plane(index: int, plane: int, planes: int,
              height: int = TILE, width: int = TILE) -> np.ndarray:
    """One plane of one tile's picture.

    Real structure rather than a flat fill, and this matters more than it looks.
    A tile of one uniform value cannot be told apart from an empty canvas by any
    measurement of the picture, so a test that photographs the screen would pass
    just as happily on a viewer that drew nothing. A gradient with bright lines
    across it, which is the pattern the Viv trial used, has plenty of variety in
    it and stays recognisable when it is shrunk down.

    Each tile is given its own brightness so that a block of them does not come
    out as one smooth field: the boundaries between tiles stay visible, which is
    what makes "another tile landed" something you can see rather than infer.

    **Every plane of the stack shows a different amount of the tile**: the first
    plane lights only a strip along the top, and each plane below it lights more,
    until the last one fills the tile. Real specimen changes with depth too, but
    not in a way anything could state as a number — and this is the property that
    lets a test say that stepping through depth really did change the picture,
    rather than hoping somebody notices.
    """
    ramp = np.linspace(500, 3200, width, dtype=np.float32)
    tile = np.tile(ramp, (height, 1))
    tile[:: height // 8, :] = 3900          # bright rows
    tile[:, :: width // 8] += 400           # and a fainter grid the other way
    tile += 120 * (index % 5)               # a little variation tile to tile

    # Everything past this plane's share of the tile is left at a value below the
    # brightness window the run declares, so it is drawn as unimaged darkness.
    lit_rows = round(height * (plane + 1) / planes)
    tile[lit_rows:, :] = 100
    return tile.astype(np.uint16)


def one_tile(index: int, planes: int) -> np.ndarray:
    """A whole acquired tile: every plane of the stack, as ``(z, y, x)``."""
    return np.stack([one_plane(index, plane, planes) for plane in range(planes)])


def positions(pattern: str) -> list[tuple[int, int]]:
    """Which places on the canvas this run images, as ``(row, column)`` of tiles.

    Two shapes, and the second is the one worth having.

    A **raster** visits every position in turn, along the first row and then the
    next, which is what an overview of a whole area does.

    **Scattered** images five places and leaves everything between them alone:
    the four corners and the middle. That is what happens when an operator marks
    a few positions on a map and images only those, and it is the harder case for
    a viewer, because most of the canvas is then room that was declared and never
    written. Nothing exists on disk for those places at all, so a viewer has to
    treat "there is no file here" as "nothing was imaged here" and draw the gaps
    as gaps — rather than as an error, or as a picture smeared across them.
    """
    if pattern == "scattered":
        edge = TILES_ACROSS - 1
        middle = TILES_ACROSS // 2
        return [(0, 0), (0, edge), (edge, 0), (edge, edge), (middle, middle),
                (0, middle)]
    return [(row, col) for row in range(TILES_ACROSS) for col in range(TILES_ACROSS)]


# The one place in the scattered pattern that is imaged and comes back empty:
# the stage went there, the camera fired, and there was nothing to see. It is
# here because "never imaged" and "imaged and empty" are two different things
# that a run genuinely produces, and an operator watching a scan needs to be able
# to tell them apart. Whether the picture on screen lets them is a fair question
# to ask of it, and this is what makes it askable.
IMAGED_BUT_EMPTY = (0, TILES_ACROSS // 2)


class Scan:
    """The pretend acquisition: a run's images, and how far through them we are.

    The scan visits its positions in the order they are listed, which for a
    raster is the order tiles arrive in on the microscope — along the first row,
    then the next. Watching a picture fill in that order is the point of having
    the picture at all.
    """

    def __init__(self, folder: Path, *, version: str, discard_existing_run: bool,
                 pattern: str = "raster", planes: int = 1,
                 under: bool = False) -> None:
        wide = TILES_ACROSS * TILE
        self.folder = folder
        self.pattern = pattern
        self.planes = planes
        self.places = positions(pattern)
        self.total = len(self.places)
        self.written = 0
        # One tile is written at a time here, and this keeps the timer and an
        # incoming request from both deciding they are the one to write the next.
        self._turn = threading.Lock()
        # A run holds one image per acquisition type, side by side in its own
        # folder. `under` adds the first of those: a survey of the whole area,
        # already finished, which the scan being watched is drawn over.
        self.under = self._survey(folder, version, discard_existing_run) if under else None
        self.canvases = TileCanvases.create(
            folder,
            name="targetscan" if under else "overview",
            # Room for the whole block, declared before anything is imaged. A
            # declared image costs almost nothing until it is written to, so it
            # is always better to declare comfortably more room than the run
            # could need.
            canvas_shape=(planes, wide, wide),
            tile_shape=(planes, TILE, TILE),
            # The stage steps a whole tile, so the tiles do not overlap. That is
            # what lets one image hold the lot: where tiles overlap, the second
            # to arrive would replace the strip it shares with the first, and the
            # writer refuses that rather than losing it quietly.
            tile_step=(planes, TILE, TILE),
            voxel_size_um=(1.0, VOXEL_UM, VOXEL_UM),
            channels=[
                # The label and the brightness window travel with the image, in
                # its `omero` block, so the page can name the channel and open it
                # looking sensible instead of flat black.
                Channel("488", window=(400, 3600)),
            ],
            chunk=CHUNK,
            levels=LEVELS,
            ome_zarr_version=version,
            discard_existing_run=discard_existing_run,
        )
        self.store = self.canvases.paths[0]

    def _survey(self, folder: Path, version: str, discard_existing_run: bool) -> Path:
        """A finished survey of the whole area, for the scan to be drawn over.

        This is the arrangement a real run has, and it is why the writer keeps one
        image per acquisition type rather than one per run. A low-power overview
        maps the whole carrier first; the operator picks targets out of it; and
        the high-power scan of those targets is a second acquisition, written
        beside the first in the same folder and covering the same ground.

        The page draws them as two layers in one picture, the target scan over the
        survey, which is the only way an operator can see where in the sample a
        target came from. Here the survey is written in one go before anything
        else happens, because it is the part that has already been acquired by the
        time the scan being watched begins.

        It is deliberately drawn in a different colour, and one plane deep whatever
        the scan above it does: the two acquisitions are different things and
        should not be mistaken for each other on screen.
        """
        wide = TILES_ACROSS * TILE
        survey = TileCanvases.create(
            folder,
            name="overview",
            canvas_shape=(1, wide, wide),
            tile_shape=(1, TILE, TILE),
            tile_step=(1, TILE, TILE),
            voxel_size_um=(1.0, VOXEL_UM, VOXEL_UM),
            # Its own brightness window, because it is dimmer than the scan above
            # it: a survey is taken at low power and short exposure, and asking
            # for the scan's window would show it almost black. Each acquisition
            # carries the window it should be shown with, which is exactly what
            # that part of the format is for.
            channels=[Channel("561", window=(150, 1400))],
            chunk=CHUNK,
            levels=LEVELS,
            ome_zarr_version=version,
            discard_existing_run=discard_existing_run,
        )
        try:
            for row in range(TILES_ACROSS):
                for col in range(TILES_ACROSS):
                    # Dimmer than the scan above it, and smoother, so it reads as
                    # the map it is rather than competing with the detail on top.
                    plane = one_plane(row * TILES_ACROSS + col, 0, 1) // 3
                    survey.write(
                        plane[np.newaxis, :, :],
                        origin=(0, row * TILE, col * TILE),
                        tile_index=(0, row, col),
                    )
        finally:
            survey.close()
        return folder / "overview.ome.zarr"

    def write_next(self) -> bool:
        """Acquire one more position, or report that the scan has finished.

        Returns:
            ``True`` if a tile was written, ``False`` if every position of the
            scan has already been visited.
        """
        with self._turn:
            if self.written >= self.total:
                return False
            index = self.written
            row, col = self.places[index]
            empty = self.pattern == "scattered" and (row, col) == IMAGED_BUT_EMPTY
            tile = (
                # A camera that sees nothing still reports its own offset — a few
                # tens of counts — rather than exactly nothing, and that is what
                # is written here. It is also the safer choice for the question
                # being asked: storage is free to leave a piece of image out
                # altogether when every value in it is nought, which would put
                # this tile on disk in exactly the same state as a place nobody
                # visited, and the two would then be impossible to tell apart for
                # reasons that have nothing to do with the viewer.
                np.full((self.planes, TILE, TILE), 60, dtype=np.uint16) if empty
                else one_tile(index, self.planes)
            )
            self.canvases.write(
                tile,
                origin=(0, row * TILE, col * TILE),
                # A raster knows where it is in its own pattern, so it says so,
                # and the writer can place the tile without looking anything up.
                # Scattered positions have no place in a pattern — they are wherever
                # the operator marked — so they say nothing and let the writer
                # check the tile against what has already been written. Both are
                # ordinary uses of the writer, and the second is the one a
                # workflow choosing targets actually makes.
                tile_index=(0, row, col) if self.pattern == "raster" else None,
            )
            self.written += 1
            return True

    def close(self) -> None:
        self.canvases.close()


class Handler(SimpleHTTPRequestHandler):
    """Hands out the run's files, and answers the two questions the test asks.

    Serving a folder of files sounds like it needs no explanation, but there are
    three details here that a plain file server gets wrong, and each of them
    breaks the picture in a way that is hard to see.

    The first is **byte ranges**. A viewer reading a piece out of a large file
    asks for the few bytes it wants with a ``Range`` header. Python's own
    ``http.server`` ignores that header and sends the whole file back as though
    nothing had been asked — so the reader gets far more than it expected, decodes
    it as though it were the piece it wanted, and draws nonsense or nothing, with
    no error anywhere. So ranges are answered properly below.

    The second is **cross-origin access**, because the page is served by Vite on
    one port and the run lives on another. Without the headers a browser will not
    let the page read a single byte.

    The third is **caching**. The whole idea here is that a file which was empty a
    moment ago now has a tile in it. A browser that kept its first answer would
    show the empty version forever, so every answer says not to keep it.
    """

    scan: Scan | None = None

    def log_message(self, *args) -> None:      # keep the console readable
        pass

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Expose-Headers", "*")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def _answer_with(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _control(self) -> bool:
        """Deal with the two addresses that are about the scan rather than a file.

        ``/scan`` says how far the scan has got, and asking for ``/scan/next``
        acquires one more position. The timer is the ordinary way tiles arrive;
        this is here for the browser test, which needs to photograph the page
        both before a tile has landed and after, and can only do that if it
        decides when tiles land.
        """
        path = self.path.split("?")[0]
        if path == "/scan":
            self._answer_with({
                "written": self.scan.written,
                "total": self.scan.total,
                "pattern": self.scan.pattern,
                "planes": self.scan.planes,
            })
            return True
        if path == "/scan/next":
            self.scan.write_next()
            self._answer_with({
                "written": self.scan.written,
                "total": self.scan.total,
                "pattern": self.scan.pattern,
                "planes": self.scan.planes,
            })
            return True
        return False

    def do_POST(self) -> None:
        if not self._control():
            self.send_error(404)

    def do_GET(self) -> None:
        if self._control():
            return
        header = self.headers.get("Range")
        if not header:
            super().do_GET()
            return

        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            self.send_error(404)
            return
        size = os.path.getsize(path)
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
        if not match:
            self.send_error(416)
            return
        first, last = match.group(1), match.group(2)
        if first == "":
            # A range written as "-500" means the last five hundred bytes, which
            # is how a reader picks up the small index kept at the end of a file.
            length = min(int(last), size)
            start, stop = size - length, size - 1
        else:
            start = int(first)
            stop = min(int(last) if last else size - 1, size - 1)
        with open(path, "rb") as handle:
            handle.seek(start)
            body = handle.read(stop - start + 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Range", f"bytes {start}-{stop}/{size}")
        self.end_headers()
        self.wfile.write(body)


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _keep_scanning(scan: Scan, interval: float) -> None:
    """Acquire a position every ``interval`` seconds until the scan is done."""
    while True:
        time.sleep(interval)
        if not scan.write_next():
            print(f"the scan is finished: {scan.total} tiles written", flush=True)
            return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--folder",
        default=None,
        help="where to write the run. A fresh folder is made under the system's "
             "temporary directory when this is left out.",
    )
    parser.add_argument("--port", type=int, default=8788, help="the port to serve the run on")
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="seconds between tiles. Zero holds them back until something asks "
             "for one, which is what the browser test does.",
    )
    parser.add_argument(
        "--version",
        default="0.4",
        choices=["0.4", "0.5"],
        help="which generation of OME-Zarr to write. 0.4 is what a run writes "
             "today; 0.5 is the newer standard the project is moving towards.",
    )
    parser.add_argument(
        "--pattern",
        default="raster",
        choices=["raster", "scattered"],
        help="which places to image. A raster fills the canvas position by "
             "position; scattered images five places far apart and leaves the "
             "room between them unwritten, which is what imaging a few marked "
             "targets looks like on disk.",
    )
    parser.add_argument(
        "--planes",
        type=int,
        default=1,
        help="how many planes deep each tile is. More than one gives something "
             "to step through in depth, and each plane is written separately, so "
             "looking at one plane reads only that plane.",
    )
    parser.add_argument(
        "--survey-underneath",
        action="store_true",
        help="also write a finished survey of the whole area, as a second "
             "acquisition in the same run, for the scan to be drawn over. This "
             "is the arrangement a real run has: a map first, then the targets "
             "picked out of it imaged at higher power.",
    )
    parser.add_argument(
        "--discard-existing-run",
        action="store_true",
        help="throw away a run already imaged into this folder. The writer "
             "refuses to write over one otherwise, which is what stops a "
             "second demo from quietly emptying the first.",
    )
    args = parser.parse_args()

    folder = Path(args.folder) if args.folder else (
        Path(tempfile.gettempdir()) / "zmart-live-overview"
        / datetime.now().strftime("run-%Y%m%d-%H%M%S")
    )
    scan = Scan(
        folder,
        version=args.version,
        discard_existing_run=args.discard_existing_run,
        pattern=args.pattern,
        planes=args.planes,
        under=args.survey_underneath,
    )
    Handler.scan = scan
    # The run's own folder is what is served, so the image sits one name below
    # it — the same shape a real run has, where several acquisition types live
    # side by side in the folder of the run they belong to.
    handler = partial(Handler, directory=str(folder))

    address = f"http://127.0.0.1:{args.port}/{scan.store.name}"
    print(f"writing the run into {folder}", flush=True)
    print(f"{scan.total} positions, {args.pattern}, {args.planes} plane(s) deep", flush=True)
    print(f"serving it at        {address}", flush=True)
    if scan.under is None:
        print(f"watch it fill in at  http://127.0.0.1:5174/?overview={address}", flush=True)
    else:
        survey = f"http://127.0.0.1:{args.port}/{scan.under.name}"
        print(f"over a finished survey at {survey}", flush=True)
        print(
            "watch it fill in at  "
            f"http://127.0.0.1:5174/?overview={survey}&targets={address}&seethrough=1",
            flush=True,
        )
    if args.interval > 0:
        print(f"a tile every {args.interval:g} s, {scan.total} in all", flush=True)
        threading.Thread(target=_keep_scanning, args=(scan, args.interval), daemon=True).start()
    else:
        print("waiting to be asked for tiles (POST /scan/next)", flush=True)

    try:
        Server(("127.0.0.1", args.port), handler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        scan.close()


if __name__ == "__main__":
    main()
