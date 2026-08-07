"""Does handing the viewer one source per position scale?

A run of many positions can be shown to the drawing engine in two quite different
ways, and this measures both of them on **the very same files**.

**Arrangement A — one store.** The run's "view" is a single OME-Zarr image that
holds no full-size picture of its own: every piece of it is a piece of one
position's file, handed over unchanged. The engine is given **one** source. The
price is that a position can only be placed on the view's grid of pieces, so a
stitcher's measured drift of a voxel and a half cannot be expressed.

**Arrangement B — one store per position.** Each position is an ordinary
OME-Zarr image carrying its own position on the stage, and all of them are handed
to the engine as **N** separate sources. Placement is then free — any fractional
offset the stitcher measured can simply be written into the store — which is why
this arrangement is worth wanting. The doubt about it is cost: the engine builds a
whole drawing layer for every source it is given.

What is being asked is where B stops being usable.

Which engine draws, and the difference between a layer and a source
-------------------------------------------------------------------

**Every number here is drawn by neuroglancer**, through the option
``viz_studio/options/neuroglancer-under``, and the page is asked to confirm that
rather than trusted about it: each reading records what the page loaded and how
many of the elements in the box carry neuroglancer's own class names. That check
is there because the harness is built with three options and two different
engines behind them, and a table that did not say which one drew it would answer
a different question from the one it appeared to answer.

One distinction runs through everything below and is easy to miss. **A source and
a drawing layer are not the same thing.** The option used here builds one layer
per acquisition it is handed, so arrangement B is N layers — which is the
arrangement the question as it was put assumes. The viewer this project actually
ships does something else: ``viz_studio/backend/server.py`` merges every position
of one acquisition and channel into a single row, and ``scene.js`` hands the
engine **one** layer that reads from N places. The server says plainly why:
"asking the engine for one layer with two hundred sources is far less work than
two hundred layers, each needing its own setup and its own shader compiled."

Both are measured, so the difference is a number rather than a claim. The third
arrangement is off unless ``--also-grouped`` is given; see
:func:`the_two_arrangements` for how it is built and why it comes to two layers
rather than one.

Reading the numbers
-------------------

Two habits are borrowed from the rest of this harness and both matter.

**Every number about the picture comes from a photograph of the screen.** The
clock for "how long until something is on screen" is stopped by a photograph in
which specimen can be seen, never by asking the engine whether it thinks it has
finished. **A gesture is recorded rather than sampled**: the panning frames come
from a live recording of what the browser actually composited, so nothing here
made the browser draw a frame it was not going to draw anyway.

**The two arrangements are made to show the same amount of specimen.** This is
the trap that spoiled an earlier comparison of the same question: if one
arrangement fills half the window and the other fills nearly all of it, part of
the difference in timing is simply more picture rather than more cost. Here both
arrangements are put at the same centre and the same magnification over the same
raster of positions, so the same ground is on screen either way — and the share of
the window that is actually lit is measured from a photograph and reported beside
every timing, so a reader can check that rather than take it on trust.

Two small liberties are taken with the harness, and both are written down here
rather than left to be discovered:

- **The view's pointed-at pieces are made real files before the measurement.**
  A view holds no picture; the viewer's own server answers a request for one of
  its pieces by handing over the position file that already holds those exact
  bytes. The little server this harness uses has no such step, so before
  measuring, each pointed-at piece is given a hard link to the file it points at.
  A hard link is a second name for one file on disk — nothing is copied. What
  reaches the browser is byte for byte what the real server would have sent, and
  the number of requests is unchanged; only a dictionary lookup in Python is
  replaced by the operating system finding a file.

- **The description files are counted too.** The harness's server normally
  leaves ``.zattrs`` and friends out of its record, because on a real share they
  would be read once and kept. For this question they are most of the story — N
  sources means N descriptions before a pixel can be drawn — so they are counted
  here, and reported separately from the pieces of picture so that either number
  can be read on its own. Nothing else about how they are served changes: the
  same bytes go out, and the small repair the server makes to the way a unit is
  spelled still happens, because the stores this run writes already spell it the
  way the format asks and there is nothing for the repair to do.

The second question: overlapping sources
----------------------------------------

There is a second thing this file answers, with ``--overlap``, and it may matter
more than the ladder. Positions that **overlap** — which is the ordinary way a
stitcher lays a run out, and the whole reason for wanting arrangement B — have
been seen on another machine to come out as a patchwork of strips at what looked
like different magnifications, where the same positions butted up against one
another came out clean. The measurement photographs the same view twice in each
condition, once the moment anything is on screen and once after everything has
come to rest, so that a patchwork which is only the engine still refining can be
told from one that is really there. The comment above
:func:`positions_that_overlap` sets out what each outcome would mean.

**This question was set aside, not settled.** The project chose the one-store
arrangement — a single view whose pieces are served from the positions' own files
and handed to the engine as one source — so the arrangement in which the
patchwork appears is no longer one anybody plans to ship. The ``--overlap``
measurement still runs and still reports honestly what it photographs, but no
cause for the patchwork was ever established, and nothing here should be read as
having found one. The comment above :func:`positions_that_overlap` keeps the
record of what was ruled out along the way, so that somebody picking this up
later does not spend their time where four people have already spent theirs.

Run it with::

    python viz_studio/options/measure/many_sources.py --rungs 50,100,400,1000
    python viz_studio/options/measure/many_sources.py --overlap --rungs 36,100

after building the page it drives::

    npm --prefix viz_studio/options/harness run build
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_VIZ = _HERE.parents[1]
for extra in (str(_HERE), str(_VIZ / "backend"), str(_VIZ.parent)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import numpy as np  # noqa: E402

import acquisitions  # noqa: E402
import data_server  # noqa: E402
import drive  # noqa: E402
import linking  # noqa: E402
from drive import Recording, pan_steadily  # noqa: E402

from zmart_storage import Channel  # noqa: E402
from zmart_storage.positions import POSITIONS_FOLDER, start_a_run  # noqa: E402

# ---------------------------------------------------------------------------
# The run every rung is built from
# ---------------------------------------------------------------------------

# How large one position is, in voxels. Two hundred and fifty-six is a compromise
# rather than a real field of view: large enough that a handful of positions fill
# the window at a natural magnification, small enough that a thousand of them can
# be written in a few minutes.
POSITION_VOXELS = 256

# How large a piece of the picture is, in voxels. This is the smallest thing that
# can be asked for, so it is what decides how many separate requests a redraw
# costs. Sixty-four keeps a screenful in the low hundreds of requests, which is
# the range the earlier figures for this question were taken in.
PIECE = 64

# One micrometre to a voxel, so that a number of voxels and a number of
# micrometres are the same number and the view settings below can be read without
# arithmetic. Nothing depends on it: every placement still goes through the voxel
# size each store records about itself.
VOXEL_UM = 1.0

# How the positions are laid out at each rung — across by down. Chosen so that
# every rung is an exact rectangle, because a half-finished last row would mean
# the two arrangements were photographed over slightly different ground.
RASTERS = {
    36: (6, 6),
    50: (10, 5),
    100: (10, 10),
    400: (20, 20),
    1000: (40, 25),
}

# The magnification every measurement is taken at, in micrometres per screen
# pixel. One micrometre to the pixel is exactly the full-size copy of the
# picture, so both arrangements draw from the same copy and ask for the same
# pieces of it — which is what makes the two request counts comparable at all.
ZOOM_UM_PER_PIXEL = 1.0

# Where the view is put, the same for every arrangement and every rung.
#
# Fixed rather than fitted to the run, because what is being asked is what a
# given number of stores costs — not what a larger picture costs to show. A view
# that widened with the run would change how much there is to draw at the same
# time as changing how many stores there are, and the two could not be told
# apart afterwards. The centre sits inside the first tile, which every rung has.
PINNED_VIEW = {"centre": {"x": 256.0, "y": 256.0}, "zoom": ZOOM_UM_PER_PIXEL}


def _a_position(seed: int) -> np.ndarray:
    """One position's picture: bright, with a gentle texture across it.

    The texture is there so that "is there specimen on screen" can be answered by
    looking rather than assumed. A perfectly flat field would pass a check that
    only asks whether anything is lit while telling a reader nothing about
    whether the picture is really the specimen.
    """
    across = np.linspace(0.0, 1.0, POSITION_VOXELS, dtype=np.float32)
    down = np.linspace(0.0, 1.0, POSITION_VOXELS, dtype=np.float32)[:, None]
    values = 3600.0 - 600.0 * (across + down) * 0.5 + 60.0 * ((seed % 5) / 4.0)
    return values.astype(np.uint16)[None, :, :]


def write_a_run(folder: Path, positions: int) -> tuple[Path, list[Path]]:
    """Image a raster of positions and hand back both arrangements.

    Returns the view — the single image of arrangement A — and the list of the
    positions' own images, which is arrangement B. They are two ways of looking at
    one set of files rather than two copies of anything.
    """
    across, down = RASTERS[positions]
    room = (1, down * POSITION_VOXELS, across * POSITION_VOXELS)
    folder.mkdir(parents=True, exist_ok=True)
    with start_a_run(
        folder,
        name="overview",
        room=room,
        tile_shape=(1, POSITION_VOXELS, POSITION_VOXELS),
        voxel_size_um=(VOXEL_UM, VOXEL_UM, VOXEL_UM),
        origin_um=(0.0, 0.0, 0.0),
        channels=[Channel("probe", color="FFFFFF", window=(0, 4095))],
        piece=PIECE,
        # Version 0.4 rather than 0.5, so that every store here describes itself
        # in a small `.zattrs` beside the picture. That is what the address handed
        # to the engine asks for — it ends `|zarr2:` — and it is the arrangement
        # every other acquisition in this folder is written in, so a number
        # measured here can be set beside one measured there.
        ome_zarr_version="0.4",
    ) as run:
        for index in range(positions):
            row, column = divmod(index, across)
            run.write(
                _a_position(index),
                at=(0, row * POSITION_VOXELS, column * POSITION_VOXELS),
            )
        view = run.path
    where = view / POSITIONS_FOLDER
    stored = sorted(one for one in where.iterdir() if one.name.endswith(".ome.zarr"))
    _make_the_pointed_at_pieces_real(view, folder, positions)
    return view, stored


def _make_the_pointed_at_pieces_real(view: Path, opened: Path, positions: int) -> int:
    """Give every piece the view points at a second name on disk.

    See this module's own notes: the view keeps no picture, and the viewer's real
    server resolves a request for one of its pieces to the position file holding
    those bytes. The little server here only knows how to find files, so each
    such piece is given a hard link — a second name for the one file, with nothing
    copied — and the bytes the browser receives are unchanged.

    Returns how many pieces were linked, so that a run which somehow produced no
    pointers is noticed here rather than as a blank window later.
    """
    across, down = RASTERS[positions]
    # How this store spells the name of a piece. Zarr allows either a single name
    # with the numbers joined by dots or a folder per number, and the two are not
    # interchangeable — a name in the wrong spelling is simply a file that exists
    # nowhere. It is read out of the store rather than assumed, so that a change
    # of format is noticed here rather than as a blank window later.
    described = json.loads((view / "0" / ".zarray").read_text(encoding="utf-8"))
    separator = described.get("dimension_separator", ".")
    made = 0
    for level in range(4):
        pieces = (POSITION_VOXELS // PIECE) // (2**level)
        if pieces < 1:
            break
        for row in range(down * pieces):
            for column in range(across * pieces):
                # The copy a piece belongs to is always a folder of its own;
                # only the five numbers within it are spelled either way.
                inside = f"{level}/" + separator.join(
                    ["0", "0", "0", str(row), str(column)]
                )
                found = linking.the_bytes_behind(view, inside)
                if found is None:
                    continue
                real = opened / found.path
                if not real.is_file():
                    continue
                here = view / inside
                if here.exists():
                    continue
                here.parent.mkdir(parents=True, exist_ok=True)
                here.hardlink_to(real)
                made += 1
    if made == 0:
        raise RuntimeError(
            "the view points at nothing, so arrangement A would have shown an "
            "empty picture and the comparison would have been meaningless"
        )
    return made


# ---------------------------------------------------------------------------
# What is on screen
# ---------------------------------------------------------------------------


def lit_share(picture) -> float:
    """What share of the window is showing specimen, from the photograph itself.

    This is the number that makes the comparison checkable. Both arrangements are
    put over the same ground at the same magnification, so both should come back
    at very nearly the same share — and where they do not, the timings beside them
    have to be read with that difference in mind.
    """
    picture = np.asarray(picture).astype(int)
    return round(float((picture.max(axis=2) > 60).mean()), 4)


# ---------------------------------------------------------------------------
# Driving one arrangement
# ---------------------------------------------------------------------------

# How long to wait for the first specimen to reach the screen before calling it a
# failure. Generous, because the whole question is where an arrangement becomes
# unusable, and an arrangement that takes two minutes has told us something real
# rather than merely run out of patience.
LONGEST_WAIT_S = 240.0

# How long the traffic has to stay quiet before a screenful is called finished.
QUIET_S = 1.5


def _the_page_can_open_a_viewer(harness) -> None:
    """Teach the open page how to open a viewer on a list of acquisitions.

    The harness page opens one acquisition, or two, from words in its address; it
    has no way to be told about a thousand. Rather than change the page — which
    every other measurement in this folder depends on being unchanged — the
    handles the page already publishes are used from here: it hands out the
    option's own ``openViewer``, and the box the viewer draws in is an ordinary
    element on the page. So this asks the page to do exactly what it does when it
    opens itself, with a longer list.

    Nothing about the option is assumed and nothing is reached into: the same two
    calls would work for any of the three options in this folder.
    """
    harness.page.evaluate(
        """() => {
      const box = document.getElementById("viewer");
      window.manySources = {
        started: null, opened: null, failed: null, frames: 0,
        // Opening is kicked off rather than waited for, so that the program
        // taking the photographs can start photographing straight away. What is
        // being timed is how long until specimen is on the screen, and waiting
        // here for the engine to say it had finished would be timing the engine's
        // own opinion of itself instead.
        open: (acquisitions, view) => {
          window.manySources.started = performance.now();
          window.manySources.opened = null;
          window.manySources.failed = null;
          window.manySources.frames = 0;
          try { window.harness.viewer.destroy(); } catch (why) { /* nothing open */ }
          window.harness.loadTheOption()
            .then(({ openViewer }) => openViewer(box, {
              acquisitions,
              coverage: null,
              background: "#101014",
              boundToCoverage: false,
              onViewChanged: (settled) => { window.harness.viewNow = settled; },
            }))
            .then((viewer) => {
              window.harness.viewer = viewer;
              // Nothing of the operator's own drawing, in either slot. The
              // question here is what the picture costs, and a carrier and a
              // rectangle per position would put the page's drawing into the
              // answer.
              viewer.drawUnder(null);
              viewer.drawOver(() => { window.manySources.frames += 1; });
              viewer.setView(view);
              window.manySources.opened = performance.now();
            })
            .catch((why) => {
              window.manySources.failed = String(why && why.stack ? why.stack : why);
            });
        },
      };
    }"""
    )


def which_engine_is_drawing(harness) -> dict:
    """Say, from the page itself, which drawing engine produced these numbers.

    This is worth a measurement of its own rather than a note in a docstring. The
    harness is built with three options and two quite different engines behind
    them — neuroglancer for one, deck.gl and Viv for the other two — and a table of
    numbers that did not say which one drew them would answer a different question
    from the one it appeared to answer. So the page is asked what it loaded, and
    the box is looked in for the marks each engine leaves: neuroglancer builds a
    small tree of elements whose class names all begin with its own name, while a
    deck.gl canvas does not.
    """
    return harness.page.evaluate(
        """() => {
      const box = document.getElementById("viewer");
      const all = Array.from(box.querySelectorAll("*"));
      const named = (word) => all.filter(
        (one) => typeof one.className === "string" && one.className.includes(word),
      ).length;
      return {
        "the option the page loaded": window.harness.option,
        "elements whose class names say neuroglancer": named("neuroglancer"),
        "elements whose class names say deck": named("deck"),
        "canvases in the box": Array.from(box.querySelectorAll("canvas")).map(
          (one) => one.className || "(no class)",
        ),
        "what the option says of drawing beneath": window.harness.drawsUnderBecause,
      };
    }"""
    )


def _how_the_ledger_reads(entries) -> dict:
    """Split what the server answered into descriptions and pieces of picture.

    Both halves matter and they answer different questions. The descriptions are
    what an arrangement costs merely for existing — one store's worth of them per
    source — and the pieces of picture are what the window on screen costs. An
    arrangement can be perfectly cheap in one and ruinous in the other, which is
    exactly what is being looked for here.
    """
    describing = [
        one for one in entries
        if Path(one["path"]).name in (".zattrs", ".zarray", ".zgroup", "zarr.json")
    ]
    picture = [one for one in entries if one not in describing]
    return {
        "requests in all": len(entries),
        "of which described a store": len(describing),
        "of which were pieces of picture": len(picture),
        "pieces that held picture": sum(1 for one in picture if one["found"]),
        "pieces that were empty ground": sum(1 for one in picture if not one["found"]),
        "seconds the traffic lasted": (
            round(max(one["finished"] for one in entries)
                  - min(one["started"] for one in entries), 2)
            if entries else 0.0
        ),
    }


def _wait_for_specimen(harness, at_least: float) -> tuple[float | None, float]:
    """Photograph in a loop until specimen appears, and say when it did.

    The clock is stopped by a photograph rather than by anything the page says
    about itself, and the loop is made of real calls into the browser, so the
    moment recorded is a moment that really happened. Photographing costs a
    fraction of a second each time, so the answer is an upper bound rather than a
    best case, and it is reported as one.
    """
    started = time.perf_counter()
    share = 0.0
    while time.perf_counter() - started < LONGEST_WAIT_S:
        failed = harness.believes("window.manySources.failed")
        if failed:
            raise RuntimeError(failed)
        share = lit_share(harness.photograph())
        if share >= at_least:
            return time.perf_counter() - started, share
        time.sleep(0.05)
    return None, share


def _panning(harness, name: str) -> dict:
    """One steady drag, read out of a live recording of what reached the screen.

    Frame times are the gaps between the frames the browser really composited
    during the gesture. Asking for a photograph would have made the browser
    produce a frame it was not going to produce, so what is recorded here is what
    an operator's eye would have been given.
    """
    with Recording(harness.page) as recording:
        started = time.perf_counter()
        pan_steadily(harness.page, steps=60, step=4)
        elapsed = time.perf_counter() - started
    frames = list(recording.pictures())
    changed_at = []
    last = None
    for when, picture in frames:
        if last is None or not np.array_equal(picture, last):
            changed_at.append(when)
        last = picture
    gaps = [
        round((later - earlier) * 1000, 1)
        for earlier, later in zip(changed_at, changed_at[1:])
    ]
    found = {
        "seconds the drag took": round(elapsed, 2),
        "frames the screen actually changed": len(changed_at),
        "frames a second": round(len(changed_at) / elapsed, 1) if elapsed else None,
        "middle frame (ms)": round(statistics.median(gaps), 1) if gaps else None,
        "worst frame (ms)": max(gaps) if gaps else None,
        "every frame (ms)": gaps,
    }
    if frames:
        found["share of the window lit, last frame of the drag"] = lit_share(
            frames[-1][1]
        )
        harness.save_frame(frames[-1][1], name)
    return found


def measure_one(harness, *, acquisitions: list[dict], view: dict,
                photograph: str) -> dict:
    """Open one arrangement, time it, and photograph what it drew."""
    _the_page_can_open_a_viewer(harness)
    harness.clear_ledger()
    harness.ledger.clear()
    started = time.perf_counter()
    harness.page.evaluate(
        "([acquisitions, view]) => window.manySources.open(acquisitions, view)",
        [acquisitions, view],
    )
    found: dict = {"sources handed to the engine": len(acquisitions)}
    try:
        # A tenth of the window is a long way past anything a stray pixel could
        # produce and a long way short of a full screenful, so it marks the moment
        # the specimen genuinely began to appear.
        first, share = _wait_for_specimen(harness, 0.10)
    except RuntimeError as why:
        found["it failed outright"] = str(why)[:2000]
        return found
    found["seconds to the first specimen on screen"] = (
        round(first, 2) if first is not None else None
    )
    found["it drew at all"] = first is not None
    # Put the view where it is told rather than where it happened to land.
    #
    # The engine centres itself once, from whichever store answers first, and
    # never does so again. When every store says a different place — which is the
    # whole point of the arrangement being compared — where the view ends up
    # depends on which answer arrived first, and that changes from one run to the
    # next. Two arrangements could then be timed while looking at different
    # ground, and a run could differ from itself for no reason worth recording.
    #
    # So the view is set explicitly, to the same place and the same magnification
    # every time, and what it was set to is written down beside the readings.
    found["where the view was put"] = harness.page.evaluate(
        """(asked) => {
      const shown = window.harness.viewer;
      if (!shown || typeof shown.setView !== "function") return "could not be set";
      shown.setView(asked);
      return shown.getView ? shown.getView() : "set, but cannot be read back";
    }""",
        PINNED_VIEW,
    )
    if first is None:
        found["share of the window lit when it gave up"] = share
        found["what the server answered while it tried"] = _how_the_ledger_reads(
            list(harness.ledger.entries)
        )
        return found

    # Let the screenful finish: wait until the server has been quiet for a while.
    seen, quiet_since = -1, time.perf_counter()
    while time.perf_counter() - started < LONGEST_WAIT_S:
        now = len(harness.ledger.entries)
        if now != seen:
            seen, quiet_since = now, time.perf_counter()
        elif time.perf_counter() - quiet_since > QUIET_S:
            break
        time.sleep(0.1)
    harness.settle(tries=40)
    settled = harness.photograph()
    found["seconds to a finished screenful"] = round(time.perf_counter() - started, 2)
    found["share of the window lit"] = lit_share(settled)
    found["one screenful of requests"] = _how_the_ledger_reads(
        list(harness.ledger.entries)
    )
    found["the engine said it had opened after (s)"] = _what_the_page_says(harness)
    found["which engine drew this"] = which_engine_is_drawing(harness)
    found["photograph"] = harness.save_frame(settled, photograph)
    # The drag is made three times over rather than once. On a machine with no
    # graphics card a single reading of a drawing rate has been seen to vary by a
    # factor of two on an unchanged build — another program waking up is enough —
    # so a single number would invite a comparison it cannot support. The middle
    # reading is reported with the lowest and highest beside it, and two cells
    # whose ranges overlap have not been shown to differ.
    drags = []
    for time_round in range(3):
        harness.page.evaluate(
            "(view) => window.harness.viewer.setView(view)", view
        )
        harness.settle(tries=25)
        drags.append(_panning(harness, f"{photograph}-panning-{time_round}"))
    found["panning"] = _the_middle_drag(drags)
    return found


def _the_middle_drag(drags: list[dict]) -> dict:
    """Three drags summarised as one, with the spread kept beside the middle.

    Sorted on the middle frame time, because that is the number a reader will
    compare. The lowest and highest are kept so that a difference which is really
    just this machine's noise can be seen for what it is.
    """
    usable = [one for one in drags if one.get("middle frame (ms)") is not None]
    if not usable:
        return {"why": "no frame reached the screen during any of the drags",
                "every drag": drags}
    in_order = sorted(usable, key=lambda one: one["middle frame (ms)"])
    middle = in_order[len(in_order) // 2]
    return {
        "middle frame (ms)": middle["middle frame (ms)"],
        "worst frame (ms)": max(one["worst frame (ms)"] for one in usable),
        "frames a second": middle["frames a second"],
        "share of the window lit while panning": middle.get(
            "share of the window lit, last frame of the drag"
        ),
        "middle frame, lowest and highest of three drags (ms)": [
            in_order[0]["middle frame (ms)"], in_order[-1]["middle frame (ms)"]
        ],
        "every drag": [
            {key: one[key] for key in one if key != "every frame (ms)"}
            for one in drags
        ],
    }


def _what_the_page_says(harness) -> float | None:
    """How long the engine took to say it had opened, in seconds.

    This is the one number here that is the page's own account of itself rather
    than a reading of the screen, and it is kept for one narrow purpose: it tells
    "the sources were all described but nothing had been drawn yet" apart from
    "the engine was still working out what it had been given". It is never the
    answer to how long an operator waited — the photograph above is.
    """
    numbers = harness.believes(
        "({s: window.manySources.started, o: window.manySources.opened})"
    )
    if not numbers or numbers.get("o") is None:
        return None
    return round((numbers["o"] - numbers["s"]) / 1000.0, 2)


# ---------------------------------------------------------------------------
# The whole thing
# ---------------------------------------------------------------------------


def the_two_arrangements(data_dir: Path, address: str, view: Path,
                         positions: list[Path], rung: int,
                         also_grouped: bool = False) -> dict:
    """The acquisition lists for arrangement A and arrangement B.

    Both are addresses into the same files. The channels are stated by the page in
    both cases and stated identically, so that neither arrangement is charged for
    reading a description the other did not have to read.

    ``also_grouped`` adds a third arrangement that is worth understanding, because
    it is the one the viewer this project actually ships uses and it is **not**
    the same as B. There are two quite different ways to hand a drawing engine N
    stores. Either each store becomes a drawing layer of its own — which is what
    arrangement B does here, and what the question as it was put assumes — or all
    of them become **one** layer that reads from N places, which is what
    ``viz_studio/backend/server.py`` builds and what ``scene.js`` passes on. That
    file says in as many words that "asking the engine for one layer with two
    hundred sources is far less work than two hundred layers, each needing its own
    setup and its own shader compiled", so the difference is expected to be large
    and it deserves to be measured rather than argued about.

    It is obtained by handing the option a *list* of addresses where its interface
    says one, which it passes straight through to the engine. The engine's own
    layer description takes either, so what is built is an ordinary layer with
    many sources — exactly what the shipping viewer builds. The first store is
    given on its own because one step inside the option reads the first
    acquisition's address as text in order to find where the specimen is, so this
    arrangement is two layers rather than one: one holding a single position and
    one holding all the rest.
    """
    said = {
        "channels": [
            {"name": "probe", "colour": [1, 1, 1], "window": {"low": 0, "high": 4095}}
        ]
    }

    def address_of(store: Path) -> str:
        return f"{address}/data/{store.relative_to(data_dir).as_posix()}/|zarr2:"

    arrangements = {
        "A — one store": [
            {"url": address_of(view), "name": "overview", **said}
        ],
        f"B — {len(positions)} stores, a layer each": [
            {"url": address_of(store), "name": store.name[: -len(".ome.zarr")], **said}
            for store in positions
        ],
    }
    if also_grouped and len(positions) > 1:
        arrangements[f"B grouped — {len(positions)} stores, two layers"] = [
            {"url": address_of(positions[0]), "name": "first position", **said},
            {"url": [address_of(store) for store in positions[1:]],
             "name": "the rest", **said},
        ]
    return arrangements


def the_view_settings(rung: int) -> dict:
    """Where to look and how closely, in micrometres — the same for both.

    The middle of the imaged raster, at exactly one micrometre to the screen
    pixel. At that magnification the window holds about three and a half positions
    across, which at every rung is comfortably inside the raster — so the window is
    full of specimen either way and the share of it that is lit can be compared
    honestly.
    """
    across, down = RASTERS[rung]
    return {
        "centre": {
            "x": across * POSITION_VOXELS * VOXEL_UM / 2,
            "y": down * POSITION_VOXELS * VOXEL_UM / 2,
        },
        "zoom": ZOOM_UM_PER_PIXEL,
    }


# ---------------------------------------------------------------------------
# Do overlapping sources come out as a patchwork?
# ---------------------------------------------------------------------------
#
# A separate question from the ladder, and possibly a more important one. On
# another machine, a hundred positions shown as separate sources with a small
# *negative* step — so that neighbouring tiles overlap by about a tenth — came out
# as a patchwork of strips at what looked like different magnifications, while the
# same hundred positions butted up against one another came out as a clean, sharp
# grid. Two explanations were tried there and neither held: it made no difference
# which of the two places in the description the position was written in, and no
# difference whether the step was a whole number of voxels or a fraction. What is
# left is the overlap itself.
#
# The explanation worth testing is that this is the engine *refining*. It draws a
# coarse copy of a source first and replaces it with a finer one as the pieces
# arrive, and with many sources that refinement is staggered — so at any one
# instant different sources are showing different copies. Where nothing overlaps,
# each part of the window is covered by exactly one source and a difference
# between sources cannot be seen. Where they overlap, the same ground is covered
# twice at two different copies, and a tile drawn from the half-size copy sitting
# beside its neighbour drawn from the full-size one is exactly what "strips at
# mismatched scales" looks like.
#
# So the window is photographed **twice** in each condition: once the moment
# anything is on screen, and once after everything has come to rest. If the
# patchwork is there in the first and gone in the second, it is refinement and not
# a fault of placement — and it would also mean any timing taken before things
# come to rest is measuring the harness rather than the arrangement. If it is
# still there once everything has settled, overlapping sources really are keeping
# different copies, which would be a structural argument against the arrangement
# quite apart from how fast it draws.
#
# What has already been ruled out, and one warning about method
# --------------------------------------------------------------
#
# Four explanations have been put forward for the patchwork and all four were
# then found not to hold. They are written down here because each of them is the
# obvious first guess, and each one has already cost somebody an afternoon:
#
#   1. **Where the position is written in the description.** It makes no
#      difference whether the offset sits beside the whole set of copies or
#      beside each copy on its own.
#   2. **Offsets that are not a whole number of voxels.** A step of a voxel and a
#      half behaves the same as a step of two voxels.
#   3. **The overlap itself.** Positions that overlap are not enough on their own
#      to produce it.
#   4. **The engine still refining.** The picture does not come right if you
#      simply wait; it was watched settling for a minute and a half and stayed as
#      it was.
#
# The warning matters more than the list. **All four of those conclusions were
# reached by looking at photographs, and all four were wrong.** A screenshot of
# this fault is genuinely ambiguous: an engine that has run out of room for
# picture pieces and an engine that is putting sources in the wrong place produce
# the same blotchy screen and the same share of the window lit, so no amount of
# careful looking can separate them. Anybody returning to this should read the
# numbers out of the engine — how many pieces it is holding, how many it asked
# for and never got, and where it has decided each source belongs — rather than
# judging by eye.
#
# One confound is also still open and is worth stating plainly, because it has
# never been separated: every clean reading happened to be taken close in, where
# the engine draws from the full-size copy of the picture, and every patchwork
# reading happened to be taken further out, where it draws from a smaller copy.
# So "many sources" and "drawing from a smaller copy" have always changed
# together, and nothing yet says which of the two the fault belongs to.

# How far apart the positions are put, as a share of one position's width, in the
# condition where they overlap. Nine tenths means neighbours share a tenth of
# their width, which is the ordinary amount of overlap a stitcher is given.
OVERLAPPING_STEP = 0.9


def positions_that_overlap(positions: list[Path], into: Path, rung: int,
                           step: float = OVERLAPPING_STEP) -> list[Path]:
    """Copy the positions and change only what each of them says about where it is.

    Nothing about the picture is touched — not one voxel — so a difference between
    this and the untouched positions can only be the placement. Each store is
    copied rather than edited in place, so the run these were written from is left
    exactly as it was and can still be measured beside them.
    """
    across, _ = RASTERS[rung]
    apart = POSITION_VOXELS * VOXEL_UM * step
    if into.exists():
        shutil.rmtree(into)
    into.mkdir(parents=True)
    made = []
    for index, store in enumerate(positions):
        row, column = divmod(index, across)
        copied = into / store.name
        shutil.copytree(store, copied)
        described = json.loads((copied / ".zattrs").read_text(encoding="utf-8"))
        multiscale = described["multiscales"][0]
        names = [axis["name"] for axis in multiscale["axes"]]
        corner = {"y": row * apart, "x": column * apart}
        # Every copy of the picture states the same position, in micrometres, so
        # every one of them has to be changed together. A store whose smaller
        # copies still said the old position would be drawn in two places at once
        # depending how far out the operator was, which is a different fault
        # altogether and would muddle the reading.
        for dataset in multiscale["datasets"]:
            for step_in in dataset.get("coordinateTransformations", []):
                if step_in.get("type") != "translation":
                    continue
                step_in["translation"] = [
                    corner.get(name, was)
                    for name, was in zip(names, step_in["translation"], strict=True)
                ]
        (copied / ".zattrs").write_text(json.dumps(described), encoding="utf-8")
        made.append(copied)
    return made


def _which_copies_were_asked_for(entries) -> dict:
    """Which copy of the picture each source has been asked for, and how often.

    This is the second half of the question and it comes from the server rather
    than from the engine. A store keeps its full-size picture and its smaller
    copies in numbered folders, so the number in a request says which copy was
    wanted — and if the patchwork really is sources sitting at different copies,
    the record will show several copies being read at the same moment rather than
    one.

    It is evidence about what was *fetched*, which is not quite the same as what
    was drawn, and it is reported as that.
    """
    copies: dict[str, dict] = {}
    for one in entries:
        path = one["path"]
        if ".ome.zarr/" not in path:
            continue
        store, _, inside = path.partition(".ome.zarr/")
        which = inside.split("/")[0]
        if not which.isdigit():
            continue
        seen = copies.setdefault(which, {"requests": 0, "stores": set()})
        seen["requests"] += 1
        seen["stores"].add(store)
    return {
        f"copy {which}": {
            "pieces asked for": seen["requests"],
            "stores that asked for it": len(seen["stores"]),
        }
        for which, seen in sorted(copies.items())
    }


def _how_blocky(picture) -> dict:
    """Two plain readings of a photograph, to sit beside looking at it.

    Neither of these decides anything — the photographs are saved so that the
    question can be answered by eye, which is what "does it look like a
    patchwork" really means. These are here so that two photographs can be
    compared without squinting. A picture drawn from one copy of the specimen is
    a smooth gradient; one drawn from a copy zoomed out and stretched back up has
    visible steps in it, and steps show up as pixels sitting on a sharp edge.
    """
    grey = np.asarray(picture).astype(int).mean(axis=2)
    across = np.abs(np.diff(grey, axis=1))
    down = np.abs(np.diff(grey, axis=0))
    sharp = float((across > 3).mean() + (down > 3).mean()) / 2
    return {
        "share of neighbouring pixels with a sharp step between them": round(sharp, 5),
        "distinct grey levels in the window": int(len(np.unique(grey.round()))),
    }


def the_overlap_question(harness, *, acquisitions: list[dict], view: dict,
                         name: str) -> dict:
    """Open one condition and photograph it twice: at once, and once at rest."""
    _the_page_can_open_a_viewer(harness)
    harness.clear_ledger()
    harness.ledger.clear()
    started = time.perf_counter()
    harness.page.evaluate(
        "([acquisitions, view]) => window.manySources.open(acquisitions, view)",
        [acquisitions, view],
    )
    found: dict = {"sources handed to the engine": len(acquisitions)}
    try:
        first, share = _wait_for_specimen(harness, 0.10)
    except RuntimeError as why:
        found["it failed outright"] = str(why)[:2000]
        return found
    if first is None:
        found["it drew at all"] = False
        found["share of the window lit when it gave up"] = share
        return found
    early = harness.photograph()
    found["as soon as anything was on screen"] = {
        "seconds": round(first, 2),
        "share of the window lit": lit_share(early),
        **_how_blocky(early),
        "which copies had been asked for": _which_copies_were_asked_for(
            list(harness.ledger.entries)
        ),
        "photograph": harness.save_frame(early, f"{name}-early"),
    }
    # And now let everything come to rest: wait for the server to go quiet, then
    # wait for the photograph itself to stop changing.
    seen, quiet_since = -1, time.perf_counter()
    while time.perf_counter() - started < LONGEST_WAIT_S:
        now = len(harness.ledger.entries)
        if now != seen:
            seen, quiet_since = now, time.perf_counter()
        elif time.perf_counter() - quiet_since > QUIET_S:
            break
        time.sleep(0.1)
    harness.settle(tries=25)
    rested = harness.photograph()
    found["once everything had come to rest"] = {
        "seconds": round(time.perf_counter() - started, 2),
        "share of the window lit": lit_share(rested),
        **_how_blocky(rested),
        "which copies had been asked for": _which_copies_were_asked_for(
            list(harness.ledger.entries)
        ),
        "photograph": harness.save_frame(rested, f"{name}-settled"),
    }
    found["which engine drew this"] = which_engine_is_drawing(harness)
    return found


def _the_middle_reading(taken: list[dict]) -> dict:
    """Several whole readings of one cell, reported as the middle one.

    Opening a viewer cold can only be done once to a page, so a repeat means a
    fresh page and a fresh reading of everything. What comes back is the reading
    whose time to the first specimen was in the middle, with the range across the
    readings kept beside it — the same habit as the drags above, and for the same
    reason: on this machine a single reading is not worth much on its own.
    """
    drew = [one for one in taken
            if one.get("seconds to the first specimen on screen") is not None]
    if not drew:
        return dict(taken[0])
    in_order = sorted(drew, key=lambda one: one["seconds to the first specimen on screen"])
    middle = dict(in_order[len(in_order) // 2])
    middle["seconds to the first specimen, lowest and highest seen"] = [
        in_order[0]["seconds to the first specimen on screen"],
        in_order[-1]["seconds to the first specimen on screen"],
    ]
    middle["how many whole readings were taken"] = len(taken)
    middle["readings where nothing was ever drawn"] = len(taken) - len(drew)
    return middle


def run_the_overlap_question(args, data_dir: Path) -> int:
    """The whole of the second question: overlapping sources against butted ones.

    Two conditions at each rung, from the very same picture files. In the control
    the positions sit exactly where the run wrote them, so neighbours butt up
    against one another and nothing is covered twice. In the other they are told
    they sit nine tenths of a position apart, so every neighbour overlaps by a
    tenth — and nothing else about them is changed, not one voxel.
    """
    everything = {
        "option": args.option,
        "measured": time.strftime("%Y-%m-%d %H:%M"),
        "window": dict(drive.WINDOW),
        "micrometres per screen pixel": ZOOM_UM_PER_PIXEL,
        "how far apart the overlapping positions were told they are": (
            f"{OVERLAPPING_STEP} of a position, so neighbours share "
            f"{round((1 - OVERLAPPING_STEP) * 100)} per cent of their width"
        ),
        "rungs": {},
    }
    said = {
        "channels": [
            {"name": "probe", "colour": [1, 1, 1], "window": {"low": 0, "high": 4095}}
        ]
    }
    out = args.out
    for rung in [int(one) for one in args.rungs.split(",") if one.strip()]:
        folder = data_dir / f"run-{rung}"
        if not folder.exists():
            print(f"writing the run of {rung} positions …", flush=True)
            write_a_run(folder, rung)
        view_store = folder / "overview.ome.zarr"
        butted = sorted(
            one for one in (view_store / POSITIONS_FOLDER).iterdir()
            if one.name.endswith(".ome.zarr")
        )
        overlapping = positions_that_overlap(
            butted, data_dir / f"overlapping-{rung}", rung
        )
        across, down = RASTERS[rung]
        conditions = {
            "butted up against one another (the control)": (
                butted,
                {"centre": {"x": across * POSITION_VOXELS * VOXEL_UM / 2,
                            "y": down * POSITION_VOXELS * VOXEL_UM / 2},
                 "zoom": ZOOM_UM_PER_PIXEL},
            ),
            "overlapping by a tenth": (
                overlapping,
                {"centre": {
                    "x": ((across - 1) * POSITION_VOXELS * OVERLAPPING_STEP
                          + POSITION_VOXELS) * VOXEL_UM / 2,
                    "y": ((down - 1) * POSITION_VOXELS * OVERLAPPING_STEP
                          + POSITION_VOXELS) * VOXEL_UM / 2},
                 "zoom": ZOOM_UM_PER_PIXEL},
            ),
        }
        everything["rungs"][rung] = {}
        print(f"\n{rung} positions", flush=True)
        with drive.Harness(data_dir, out / f"overlap-{rung}",
                           option=args.option) as harness:
            for shortly, (label, (stores, view)) in zip(
                ("butted", "overlapping"), conditions.items()
            ):
                print(f"  {label} …", flush=True)
                asked = [
                    {"url": (f"{harness.address}/data/"
                             f"{store.relative_to(data_dir).as_posix()}/|zarr2:"),
                     "name": store.name[: -len(".ome.zarr")], **said}
                    for store in stores
                ]
                try:
                    harness.open(store="square", draw="none")
                    found = the_overlap_question(
                        harness, acquisitions=asked, view=view,
                        name=f"{rung}-{shortly}",
                    )
                except Exception as went_wrong:
                    found = {
                        "could not be measured": str(went_wrong)[:2000],
                        "where": traceback.format_exc().splitlines()[-4:],
                    }
                    print(f"    could not be measured: {went_wrong}", flush=True)
                found["console"] = [
                    line for line in harness.console
                    if line.startswith(("error", "pageerror", "warning"))
                ][:20]
                everything["rungs"][rung][label] = found
                early = found.get("as soon as anything was on screen", {})
                rested = found.get("once everything had come to rest", {})
                print(
                    f"    early: lit {early.get('share of the window lit')}, "
                    f"sharp steps "
                    f"{early.get('share of neighbouring pixels with a sharp step between them')}"
                    f" | at rest: lit {rested.get('share of the window lit')}, "
                    f"sharp steps "
                    f"{rested.get('share of neighbouring pixels with a sharp step between them')}",
                    flush=True,
                )
                (out / "overlapping-sources.json").write_text(
                    json.dumps(everything, indent=2, default=str)
                )
    print(f"\nwritten to {out / 'overlapping-sources.json'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rungs", default="50,100,400,1000")
    parser.add_argument("--option", default="neuroglancer-under")
    parser.add_argument("--out", type=Path,
                        default=_HERE.parent / "measurements" / "many-sources")
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument(
        "--overlap", action="store_true",
        help="ask the other question instead: do overlapping sources come out as "
             "a patchwork, and does it survive everything coming to rest")
    parser.add_argument(
        "--also-grouped", action="store_true",
        help="measure a third arrangement: the same N stores handed over as one "
             "layer reading from many places, which is how the shipping viewer "
             "does it")
    parser.add_argument("--repeats", type=int, default=2,
                        help="how many whole readings of each cell to take")
    parser.add_argument("--keep", action="store_true",
                        help="do not write the runs again if they are already there")
    args = parser.parse_args()

    drive.require_a_browser()
    # Every request the server answers is counted, descriptions included. See this
    # module's notes: on this question the descriptions are most of the cost, and
    # leaving them out of the record would hide the very thing being measured.
    data_server._DESCRIBING_FILES = ()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    data_dir = args.data or (out / "acquisitions")
    data_dir.mkdir(parents=True, exist_ok=True)
    # A small ordinary store, so the harness page can open on something with a
    # coverage record before it is asked to open the run. It is the same page and
    # the same first steps for both arrangements, so whatever it costs, it costs
    # them equally.
    if not (data_dir / "square.ome.zarr").exists():
        acquisitions.write_the_square(data_dir).close()

    if args.overlap:
        return run_the_overlap_question(args, data_dir)

    rungs = [int(one) for one in args.rungs.split(",") if one.strip()]
    runs = {}
    for rung in rungs:
        folder = data_dir / f"run-{rung}"
        if folder.exists() and args.keep:
            view = folder / "overview.ome.zarr"
            stored = sorted(
                one for one in (view / POSITIONS_FOLDER).iterdir()
                if one.name.endswith(".ome.zarr")
            )
            print(f"keeping the run of {rung} positions already written", flush=True)
        else:
            if folder.exists():
                shutil.rmtree(folder)
            started = time.perf_counter()
            view, stored = write_a_run(folder, rung)
            print(f"wrote {rung} positions in "
                  f"{time.perf_counter() - started:.1f} s", flush=True)
        runs[rung] = (view, stored)

    everything: dict = {
        "option": args.option,
        "measured": time.strftime("%Y-%m-%d %H:%M"),
        "window": dict(drive.WINDOW),
        "one position is this many voxels across": POSITION_VOXELS,
        "one piece is this many voxels across": PIECE,
        "micrometres per screen pixel": ZOOM_UM_PER_PIXEL,
        "rungs": {},
    }
    for rung in rungs:
        view, stored = runs[rung]
        print(f"\n{rung} positions", flush=True)
        everything["rungs"][rung] = {}
        with drive.Harness(data_dir, out / f"{rung}", option=args.option) as harness:
            arrangements = the_two_arrangements(
                data_dir, harness.address, view, stored, rung,
                also_grouped=args.also_grouped,
            )
            for shortly, (label, asked) in zip(
                ("A", "B", "Bgrouped"), arrangements.items()
            ):
                taken = []
                for again in range(args.repeats):
                    print(f"  {label}, reading {again + 1} …", flush=True)
                    began = time.perf_counter()
                    try:
                        # A fresh page for every reading, so that neither
                        # arrangement is measured on an engine the other one — or
                        # an earlier reading — had already warmed.
                        harness.open(store="square", draw="none")
                        found = measure_one(
                            harness,
                            acquisitions=asked,
                            view=the_view_settings(rung),
                            photograph=f"{rung}-{shortly}-{again}",
                        )
                    except Exception as went_wrong:
                        found = {
                            "could not be measured": str(went_wrong)[:2000],
                            "where": traceback.format_exc().splitlines()[-4:],
                        }
                        print(f"    could not be measured: {went_wrong}", flush=True)
                    found["console"] = [
                        line for line in harness.console
                        if line.startswith(("error", "pageerror", "warning"))
                    ][:20]
                    taken.append(found)
                    print(f"    {time.perf_counter() - began:.1f} s: "
                          f"first pixel "
                          f"{found.get('seconds to the first specimen on screen')} s, "
                          f"lit {found.get('share of the window lit')}, "
                          f"requests "
                          f"{(found.get('one screenful of requests') or {}).get('requests in all')}, "
                          f"middle frame "
                          f"{(found.get('panning') or {}).get('middle frame (ms)')} ms",
                          flush=True)
                    (out / "many-sources.json").write_text(
                        json.dumps(
                            {**everything, "rungs": {
                                **everything["rungs"],
                                rung: {**everything["rungs"][rung],
                                       label: {"readings": taken}},
                            }}, indent=2, default=str)
                    )
                # A copy, not the reading itself. Where only one was taken, the
                # middle of them *is* that one reading, and putting the list of
                # readings inside it would make it hold itself — which reads
                # perfectly well until the results are written out, at which
                # point it cannot be, and the whole run is lost at the last step.
                found = dict(taken[0]) if len(taken) == 1 else _the_middle_reading(taken)
                found["readings"] = taken
                everything["rungs"][rung][label] = found
                (out / "many-sources.json").write_text(
                    json.dumps(everything, indent=2, default=str)
                )
    print(f"\nwritten to {out / 'many-sources.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
