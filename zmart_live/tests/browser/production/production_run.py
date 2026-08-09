"""A run written by the real publisher, served the way the design says.

This is the sister of ``zmart_live/tests/browser/growing_run.py``, and the one
difference between them is the whole reason it exists.

The older harness writes its two positions with a small purpose-built writer and
keeps the publication record beside it by hand. That was enough to show that a
commit decides what reaches the screen, but it left one honest complaint open,
written down as finding 4 of ``docs/design/codex-review-findings.md``: the
browser was watching a stand-in, not the code an acquisition actually runs. If
:class:`~zmart_live.coordinator.LivePublisher` ever stopped publishing in the
right order, that test would have gone on passing.

So here the pixels, the zoomed-out copies, the run-wide picture, the arrangement
and the commit all come from :meth:`LivePublisher.write_and_publish`. Nothing in
this file writes an image or moves the publication record itself; it only calls
the production path and then serves what that path left on disk.

The run
-------

Two neighbouring positions of one confocal mosaic, written at the project's own
frame size of 1152 pixels square with a single plane, which is the shape the
storage plan in :mod:`zmart_live.profiles` was designed around. The overlap the
plan chooses is 128 pixels, so each position *shows* 1024 pixels of specimen
after the shared strip has been given to one neighbour rather than both:

* **A** is the left tile, and the run-wide picture shows it from x=0 to x=1024.
* **B** is the right tile, shown from x=1024 to x=2048.

Both cover y=0 to y=1024. The picture the viewer opens is therefore 2048 across
and 1024 down, which is exactly twice the 1024 by 512 box the test page draws
into — so at two specimen pixels per screen pixel the mosaic fills that box, the
left half of the box is always A's ground, and the right half is always B's.

What the viewer is pointed at
-----------------------------

One image, and only one: the run-wide seamless overview at
``views/overview-seamless.ome.zarr``. That is not a convenience for the test. It
is the rule :mod:`zmart_live.scene` exists to protect — the drawing engine is
given one source per view and never one per position, because every source it is
handed becomes a layer that takes part in every frame for as long as the viewer
is open.

It also makes the question this test asks a fair one. Because both positions live
in one image whose declared extent covers them both from the very first moment,
"position B is not drawn" cannot be satisfied by a layer that simply never
opened. The layer is there throughout. The only thing that changes is whether the
pieces of image behind its right-hand half may be fetched.

What is refused, and why it is refused here
-------------------------------------------

The rule the whole design rests on is that a position becomes visible only when
it has been committed. Files sitting on disk mean nothing. A server that handed
over pixels the moment they were written would break that rule however careful
the viewer was, so the rule is enforced at the one place every reader has to come
through: this server refuses every piece of image belonging to a position whose
committed revision is still zero.

Two things about that refusal are worth saying plainly.

It reads the answer from :class:`~zmart_live.manifest.RunManifest`, the run's own
publication record, rather than from a list kept by hand in this file. A
hand-kept list would be a second opinion about what is published, and a test
whose gate can drift away from the thing it is testing is not a test.

And it works out *which* position a piece belongs to using
:func:`zmart_live.coarse.contributors_to`, the same production function the
publisher itself uses to decide which pieces of the zoomed-out picture a commit
has to rebuild. Nothing here re-derives the geometry.

Why nothing may be cached
-------------------------

Every answer carries ``Cache-Control: no-store``. Without it the test can go
green over stale data: the browser asks for one of B's pieces before B is
published, is refused, and later answers the same question from its own memory of
that refusal — or redraws a piece it fetched in an earlier step without ever
asking again. Either way the picture stops being evidence about what the server
was willing to serve, which is the only thing this test measures.

How the test drives it
----------------------

``POST /control/publish?position=A``
    The whole production path for one position:
    :meth:`LivePublisher.write_and_publish`. Pixels and their zoomed-out copies,
    then the run-wide picture rebuilt from what is already published plus this
    one, then the arrangement, and only then a single commit.

``POST /control/write-everything-except-the-commit?position=B``
    Every step of that same sequence apart from the last one. The position's
    pixels are written with :meth:`LivePublisher.write_a_position`, both run-wide
    pictures are rebuilt to include them, the arrangement is written — and the
    commit is not made.

    Those steps are listed out again here rather than borrowed, because the whole
    point is to stop the sequence part-way through, and a method that runs to the
    end cannot be stopped in the middle. A list copied from somewhere else can
    fall behind it, so :func:`_this_file_still_mirrors_the_production_sequence`
    reads what :meth:`write_and_publish` actually does and refuses to start the
    server if the two have drifted apart.

    This is the state a microscope is genuinely in for a moment during every
    single position, and the state it would be left in for good if the software
    stopped between writing and committing. It is also what makes the middle step
    of the browser test mean something. If the run-wide picture were left without
    B's pixels in it, then "B is not drawn" would be true merely because there was
    nothing there to draw, and the commit gate — the thing under test — would
    never have been asked a question at all.

``POST /control/commit?position=B``
    :meth:`LivePublisher.publish` on its own: go and inspect what is on disk and,
    if it justifies publication, move the record. Between this and the request
    above, not one byte of image changes. The only difference is the commit,
    which is precisely the claim the test is making.

``GET /control/state``
    What has been published so far, and how many pieces of each position have
    been served and refused since the counters were last cleared. Those counts
    matter more than they look: "the viewer asked for B and was refused" and "the
    viewer never asked for B at all" produce exactly the same black screen and
    mean completely different things.

``POST /control/forget-what-was-asked``
    Set the counts back to nought, so one step can be measured without the
    previous step's requests in the total.

``POST /control/refuse-everything``
    Behave as though nothing had ever been published, so that the screen goes
    black. This is not a feature. It exists so that the browser test can be proved
    able to notice a black screen; see ``check-the-production-test-can-fail.mjs``.

The built viewer page is served from this same server under ``/page/``, so the
page and the run share an origin and no cross-origin permissions are involved.
That keeps the test about commits rather than about browser security rules.

Run it by hand to look at the picture yourself::

    python -m zmart_live.tests.browser.production.production_run \\
        --folder /tmp/a-real-run --port 8792 --publish-the-first-position

then open the address it prints.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import shutil
import sys
import textwrap
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from zmart_live.coarse import CoarseChunk, contributors_to  # noqa: E402
from zmart_live.coordinator import LivePublisher  # noqa: E402
from zmart_live.model import GridCell, ZmartLiveError  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

#: The kind of acquisition this pretends to be. A confocal mosaic is a connected
#: grid of overlapping tiles, which is the case where a seamless run-wide picture
#: is genuinely wanted — the one the viewer opens below.
ACQUISITION = "confocal"

#: How large one frame is, in pixels. This is the size the storage plan in
#: :mod:`zmart_live.profiles` is written around: nine stored pieces of 128 pixels
#: across a frame. Choosing a rounder number here would quietly test a geometry
#: no microscope in this project ever writes.
FRAME = 1152

#: How many planes deep each position is. One, because depth is not what is being
#: tested and every extra plane is time the test spends waiting.
Z_PLANES = 1

#: The one colour this run records.
CHANNELS = ("probe",)

#: How bright the specimen is, in the stored numbers' own units, against the
#: brightness window of 0 to 4095 the test page draws with. Well clear of the
#: floor, so a position that is drawn at all is drawn brightly and the
#: measurement is not sitting on a threshold.
SIGNAL = 3000

#: The run's own name, as it is written into the publication record.
RUN_ID = "commit-gates-the-picture-in-production"

#: Where in the scan pattern each position sits: two neighbours, side by side in
#: one row.
CELLS = {GridCell(0, 0): "A", GridCell(0, 1): "B"}

#: The name of the run-wide picture the viewer opens, relative to the run folder.
#: :class:`~zmart_live.coordinator.LivePublisher` decides this; it is repeated
#: here only so the server can recognise addresses that fall inside it.
SEAMLESS = "views/overview-seamless.ome.zarr"

#: The other run-wide picture the publisher writes: the one that keeps every
#: pixel every tile recorded, overlaps included. The viewer in this test never
#: opens it, but its pieces are gated all the same, because a piece of image that
#: nobody has published must not be readable by anybody, whichever picture it
#: happens to sit in.
RAW_OVERLAP = "views/overview-raw.ome.zarr"

#: Where each position's own image lives, relative to the run folder.
POSITIONS = "positions"

#: The steps this file performs when it is asked to write a position without
#: committing it — that is, :meth:`LivePublisher.write_and_publish` stopped one
#: step short. They are checked against the real thing before the server starts;
#: see :func:`_this_file_still_mirrors_the_production_sequence`.
THE_SEQUENCE_WITHOUT_THE_COMMIT = (
    "write_a_position",
    "write_the_seamless_view",
    "write_the_raw_overlap_view",
    "write_the_layout",
)

#: The step that actually makes a position visible, and the only one the middle
#: step of the browser test leaves out.
THE_COMMIT = "publish"


def _a_frame(seed: int) -> np.ndarray:
    """The pixels of one position, as the camera would hand them over.

    Every pixel is the same brightness on purpose. A position drawn in full is
    then one flat expanse of light, which is exactly the case a test counting
    *colours* could not tell apart from a blank screen — the mistake
    ``workflows/target_acquisition/webapp-ui/tests/pixels.js`` warns about at
    length. Measuring how much of a fixed rectangle is brighter than the
    background separates the two, so a flat frame is the honest thing to write
    here rather than something textured that would flatter a weaker measurement.

    A dimmer border is drawn around the edge so that a person looking at a saved
    photograph can see where one position stops and the next begins. It changes
    no number, because every measurement is inset well away from the edges.
    """
    frame = np.full((Z_PLANES, FRAME, FRAME), SIGNAL, dtype=np.uint16)
    edge = SIGNAL // 2 + seed * 200
    frame[:, :6, :] = edge
    frame[:, -6:, :] = edge
    frame[:, :, :6] = edge
    frame[:, :, -6:] = edge
    return frame


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

    def as_json(self, names) -> dict:
        return {
            name: {
                "served": self.served.get(name, 0),
                "refused": self.refused.get(name, 0),
            }
            for name in names
        }


class ProductionRun:
    """A run driven entirely through :class:`~zmart_live.coordinator.LivePublisher`.

    Everything this class does to the run on disk, it does by calling the
    publisher. It adds only two things of its own: a memory of how many pieces
    were asked for, and the ability to answer "may this piece be served yet?" —
    and even that answer is looked up in the run's publication record rather than
    decided here.
    """

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.profile, self.geometry = plan_the_writing(
            ACQUISITION, frame=FRAME, z_planes=Z_PLANES, channels=CHANNELS
        )
        self.publisher = LivePublisher(
            folder=self.folder,
            profile=self.profile,
            run_id=RUN_ID,
            cells=CELLS,
            channels=CHANNELS,
        )
        self.names = tuple(sorted(CELLS.values()))
        self.counts = Counts()
        #: Set only by the deliberate-fault check, which needs the screen to go
        #: black on purpose so that it can find out whether the browser test
        #: notices. Nothing in an ordinary run touches this.
        self.refusing_everything = False
        self._lock = threading.Lock()

    # -- what the test asks for ---------------------------------------------

    def publish_the_whole_position(self, name: str) -> int:
        """The production path for one position, from pixels to commit.

        This is one call to :meth:`LivePublisher.write_and_publish`, which does
        the ordered sequence the architecture record lays out and refuses to
        commit anything it cannot read back off disk in full.
        """
        with self._lock:
            event = self.publisher.write_and_publish(name, _a_frame(self._seed(name)))
            return event.revision

    def write_everything_except_the_commit(self, name: str) -> None:
        """Do all of that sequence apart from the last step.

        The pixels land, every zoomed-out copy lands, both run-wide pictures are
        rebuilt to include them and the arrangement is written down. Nothing is
        published. An operator looking at the folder at this moment would say the
        position had arrived, and would be wrong: nobody may see it yet.

        These are the lines of :meth:`LivePublisher.write_and_publish` up to but
        not including the commit, called one at a time so that the sequence can be
        stopped just short of it. Calling that method instead is not an option
        here — the whole point is to hold the run in the state it passes through
        in the middle of it — so the list is checked against the real thing before
        the server starts.
        """
        with self._lock:
            already = frozenset(self.publisher.manifest.committed().by_store) | {name}
            self.publisher.write_a_position(name, _a_frame(self._seed(name)))
            self.publisher.write_the_seamless_view(already)
            self.publisher.write_the_raw_overlap_view(already)
            self.publisher.write_the_layout()

    def commit_only(self, name: str) -> int:
        """Publish a position that is already on disk, and change nothing else.

        :meth:`LivePublisher.publish` goes and inspects what was written — every
        piece read back, every pointer resolved, the run-wide picture and the
        arrangement checked — and moves the record only if what it finds
        justifies it. No image is touched, which is what makes the step before
        and after this one differ by the commit alone.
        """
        with self._lock:
            return self.publisher.publish(name).revision

    def has_been_published(self, name: str) -> bool:
        """Whether this position may be shown to anybody yet.

        A revision of zero means the run's publication record has never been
        moved for this position, whatever may be sitting on disk under its name.
        """
        if self.refusing_everything:
            return False
        return self.publisher.manifest.revision_of(name) > 0

    def state(self) -> dict:
        committed = self.publisher.manifest.committed()
        return {
            "revision": committed.revision,
            "by_position": dict(committed.by_store),
            "asked": self.counts.as_json(self.names),
            "refusing_everything": self.refusing_everything,
        }

    def _seed(self, name: str) -> int:
        if name not in self.names:
            raise ZmartLiveError(
                f"There is no position called '{name}' in this run. It has "
                f"{', '.join(self.names)}."
            )
        return self.names.index(name)

    # -- who owns a piece of image ------------------------------------------

    def who_owns(self, inside_the_run: str) -> tuple[str, str | None]:
        """Decide what may be done with one address, and say why.

        The answer is one of three words.

        ``"describe"``
            This is not a piece of image at all — it is one of the small files
            saying how large an image is and which way its axes run. Those are
            always served, because the extent a run declares is public from the
            moment it is declared. Only the pixels are gated.

        ``"gate"``
            This is a piece of image belonging to the named position, so whether
            it may be served depends on whether that position has been published.

        ``"refuse"``
            This is a piece of image and nothing here can say which position it
            belongs to. It is refused, and the reason comes back with it. Refusing
            is the only safe answer: an unattributable piece of image might belong
            to a position nobody has published, and serving it on the grounds that
            we could not tell would be exactly the leak this server exists to
            prevent.

        Which position a piece belongs to is read differently for each picture the
        publisher writes. A position's own image says so in the address. The
        seamless run-wide picture does not, so it is worked out with
        :func:`zmart_live.coarse.contributors_to` — the same production function
        the publisher uses when deciding which pieces a commit has to rebuild. The
        raw overlap picture keeps one whole tile at each stop of its tile slider,
        so the first number in the address is the stop, and the publisher's own
        :meth:`LivePublisher.tile_stop_of` says whose stop that is.
        """
        piece = _the_piece_this_address_asks_for(inside_the_run)
        if piece is None:
            return ("describe", None)

        if inside_the_run.startswith(f"{POSITIONS}/"):
            name = inside_the_run.split("/")[1].removesuffix(".ome.zarr")
            if name in self.names:
                return ("gate", name)
            return ("refuse", f"no position of this run is called '{name}'")

        if inside_the_run.startswith(f"{SEAMLESS}/"):
            # A piece of the seamless picture is addressed as (moment, colour,
            # plane, row, column); only the last two say where on the specimen it
            # is.
            chunk = CoarseChunk(level=0, index=piece[-2:], axes=("y", "x"))
            showing = contributors_to(
                self.profile, chunk, self.publisher.layout.positions
            )
            if len(showing) == 1:
                return ("gate", showing[0].position_id)
            if not showing:
                return ("refuse", "no position of this run covers that ground")
            # This cannot happen with the geometry above, and it is checked rather
            # than assumed because there would be no honest answer if it did.
            # Serving would leak a position nobody has published; refusing would
            # hide one that is finished. See
            # :func:`_the_gate_can_answer_for_every_piece`, which stops the server
            # starting at all in that case.
            return (
                "refuse",
                "that piece shows "
                + ", ".join(p.position_id for p in showing)
                + " at once, so no answer for it would be honest",
            )

        if inside_the_run.startswith(f"{RAW_OVERLAP}/"):
            for name in self.names:
                if self.publisher.tile_stop_of(name) == piece[0]:
                    return ("gate", name)
            return ("refuse", "no position of this run sits at that stop")

        # Somewhere new. The publisher may have grown another picture since this
        # was written, and a picture nobody has taught this server to read is a
        # picture it cannot promise anything about.
        return (
            "refuse",
            "this server does not know which position that piece belongs to, and "
            "will not hand over pixels it cannot account for",
        )


def _the_piece_this_address_asks_for(inside_the_run: str) -> tuple[int, ...] | None:
    """Read a stored piece's place out of its address, or say it is not a piece.

    A piece of an image written in the newer Zarr layout is filed under a folder
    called ``c`` and then one folder per axis, so its address is ``c`` followed by
    one number per axis. How many numbers that is depends on the picture — the
    seamless view has five axes and the raw overlap view has six — so they are
    counted rather than assumed. Anything else is a description of an image rather
    than pixels from one.
    """
    parts = [part for part in inside_the_run.split("/") if part]
    numbers: list[int] = []
    at = len(parts) - 1
    while at >= 0 and parts[at].isdigit():
        numbers.insert(0, int(parts[at]))
        at -= 1
    if not numbers or at < 0 or parts[at] != "c":
        return None
    return tuple(numbers)


def _this_file_still_mirrors_the_production_sequence() -> None:
    """Refuse to start if the publisher's ordered sequence has changed.

    The middle step of the browser test has to hold the run in the state it
    passes through part-way through :meth:`LivePublisher.write_and_publish`, so it
    performs that method's steps one at a time and leaves the commit off the end.
    A copied list like that can quietly fall behind the thing it copies, and if it
    did, the test would still go green while no longer testing the sequence a
    microscope actually runs.

    So the real method is read here and the steps it takes are compared against
    the list this file keeps. Reading the code is a blunt way to check, and it is
    the right one: the alternative is a silent, confident test of the wrong thing.
    """
    source = textwrap.dedent(inspect.getsource(LivePublisher.write_and_publish))
    steps = [
        (node.lineno, node.func.attr)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    ]
    found = tuple(name for _, name in sorted(steps))
    expected = (*THE_SEQUENCE_WITHOUT_THE_COMMIT, THE_COMMIT)
    if found != expected:
        raise SystemExit(
            "LivePublisher.write_and_publish no longer does what this test thinks "
            "it does, so the test would be measuring a sequence nobody runs.\n"
            f"  it now does: {', '.join(found) or 'nothing this check could see'}\n"
            f"  this test expects: {', '.join(expected)}\n"
            "Update THE_SEQUENCE_WITHOUT_THE_COMMIT in "
            f"{Path(__file__).name} so that the middle step of the browser test "
            "still stops exactly one step short of the commit, and check that the "
            "new step does not put unpublished pixels anywhere a reader can see "
            "them."
        )


def _the_gate_can_answer_for_every_piece(run: ProductionRun) -> None:
    """Refuse to start unless every piece of the run-wide picture has one owner.

    The gate can only be honest when the boundary between two positions falls on
    a boundary between stored pieces. If it did not, one piece would hold pixels
    from both, and there would be no truthful answer to give for it while one of
    them was published and the other was not.

    With the geometry this file chooses, it does: the positions are 1024 pixels
    apart and the stored pieces are 128 pixels across. That is checked here
    anyway, because the check costs a fraction of a second and the alternative is
    a test that quietly measures something other than what it claims.
    """
    seamless = run.folder / SEAMLESS
    across = run.profile.level(0).inner_chunk
    height, width = run.publisher._mosaic_extent()
    trouble = []
    for row in range(-(-height // across["y"])):
        for column in range(-(-width // across["x"])):
            chunk = CoarseChunk(level=0, index=(row, column), axes=("y", "x"))
            showing = contributors_to(
                run.profile, chunk, run.publisher.layout.positions
            )
            if len(showing) > 1:
                trouble.append(
                    f"the piece at row {row}, column {column} shows "
                    f"{', '.join(p.position_id for p in showing)}"
                )
    if trouble:
        raise SystemExit(
            "This run cannot be gated honestly, so it is not worth serving. Some "
            "pieces of the run-wide picture at "
            f"{seamless} hold more than one position at once, which means neither "
            "serving nor refusing them would tell the truth: "
            + "; ".join(trouble)
            + ". Change the frame size or the positions so that the boundary "
            "between them falls on a whole piece."
        )


def make_handler(run: ProductionRun, page: Path):
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
            # Nothing may be remembered by the browser. See the note at the top of
            # this file: a cached piece turns this test's evidence into a memory
            # of what the server used to allow.
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
                if asked.path == "/control/publish":
                    run.publish_the_whole_position(wanted)
                elif asked.path == "/control/write-everything-except-the-commit":
                    run.write_everything_except_the_commit(wanted)
                elif asked.path == "/control/commit":
                    run.commit_only(wanted)
                elif asked.path == "/control/forget-what-was-asked":
                    run.counts.forget()
                elif asked.path == "/control/refuse-everything":
                    run.refusing_everything = True
                else:
                    self._send_json({"trouble": f"no such control: {asked.path}"}, 404)
                    return
            except (ZmartLiveError, ValueError, OSError) as trouble:
                self._send_json({"trouble": f"{type(trouble).__name__}: {trouble}"}, 400)
                return
            self._send_json(run.state())

        # -- everything a browser reads -------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            asked = unquote(urlparse(self.path).path)
            if asked == "/control/state":
                self._send_json(run.state())
                return
            if asked.startswith("/page/"):
                self._serve_the_page(page / asked[len("/page/") :])
                return
            self._serve_from_the_run(asked.lstrip("/"))

        def _serve_the_page(self, where: Path) -> None:
            self._read_and_send(where)

        def _serve_from_the_run(self, inside_the_run: str) -> None:
            answer, about = run.who_owns(inside_the_run)
            if answer == "refuse":
                self._send(404, f"not served: {about}".encode(), "text/plain")
                return
            if answer == "gate":
                allowed = run.has_been_published(about)
                run.counts.note(about, allowed=allowed)
                if not allowed:
                    # The honest answer for a position nobody has published is the
                    # same as for a position nobody has imaged: there is nothing
                    # here. A reader is meant to take that as empty ground and
                    # carry on drawing what it does have, which is the other half
                    # of what this test checks.
                    self._send(404, b"that position has not been committed", "text/plain")
                    return
            self._read_and_send(run.folder / inside_the_run)

        def _read_and_send(self, where: Path) -> None:
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


def serve(folder: Path, port: int) -> tuple[ThreadingHTTPServer, ProductionRun]:
    """Start the run and the server, and hand both back without blocking."""
    _this_file_still_mirrors_the_production_sequence()
    run = ProductionRun(folder)
    _the_gate_can_answer_for_every_piece(run)
    page = Path(__file__).resolve().parents[1] / "page" / "built"
    if not (page / "index.html").exists():
        raise SystemExit(
            f"The viewer page has not been built yet, so there is nothing to open. "
            f"Expected it at {page}. Run `node build-the-page.mjs` in "
            f"{page.parents[1]}, which the browser test does for you."
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
        "--publish-the-first-position",
        action="store_true",
        help="write and publish position A before serving, which is where the "
        "browser test's three-step sequence begins",
    )
    chosen = parser.parse_args()

    if chosen.folder.exists():
        shutil.rmtree(chosen.folder)
    server, run = serve(chosen.folder, chosen.port)
    if chosen.publish_the_first_position:
        run.publish_the_whole_position("A")
    address = f"http://127.0.0.1:{chosen.port}"
    print(f"the run is on {address}, showing {SEAMLESS}", flush=True)
    print(
        f"open {address}/page/index.html?store={address}/{SEAMLESS}/%7Czarr3:",
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
