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

A row of neighbouring positions from one confocal mosaic, written at the
project's own frame size of 1152 pixels square with a single plane, which is the
shape the storage plan in :mod:`zmart_live.profiles` was designed around. The
overlap the plan chooses is 128 pixels, so each position *shows* 1024 pixels of
specimen after the shared strip has been given to one neighbour rather than
both:

* **A** is the leftmost tile, and the run-wide picture shows it from x=0 to
  x=1024.
* **B** is next along, shown from x=1024 to x=2048, and so on.

How many tiles there are, and how many moments in time each of them holds, are
chosen when the server starts (``--tiles-in-a-row`` and ``--moments``). Two
tiles and one moment is the smallest run that can ask the original question — is
a written-but-uncommitted position on the screen? — and it stays the default so
that the first browser test beside this file is unchanged.

Two larger runs are worth having, and each of them exists because a run of two
tiles at one moment cannot see a mistake that a real acquisition would meet
every day.

**Three tiles in a row.** The picture that keeps every overlapping pixel gives
each tile a stop on a slider, and those stops are deliberately shared out like
the squares of a chessboard, so that tiles too far apart to overlap sit on the
same stop. In a row of three, the first and the third share a stop. If the
server worked out which position a piece of that picture belonged to from its
stop alone, it would hand over the third tile's pixels while claiming they were
the first tile's — and a run of only two tiles could never show that, because in
a row of two no stop is ever shared.

**More than one moment.** A position is committed one moment at a time. Once its
first moment is published, a server that asks only "has this position been
published?" will hand over every later moment as soon as it is written, which is
exactly what the commit is supposed to prevent.

What the viewer is pointed at
-----------------------------

One image, and only one: the run-wide seamless overview at
``views/overview.ome.zarr``. That is not a convenience for the test. It
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
through: this server refuses every piece of image that belongs to a moment of a
position which has not been committed.

Three things about that refusal are worth saying plainly.

It reads the answer from :class:`~zmart_live.manifest.RunManifest`, the run's own
publication record, rather than from a list kept by hand in this file. A
hand-kept list would be a second opinion about what is published, and a test
whose gate can drift away from the thing it is testing is not a test.

The thing it looks up is a *position and a moment together*, never a position on
its own. A position is committed one moment at a time, so "position A has been
published" is not an answer to the question "may this piece be served" — it is an
answer to a different and much weaker question, and using it would put every
later moment of A on the screen the instant it was written, which is precisely
what the commit is there to prevent.

And it works out *which* position and moment a piece belongs to from the piece's
own address, using the production geometry rather than any rule invented here.
Every stored piece carries the moment it belongs to as one of the numbers in its
address. For the seamless picture, the position comes from
:func:`zmart_live.coarse.contributors_to` — the same production function the
publisher uses to decide which pieces of the zoomed-out picture a commit has to
rebuild. For the picture that keeps every overlapping pixel, the position comes
from the piece's stop on the tile slider **and** the ground that piece covers,
taken together. The stop on its own is not enough, and that is the point worth
remembering: stops are deliberately shared between tiles that are too far apart
to overlap, so a stop names a scattering of tiles across the whole mosaic rather
than one of them.

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

Each of the three requests below names a position, and may also name a moment
with ``&moment=1``. Leaving the moment out means the first one, which is the only
moment a run started with ``--moments 1`` has.

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
    What has been published so far, and how many pieces have been served and
    refused since the counters were last cleared. Those counts matter more than
    they look: "the viewer asked for B and was refused" and "the viewer never
    asked for B at all" produce exactly the same black screen and mean completely
    different things.

    The counts come back twice over. ``asked`` totals them by position, which is
    what a run of one moment needs. ``asked_by_moment`` keeps the moment separate
    — ``"A moment 1"`` — because a test about moments has to be able to say that
    the viewer asked for a *particular* moment of a position and was refused,
    which a total for the whole position cannot tell it.

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

#: How many tiles the run has, and how many moments in time each of them holds,
#: unless the command line says otherwise. Two tiles at one moment is the
#: smallest run that can ask the original question, and it is what the first
#: browser test beside this file expects to find.
TILES_IN_A_ROW = 2
MOMENTS = 1


def cells_in_a_row(how_many: int) -> dict[GridCell, str]:
    """Where in the scan pattern each position sits: neighbours along one row.

    The positions are named A, B, C and so on from left to right, and each sits
    in the next column of the same row, which is the simplest scan pattern a
    mosaic can have. A row is enough for everything tested here and it keeps the
    picture on screen easy to read: the leftmost part of it is always A's ground.
    """
    if how_many < 1 or how_many > 26:
        raise SystemExit(
            f"A run of {how_many} tiles cannot be built here. This file names its "
            "positions with single letters, so it can hold between 1 and 26 of "
            "them, and every test that uses it wants at least two."
        )
    return {
        GridCell(0, column): chr(ord("A") + column) for column in range(how_many)
    }

#: The name of the run-wide picture the viewer opens, relative to the run folder.
#: :class:`~zmart_live.coordinator.LivePublisher` decides this; it is repeated
#: here only so the server can recognise addresses that fall inside it.
SEAMLESS = "views/overview.ome.zarr"

#: Where each position's own image lives, relative to the run folder.
POSITIONS = "positions"

#: The steps this file performs when it is asked to write a position without
#: committing it — that is, :meth:`LivePublisher.write_and_publish` stopped one
#: step short. They are checked against the real thing before the server starts;
#: see :func:`_this_file_still_mirrors_the_production_sequence`.
THE_SEQUENCE_WITHOUT_THE_COMMIT = (
    "write_a_position",
    "write_the_link_map",
    "write_the_view",
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


@dataclass(frozen=True)
class Wrote:
    """The one position, at the one moment, whose camera wrote a piece of image.

    Both halves are needed and neither is enough on its own. A position is
    committed one moment at a time, so knowing only the position cannot answer
    "may this be shown"; and a moment on its own belongs to every position in the
    run at once. This little pair is what the gate looks up and what the counters
    are kept by, so that the two can never quietly come apart.
    """

    position: str
    moment: int

    def __str__(self) -> str:
        return f"{self.position} moment {self.moment}"


@dataclass
class Counts:
    """How many pieces were served, and how many were refused.

    The tally is kept per position **and** per moment, because a test about
    moments needs to be able to say that the viewer went and asked for a
    particular moment and was turned away. A total for the whole position cannot
    distinguish that from the viewer having asked for an earlier moment it was
    perfectly entitled to see.
    """

    served: dict[Wrote, int] = field(default_factory=dict)
    refused: dict[Wrote, int] = field(default_factory=dict)

    def note(self, wrote: Wrote, *, allowed: bool) -> None:
        where = self.served if allowed else self.refused
        where[wrote] = where.get(wrote, 0) + 1

    def forget(self) -> None:
        self.served.clear()
        self.refused.clear()

    def as_json(self, names) -> dict:
        """The tally added up per position, whichever moment each piece was of."""
        return {
            name: {
                "served": sum(
                    count for wrote, count in self.served.items()
                    if wrote.position == name
                ),
                "refused": sum(
                    count for wrote, count in self.refused.items()
                    if wrote.position == name
                ),
            }
            for name in names
        }

    def by_moment_json(self, names, moments: int) -> dict:
        """The same tally with each moment of each position kept apart."""
        return {
            str(Wrote(name, moment)): {
                "served": self.served.get(Wrote(name, moment), 0),
                "refused": self.refused.get(Wrote(name, moment), 0),
            }
            for name in names
            for moment in range(moments)
        }


class ProductionRun:
    """A run driven entirely through :class:`~zmart_live.coordinator.LivePublisher`.

    Everything this class does to the run on disk, it does by calling the
    publisher. It adds only two things of its own: a memory of how many pieces
    were asked for, and the ability to answer "may this piece be served yet?" —
    and even that answer is looked up in the run's publication record rather than
    decided here.
    """

    def __init__(
        self,
        folder: Path,
        *,
        tiles_in_a_row: int = TILES_IN_A_ROW,
        moments: int = MOMENTS,
    ) -> None:
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.profile, self.geometry = plan_the_writing(
            ACQUISITION, frame=FRAME, z_planes=Z_PLANES, channels=CHANNELS
        )
        self.cells = cells_in_a_row(tiles_in_a_row)
        self.moments = moments
        self.publisher = LivePublisher(
            folder=self.folder,
            profile=self.profile,
            run_id=RUN_ID,
            cells=self.cells,
            channels=CHANNELS,
            timepoints=moments,
        )
        self.names = tuple(sorted(self.cells.values()))
        self.counts = Counts()
        #: Set only by the deliberate-fault check, which needs the screen to go
        #: black on purpose so that it can find out whether the browser test
        #: notices. Nothing in an ordinary run touches this.
        self.refusing_everything = False
        self._lock = threading.Lock()

    # -- what the test asks for ---------------------------------------------

    def publish_the_whole_position(self, name: str, moment: int = 0) -> int:
        """The production path for one position, from pixels to commit.

        This is one call to :meth:`LivePublisher.write_and_publish`, which does
        the ordered sequence the architecture record lays out and refuses to
        commit anything it cannot read back off disk in full.
        """
        with self._lock:
            event = self.publisher.write_and_publish(
                name,
                _a_frame(self._seed(name)),
                timepoint=self._how_the_record_names(name, moment),
            )
            return event.revision

    def _how_the_record_names(self, name: str, moment: int) -> int | None:
        """How the publication record wants this moment referred to.

        The run's record keeps two different kinds of entry, and it refuses the
        wrong one, so this is not a matter of taste. The entry that *introduces* a
        position names no moment at all — it says "this position now exists and is
        visible" — and the publisher writes its pixels at the first moment. Every
        later moment of that same position is named explicitly, because the record
        already knows the position and what is new is the moment.

        So the first moment is passed as "no moment named", and every later one is
        passed as itself.
        """
        self._check_the_moment(moment)
        return None if moment == 0 else moment

    def _check_the_moment(self, moment: int) -> None:
        if not 0 <= moment < self.moments:
            raise ZmartLiveError(
                f"This run holds {self.moments} moment(s) in time, numbered from "
                f"0 to {self.moments - 1}, so there is no moment {moment} to "
                f"write or publish. Start the run with --moments if a longer one "
                f"is wanted."
            )

    def write_everything_except_the_commit(self, name: str, moment: int = 0) -> None:
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
            self._check_the_moment(moment)
            self.publisher.write_a_position(
                name, _a_frame(self._seed(name)), timepoint=moment
            )
            units = frozenset(self.publisher._committed_units()) | {(name, moment)}
            self.publisher.write_the_link_map(units)
            self.publisher.write_the_view()
            self.publisher.write_the_layout()

    def commit_only(self, name: str, moment: int = 0) -> int:
        """Publish a position that is already on disk, and change nothing else.

        :meth:`LivePublisher.publish` goes and inspects what was written — every
        piece read back, every pointer resolved, the run-wide picture and the
        arrangement checked — and moves the record only if what it finds
        justifies it. No image is touched, which is what makes the step before
        and after this one differ by the commit alone.
        """
        with self._lock:
            return self.publisher.publish(
                name, timepoint=self._how_the_record_names(name, moment)
            ).revision

    def has_been_published(self, wrote: Wrote) -> bool:
        """Whether this moment of this position may be shown to anybody yet.

        The question is asked about a position **and** a moment together, which is
        the whole of the matter. A run publishes one moment of one position at a
        time, so a position whose first moment is on the screen may perfectly well
        have a second moment sitting on disk that nobody has committed. Answering
        "yes, that position is published" to a question about the second moment
        would put unpublished pixels on screen, which is the one thing this server
        exists to prevent.

        The answer is read out of the run's own history of publications rather
        than from anything kept here. Each entry in that history says which
        position it made visible and, if it was a later moment rather than the
        position's first appearance, which moment. An entry that names no moment
        is the one that introduced the position, and the publisher writes a
        position's first appearance at the first moment — so that is the moment
        such an entry makes visible.
        """
        if self.refusing_everything:
            return False
        return wrote.moment in self.moments_published_of(wrote.position)

    def moments_published_of(self, name: str) -> frozenset[int]:
        """Which moments of one position the run has actually committed."""
        return frozenset(
            0 if event.timepoint is None else event.timepoint
            for event in self.publisher.manifest.events_for(name)
        )

    def state(self) -> dict:
        committed = self.publisher.manifest.committed()
        return {
            "revision": committed.revision,
            "by_position": dict(committed.by_store),
            "moments_published": {
                name: sorted(self.moments_published_of(name)) for name in self.names
            },
            "asked": self.counts.as_json(self.names),
            "asked_by_moment": self.counts.by_moment_json(self.names, self.moments),
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

    def who_owns(self, inside_the_run: str) -> tuple[str, Wrote | str | None]:
        """Decide what may be done with one address, and say why.

        The answer is one of three words.

        ``"describe"``
            This is not a piece of image at all — it is one of the small files
            saying how large an image is and which way its axes run. Those are
            always served, because the extent a run declares is public from the
            moment it is declared. Only the pixels are gated.

        ``"gate"``
            This is a piece of image, and it is known which position wrote it and
            at which moment. Whether it may be served then depends on whether that
            position has been committed *at that moment*. The pair comes back as a
            :class:`Wrote`.

        ``"refuse"``
            This is a piece of image and nothing here can say which position and
            moment it belongs to. It is refused, and the reason comes back with
            it. Refusing is the only safe answer: an unattributable piece of image
            might belong to something nobody has published, and serving it on the
            grounds that we could not tell would be exactly the leak this server
            exists to prevent.

        How the pair is read out of an address
        --------------------------------------

        The moment is the easy half, and it is never guessed: every picture the
        publisher writes carries the moment as one of the numbers in a piece's
        address, and it is simply read from there.

        The position is the half that has to be worked out, and it is worked out
        differently for each picture, always from production geometry.

        A position's own image says whose it is in its address, and that is the
        end of it.

        The seamless run-wide picture holds every position in one image, so the
        position is found from the ground the piece covers, using
        :func:`zmart_live.coarse.contributors_to` — the same production function
        the publisher uses when deciding which pieces a commit has to rebuild.

        The picture that keeps every overlapping pixel needs **both** the stop on
        its tile slider and the ground the piece covers. This is the part that is
        easy to get wrong, and it is worth understanding rather than copying. The
        stops are shared out deliberately, like the squares of a chessboard, so
        that tiles too far apart to overlap sit on the same stop and the slider
        stays short on a run of thousands of positions. A stop therefore names a
        *set* of scattered tiles, not one tile. In a row of three, the first and
        the third tile share a stop; reading the stop alone would call the third
        tile's pixels the first tile's, and would hand them over the moment the
        first tile was committed. Asking which of the tiles at that stop actually
        photographed the ground this piece covers gives one answer, because the
        publisher refuses to write the picture at all unless tiles sharing a stop
        share no specimen.
        """
        piece = _the_piece_this_address_asks_for(inside_the_run)
        if piece is None:
            return ("describe", None)

        if inside_the_run.startswith(f"{POSITIONS}/"):
            # A position's own image is addressed as (moment, colour, plane, row,
            # column), and the folder above it already says whose it is.
            name = inside_the_run.split("/")[1].removesuffix(".ome.zarr")
            if name in self.names:
                return ("gate", Wrote(name, piece[0]))
            return ("refuse", f"no position of this run is called '{name}'")

        if inside_the_run.startswith(f"{SEAMLESS}/"):
            # A piece of the seamless picture is addressed as (moment, colour,
            # plane, row, column); only the last two say where on the specimen it
            # is.
            showing = contributors_to(
                self.profile,
                self._the_piece_of_ground(piece[-2:]),
                self.publisher.layout.positions,
            )
            if len(showing) == 1:
                return ("gate", Wrote(showing[0].position_id, piece[0]))
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
            # A piece of this picture is addressed as (stop on the tile slider,
            # moment, colour, plane, row, column).
            stop, moment = piece[0], piece[1]
            here = self._tiles_at_that_stop_covering(stop, piece[-2:])
            if len(here) == 1:
                return ("gate", Wrote(here[0].position_id, moment))
            if not here:
                return (
                    "refuse",
                    f"no tile sitting at stop {stop} on the tile slider "
                    "photographed that ground",
                )
            # As above, this is checked rather than assumed. The publisher refuses
            # to write this picture when two tiles sharing a stop share specimen,
            # so reaching here would mean the geometry had changed underneath us,
            # and there would be no honest answer to give. See
            # :func:`_the_gate_can_answer_for_every_raw_piece`.
            return (
                "refuse",
                f"stop {stop} holds "
                + ", ".join(p.position_id for p in here)
                + " over that same ground, so no answer for it would be honest",
            )

        # Somewhere new. The publisher may have grown another picture since this
        # was written, and a picture nobody has taught this server to read is a
        # picture it cannot promise anything about.
        return (
            "refuse",
            "this server does not know which position that piece belongs to, and "
            "will not hand over pixels it cannot account for",
        )

    def _the_piece_of_ground(self, index: tuple[int, ...]) -> CoarseChunk:
        """The stored piece at this row and column of a run-wide picture.

        Both run-wide pictures are written at full resolution with the storage
        plan's own piece size, so one description serves for both.
        """
        return CoarseChunk(level=0, index=tuple(index), axes=("y", "x"))

    def _tiles_at_that_stop_covering(self, stop: int, index: tuple[int, ...]):
        """Which tiles sit at this stop of the tile slider and cover this ground.

        The picture that keeps every overlapping pixel holds each tile's whole
        recorded frame — overlaps and all — which is the ground the layout calls
        the position's analysis input. So a tile is looked for whose whole frame,
        placed where the layout puts it in the run, reaches into the piece asked
        for.

        For a run written by this publisher the answer is always none or one, and
        a check before the server starts refuses to run if that is ever untrue.
        """
        ground = self._the_piece_of_ground(index).covers(
            self.profile, self.profile.level(0).inner_chunk
        )
        return [
            placement
            for placement in self.publisher.layout.positions
            if self.publisher.tile_stop_of(placement.position_id) == stop
            and placement.analysis_input_roi.shifted(placement.origin).overlaps(ground)
        ]


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
    def steps_taken_by(method) -> list[str]:
        """The things a method asks of itself, in the order it asks them.

        A step whose name begins with an underscore is one of the publisher's own
        private helpers rather than a step in its own right, so this reads that
        helper too and puts its steps in place of the call. Without that, a
        refactor which merely moves the sequence into a helper would leave this
        check reading two names and believing the run had changed shape when it
        had not -- and, worse, a refactor which moved it somewhere this check
        could not see would let the test go on measuring a sequence nobody runs.
        """
        source = textwrap.dedent(inspect.getsource(method))
        asked = [
            (node.lineno, node.func.attr)
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ]
        flattened: list[str] = []
        for _, name in sorted(asked):
            deeper = getattr(LivePublisher, name, None)
            if name.startswith("_") and callable(deeper):
                flattened.extend(steps_taken_by(deeper))
            else:
                flattened.append(name)
        return flattened

    found = tuple(steps_taken_by(LivePublisher.write_and_publish))
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


def _the_gate_can_answer_for_every_raw_piece(run: ProductionRun) -> None:
    """The same question, asked of the picture that keeps every overlapping pixel.

    That picture gives each tile a stop on a slider, and the stops are shared
    between tiles too far apart to overlap. Sharing is what keeps the slider short
    on a real run, and it is also what makes this check worth doing: for the gate
    to be honest, no single stored piece may hold parts of two different tiles
    that happen to sit at the same stop. The publisher already refuses to write
    the picture when two tiles at one stop share specimen, and this asks the
    slightly stronger question the gate actually depends on — that they do not
    even share a stored piece, which they could in principle do by sitting a few
    pixels either side of one of its edges.

    With the geometry this file chooses they do not come close: the tiles at one
    stop are 2048 pixels apart and the stored pieces are 128 pixels across.
    Checking anyway costs a fraction of a second, and the alternative is a server
    that serves one tile's pixels under another tile's name.
    """
    across = run.profile.level(0).inner_chunk
    height, width = run.publisher._mosaic_extent()
    trouble = []
    for stop in range(run.publisher.tile_stop_count):
        for row in range(-(-height // across["y"])):
            for column in range(-(-width // across["x"])):
                here = run._tiles_at_that_stop_covering(stop, (row, column))
                if len(here) > 1:
                    trouble.append(
                        f"at stop {stop}, the piece at row {row}, column {column} "
                        f"holds {', '.join(p.position_id for p in here)}"
                    )
    if trouble:
        raise SystemExit(
            "This run cannot be gated honestly, so it is not worth serving. Some "
            f"pieces of the picture at {run.folder / RAW_OVERLAP} hold parts of two "
            "tiles that share a stop on the tile slider, which means neither "
            "serving nor refusing them would tell the truth: "
            + "; ".join(trouble)
            + ". Change the frame size or the positions so that tiles sharing a "
            "stop are further apart than one stored piece."
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
            query = parse_qs(asked.query)
            wanted = query.get("position", [""])[0]
            # A request that says nothing about the moment means the first one,
            # which is the only moment most of these runs have.
            moment = int(query.get("moment", ["0"])[0])
            try:
                if asked.path == "/control/publish":
                    run.publish_the_whole_position(wanted, moment)
                elif asked.path == "/control/write-everything-except-the-commit":
                    run.write_everything_except_the_commit(wanted, moment)
                elif asked.path == "/control/commit":
                    run.commit_only(wanted, moment)
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
                    # The honest answer for a moment nobody has published is the
                    # same as for a position nobody has imaged: there is nothing
                    # here. A reader is meant to take that as empty ground and
                    # carry on drawing what it does have, which is the other half
                    # of what this test checks.
                    self._send(
                        404, f"{about} has not been committed".encode(), "text/plain"
                    )
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


def serve(
    folder: Path,
    port: int,
    *,
    tiles_in_a_row: int = TILES_IN_A_ROW,
    moments: int = MOMENTS,
) -> tuple[ThreadingHTTPServer, ProductionRun]:
    """Start the run and the server, and hand both back without blocking."""
    _this_file_still_mirrors_the_production_sequence()
    run = ProductionRun(folder, tiles_in_a_row=tiles_in_a_row, moments=moments)
    _the_gate_can_answer_for_every_piece(run)
    _the_gate_can_answer_for_every_raw_piece(run)
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
        "--tiles-in-a-row",
        type=int,
        default=TILES_IN_A_ROW,
        help="how many neighbouring positions the mosaic has, left to right. "
        "Three is the smallest row in which two tiles share a stop on the raw "
        "view's tile slider, which is the case the gate is easiest to get wrong.",
    )
    parser.add_argument(
        "--moments",
        type=int,
        default=MOMENTS,
        help="how many moments in time each position holds. More than one is "
        "needed to ask whether a later, uncommitted moment of an already "
        "published position stays off the screen.",
    )
    parser.add_argument(
        "--publish-the-first-position",
        action="store_true",
        help="write and publish position A before serving, which is where the "
        "browser test's three-step sequence begins",
    )
    chosen = parser.parse_args()

    if chosen.folder.exists():
        shutil.rmtree(chosen.folder)
    server, run = serve(
        chosen.folder,
        chosen.port,
        tiles_in_a_row=chosen.tiles_in_a_row,
        moments=chosen.moments,
    )
    if chosen.publish_the_first_position:
        run.publish_the_whole_position("A")
    address = f"http://127.0.0.1:{chosen.port}"
    print(
        f"the run is on {address}: {chosen.tiles_in_a_row} tile(s) in a row, "
        f"{chosen.moments} moment(s) each",
        flush=True,
    )
    print(
        f"the seamless picture:   {address}/page/index.html"
        f"?store={address}/{SEAMLESS}/0/%7Czarr3:",
        flush=True,
    )
    print(
        f"every overlapping pixel: {address}/page/index.html"
        f"?store={address}/{RAW_OVERLAP}/0/%7Czarr3:",
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
