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
  can be read on its own.

Run it with::

    python viz_studio/options/measure/many_sources.py --rungs 50,100,400,1000

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
        # in a `.zattrs` beside the picture. That is the spelling the address the
        # page hands over asks for, and the one the harness's server knows how to
        # repair units in.
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
    _spell_the_units_the_way_the_engine_wants(folder)
    _make_the_pointed_at_pieces_real(view, folder, positions)
    return view, stored


def _spell_the_units_the_way_the_engine_wants(folder: Path) -> None:
    """Rewrite "micrometer" as "um" in every description under this folder.

    The writer spells the unit out in full, which is correct, and the drawing
    engine refuses anything but the short form. The harness's server normally
    repairs that as it hands a description over — but only for the files it
    treats as descriptions, and this measurement needs those files counted like
    any other. Repairing them on disk instead means the server can be asked to
    count everything without also being asked to stop repairing anything.
    """
    for described in folder.rglob(".zattrs"):
        text = described.read_text(encoding="utf-8")
        if "micrometer" in text:
            described.write_text(text.replace("micrometer", "um"), encoding="utf-8")


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


def measure_one(harness, *, label: str, acquisitions: list[dict], view: dict,
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
    found["panning"] = _panning(harness, f"{photograph}-panning")
    return found


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
                         positions: list[Path], rung: int) -> dict:
    """The acquisition lists for arrangement A and arrangement B.

    Both are addresses into the same files. The channels are stated by the page in
    both cases and stated identically, so that neither arrangement is charged for
    reading a description the other did not have to read.
    """
    said = {
        "channels": [
            {"name": "probe", "colour": [1, 1, 1], "window": {"low": 0, "high": 4095}}
        ]
    }

    def address_of(store: Path) -> str:
        return f"{address}/data/{store.relative_to(data_dir).as_posix()}/|zarr2:"

    return {
        "A — one store": [
            {"url": address_of(view), "name": "overview", **said}
        ],
        f"B — {len(positions)} stores": [
            {"url": address_of(store), "name": store.name[: -len(".ome.zarr")], **said}
            for store in positions
        ],
    }


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rungs", default="50,100,400,1000")
    parser.add_argument("--option", default="neuroglancer-under")
    parser.add_argument("--out", type=Path,
                        default=_HERE.parent / "measurements" / "many-sources")
    parser.add_argument("--data", type=Path, default=None)
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
        _spell_the_units_the_way_the_engine_wants(data_dir / "square.ome.zarr")

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
                data_dir, harness.address, view, stored, rung
            )
            for label, asked in arrangements.items():
                print(f"  {label} …", flush=True)
                began = time.perf_counter()
                try:
                    # A fresh page for every cell, so that neither arrangement is
                    # measured on an engine another one had already warmed.
                    harness.open(store="square", draw="none")
                    found = measure_one(
                        harness,
                        label=label,
                        acquisitions=asked,
                        view=the_view_settings(rung),
                        photograph=f"{rung}-{label.split()[0]}",
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
                print(f"    {time.perf_counter() - began:.1f} s: "
                      f"first pixel "
                      f"{found.get('seconds to the first specimen on screen')} s, "
                      f"lit {found.get('share of the window lit')}, "
                      f"requests "
                      f"{(found.get('one screenful of requests') or {}).get('requests in all')}",
                      flush=True)
                (out / "many-sources.json").write_text(
                    json.dumps(everything, indent=2, default=str)
                )
    print(f"\nwritten to {out / 'many-sources.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
