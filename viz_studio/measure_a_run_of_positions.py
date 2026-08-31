"""How a run of positions draws, as the number of positions climbs.

This measures the arrangement :mod:`zmart_storage.positions` writes: one zarr per
run, the positions inside it each with their own zoomed-out copies, and a map in
the picture's description saying which piece of the picture is which piece of
which position. **The picture the viewer opens holds no full-size voxels of its
own** -- that is the claim the whole arrangement rests on, and it holds.

What does not hold, and used to be written here, is "nothing is copied at all".
A position keeps only as many zoomed-out copies as it can, which is as far as
halving it goes before a copy would be smaller than one piece: for the 512-voxel
positions and 128-voxel pieces below, three levels. The picture is deeper than
that as soon as the run is wide, and every level past the third has nothing to
point at, so it is written from the positions' pixels. Measured on the runs this
script writes::

    positions   picture levels 0-2   levels 3 and up          against the positions
          100   no files at all      25 chunks, 0.7 MB        54 MB
          400   no files at all      125 chunks, 3.4 MB       216 MB

So it is a small copy rather than none, it grows with the *area* of the run rather
than with its data, and it is the coarse end of the pyramid -- which is also why
zooming out far enough is drawn from copies rather than through the pointers. Say
"no full-size voxels", not "nothing".

The question it answers is the one the whole arrangement exists for. Neuroglancer
builds a drawing layer for every image it is handed, so a run given to it as a
folder of positions gets slower with every position and eventually does not open
at all. Handed a single picture it should not care what is underneath — and
"should not" is a claim, so here it is measured instead.

Run it like this, from the top of the repository::

    python viz_studio/measure_a_run_of_positions.py
    python viz_studio/measure_a_run_of_positions.py --steps 1,10,100,400

**Read the ``lit`` column before any of the others.** It says how much of the
screen actually had specimen on it. An empty panel redraws beautifully, so a frame
rate without it can look excellent and mean nothing — which is not a hypothetical:
the first run of this measurement reported a healthy thirty-five frames a second
with ``lit`` at nought, over a completely black screen. The picture was being
served correctly and drawn at about five per cent of its brightness. Every table
carries the column for that reason.

**And absolute numbers are worth nothing off the machine that made them.** A
sandbox with no graphics card draws in software and is slow whatever it is given.
What carries from one machine to another is the *shape*: whether the middle frame
holds steady as positions are added, and whether the requests stop climbing. If
your figures disagree with any quoted in the repository, yours are the real ones.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

_VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(_VIZ.parent))
sys.path.insert(0, str(_VIZ))
sys.path.insert(0, str(_VIZ / "backend"))
sys.path.insert(0, str(_VIZ / "tests"))

from measure_the_frame_rate_of_a_linked_view import (  # noqa: E402
    COUNT_FRAMES,
    EVERY_SOURCE_RESOLVED,
    HELD,
    KEEP_MOVING,
    SAMPLE_SECONDS,
    WATCH_THE_DRAWING,
    a_browser,
    another_browser,
    say_what_is_drawing,
    how_long_a_drawing_frame_took,
)
from pixels import fraction_lit  # noqa: E402
from server import make_server  # noqa: E402

from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.positions import start_a_run  # noqa: E402

# One position, and how its picture is cut up. Five hundred and twelve voxels
# across is small for a real camera and large enough that a position carries its
# own zoomed-out copies, which is the case worth measuring: with them the picture
# writes nothing at the three zoom levels a position can supply, and only from the
# fourth level up does it write anything of its own. See the note at the top for
# what that costs, measured.
TILE = (1, 512, 512)
PIECE = 128
VOXEL_UM = (2.0, 0.325, 0.325)

# How bright the specimen is asked to be shown. It sits well inside a sixteen-bit
# camera's range on purpose, because that gap is exactly what makes a picture open
# black when the window is not read from the store.
SHOWN_BETWEEN = (400, 3800)

STEPS = (1, 10, 50, 100, 200, 400)


def a_specimen(seed: int) -> np.ndarray:
    """One position's picture, with structure in it rather than flat noise.

    Structure matters here for two reasons. A flat block compresses to almost
    nothing, which would flatter every reading that involves fetching; and it gives
    ``lit`` nothing to be sure about, since a flat field either covers the screen
    or does not.
    """
    rng = np.random.default_rng(seed)
    _, y, x = np.indices(TILE, dtype=np.float32)
    picture = 600 + 60 * rng.standard_normal(TILE)
    for _ in range(30):
        at_y, at_x = rng.uniform(0, TILE[1]), rng.uniform(0, TILE[2])
        spread = rng.uniform(20, 70)
        near = ((y - at_y) ** 2 + (x - at_x) ** 2) / (2 * spread ** 2)
        picture = np.maximum(picture, rng.uniform(2200, 3900) * np.exp(-near))
    return picture.clip(0, 4000).astype("uint16")


def a_run_of(count: int, folder: Path) -> Path:
    """Write ``count`` positions as a squarish mosaic and hand back the picture.

    A mosaic rather than a row, and it matters more than it sounds. Laid out in a
    line, four hundred positions are a picture two hundred thousand voxels wide and
    five hundred tall — a hair on the screen. Almost nothing would be drawn, and
    the rate being measured would mostly be the cost of drawing an empty panel.
    """
    across = int(np.ceil(np.sqrt(count)))
    with start_a_run(
        folder, name="experiment",
        room=(TILE[0], across * TILE[1], across * TILE[2]),
        tile_shape=TILE, voxel_size_um=VOXEL_UM,
        channels=[Channel("488", window=SHOWN_BETWEEN)], piece=PIECE,
    ) as run:
        for index in range(count):
            run.write(a_specimen(index),
                      at=(0, (index // across) * TILE[1], (index % across) * TILE[2]))
        return run.path


def how_it_drew(browser, built: Path, folder: Path, store: str,
                save_to: Path | None = None, fit: bool = False,
                panel: tuple[int, int] = (900, 700),
                look_at: dict[str, float] | None = None,
                zoom: float = 1.0) -> dict:
    """Open the picture, wait until it has settled, then watch it draw.

    The waiting is measured separately rather than folded in. Counting frames while
    the picture is still arriving would measure the *opening*, which is a different
    question and, at these sizes, a much shorter one.
    """
    server = make_server(port=0, data_dir=folder, site_dir=built, store=store,
                         live=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": panel[0], "height": panel[1]})
    # Before anything is loaded, so the wrapping is in place when the page makes
    # its drawing context. Added after the page exists but before `goto`, which is
    # when the context is made.
    page.add_init_script(f"({WATCH_THE_DRAWING})()")

    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url))
    try:
        opened = _open_it_and_time_it(page, server.server_address[1])

        page.wait_for_timeout(2500)
        if fit:
            _show_the_whole_run(page, _how_wide_the_picture_is(folder, store))
        if look_at is not None:
            page.evaluate(LOOK_AT, [look_at, zoom])
            page.wait_for_timeout(2000)

        # What an operator would be looking at, taken once the picture has settled
        # and before anything starts moving it. Worth having beside the numbers:
        # the screen is the same size whatever the run holds, so a row of these
        # says more plainly than any column what "the viewer opened ten thousand
        # positions" does and does not mean.
        if save_to is not None:
            save_to.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(save_to))

        # Requests for picture rather than for the page itself. This is the number
        # that says whether the browser is fetching the run or fetching the screen:
        # it should climb while the picture is smaller than the window and then
        # stop, however many positions are added afterwards.
        for_the_picture = len([one for one in asked if "/data/" in one])

        page.evaluate(KEEP_MOVING)
        page.evaluate(COUNT_FRAMES)
        page.evaluate(
            "() => { window.__drawn = 0; window.__at = []; window.__gl_at = []; }"
        )
        page.wait_for_timeout(int(SAMPLE_SECONDS * 1000))
        # Read in one visit, and copied there rather than here. Asked for one at a
        # time, a frame lands between two of the questions and the answers come
        # back describing different moments -- 349 frame times against 350 drawing
        # counts, which is what the guard in `how_long_a_drawing_frame_took` caught
        # the first time this ran.
        counted = page.evaluate(
            "() => ({drawn: window.__drawn, at: window.__at.slice(), "
            "gl: window.__gl_at.slice()})"
        )
        drawn = int(counted["drawn"])
        at = [float(n) for n in counted["at"]]
        gl_at = [int(n) for n in counted["gl"]]
        page.evaluate("() => clearInterval(window.__nudge)")
        # How many pictures the viewer is holding. Recorded rather than merely
        # waited on: one image however many positions are underneath is the whole
        # mechanism, and a table that does not say so leaves it unevidenced.
        held = int(page.evaluate(HELD))
        # Beside it rather than instead of it, so older tables still read: `held`
        # is the declared count and these say how much of it arrived.
        loaded = page.evaluate(WHAT_LOADED)

        # The *middle* frame says the rate the viewer is really holding; the
        # *worst* says the longest an operator ever watched the picture sit still,
        # which is what makes a viewer feel broken even when the average looks
        # respectable.
        gaps = sorted(later - earlier for earlier, later in zip(at, at[1:]))
        return {
            "lit": fraction_lit(page),
            "opened": opened,
            "requests": for_the_picture,
            "held": held,
            "loaded": int(loaded["loaded"]),
            "failed": int(loaded["failed"]),
            "pending": int(loaded["pending"]),
            **how_long_a_drawing_frame_took(at, gl_at),
            "fps": drawn / SAMPLE_SECONDS,
            # The time a frame really took, over the whole sample. Kept beside the
            # middle gap rather than instead of it because the two disagree the
            # moment the browser stops pacing itself: uncapped it draws in bursts,
            # so the middle gap falls to about a millisecond while a frame is
            # still taking nine. This is the one to charge a per-position cost
            # against; see `what_one_more_position_costs`.
            "mean_ms": SAMPLE_SECONDS * 1000 / drawn if drawn else 0.0,
            "usual_ms": gaps[len(gaps) // 2] if gaps else 0.0,
            "worst_ms": gaps[-1] if gaps else 0.0,
        }
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _show_the_whole_run(page, across: int) -> None:
    """Zoom out until the entire run is on the screen, and wait for it to arrive.

    Without this the viewer opens at one voxel to the pixel, which shows a panel's
    worth of picture and no more -- about four positions, whether the run holds ten
    or ten thousand. That is the right thing to measure for the fault this began
    with, where a layer was built per position whether or not it was in view. It is
    the wrong thing to show somebody who asks what opening a plate looks like, and
    it makes every row from two hundred upwards the same picture.

    Be careful reading what comes back. Only the first three levels are pointed at
    the positions' own files; the coarser ones were written from their pixels. A
    run wide enough to need a coarser level to fit on the screen is therefore drawn
    here from copies, not through the pointers -- so this says what an operator
    sees, and says nothing about whether the pointing works.
    """
    page.evaluate(
        """(across) => {
             const view = window.zmartViewer;
             const canvas = view.display.canvas;
             const room = Math.min(canvas.width, canvas.height);
             view.navigationState.zoomFactor.value = (across / room) * 1.1;
           }""",
        across,
    )
    page.wait_for_function("() => window.zmartSourcesWaiting() === 0", timeout=300_000)
    page.wait_for_timeout(2000)


# Where the view is looking and how far in, set rather than left to chance.
#
# **The camera is otherwise a race, and two rows of a table need not be looking at
# the same thing.** Neuroglancer centres the view once, from whichever source
# resolved first, and never recentres; the zoom is reset the same way. That is
# harmless when every source declares the same bounds, and it is not harmless when
# each carries its own placement -- a run served as one picture and the same run
# served as many placed sources then start from different corners, and the opening
# time carries that difference for reasons that have nothing to do with how many
# positions there are. Anything comparing two arrangements has to pin both.
LOOK_AT = """([centre, zoom]) => {
  const view = window.zmartViewer;
  const names = view.navigationState.coordinateSpace.value.names;
  const position = view.navigationState.position.value;
  for (const [axis, at] of Object.entries(centre)) {
    const index = names.indexOf(axis);
    if (index >= 0) position[index] = at;
  }
  view.navigationState.position.changed.dispatch();
  view.navigationState.zoomFactor.value = zoom;
}"""

# What the layer really holds, as against what it declares.
#
# `HELD` counts `dataSources.length`, and a source is pushed into that list
# synchronously, before it has resolved -- one that fails stays there forever with
# an error on it and is still counted. So "a hundred registered" is not something
# `held` can say. These four are separable and honest: `pending` says the picture
# is not finished arriving, and `failed` says it never will.
WHAT_LOADED = """() => {
  const layers = window.zmartViewer.layerManager.managedLayers
    .filter((managed) => managed.layer && managed.layer.type === 'image');
  const sources = layers.flatMap((managed) => managed.layer.dataSources);
  return {
    declared: sources.length,
    loaded: sources.filter((s) => s.loadState && !s.loadState.error).length,
    failed: sources.filter((s) => s.loadState && s.loadState.error).length,
    pending: sources.filter((s) => !s.loadState).length,
  };
}"""


def _how_wide_the_picture_is(folder: Path, store: str) -> int:
    """How many voxels across the run is, read from what it says about itself."""
    described = json.loads((folder / store / "0" / "zarr.json").read_text())
    return int(described["shape"][-1])




def _open_it_and_time_it(page, port: int) -> float:
    """Point a page at the run and wait until it has everything, in seconds.

    Waiting on the engine rather than on the page's own loading, because a page that
    has loaded has drawn nothing: `zmartViewer` existing says the viewer was made,
    holding a picture says the run was opened, nothing left waiting says every source
    has been handed to the engine -- and every source carrying a `loadState` says
    they were actually read, which is the one that makes this an opening time.
    """
    began = time.time()
    page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
    page.wait_for_function(f"{HELD} >= 1", timeout=300_000)
    page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                           timeout=300_000)
    page.wait_for_function(EVERY_SOURCE_RESOLVED, timeout=600_000)
    return time.time() - began


def _refuse_a_browser_that_is_not_cold(browser) -> None:
    """Stop a cold opening being measured in a browser that has already opened one.

    The failure this guards is silent rather than loud. Handed the ladder's own
    browser, a cold opening still returns a number, the number still looks
    reasonable, and it is the warm reading under a colder name -- the two differ
    by about forty milliseconds, well inside what either varies by between runs.
    A browser that has opened something has a context to show for it.
    """
    if browser.contexts:
        raise ValueError(
            f"this browser has already opened {len(browser.contexts)} thing(s), so "
            "an opening measured in it would be a warm one wearing a cold name. A "
            "cold opening must be the first thing its browser ever does; launch a "
            "further browser with `another_browser` rather than passing the one "
            "the ladder is using."
        )


def how_long_a_cold_open_takes(started, built: Path, folder: Path,
                               store: str, headed: bool = False) -> float:
    """The same open, in a browser that has never seen this page before.

    The ladder measures every step through **one** browser, so only its first row
    pays for compiling the viewer's code and its drawing programs; every row after
    that is an open into a warmed browser. That is the right thing to measure
    beside the frames, and the wrong thing to quote to an operator, who opens a run
    by starting the application.

    So this launches a browser of its own, uses it once and closes it. What it
    cannot make cold is the disk: Windows offers no supported way to drop the file
    cache, so the pieces this morning's writing left in memory are still there.
    That bounds what this measures rather than spoiling it -- only about forty
    pieces of picture are ever fetched, however large the run, while the map saying
    which piece is which grows with every position. The part that scales is the
    part that is honestly measured here.
    """
    server = make_server(port=0, data_dir=folder, site_dir=built, store=store,
                         live=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    browser = another_browser(started, headed)
    _refuse_a_browser_that_is_not_cold(browser)
    page = browser.new_page(viewport={"width": 900, "height": 700})
    try:
        return _open_it_and_time_it(page, server.server_address[1])
    finally:
        page.close()
        browser.close()
        server.shutdown()
        thread.join(timeout=5)


def runs_already_written(folder: Path) -> dict[int, Path]:
    """Which sizes a kept ladder holds, and where each one's picture is.

    Found by looking rather than by reading a list written down beside them,
    because the case that matters is a ladder whose writing was interrupted.

    A step is offered only if it holds **exactly** as many positions as its name
    promises. Checking that the picture opens is not enough, and the difference is
    the whole point of counting: a run's description is written before its
    positions are, so a step killed halfway leaves a picture that opens perfectly
    and holds some fraction of what it claims. Measuring that gives a row labelled
    five thousand positions over however many were finished — a wrong number
    rather than a missing one, which nothing downstream could catch.
    """
    found: dict[int, Path] = {}
    if not folder.is_dir():
        return found
    for step in folder.iterdir():
        if not step.is_dir() or not step.name.startswith("n"):
            continue
        count = step.name[1:]
        if not count.isdigit():
            continue
        picture = step / "experiment.ome.zarr"
        if not ((picture / "zarr.json").is_file()
                or (picture / ".zattrs").is_file()):
            continue
        inside = picture / "positions"
        if not inside.is_dir():
            continue
        written = sum(1 for one in inside.iterdir()
                      if one.is_dir() and one.name.endswith(".ome.zarr"))
        if written == int(count):
            found[int(count)] = picture
    return found


def what_one_more_position_costs(rows: list[dict]) -> dict[int, float | None]:
    """What each row's positions cost a frame, in microseconds per position.

    The frame rate says whether the viewer is usable; this says whether the
    arrangement's central claim holds. They are different questions, and only one
    of them survives a fast machine: a rate is bounded above by the browser's own
    clock, so every size reads the same number once that ceiling is reached and
    the table stops being able to say anything. A per-position cost is a slope
    instead of a level. It is nought when a position costs the frame nothing,
    however quick or slow the machine drawing it is.

    Charged against ``drawing_ms``, the middle frame **among those in which the
    picture was actually redrawn**. Not against the frame rate, and not against
    the mean frame: both include the frames in which the browser offered a moment
    and the page drew nothing in it, which cost 17.3 milliseconds here against a
    real frame's 0.8. The quantity being measured then sits inside a constant
    twenty times its size, and a page drawing nothing at all still scores 57.7
    frames a second. A run of ten thousand positions and a run of one are
    indistinguishable in that average whatever the drawing costs, which is exactly
    what the first two versions of this reported.

    A row that drew nothing is charged nothing rather than nought. It says the
    measurement did not happen, and nought would put it at the top of the table.

    Each row is charged against the **smallest** run measured rather than against
    the row before it, so that every figure answers for itself. Charged against
    its neighbour, a cost that only appears above some size would be smeared
    across the steps on either side of where it started.

    A negative figure is passed through as it was measured. It means a later row
    drew quicker than the smallest one, which says the spread between repeats is
    wider than the effect being looked for — worth seeing, and hidden by rounding
    it up to nought.
    """
    if len(rows) < 2:
        return {row["positions"]: None for row in rows}
    fewest = min(rows, key=lambda row: row["positions"])
    costs: dict[int, float | None] = {}
    for row in rows:
        added = row["positions"] - fewest["positions"]
        drew = row["drawing_ms"] is not None and fewest["drawing_ms"] is not None
        if added <= 0 or not drew:
            costs[row["positions"]] = None
            continue
        costs[row["positions"]] = (
            (row["drawing_ms"] - fewest["drawing_ms"]) * 1000 / added
        )
    return costs


def _how_big(folder: Path) -> tuple[int, int]:
    """How many bytes the picture and the positions take, in that order."""
    picture = folder / "experiment.ome.zarr"
    inside = picture / "positions"
    positions = sum(one.stat().st_size for one in inside.rglob("*") if one.is_file())
    everything = sum(one.stat().st_size for one in picture.rglob("*") if one.is_file())
    return everything - positions, positions


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument(
        "--steps", type=str, default=None,
        help="position counts to climb through, comma separated "
             f"(default {','.join(str(n) for n in STEPS)})",
    )
    parsing.add_argument(
        "--keep", action="store_true",
        help="leave the runs on disk afterwards instead of deleting them",
    )
    parsing.add_argument(
        "--headed", action="store_true",
        help="open a real window instead of a headless browser. On Windows this "
             "is the only way the graphics card is used at all; headless reports "
             "SwiftShader whatever it is asked for. A window will appear, and "
             "touching it disturbs the measurement",
    )
    parsing.add_argument(
        "--panel", type=str, default="900x700",
        help="how large a window to draw into, as WxH. Four times the pixels "
             "should cost about four times the drawing, which is how this "
             "measurement can be shown to notice work at all",
    )
    parsing.add_argument(
        "--fit", action="store_true",
        help="zoom out until the whole run is on the screen before measuring, "
             "instead of the panelful the viewer opens with",
    )
    parsing.add_argument(
        "--pictures", type=str, default=None,
        help="save what the viewer showed at each step, as a png a step, into "
             "this folder",
    )
    parsing.add_argument(
        "--cold", action="store_true",
        help="also open each run in a browser of its own, so the opening is not "
             "measured into a browser the previous step warmed up; costs a "
             "browser launch a step",
    )
    parsing.add_argument(
        "--from", dest="reuse", type=str, default=None,
        help="measure a ladder left by an earlier --keep instead of writing one; "
             "any size missing from it is written, and the folder is never deleted",
    )
    asked = parsing.parse_args()
    steps = sorted(int(n) for n in (asked.steps.split(",") if asked.steps
                                    else [str(n) for n in STEPS]))

    built = _VIZ / "frontend" / "dist"
    if not (built / "index.html").is_file():
        raise SystemExit(
            f"the viewer page has not been built ({built} holds no index.html), so "
            "there is nothing for a browser to open. Build it with:\n"
            "  npm --prefix viz_studio/frontend install\n"
            "  npm --prefix viz_studio/frontend run build"
        )

    panel = tuple(int(n) for n in asked.panel.lower().split('x'))
    ours = asked.reuse is None
    work = Path(tempfile.mkdtemp(prefix="a-run-of-positions-")) if ours \
        else Path(asked.reuse)
    already = runs_already_written(work)
    if already:
        print(f"measuring the ladder in {work} again; "
              f"{len(already)} of {len(steps)} sizes are already written")

    started, browser = a_browser(asked.headed)
    drawn_by = say_what_is_drawing(browser)
    rows = []
    try:
        for count in steps:
            folder = work / f"n{count}"
            if count in already:
                picture, written = already[count], None
            else:
                writing = time.time()
                picture = a_run_of(count, folder)
                written = time.time() - writing
            # Cold first, and in that order deliberately: opening it warm first
            # would leave the browser, the server and the file cache warmed by the
            # very thing the cold reading is supposed to be innocent of.
            cold = how_long_a_cold_open_takes(started, built, folder, picture.name,
                                              headed=asked.headed) \
                if asked.cold else None
            shown = Path(asked.pictures) / f"n{count}.png" if asked.pictures \
                else None
            drew = how_it_drew(browser, built, folder, picture.name, save_to=shown,
                               fit=asked.fit, panel=panel)
            small, large = _how_big(folder)
            drew.update(positions=count, cold_opened=cold,
                        picture_bytes=small, position_bytes=large)
            rows.append(drew)
            how = "already written" if written is None \
                else f"written in {written:>5.0f}s"
            print(f"  {count:>5} positions {how}   "
                  f"lit {drew['lit']:.3f}  fps {drew['fps']:.1f}", flush=True)
    finally:
        browser.close()
        started.stop()
        # A folder we were handed is never deleted, whatever --keep says. Writing
        # the ladder is nearly all of what this costs, so throwing away somebody
        # else's copy of it is the one mistake here that is expensive to undo.
        if ours and not asked.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"\nthe runs are in {work} — measure them again with "
                  f"--from {work}")

    costs = what_one_more_position_costs(rows)
    print()
    # The three questions this exists to answer come first -- what it costs to
    # open a run that has not been opened, what a frame costs while working in it,
    # and what one further position adds to that frame. Everything after `held` is
    # there to say whether those three can be believed, and is read second.
    print("| positions | cold opening | drawing frame | one more | held | lit | "
          "drawing frames | idle frame | fps | warm opening | requests | "
          "the picture | the positions |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        cost = costs[row["positions"]]
        drew = row["drawing_ms"]
        idle = row["idle_ms"]
        cold = row["cold_opened"]
        print(f"| {row['positions']} | "
              f"{'not asked for' if cold is None else f'{cold:.2f} s'} | "
              f"{'never drew' if drew is None else f'{drew:.2f} ms'} | "
              f"{'-' if cost is None else f'{cost:.4f} us'} | "
              f"{row['held']} | {row['lit']:.3f} | "
              f"{row['drawing_frames']} | "
              f"{'-' if idle is None else f'{idle:.1f} ms'} | "
              f"{row['fps']:.1f} | "
              f"{row['opened']:.2f} s | {row['requests']} | "
              f"{row['picture_bytes'] / 1e6:.1f} MB | "
              f"{row['position_bytes'] / 1e6:.0f} MB |")
    print()
    print("The drawing frame holding steady as positions are added is the whole "
          "claim; the picture staying small beside the positions is the other "
          "half of it. Check 'lit' is well above nought on every row before "
          "believing any of the rest.")
    print("'one more' is what each row's positions cost a frame, in microseconds "
          "a position, charged against the smallest run measured.")
    print(f"Drawn by: {drawn_by}. Figures from software drawing compare with "
          "other machines; figures from a card describe this one.")
    print("It is charged against the drawing frame: the middle frame among those "
          "in which the picture was really redrawn. 'fps' and the idle frame are "
          "printed beside it as context and must not be read as cost. Counting "
          "every frame the browser offers measures the browser: a page drawing "
          "nothing at all scores about 58 a second, because an idle frame is "
          "served on schedule and costs nothing.")
    print("Read 'one more' against the spread of the drawing-frame column across "
          "repeats — a per-position cost smaller than that spread has been "
          "bounded rather than measured. And check 'held' is 1 on every row: one "
          "image however many positions are underneath is the mechanism the whole "
          "claim rests on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
