"""A run that grows while a browser is watching it, served the way the design says.

This is the half of the browser test that stands in for the microscope. It writes
a real OME-Zarr with the project's own writer, keeps the publication record from
:mod:`zmart_live.manifest` beside it, and serves the whole thing over HTTP — but
it refuses to hand over any piece of image belonging to a position that has not
been committed yet.

That refusal is the point. The rule the design rests on is that data becomes
visible only once the complete position has been committed; files existing on
disk means nothing. A server that hands out pixels the moment they are written
would break that rule no matter how careful the viewer was, so the rule is
enforced here, at the one place every reader has to come through.

The run
-------

Two positions, side by side, in one image:

* **A** covers the left half of the canvas, from x=0 to x=512.
* **B** covers the right half, from x=512 to x=1024.

They are two halves of a *single* OME-Zarr, which is how an acquisition really
writes them and is what makes the test worth running. If each position were a
separate image, then "B is not drawn" could be satisfied by a viewer that simply
never opened a second image, which proves nothing about commits. Here the viewer
opens one image whose declared room covers both positions from the very
beginning, and the only thing that changes is whether the pieces of image behind
B's half can be fetched at all.

The canvas is deliberately small — 1024 by 512 voxels, one plane, one colour — so
that the whole browser test finishes in a couple of minutes rather than half an
hour.

Why nothing is allowed to be cached
-----------------------------------

Every answer is sent with ``Cache-Control: no-store``. Without it the test can go
green over stale data: the browser asks for one of B's pieces before B is
committed, is refused, and then — after B is committed — answers the same
question from its own memory of the refusal, or worse, a piece fetched during an
earlier step is redrawn without ever being asked for again. Either way the
picture on screen would stop being evidence about what the server was willing to
serve, which is the only thing this test measures.

How it is driven
----------------

The browser test starts one of these, then tells it what to do through a few
plain HTTP requests:

``POST /control/write?position=B``
    Put B's pixels on disk. Nothing about the picture changes: the position has
    not been committed, so the server still refuses every piece of it.

``POST /control/commit?position=B``
    Publish B through :class:`~zmart_live.manifest.RunManifest`. From this moment
    the server will serve B's pieces.

``GET /control/state``
    What has been committed so far, and how many pieces of each position the
    server has served and refused since it started. The counts matter more than
    they look: "the viewer asked for B and was refused" and "the viewer never
    asked for B at all" produce exactly the same black screen and mean completely
    different things.

``POST /control/forget-what-was-asked``
    Set those counts back to nought, so that one step of the test can be measured
    without the previous step's requests in the total.

``POST /control/refuse-everything``
    Behave as though nothing had ever been committed, so that the screen goes
    black. This exists for one reason and it is not a feature: it is how the
    browser test is proved able to notice a black screen. See
    ``check-the-test-can-fail.mjs``.

The built viewer page is served from this same server, under ``/page/``, so that
the page and the run share an origin and no cross-origin permissions are
involved. That keeps the test about commits rather than about browser security
rules.

Run it by hand to look at the picture yourself::

    python -m zmart_live.tests.browser.growing_run --folder /tmp/a-run --port 8791

then open ``http://127.0.0.1:8791/page/index.html?store=http://127.0.0.1:8791/live.ome.zarr/|zarr2:``
and use the control requests above to watch the two halves appear.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from zmart_live.manifest import RunManifest  # noqa: E402
from zmart_live.model import Box, CommitEvent, GridCell  # noqa: E402
from zmart_storage.canvas import Channel, TileCanvases  # noqa: E402

#: What the image is called on disk, and therefore the first part of every
#: address the viewer asks for.
STORE = "live.ome.zarr"

#: The run's shape, in voxels, as (z, y, x). One plane and one colour, because
#: depth is not what is being tested and every extra plane is time the test
#: spends waiting.
CANVAS = (1, 512, 1024)

#: One position's shape, as (z, y, x). Two of these side by side fill the canvas.
TILE = (1, 512, 512)

#: How large a piece of image is, in y and x. This has to divide the boundary
#: between the two positions exactly — see :func:`_which_position_owns_each_piece`,
#: which refuses to start if it does not.
PIECE = 256

#: How bright the specimen is, in the stored numbers' own units, against a
#: brightness window running from 0 to 4095. Well clear of the floor, so that a
#: position which is drawn at all is drawn brightly and the measurement is not
#: sitting on a threshold.
SIGNAL = 3000

#: The run's own name, and the kind of acquisition it is, as they are written
#: into the publication record.
RUN_ID = "commit-gates-the-picture"
ACQUISITION = "targetscan"
PROFILE = "browser-test-profile"


@dataclass(frozen=True)
class Position:
    """One imaged place: what it is called, and which part of the canvas it fills."""

    name: str
    #: Where its low corner sits in the canvas, as (z, y, x) in voxels.
    origin: tuple[int, int, int]
    #: Which square of the scan pattern it is, which the writer records.
    cell: tuple[int, int]


POSITIONS = (
    Position(name="A", origin=(0, 0, 0), cell=(0, 0)),
    Position(name="B", origin=(0, 0, 512), cell=(0, 1)),
)


def _a_tile(seed: int) -> np.ndarray:
    """The pixels of one position.

    Every voxel is the same brightness on purpose. A position drawn in full is
    then one flat expanse of light, which is the case a test that counted
    *colours* rather than *lit pixels* could not tell apart from a blank screen —
    the mistake `workflows/target_acquisition/webapp-ui/tests/pixels.js` warns
    about at length. Measuring how much of a fixed rectangle is brighter than the
    background separates the two, so a flat tile is the honest thing to write
    here rather than something with texture that would flatter a weaker
    measurement.

    A faint border of a different brightness is drawn around the edge so that a
    person looking at a saved photograph can see where one position stops and the
    next begins. It does not affect the measurement, which insets well away from
    the edges.
    """
    tile = np.full(TILE, SIGNAL, dtype=np.uint16)
    edge = SIGNAL // 2 + seed * 200
    tile[:, :4, :] = edge
    tile[:, -4:, :] = edge
    tile[:, :, :4] = edge
    tile[:, :, -4:] = edge
    return tile


def _which_position_owns_each_piece() -> dict[int, str]:
    """Work out which position each column of pieces belongs to.

    A piece of image is the smallest thing the viewer can ask for, and this
    server has to answer for each one on its own. So the question "may this be
    served yet?" comes down to "which position wrote it?", and the answer has to
    be one position and not two.

    That is only true when the boundary between the positions falls exactly on a
    boundary between pieces. If it did not, one piece would hold pixels from both
    positions, and there would be no honest answer to give for it: serving it
    would leak a position that has not been published, and refusing it would hide
    one that has. Rather than pick between two wrong answers, this refuses to
    start and says so.
    """
    owners: dict[int, str] = {}
    for position in POSITIONS:
        low = position.origin[2]
        high = low + TILE[2]
        if low % PIECE or high % PIECE:
            raise SystemExit(
                f"Position {position.name} covers x={low} to x={high}, which does "
                f"not line up with the {PIECE}-voxel pieces the image is stored "
                f"in. A piece would then hold pixels from two positions at once, "
                f"and this server could neither serve nor refuse it honestly. "
                f"Change PIECE or the positions so that the boundary between them "
                f"falls on a whole piece."
            )
        for column in range(low // PIECE, high // PIECE):
            owners[column] = position.name
    return owners


@dataclass
class Counts:
    """How many pieces of each position were served, and how many were refused."""

    served: dict[str, int] = field(default_factory=dict)
    refused: dict[str, int] = field(default_factory=dict)

    def note(self, position: str, *, allowed: bool) -> None:
        where = self.served if allowed else self.refused
        where[position] = where.get(position, 0) + 1

    def forget(self) -> None:
        self.served.clear()
        self.refused.clear()

    def as_json(self) -> dict:
        return {
            name: {
                "served": self.served.get(name, 0),
                "refused": self.refused.get(name, 0),
            }
            for name in [p.name for p in POSITIONS]
        }


class GrowingRun:
    """The run itself: the image on disk, the publication record, and the writing."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.canvases = TileCanvases.create(
            self.folder,
            name="live",
            canvas_shape=CANVAS,
            tile_shape=TILE,
            tile_step=TILE,
            voxel_size_um=(1.0, 1.0, 1.0),
            channels=[Channel("probe", window=(0, 4095))],
            chunk=PIECE,
            # One size only, with no smaller copies. A pyramid would be the right
            # thing for a real run and the wrong thing here: a zoomed-out copy is
            # built from every position that touches it, so a single piece of it
            # would hold parts of both positions and there would be no honest
            # answer to give when one of them is committed and the other is not.
            # That problem is real and is worth a test of its own; it is not this
            # test, and mixing the two would make neither of them clear.
            levels=1,
            ome_zarr_version="0.4",
            discard_existing_run=True,
        )
        self.manifest = RunManifest.start(self.folder, RUN_ID)
        self.written: set[str] = set()
        self.owners = _which_position_owns_each_piece()
        self.counts = Counts()
        #: Set only by the deliberate-fault check, which needs to make the screen
        #: go black on purpose so that it can find out whether the browser test
        #: notices. Nothing in an ordinary run touches this.
        self.refusing_everything = False
        self._lock = threading.Lock()

    def close(self) -> None:
        self.canvases.close()

    # -- what the test asks for ---------------------------------------------

    def write(self, name: str) -> None:
        """Put one position's pixels on disk, and publish nothing.

        This is the step that is easy to mistake for progress. The files are
        there afterwards, complete and correct, and an operator looking at the
        folder would say the position had arrived. Nobody may see it yet.
        """
        with self._lock:
            if name in self.written:
                return
            position = self._position(name)
            self.canvases.write(
                _a_tile(POSITIONS.index(position)),
                origin=position.origin,
                tile_index=(0, position.cell[0], position.cell[1]),
            )
            self.written.add(name)

    def commit(self, name: str) -> int:
        """Publish one position, which is the moment it becomes visible.

        Everything a commit depends on is claimed as checked here, because in
        this small run there genuinely is nothing else to check: one size of
        image, no zoomed-out copies, no pointers and no shared coarse pieces. A
        real writer earns each of those flags; see :meth:`RunManifest.publish`,
        which refuses a commit that does not claim them all.
        """
        with self._lock:
            position = self._position(name)
            if name not in self.written:
                raise ValueError(
                    f"Position {name} has not been written yet, so committing it "
                    f"would publish a position whose pixels do not exist. That is "
                    f"exactly the mistake the publication record is there to "
                    f"prevent, so it is refused here too."
                )
            revision = self.manifest.next_revision()
            self.manifest.publish(
                CommitEvent(
                    revision=revision,
                    event_type="position_committed",
                    position_id=name,
                    run_id=RUN_ID,
                    acquisition_type=ACQUISITION,
                    acquisition_profile_id=PROFILE,
                    scene_layout_revision=1,
                    link_revision=1,
                    component_id="one-strip",
                    cell=GridCell(*position.cell),
                    owned_region=Box.of(
                        y=(position.origin[1], position.origin[1] + TILE[1]),
                        x=(position.origin[2], position.origin[2] + TILE[2]),
                    ),
                    channels=("probe",),
                    levels=(0,),
                    pyramids_ready=True,
                    links_ready=True,
                    coarse_chunks_ready=True,
                    validated=True,
                )
            )
            return revision

    def is_visible(self, name: str) -> bool:
        """Whether this position has been published, and may therefore be served."""
        if self.refusing_everything:
            return False
        return self.manifest.revision_of(name) > 0

    def state(self) -> dict:
        committed = self.manifest.committed()
        return {
            "revision": committed.revision,
            "by_store": dict(committed.by_store),
            "written": sorted(self.written),
            "asked": self.counts.as_json(),
            "refusing_everything": self.refusing_everything,
        }

    def _position(self, name: str) -> Position:
        for position in POSITIONS:
            if position.name == name:
                return position
        raise ValueError(
            f"There is no position called '{name}' in this run. It has "
            f"{', '.join(p.name for p in POSITIONS)}."
        )


def _the_piece_this_address_asks_for(parts: list[str]) -> int | None:
    """Which column of pieces an address is asking for, or ``None`` if it is not.

    A piece of a five-dimensional image is stored under one folder per axis, so
    its address ends in five numbers: which moment, which colour, which plane,
    which row of pieces and which column. Anything else under the image — the
    small files describing its shape and its axes — is not a piece and is always
    served, because the room a run declares is public from the moment it is
    declared. Only the pixels are gated.
    """
    if len(parts) < 5:
        return None
    tail = parts[-5:]
    if not all(part.isdigit() for part in tail):
        return None
    return int(tail[-1])


def make_handler(run: GrowingRun, page: Path):
    """Build the request handler, closing over the run it answers for."""

    class Handler(BaseHTTPRequestHandler):
        # Keeps the test's own output readable. Every request is counted anyway,
        # and the counts are what the test looks at.
        def log_message(self, *_args) -> None:  # noqa: D102
            return

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            # Nothing may be remembered by the browser. See the note at the top
            # of this file: a cached piece turns this test's evidence into a
            # memory of what the server used to allow.
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, value: dict, status: int = 200) -> None:
            self._send(status, json.dumps(value, indent=2).encode(), "application/json")

        # -- the control requests the test drives the run with --------------

        def do_POST(self) -> None:  # noqa: N802 - the name the library requires
            asked = urlparse(self.path)
            wanted = parse_qs(asked.query).get("position", [""])[0]
            try:
                if asked.path == "/control/write":
                    run.write(wanted)
                elif asked.path == "/control/commit":
                    run.commit(wanted)
                elif asked.path == "/control/forget-what-was-asked":
                    run.counts.forget()
                elif asked.path == "/control/refuse-everything":
                    run.refusing_everything = True
                else:
                    self._send_json({"trouble": f"no such control: {asked.path}"}, 404)
                    return
            except (ValueError, OSError) as trouble:
                self._send_json({"trouble": str(trouble)}, 400)
                return
            self._send_json(run.state())

        # -- everything a browser reads -------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            asked = unquote(urlparse(self.path).path)
            if asked == "/control/state":
                self._send_json(run.state())
                return
            if asked.startswith("/page/"):
                self._serve_file(page / asked[len("/page/") :], gate=False)
                return
            self._serve_file(run.folder / asked.lstrip("/"), gate=True)

        def _serve_file(self, where: Path, *, gate: bool) -> None:
            parts = [part for part in where.parts if part not in ("/", "")]
            column = _the_piece_this_address_asks_for(parts) if gate else None

            if column is not None:
                owner = run.owners.get(column)
                if owner is None:
                    self._send(404, b"no position covers that piece", "text/plain")
                    return
                allowed = run.is_visible(owner)
                run.counts.note(owner, allowed=allowed)
                if not allowed:
                    # The honest answer for a position nobody has published is the
                    # same as for a position nobody has imaged: there is nothing
                    # here. A reader is meant to take that as emptiness and carry
                    # on drawing what it does have, which is the other half of
                    # what this test is checking.
                    self._send(404, b"that position has not been committed", "text/plain")
                    return

            try:
                body = where.read_bytes()
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                self._send(404, b"not here", "text/plain")
                return
            kinds = {
                ".html": "text/html",
                ".js": "text/javascript",
                ".css": "text/css",
                ".json": "application/json",
            }
            self._send(200, body, kinds.get(where.suffix, "application/octet-stream"))

    return Handler


def serve(folder: Path, port: int) -> tuple[ThreadingHTTPServer, GrowingRun]:
    """Start the run and the server, and hand both back without blocking."""
    run = GrowingRun(folder)
    page = Path(__file__).resolve().parent / "page" / "built"
    if not (page / "index.html").exists():
        raise SystemExit(
            f"The viewer page has not been built yet, so there is nothing to open. "
            f"Expected it at {page}. Run `node build-the-page.mjs` in "
            f"{Path(__file__).resolve().parent}, which the browser test does for you."
        )
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(run, page))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--folder", required=True, type=Path, help="where to write the run; emptied first"
    )
    parser.add_argument("--port", required=True, type=int, help="which port to serve it on")
    parser.add_argument(
        "--commit-first-position",
        action="store_true",
        help="write and commit position A before serving, which is "
        "where the browser test's three-step sequence begins",
    )
    chosen = parser.parse_args()

    if chosen.folder.exists():
        shutil.rmtree(chosen.folder)
    server, run = serve(chosen.folder, chosen.port)
    if chosen.commit_first_position:
        run.write("A")
        run.commit("A")
    address = f"http://127.0.0.1:{chosen.port}"
    print(f"the run is on {address}, serving {STORE}", flush=True)
    print(
        f"open {address}/page/index.html?store={address}/{STORE}/%7Czarr2:",
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        run.close()


if __name__ == "__main__":
    main()
