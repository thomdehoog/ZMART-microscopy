"""Does showing a run as one picture keep the viewer's drawing rate up?

What this is asking
-------------------

``viz_studio/tests/test_the_drawing_keeps_up.py`` records the fault this measures
against, and it is the worst one the project has found. With a thousand positions
open the viewer managed **24 frames in five seconds** where a hundred positions
managed 302. Three drawing layers are made for every position and each one takes
part in every frame, so the cost is paid on every draw for as long as the run is
open. Slow *loading* ends; this does not. `NEXT_STEPS.md` calls the fix
architectural: the engine has to be holding fewer positions.

A linked view — :mod:`zmart_storage.linked` — hands the viewer **one** store no
matter how many tiles are underneath it. If the cost really is paid per position,
then a run shown that way should keep its drawing rate whatever its size, and the
architectural fix is a thing that already exists.

That is a claim about how the viewer builds its layers, and until this script was
written nobody had measured it. So this measures it: the *same* tiles, opened both
ways, frames counted in a real browser.

How it goes about it
--------------------

It climbs. One tile, then a few, then more, and it prints each row as soon as that
row is done — so a run that is taking too long can be stopped at any point and
everything measured so far is already on screen. Before starting a step it works
out roughly what that step will cost from what the last one actually cost, and
stops rather than begin one that would run past the time allowed. A measurement
that has to be babysat does not get run.

**Everything here is a comparison, never an absolute number.** A machine with no
graphics card draws slowly whatever it is given, so "so many frames per second"
would mean nothing and would need retuning for every machine. What is reported is
how the two arrangements compare *on the machine you are sitting at*, which holds
anywhere.

Running it
----------

::

    python viz_studio/measure_the_frame_rate_of_a_linked_view.py
    python viz_studio/measure_the_frame_rate_of_a_linked_view.py --budget 900
    python viz_studio/measure_the_frame_rate_of_a_linked_view.py --steps 1,5,20,50

It needs the viewer page to have been built (``npm --prefix viz_studio/frontend run
build``) and a Chromium it can drive. It writes tiny tiles into a temporary folder
and removes them afterwards.
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

_VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(_VIZ / "backend"))
sys.path.insert(0, str(_VIZ / "tests"))
sys.path.insert(0, str(_VIZ.parent))

from server import make_server  # noqa: E402

from zmart_storage.canvas import Channel, _declare_one  # noqa: E402
from zmart_storage.linked import PlacedTile, link_the_tiles  # noqa: E402

# Deliberately tiny. What is being measured is the cost of *how many* things are
# open, not how much picture there is, and small tiles keep the writing quick
# enough that the climb can reach interesting numbers.
TILE = (1, 64, 64)
PIECE = 64
VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (11.0, 5.5, 7.25)

# What the test picture is made of. A pattern rather than one flat value, so that
# it does not compress away to nothing and draw unrealistically fast — and bright,
# spanning most of what a sixteen-bit number can hold.
#
# The brightness matters more than it looks. An earlier version drew the same
# pattern between 400 and 800, which is perfectly good specimen but reaches the
# screen at about one per cent of full brightness once it is spread across the
# whole sixteen-bit range. The picture was there and drawing, and the check that
# asks "was anything actually drawn" reported an empty panel — so every rate in
# the table was dismissed as measured on nothing. Painting near the top of the
# range removes the ambiguity: if the panel comes out dark now, something is
# genuinely wrong rather than merely dim.
MID = 32000
SWING = 15000

# How long to count frames for, at each size, for each arrangement. Long enough to
# average over a slow patch, short enough that the climb stays affordable.
SAMPLE_SECONDS = 3.0

# How far to climb unless told otherwise. Each step is a few times the one before,
# because the fault being looked for shows up as an *order of magnitude* rather
# than a few per cent.
STEPS = (1, 5, 20, 100, 400, 1600, 6400)

# Turning off the frame-rate ceiling, whichever renderer draws.
#
# `requestAnimationFrame` fires at the display's own rhythm unless told otherwise,
# so a machine quick enough to reach it draws every size at exactly sixty frames a
# second and a climb reads flat for the one reason that does not mean the claim
# holds — nothing was allowed to get slower. Measured on this repository's sandbox
# at 23 to 36 frames a second, so the cap was never reached there and none of the
# figures already written down move because of this. On the machine this was found
# on, every row of a run from one position to two thousand read 60.0 to 60.3.
UNCAPPED = ["--disable-gpu-vsync", "--disable-frame-rate-limit"]

# How the browser is launched: the machine's own graphics card, if it has one.
#
# **This used to force software drawing and no longer does**, which changes what
# every number here means. `--use-gl=angle --use-angle=swiftshader` made the
# engine draw on the CPU, so that a machine with a card and one without would
# report comparable figures — right for a regression guard, and wrong for telling
# an operator what their own machine does. On 6 August 2026 a whole afternoon of
# frame figures was quoted as "this machine" when every one of them described a
# CPU rasteriser: the same box reports `NVIDIA T400 4GB … D3D11` unforced and
# `SwiftShader driver` forced.
#
# Anything already written down in this repository was measured in software and
# does not compare with what this now produces. `SOFTWARE_ARGS` reproduces the old
# behaviour when a comparison with those figures is what is wanted.
BROWSER_ARGS = ["--ignore-gpu-blocklist", *UNCAPPED]

# The fallback, and the way back to the old figures.
#
# Chromium falls back to SwiftShader on its own where a card cannot be used, so
# this is needed only when the browser will not give WebGL at all, and when
# somebody deliberately wants the software numbers.
SOFTWARE_ARGS = ["--use-gl=angle", "--use-angle=swiftshader",
                 "--ignore-gpu-blocklist", *UNCAPPED]

# Renderer names that mean the picture was drawn on the processor. Matched
# loosely and in lower case, because each driver writes its name its own way and
# buries it inside a longer string.
SOFTWARE_RENDERERS = ("swiftshader", "llvmpipe", "software", "microsoft basic")

# Asking the browser what actually drew. Kept beside the arguments because the
# two belong together: asking for a card is not the same as getting one.
WHAT_IS_DRAWING = """() => {
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
  if (!gl) return 'no webgl at all';
  const named = gl.getExtension('WEBGL_debug_renderer_info');
  return named ? gl.getParameter(named.UNMASKED_RENDERER_WEBGL) : '(masked)';
}"""


def is_drawn_in_software(renderer: str) -> bool:
    """Whether this renderer name is one of the processor's rather than a card's.

    A name that will not say — some browsers mask it — is **not** reported as
    software. Saying so would be a guess dressed as a measurement, and would send
    somebody looking for a fault on a machine that has a perfectly good card. The
    name itself is printed either way, so a reader can see the question went
    unanswered.
    """
    lowered = (renderer or "").lower()
    return any(one in lowered for one in SOFTWARE_RENDERERS)


def what_drew(browser) -> str:
    """The renderer this browser really got, asked rather than assumed."""
    page = browser.new_page()
    try:
        page.goto("about:blank")
        return str(page.evaluate(WHAT_IS_DRAWING))
    finally:
        page.close()


def say_what_is_drawing(browser) -> str:
    """Print which renderer drew, and hand it back for a table to carry.

    Printed on every run without being asked for. A measurement that quietly fell
    back to software looks exactly like one that did not, and the two differ by
    more than tenfold — so the fallback has to announce itself or it is a trap
    rather than a kindness.
    """
    renderer = what_drew(browser)
    how = "IN SOFTWARE" if is_drawn_in_software(renderer) else "on the card"
    print(f"drawing {how}: {renderer}", flush=True)
    if is_drawn_in_software(renderer):
        print("  (figures from software drawing say nothing about how this "
              "machine performs; they are for comparison with other machines)",
              flush=True)
    return renderer

# Watching for drawing itself, rather than for the browser offering a moment in
# which drawing could have happened.
#
# This must be installed before the page makes its drawing context, so it is added
# as an init script rather than evaluated after loading. It counts calls to every
# way WebGL can be asked to draw; the count is read once a frame and only the
# change matters, so the wrapping costs an increment per call.
#
# Why it exists: counting frames alone measures the browser's own clock. A page
# drawing nothing at all still reports about 58 frames a second, because an idle
# `requestAnimationFrame` callback is offered on schedule and costs nothing to
# serve. Measured on 6 August 2026 with the view-nudging turned off: zero draw
# calls in three seconds, 57.7 frames a second reported.
WATCH_THE_DRAWING = """() => {
  window.__gl = 0;
  const count = (which) => {
    for (const context of [window.WebGLRenderingContext,
                           window.WebGL2RenderingContext]) {
      if (!context || !context.prototype[which]) continue;
      const was = context.prototype[which];
      context.prototype[which] = function (...given) {
        window.__gl += 1;
        return was.apply(this, given);
      };
    }
  };
  for (const which of ["drawArrays", "drawElements", "drawArraysInstanced",
                       "drawElementsInstanced", "drawRangeElements"]) {
    count(which);
  }
}"""

# Counting frames the way the browser really draws them. Started once and only
# once: two loops would both count and read as the page having doubled its rate.
#
# `__gl_at` records how much drawing had been done by each frame, so that a frame
# in which the picture was redrawn can afterwards be told from one in which the
# browser merely offered the chance. Without `WATCH_THE_DRAWING` installed the
# count stays at nought and every frame reads as idle, which is the honest answer
# to "how long did a drawing frame take" when nothing was watching.
COUNT_FRAMES = """() => {
  if (window.__counting) return;
  window.__counting = true;
  window.__drawn = 0;
  window.__at = [];
  window.__gl_at = [];
  const tick = (now) => {
    window.__drawn += 1;
    window.__at.push(now);
    window.__gl_at.push(window.__gl || 0);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}"""

# Keep the view moving while frames are counted. A page with nothing to redraw is
# not being asked the question: the cost being looked for is paid per frame, so
# there have to be frames.
KEEP_MOVING = """() => {
  if (window.__nudging) return;
  window.__nudging = true;
  let forward = true;
  window.__nudge = setInterval(() => {
    const nav = window.zmartViewer.navigationState;
    const at = Float32Array.from(nav.position.value);
    at[at.length - 1] += forward ? 0.5 : -0.5;
    forward = !forward;
    nav.position.value = at;
  }, 16);
}"""

# How many pictures the viewer has been *given*. Counted from the engine rather than
# from what we asked for -- but **not** how many of them loaded, which this comment
# used to claim. A source is pushed into `dataSources` synchronously, before it has
# resolved, and one that fails stays in the list for ever with an error on it and is
# still counted here. Read it as an upper bound, and use `EVERY_SOURCE_RESOLVED`
# below to know whether it means anything yet.
HELD = """() => window.zmartViewer.layerManager.managedLayers
           .filter((managed) => managed.layer && managed.layer.type === 'image')
           .reduce((total, managed) => total + managed.layer.dataSources.length, 0)"""

# Every source has resolved -- succeeded or failed -- rather than merely been handed
# over.
#
# **`zmartSourcesWaiting()` reaching nought does not mean the run is open.** It counts
# the URLs the page has still to pass to the engine, so it empties when the last one
# has been handed over and not when it has been read. Measured on a ladder of
# positions it returned with **thirty of a hundred** resolved and **three hundred of
# four hundred**, and an opening timed against it read 3.64 s where the truth was
# 8.96. Anything that waits on it alone is looking at a page that is still filling in
# -- which for a measurement is an optimistic number, and for a test is an assertion
# about a picture that has not arrived.
#
# A source carries a `loadState` once it has resolved and once it has failed, so
# waiting for all of them to have one is the honest condition. Pair it with the wait
# on `zmartSourcesWaiting()`: that one says the list is complete, this one says the
# list was read.
EVERY_SOURCE_RESOLVED = """() => {
  const sources = window.zmartViewer.layerManager.managedLayers
    .filter((managed) => managed.layer && managed.layer.type === 'image')
    .flatMap((managed) => managed.layer.dataSources);
  return sources.length > 0 && sources.every((s) => s.loadState !== undefined);
}"""


def how_long_a_drawing_frame_took(at: list[float], drawn_by: list[int]) -> dict:
    """Split frames into the ones that drew the picture and the ones that idled.

    Args:
        at: when each frame was offered, in milliseconds.
        drawn_by: how many drawing calls the page had made by that frame.

    Returns:
        ``drawing_ms``, the middle interval among those in which the picture was
        actually redrawn; ``idle_ms``, the middle interval among the rest; and
        ``drawing_frames``, how many of the intervals drew anything.

    The two populations are far apart -- about 0.8 milliseconds against 17.3 on
    the machine this was written for -- so averaging across both, which is what
    counting frames does, buries the quantity being measured inside a constant
    twenty times larger. That is why a run of ten thousand positions and a run of
    one read the same: they are the same in that average whatever drawing costs.

    ``drawing_ms`` is ``None`` when nothing was drawn at all. Reporting nought
    there would make a page that drew nothing look like the quickest result on the
    table, which is exactly the way this measurement has been fooled before.
    """
    if len(at) != len(drawn_by):
        raise ValueError(
            f"{len(at)} frame times against {len(drawn_by)} drawing counts; they "
            "are read from the same page and must line up, so a mismatch means "
            "the page was read wrongly rather than that it behaved oddly"
        )
    drew, idled = [], []
    for earlier, later, before, after in zip(at, at[1:], drawn_by, drawn_by[1:]):
        (drew if after > before else idled).append(later - earlier)
    middle = lambda gaps: sorted(gaps)[len(gaps) // 2] if gaps else None
    return {
        "drawing_ms": middle(drew),
        "idle_ms": middle(idled),
        "drawing_frames": len(drew),
    }


def a_grid_of_tiles(folder: Path, count: int) -> list[PlacedTile]:
    """Write ``count`` tiles laid out as a mosaic, roughly square.

    **A square-ish grid rather than a row, and it matters more than it sounds.** An
    earlier version of this laid every tile in one line, which at eight hundred
    tiles is a picture fifty thousand voxels wide and sixty-four tall — a hair on
    the screen. Almost nothing was drawn, so the rate being measured was mostly the
    cost of drawing an empty panel, which flatters whichever arrangement is being
    asked to draw the least. A mosaic fills the view the way a real acquisition
    does, so the drawing being counted is drawing of the specimen.

    Tiles butt up against one another and each lands on a whole piece boundary, so
    the picture can always be pointed at.
    """
    folder.mkdir(parents=True, exist_ok=True)
    across = max(1, math.ceil(math.sqrt(count)))
    placed = []
    for index in range(count):
        lands_y = (index // across) * TILE[1]
        lands_x = (index % across) * TILE[2]
        store = folder / f"tile{index:05d}.ome.zarr"
        arrays = _declare_one(
            store,
            canvas_shape=TILE,
            frames=1,
            channels=1,
            dtype="uint16",
            chunk=PIECE,
            levels=1,
            voxel_size_um=VOXEL_UM,
            origin_um=(ORIGIN_UM[0],
                       ORIGIN_UM[1] + lands_y * VOXEL_UM[1],
                       ORIGIN_UM[2] + lands_x * VOXEL_UM[2]),
            channel_blocks=[Channel("488", window=(0, 65535)).described(65535)],
        )
        # Something with structure in it, so the picture is not one flat value
        # that compresses to nothing and draws unrealistically fast. The
        # brightness window above is set to suit these numbers: with a window of
        # nought to four thousand the same picture draws at about a tenth
        # brightness, which reads as an empty panel to anything checking whether
        # a specimen was drawn at all.
        y, x = np.indices(TILE[1:], dtype=np.float32)
        picture = (
            MID + SWING * np.sin((y + lands_y) / 7) + SWING * np.cos((x + lands_x) / 9)
        ).astype("uint16")
        arrays[0][0, 0] = np.broadcast_to(picture, TILE)
        placed.append(PlacedTile(store=store, lands_at=(0, lands_y, lands_x)))
    return placed


def how_it_drew(browser, built_dist: Path, folder: Path, store, expect: int) -> dict:
    """Open what ``store`` names, wait until it is all there, then watch it draw.

    Waiting matters, and it is measured separately rather than folded in. Counting
    frames while stores are still arriving would measure the *loading*, which is a
    different question — and, at these sizes, the one that takes all the time.

    Returns how long the opening took, and then what the drawing looked like once
    it had settled: how many frames, how often they came, and — the number that
    says how it *feels* — the longest the picture ever sat still.
    """
    server = make_server(
        port=0, data_dir=folder, site_dir=built_dist, store=store, live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})
    try:
        opening = time.time()
        page.goto(
            f"http://127.0.0.1:{server.server_address[1]}",
            wait_until="domcontentloaded",
        )
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(f"{HELD} >= {expect}", timeout=300_000)
        page.wait_for_function(
            "() => window.zmartSourcesWaiting() === 0", timeout=300_000
        )
        page.wait_for_function(EVERY_SOURCE_RESOLVED, timeout=600_000)
        opened = time.time() - opening

        page.wait_for_timeout(3000)
        page.evaluate(KEEP_MOVING)
        page.evaluate(COUNT_FRAMES)
        page.evaluate("() => { window.__drawn = 0; window.__at = []; }")
        page.wait_for_timeout(int(SAMPLE_SECONDS * 1000))
        drawn = int(page.evaluate("() => window.__drawn"))
        at = [float(n) for n in page.evaluate("() => window.__at")]
        page.evaluate("() => clearInterval(window.__nudge)")

        # How long each frame took, in milliseconds. The *middle* of these says the
        # rate the viewer is really holding; the *largest* says the worst pause an
        # operator would feel, which is what makes a viewer feel broken even when
        # the average looks respectable.
        gaps = sorted(later - earlier for earlier, later in zip(at, at[1:]))
        middle = gaps[len(gaps) // 2] if gaps else 0.0
        worst = gaps[-1] if gaps else 0.0
        # How much of the screen actually has specimen on it. Without this the
        # whole measurement can be flattered by drawing nothing: an empty panel
        # redraws beautifully. It is reported on every row so that a suspiciously
        # good rate can always be checked against whether there was a picture.
        from pixels import fraction_lit
        return {
            "lit": fraction_lit(page),
            "opened": opened,
            "frames": drawn,
            "per_second": drawn / SAMPLE_SECONDS,
            "usual_ms": middle,
            "worst_ms": worst,
        }
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def frames_counted(browser, built_dist: Path, folder: Path, store, expect: int) -> int:
    """Just the number of frames, for callers that want only the comparison."""
    return how_it_drew(browser, built_dist, folder, store, expect)["frames"]


def a_browser(headed: bool = False):
    """A headless Chromium drawing in software and uncapped, or why there is none.

    Software drawing is needed because the engine wants WebGL2 and most machines
    running this have no graphics card. Uncapped because a frame rate measured
    against the display's rhythm cannot be climbed past it; see ``BROWSER_ARGS``.
    A machine whose policy blocks the browser that was downloaded is offered the
    one it already has.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "playwright is not installed, so no browser could be driven. "
            "Install it with `pip install playwright`."
        )
    started = sync_playwright().start()
    try:
        return started, another_browser(started, headed)
    except SystemExit:
        started.stop()
        raise


def another_browser(started, headed: bool = False):
    """A further browser from a driver that is already running.

    Two drivers cannot run at once -- the synchronous playwright API refuses to be
    started inside its own event loop -- so anything wanting a second browser, as
    a cold opening does, has to launch it from the driver already there. The
    browser itself is a new process either way, which is what makes it cold.

    The card is asked for first and software is the fallback, taken only when the
    browser gives no WebGL at all. Chromium falls back to SwiftShader by itself on
    a machine whose card cannot be used, so this second attempt is for the case
    where even that did not happen -- and when it is taken, it is said out loud by
    whoever reports the renderer, because a silent fallback is indistinguishable
    from a card and worth more than tenfold in the figures.
    """
    launched = _launched_with(started, BROWSER_ARGS, headed)
    if what_drew(launched) == "no webgl at all":
        launched.close()
        launched = _launched_with(started, SOFTWARE_ARGS, headed)
    return launched


def _launched_with(started, args, headed: bool = False):
    """A browser with these arguments, or the Chromium the machine already has.

    ``headed`` opens a real window, and on this machine it is the **only** way to
    reach the graphics card: measured on 6 August 2026, a headless Chromium
    reports SwiftShader whatever arguments it is given, while the same browser
    with a window reports `NVIDIA T400 4GB … D3D11`. Removing the software flags
    was therefore necessary and not sufficient, and the run said so itself only
    because it had been made to announce its renderer.

    The cost is that a window opens on somebody's desk and anything typed into it
    disturbs the measurement, so it stays off by default.
    """
    try:
        return started.chromium.launch(headless=not headed, args=list(args))
    except Exception:
        from conftest import find_a_chromium
        already_here = find_a_chromium()
        if already_here is None:
            raise SystemExit(
                "no Chromium on this machine that could be driven, so frames "
                "cannot be counted here."
            )
        return started.chromium.launch(
            executable_path=str(already_here), headless=not headed,
            args=list(args)
        )


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument(
        "--budget", type=float, default=1800.0,
        help="how many seconds to spend in total before stopping (default 1800)",
    )
    parsing.add_argument(
        "--steps", type=str, default=None,
        help="tile counts to climb through, comma separated",
    )
    parsing.add_argument(
        "--headed", action="store_true",
        help="open a visible window, which on Windows is the only way the "
             "browser reaches the graphics card — headless Chromium draws in "
             "SwiftShader whatever arguments it is given",
    )
    asked = parsing.parse_args()
    steps = sorted(
        int(n) for n in (asked.steps.split(",") if asked.steps else
                         [str(n) for n in STEPS])
    )

    built = _VIZ / "frontend" / "dist"
    if not (built / "index.html").is_file():
        raise SystemExit(
            f"the viewer page has not been built ({built} holds no index.html), so "
            "there is nothing for a browser to open. Build it with:\n"
            "  npm --prefix viz_studio/frontend install\n"
            "  npm --prefix viz_studio/frontend run build"
        )

    started, browser = a_browser(asked.headed)
    say_what_is_drawing(browser)
    work = Path(tempfile.mkdtemp(prefix="frame-rate-"))
    began = time.time()

    # Written once, at the largest size, and every step points at the first so many
    # of them. Rewriting the tiles for every step was most of what an earlier
    # version of this spent its time on, and it measured nothing.
    print(f"\nWriting {steps[-1]} tiles once, to be shared by every step...")
    writing = time.time()
    folder = work / "tiles"
    every = a_grid_of_tiles(folder, steps[-1])
    print(f"  written in {time.time() - writing:.0f}s")

    print()
    print("How one picture draws, however many tiles are under it. 'usual' is the")
    print("middle frame, 'worst' the longest the picture ever sat still, 'lit' how")
    print("much of the screen had specimen on it — a rate measured on an empty")
    print("panel would mean nothing, so it is reported alongside.")
    print()
    print(f"{'tiles':>6}  {'fps':>6}  {'usual':>7}  {'worst':>7}  {'open':>5}  "
          f"{'lit':>5}  {'linking':>8}")
    print("-" * 56)

    took_last, last_count = 0.0, 0
    try:
        for count in steps:
            spent = time.time() - began
            likely = took_last * (count / last_count) if last_count else 60.0
            if spent + likely > asked.budget:
                print(f"\nStopping before {count} tiles: it would likely take "
                      f"{likely:.0f}s and only {asked.budget - spent:.0f}s is left. "
                      "Everything above is measured.")
                break

            step_began = time.time()
            linking = time.time()
            reaches = tuple(
                max(one.lands_at[axis] + TILE[axis] for one in every[:count])
                for axis in range(3)
            )
            link_the_tiles(
                folder, name="linked", tiles=every[:count],
                view_shape=reaches, discard_existing_run=True,
                # Only the full-size picture, which is the one made of pointers.
                # The smaller copies are genuinely written and cost a read of every
                # tile to build, and leaving them out both makes the climb
                # affordable and means what is drawn here is the pointed-at picture
                # rather than a copy of it.
                levels=1,
            )
            linked_in = time.time() - linking

            try:
                one = how_it_drew(browser, built, folder, "linked.ome.zarr", 1)
            except Exception as why:
                print(f"{count:>6}  did not finish: {type(why).__name__}")
                took_last, last_count = time.time() - step_began, count
                continue

            took_last, last_count = time.time() - step_began, count
            warn = "  <- nearly blank, so this rate means little" if one["lit"] < 0.1 else ""
            print(f"{count:>6}  {one['per_second']:>6.1f}  {one['usual_ms']:>5.0f}ms  "
                  f"{one['worst_ms']:>5.0f}ms  {one['opened']:>4.0f}s  "
                  f"{one['lit']:>5.2f}  {linked_in:>7.0f}s{warn}")
    except KeyboardInterrupt:
        print("\nStopped. Everything above is measured.")
    finally:
        browser.close()
        started.stop()
        shutil.rmtree(work, ignore_errors=True)

    print()
    print("One picture is one store however many tiles are under it, so the rate")
    print("should hardly move down the table. 'linking' is the cost of building the")
    print("view, paid once when a run is opened, not on every frame.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
